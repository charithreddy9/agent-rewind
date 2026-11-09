"""Run a trusted check against the current files and a proposed rewind."""

import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory


def run_check(command: list[str], workspace: Path) -> dict:
    try:
        result = subprocess.run(command, cwd=workspace, capture_output=True, timeout=60)
        return {"exit_code": result.returncode,
                "output": (result.stdout + result.stderr).decode("utf-8", errors="replace")}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"exit_code": None, "error": str(exc)}


def check_rewind(root: Path, tracked: bytes, candidates: dict[str, tuple[str, str]],
                 command: list[str]) -> dict:
    report = {"command": command, "status": "error"}
    try:
        with TemporaryDirectory(prefix="agent-rewind-") as directory:
            baseline = Path(directory) / "baseline"
            baseline.mkdir()
            for name in tracked.split(b"\0"):
                if not name:
                    continue
                relative = os.fsdecode(name)
                path = root / relative
                if not path.is_file() or path.resolve() != path:
                    raise ValueError(f"Cannot copy tracked file {relative!r}; expected a regular file")
                target = baseline / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            candidate = Path(directory) / "candidate"
            shutil.copytree(baseline, candidate)
            for name, (original, content) in candidates.items():
                target = candidate / name
                if not target.is_file():
                    raise ValueError(f"Rewind target {name!r} is absent from the tracked snapshot")
                if target.read_bytes() != original.encode("utf-8"):
                    raise ValueError(f"Rewind target {name!r} changed after the preview")
                target.write_bytes(content.encode("utf-8"))
            current = report["baseline"] = run_check(command, baseline)
            if current["exit_code"] is None:
                return report
            if current["exit_code"] != 0:
                report["status"] = "baseline_failed"
                return report
            proposed = report["candidate"] = run_check(command, candidate)
            if proposed["exit_code"] is not None:
                report["status"] = "passed" if proposed["exit_code"] == 0 else "candidate_failed"
    except (OSError, ValueError) as exc:
        report["error"] = str(exc)
    return report
