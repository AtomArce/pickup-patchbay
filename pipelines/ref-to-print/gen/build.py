"""Stage S2 without Fusion: build every part the brief names that code can generate.

    python -m gen.build --job-dir jobs/chain-chomp [--milestone M1|M2|M3]

Which generator runs is decided by the part names in the brief (or in one milestone of it):
chain_link -> gen.chain, stake -> gen.chain, body_upper -> gen.head. Clearance and wall come
from the job's state params, so `r2p set JOB clearance_mm=0.25` followed by this stage rebuilds
every joint with the new gap.

The chain is laid on the ground behind the head so the two do not overlap in one manifest.
Hooking the chain through the head's anchor ring and the stake's ring is not done yet.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from checks.report import EXIT_ERROR, load_json, validate
from gen import common
from gen.head import HEAD_PREFIXES


def wanted_parts(brief: dict, milestone: str | None) -> dict[str, int]:
    """Part name -> count, for the whole brief or for one milestone."""
    counts = {p["name"]: p.get("count", 1) for p in brief["parts"]}
    if milestone is None:
        return counts
    for m in brief.get("milestones", []):
        if m["id"] == milestone:
            return {name: counts.get(name, 1) for name in m["parts"]}
    raise ValueError(f"milestone {milestone} is not in the brief")


def build(job_dir: Path, milestone: str | None = None, stage: str = "parts") -> list[str]:
    brief = load_json(job_dir / "brief.json", "brief")
    want = wanted_parts(brief, milestone)
    limits = common.job_limits(job_dir)
    clearance, wall = limits["clearance_mm"], limits["min_wall_mm"]
    radius = max(brief["target"]["bbox_mm"]) / 2
    parts: list[dict] = []
    mates: list[dict] = []
    built: list[str] = []

    if "body_upper" in want:
        from gen.head import build_head

        head_parts, head_mates = build_head(diameter=2 * radius, clearance=clearance)
        parts += head_parts
        mates += head_mates
        built.append("head")

    if "chain_link" in want or "stake" in want:
        from gen import chain

        chain_parts: list[dict] = []
        if "chain_link" in want:
            # M1 is the smallest end-to-end job: two links. Otherwise use the brief's count.
            count = 2 if milestone == "M1" else max(2, want["chain_link"])
            links, link_mates = chain.build_chain(count=count)
            chain_parts += links
            mates += link_mates
            built.append(f"chain x{count}")
        if "stake" in want:
            chain_parts.append(chain.build_stake())
            built.append("stake")
        if "body_upper" in want:
            # Lay the chain on the ground plane behind the head, clear of the hinge and its swing.
            far_x = max(p["mesh"].bounds[1][0] for p in chain_parts)
            shift = (-(radius + 40.0) - far_x, 0.0, -radius)
            for p in chain_parts:
                p["mesh"].apply_translation(shift)
        parts += chain_parts

    if not parts:
        raise ValueError("the brief names no part that a generator can build")
    if stage == "form":
        write_form(job_dir, brief["job"], parts, mates)
        return built
    common.save_parts(
        job_dir, brief["job"], parts, mates, clearance, wall,
        drop_prefixes=(*HEAD_PREFIXES, "chain_link_", "stake"),
    )
    return built


def write_form(job_dir: Path, job: str, parts: list[dict], mates: list[dict]) -> None:
    """Stand in for stage S1 on a job that needs no modelling: write the generated shapes as the
    form meshes (OBJ) with a form manifest, so gate G1 has something real to check."""
    (job_dir / "form").mkdir(parents=True, exist_ok=True)
    entries = []
    for p in parts:
        rel = f"form/{p['name']}.obj"
        p["mesh"].export(job_dir / rel)
        b = p["mesh"].bounds
        entries.append({"name": p["name"], "file": rel, "triangles": int(len(p["mesh"].faces)),
                        "bbox_mm": {"min": [round(float(v), 4) for v in b[0]], "max": [round(float(v), 4) for v in b[1]]}})
    locators = [
        {"name": m["name"], "kind": "hinge_axis", "origin": m["axis_origin"],
         "direction": m["axis_direction"], "parts": [m["a"], m["b"]]}
        for m in mates if m["type"] == "hinge"
    ]
    manifest = {"schema": "form.manifest/1", "job": job, "units": "mm", "up_axis": common.UP_AXIS,
                "parts": entries, "locators": locators}
    validate(manifest, "form.manifest")
    (job_dir / "form.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gen.build", description="Build code-generated parts for a job (S2).")
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--stage", choices=["parts", "form"], default="parts",
                        help="form: write form meshes for G1 (stands in for S1); parts: print-ready parts (S2)")
    parser.add_argument("--milestone", help="Build only the parts of this milestone id from the brief")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_ERROR if exc.code else 0
    try:
        built = build(Path(args.job_dir), args.milestone, args.stage)
    except Exception as exc:  # one plain line for the driver, never a traceback
        print(f"gen.build: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print("built: " + ", ".join(built))
    return 0


if __name__ == "__main__":
    sys.exit(main())
