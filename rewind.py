"""Preview a selective undo of an agent's changes to text files."""

import argparse
from dataclasses import dataclass
from difflib import unified_diff
import json
import os
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


def format_diff(current: str, proposed: str, filename: str) -> str:
    lines = []
    for line in unified_diff(
        current.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile=f"current/{filename}",
        tofile=f"rewound/{filename}",
    ):
        if line.endswith("\n"):
            lines.append(line)
        else:
            lines.append(line + "\n\\ No newline at end of file\n")
    return "".join(lines)


def print_preview(current: str, preview: Preview, filename: str) -> None:
    if preview.has_conflicts:
        print("Review required. Conflict preview:\n")
        print(preview.text, end="")
    elif current == preview.text:
        print("No changes to rewind.")
    else:
        print("Proposed changes:\n")
        print(format_diff(current, preview.text, filename), end="")


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


def git(directory: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def resolve_commit(directory: Path, ref: str) -> str:
    return git(directory, "rev-parse", "--verify", "--end-of-options",
               f"{ref}^{{commit}}").decode("ascii").strip()


def match_line_endings(text: str, current: str) -> str:
    # Git may store LF while a Windows checkout uses CRLF.
    if "\r\n" in current and "\n" not in current.replace("\r\n", ""):
        return text.replace("\r\n", "\n").replace("\n", "\r\n")
    return text


def read_git_versions(path: Path, before_ref: str, after_ref: str, current: str) -> tuple[str, str]:
    prefix = git(path.parent, "rev-parse", "--show-prefix").decode("utf-8").removesuffix("\n").removesuffix("\r")
    versions = []
    for ref in (before_ref, after_ref):
        commit = resolve_commit(path.parent, ref)
        content = git(path.parent, "cat-file", "blob", f"{commit}:{prefix}{path.name}")
        versions.append(match_line_endings(content.decode("utf-8"), current))
    return versions[0], versions[1]


def preview_repository(directory: Path, before_ref: str, after_ref: str, json_output: bool = False) -> int:
    root = Path(git(directory, "rev-parse", "--show-toplevel").decode("utf-8").rstrip("\r\n")).resolve()
    before = resolve_commit(root, before_ref)
    after = resolve_commit(root, after_ref)
    fields = git(root, "diff", "--raw", "-z", "--no-abbrev", "--no-renames",
                 "--no-ext-diff", "--ignore-submodules=none", before, after, "--").split(b"\0")
    counts = dict(clean=0, unchanged=0, conflict=0, skipped=0)
    records = []
    for header, name in zip(fields[0:-1:2], fields[1:-1:2]):
        old_mode, new_mode, old_blob, new_blob, status = header.decode("ascii").split()
        filename = os.fsdecode(name)
        if not json_output:
            print(f"\n{filename!r}")
        path = root / filename
        try:
            if status != "M" or old_mode[1:] != new_mode or new_mode not in {"100644", "100755"}:
                raise ValueError("only content changes to existing regular files are supported.")
            if not path.is_file() or path.resolve() != path:
                raise ValueError("working file is missing or points through a symlink")
            current, before_text, after_text = (
                data.decode("utf-8") for data in (
                    path.read_bytes(), git(root, "cat-file", "blob", old_blob),
                    git(root, "cat-file", "blob", new_blob),
                )
            )
            if any("\0" in text for text in (current, before_text, after_text)):
                raise ValueError("file contains binary data")
            preview = preview_rewind(
                match_line_endings(before_text, current),
                match_line_endings(after_text, current),
                current,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            if json_output:
                records.append(dict(path=filename, status="skipped", reason=str(exc)))
            else:
                print(f"Skipped: {exc}")
            counts["skipped"] += 1
            continue
        if preview.has_conflicts:
            outcome = "conflict"
        elif preview.text == current:
            outcome = "unchanged"
        else:
            outcome = "clean"
        counts[outcome] += 1
        if json_output:
            record = dict(path=filename, status=outcome)
            if outcome == "conflict":
                record["conflict_preview"] = preview.text
            elif outcome == "clean":
                record["diff"] = format_diff(current, preview.text, repr(filename))
            records.append(record)
        else:
            print_preview(current, preview, repr(filename))

    if json_output:
        print(json.dumps(dict(schema_version=1, before_commit=before, after_commit=after,
                              summary=counts, files=records), indent=2))
    else:
        print(f"\nSummary: {counts['clean']} clean, {counts['unchanged']} unchanged, "
              f"{counts['conflict']} conflicts, {counts['skipped']} skipped.")
    return int(bool(counts["conflict"] or counts["skipped"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, help="UTF-8 file before the agent edit")
    parser.add_argument("--after", type=Path, help="UTF-8 file immediately after the agent edit")
    parser.add_argument("--before-ref", help="Git commit before the agent edit")
    parser.add_argument("--after-ref", help="Git commit immediately after the agent edit")
    parser.add_argument("--current", type=Path, help="Current UTF-8 file including later edits")
    parser.add_argument("--output", type=Path, help="Save a clean result to a new file")
    parser.add_argument("--all", action="store_true", help="Preview all supported changes between Git commits")
    parser.add_argument("--json", action="store_true", help="Print the batch preview as JSON")
    args = parser.parse_args()
    if args.json and not args.all:
        parser.error("--json requires --all")
    file_mode = args.before is not None or args.after is not None
    git_mode = args.before_ref is not None or args.after_ref is not None
    if args.all:
        if file_mode or args.current is not None or args.output is not None:
            parser.error("--all accepts Git refs and previews changes in the current repository")
        if not (args.before_ref and args.after_ref):
            parser.error("--all requires --before-ref and --after-ref")
        try:
            return preview_repository(Path.cwd(), args.before_ref, args.after_ref, args.json)
        except (OSError, ValueError, RuntimeError) as exc:
            parser.error(str(exc))
    if not (file_mode or git_mode or args.current is not None or args.output is not None):
        run_demo()
        return 0
    if file_mode and git_mode:
        parser.error("choose file paths or Git refs for before and after")
    if args.current is None:
        parser.error("--current is required")
    if git_mode and not (args.before_ref and args.after_ref):
        parser.error("--before-ref and --after-ref must be supplied together")
    if not git_mode and not (args.before and args.after):
        parser.error("--before and --after must be supplied together in file mode")

    try:
        current = args.current.read_bytes().decode("utf-8")
        if git_mode:
            before, after = read_git_versions(args.current, args.before_ref, args.after_ref, current)
        else:
            before, after = (path.read_bytes().decode("utf-8") for path in (args.before, args.after))
        preview = preview_rewind(before, after, current)
    except (OSError, UnicodeError, RuntimeError) as exc:
        parser.error(str(exc))
    print_preview(current, preview, args.current.name)
    if args.output is not None and not preview.has_conflicts:
        try:
            with args.output.open("xb") as output:
                output.write(preview.text.encode("utf-8"))
        except FileExistsError:
            parser.error(f"output already exists: {args.output}")
        except OSError as exc:
            parser.error(str(exc))
        print(f"\nSaved rewind to {args.output}")
    return int(preview.has_conflicts)


if __name__ == "__main__":
    raise SystemExit(main())
