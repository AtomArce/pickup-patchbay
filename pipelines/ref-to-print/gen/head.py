"""Chain Chomp head: a hollow ball with a hinged lower jaw, built with manifold booleans.

Frame: ball centre at the origin, +X is the face, +Z is up, the hinge is at the back (-X)
with its axis parallel to Y. Everything is in millimetres, in the assembled, mouth-closed pose.

Design sketch
  shell        outer sphere minus inner sphere, split at the mouth plane Z = 0 with a rim gap.
  body_upper   shell above the mouth, two outer hinge lugs, two eye holes, a chain ring on the back.
  jaw_lower    shell below the mouth, one centre hinge lug. Each part has a cylindrical relief
               (lug radius + clearance) where the other part's lugs turn, so nothing fouls at any angle.
  hinge_pin    short cylinder through all three lugs: press fit in the outer lugs, free in the jaw lug.
  teeth_*      a "denture" each: a curved band glued inside the shell at the front, carrying cones.
               The upper teeth hang down past the rim, the lower ones stand up. Teeth sit radially
               inside the opposite band and are staggered by half a pitch, so they never touch.
  eye_*        round plug with an inside flange, pushed in from inside through a hole in body_upper.

Hinge gaps are the requested clearance plus GAP_EXTRA, so mesh faceting cannot eat the clearance.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from checks.report import load_json
from gen.common import (
    cylinder_between, difference, intersection, job_limits, part, save_parts, union,
)

GAP_EXTRA = 0.02  # added to every hinge gap so faceting never shrinks it below the clearance
GLUE_GAP = 0.1    # glued seats (teeth, eyes) stand this far off the wall
LUG_R, PIN_R, LUG_W = 5.0, 2.0, 8.0
EYE_R, FLANGE_T = 7.0, 1.4  # flange is 1.4 thick (not 1.0) so the wall check stays at >= 1.2


def _box(lo: tuple[float, float, float], hi: tuple[float, float, float]) -> trimesh.Trimesh:
    return trimesh.creation.box(bounds=[lo, hi])


def _sphere(radius: float) -> trimesh.Trimesh:
    return trimesh.creation.icosphere(subdivisions=4, radius=radius)


def _hull(points: list[tuple[float, float, float]]) -> trimesh.Trimesh:
    return trimesh.convex.convex_hull(np.array(points, dtype=float))


def _y_cyl(x: float, y0: float, y1: float, radius: float) -> trimesh.Trimesh:
    return cylinder_between((x, y0, 0.0), (x, y1, 0.0), radius)


def _frustum(cx: float, cy: float, z0: float, r0: float, z1: float, r1: float, n: int = 24) -> trimesh.Trimesh:
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.column_stack([np.cos(t), np.sin(t)])
    pts = [(cx + r0 * u, cy + r0 * v, z0) for u, v in ring] + [(cx + r1 * u, cy + r1 * v, z1) for u, v in ring]
    return _hull(pts)


def _denture(sign: int, r_in: float, clearance: float, angles: list[float]) -> trimesh.Trimesh:
    """Band + teeth. sign +1: upper (band above the mouth, teeth down); -1: lower (mirror image)."""
    zb = clearance / 2 + 0.5          # band starts here (distance from the mouth plane)
    height = 8.0
    # outer face is a plain cylinder that clears the inner wall at the band's top edge by GLUE_GAP
    r_out = float(np.sqrt(r_in ** 2 - (zb + height) ** 2)) - GLUE_GAP
    r_band_in = r_in - 2.4            # band inner face (cylinder)
    z0, z1 = sorted((sign * zb, sign * (zb + height)))
    ring = difference(cylinder_between((0, 0, z0), (0, 0, z1), r_out), [cylinder_between((0, 0, z0 - 1), (0, 0, z1 + 1), r_band_in)])
    big = 2 * r_in
    wedge = _hull([(0, 0, z) for z in (z0 - 1, z1 + 1)] + [
        (big * np.cos(np.radians(s * 60)), big * np.sin(np.radians(s * 60)), z) for s in (-1, 1) for z in (z0 - 1, z1 + 1)])
    pieces = [intersection([ring, wedge])]
    c_tip, c_neck = r_in - 5.7, r_in - 5.4     # tooth tip and neck axes, both well inside the opposite band
    for a in np.radians(angles):
        ux, uy = np.cos(a), np.sin(a)
        t = np.linspace(0, 2 * np.pi, 24, endpoint=False)

        def circle(centre: float, radius: float, z: float) -> list[tuple[float, float, float]]:
            return [\
                    (centre * ux + radius * np.cos(v) * ux - radius * np.sin(v) * uy,
                     centre * uy + radius * np.cos(v) * uy + radius * np.sin(v) * ux, sign * z) for v in t]
        # Two convex solids. Tooth: 0.75 mm radius tip (1.5 mm flat) 10 mm below the band edge widening to a
        # 2.4 mm radius neck at the mouth plane, always >= clearance inside the opposite band's inner face.
        # Shoulder: neck widening into a slab buried in the band wall (no exposed flat cap).
        slab = [(rad * ux - lat * uy, rad * uy + lat * ux, sign * z)
                for rad in (r_band_in + 0.4, r_band_in + 1.1) for lat in (-3.5, 3.5) for z in (zb + 1.0, zb + 7.0)]
        pieces.append(union([_hull(circle(c_tip, 0.75, zb - 10) + circle(c_neck, 2.4, -zb)),
                             _hull(circle(c_neck, 2.4, -zb) + slab)]))
    return union(pieces)


def _eye(side: int, r_in: float, r_out: float) -> tuple[trimesh.Trimesh, trimesh.Trimesh, np.ndarray]:
    """Return (plug, hole cutter, outward direction) for the eye on the given side (+1 left, -1 right)."""
    el, az = np.radians(35), np.radians(30 * side)
    d = np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])
    flange_r = EYE_R + 1.5
    a_flange = np.sqrt((r_in - GLUE_GAP) ** 2 - flange_r ** 2)   # flange edge stays off the inner wall
    a0 = a_flange - FLANGE_T
    # one revolved profile (flange, then plug) instead of a union: no seam triangles, clean STL round trip
    profile = np.array([(0, a0), (flange_r, a0), (flange_r, a_flange), (EYE_R, a_flange), (EYE_R, r_out + 1.0), (0, r_out + 1.0)])
    plug = trimesh.creation.revolve(profile, sections=48, transform=trimesh.geometry.align_vectors([0, 0, 1], d))
    hole = cylinder_between(d * (r_in - 8), d * (r_out + 5), EYE_R + GLUE_GAP)
    return plug, hole, d


def build_head(diameter: float = 100.0, wall: float = 2.4, clearance: float = 0.3,
               jaw_range: tuple[float, float] = (0.0, 45.0)) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the head parts (assembled pose) and their mates."""
    R, r_in, c = diameter / 2, diameter / 2 - wall, clearance
    g = c + GAP_EXTRA                      # real hinge gap
    zr = c / 2 + GAP_EXTRA / 2             # rim planes at +-zr, so the rim gap is g
    ax = -(R + LUG_R * 0.6)                # hinge axis x (axis runs along Y through (ax, 0, 0))
    a = LUG_W / 2                          # jaw lug spans y in [-a, a]
    y_in, y_out = a + g, a + g + LUG_W     # upper lugs span |y| in [y_in, y_out]
    shell = difference(_sphere(R), [_sphere(r_in)])
    below, above = _box((-R - 1, -R - 1, -R - 1), (R + 1, R + 1, -zr)), _box((-R - 1, -R - 1, zr), (R + 1, R + 1, R + 1))
    relief = LUG_R + g
    seat_z = LUG_R * 1.0   # relief block height: removes the knife edge where the relief cylinder meets the wall

    # jaw: shell below the mouth, relieved around the upper lugs, plus its own lug and gusset
    # The relief ends on a plane that leans away from y = const so it never meets the sphere at a glancing
    # angle; y_end keeps that plane >= g beyond the upper lug over the whole wall.
    def y_end(x: float) -> float:   # radial plane through the ball centre: square to the wall, at least g beyond the lug
        return (y_out + g + 0.4) * abs(x) / r_in
    def prisms(floor: float) -> list[trimesh.Trimesh]:
        # floor = 0: full height; else the floor is the plane z = floor * x / |ax| through the ball centre, for the same reason
        return [_hull([(x, s * y, (floor * x / abs(ax) if floor else -R)) for x, y in ((-44.0, a), (-44.0, y_end(-44)), (-70.0, y_end(-70)), (-70.0, a))]
                       + [(x, s * y, 1.0 if floor else R) for x, y in ((-44.0, a), (-44.0, y_end(-44)), (-70.0, y_end(-70)), (-70.0, a))])
                for s in (1, -1)]
    jaw_cut = [intersection([_y_cyl(ax, -30, 30, relief), pr]) for pr in prisms(0)] + prisms(seat_z)
    jaw = difference(intersection([shell, below]), jaw_cut)
    jaw = union([jaw, _y_cyl(ax, -a, a, LUG_R), _box((ax - 1, -a, -LUG_R), (ax + 3.5, a, -zr))])
    jaw = difference(jaw, [_y_cyl(ax, -a - 1, a + 1, PIN_R + c)])

    # upper body: shell above the mouth, relieved around the jaw lug, two outer lugs, eye holes, chain ring
    eyes = [_eye(s, r_in, R) for s in (1, -1)]
    upper = difference(intersection([shell, above]), [_y_cyl(ax, -(a + g), a + g, relief),
                                                                _hull([(x, y, z) for x in (-44.0, -70.0) for y in (-(a + g), a + g) for z in (-1.0, -seat_z * x / abs(ax))])])
    lugs = [_y_cyl(ax, s * y_in, s * y_out, LUG_R) for s in (1, -1)]
    gussets = [_box((ax - 1, min(s * y_in, s * y_out), zr), (ax + 3.5, max(s * y_in, s * y_out), LUG_R)) for s in (1, -1)]
    upper = union([upper, *lugs, *gussets])
    upper = difference(upper, [_y_cyl(ax, -y_out - 1, y_out + 1, PIN_R + 0.1), *(e[1] for e in eyes)])
    minor, major = 2.5, 5.5 + 2.5          # wire 5 mm thick, 11 mm inner opening
    u = np.array([-np.cos(np.radians(40)), 0.0, np.sin(np.radians(40))])
    ring_t = trimesh.transformations.translation_matrix(u * (R + 7.5)) @ trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
    upper = union([upper, trimesh.creation.torus(major, minor, 48, 24, transform=ring_t)])

    pin = _y_cyl(ax, -y_out, y_out, PIN_R)
    pitch = 18.0
    teeth_u = _denture(+1, r_in, c, [k * pitch for k in (-3, -2, -1, 0, 1, 2, 3)])
    teeth_l = _denture(-1, r_in, c, [(k + 0.5) * pitch for k in (-3, -2, -1, 0, 1, 2)])

    parts = [
        part("body_upper", upper, "black", (0, 0, 1)),     # rim on the bed, dome up
        part("jaw_lower", jaw, "black", (0, 0, -1)),       # rim on the bed, bowl up
        # pin stands on end: the round section prints truest as stacked circles, and it is a bearing surface
        part("hinge_pin", pin, "black", (0, 1, 0)),
        # band's flat outer edge on the bed, teeth pointing up: no supports needed
        part("teeth_upper", teeth_u, "white", (0, 0, -1)),
        part("teeth_lower", teeth_l, "white", (0, 0, 1)),
        # flange's flat back on the bed, plug standing up along its own axis
        part("eye_left", eyes[0][0], "white", tuple(eyes[0][2])),
        part("eye_right", eyes[1][0], "white", tuple(eyes[1][2])),
    ]
    axis = {"axis_origin": [ax, 0.0, 0.0], "axis_direction": [0.0, 1.0, 0.0]}  # +angle: front of jaw drops
    mates: list[dict[str, Any]] = [
        {"name": "jaw_hinge", "type": "hinge", "a": "body_upper", "b": "jaw_lower", "clearance_mm": c,
         **axis, "range_deg": list(jaw_range)},
        {"name": "pin_in_upper", "type": "fixed", "a": "body_upper", "b": "hinge_pin", "clearance_mm": 0},
        # the pin hole gives exactly c; ask for 0.8 c because the mesh is faceted
        {"name": "pin_in_jaw", "type": "link", "a": "hinge_pin", "b": "jaw_lower", "clearance_mm": c * 0.8},
        {"name": "teeth_upper_seat", "type": "fixed", "a": "body_upper", "b": "teeth_upper"},
        {"name": "teeth_lower_seat", "type": "fixed", "a": "jaw_lower", "b": "teeth_lower"},
        {"name": "eye_left_seat", "type": "fixed", "a": "body_upper", "b": "eye_left"},
        {"name": "eye_right_seat", "type": "fixed", "a": "body_upper", "b": "eye_right"},
    ]
    return parts, mates


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gen.head", description="Build the Chain Chomp head parts.")
    ap.add_argument("--job-dir", required=True)
    ap.add_argument("--job")
    ap.add_argument("--diameter", type=float, default=100.0)
    ap.add_argument("--wall", type=float, default=2.4)
    ap.add_argument("--jaw-open", type=float, default=45.0)
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    job_dir = Path(args.job_dir)
    try:
        if not job_dir.is_dir():
            raise ValueError(f"job dir not found: {job_dir}")
        if not 80 <= args.diameter <= 180:
            raise ValueError("--diameter must be between 80 and 180 mm")
        if not 1.2 <= args.wall <= 6:
            raise ValueError("--wall must be between 1.2 and 6 mm")
        if not 0 < args.jaw_open <= 80:
            raise ValueError("--jaw-open must be between 0 and 80 degrees")
        limits = job_limits(job_dir)
        job = args.job or (load_json(job_dir / "brief.json").get("job") if (job_dir / "brief.json").exists() else None) or "head"
        parts, mates = build_head(args.diameter, args.wall, limits["clearance_mm"], (0.0, args.jaw_open))
        save_parts(job_dir, job, parts, mates, limits["clearance_mm"], limits["min_wall_mm"],
                   drop_prefixes=("body_upper", "jaw_lower", "hinge_pin", "teeth_", "eye_"))
    except (OSError, ValueError, KeyError) as exc:
        print(f"gen.head: {exc}", file=sys.stderr)
        return 2
    for p in parts:
        size = p["mesh"].extents
        print(f"{p['name']}: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm, {p['mesh'].volume:.0f} mm3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
