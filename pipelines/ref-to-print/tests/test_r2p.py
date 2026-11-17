"""Tests for the r2p driver. run_cmd is replaced by a fake; no real check runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from checks.report import load_json, validate
from r2p import cli

BRIEF = {"schema": "brief/1", "job": "demo", "units": "mm", "printer": "ender3-v3se.json",
         "target": {"bbox_mm": [10, 10, 10]}, "parts": [{"name": "cube"}],
         "constraints": {"min_wall_mm": 1.2, "clearance_mm": 0.3, "max_triangles_per_part": 20000}}
NEXT_S1 = "A modelling agent must do S1 (form modelling in Maya), then run: python -m r2p mark demo S1 done"


class Fake:
    """Stands in for run_cmd: writes a one-result report to --out and returns `rc`."""

    def __init__(self) -> None:
        self.rc = 0
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], cwd: Path) -> tuple[int, str, str]:
        self.calls.append(argv)
        if "--out" in argv:
            check = argv[argv.index("-m") + 1].split(".")[-1].removesuffix("_check")
            ok = self.rc == 0
            rep = {"schema": "check.report/1", "check": check, "job": "demo", "passed": ok,
                   "results": [{"part": "cube", "rule": "watertight", "passed": ok, "note": "" if ok else "holes"}]}
            Path(argv[argv.index("--out") + 1]).write_text(json.dumps(rep))
        return self.rc, "", "boom" if self.rc > 1 else ""


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """Jobs dir with a brief, a Fake runner, and a helper that runs r2p and returns (code, out)."""
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "brief.json").write_text(json.dumps(BRIEF))
    monkeypatch.setenv("R2P_JOBS_DIR", str(tmp_path))
    fake = Fake()
    monkeypatch.setattr(cli, "run_cmd", fake)

    def r2p(*args: str) -> tuple[int, str]:
        capsys.readouterr()
        code = cli.main(list(args))
        cap = capsys.readouterr()
        # the state file must stay valid after every command
        path = tmp_path / "demo" / "job.state.json"
        if path.exists():
            load_json(path, "job.state")
        return code, cap.out + cap.err

    r2p.fake, r2p.dir = fake, tmp_path / "demo"  # type: ignore[attr-defined]
    return r2p


def state(env: Any) -> dict[str, Any]:
    return json.loads((env.dir / "job.state.json").read_text())


def advance(env: Any, *steps: str) -> None:
    for s in steps:
        assert env("mark", "demo", s, "done")[0] == 0


def test_init_and_status(env):
    assert env("init", "demo")[0] == 0
    s = state(env)
    assert s["steps"]["S0"]["status"] == "done" and s["steps"]["S1"]["needs"] == "modelling"
    assert s["steps"]["S4"]["needs"] == "person" and s["params"]["clearance_mm"] == 0.3
    code, out = env("status", "demo")
    assert code == 0 and f"NEXT: {NEXT_S1}" in out
    assert env("init", "demo")[0] == 2 and env("init", "demo", "--force")[0] == 0


def test_missing_job_and_state(env):
    assert env("status", "demo")[0] == 2
    assert env("status", "nope")[0] == 2


def test_out_of_order(env):
    env("init", "demo")
    code, out = env("gate", "demo", "G1")
    assert code == 2 and "S1" in out
    assert env("mark", "demo", "S2", "done")[0] == 2
    assert env("run", "demo", "S3")[0] == 2
    assert env("run", "demo", "S1")[0] == 2 and "modelling" in env("run", "demo", "S1")[1]


def test_gate_g1_pass(env):
    env("init", "demo")
    code, out = env("mark", "demo", "S1", "done")
    assert code == 0
    assert "NEXT: python -m r2p gate demo G1" in env("status", "demo")[1]
    code, out = env("gate", "demo", "G1")
    assert code == 0 and "G1: PASSED" in out
    assert state(env)["steps"]["G1"]["status"] == "done"
    rep = load_json(env.dir / "reports" / "G1.check.report.json", "check.report")
    assert rep["check"] == "gate" and rep["passed"]
    assert [r["rule"] for r in rep["results"]] == ["mesh.watertight"]
    argv = env.fake.calls[0]
    assert "--min-wall" in argv and "1.2" in argv and "--max-triangles" in argv


def test_gate_g2_runs_three_checks(env):
    env("init", "demo")
    advance(env, "S1")
    assert env("gate", "demo", "G1")[0] == 0
    advance(env, "S2")
    assert env("gate", "demo", "G2")[0] == 0
    rep = load_json(env.dir / "reports" / "G2.check.report.json", "check.report")
    assert [r["rule"] for r in rep["results"]] == ["mesh.watertight", "fit.watertight", "mate.watertight"]


def test_escalation_and_resume(env):
    env("init", "demo")
    advance(env, "S1")
    env.fake.rc = 1
    code, out = env("gate", "demo", "G1")
    assert code == 1 and "FAIL cube mesh.watertight" in out and "G1: FAILED (attempt 1 of 2)" in out
    assert env("status", "demo")[0] == 0
    code, out = env("gate", "demo", "G1")
    assert code == 1 and "attempt 2 of 2" in out
    assert state(env)["escalated"] and (env.dir / "escalate.md").is_file()
    code, out = env("status", "demo")
    assert code == 3 and "STOPPED:" in out and "NEXT: none (see escalate.md)" in out
    assert env("gate", "demo", "G1")[0] == 3 and env("run", "demo", "S3")[0] == 3
    env.fake.rc = 0
    assert env("resume", "demo", "--note", "fixed the mesh")[0] == 0
    assert not state(env)["escalated"] and state(env)["steps"]["G1"]["attempts"] == 0
    assert env("gate", "demo", "G1")[0] == 0


def test_check_error_counts_as_failure(env):
    env("init", "demo")
    advance(env, "S1")
    env.fake.rc = 2
    code, out = env("gate", "demo", "G1")
    assert code == 1 and "boom" in out and state(env)["steps"]["G1"]["attempts"] == 1


def test_run_null_cmd_leaves_state(env, tmp_path, monkeypatch):
    # A stage with no command yet (as S2 was before the code route existed).
    stages = tmp_path / "stages.json"
    stages.write_text(json.dumps({"S2": {"cmd": None, "todo": "The script is not written yet; do S2 by hand."}}))
    monkeypatch.setattr(cli, "STAGES", stages)
    env("init", "demo")
    advance(env, "S1")
    env("gate", "demo", "G1")
    before = state(env)
    code, out = env("run", "demo", "S2")
    assert code == 2 and "not written yet" in out and state(env) == before


def test_run_s3(env):
    env("init", "demo")
    advance(env, "S1")
    env("gate", "demo", "G1")
    advance(env, "S2")
    env("gate", "demo", "G2")
    assert env("run", "demo", "S3")[0] == 0
    assert state(env)["steps"]["S3"]["status"] == "done"
    assert env.fake.calls[-1][1:3] == ["-m", "slicer.slice_check"]
    assert "NEXT: python -m r2p gate demo G3" in env("status", "demo")[1]


def test_set_resets_from_s2(env):
    env("init", "demo")
    advance(env, "S1")
    env("gate", "demo", "G1")
    advance(env, "S2")
    env("gate", "demo", "G2")
    assert env("set", "demo", "clearance_mm=0.25", "label=x")[0] == 0
    s = state(env)
    assert s["params"]["clearance_mm"] == 0.25 and isinstance(s["params"]["clearance_mm"], float)
    assert s["steps"]["S2"]["status"] == s["steps"]["G2"]["status"] == "pending"
    assert s["steps"]["G1"]["status"] == "done" and s["steps"]["S2"]["attempts"] == 0
    assert env("set", "demo", "bad")[0] == 2


def prepare_g3(env: Any) -> None:
    env("init", "demo")
    advance(env, "S1")
    env("gate", "demo", "G1")
    advance(env, "S2")
    env("gate", "demo", "G2")
    advance(env, "S3")


def test_g3_reads_slice_report(env):
    prepare_g3(env)
    code, out = env("gate", "demo", "G3")
    assert code == 1 and "slice.present" in out
    assert state(env)["steps"]["G3"]["status"] == "failed"
    plate = {"input": "plate1.stl", "passed": True, "errors": []}
    rep = {"schema": "slice.report/1", "slicer": "orca", "passed": True, "plates": [plate]}
    (env.dir / "slice.report.json").write_text(json.dumps(rep))
    assert env("gate", "demo", "G3")[0] == 0
    assert state(env)["steps"]["G3"]["status"] == "done"
    out_rep = load_json(env.dir / "reports" / "G3.check.report.json", "check.report")
    assert [r["part"] for r in out_rep["results"]] == ["plate1.stl"]
    assert "person must do S4" in env("status", "demo")[1]


def test_mark_gate_refused_and_json(env):
    env("init", "demo")
    assert env("mark", "demo", "G1", "done")[0] == 2
    code, out = env("status", "demo", "--json")
    doc = json.loads(out)
    assert code == 0 and {"job", "current", "steps", "last_gate", "next", "escalated"} <= set(doc)
    assert doc["current"] == "S1" and doc["next"] == NEXT_S1 and doc["last_gate"] is None
    validate(state(env), "job.state")


def test_run_that_fails_twice_escalates(tmp_path, monkeypatch):
    """A stage that keeps failing (for example no slicer installed) must stop the driver."""
    import shutil
    from checks import report as rp
    from r2p import cli

    job = tmp_path / "chain-chomp"
    job.mkdir()
    shutil.copy(rp.ROOT / "jobs" / "chain-chomp" / "brief.json", job / "brief.json")
    monkeypatch.setenv("R2P_JOBS_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "run_cmd", lambda argv, cwd: (2, "", "no slicer found"))
    assert cli.main(["init", "chain-chomp"]) == 0
    state = json.loads((job / "job.state.json").read_text())
    for step in ("S1", "G1", "S2", "G2"):
        state["steps"][step]["status"] = "done"
    (job / "job.state.json").write_text(json.dumps(state))
    assert cli.main(["run", "chain-chomp", "S3"]) == 1
    assert cli.main(["run", "chain-chomp", "S3"]) == 1
    assert (job / "escalate.md").exists()
    assert cli.main(["status", "chain-chomp"]) == 3
    assert cli.main(["run", "chain-chomp", "S3"]) == 3
    assert cli.main(["resume", "chain-chomp", "--note", "slicer installed"]) == 0
    assert cli.main(["status", "chain-chomp"]) == 0
