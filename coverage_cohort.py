"""Run the frozen single-file coverage-ranking evaluation."""

import argparse
from collections import Counter
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

from coverage_replay import worker
from external_history import cases
from gate_benchmark import diff_identifiers, identifiers
from rewind import git, preview_rewind


MANIFEST = Path(__file__).with_name("coverage_cohort_plan.json")
PASS = dict.fromkeys(("setup", "call", "teardown"), "passed")


def run_phase(archive: bytes, target: str, contents: str, selectors: list[str],
              limit: int, timeout: int, trace: bool = False) -> dict:
    with TemporaryDirectory(prefix="rewind-coverage-cohort-") as directory:
        root = Path(directory).resolve()
        with tarfile.open(fileobj=BytesIO(archive), mode="r:") as source:
            source.extractall(root, filter="data")
        path = root / target
        if not path.is_file() or path.resolve() != path:
            raise ValueError(f"Expected a regular source file at {target}")
        path.write_bytes(contents.encode())
        command = [sys.executable, "-B", str(Path(__file__).resolve()),
                   "--worker", target, str(limit), "trace" if trace else "plain", *selectors]
        env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root))),
               "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONHASHSEED": "0"}
        started = perf_counter()
        try:
            result = subprocess.run(command, cwd=root, env=env, capture_output=True,
                                    encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "seconds": perf_counter() - started}
        report = {"seconds": perf_counter() - started, "exit_code": result.returncode}
        output = root / "pool-results.json"
        if result.returncode not in (0, 1) or not output.exists():
            return {**report, "status": "missing_tests" if result.returncode == 5 else "setup_error",
                    "output": (result.stdout + result.stderr)[-12000:]}
        return {**report, "status": "ran", "tests": json.loads(output.read_text(encoding="utf-8"))}


def rank(current: str, proposed: str, eligible: dict) -> tuple[dict, dict, dict]:
    started = perf_counter()
    terms = diff_identifiers(current, proposed, 0)
    lexical = {node: len(terms & identifiers(run.get("source", "")))
               for node, run in eligible.items()}
    lexical_pick = max(eligible, key=lexical.__getitem__)
    lexical_seconds = perf_counter() - started

    started = perf_counter()
    old, new = current.splitlines(), proposed.splitlines()
    changed = {line for operation, start, stop, _, _ in
               SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
               if operation != "equal" for line in range(start + 1, stop + 1)}
    coverage = {node: len(changed.intersection(run["lines"])) for node, run in eligible.items()}
    coverage_pick = max(eligible, key=coverage.__getitem__)
    coverage_seconds = perf_counter() - started
    return (
        {"fixed": next(iter(eligible)), "lexical": lexical_pick, "coverage": coverage_pick},
        {"lexical": lexical_seconds, "coverage": coverage_seconds},
        {node: {"lexical": lexical[node], "coverage": coverage[node]} for node in eligible},
    )


def evaluate(repo: Path, snapshot: str, case: dict, limit: int, timeout: int) -> dict:
    target, revert = case["target"], case["revert"]
    record = {"project": repo.name, **case}
    try:
        before, after, current, _ = next(
            contents for commit, path, _, contents in cases(repo, snapshot)
            if commit == revert and path == target.encode()
        )
        candidate = preview_rewind(before, after, current)
        if candidate.has_conflicts:
            return {**record, "status": "conflict"}
        if candidate.text == current:
            return {**record, "status": "unchanged"}
        if not case["test_files"]:
            return {**record, "status": "missing_tests"}
        archive = git(repo, "archive", "--format=tar", revert + "^")
        baseline = run_phase(archive, target, current, case["test_files"], limit, timeout, trace=True)
        record["baseline"] = baseline
        if baseline["status"] != "ran":
            return {**record, "status": "baseline_" + baseline["status"]}
        eligible = {node: run for node, run in sorted(baseline["tests"].items()) if run["phases"] == PASS}
        if not eligible:
            return {**record, "status": "no_baseline_passing_tests"}
        picks, ranking_seconds, scores = rank(current, candidate.text, eligible)
        record.update(selected=picks, ranking_seconds=ranking_seconds, scores=scores,
                      eligible_tests=len(eligible))
        proposed = run_phase(archive, target, candidate.text, case["test_files"], limit, timeout)
        record["candidate"] = proposed
        if proposed["status"] != "ran":
            return {**record, "status": "candidate_" + proposed["status"]}
        if baseline["tests"].keys() != proposed["tests"].keys():
            return {**record, "status": "pool_changed"}
        failures = [node for node in eligible if proposed["tests"][node]["phases"].get("call") == "failed"]
        other = [node for node in eligible if node not in failures
                 and proposed["tests"][node]["phases"] != PASS]
        # Time each distinct chosen check in an independent candidate process.
        timed = {node: run_phase(archive, target, candidate.text, [node], 1, timeout)
                 for node in sorted(set(picks.values()))}
        return {**record, "status": "evaluated", "call_failures": failures,
                "other_candidate_outcomes": other, "selected_runs": timed,
                "hits": {method: node in failures for method, node in picks.items()},
                "uniform_detection_probability": str(Fraction(len(failures), len(eligible)))}
    except (OSError, RuntimeError, StopIteration, ValueError, tarfile.TarError) as exc:
        return {**record, "status": "setup_error", "error": str(exc) or type(exc).__name__}


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        target, limit, mode, *selectors = sys.argv[2:]
        raise SystemExit(worker(target, mode == "trace", selectors, int(limit)))

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clones", type=Path)
    args = parser.parse_args()
    plan = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = []
    for project in plan["projects"]:
        for case in project["cases"]:
            record = evaluate(args.clones / project["project"], project["snapshot"], case,
                              plan["max_nodes_per_case"], plan["timeout_seconds_per_phase"])
            records.append(record)
            print(f"{record['project']} {record['revert'][:8]} {record['status']}", file=sys.stderr)
    print(json.dumps({"statuses": dict(Counter(row["status"] for row in records)),
                      "cases": records}, indent=2))


if __name__ == "__main__":
    main()
