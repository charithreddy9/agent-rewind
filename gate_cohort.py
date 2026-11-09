"""Replay a frozen cohort of full historical batches from their pre-revert trees."""

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from external_history import REVERT_MARKER
from rewind import git


# Every distinct revert with an intervening file edit in the expanded replay.
# Selectors were chosen from the pre-revert trees before this cohort was run.
COHORT = (
    ("requests", "09fd857eb1448a8234e39bc39e2c795d4c980bfb",
     ("tests/test_requests.py::TestRequests::test_entry_points",
      "tests/test_requests.py::TestRequests::test_basic_building")),
    ("requests", "1fcda912dbac57cd4e0f557fb611ea46c200cb4e",
     ("test_requests.py::RequestsTestCase::test_entry_points",)),
    ("requests", "b14584f36eca344ed5033d1d2f5a59490fadca56",
     ("test_requests.py::RequestsTestCase::test_entry_points",)),
    ("pytest", "6a47389c7813ec7ed395c0279c4b7685fde9f95a",
     ("testing/test_unittest.py::test_unittest_skip_issue148",)),
    ("pytest", "7b6e477e2f55f143a490c7d206eac5a7e005b392",
     ("testing/deprecated_test.py::test_raising_unittest_skiptest_during_collection_is_deprecated",)),
    ("pytest", "b3ed595f526c5b531b701d0cc9480432bf62c42e",
     ("testing/test_unittest.py::test_simple_unittest",)),
    ("black", "b9ad4da2e81f6ec66d292b85f284889211e052b4",
     ("tests/test_black.py::BlackTestCase::test_empty_ff",)),
    ("black", "773e4a22d58be1f1aa82df7ad9a0f4c4e1328c10",
     ("tests/test_black.py::BlackTestCase::test_numeric_literals",
      "tests/test_black.py::BlackTestCase::test_numeric_literals_ignoring_underscores")),
    ("black", "394edc388755eff01cc2ea155918bc4379ce933d",
     ("tests/test_black.py::BlackTestCase::test_empty",)),
    ("httpx", "631ba97635262fc72556a1638bac42cc843fe2ea",
     ("tests/models/test_requests.py::test_no_content",
      "tests/models/test_requests.py::test_content_length_header")),
)


def run_case(repo: Path, project: str, revert: str, tests: tuple[str, ...]) -> dict:
    record = {"project": project, "revert": revert, "selectors": tests}
    try:
        target, = REVERT_MARKER.findall(git(repo, "show", "-s", "--format=%B", revert))
        before_revert = revert + "^"
        for selector in tests:
            path, name = selector.split("::", 1)[0], selector.rsplit("::", 1)[1]
            source = git(repo, "show", f"{before_revert}:{path}")
            if f"def {name}(".encode() not in source:
                raise ValueError(f"Selected test definition missing from baseline: {selector}")
        with TemporaryDirectory(prefix=f"rewind-cohort-{project}-") as directory:
            root = Path(directory).resolve()
            git(root, "clone", "--quiet", "--shared", "--no-checkout", "--template=", str(repo.resolve()), ".")
            git(root, "-c", "core.autocrlf=false", "checkout", "--quiet", "--detach", before_revert)
            if project in {"pytest", "black"}:
                path = "src/_pytest/_version.py" if project == "pytest" else "src/_black_version.py"
                if (root / path).parent.is_dir() and not (root / path).exists():
                    version = git(repo, "describe", "--tags", "--abbrev=0", before_revert).decode().strip()
                    (root / path).write_text(f"version = {version!r}\nversion_tuple = (0,)\n", encoding="utf-8")
                    git(root, "add", "-f", "--", path)
            bootstrap = (
                "import os, sys; "
                "paths = [os.path.abspath('src'), os.getcwd()]; "
                "os.environ.update(PYTHONPATH=os.pathsep.join(paths), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'); "
                "sys.path[:0] = paths; "
                "import pytest; raise SystemExit(pytest.main(sys.argv[1:]))"
            )
            target_ref = target.decode("ascii")
            result = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve().with_name("rewind.py")),
                 "--all", "--json", "--before-ref", target_ref + "^", "--after-ref", target_ref,
                 "--check", sys.executable, "-B", "-c", bootstrap, "-q", "--disable-warnings", *tests],
                cwd=root, capture_output=True, text=True, timeout=180,
            )
            report = json.loads(result.stdout)
            gate = report["test_gate"]
            record.update(status=gate["status"], batch_exit_code=result.returncode,
                          summary=report["summary"], gate=gate)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        record.update(status="setup_error", error=str(exc))
        if "result" in locals():
            record["stderr"] = result.stderr
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clones", type=Path, help="Directory containing the full upstream clones")
    args = parser.parse_args()
    records = [run_case(args.clones / project, project, revert, tests)
               for project, revert, tests in COHORT]
    print(json.dumps({"planned": len(COHORT),
                      "statuses": dict(Counter(record["status"] for record in records)),
                      "cases": records}, indent=2))


if __name__ == "__main__":
    main()
