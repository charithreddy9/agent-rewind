"""Replay fixed later edits against real commits from this repository."""

from dataclasses import dataclass
from pathlib import Path

from benchmark import Case, full_restore, outcome, skip_edited
from rewind import git, preview_rewind


ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Change:
    label: str
    commit: str
    path: str
    overlap_line: str
    human_line: str


CHANGES = (
    Change("Output flag", "466e8b63b5cd8761e9b74b1218da90baa2224680", "rewind.py",
           '    parser.add_argument("--output", type=Path, help="Save a clean result to a new file")',
           '    parser.add_argument("--output", type=Path, help="Write the proposed result")'),
    Change("JSON reporting", "138a0cdb34f75fca8cdb4b4f41c5d69f5cfab2be", "rewind.py",
           "import json", "import json as json_tools"),
    Change("Demo documentation", "acf1f86f6a05b7f6afe641304be3547b8dc5d163", "README.md",
           "You asked a coding agent to change a file, then added a change of your own. Agent Rewind compares the Git history with your working copy and previews which agent edits it can reverse while keeping yours.",
           "Compare your working copy with the agent's edits before undoing anything."),
    Change("Benchmark check", "b90d13c06d819794227974ad78747174b2c0a6a0", "benchmark.py",
           '        return "invalid result"', '        return "validation failure"'),
)


def build_cases(change: Change) -> tuple[Case, ...]:
    before = git(ROOT, "cat-file", "blob", f"{change.commit}^:{change.path}").decode("utf-8")
    after = git(ROOT, "cat-file", "blob", f"{change.commit}:{change.path}").decode("utf-8")
    target = change.overlap_line + "\n"
    if target in before or after.splitlines().count(change.overlap_line) != 1:
        raise ValueError(f"Expected one agent-introduced overlap line for {change.label}")
    note = ("<!-- Later local note -->\n" if change.path.endswith(".md")
            else "# Later local note\n")
    return (
        Case(f"{change.label} / prefix", before, after, note + "\n" + after,
             note + "\n" + before),
        Case(f"{change.label} / suffix", before, after, after + "\n" + note,
             before + "\n" + note),
        Case(f"{change.label} / overlap", before, after,
             after.replace(target, change.human_line + "\n", 1), None),
    )


def main() -> None:
    strategies = (
        ("Full restore", full_restore),
        ("Skip edited", skip_edited),
        ("Selective (Git)", preview_rewind),
    )
    try:
        cases = [case for change in CHANGES for case in build_cases(change)]
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Cannot load replay fixtures. Use a full Git clone. {exc}") from exc
    print(f"{'Scenario':<33}" + "".join(f"{label:<18}" for label, _ in strategies))
    for case in cases:
        results = [
            outcome(case, strategy(case.before, case.after, case.current))
            for _, strategy in strategies
        ]
        print(f"{case.name:<33}" + "".join(f"{result:<18}" for result in results))


if __name__ == "__main__":
    main()
