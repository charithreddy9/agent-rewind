"""Run full-batch checks on modern revisions from the frozen coverage cohort."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

from coverage_cohort import MANIFEST, PASS
from coverage_replay import worker
from external_history import REVERT_MARKER
from rewind import git


CUTOFF = "2021-01-01"
RESULT_PREFIX = "REWIND_TEST_PHASES="
HERE = Path(__file__).resolve().parent


def phases_from_output(output: str) -> dict | None:
    for line in reversed(output.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line.removeprefix(RESULT_PREFIX))
    return None


def test_worker(selectors: list[str]) -> int:
    paths = [str(Path("src").resolve()), str(Path.cwd())]
    sys.path[:0] = paths
    os.environ.update(PYTHONPATH=os.pathsep.join(paths), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    status = worker("", False, selectors)
    output = Path("pool-results.json")
    if output.exists():
        tests = json.loads(output.read_text(encoding="utf-8"))
        print(RESULT_PREFIX + json.dumps({node: run["phases"] for node, run in tests.items()}))
    return status


def evaluate(repo: Path, revert: str, selectors: list[str]) -> dict:
    marker, = REVERT_MARKER.findall(git(repo, "show", "-s", "--format=%B", revert))
    original = marker.decode("ascii")
    record = {"project": repo.name, "revert": revert, "selectors": selectors}
    with TemporaryDirectory(prefix="rewind-full-batch-") as directory:
        root = Path(directory).resolve()
        git(root, "clone", "--quiet", "--shared", "--no-checkout", "--template=", str(repo.resolve()), ".")
        git(root, "-c", "core.autocrlf=false", "checkout", "--quiet", "--detach", revert + "^")
        generated = root / "src/urllib3/_version.py"
        if repo.name == "urllib3" and generated.parent.is_dir() and not generated.exists():
            tag = git(repo, "describe", "--tags", "--match", "[0-9]*", "--abbrev=0", revert + "^")
            version = tag.decode().strip()
            generated.write_text(f"__version__ = version = {version!r}\n", encoding="utf-8")
            git(root, "add", "-f", "--", "src/urllib3/_version.py")
            record["generated_version_stub"] = version
        command = [sys.executable, "-B", str(HERE / "full_batch_cohort.py"), "--worker", *selectors]
        cli = [sys.executable, "-B", str(HERE / "rewind.py"), "--all", "--json",
               "--before-ref", original + "^", "--after-ref", original, "--check", *command]
        env = {**os.environ, "HYPOTHESIS_NO_PLUGINS": "1", "PYTHONHASHSEED": "0"}
        result = subprocess.run(cli, cwd=root, env=env, capture_output=True, encoding="utf-8",
                                errors="replace", timeout=150)
        if not result.stdout:
            raise RuntimeError(result.stderr)
        report = json.loads(result.stdout)
        gate = report["test_gate"]
        record.update(preview=report["summary"], gate=gate, cli_exit_code=result.returncode,
                      unresolved=[{"path": row["path"], "status": row["status"],
                                   "reason": row.get("reason")}
                                  for row in report["files"] if row["status"] in {"skipped", "conflict"}])
        if gate["status"] == "skipped_incomplete":
            # Establish whether the historical baseline can run even if preview blocks the batch.
            started = perf_counter()
            try:
                baseline = subprocess.run(command, cwd=root, env=env, capture_output=True, encoding="utf-8",
                                          errors="replace", timeout=120)
                record["baseline_probe"] = {"exit_code": baseline.returncode,
                                            "output": baseline.stdout + baseline.stderr}
            except subprocess.TimeoutExpired:
                record["baseline_probe"] = {"exit_code": None, "error": "120-second timeout"}
            record["baseline_probe"]["seconds"] = perf_counter() - started
        baseline = record.get("baseline_probe", gate.get("baseline", {}))
        base_tests = phases_from_output(baseline.get("output", ""))
        proposed_tests = phases_from_output(gate.get("candidate", {}).get("output", ""))
        if base_tests is not None:
            record["baseline_nodes"] = len(base_tests)
            record["baseline_passing_nodes"] = sum(run == PASS for run in base_tests.values())
        if base_tests is not None and proposed_tests is not None:
            record["candidate_nodes"] = len(proposed_tests)
            record["baseline_only_nodes"] = sorted(base_tests.keys() - proposed_tests.keys())
            record["candidate_only_nodes"] = sorted(proposed_tests.keys() - base_tests.keys())
            record["shared_passing_to_failing"] = sorted(
                node for node in base_tests.keys() & proposed_tests.keys()
                if base_tests[node] == PASS and proposed_tests[node].get("call") == "failed"
            )
        return record


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        raise SystemExit(test_worker(sys.argv[2:]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clones", type=Path)
    args = parser.parse_args()
    plan = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = []
    for project in plan["projects"]:
        repo = args.clones / project["project"]
        batches = {}
        for case in project["cases"]:
            revert = case["revert"]
            if git(repo, "show", "-s", "--format=%as", revert).decode().strip() >= CUTOFF:
                batches.setdefault(revert, set()).update(case["test_files"])
        for revert, selectors in batches.items():
            try:
                record = evaluate(repo, revert, sorted(selectors))
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
                record = {"project": repo.name, "revert": revert, "error": str(exc)}
            records.append(record)
            print(f"{repo.name} {revert[:8]} {record.get('gate', {}).get('status', 'error')}",
                  file=sys.stderr)
    print(json.dumps({"cutoff": CUTOFF, "batches": records}, indent=2))


if __name__ == "__main__":
    main()
