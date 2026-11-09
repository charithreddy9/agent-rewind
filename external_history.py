"""Compare rewind candidates with maintainers' recorded external reverts."""

import argparse
from collections import Counter
from pathlib import Path
import re

from benchmark import full_restore, skip_edited
from rewind import git, preview_rewind


SNAPSHOTS = {
    "requests": "3c7baaa05ab4aa49cc819ce3a819d260de19c157",
    "flask": "49943b5a94413a530761350f04e896f76e8d620e",
    "click": "8abb77a8432e03ed14a95f972b44f905279415a7",
}
REVERT_MARKER = re.compile(rb"^This reverts commit ([0-9a-f]{40})\b", re.MULTILINE)


def modified_regular_files(repo: Path, commit: str) -> dict[bytes, tuple[str, str]]:
    fields = git(repo, "diff", "--raw", "-z", "--no-abbrev", "--no-renames",
                 "--no-ext-diff", "--diff-filter=M", commit + "^", commit, "--").split(b"\0")
    files = {}
    for header, path in zip(fields[0:-1:2], fields[1:-1:2]):
        old_mode, new_mode, old_blob, new_blob, _ = header.decode("ascii").split()
        if old_mode[1:] == new_mode and new_mode in {"100644", "100755"}:
            files[path] = (old_blob, new_blob)
    return files


def is_single_parent(repo: Path, commit: str) -> bool:
    return len(git(repo, "rev-list", "--ignore-missing", "--parents", "-n", "1", commit).split()) == 2


def cases(repo: Path, head: str):
    if git(repo, "rev-parse", "--is-shallow-repository").strip() == b"true":
        raise ValueError(f"{repo.name} is a shallow clone")
    reverts = git(repo, "log", "--first-parent", "--format=%H", "-n", "12",
                  "--grep=^This reverts commit", head).decode("ascii").splitlines()
    for revert in reverts:
        targets = REVERT_MARKER.findall(git(repo, "show", "-s", "--format=%B", revert))
        if len(targets) != 1 or not is_single_parent(repo, revert):
            continue
        target = targets[0].decode("ascii")
        if not is_single_parent(repo, target):
            continue
        if git(repo, "rev-list", "-n", "1", target, "--not", revert + "^"):
            continue
        original = modified_regular_files(repo, target)
        restored = modified_regular_files(repo, revert)
        for path in sorted(original.keys() & restored.keys()):
            blobs = original[path] + restored[path]
            contents = [git(repo, "cat-file", "blob", blob) for blob in blobs]
            if any(b"\0" in data for data in contents):
                continue
            try:
                snapshots = tuple(data.decode("utf-8") for data in contents)
            except UnicodeDecodeError:
                continue
            yield revert, path, blobs[1] != blobs[2], snapshots


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clones", type=Path, help="Directory containing full requests, flask, and click clones")
    args = parser.parse_args()
    strategies = (full_restore, skip_edited, preview_rewind)
    totals = Counter()
    print("Repository / revert / file | intervening edit | full / skip / selective")
    try:
        for name, head in SNAPSHOTS.items():
            for revert, path, intervening, (before, after, current, expected) in cases(args.clones / name, head):
                outcomes = []
                for strategy in strategies:
                    result = strategy(before, after, current)
                    status = ("review" if result.has_conflicts else
                              "exact" if result.text == expected else "different")
                    totals[(intervening, strategy.__name__, status)] += 1
                    outcomes.append(status)
                print(f"{name}/{revert[:8]}/{path.decode('utf-8', errors='backslashreplace')} | "
                      f"{'yes' if intervening else 'no'} | {' / '.join(outcomes)}")
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(f"Could not read the pinned histories: {exc}")
    for intervening in (True, False):
        print(f"Intervening file edit: {'yes' if intervening else 'no'}")
        for strategy in strategies:
            counts = ", ".join(f"{status}={totals[intervening, strategy.__name__, status]}"
                               for status in ("exact", "different", "review"))
            print(f"  {strategy.__name__}: {counts}")


if __name__ == "__main__":
    main()
