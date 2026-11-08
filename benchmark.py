"""Compare rewind strategies on fixed, synthetic text-file examples."""

from dataclasses import dataclass
import json
from typing import Callable

from rewind import Preview, preview_rewind


@dataclass(frozen=True)
class Case:
    name: str
    before: str
    after: str
    current: str
    expected: str | None
    valid: Callable[[str], bool] | None = None


def full_restore(before: str, after: str, current: str) -> Preview:
    return Preview(before, False)


def skip_edited(before: str, after: str, current: str) -> Preview:
    return Preview(before if current == after else current, False)


def valid_worker_limits(text: str) -> bool:
    settings = json.loads(text)
    return settings["min_workers"] <= settings["max_workers"]


def cases() -> tuple[Case, ...]:
    before = "cache = off\n\nport = 8080\n"
    after = "cache = on\n\nport = 8080\n"
    limits = '{\n  "max_workers": 4,\n\n  "min_workers": 2\n}\n'
    raised_limit = limits.replace(": 4,", ": 8,")
    return (
        Case("Agent edit only", before, after, after, before),
        Case("Later logging edit", before, after, after + "log = debug\n",
             before + "log = debug\n"),
        Case("Later port edit", before, after, "cache = on\n\nport = 9090\n",
             "cache = off\n\nport = 9090\n"),
        Case("Same line edited", before, after, "cache = auto\n\nport = 8080\n", None),
        Case("Agent added a line", before, "debug = on\n" + before,
             "debug = on\n" + before + "log = debug\n", before + "log = debug\n"),
        Case("Agent removed a line", "debug = off\n" + before, before,
             before + "log = debug\n", "debug = off\n" + before + "log = debug\n"),
        Case("Adjacent line edited", "cache = off\nport = 8080\n",
             "cache = on\nport = 8080\n", "cache = on\nport = 9090\n",
             "cache = off\nport = 9090\n"),
        Case("Worker limit dependency", limits, raised_limit,
             raised_limit.replace(": 2", ": 6"), None, valid_worker_limits),
    )


def outcome(case: Case, preview: Preview) -> str:
    if preview.has_conflicts:
        return "review" if case.expected is None else "extra review"
    if case.valid is not None and not case.valid(preview.text):
        return "invalid result"
    if case.expected is None:
        return "missed review"
    return "exact" if preview.text == case.expected else "wrong result"


def main() -> None:
    strategies = (
        ("Full restore", full_restore),
        ("Skip edited", skip_edited),
        ("Selective (Git)", preview_rewind),
    )
    print(f"{'Scenario':<24}" + "".join(f"{label:<18}" for label, _ in strategies))
    for case in cases():
        results = (
            outcome(case, strategy(case.before, case.after, case.current))
            for _, strategy in strategies
        )
        print(f"{case.name:<24}" + "".join(f"{result:<18}" for result in results))


if __name__ == "__main__":
    main()
