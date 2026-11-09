"""Regression tests for configuration checks and the public CLI."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from benchmark import cases, outcome
from rewind import preview_rewind, render_html
from validation import check_json, load_rules


HERE = Path(__file__).resolve().parent
WORKER_RULE = [("min_workers", "max_workers")]


class ValidationTests(unittest.TestCase):
    def test_numeric_bound(self):
        self.assertEqual(check_json('{"min_workers": 4, "max_workers": 4}', WORKER_RULE), [])
        self.assertEqual(check_json('{"min_workers": 6, "max_workers": 4}', WORKER_RULE),
                         ["min_workers (6) must be <= max_workers (4)."])

    def test_invalid_json_and_non_numbers(self):
        for text in ('[1, 2]', '{', '{"min_workers": 2, "min_workers": 5, "max_workers": 4}',
                     '{"min_workers": true, "max_workers": 4}', '{"min_workers": 2}',
                     '{"min_workers": 2, "max_workers": 1e999}'):
            with self.subTest(text=text):
                self.assertTrue(check_json(text, WORKER_RULE))

    def test_rules_use_repository_relative_paths(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "rules.json"
            path.write_text('{"config/worker.json": [["min_workers", "max_workers"]]}', encoding="utf-8")
            self.assertEqual(load_rules(path), {"config/worker.json": WORKER_RULE})
            for filename in ("../worker.json", "/worker.json", ".", "C:/worker.json"):
                with self.subTest(filename=filename):
                    path.write_text(json.dumps({filename: WORKER_RULE}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_rules(path)

    def test_benchmark_detects_both_dependency_failures(self):
        for case in cases():
            if case.rule and case.expected is None:
                with self.subTest(case=case.name):
                    preview = preview_rewind(case.before, case.after, case.current)
                    self.assertEqual(outcome(case, preview), "invalid result")
                    self.assertEqual(outcome(case, preview, use_rules=True), "review")


class CommandTests(unittest.TestCase):
    def test_rules_change_batch_status_without_changing_the_file(self):
        case = next(c for c in cases() if c.name == "Worker limit dependency")
        with TemporaryDirectory() as folder:
            repo = Path(folder)

            def git(*args):
                subprocess.run(["git", "-c", "user.name=Demo",
                                "-c", "user.email=demo@example.invalid",
                                "-c", "commit.gpgsign=false",
                                "-c", f"core.hooksPath={repo / '.git' / 'disabled-hooks'}",
                                *args], cwd=repo, check=True, capture_output=True)

            git("init", "-q", "--template=")
            config = repo / "workers.json"
            for snapshot in (case.before, case.after):
                config.write_bytes(snapshot.encode("utf-8"))
                git("add", "-f", "--", config.name)
                git("commit", "-qm", "Fixture snapshot")
            config.write_bytes(case.current.encode("utf-8"))
            original = config.read_bytes()
            rules = repo / "rules.json"
            rules.write_text(json.dumps({config.name: WORKER_RULE}), encoding="utf-8")
            command = [sys.executable, str(HERE / "rewind.py"), "--all", "--json",
                       "--before-ref", "HEAD~1", "--after-ref", "HEAD"]
            regular = subprocess.run(command, cwd=repo, capture_output=True)
            guarded = subprocess.run(command + ["--rules", str(rules)], cwd=repo, capture_output=True)
            self.assertEqual(regular.returncode, 0, regular.stderr)
            self.assertEqual(json.loads(regular.stdout)["files"][0]["status"], "clean")
            self.assertEqual(guarded.returncode, 1, guarded.stderr)
            report = json.loads(guarded.stdout)
            self.assertEqual(report["summary"]["validation_failed"], 1)
            self.assertEqual(report["validation"]["checked_files"], 1)
            self.assertEqual(report["files"][0]["status"], "validation_failed")
            self.assertEqual(report["files"][0]["issues"],
                             ["min_workers (6) must be <= max_workers (4)."])
            self.assertEqual(config.read_bytes(), original)

    def test_gate_distinguishes_candidate_and_baseline_failures(self):
        with TemporaryDirectory() as folder:
            repo = Path(folder)

            def git(*args):
                return subprocess.check_output(
                    ["git", "-c", "user.name=Demo", "-c", "user.email=demo@example.invalid",
                     "-c", "commit.gpgsign=false",
                     "-c", f"core.hooksPath={repo / '.git' / 'disabled-hooks'}", *args], cwd=repo
                )

            git("init", "-q", "--template=")
            source = repo / "setting.py"
            check = repo / "verify.py"
            check.write_bytes(b"from pathlib import Path\n"
                              b"assert Path('setting.py').read_text().startswith('ENABLED = True')\n"
                              b"Path('test-marker').touch()\n")
            for value in ("False", "True"):
                source.write_bytes(f"ENABLED = {value}\n\nPORT = 8080\n".encode())
                git("add", "-f", "--", source.name, check.name)
                git("commit", "-qm", "Fixture snapshot")
            # The baseline includes the uncommitted edit.
            source.write_bytes(b"ENABLED = True\n\nPORT = 8080\n# later edit\n")
            original = source.read_bytes()
            command = [sys.executable, str(HERE / "rewind.py"), "--all", "--json",
                       "--before-ref", "HEAD~1", "--after-ref", "HEAD", "--check"]

            def run_check(*argv):
                result = subprocess.run(command + list(argv), cwd=repo, capture_output=True)
                return result.returncode, json.loads(result.stdout)

            code, report = run_check(sys.executable, check.name)
            self.assertEqual(code, 1)
            self.assertEqual(report["files"][0]["status"], "clean")
            gate = report["test_gate"]
            self.assertEqual(gate["status"], "candidate_failed")
            self.assertEqual(gate["baseline"]["exit_code"], 0)
            self.assertIn("AssertionError", gate["candidate"]["output"])
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse((repo / "test-marker").exists())

            code, report = run_check(sys.executable, "-c", "raise SystemExit(1)")
            self.assertEqual(code, 1)
            self.assertEqual(report["test_gate"]["status"], "baseline_failed")
            self.assertNotIn("candidate", report["test_gate"])

            code, report = run_check(sys.executable, "-c", "pass")
            self.assertEqual(code, 0)
            self.assertEqual(report["test_gate"]["status"], "passed")

    def test_passing_gate_requires_review_when_rewind_removes_a_test(self):
        with TemporaryDirectory() as folder:
            repo = Path(folder)

            def git(*args):
                subprocess.check_output(
                    ["git", "-c", "user.name=Demo", "-c", "user.email=demo@example.invalid",
                     "-c", "commit.gpgsign=false",
                     "-c", f"core.hooksPath={repo / '.git' / 'disabled-hooks'}", *args], cwd=repo
                )

            git("init", "-q", "--template=")
            path = repo / "test_sample.py"
            before = ("import unittest\n\nclass Checks(unittest.TestCase):\n"
                      "    def test_kept(self):\n        self.assertTrue(True)\n")
            after = before + "\n    def test_removed(self):\n        self.assertTrue(True)\n"
            for source in (before, after):
                path.write_bytes(source.encode())
                git("add", "-f", "--", path.name)
                git("commit", "-qm", "Fixture snapshot")

            command = [sys.executable, str(HERE / "rewind.py"), "--all",
                       "--before-ref", "HEAD~1", "--after-ref", "HEAD"]
            plain = subprocess.run(command + ["--json"], cwd=repo, capture_output=True)
            self.assertEqual(plain.returncode, 0, plain.stderr)
            checked = subprocess.run(
                command + ["--json", "--check", sys.executable, "-m", "unittest", "discover"],
                cwd=repo, capture_output=True,
            )
            self.assertEqual(checked.returncode, 1, checked.stderr)
            report = json.loads(checked.stdout)
            gate = report["test_gate"]
            self.assertEqual(gate["status"], "passed")
            self.assertEqual(gate["test_changes"], [
                {"path": "test_sample.py", "removed_definitions": ["Checks.test_removed"]},
            ])
            self.assertIn("Removed Python test definition: Checks.test_removed", render_html(report))
            self.assertEqual(path.read_bytes(), after.encode())

    def test_browser_demo_contains_all_three_outcomes(self):
        with TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(HERE / "demo.py")], cwd=folder,
                                    capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = (Path(folder) / "rewind-demo.html").read_text(encoding="utf-8")
            for expected in ("+CACHE_ENABLED = False", "LOG_LEVEL = &quot;debug&quot;",
                             'class="badge conflict"', 'class="badge validation_failed"',
                             "min_workers (6) must be &lt;= max_workers (4)."):
                self.assertIn(expected, report)


if __name__ == "__main__":
    unittest.main()
