"""Job state: load, validate, save atomically. Only r2p writes job.state.json."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

from checks.report import validate

ORDER = ["S0", "S1", "G1", "S2", "G2", "S3", "G3", "S4"]
NEEDS = {"S1": "modelling", "S4": "person"}
GATES = ["G1", "G2", "G3"]


class UserError(Exception):
    """A mistake the caller can fix; printed as one line, no traceback."""

    def __init__(self, msg: str, code: int = 2) -> None:
        super().__init__(msg)
        self.code = code


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def state_path(job_dir: Path) -> Path:
    return job_dir / "job.state.json"


def new_state(job: str, params: dict[str, Any]) -> dict[str, Any]:
    """All steps pending, attempts 0, `needs` set; the caller marks S0 done."""
    steps = {s: {"status": "pending", "attempts": 0, "needs": NEEDS.get(s, "none")} for s in ORDER}
    return {"schema": "job.state/1", "job": job, "escalated": False,
            "escalation_reason": None, "params": dict(params), "steps": steps}


def check_state(state: dict[str, Any]) -> None:
    try:
        validate(state, "job.state")
    except jsonschema.ValidationError as e:
        raise UserError(f"state is invalid: {e.message}") from e


def load(job_dir: Path) -> dict[str, Any]:
    path = state_path(job_dir)
    if not path.is_file():
        raise UserError(f"no state for this job ({path}); run: python -m r2p init {job_dir.name}")
    try:
        state = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise UserError(f"{path} is not valid JSON: {e}") from e
    check_state(state)
    return state


def save(job_dir: Path, state: dict[str, Any]) -> None:
    """Validate, then write to a temp file and os.replace it over the state file."""
    check_state(state)
    path = state_path(job_dir)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.replace(tmp, path)


def current(state: dict[str, Any]) -> str | None:
    """First step that is not done, or None when the job is complete."""
    for s in ORDER:
        if state["steps"][s]["status"] != "done":
            return s
    return None


def require_ready(state: dict[str, Any], step: str) -> None:
    """Raise unless every step before `step` is done."""
    for s in ORDER[: ORDER.index(step)]:
        if state["steps"][s]["status"] != "done":
            raise UserError(f"{step} cannot run yet: {s} is {state['steps'][s]['status']}. "
                            f"Current step is {current(state)}.")


def update(state: dict[str, Any], step: str, status: str, report: str | None = None,
           note: str | None = None) -> None:
    """Set status, attempts + 1, report, note and time on one step."""
    st = state["steps"][step]
    st.update(status=status, attempts=st["attempts"] + 1, updated=now(), note=note)
    if report is not None:
        st["report"] = report
