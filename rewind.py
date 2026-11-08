"""Preview a selective undo of an agent's changes to one text file."""

import argparse
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


@dataclass(frozen=True)
class Preview:
    text: str
    has_conflicts: bool


def preview_rewind(before_agent: str, after_agent: str, current: str) -> Preview:
    """Merge the inverse agent change into the current file."""
    if current == after_agent:
        return Preview(before_agent, False)
    if before_agent == after_agent or current == before_agent:
        return Preview(current, False)

    with TemporaryDirectory(prefix="agent-rewind-") as directory:
        paths = [Path(directory) / name for name in ("current", "after", "before")]
        for path, content in zip(paths, (current, after_agent, before_agent)):
            path.write_bytes(content.encode("utf-8"))
        result = subprocess.run(
            [
                "git", "merge-file", "-p", "--diff3",
                "-L", "current workspace", "-L", "after agent", "-L", "before agent",
                "--", *paths,
            ],
            capture_output=True,
            check=False,
        )

    if not 0 <= result.returncode <= 127:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    return Preview(result.stdout.decode("utf-8"), result.returncode != 0)


def print_preview(current: str, preview: Preview, filename: str) -> None:
    if preview.has_conflicts:
        print("Review required. Conflict preview:\n")
        print(preview.text, end="")
        return
    if current == preview.text:
        print("No changes to rewind.")
        return
    print("Proposed changes:\n")
    for line in unified_diff(
        current.splitlines(keepends=True),
        preview.text.splitlines(keepends=True),
        fromfile=f"current/{filename}",
        tofile=f"rewound/{filename}",
    ):
        if line.endswith("\n"):
            print(line, end="")
        else:
            print(line)
            print("\\ No newline at end of file")


def run_demo() -> None:
    before = 'CACHE_ENABLED = False\n\nPORT = 8080\n'
    after = before.replace("False", "True")
    current = after + 'LOG_LEVEL = "debug"\n'
    overlapping = current.replace("True", "None")

    for label, workspace in (
        ("Later human edit", current),
        ("Human and agent changed the same line", overlapping),
    ):
        print(f"\n{label}")
        print_preview(workspace, preview_rewind(before, after, workspace), "config.py")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, help="UTF-8 file before the agent edit")
    parser.add_argument("--after", type=Path, help="UTF-8 file immediately after the agent edit")
    parser.add_argument("--current", type=Path, help="Current UTF-8 file including later edits")
    args = parser.parse_args()
    paths = (args.before, args.after, args.current)
    if not any(paths):
        run_demo()
        return 0
    if not all(paths):
        parser.error("--before, --after, and --current must be supplied together")

    try:
        before, after, current = (path.read_bytes().decode("utf-8") for path in paths)
        preview = preview_rewind(before, after, current)
    except (OSError, UnicodeError, RuntimeError) as exc:
        parser.error(str(exc))
    print_preview(current, preview, args.current.name)
    return int(preview.has_conflicts)


if __name__ == "__main__":
    raise SystemExit(main())
