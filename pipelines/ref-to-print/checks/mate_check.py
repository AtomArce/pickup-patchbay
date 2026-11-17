"""Mate check: do assembled parts overlap, keep their clearance, and swing freely?

Accuracy limits (all lengths mm):
- Overlap volumes come from manifold3d booleans on the meshes as given, so they
  are exact for those triangles; limit 0.01 mm3 absorbs rounding only.
- The gap is measured on triangle meshes, not the original curved CAD surface.
  It is accurate to about 0.05 mm on 20 to 100 mm parts when the mesh is fine,
  but a coarse tessellation of a curved part shifts it by the chord error. The
  sampled search can miss a narrower pinch point by up to about half the sample
  spacing (a fraction of a mm on large parts), so it may read slightly high.
- The hinge sweep tests N+1 discrete angles; a collision that exists only
  between two samples is not seen. Parts joined to b by a fixed mate (which
  would move with it) are not swept; they are skipped.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import jsonschema
import numpy as np
import trimesh
from scipy.spatial import cKDTree

from checks.report import EXIT_ERROR, finish, load_json, make_report, result

MAX_OVERLAP_MM3 = 0.01
GAP_SAMPLES = 20000
GAP_CANDIDATES = 50


def overlap_volume(a: trimesh.Trimesh, b: trimesh.Trimesh) -> float:
    """Volume (mm3) of the boolean intersection of two watertight meshes."""
    if np.any(a.bounds[1] < b.bounds[0]) or np.any(b.bounds[1] < a.bounds[0]):
        return 0.0
    try:
        common = trimesh.boolean.intersection([a, b], engine="manifold")
    except ValueError:
        return 0.0  # manifold reports an empty result as an error on some versions
    if common is None or len(common.faces) == 0:
        return 0.0
    return float(abs(common.volume))


def _one_way_gap(src: trimesh.Trimesh, dst: trimesh.Trimesh, rng: np.random.Generator) -> float:
    pts = np.vstack([src.vertices, trimesh.sample.sample_surface(src, GAP_SAMPLES, seed=rng)[0]])
    # KD-tree prefilter on dst's points, then exact point-to-triangle distance.
    dst_pts = np.vstack([dst.vertices, trimesh.sample.sample_surface(dst, GAP_SAMPLES, seed=rng)[0]])
    approx, _ = cKDTree(dst_pts).query(pts)
    nearest = pts[np.argsort(approx)[:GAP_CANDIDATES]]
    _, dist, _ = trimesh.proximity.closest_point(dst, nearest)
    return float(dist.min())


def min_gap(a: trimesh.Trimesh, b: trimesh.Trimesh) -> float:
    """Smallest surface-to-surface distance in mm (0 if the parts overlap)."""
    if overlap_volume(a, b) > 0:
        return 0.0
    rng = np.random.default_rng(0)
    return min(_one_way_gap(a, b, rng), _one_way_gap(b, a, rng))


def sweep_hinge(
    a: trimesh.Trimesh,
    b: trimesh.Trimesh,
    origin: list[float],
    direction: list[float],
    range_deg: list[float],
    steps: int,
    others: dict[str, trimesh.Trimesh] | None = None,
) -> tuple[float, float, str]:
    """Swing b about the axis; return (worst volume mm3, worst angle deg, what it hit)."""
    others = others or {}
    worst, worst_angle, hit = 0.0, float(range_deg[0]), ""
    for angle in np.linspace(range_deg[0], range_deg[1], steps + 1):
        moved = b.copy()
        moved.apply_transform(
            trimesh.transformations.rotation_matrix(np.radians(angle), direction, origin)
        )
        for name, target in {"": a, **others}.items():
            vol = overlap_volume(target, moved)
            if vol > worst:
                worst, worst_angle, hit = vol, float(angle), name
    return worst, worst_angle, hit


def _load_mesh(path: Path) -> trimesh.Trimesh:
    mesh = trimesh.load(path, force="mesh")
    return mesh


def check_mate(
    mate: dict[str, Any],
    meshes: dict[str, trimesh.Trimesh],
    default_clearance: float,
    steps: int,
    fixed_to_b: set[str],
) -> list[dict[str, Any]]:
    name, a, b = mate["name"], meshes[mate["a"]], meshes[mate["b"]]
    if not (a.is_watertight and b.is_watertight):
        return [result(name, "no_intersection", False, note="a mesh is not watertight; overlap not measured")]
    out = [overlap_result(name, a, b)]
    required = mate.get("clearance_mm", 0.0 if mate["type"] == "fixed" else default_clearance)
    if required > 0:
        out.append(gap_result(name, a, b, required))
    if mate["type"] == "hinge":
        skip = {mate["a"], mate["b"]} | fixed_to_b
        others = {n: m for n, m in meshes.items() if n not in skip and m.is_watertight}
        out.append(sweep_result(name, mate, a, b, others, steps, sorted(fixed_to_b)))
    return out


def overlap_result(name: str, a: trimesh.Trimesh, b: trimesh.Trimesh) -> dict[str, Any]:
    vol = overlap_volume(a, b)
    return result(name, "no_intersection", vol <= MAX_OVERLAP_MM3, vol, MAX_OVERLAP_MM3, "mm3")


def gap_result(name: str, a: trimesh.Trimesh, b: trimesh.Trimesh, required: float) -> dict[str, Any]:
    gap = min_gap(a, b)
    note = (f"nearest of {GAP_SAMPLES} surface samples per mesh, both ways (KD-tree prefilter, "
            "exact point-to-triangle distance); about 0.05 mm accurate")
    return result(name, "min_gap", gap >= required, gap, required, "mm", note)


def sweep_result(
    name: str,
    mate: dict[str, Any],
    a: trimesh.Trimesh,
    b: trimesh.Trimesh,
    others: dict[str, trimesh.Trimesh],
    steps: int,
    skipped: list[str],
) -> dict[str, Any]:
    vol, angle, hit = sweep_hinge(
        a, b, mate["axis_origin"], mate["axis_direction"], mate["range_deg"], steps, others
    )
    note = f"{steps + 1} poses; worst at {angle:.1f} deg" + (f" against {hit or mate['a']}" if vol > 0 else "")
    note += f"; checked against {len(others)} other part(s)"
    if skipped:
        note += f"; skipped parts fixed to b (not moved with it): {', '.join(skipped)}"
    return result(name, "sweep_clear", vol <= MAX_OVERLAP_MM3, vol, MAX_OVERLAP_MM3, "mm3", note)


def run(job_dir: Path, steps: int, job: str | None) -> dict[str, Any]:
    """Build the report; raises ValueError for an unusable manifest."""
    manifest = load_json(job_dir / "parts.manifest.json", "parts.manifest")
    parts = {p["name"]: p for p in manifest["parts"]}
    for mate in manifest["mates"]:
        for key in ("a", "b"):
            if mate[key] not in parts:
                raise ValueError(f"mate {mate['name']} names unknown part {mate[key]}")
    meshes = {n: _load_mesh(job_dir / p["stl"]) for n, p in parts.items()}
    results: list[dict[str, Any]] = []
    for mate in manifest["mates"]:
        fixed_to_b = {
            m["a"] if m["b"] == mate["b"] else m["b"]
            for m in manifest["mates"]
            if m["type"] == "fixed" and mate["b"] in (m["a"], m["b"])
        }
        results += check_mate(mate, meshes, manifest["clearance_mm"], steps, fixed_to_b)
    return make_report("mate", results, job or manifest["job"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mate_check", description="Check that printed parts mate and move.")
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--steps", type=int, default=10)
    parser.add_argument("--job")
    parser.add_argument("--out")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_ERROR if exc.code else 0
    try:
        report = run(Path(args.job_dir), max(1, args.steps), args.job)
    except (OSError, ValueError, KeyError, jsonschema.ValidationError) as exc:  # missing file, bad JSON/schema, unknown part
        print(f"mate_check: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return finish(report, args.out)


if __name__ == "__main__":
    sys.exit(main())
