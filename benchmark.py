"""Compare rewind strategies on fixed, synthetic text-file examples."""

from dataclasses import dataclass
import json
from typing import Callable

from rewind import Preview, preview_rewind
from validation import check_json


@dataclass(frozen=True)
class Case:
    name: str
    before: str
    after: str
    current: str
    expected: str | None
    valid: Callable[[str], bool] | None = None
    rule: tuple[str, str] | None = None


def full_restore(before: str, after: str, current: str) -> Preview:
    return Preview(before, False)


def skip_edited(before: str, after: str, current: str) -> Preview:
    return Preview(before if current == after else current, False)


def valid_worker_limits(text: str) -> bool:
    settings = json.loads(text)
    return settings["min_workers"] <= settings["max_workers"]


def valid_retry_limits(text: str) -> bool:
    settings = json.loads(text)
    return settings["retry_delay_ms"] <= settings["deadline_ms"]


def cases() -> tuple[Case, ...]:
    before = "cache = off\n\nport = 8080\n"
    after = "cache = on\n\nport = 8080\n"
    limits = '{\n  "max_workers": 4,\n\n  "min_workers": 2\n}\n'
    raised_limit = limits.replace(": 4,", ": 8,")
    worker_rule = ("min_workers", "max_workers")
    retry = '{\n  "retry_delay_ms": 50,\n\n  "deadline_ms": 100\n}\n'
    lower_delay = retry.replace(": 50,", ": 20,")
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
             raised_limit.replace(": 2", ": 6"), None, valid_worker_limits, worker_rule),
        Case("Already manually rewound", before, after, before + "log = debug\n",
             before + "log = debug\n"),
        Case("Worker limits equal", limits, raised_limit, raised_limit.replace(": 2", ": 4"),
             limits.replace(": 2", ": 4"), valid_worker_limits, worker_rule),
        Case("Retry deadline dependency", retry, lower_delay, lower_delay.replace(": 100", ": 30"),
             None, valid_retry_limits, ("retry_delay_ms", "deadline_ms")),
        Case("Retry deadline still valid", retry, lower_delay, lower_delay.replace(": 100", ": 80"),
             retry.replace(": 100", ": 80"), valid_retry_limits, ("retry_delay_ms", "deadline_ms")),
    )


def outcome(case: Case, preview: Preview, use_rules: bool = False) -> str:
    if preview.has_conflicts or (use_rules and case.rule and preview.text != case.current
                                 and check_json(preview.text, [case.rule])):
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
    print(f"{'Scenario':<29}" + "".join(f"{label:<18}" for label, _ in strategies) + "Git + rules")
    for case in cases():
        previews = [strategy(case.before, case.after, case.current) for _, strategy in strategies]
        results = [outcome(case, preview) for preview in previews]
        results.append(outcome(case, previews[-1], use_rules=True))
        print(f"{case.name:<29}" + "".join(f"{result:<18}" for result in results))


if __name__ == "__main__":
    main()
