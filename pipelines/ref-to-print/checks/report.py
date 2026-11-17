"""Shared report and schema helpers. Every check uses these so reports look the same.

Exit codes for every check CLI: 0 = passed, 1 = a rule failed, 2 = bad input or usage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
PRINTERS = ROOT / "printer"

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2


def load_schema(name: str) -> dict[str, Any]:
    """Load contracts/<name>.schema.json, e.g. load_schema('check.report')."""
    return json.loads((CONTRACTS / f"{name}.schema.json").read_text())


def validate(doc: dict[str, Any], name: str) -> None:
    """Raise jsonschema.ValidationError if doc does not match contracts/<name>.schema.json."""
    jsonschema.validate(doc, load_schema(name))


def load_json(path: str | Path, schema: str | None = None) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text())
    if schema:
        validate(doc, schema)
    return doc


def load_printer(name: str) -> dict[str, Any]:
    """Load printer/<name>; name may be given with or without .json."""
    if not name.endswith(".json"):
        name += ".json"
    return json.loads((PRINTERS / name).read_text())


def result(
    part: str,
    rule: str,
    passed: bool,
    value: float | None = None,
    limit: float | None = None,
    unit: str = "",
    note: str = "",
) -> dict[str, Any]:
    return {
        "part": part,
        "rule": rule,
        "passed": bool(passed),
        "value": None if value is None else float(value),
        "limit": None if limit is None else float(limit),
        "unit": unit,
        "note": note,
    }


def make_report(check: str, results: list[dict[str, Any]], job: str | None = None) -> dict[str, Any]:
    report = {
        "schema": "check.report/1",
        "check": check,
        "job": job,
        "passed": bool(results) and all(r["passed"] for r in results),
        "results": results,
    }
    validate(report, "check.report")
    return report


def finish(report: dict[str, Any], out: str | Path | None = None) -> int:
    """Write the report to `out` (or stdout when None) and return the exit code."""
    text = json.dumps(report, indent=2)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n")
    else:
        sys.stdout.write(text + "\n")
    return EXIT_PASS if report["passed"] else EXIT_FAIL
