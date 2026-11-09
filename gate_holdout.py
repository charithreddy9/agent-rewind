"""Evaluate frozen rewind test selectors on separate synthetic fixtures."""

from fractions import Fraction
import json

from gate_benchmark import Scenario, measure


def holdout():
    before = '{"encoding": "latin1", "document": "ascii"}\n'
    after = before.replace("latin1", "utf8")
    smoke = "assert isinstance(json.loads(Path('target.json').read_text()), dict)"
    contract = (
        "settings = json.loads(Path('target.json').read_text())\n"
        "content = '東京' if settings['document'] == 'unicode' else 'hello'\n"
        "content.encode(settings['encoding'])"
    )
    # Separate lines allow the encoding and later document changes to merge.
    before = before.replace(", ", ",\n\n ")
    after = after.replace(", ", ",\n\n ")
    encoding = (
        Scenario("Unicode document", True, before, after, after.replace("ascii", "unicode"),
                 smoke, contract, target="target.json"),
        Scenario("ASCII document", False, before, after, after, smoke, contract, target="target.json"),
    )

    before = "def permits(total, ceiling):\n    return total < ceiling\n"
    after = before.replace(" < ", " <= ")
    smoke = "from target import permits\nassert permits(1, 5)"
    contract = "from consumer import can_submit\nassert can_submit()"
    ceiling = (
        Scenario("Consumer uses exact ceiling", True, before, after, after, smoke, contract,
                 "from target import permits\n\ndef can_submit():\n    return permits(5, 5)\n"),
        Scenario("Consumer stays below ceiling", False, before, after, after, smoke, contract,
                 "from target import permits\n\ndef can_submit():\n    return permits(4, 5)\n"),
    )

    before = "def normalize(tag):\n    return tag.lower()\n"
    after = before.replace("tag.lower()", "tag.strip().lower()")
    smoke = "from target import normalize\nassert normalize('TEST') == 'test'"
    contract = "from consumer import resolve\nassert resolve() == 'ready'"
    normalization = (
        Scenario("Padded tag input", True, before, after, after, smoke, contract,
                 "from target import normalize\n\ndef resolve():\n    return normalize(' READY ')\n"),
        Scenario("Unpadded tag input", False, before, after, after, smoke, contract,
                 "from target import normalize\n\ndef resolve():\n    return normalize('READY')\n"),
    )

    before = "def encode(flag):\n    return 'true' if flag else ''\n"
    after = before.replace("else ''", "else 'false'")
    smoke = "from target import encode\nassert encode(True) == 'true'"
    contract = "from consumer import serialized\nassert json.loads(serialized()) is not None"
    serialization = (
        Scenario("Consumer serializes false", True, before, after, after, smoke, contract,
                 "from target import encode\n\ndef serialized():\n    return encode(False)\n"),
        Scenario("Consumer serializes true", False, before, after, after, smoke, contract,
                 "from target import encode\n\ndef serialized():\n    return encode(True)\n"),
    )
    return (*encoding, *ceiling, *normalization, *serialization)


def main() -> None:
    records = []
    for index, scenario in enumerate(holdout()):
        checks = {"smoke": scenario.smoke, "contract": scenario.contract,
                  "environment": "assert Path.cwd().is_dir()"}
        names = list(checks)
        # Rotate by pair. Both members of each pair see the same order.
        rotation = (index // 2) % len(names)
        order = names[rotation:] + names[:rotation]
        record = measure(scenario, True, {name: checks[name] for name in order})
        record["pool_order"] = order
        records.append(record)
    if any(run["status"] not in {"passed", "candidate_failed"}
           for record in records for run in record["results"].values()):
        print(json.dumps(records, indent=2))
        raise SystemExit("At least one selected or pool check could not be evaluated")

    summary = {}
    for label in ("broken", "valid"):
        group = [record for record in records if record["label"] == label]
        flags = {
            method: sum(record["results"][method]["status"] == "candidate_failed" for record in group)
            for method in ("fixed", "changed_lines", "one_context_line")
        }
        # Enumerate pool outcomes to compute the expectation for one uniformly
        # chosen check, without relying on one random seed.
        uniform = sum(
            Fraction(sum(record["results"][f"pool_{name}"]["status"] == "candidate_failed"
                         for name in record["pool_order"]), len(record["pool_order"]))
            for record in group
        )
        summary[label] = {"cases": len(group), "flags": flags,
                          "uniform_random_expected_flags": str(uniform)}
    print(json.dumps({"summary": summary, "cases": records}, indent=2))


if __name__ == "__main__":
    main()
