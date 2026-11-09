"""Freeze the coverage evaluation cohort without building or testing candidates."""

import argparse
import json
from pathlib import Path, PurePosixPath
import re

from external_history import cases
from rewind import git


PROJECTS = {
    "attrs": ("python-attrs/attrs", "9d9f94a043de7fc4012459853a4ed597a5577855", ("src/attr/", "src/attrs/", "attr/")),
    "packaging": ("pypa/packaging", "713d0d78924ab2686c513dde058ce6aafc63e766", ("src/packaging/", "packaging/")),
    "pluggy": ("pytest-dev/pluggy", "30b8ae208f5955125f2a2edcb038c03893774b49", ("src/pluggy/", "pluggy/")),
    "scrapy": ("scrapy/scrapy", "1bc0473909e4e5a3d0b62710715b6383c5641765", ("scrapy/",)),
    "sphinx": ("sphinx-doc/sphinx", "035a07c32c3241fd3356f4d827800c1f88525272", ("sphinx/",)),
    "urllib3": ("urllib3/urllib3", "c5347bbd39203d68d7b0e3ffb83ced3e3b4b9109", ("src/urllib3/", "urllib3/")),
    "werkzeug": ("pallets/werkzeug", "5f11cd39b40ac03296ab7db446bfb0a737d77590", ("src/werkzeug/", "werkzeug/")),
}


def choose_test_files(repo: Path, revision: str, target: str) -> list[str]:
    path = PurePosixPath(target)
    name = path.parent.name if path.stem == "__init__" else path.stem
    terms = set(re.findall(r"[a-z0-9]+", name.lower()))
    candidates = []
    tree = git(repo, "ls-tree", "-rz", "--name-only", revision)
    for raw in tree.split(b"\0"):
        if not raw:
            continue
        filename = raw.decode("utf-8")
        test = PurePosixPath(filename)
        if (test.parts[0] not in {"test", "tests"} or not test.match("test_*.py")
                or {"roots", "fixtures", "data"} & set(test.parts[1:-1])):
            continue
        stem = test.stem.removeprefix("test_")
        overlap = len(terms.intersection(re.findall(r"[a-z0-9]+", stem.lower())))
        candidates.append((-(stem.lower().strip("_") == name.lower().strip("_")), -overlap, filename))
    matching = [item for item in candidates if item[0] < 0 or item[1] < 0]
    return [filename for _, _, filename in sorted(matching or candidates)[:3]]


def make_plan(clones: Path) -> dict:
    projects = []
    for name, (upstream, head, prefixes) in PROJECTS.items():
        repo = clones / name
        by_revert = {}
        for revert, raw_path, intervening, _ in cases(repo, head):
            path = raw_path.decode("utf-8")
            if path.startswith(prefixes) and path.endswith(".py") and not (
                {"test", "tests", "testsuite"} & set(PurePosixPath(path).parts)
            ):
                by_revert.setdefault(revert, []).append((path, intervening))
        planned = []
        for revert, paths in by_revert.items():
            changed_later = sorted(path for path, intervening in paths if intervening)
            targets = changed_later or [min(path for path, _ in paths)]
            for target in targets:
                planned.append({
                    "revert": revert, "target": target,
                    "stratum": "intervening" if changed_later else "control",
                    "test_files": choose_test_files(repo, revert + "^", target),
                })
        projects.append({"project": name, "upstream": upstream, "snapshot": head,
                         "cases": planned})
    return {"protocol_version": 1, "test_budget": 1, "max_nodes_per_case": 35,
            "timeout_seconds_per_phase": 120, "projects": projects}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clones", type=Path, help="Directory containing the seven full clones")
    args = parser.parse_args()
    print(json.dumps(make_plan(args.clones), indent=2))


if __name__ == "__main__":
    main()
