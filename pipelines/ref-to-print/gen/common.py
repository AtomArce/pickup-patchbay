"""Shared helpers for code-built parts (the route that needs neither Maya nor Fusion).

Every generator builds trimesh solids in ASSEMBLED position, in millimetres, Z up,
and hands them to save_parts(), which writes the STLs and merges them into
parts.manifest.json. Booleans go through manifold3d.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import trimesh

from checks.report import load_json, validate

UP_AXIS = "Z"


def union(meshes: Iterable[trimesh.Trimesh]) -> trimesh.Trimesh:
    return trimesh.boolean.union(list(meshes), engine="manifold")


def difference(base: trimesh.Trimesh, cutters: Iterable[trimesh.Trimesh]) -> trimesh.Trimesh:
    return trimesh.boolean.difference([base, *cutters], engine="manifold")


def intersection(meshes: Iterable[trimesh.Trimesh]) -> trimesh.Trimesh:
    return trimesh.boolean.intersection(list(meshes), engine="manifold")


def clean(mesh: trimesh.Trimesh, tolerance: float = 0.005) -> trimesh.Trimesh:
    """Collapse edges shorter than tolerance (mm) left by booleans.

    Booleans between faceted surfaces leave near-zero triangles. They break the STL round trip
    (vertices weld and the mesh stops being watertight) and fool the ray wall check.
    """
    import manifold3d

    m = manifold3d.Manifold(manifold3d.Mesh64(vert_properties=np.asarray(mesh.vertices, dtype=np.float64),
                                              tri_verts=np.asarray(mesh.faces, dtype=np.uint32)))
    out = m.simplify(tolerance).to_mesh64()
    return trimesh.Trimesh(vertices=np.asarray(out.vert_properties)[:, :3], faces=np.asarray(out.tri_verts), process=True)


def stl_round_trip_ok(mesh: trimesh.Trimesh) -> bool:
    """True when the mesh is still watertight after writing and reading it back as binary STL."""
    import io

    back = trimesh.load(io.BytesIO(mesh.export(file_type="stl")), file_type="stl", force="mesh")
    return bool(back.is_watertight)


def cylinder_between(p0: Iterable[float], p1: Iterable[float], radius: float, sections: int = 64) -> trimesh.Trimesh:
    """Solid cylinder whose axis runs from p0 to p1."""
    return trimesh.creation.cylinder(radius=radius, segment=[list(p0), list(p1)], sections=sections)


def part(
    name: str,
    mesh: trimesh.Trimesh,
    colour: str | None = None,
    print_up: Iterable[float] | None = None,
) -> dict[str, Any]:
    """Bundle one part for save_parts(). print_up is the direction that points up on the bed."""
    return {"name": name, "mesh": mesh, "colour": colour, "print_up": None if print_up is None else list(print_up)}


def job_limits(job_dir: str | Path) -> dict[str, float]:
    """clearance_mm and min_wall_mm for a job: job.state.json params win over brief.json constraints."""
    job_dir = Path(job_dir)
    limits = {"clearance_mm": 0.3, "min_wall_mm": 1.2}
    brief = job_dir / "brief.json"
    if brief.exists():
        limits.update({k: v for k, v in load_json(brief)["constraints"].items() if k in limits})
    state = job_dir / "job.state.json"
    if state.exists():
        limits.update({k: v for k, v in load_json(state).get("params", {}).items() if k in limits})
    return limits


def save_parts(
    job_dir: str | Path,
    job: str,
    parts: list[dict[str, Any]],
    mates: list[dict[str, Any]],
    clearance_mm: float,
    min_wall_mm: float | None = None,
    drop_prefixes: Iterable[str] = (),
) -> dict[str, Any]:
    """Write parts/<name>.stl for each part and merge parts and mates into parts.manifest.json.

    Existing entries with the same name are replaced. Existing parts whose name starts with one
    of drop_prefixes (and mates that mention them) are removed first, so a generator can be re-run
    with a different count without leaving stale parts behind. Returns the manifest.
    """
    job_dir = Path(job_dir)
    (job_dir / "parts").mkdir(parents=True, exist_ok=True)
    path = job_dir / "parts.manifest.json"
    manifest: dict[str, Any] = (
        load_json(path)
        if path.exists()
        else {"schema": "parts.manifest/1", "job": job, "units": "mm", "up_axis": UP_AXIS, "parts": [], "mates": []}
    )
    manifest["clearance_mm"] = clearance_mm
    if min_wall_mm is not None:
        manifest["min_wall_mm"] = min_wall_mm

    new_names = {p["name"] for p in parts}
    prefixes = tuple(drop_prefixes)
    gone = {p["name"] for p in manifest["parts"] if prefixes and p["name"].startswith(prefixes)} | new_names
    for old in manifest["parts"]:
        if old["name"] in gone - new_names:
            (job_dir / old["stl"]).unlink(missing_ok=True)
    manifest["parts"] = [p for p in manifest["parts"] if p["name"] not in gone]
    new_mates = {m["name"] for m in mates}
    manifest["mates"] = [
        m for m in manifest["mates"]
        if m["name"] not in new_mates and not ({m["a"], m["b"]} & (gone - new_names))
    ]

    for p in parts:
        mesh: trimesh.Trimesh = p["mesh"]
        if not mesh.is_watertight:
            raise ValueError(f"part {p['name']} is not watertight; refusing to write it")
        if not stl_round_trip_ok(mesh):
            raise ValueError(f"part {p['name']} stops being watertight when written as STL; refusing to write it")
        rel = f"parts/{p['name']}.stl"
        mesh.export(job_dir / rel)
        entry: dict[str, Any] = {
            "name": p["name"],
            "stl": rel,
            "source": "rebuilt",
            "bbox_mm": {"min": np.round(mesh.bounds[0], 4).tolist(), "max": np.round(mesh.bounds[1], 4).tolist()},
            "volume_mm3": round(float(mesh.volume), 3),
        }
        if p.get("colour"):
            entry["colour"] = p["colour"]
        if p.get("print_up"):
            entry["print_up"] = [float(v) for v in p["print_up"]]
        manifest["parts"].append(entry)
    manifest["mates"] += mates

    validate(manifest, "parts.manifest")
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
