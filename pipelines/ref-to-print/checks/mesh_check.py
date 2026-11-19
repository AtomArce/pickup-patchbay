"""Check whether meshes are fit to print (millimetres).

Rules per part: watertight, winding, volume_positive, and optionally max_triangles
and min_wall (thinnest wall, estimated with rays). Usage:
  python -m checks.mesh_check --mesh FILE [FILE ...] [--out FILE]
  python -m checks.mesh_check --job-dir DIR --manifest form|parts [--out FILE]
Exit codes: 0 all rules passed, 1 a rule failed, 2 bad usage or unreadable input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from checks.report import EXIT_ERROR, finish, load_json, make_report, result

RAY_SAMPLES = 2000
RAY_OFFSET = 1e-4  # ray starts this far inside the surface (mm)
WALL_FACING_DOT = -0.5  # start and hit normals more than 120 degrees apart: a wall, not an edge


def open_edge_count(mesh: trimesh.Trimesh) -> int:
    """Number of boundary edges (edges used by exactly one face)."""
    return len(trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1))


def wall_result(mesh: trimesh.Trimesh, name: str, limit: float) -> dict[str, Any]:
    """Thinnest wall estimate: shoot rays inward from sampled surface points to the opposite side.

    Points are sampled by surface area, not one per triangle. Booleans leave many tiny triangles
    along cut edges; one ray per triangle centre over-samples those edges and reports slivers
    (0.001 mm2 triangles beside a hole) as thin walls. A real thin wall has area, so area
    sampling still finds it (see tests/test_mesh_check.py::test_thin_shell_fails_min_wall).

    A wall is material between two surfaces that face away from each other. A ray that starts a
    hair from a square edge and leaves through the side face (normals about 90 degrees apart)
    measures the distance to the edge, not a wall, so it is not counted. Knife edges still count:
    the faces of a wedge sharper than 60 degrees face away from each other.
    """
    centres, face_index = trimesh.sample.sample_surface(mesh, RAY_SAMPLES, seed=0)
    normals = mesh.face_normals[face_index]
    origins = centres - normals * RAY_OFFSET
    locations, index_ray, index_tri = mesh.ray.intersects_location(
        origins, -normals, multiple_hits=False
    )
    if len(index_ray) == 0:
        return result(name, "min_wall", False, limit=limit, unit="mm", note="no rays hit")
    facing = np.einsum("ij,ij->i", normals[index_ray], mesh.face_normals[index_tri]) < WALL_FACING_DOT
    if not facing.any():
        return result(name, "min_wall", False, limit=limit, unit="mm", note="no ray met an opposite face")
    lengths = np.linalg.norm(locations - origins[index_ray], axis=1)[facing]
    thinnest = float(lengths.min())
    note = f"{int(facing.sum())} of {len(index_ray)} rays met an opposite face; side-face exits at edges not counted"
    return result(name, "min_wall", thinnest >= limit, value=thinnest, limit=limit, unit="mm", note=note)


def check_mesh(
    mesh: trimesh.Trimesh,
    name: str,
    max_triangles: int | None = None,
    min_wall: float | None = None,
) -> list[dict[str, Any]]:
    """Run every applicable rule on one mesh and return one result dict per rule."""
    watertight = bool(mesh.is_watertight)
    results = [
        result(name, "watertight", watertight, value=open_edge_count(mesh), unit="edges"),
        result(name, "winding", bool(mesh.is_winding_consistent)),
    ]
    if watertight:
        volume = float(mesh.volume)
        results.append(result(name, "volume_positive", volume > 0, value=volume, unit="mm3"))
    else:
        results.append(result(name, "volume_positive", False, note="not watertight"))
    if max_triangles is not None:
        count = len(mesh.faces)
        results.append(
            result(name, "max_triangles", count <= max_triangles, value=count, limit=max_triangles)
        )
    if min_wall is not None and watertight:
        results.append(wall_result(mesh, name, min_wall))
    return results


def load_mesh(path: Path) -> trimesh.Trimesh:
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {path}")
    mesh = trimesh.load(path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError(f"not a usable mesh: {path}")
    return mesh


def load_job(job_dir: Path, kind: str) -> tuple[str, list[tuple[str, Path]]]:
    """Read form.manifest.json (key 'file') or parts.manifest.json (key 'stl')."""
    doc = load_json(job_dir / f"{kind}.manifest.json", f"{kind}.manifest")
    key = "file" if kind == "form" else "stl"
    return doc["job"], [(p["name"], job_dir / p[key]) for p in doc["parts"]]


def run(args: argparse.Namespace) -> int:
    max_triangles, min_wall, job = args.max_triangles, args.min_wall, args.job
    if args.mesh:
        parts = [(path.stem, path) for path in args.mesh]
    else:
        brief_path = args.job_dir / "brief.json"
        if brief_path.is_file():
            constraints = load_json(brief_path, "brief")["constraints"]
            if max_triangles is None:
                max_triangles = constraints["max_triangles_per_part"]
            if min_wall is None:
                min_wall = constraints["min_wall_mm"]
        manifest_job, parts = load_job(args.job_dir, args.manifest)
        job = job or manifest_job
    results: list[dict[str, Any]] = []
    for name, path in parts:
        results += check_mesh(load_mesh(path), name, max_triangles, min_wall)
    return finish(make_report("mesh", results, job), args.out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check meshes are fit to print (mm).")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--mesh", nargs="+", type=Path, help="STL or OBJ files")
    source.add_argument("--job-dir", type=Path, help="job folder holding a manifest")
    parser.add_argument("--manifest", choices=["form", "parts"])
    parser.add_argument("--max-triangles", type=int)
    parser.add_argument("--min-wall", type=float, help="minimum wall thickness, mm")
    parser.add_argument("--job")
    parser.add_argument("--out", type=Path, help="write JSON here instead of stdout")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_ERROR
    if args.job_dir is not None and args.manifest is None:
        print("error: --job-dir needs --manifest form|parts", file=sys.stderr)
        return EXIT_ERROR
    if args.mesh is not None and args.manifest is not None:
        print("error: --manifest only goes with --job-dir", file=sys.stderr)
        return EXIT_ERROR
    try:
        return run(args)
    except Exception as exc:  # missing file, unreadable mesh, bad manifest or brief
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
