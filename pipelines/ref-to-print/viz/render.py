"""Software renderer: assembled parts -> PNG views (numpy + Pillow, no GL, no display).

    python -m viz.render --job-dir DIR [--manifest parts|form] [--out-dir DIR/views]
        [--size 512] [--views front,side,back,top,three_quarter] [--pose MATE=DEG ...]

Orthographic camera, z-buffered flat shading, same pixel scale for every view of a run.
Exit 0 on success, 2 with a one-line stderr message for bad input.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from PIL import Image

from checks.report import load_json

Scene = list[tuple[str, trimesh.Trimesh, tuple[int, int, int]]]
BACKGROUND = (245, 245, 245)
OUTLINE = (60, 60, 65)
DEFAULT_COLOUR = (140, 150, 165)
COLOURS = {
    "black": (45, 45, 50),
    "white": (235, 235, 235),
    "grey": (150, 150, 155),
    "gray": (150, 150, 155),
    "brown": (130, 90, 60),
    "red": (200, 40, 40),
}
VIEWS = ("front", "side", "back", "top", "three_quarter")
MARGIN = 0.06
BIG_SCENE_TRIANGLES = 150_000


def camera(view: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (right, up, forward) unit vectors; forward points from camera into the scene."""
    z = np.array([0.0, 0.0, 1.0])
    if view == "front":
        fwd, up = np.array([-1.0, 0, 0]), z
    elif view == "side":
        fwd, up = np.array([0.0, 1, 0]), z
    elif view == "back":
        fwd, up = np.array([1.0, 0, 0]), z
    elif view == "top":
        fwd, up = np.array([0.0, 0, -1]), np.array([0.0, 1, 0])
    elif view == "three_quarter":
        az, el = math.radians(35), math.radians(25)
        fwd, up = -np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)]), z
    else:
        raise ValueError(f"unknown view '{view}' (choose from {', '.join(VIEWS)})")
    right = np.cross(fwd, up)
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    return right, up, fwd


def _colour(name: str | None) -> tuple[int, int, int]:
    return COLOURS.get((name or "").strip().lower(), DEFAULT_COLOUR)


def load_scene(job_dir: str | Path, manifest: str = "parts", pose: dict[str, float] | None = None) -> Scene:
    """Load every part mesh of a manifest. pose maps hinge-mate name -> degrees (parts manifests only)."""
    job_dir = Path(job_dir)
    if manifest not in ("parts", "form"):
        raise ValueError("manifest must be 'parts' or 'form'")
    path = job_dir / f"{manifest}.manifest.json"
    if not path.exists():
        raise ValueError(f"{path} not found")
    doc = load_json(path)
    key = "stl" if manifest == "parts" else "file"
    meshes: dict[str, trimesh.Trimesh] = {}
    colours: dict[str, tuple[int, int, int]] = {}
    for p in doc["parts"]:
        f = job_dir / p[key]
        if not f.exists():
            raise ValueError(f"mesh file {f} not found")
        mesh = trimesh.load(f, force="mesh", process=False)
        meshes[p["name"]] = mesh
        colours[p["name"]] = _colour(p.get("colour"))
    if pose:
        mates = {m["name"]: m for m in doc.get("mates", [])} if manifest == "parts" else {}
        for mate_name, deg in pose.items():
            m = mates.get(mate_name)
            if m is None or m["type"] != "hinge":
                raise ValueError(f"unknown hinge mate '{mate_name}'")
            moving = {m["b"]}
            grew = True
            while grew:  # parts glued to b by fixed mates move with it
                grew = False
                for f in mates.values():
                    if f["type"] == "fixed" and (f["a"] in moving) != (f["b"] in moving):
                        moving |= {f["a"], f["b"]}
                        grew = True
            moving.discard(m["a"])
            rot = trimesh.transformations.rotation_matrix(
                math.radians(deg), m.get("axis_direction", [0, 0, 1]), m.get("axis_origin", [0, 0, 0])
            )
            for name in moving:
                if name in meshes:
                    meshes[name] = meshes[name].copy()
                    meshes[name].apply_transform(rot)
    return [(n, meshes[n], colours[n]) for n in meshes]


def _bounds(scene: Scene) -> tuple[np.ndarray, float]:
    lo = np.min([m.bounds[0] for _, m, _ in scene], axis=0)
    hi = np.max([m.bounds[1] for _, m, _ in scene], axis=0)
    return (lo + hi) / 2, float(np.linalg.norm(hi - lo)) / 2


def fit_scale(scene: Scene, size: int) -> float:
    """Pixels per mm so the assembly fits any view (bounding sphere) with a 6% margin."""
    _, radius = _bounds(scene)
    return size * (1 - 2 * MARGIN) / (2 * max(radius, 1e-9))


def render_view(scene: Scene, view: str, size: int = 512, scale: float | None = None) -> tuple[Image.Image, Image.Image]:
    """Render one view. Returns (shaded image, silhouette image)."""
    right, up, fwd = camera(view)
    centre, _ = _bounds(scene)
    scale = fit_scale(scene, size) if scale is None else scale
    tris, normals, part_of = [], [], []
    for i, (_, mesh, _) in enumerate(scene):
        tris.append(np.asarray(mesh.triangles, dtype=float))
        normals.append(np.asarray(mesh.face_normals, dtype=float))
        part_of.append(np.full(len(mesh.faces), i))
    tri = np.concatenate(tris) - centre
    nrm = np.concatenate(normals)
    pid = np.concatenate(part_of)
    if len(tri) > BIG_SCENE_TRIANGLES:
        print(f"note: {len(tri)} triangles, rendering will be slow", file=sys.stderr)

    sx = size / 2 + (tri @ right) * scale
    sy = size / 2 - (tri @ up) * scale
    sz = tri @ fwd
    nrm = np.where(((nrm @ fwd) > 0)[:, None], -nrm, nrm)  # face the camera
    light = -0.5 * right + 0.6 * up - 0.7 * fwd
    light /= np.linalg.norm(light)
    bright = 0.35 + 0.65 * np.clip(nrm @ light, 0, None)

    d = (sy[:, 1] - sy[:, 2]) * (sx[:, 0] - sx[:, 2]) + (sx[:, 2] - sx[:, 1]) * (sy[:, 0] - sy[:, 2])
    x0 = np.maximum(0, np.ceil(sx.min(1) - 0.5)).astype(int)
    x1 = np.minimum(size - 1, np.floor(sx.max(1) - 0.5)).astype(int)
    y0 = np.maximum(0, np.ceil(sy.min(1) - 0.5)).astype(int)
    y1 = np.minimum(size - 1, np.floor(sy.max(1) - 0.5)).astype(int)
    todo = np.nonzero((np.abs(d) > 1e-12) & (x1 >= x0) & (y1 >= y0))[0]

    zbuf = np.full((size, size), np.inf)
    tid = np.full((size, size), -1, dtype=np.int64)
    xs_all = np.arange(size) + 0.5
    for t in todo:
        ax, bx, cx = sx[t]
        ay, by, cy = sy[t]
        az, bz, cz = sz[t]
        px = xs_all[x0[t]:x1[t] + 1][None, :]
        py = xs_all[y0[t]:y1[t] + 1][:, None]
        l0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / d[t]
        l1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / d[t]
        l2 = 1 - l0 - l1
        inside = (l0 >= -1e-9) & (l1 >= -1e-9) & (l2 >= -1e-9)
        z = l0 * az + l1 * bz + l2 * cz
        win = (slice(y0[t], y1[t] + 1), slice(x0[t], x1[t] + 1))
        upd = inside & (z < zbuf[win])
        zbuf[win] = np.where(upd, z, zbuf[win])
        tid[win] = np.where(upd, t, tid[win])

    covered = tid >= 0
    part_id = np.where(covered, pid[np.maximum(tid, 0)], -1)
    base = np.array([c for _, _, c in scene], dtype=float)
    rgb = np.empty((size, size, 3))
    rgb[:] = BACKGROUND
    rgb[covered] = base[part_id[covered]] * bright[tid[covered]][:, None]

    thr = 0.02 * 2 * _bounds(scene)[1]  # depth step that counts as a discontinuity
    edge = np.zeros((size, size), dtype=bool)
    for a, b in ((np.s_[:, 1:], np.s_[:, :-1]), (np.s_[1:, :], np.s_[:-1, :])):
        both = covered[a] & covered[b]
        jump = (part_id[a] != part_id[b]) | (both & (np.abs(zbuf[a] - np.where(both, zbuf[b], 0)) > thr))
        jump &= covered[a] | covered[b]
        edge[a] |= jump & covered[a]
        edge[b] |= jump & covered[b]
    rgb[edge] = OUTLINE

    sil = np.where(covered, 0, 255).astype(np.uint8)
    return (
        Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB"),
        Image.fromarray(sil, "L").convert("RGB"),
    )


def _parse_pose(items: list[str] | None) -> dict[str, float]:
    pose: dict[str, float] = {}
    for item in items or []:
        name, sep, deg = item.partition("=")
        try:
            if not sep:
                raise ValueError
            pose[name] = float(deg)
        except ValueError:
            raise ValueError(f"bad --pose '{item}', expected MATE=DEGREES") from None
    return pose


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="viz.render", description=__doc__.split("\n")[0])
    ap.add_argument("--job-dir", required=True)
    ap.add_argument("--manifest", choices=("parts", "form"), default="parts")
    ap.add_argument("--out-dir")
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--views", default=",".join(VIEWS))
    ap.add_argument("--pose", action="append", metavar="MATE=DEG")
    args = ap.parse_args(argv)
    try:
        views = [v.strip() for v in args.views.split(",") if v.strip()]
        for v in views:
            camera(v)
        if args.size < 16:
            raise ValueError("--size must be at least 16")
        scene = load_scene(args.job_dir, args.manifest, _parse_pose(args.pose))
    except (ValueError, OSError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out = Path(args.out_dir) if args.out_dir else Path(args.job_dir) / "views"
    out.mkdir(parents=True, exist_ok=True)
    scale = fit_scale(scene, args.size)
    index: dict[str, Any] = {"size": args.size, "scale_px_per_mm": scale, "pose": _parse_pose(args.pose), "images": []}
    for v in views:
        shaded, sil = render_view(scene, v, args.size, scale)
        right, up, fwd = camera(v)
        for kind, img in (("shaded", shaded), ("silhouette", sil)):
            path = out / (f"{v}.png" if kind == "shaded" else f"silhouette_{v}.png")
            img.save(path)
            print(path)
            index["images"].append(
                {"file": path.name, "view": v, "kind": kind, "right": right.tolist(), "up": up.tolist(), "forward": fwd.tolist()}
            )
    (out / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(out / "index.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
