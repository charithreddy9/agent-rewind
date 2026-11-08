"""Create a disposable Git history and render the Agent Rewind demo report."""

import argparse
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


def generate_report() -> bytes:
    script = Path(__file__).resolve().with_name("rewind.py")
    with TemporaryDirectory(prefix="agent-rewind-demo-") as folder:
        repo = Path(folder)

        def git(*args: str) -> None:
            subprocess.run(
                ["git", "-c", "user.name=Rewind Demo",
                 "-c", "user.email=demo@example.invalid",
                 "-c", "commit.gpgsign=false",
                 "-c", f"core.hooksPath={repo / '.git' / 'demo-disabled-hooks'}",
                 "-c", "core.autocrlf=false", *args],
                cwd=repo, capture_output=True, check=True,
            )

        git("init", "--quiet", "--template=")
        config = repo / "config.py"
        worker = repo / "worker.py"
        config.write_bytes(b"CACHE_ENABLED = False\n\nPORT = 8080\n")
        worker.write_bytes(b"MAX_RETRIES = 3\n")
        git("add", "-f", "--", config.name, worker.name)
        git("commit", "--quiet", "-m", "Before agent edits")

        config.write_bytes(b"CACHE_ENABLED = True\n\nPORT = 8080\n")
        worker.write_bytes(b"MAX_RETRIES = 5\n")
        git("add", "-f", "--", config.name, worker.name)
        git("commit", "--quiet", "-m", "Agent enables caching and increases retries")

        config.write_bytes(b'CACHE_ENABLED = True\n\nPORT = 8080\nLOG_LEVEL = "debug"\n')
        worker.write_bytes(b"MAX_RETRIES = 8\n")
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(script), "--before-ref", "HEAD~1",
             "--after-ref", "HEAD", "--all", "--html"],
            cwd=repo, capture_output=True,
        )
        # A review-required exit is expected because worker.py has an overlap.
        if result.returncode != 1 or not result.stdout.startswith(b"<!doctype html>"):
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(detail or f"Unexpected preview exit code: {result.returncode}")
        return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("rewind-demo.html"),
                        help="New path for the report (default: rewind-demo.html)")
    args = parser.parse_args()
    try:
        report = generate_report()
        with args.output.open("xb") as output:
            output.write(report)
    except subprocess.CalledProcessError as exc:
        parser.error(exc.stderr.decode("utf-8", errors="replace").strip())
    except (OSError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"Open {args.output.resolve()} in your browser.")


if __name__ == "__main__":
    main()
