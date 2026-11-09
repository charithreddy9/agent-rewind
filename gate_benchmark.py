"""Compare smoke and targeted checks on labeled, synthetic rewind candidates."""

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from benchmark import cases
from check_gate import check_rewind
from rewind import preview_rewind


@dataclass(frozen=True)
class Scenario:
    name: str
    broken: bool
    before: str
    after: str
    current: str
    smoke: str
    contract: str
    context: str = ""
    target: str = "target.py"


def scenarios() -> tuple[Scenario, ...]:
    configs = {
        "Worker limit dependency": (True, "min_workers", "max_workers"),
        "Worker limits equal": (False, "min_workers", "max_workers"),
        "Retry deadline dependency": (True, "retry_delay_ms", "deadline_ms"),
        "Retry deadline still valid": (False, "retry_delay_ms", "deadline_ms"),
    }
    config_cases = []
    for case in cases():
        if case.name in configs:
            broken, lower, upper = configs[case.name]
            config_cases.append(Scenario(
                case.name, broken, case.before, case.after, case.current,
                "assert isinstance(json.loads(Path('target.json').read_text()), dict)",
                f"settings = json.loads(Path('target.json').read_text())\n"
                f"assert settings[{lower!r}] <= settings[{upper!r}]",
                target="target.json",
            ))

    before = "from math import ceil\n\nFORMAT = 'number'\n\ndef size(value):\n    return ceil(value)\n"
    after = before.replace("ceil(value)", "round(value)")
    smoke = "import target\nassert target.FORMAT == 'number'"
    contract = "import target\nassert isinstance(target.size(1.2), int)"
    import_cases = (
        Scenario("Removed import", True, before, after,
                 after.replace("from math import ceil\n\n", ""), smoke, contract),
        Scenario("Retained import", False, before, after,
                 after.replace("FORMAT = 'number'", "FORMAT = 'number'  # documented"),
                 smoke, contract),
    )
    before = "VERSION = 1\n\ndef payload():\n    return {'id': 7}\n"
    after = before.replace("'id': 7", "'id': 7, 'label': 'item'")
    smoke = "import target\nassert target.payload()['id'] == 7"
    contract = "from consumer import display\nassert display() == 'item'"
    interface_cases = (
        Scenario("Consumer requires new field", True, before, after, after, smoke, contract,
                 "from target import payload\n\ndef display():\n    return payload()['label']\n"),
        Scenario("Consumer allows missing field", False, before, after, after, smoke, contract,
                 "from target import payload\n\ndef display():\n    return payload().get('label', 'item')\n"),
    )
    return (*config_cases, *import_cases, *interface_cases)


def measure(scenario: Scenario) -> dict:
    preview = preview_rewind(scenario.before, scenario.after, scenario.current)
    if preview.has_conflicts or preview.text == scenario.current:
        raise ValueError(f"Expected a changed, conflict-free candidate for {scenario.name}")
    results = {}
    with TemporaryDirectory(prefix="rewind-benchmark-") as directory:
        root = Path(directory).resolve()
        target = scenario.target
        (root / target).write_bytes(scenario.current.encode())
        files = [target, "smoke.py", "targeted.py"]
        if scenario.context:
            (root / "consumer.py").write_text(scenario.context, encoding="utf-8")
            files.append("consumer.py")
        preamble = "import json\nfrom pathlib import Path\n"
        for suite, code in (("smoke", scenario.smoke),
                            ("targeted", scenario.smoke + "\n" + scenario.contract)):
            (root / f"{suite}.py").write_text(preamble + code + "\n", encoding="utf-8")
        tracked = "\0".join(files).encode() + b"\0"
        for suite in ("smoke", "targeted"):
            results[suite] = check_rewind(
                root, tracked, {target: (scenario.current, preview.text)},
                [sys.executable, "-B", f"{suite}.py"],
            )
    return {"name": scenario.name, "label": "broken" if scenario.broken else "valid",
            "candidate": preview.text, "results": results}


def main() -> None:
    records = [measure(scenario) for scenario in scenarios()]
    summary = {}
    for suite in ("smoke", "targeted"):
        counts = Counter()
        for record in records:
            label = record["label"]
            status = record["results"][suite]["status"]
            counts[f"{label}_{status}"] += 1
        summary[suite] = dict(counts)
    print(json.dumps({"summary": summary, "cases": records}, indent=2))
    if any(record["results"][suite]["status"] not in {"passed", "candidate_failed"}
           for record in records for suite in ("smoke", "targeted")):
        sys.exit(1)


if __name__ == "__main__":
    main()
