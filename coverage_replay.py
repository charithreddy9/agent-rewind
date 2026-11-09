"""Compare one-test rewind ranking with historical Black baseline coverage."""

import argparse
import ast
from difflib import SequenceMatcher
from fractions import Fraction
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from behavior_replay import REPLAYS, source_snapshots
from gate_benchmark import diff_identifiers, identifiers
from rewind import git, preview_rewind


TEST_FILE = "tests/test_black.py"
TEST_CLASS = "BlackTestCase"
POOL_LIMIT = 35


def run_pool(repo: Path, revision: str, target: str, contents: str,
             version_path: str, version_contents: str, trace: bool) -> dict:
    with TemporaryDirectory(prefix="rewind-coverage-") as directory:
        root = Path(directory)
        archive = git(repo, "archive", "--format=tar", revision)
        with tarfile.open(fileobj=BytesIO(archive), mode="r:") as source:
            source.extractall(root, filter="data")
        (root / target).write_bytes(contents.encode())
        version_file = root / version_path
        if not version_file.exists():
            version_file.write_text(version_contents, encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(root / "src"),
               "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", target]
        if trace:
            command.append("--trace")
        run = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=90)
        result = root / "pool-results.json"
        if not result.exists() or run.returncode not in (0, 1):
            raise RuntimeError(f"Pool could not run (exit {run.returncode})\n{run.stdout}\n{run.stderr}")
        return json.loads(result.read_text(encoding="utf-8"))


def worker(target: str, trace: bool) -> int:
    import pytest

    filename = str(Path(target).resolve())
    records = {}

    class Pool:
        def pytest_collection_modifyitems(self, config, items):
            items.sort(key=lambda item: (item.location[1], item.nodeid))
            config.hook.pytest_deselected(items=items[POOL_LIMIT:])
            del items[POOL_LIMIT:]

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_call(self, item):
            lines = set()

            def on_line(frame, event, arg):
                if event == "line":
                    lines.add(frame.f_lineno)
                return on_line

            def on_call(frame, event, arg):
                return on_line if frame.f_code.co_filename == filename else None

            previous = sys.gettrace()
            if trace:
                sys.settrace(on_call)
            try:
                yield
            finally:
                if trace:
                    sys.settrace(previous)
            records[item.nodeid]["lines"] = sorted(lines)

        def pytest_runtest_logreport(self, report):
            record = records.setdefault(report.nodeid, {"phases": {}, "lines": []})
            record["phases"][report.when] = report.outcome
            if report.failed:
                record["failure"] = str(report.longrepr)

    # Historical Black uses os.cpu_count() to size its process pool.
    with patch("os.cpu_count", return_value=2):
        status = pytest.main(["-q", "--disable-warnings", f"{TEST_FILE}::{TEST_CLASS}"], plugins=[Pool()])
    Path("pool-results.json").write_text(json.dumps(records), encoding="utf-8")
    return int(status)


def replay(repo: Path) -> dict:
    revert, target, version_path, version_contents, _ = REPLAYS["black"]
    before, after, current, _ = source_snapshots(repo, "black", revert, target)
    candidate = preview_rewind(before, after, current)
    if candidate.has_conflicts or candidate.text == current:
        raise ValueError("Expected the historical single-file candidate to merge cleanly")
    revision = revert + "^"
    started = perf_counter()
    baseline = run_pool(repo, revision, target, current, version_path, version_contents, trace=True)
    baseline_seconds = perf_counter() - started
    eligible = sorted(node for node, run in baseline.items()
                      if run["phases"] == {"setup": "passed", "call": "passed", "teardown": "passed"})
    if not eligible:
        raise ValueError("No baseline-passing tests")
    source = git(repo, "show", f"{revision}:{TEST_FILE}").decode()
    test_class = next(node for node in ast.parse(source).body
                      if isinstance(node, ast.ClassDef) and node.name == TEST_CLASS)
    test_bodies = {node.name: ast.get_source_segment(source, node) for node in test_class.body
                   if isinstance(node, ast.FunctionDef)}
    old, new = current.splitlines(), candidate.text.splitlines()
    changed_lines = {line for operation, start, stop, _, _ in
                     SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
                     if operation != "equal" for line in range(start + 1, stop + 1)}
    terms = diff_identifiers(current, candidate.text, 0)
    scores = {}
    for node in eligible:
        name = node.rsplit("::", 1)[-1].split("[", 1)[0]
        scores[node] = {
            "lexical": len(terms & identifiers(test_bodies.get(name, ""))),
            "coverage": len(changed_lines.intersection(baseline[node]["lines"])),
        }
    # Resolve all ties by node ID, before running the candidate.
    selected = {"fixed": eligible[0]}
    for method in ("lexical", "coverage"):
        selected[method] = max(eligible, key=lambda node: scores[node][method])

    proposed = run_pool(repo, revision, target, candidate.text, version_path, version_contents, trace=False)
    if baseline.keys() != proposed.keys():
        raise ValueError("Collected nodes changed between versions")
    regressions = [node for node in eligible if proposed[node]["phases"].get("call") == "failed"]
    other = [node for node in eligible if node not in regressions
             and proposed[node]["phases"] != baseline[node]["phases"]]
    return {
        "revert": revert, "pool": f"{TEST_FILE}::{TEST_CLASS}", "pool_limit": POOL_LIMIT,
        "collected": len(baseline), "baseline_wall_seconds": baseline_seconds,
        "eligible": len(eligible), "regressions": regressions, "other_candidate_outcomes": other,
        "uniform_random_detection_probability": str(Fraction(len(regressions), len(eligible))),
        "selected": {method: {"node": node, "scores": scores[node], "detected": node in regressions}
                     for method, node in selected.items()},
        "scores": scores, "baseline": baseline, "candidate": proposed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clone", type=Path, nargs="?")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--trace", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker, args.trace)
    if args.clone is None:
        parser.error("provide the full Black clone")
    print(json.dumps(replay(args.clone), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
