"""r2p: drive a ref-to-print job. Loop: `r2p status JOB`, run the NEXT command, repeat."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from checks.report import load_json, make_report, result
from r2p import state as st
from r2p.state import GATES, ORDER, UserError

ROOT = Path(__file__).resolve().parent.parent
STAGES = Path(__file__).with_name("stages.json")
MAX_ATTEMPTS = 2
DESC = {"S0": "brief", "S1": "form modelling in Maya", "G1": "form gate", "S2": "print prep in Fusion",
        "G2": "parts gate", "S3": "slicing", "G3": "slice gate", "S4": "physical print"}


def run_cmd(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    """The only place a subprocess starts. Tests replace this."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    except OSError as e:
        return 127, "", str(e)
    return p.returncode, p.stdout, p.stderr


class Ctx:
    """Paths and global options for one command."""

    def __init__(self, jobs_dir: str | None, job: str) -> None:
        self.explicit = jobs_dir
        base = Path(jobs_dir or os.environ.get("R2P_JOBS_DIR") or ROOT / "jobs").resolve()
        self.job, self.dir = job, base / job

    def cmd(self, text: str) -> str:
        """A command line to print, carrying --jobs-dir when the user gave one."""
        flag = f"--jobs-dir {self.explicit} " if self.explicit else ""
        return f"python -m r2p {flag}{text}"


def load(ctx: Ctx) -> dict[str, Any]:
    if not ctx.dir.is_dir():
        raise UserError(f"no job folder {ctx.dir}")
    return st.load(ctx.dir)


def refuse_if_escalated(state: dict[str, Any]) -> None:
    if state["escalated"]:
        raise UserError(f"STOPPED: {state['escalation_reason']}. See escalate.md; a person runs resume.", 3)


def step_arg(step: str) -> str:
    step = step.upper()
    if step not in ORDER:
        raise UserError(f"unknown step {step}; use one of {' '.join(ORDER)}")
    return step


def rel(ctx: Ctx, path: Path) -> str:
    return str(path.relative_to(ctx.dir))


# ---------------------------------------------------------------- status

def last_gate(state: dict[str, Any]) -> dict[str, Any] | None:
    seen = [(s, state["steps"][s]) for s in GATES if state["steps"][s]["status"] != "pending"]
    if not seen:
        return None
    gate, step = max(seen, key=lambda x: x[1].get("updated") or "")
    return {"gate": gate, "passed": step["status"] == "done", "report": step.get("report")}


def next_command(ctx: Ctx, state: dict[str, Any]) -> str:
    cur = st.current(state)
    j = ctx.job
    if state["escalated"]:
        return "none (see escalate.md)"
    if cur is None:
        return "none (job complete)"
    mark = ctx.cmd(f"mark {j} {cur} done")
    if state["steps"][cur]["needs"] == "modelling":
        return f"A modelling agent must do {cur} ({DESC[cur]}), then run: {mark}"
    if state["steps"][cur]["needs"] == "person":
        return f"A person must do {cur} ({DESC[cur]}), then run: {mark}"
    if cur in GATES:
        run = ctx.cmd(f"gate {j} {cur}")
        if state["steps"][cur]["status"] == "failed":
            rep = state["steps"][cur].get("report")
            return (f"{cur} failed. Read {rep}, redo the earlier step it blames "
                    f"(python -m r2p set {j} KEY=VALUE changes a param), then run: {run}")
        return run
    stage = json.loads(STAGES.read_text()).get(cur, {})
    if stage.get("cmd") is None:
        return f"{cur} ({DESC[cur]}) has no script yet: do it by hand, then run: {mark}"
    return ctx.cmd(f"run {j} {cur}")


def cmd_status(ctx: Ctx, a: argparse.Namespace) -> int:
    state = load(ctx)
    nxt, lg, cur = next_command(ctx, state), last_gate(state), st.current(state)
    if a.json:
        print(json.dumps({"job": ctx.job, "current": cur, "steps": state["steps"], "last_gate": lg,
                          "next": nxt, "escalated": state["escalated"],
                          "reason": state["escalation_reason"]}, indent=2))
    else:
        print(f"Job: {ctx.job}")
        for s in ORDER:
            print(f"  {s} {DESC[s]}: {state['steps'][s]['status']}")
        print(f"Current step: {cur or 'none'}")
        if lg:
            print(f"Last gate: {lg['gate']} {'passed' if lg['passed'] else 'failed'} ({lg['report']})")
        if state["escalated"]:
            print(f"STOPPED: {state['escalation_reason']}")
        print(f"NEXT: {nxt}")
    return 3 if state["escalated"] else 0


# ---------------------------------------------------------------- init, mark, set, resume

def cmd_init(ctx: Ctx, a: argparse.Namespace) -> int:
    brief = ctx.dir / "brief.json"
    if not brief.is_file():
        raise UserError(f"missing {brief}")
    if st.state_path(ctx.dir).exists() and not a.force:
        raise UserError("state file already exists; use --force to replace it")
    try:
        doc = load_json(brief, "brief")
    except Exception as e:  # bad JSON or schema mismatch
        raise UserError(f"brief.json is invalid: {getattr(e, 'message', e)}") from e
    state = st.new_state(ctx.job, doc.get("constraints", {}))
    st.update(state, "S0", "done", note="brief validated")
    st.save(ctx.dir, state)
    print(f"Created {st.state_path(ctx.dir)}; S0 done.")
    print("NEXT: " + next_command(ctx, state))
    return 0


def cmd_mark(ctx: Ctx, a: argparse.Namespace) -> int:
    step = step_arg(a.step)
    if step in GATES:
        raise UserError(f"{step} is a gate; only 'gate' can set it: {ctx.cmd(f'gate {ctx.job} {step}')}")
    state = load(ctx)
    st.require_ready(state, step)
    st.update(state, step, a.status, note=a.note)
    st.save(ctx.dir, state)
    print(f"{step} marked {a.status}.")
    print("NEXT: " + next_command(ctx, state))
    return 0


def parse_value(text: str) -> Any:
    for conv in (int, float):
        try:
            return conv(text)
        except ValueError:
            pass
    return text


def cmd_set(ctx: Ctx, a: argparse.Namespace) -> int:
    state = load(ctx)
    changed = False
    for pair in a.pairs:
        key, sep, val = pair.partition("=")
        if not sep or not key:
            raise UserError(f"expected KEY=VALUE, got '{pair}'")
        new = parse_value(val)
        changed |= state["params"].get(key) != new
        state["params"][key] = new
    if changed:
        for s in ORDER[ORDER.index("S2"):]:
            step = state["steps"][s]
            if step["status"] in ("done", "failed"):
                state["steps"][s] = {"status": "pending", "attempts": 0, "needs": step["needs"]}
                print(f"{s} reset to pending.")
    st.save(ctx.dir, state)
    print("params: " + json.dumps(state["params"]))
    print("NEXT: " + next_command(ctx, state))
    return 0


def cmd_resume(ctx: Ctx, a: argparse.Namespace) -> int:
    state = load(ctx)
    if not state["escalated"]:
        raise UserError("job is not escalated; nothing to resume")
    for s in ORDER:  # gates and run steps alike
        if state["steps"][s]["status"] == "failed":
            state["steps"][s]["attempts"] = 0
            state["steps"][s]["note"] = f"resumed: {a.note}"
            break
    state["escalated"], state["escalation_reason"] = False, None
    st.save(ctx.dir, state)
    print("Resumed.")
    print("NEXT: " + next_command(ctx, state))
    return 0


# ---------------------------------------------------------------- gate

def gate_checks(ctx: Ctx, gate: str, params: dict[str, Any]) -> list[tuple[str, list[str], Path]]:
    """(check name, argv, report path) for each subprocess check of a gate."""
    rep = ctx.dir / "reports"
    base = ["--job-dir", str(ctx.dir), "--job", ctx.job]
    py = sys.executable

    def mesh(manifest: str, out: Path) -> tuple[str, list[str], Path]:
        argv = [py, "-m", "checks.mesh_check", "--job-dir", str(ctx.dir), "--manifest", manifest,
                "--job", ctx.job, "--out", str(out)]
        for flag, key in (("--min-wall", "min_wall_mm"), ("--max-triangles", "max_triangles_per_part")):
            if key in params:
                argv += [flag, str(params[key])]
        return "mesh", argv, out

    if gate == "G1":
        return [mesh("form", rep / "G1.mesh.json")]
    out = {n: rep / f"G2.{n}.json" for n in ("fit", "mate")}
    return [mesh("parts", rep / "G2.mesh.json"),
            *[(n, [py, "-m", f"checks.{n}_check", *base, "--out", str(out[n])], out[n]) for n in out]]


def run_checks(ctx: Ctx, gate: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the gate's subprocess checks; every result gets its check name as rule prefix."""
    (ctx.dir / "reports").mkdir(exist_ok=True)
    results: list[dict[str, Any]] = []
    for name, argv, out in gate_checks(ctx, gate, params):
        out.unlink(missing_ok=True)
        rc, _, err = run_cmd(argv, ROOT)
        tail = " ".join(err.strip().splitlines()[-3:])
        try:
            if rc not in (0, 1):
                raise ValueError(f"exit {rc}: {tail}")
            rep = load_json(out, "check.report")
        except Exception as e:  # missing or bad report counts as an error result
            results.append(result("-", f"{name}.error", False, note=f"{name} check error: {e}"[:300]))
            continue
        results += [{**r, "rule": f"{name}.{r['rule']}"} for r in rep["results"]]
    return results


def slice_results(ctx: Ctx) -> list[dict[str, Any]]:
    path = ctx.dir / "slice.report.json"
    if not path.is_file():
        return [result("slice.report.json", "slice.present", False, note="missing; run the S3 slice step")]
    try:
        rep = load_json(path, "slice.report")
    except Exception as e:
        return [result("slice.report.json", "slice.valid", False, note=f"invalid: {e}"[:300])]
    out = [result(p["input"], "slice.plate", p["passed"], note="; ".join(p.get("errors", [])))
           for p in rep["plates"]]
    if not out or (not rep["passed"] and all(r["passed"] for r in out)):
        out.append(result("slice.report.json", "slice.passed", rep["passed"], note="slicer reported failure"))
    return out


def cmd_gate(ctx: Ctx, a: argparse.Namespace) -> int:
    gate = step_arg(a.gate)
    if gate not in GATES:
        raise UserError(f"{gate} is not a gate; use G1, G2 or G3")
    state = load(ctx)
    refuse_if_escalated(state)
    st.require_ready(state, gate)
    results = slice_results(ctx) if gate == "G3" else run_checks(ctx, gate, state["params"])
    report = make_report("gate", results, ctx.job)
    path = ctx.dir / "reports" / f"{gate}.check.report.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    failed = [r for r in results if not r["passed"]]
    for r in failed:
        print(f"FAIL {r['part']} {r['rule']}: {r['note'] or r.get('value')} (limit {r.get('limit')})")
    ok = report["passed"]
    st.update(state, gate, "done" if ok else "failed", rel(ctx, path),
              None if ok else "failed: " + ", ".join(f"{r['part']} {r['rule']}" for r in failed)[:400])
    attempts = state["steps"][gate]["attempts"]
    if not ok and attempts >= MAX_ATTEMPTS:
        state["escalated"] = True
        state["escalation_reason"] = f"{gate} failed {attempts} times"
        write_escalation(ctx, state, gate, failed)
    st.save(ctx.dir, state)
    print(f"{gate}: PASSED" if ok else f"{gate}: FAILED (attempt {attempts} of {MAX_ATTEMPTS})")
    if state["escalated"]:
        print("STOPPED: escalated. NEXT: none (see escalate.md)")
    return 0 if ok else 1


def write_escalation(ctx: Ctx, state: dict[str, Any], gate: str, failed: list[dict[str, Any]]) -> None:
    lines = [f"Job {ctx.job} is stopped: {gate} failed {state['steps'][gate]['attempts']} times.", "",
             "Failed results:"]
    lines += [f"- {r['part']} {r['rule']}: {r['note']} (value {r.get('value')}, limit {r.get('limit')})"
              for r in failed]
    lines += ["", "What was tried (notes in the state file):"]
    lines += [f"- {s} {state['steps'][s]['status']}, {state['steps'][s]['attempts']} attempts: "
              f"{state['steps'][s].get('note') or '-'}" for s in ORDER]
    lines += ["", f"Params: {json.dumps(state['params'])}", "",
              "A person or a stronger model must look. After fixing, run: "
              f"{ctx.cmd(f'resume {ctx.job} --note TEXT')}"]
    (ctx.dir / "escalate.md").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------- run

def fill(item: str, ctx: Ctx, params: dict[str, Any]) -> str:
    def param(m: re.Match[str]) -> str:
        if m.group(1) not in params:
            raise UserError(f"param {m.group(1)} is not set; use: python -m r2p set {ctx.job} {m.group(1)}=VALUE")
        return str(params[m.group(1)])
    item = re.sub(r"\{param:(\w+)\}", param, item)
    return (item.replace("{job_dir}", str(ctx.dir)).replace("{job}", ctx.job)
            .replace("{python}", sys.executable))


def cmd_run(ctx: Ctx, a: argparse.Namespace) -> int:
    step = step_arg(a.step)
    state = load(ctx)
    refuse_if_escalated(state)
    if step in GATES or step == "S0":
        raise UserError(f"{step} is not a run step; gates use: {ctx.cmd(f'gate {ctx.job} G1|G2|G3')}")
    needs = state["steps"][step]["needs"]
    if needs != "none":
        raise UserError(f"{step} needs {needs}: a {'modelling agent' if needs == 'modelling' else 'person'} "
                        f"does it, then run: {ctx.cmd(f'mark {ctx.job} {step} done')}")
    st.require_ready(state, step)
    stage = json.loads(STAGES.read_text()).get(step)
    if not stage:
        raise UserError(f"no stage entry for {step} in stages.json")
    if stage["cmd"] is None:
        print(stage.get("todo", f"{step} has no command yet").replace("JOB", ctx.job))
        return 2
    argv = [fill(i, ctx, state["params"]) for i in stage["cmd"]]
    rc, out, err = run_cmd(argv, ROOT)
    ok = rc == 0
    tail = " ".join(err.strip().splitlines()[-3:])
    st.update(state, step, "done" if ok else "failed", note=None if ok else f"exit {rc}: {tail}"[:400])
    attempts = state["steps"][step]["attempts"]
    if not ok and attempts >= MAX_ATTEMPTS:  # a driver must not retry a broken stage forever
        state["escalated"] = True
        state["escalation_reason"] = f"{step} failed {attempts} times"
        write_escalation(ctx, state, step, [{"part": step, "rule": "run", "note": f"exit {rc}: {tail}"}])
    st.save(ctx.dir, state)
    print(f"{step}: {'done' if ok else f'FAILED (exit {rc}) {tail}'}")
    print("NEXT: " + next_command(ctx, state))
    return 0 if ok else 1


# ---------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="r2p", description="Drive a ref-to-print job.")
    p.add_argument("--jobs-dir", help="jobs folder (default: $R2P_JOBS_DIR or <project>/jobs)")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name: str, fn: Any, *args: tuple[str, dict[str, Any]]) -> None:
        sp = sub.add_parser(name)
        sp.add_argument("job")
        for flag, kw in args:
            sp.add_argument(flag, **kw)
        sp.set_defaults(fn=fn)

    add("init", cmd_init, ("--force", {"action": "store_true"}))
    add("status", cmd_status, ("--json", {"action": "store_true"}))
    add("gate", cmd_gate, ("gate", {}))
    add("run", cmd_run, ("step", {}))
    add("mark", cmd_mark, ("step", {}), ("status", {"choices": ["done", "failed"]}),
        ("--note", {"default": None}))
    add("set", cmd_set, ("pairs", {"nargs": "+", "metavar": "KEY=VALUE"}))
    add("resume", cmd_resume, ("--note", {"required": True}))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(Ctx(args.jobs_dir, args.job), args)
    except UserError as e:
        print(str(e), file=sys.stderr)
        return e.code
    except OSError as e:
        print(f"file error: {e}", file=sys.stderr)
        return 2
