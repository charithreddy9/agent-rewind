"""Compare rewind strategies on fixed, synthetic text-file examples."""

from dataclasses import dataclass

from rewind import Preview, preview_rewind


@dataclass(frozen=True)
class Case:
    name: str
    before: str
    after: str
    current: str
    expected: str | None


def full_restore(before: str, after: str, current: str) -> Preview:
    return Preview(before, False)


def skip_edited(before: str, after: str, current: str) -> Preview:
    return Preview(before if current == after else current, False)


def cases() -> tuple[Case, ...]:
    before = "cache = off\n\nport = 8080\n"
    after = "cache = on\n\nport = 8080\n"
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
    )


def outcome(case: Case, preview: Preview) -> str:
    if preview.has_conflicts:
        return "review" if case.expected is None else "extra review"
    if case.expected is None:
        return "missed conflict"
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
