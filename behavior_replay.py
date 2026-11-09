"""Run targeted upstream tests against three versions of a single source file."""

import argparse
import json
from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory

from check_gate import check_rewind
from external_history import EXPANDED_SNAPSHOTS, REVERT_MARKER, cases
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


def source_snapshots(repo: Path, project: str, revert: str, target: str):
    return next(
        snapshots for commit, path, intervening, snapshots
        in cases(repo, EXPANDED_SNAPSHOTS[project])
        if commit == revert and path == target.encode() and intervening
    )


def replay(repo: Path, project: str) -> dict[str, int]:
    revert, target, version_path, version_contents, tests = REPLAYS[project]
    before, after, current, expected = source_snapshots(repo, project, revert, target)
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


def replay_gate(repo: Path, project: str) -> dict:
    revert, target, version_path, version_contents, tests = REPLAYS[project]
    before, after, current, _ = source_snapshots(repo, project, revert, target)
    candidate = preview_rewind(before, after, current)
    if candidate.has_conflicts:
        raise ValueError(f"{project} unexpectedly needs textual review")
    # Resolve src inside each gate copy, including for pytester child processes.
    bootstrap = (
        "import os, sys; "
        "src = os.path.abspath('src'); "
        "os.environ.update(PYTHONPATH=src, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'); "
        "sys.path.insert(0, src); "
        "import pytest; raise SystemExit(pytest.main(sys.argv[1:]))"
    )
    command = [sys.executable, "-B", "-c", bootstrap, "-q", "--disable-warnings", *tests]
    target_commit, = REVERT_MARKER.findall(git(repo, "show", "-s", "--format=%B", revert))
    with TemporaryDirectory(prefix=f"rewind-gate-{project}-") as directory:
        root = Path(directory).resolve()
        # A disposable checkout gives the CLI the actual history and file set.
        git(root, "clone", "--quiet", "--shared", "--no-checkout", "--template=", str(repo.resolve()), ".")
        git(root, "-c", "core.autocrlf=false", "checkout", "--quiet", "--detach", revert + "^")
        version_file = root / version_path
        if not version_file.exists():
            version_file.write_text(version_contents, encoding="utf-8")
            git(root, "add", "-f", "--", version_path)

        target_ref = target_commit.decode("ascii")
        batch = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve().with_name("rewind.py")),
             "--all", "--json", "--before-ref", target_ref + "^", "--after-ref", target_ref,
             "--check", *command],
            cwd=root, capture_output=True, text=True,
        )
        if not batch.stdout:
            raise RuntimeError(batch.stderr.strip() or "Batch preview produced no report")
        report = json.loads(batch.stdout)
        isolated = check_rewind(root, git(root, "ls-files", "-z", "--cached"),
                                {target: (current, candidate.text)}, command)
        return {"batch_exit_code": batch.returncode, "batch_summary": report["summary"],
                "batch_gate": report["test_gate"], "single_file_gate": isolated}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clones", type=Path, help="Directory containing full pytest and black clones")
    parser.add_argument("--gate", action="store_true",
                        help="Exercise the batch and single-file gates from the pre-revert tree")
    args = parser.parse_args()
    try:
        if args.gate:
            print(json.dumps({project: replay_gate(args.clones / project, project)
                              for project in REPLAYS}, indent=2))
            return 0
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
