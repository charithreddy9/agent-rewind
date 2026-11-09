"""Run targeted upstream tests against three versions of a single source file."""

import argparse
from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory

from external_history import EXPANDED_SNAPSHOTS, cases
from rewind import git, preview_rewind


REPLAYS = {
    "pytest": (
        "6a47389c7813ec7ed395c0279c4b7685fde9f95a",
        "src/_pytest/unittest.py",
        "src/_pytest/_version.py",
        "version = '9.0.0.dev0'\nversion_tuple = (9, 0, 0, 'dev0')\n",
        (
            "testing/test_unittest.py::test_skip_setup_class",
            "testing/test_unittest.py::test_unittest_skip_function",
        ),
    ),
    "black": (
        "773e4a22d58be1f1aa82df7ad9a0f4c4e1328c10",
        "src/black/__init__.py",
        "src/_black_version.py",
        "version = '0+replay'\n",
        (
            "tests/test_black.py::BlackTestCase::test_numeric_literals",
            "tests/test_black.py::BlackTestCase::test_numeric_literals_ignoring_underscores",
        ),
    ),
}


def replay(repo: Path, project: str) -> dict[str, int]:
    revert, target, version_path, version_contents, tests = REPLAYS[project]
    before, after, current, expected = next(
        snapshots for commit, path, intervening, snapshots
        in cases(repo, EXPANDED_SNAPSHOTS[project])
        if commit == revert and path == target.encode() and intervening
    )
    candidate = preview_rewind(before, after, current)
    if candidate.has_conflicts or candidate.text == expected:
        raise ValueError(f"{project} is no longer a clean, different candidate")
    archive = git(repo, "archive", "--format=tar", revert)
    statuses = {}
    for variant, contents in (
        ("maintainer", expected), ("candidate", candidate.text), ("pre-revert", current)
    ):
        # Fresh extraction keeps test-generated files out of the other variants.
        with TemporaryDirectory(prefix=f"rewind-{project}-") as directory:
            root = Path(directory)
            with tarfile.open(fileobj=BytesIO(archive), mode="r:") as source:
                source.extractall(root, filter="data")
            path = root / target
            if path.read_bytes() != expected.encode():
                raise ValueError(f"Archived file does not match the reference: {target}")
            path.write_bytes(contents.encode())
            # Git archives omit the version modules normally generated at build time.
            version_file = root / version_path
            if not version_file.exists():
                version_file.write_text(version_contents, encoding="utf-8")
            env = {**os.environ, "PYTHONPATH": str(root / "src"),
                   "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
            print(f"\n{project} / {variant}", flush=True)
            result = subprocess.run(
                [sys.executable, "-B", "-m", "pytest", "-q", "--disable-warnings", *tests],
                cwd=root, env=env,
            )
            statuses[variant] = result.returncode
    return statuses


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clones", type=Path, help="Directory containing full pytest and black clones")
    args = parser.parse_args()
    try:
        results = {project: replay(args.clones / project, project) for project in REPLAYS}
    except (OSError, RuntimeError, ValueError, StopIteration) as exc:
        parser.error(f"Could not prepare the pinned replay: {exc}")
    print("\nUpstream pytest exit codes (0 passed, 1 tests failed, other codes indicate runner problems):")
    for project, statuses in results.items():
        print(f"{project}: {statuses}")
    return int(any(statuses["maintainer"] != 0 or any(code not in (0, 1) for code in statuses.values())
                   for statuses in results.values()))


if __name__ == "__main__":
    sys.exit(main())
