"""Opt-in checks for proposed rewinds of JSON configuration files."""

import json
from math import isfinite
from pathlib import Path, PurePosixPath


Rules = dict[str, list[tuple[str, str]]]


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def reject_constant(value: str):
    raise ValueError(f"unsupported JSON constant: {value}")


def parse_json(text: str):
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)


def load_rules(path: Path) -> Rules:
    config = parse_json(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict) or not config:
        raise ValueError("rules must be a nonempty JSON object keyed by repository-relative file paths")
    rules: Rules = {}
    for name, checks in config.items():
        relative = PurePosixPath(name)
        if (not relative.parts or relative.is_absolute() or relative.as_posix() != name or ".." in relative.parts
                or "\\" in name or ":" in name or "\0" in name):
            raise ValueError(f"invalid repository-relative path: {name!r}")
        if not isinstance(checks, list) or not checks:
            raise ValueError(f"{name!r} must contain a nonempty list of [lower, upper] key pairs")
        for pair in checks:
            if (not isinstance(pair, list) or len(pair) != 2
                    or not all(isinstance(key, str) and key.strip() for key in pair)):
                raise ValueError(f"invalid [lower, upper] key pair for {name!r}")
        rules[name] = [(lower, upper) for lower, upper in checks]
    return rules


def check_json(text: str, checks: list[tuple[str, str]]) -> list[str]:
    try:
        data = parse_json(text)
    except ValueError as exc:
        return [f"Invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return ["Expected a JSON object."]
    issues = []
    for lower, upper in checks:
        invalid_keys = []
        for key in dict.fromkeys((lower, upper)):
            value = data.get(key)
            if type(value) not in (int, float) or (isinstance(value, float) and not isfinite(value)):
                invalid_keys.append(key)
        issues.extend(f"{key} must be a finite number." for key in invalid_keys)
        if not invalid_keys and data[lower] > data[upper]:
            issues.append(f"{lower} ({data[lower]}) must be <= {upper} ({data[upper]}).")
    return issues
