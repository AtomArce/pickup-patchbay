"""Clearance test coupon: a plate with a row of holes and a matching peg.

Print the plate flat, try the peg in each hole starting from the chamfered end. The smallest
gap that drops in and turns freely by hand becomes clearance_mm for every joint in the pipeline.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterable

import trimesh

from gen.common import cylinder_between, difference, part, save_parts, union

DEFAULT_GAPS = (0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50)
PLATE_T = 6.0
PLATE_W = 18.0  # Y. Widened from 16 so the dimples keep 1.75 mm wall to the holes and 1.25 mm to the edge
FIRST_X = 10.0  # centre of hole 1 from the plate's -X end
PITCH = 14.0
CHAMFER = 4.0  # 45 degree chamfer on the -X, -Y corner, nearest hole 1
DIMPLE_D = 1.5
DIMPLE_DEPTH = 1.0
# 2.8 mm pitch, not 2 mm: at 2 mm the 1.5 mm dimples leave 0.5 mm walls, below the 1.2 mm min wall.
DIMPLE_PITCH = 2.8
DIMPLE_Y = 6.9  # rows sit 6.9 mm from the centre line; odd holes on +Y, even holes on -Y
SECTIONS = 96
FOOT = 14.0
FOOT_T = 2.0
PEG_H = 12.0
PEG_GAP = 8.0  # clear distance from the plate's -Y edge to the peg foot


def _plate(length: float) -> trimesh.Trimesh:
    """Bar with one 45 degree corner cut. It is convex, so the convex hull is exact."""
    half = PLATE_W / 2
    outline = [(CHAMFER, -half), (length, -half), (length, half), (0.0, half), (0.0, -half + CHAMFER)]
    verts = [(x, y, z) for z in (0.0, PLATE_T) for x, y in outline]
    return trimesh.Trimesh(vertices=verts).convex_hull


def _peg(peg_diameter: float, plate_length: float) -> trimesh.Trimesh:
    """Peg standing on a square foot, placed beside the plate's -Y edge (not touching it)."""
    cx = plate_length / 2
    cy = -PLATE_W / 2 - PEG_GAP - FOOT / 2
    foot = trimesh.creation.box(extents=(FOOT, FOOT, FOOT_T))
    foot.apply_translation((cx, cy, FOOT_T / 2))
    # The post starts 1 mm inside the foot so the boolean union overlaps rather than touching.
    post = cylinder_between((cx, cy, FOOT_T - 1), (cx, cy, FOOT_T + PEG_H), peg_diameter / 2, sections=SECTIONS)
    return union([foot, post])


def build(gaps: Iterable[float] = DEFAULT_GAPS, peg_diameter: float = 8.0) -> list[dict[str, Any]]:
    """Return the coupon_plate and coupon_peg parts in assembled position (mm, Z up)."""
    gaps = sorted(float(g) for g in gaps)
    if not gaps or min(gaps) <= 0:
        raise ValueError("gaps must be a non-empty list of positive numbers")
    if peg_diameter <= 0:
        raise ValueError("peg diameter must be positive")

    xs = [FIRST_X + PITCH * i for i in range(len(gaps))]
    last_count = len(gaps)  # the last hole has the widest dimple row
    end_margin = (last_count - 1) * DIMPLE_PITCH / 2 + DIMPLE_D / 2 + 2.0
    length = xs[-1] + max(FIRST_X, end_margin)
    cutters: list[trimesh.Trimesh] = []
    for x, gap in zip(xs, gaps):
        radius = (peg_diameter + 2 * gap) / 2
        cutters.append(cylinder_between((x, 0, -1), (x, 0, PLATE_T + 1), radius, sections=SECTIONS))
    for i, x in enumerate(xs):
        count = i + 1  # hole number (1-based) gets that many dimples, centred on its X
        side = 1 if i % 2 == 0 else -1  # alternate sides so neighbouring rows do not collide
        for k in range(count):
            dx = (k - (count - 1) / 2) * DIMPLE_PITCH
            cutters.append(cylinder_between(
                (x + dx, side * DIMPLE_Y, PLATE_T - DIMPLE_DEPTH), (x + dx, side * DIMPLE_Y, PLATE_T + 1),
                DIMPLE_D / 2, sections=32,
            ))

    plate = difference(_plate(length), cutters)
    return [
        part("coupon_plate", plate, print_up=(0, 0, 1)),
        part("coupon_peg", _peg(peg_diameter, length), print_up=(0, 0, 1)),
    ]


def _sheet(gaps: list[float], peg_diameter: float, job: str) -> str:
    rows = []
    for i, gap in enumerate(gaps, start=1):
        rows.append(f"| {i} | {i} | {gap:.2f} | {peg_diameter + 2 * gap:.2f} |")
    return "\n".join([
        f"# Clearance coupon ({job})",
        "",
        "## How to print",
        "- Print `coupon_plate` and `coupon_peg` flat on the bed, with no supports.",
        "- Use the same material and settings as the real parts (PLA, 0.4 mm nozzle).",
        "",
        "## How to test",
        "1. Start at the chamfered corner: that end holds the smallest hole.",
        "2. Try the peg in each hole in turn, from hole 1 towards the last hole.",
        "3. Pick the smallest gap where the peg drops in and turns freely by hand.",
        "",
        "Count the dimples on the plate edge to read the hole number (hole 1 has one dimple, hole 2 has two, and so on).",
        "",
        "## Holes",
        "| Hole | Dimples | Gap (mm) | Hole diameter (mm) |",
        "|---|---|---|---|",
        *rows,
        "",
        "## After the test",
        "Run this with the smallest gap that fitted (replace VALUE):",
        "",
        "    python -m r2p set JOB clearance_mm=VALUE",
        "",
        "JOB is the job whose joints should use this gap, for example chain-chomp.",
        "",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the clearance test coupon (mm).")
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--job", default="coupon")
    parser.add_argument("--gaps", default=",".join(str(g) for g in DEFAULT_GAPS), help="comma-separated gaps, mm")
    parser.add_argument("--peg-diameter", type=float, default=8.0)
    args = parser.parse_args(argv)

    try:
        gaps = sorted(float(v) for v in args.gaps.split(",") if v.strip())
        parts = build(gaps, args.peg_diameter)
    except ValueError as exc:
        print(f"coupon: {exc}", file=sys.stderr)
        return 2

    job_dir: Path = args.job_dir
    job_dir.mkdir(parents=True, exist_ok=True)
    save_parts(job_dir, args.job, parts, mates=[], clearance_mm=min(gaps), drop_prefixes=("coupon_",))
    sheet = job_dir / "coupon.md"
    sheet.write_text(_sheet(gaps, args.peg_diameter, args.job))

    print(job_dir / "parts.manifest.json")
    for p in parts:
        print(job_dir / "parts" / f"{p['name']}.stl")
    print(sheet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
