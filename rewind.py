"""Preview a selective undo of an agent's changes to one text file."""

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


def main() -> None:
    before = 'CACHE_ENABLED = False\n\nPORT = 8080\n'
    after = before.replace("False", "True")
    current = after + 'LOG_LEVEL = "debug"\n'
    overlapping = current.replace("True", "None")

    for label, workspace in (
        ("Later human edit", current),
        ("Human and agent changed the same line", overlapping),
    ):
        preview = preview_rewind(before, after, workspace)
        print(f"\n{label}")
        if preview.has_conflicts:
            print("Review required. Conflict preview:\n")
            print(preview.text, end="")
        else:
            print("Proposed changes:\n")
            print("".join(unified_diff(
                workspace.splitlines(keepends=True),
                preview.text.splitlines(keepends=True),
                fromfile="current/config.py",
                tofile="rewound/config.py",
            )), end="")


if __name__ == "__main__":
    main()
