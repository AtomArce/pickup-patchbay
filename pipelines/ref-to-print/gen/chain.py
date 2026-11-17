"""Print-in-place chain (and a ground stake) for the Chain Chomp figure, built in code.

Closed links cannot be threaded together after printing, so every link is printed
already interlocked, with a gap to its neighbours so the chain comes off the bed free.

Design choices
- Link: stadium-shaped loop of round wire (default 5 mm, inner opening 9 x 20 mm). The
  tube is triangulated directly along the centreline (no booleans), so it is a single
  watertight solid. Round wire rather than square: a round section needs no supports
  at any tilt and keeps the tube mesh simple.
- Links lie along +X. Alternate links are rolled +45 / -45 degrees about X, so each
  link leans the same amount off the bed (no supports) and neighbours cross at 90 degrees.
- Pitch (link-to-link spacing along X) is searched numerically, not guessed: scan
  upward from a pitch where the links overlap until the pair has zero overlap volume and a
  smallest gap >= `gap`, then bisect to the tightest such pitch. Both measures are
  mate_check's own functions. The upper limit is the pitch where the X extents overlap by
  only one wire thickness (past that the links no longer hook through each other).
  Default gap = max(0.4, clearance + 0.1): print-in-place needs more room than a
  hand-assembled joint.
- Whole chain is lowered so its lowest point sits FLAT_MM below Z=0, then cut at Z=0,
  leaving a 0.6 mm flat strip on each link as its footprint on the bed.
- Stake: 14 mm cylinder, 45 mm long overall (30 mm shaft + 15 mm cone), lying on its side
  beside the chain with a fused torus ring (inner opening wire + 4 mm) at the blunt end.
  A flat along the shaft and ring gives it a footprint.

Not done yet: mates joining the chain to the stake and to the head are a later step.
"""

from __future__ import annotations

import argparse
import functools
import sys
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from checks.mate_check import min_gap, overlap_volume
from checks.report import load_json
from gen.common import cylinder_between, difference, intersection, job_limits, part, save_parts, union

FLAT_MM = 0.6
ROLL_DEG = 45.0
STAKE_DIAMETER, STAKE_LENGTH, STAKE_CONE = 14.0, 45.0, 15.0


def _tube(path: np.ndarray, radius: float, sections: int = 20) -> trimesh.Trimesh:
    """Round tube along a closed planar (XY) centreline: watertight by construction."""
    n = len(path)
    tangent = np.roll(path, -1, axis=0) - np.roll(path, 1, axis=0)
    tangent /= np.linalg.norm(tangent, axis=1, keepdims=True)
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0], np.zeros(n)])
    theta = np.linspace(0, 2 * np.pi, sections, endpoint=False)
    ring = (np.cos(theta)[None, :, None] * normal[:, None, :]
            + np.sin(theta)[None, :, None] * np.array([0, 0, 1.0]))  # (n, sections, 3)
    verts = (path[:, None, :] + radius * ring).reshape(-1, 3)  # index = i*sections + k
    faces = []
    for i in range(n):
        j = (i + 1) % n
        for k in range(sections):
            k2 = (k + 1) % sections
            a, b, c, d = i * sections + k, j * sections + k, j * sections + k2, i * sections + k2
            faces += [[a, b, c], [a, c, d]]
    mesh = trimesh.Trimesh(verts, faces, process=False)
    mesh.fix_normals()
    return mesh


def _stadium_path(inner_width: float, inner_length: float, wire: float, arc_pts: int = 40, run_pts: int = 8) -> np.ndarray:
    a = (inner_width + wire) / 2  # centreline arc radius
    half_run = (inner_length + wire) / 2 - a
    ang = np.linspace(-np.pi / 2, np.pi / 2, arc_pts, endpoint=False)
    right = np.column_stack([half_run + a * np.cos(ang), a * np.sin(ang)])
    top = np.column_stack([np.linspace(half_run, -half_run, run_pts, endpoint=False), np.full(run_pts, a)])
    left = np.column_stack([-half_run - a * np.cos(ang), -a * np.sin(ang)])
    bottom = np.column_stack([np.linspace(-half_run, half_run, run_pts, endpoint=False), np.full(run_pts, -a)])
    return np.column_stack([np.vstack([right, top, left, bottom]), np.zeros(2 * arc_pts + 2 * run_pts)])


def _roll(mesh: trimesh.Trimesh, deg: float, x: float) -> trimesh.Trimesh:
    out = mesh.copy()
    out.apply_transform(trimesh.transformations.rotation_matrix(np.radians(deg), [1, 0, 0]))
    out.apply_translation((x, 0, 0))
    return out


def _bed_cut(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    lo, hi = mesh.bounds
    box = trimesh.creation.box(bounds=[[lo[0] - 1, lo[1] - 1, 0], [hi[0] + 1, hi[1] + 1, hi[2] + 1]])
    return intersection([mesh, box])


@functools.cache
def _link(wire: float, inner_width: float, inner_length: float) -> trimesh.Trimesh:
    return _tube(_stadium_path(inner_width, inner_length, wire), wire / 2)


@functools.cache
def find_pitch(wire: float, inner_width: float, inner_length: float, gap: float) -> tuple[float, float]:
    """Return (pitch, measured gap): the tightest interlocked pitch with gap >= `gap`."""
    link = _link(wire, inner_width, inner_length)
    outer = inner_length + 2 * wire
    limit = outer - wire - 0.3  # beyond this the X extents barely overlap: not hooked through

    def measure(p: float) -> float:
        a, b, c = _roll(link, ROLL_DEG, 0.0), _roll(link, -ROLL_DEG, p), _roll(link, ROLL_DEG, 2 * p)
        if overlap_volume(a, b) > 0.01 or overlap_volume(a, c) > 0.01:  # neighbours, then next-but-one
            return 0.0
        return min(min_gap(a, b), min_gap(a, c))

    prev, p = None, inner_length * 0.4
    while p <= limit:
        g = measure(p)
        if g >= gap:
            lo, hi, ghi = (prev if prev is not None else p), p, g
            for _ in range(5):
                mid = (lo + hi) / 2
                gm = measure(mid)
                if gm >= gap:
                    hi, ghi = mid, gm
                else:
                    lo = mid
            return hi, ghi
        prev, p = p, p + 0.25
    raise ValueError(f"gap {gap} mm cannot be achieved with wire {wire}, opening {inner_length} mm long")


def build_chain(count: int = 6, wire: float = 5.0, inner_width: float = 9.0, inner_length: float = 20.0,
                gap: float = 0.4) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if count < 2:
        raise ValueError("count must be at least 2")
    if wire <= 0 or inner_width <= 0 or inner_length <= inner_width:
        raise ValueError("wire and opening must be positive and the opening longer than wide")
    link = _link(wire, inner_width, inner_length)
    pitch, _ = find_pitch(wire, inner_width, inner_length, gap)
    raw = [_roll(link, ROLL_DEG if i % 2 == 0 else -ROLL_DEG, i * pitch) for i in range(count)]
    drop = -FLAT_MM - min(float(m.bounds[0][2]) for m in raw)  # lowest point -> Z = -FLAT_MM
    meshes = []
    for m in raw:
        m.apply_translation((0, 0, drop))
        meshes.append(_bed_cut(m))
    parts = [part(f"chain_link_{i + 1}", m, "grey", (0, 0, 1)) for i, m in enumerate(meshes)]
    mates = [{"name": f"chain_{i + 1}_{i + 2}", "type": "link", "a": f"chain_link_{i + 1}",
              "b": f"chain_link_{i + 2}", "clearance_mm": gap} for i in range(count - 1)]
    return parts, mates


def build_stake(wire: float = 5.0, y_offset: float = 25.0) -> dict[str, Any]:
    """Stake lying along X at Y = y_offset, flat-cut on the bed; ring at the blunt end."""
    r = STAKE_DIAMETER / 2
    shaft_len = STAKE_LENGTH - STAKE_CONE
    zc = r - 1.0  # shaft axis height: 1 mm flat cut below the bed
    shaft = cylinder_between((0, y_offset, zc), (shaft_len, y_offset, zc), r)
    cone = trimesh.creation.cone(radius=r, height=STAKE_CONE, sections=64)
    cone.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))  # +Z axis -> +X
    cone.apply_translation((shaft_len, y_offset, zc))
    tube_r = wire / 2
    ring_major = (wire + 4.0) / 2 + tube_r  # inner opening = wire + 4 mm
    ring = trimesh.creation.torus(ring_major, tube_r, major_sections=64, minor_sections=24)
    ring.apply_translation((3.0 - ring_major - tube_r, y_offset, tube_r - FLAT_MM))
    body = _bed_cut(union([shaft, cone, ring]))
    return part("stake", body, "brown", (0, 0, 1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gen.chain", description="Print-in-place chain and stake.")
    ap.add_argument("--job-dir", required=True)
    ap.add_argument("--job")
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--wire", type=float, default=5.0)
    ap.add_argument("--gap", type=float)
    ap.add_argument("--no-stake", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    job_dir = Path(args.job_dir)
    try:
        limits = job_limits(job_dir)
        brief = job_dir / "brief.json"
        job = args.job or (load_json(brief).get("job") if brief.exists() else None) or "chain"
        gap = args.gap if args.gap is not None else max(0.4, limits["clearance_mm"] + 0.1)
        parts, mates = build_chain(args.count, args.wire, gap=gap)
        if not args.no_stake:
            ymax = max(float(p["mesh"].bounds[1][1]) for p in parts)
            parts.append(build_stake(args.wire, ymax + 8.0 + (STAKE_DIAMETER / 2 + 2.5 + 2.5)))
        save_parts(job_dir, job, parts, mates, gap, limits["min_wall_mm"], drop_prefixes=("chain_link_", "stake"))
    except (ValueError, OSError, KeyError) as exc:
        print(f"gen.chain: {exc}", file=sys.stderr)
        return 2
    measured = min(min_gap(parts[i]["mesh"], parts[i + 1]["mesh"]) for i in range(args.count - 1))
    for p in parts:
        print(f"wrote {p['name']}: {len(p['mesh'].faces)} faces")
    print(f"smallest neighbour gap {measured:.3f} mm (requested {gap})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
