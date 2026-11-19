"""Chain Chomp head, second pass: a Pac-Man mouth whose corners sit at the sides of the ball.

Frame: ball centre at the origin, +X is the face, +Z is up, millimetres. Angles "alpha" are measured
in the XZ plane from +X towards +Z, so alpha = 0 is the front of the mouth plane and -90 is straight
down. The jaw turns about the Y axis through the ball centre; +angle drops the front of the jaw.

Design sketch (reference: the side view Atom supplied, jobs/chain-chomp/refs/, not committed)
  body_upper   the outer shell from the upper lip (alpha 0) over the top and round the back down to
               alpha -125. Under the jaw's travel it carries a recessed inner band (alpha -131 to -70)
               that the jaw slides over, and at each side pole an inner cap that holds a hinge pin.
               Chain ring on the back, two eye holes.
  jaw_lower    the outer shell from the lower lip down to alpha -60 (closed frame), plus a cap round
               each side pole that rides on the body's inner cap. Built open by REST_DEG, so the
               teeth interleave without touching; its hinge range runs from there to MAX_DEG.
  hinge_pin_*  one short pin per side, glued in the body's inner cap, free in the jaw's cap.
  mouth_roof / mouth_floor   red plates that close the mouth, glued inside the shell at the lips.
               Each has a groove that seats one teeth strip.
  teeth_*      a strip of big triangular teeth, glued into the plate groove. Each tooth reaches
               TOOTH_DEG round the hinge axis, so teeth near the corners are smaller (as in the
               reference) and no tip reaches the opposite plate while the mouth is at rest or wider.
  eye_*        domed white eye, pushed in from inside through a hole in the body, with a flange.
  pupil_*      black plug glued into a hole in the eye, set towards the front, standing 0.6 proud.

Gaps that move are the clearance plus GAP_EXTRA (faceting); glued seats stand GLUE_GAP off.
Assembly: the jaw springs over the two inner caps (about 2.7 mm each side), then the pins go in.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from checks.report import load_json
from gen.common import clean, cylinder_between, difference, intersection, job_limits, part, save_parts, union

GAP_EXTRA = 0.1      # added to moving gaps so faceting never eats the clearance
GLUE_GAP = 0.1       # glued seats stand this far off
REST_DEG, MAX_DEG = 25.0, 65.0   # jaw opening as built (teeth interleaved) and fully open
JAW_SPAN = 60.0      # jaw shell from the lip down this many degrees (closed frame)
SLIDE_MARGIN = 5.0   # degrees between the fully open jaw's back edge and the body's outer edge
CAP_DEG, CAP_GAP_DEG = 10.0, 1.0  # jaw cap half-angle round each side pole, and the gap round it
PIN_R = 2.5
PLATE_T = 3.2        # roof and floor plate thickness
STRIP_W, STRIP_T = 7.0, 1.4      # teeth strip width (radial) and thickness
TOOTH_DEG = 21.0     # how far each tooth reaches round the hinge axis
BALL_R = 0.7         # edge rounding on the teeth
N_TEETH = 9          # upper teeth; the lower jaw has one fewer, staggered half a pitch
TEETH_SPREAD = 55.0  # outermost upper tooth, degrees of azimuth from the front
EYE_R, FLANGE_T, EYE_BULGE = 11.0, 1.4, 3.0
EYE_EL, EYE_AZ = 28.0, 48.0
PUPIL_R, PUPIL_SHIFT = 4.5, 3.5


# ---------------------------------------------------------------- primitives

def _box(lo, hi) -> trimesh.Trimesh:
    return trimesh.creation.box(bounds=[lo, hi])


def _sphere(radius: float, centre=(0.0, 0.0, 0.0)) -> trimesh.Trimesh:
    s = trimesh.creation.icosphere(subdivisions=4, radius=radius)
    s.apply_translation(centre)
    return s


def _shell(r_out: float, r_in: float) -> trimesh.Trimesh:
    return difference(_sphere(r_out), [_sphere(r_in)])


def _hull(points) -> trimesh.Trimesh:
    return trimesh.convex.convex_hull(np.array(points, dtype=float))


def _wedge_y(a1: float, a2: float, reach: float) -> trimesh.Trimesh:
    """Convex wedge about the Y axis covering alpha in [a1, a2] degrees (span at most 180)."""
    pts = []
    for y in (-reach, reach):
        pts.append((0.0, y, 0.0))
        for a in np.radians(np.linspace(a1, a2, 9)):
            pts.append((2 * reach * np.cos(a), y, 2 * reach * np.sin(a)))
    return _hull(pts)


def _wedge_z(p1: float, p2: float, reach: float, z0: float, z1: float) -> trimesh.Trimesh:
    """Convex wedge about the Z axis covering azimuth [p1, p2] degrees (span under 180), z0..z1."""
    pts = []
    for z in (z0, z1):
        pts.append((0.0, 0.0, z))
        for p in np.radians(np.linspace(p1, p2, 9)):
            pts.append((2 * reach * np.cos(p), 2 * reach * np.sin(p), z))
    return _hull(pts)


def _cones(beta: float, reach: float) -> list[trimesh.Trimesh]:
    """Solid cones from the centre round +Y and -Y with half-angle beta degrees."""
    t = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    r = reach * np.tan(np.radians(beta))
    return [_hull([(0.0, 0.0, 0.0)] + [(r * np.cos(v), s * reach, r * np.sin(v)) for v in t]) for s in (1, -1)]


def _rot_y(deg: float) -> np.ndarray:
    return trimesh.transformations.rotation_matrix(np.radians(deg), [0, 1, 0])


def _z_cyl(r: float, z0: float, z1: float) -> trimesh.Trimesh:
    return cylinder_between((0, 0, z0), (0, 0, z1), r, sections=128)


# ---------------------------------------------------------------- mouth: plate, groove, teeth

def _mouth_upper(r_wall: float, z_lip: float, stagger: bool, y_lim: float) -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
    """(plate, teeth) for the upper side of the mouth plane z = 0, in the closed frame.

    The lower side is the same thing mirrored in Z (with stagger=True), then turned with the jaw.
    """
    z0, z1 = z_lip, z_lip + PLATE_T
    plate_r = float(np.sqrt(r_wall ** 2 - z1 ** 2)) - GLUE_GAP
    r_s1 = plate_r - 1.5
    r_s0 = r_s1 - STRIP_W
    pitch = 2 * TEETH_SPREAD / (N_TEETH - 1)
    half_w = 0.42 * pitch                       # tooth half-width, degrees of azimuth
    centres = np.linspace(-TEETH_SPREAD, TEETH_SPREAD, N_TEETH)
    if stagger:
        centres = (centres[:-1] + centres[1:]) / 2
    edge = float(np.max(np.abs(centres))) + half_w + 0.6
    reach = plate_r + 5

    def footprint(grow: float, za: float, zb: float) -> trimesh.Trimesh:
        ring = difference(_z_cyl(r_s1 + grow, za, zb), [_z_cyl(r_s0 - grow, za - 1, zb + 1)])
        d_ang = np.degrees(grow / r_s0)
        return intersection([ring, _wedge_z(-edge - d_ang, edge + d_ang, reach, za - 1, zb + 1)])

    # Sides clipped square (|y| <= y_lim) so the plate keeps clear of the body's inner caps at the poles.
    plate = intersection([_box((1.0, -y_lim, z0), (reach, y_lim, z1)), _z_cyl(plate_r, z0 - 1, z1 + 1)])
    plate = difference(plate, [footprint(GLUE_GAP, z0 - 1, z0 + STRIP_T + 0.2)])

    zs = z0 + GLUE_GAP                          # strip underside, flush-ish with the plate face
    strip = footprint(0.0, zs, zs + STRIP_T - GLUE_GAP)
    # Each tooth is the hull of six small balls (three at the base, three at the tip), so every
    # edge is rounded at BALL_R: a flat-sided tooth has knife edges no printer can hold.
    inset = BALL_R + 0.2
    rb1, rb0, zb = r_s1 - inset, r_s0 + inset, zs + BALL_R + 0.1
    turn = _rot_y(TOOTH_DEG)
    ball = trimesh.creation.icosphere(subdivisions=1, radius=BALL_R).vertices
    teeth = []
    for c in centres:
        p, q = np.radians(c), np.radians(half_w) - inset / rb1
        base = [(rb1 * np.cos(p - q), rb1 * np.sin(p - q), zb), (rb1 * np.cos(p + q), rb1 * np.sin(p + q), zb),
                (rb0 * np.cos(p), rb0 * np.sin(p), zb)]
        rt = rb1 - 0.45 * (rb1 - rb0)           # tip: a small blunt triangle
        dq = 0.6 / rt
        tip = np.array([(rt + 0.3) * np.array([np.cos(p - dq), np.sin(p - dq), 0]),
                        (rt + 0.3) * np.array([np.cos(p + dq), np.sin(p + dq), 0]),
                        (rt - 0.6) * np.array([np.cos(p), np.sin(p), 0])]) + [0, 0, zb]
        tip = trimesh.transformations.transform_points(tip, turn)
        teeth.append(_hull([v + k for k in [*map(np.array, base), *tip] for v in ball]))
    return plate, union([strip, *teeth])


def _mirror_z(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    m = mesh.copy()
    m.apply_transform(np.diag([1.0, 1.0, -1.0, 1.0]))
    return m


# ---------------------------------------------------------------- eyes

def _eye(side: int, r_wall: float, R: float):
    """(eye white, pupil, hole cutter for the body, outward direction) for side +1 left, -1 right."""
    el, az = np.radians(EYE_EL), np.radians(EYE_AZ * side)
    d = np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])
    flange_r = EYE_R + 1.5
    a_flange = float(np.sqrt((r_wall - GLUE_GAP) ** 2 - flange_r ** 2))
    a0 = a_flange - FLANGE_T
    apex = R + EYE_BULGE
    h_rim = float(np.sqrt(R ** 2 - EYE_R ** 2)) + 0.6       # dome edge just outside the ball
    c = (apex ** 2 - h_rim ** 2 - EYE_R ** 2) / (2 * (apex - h_rim))
    rho = apex - c
    # One revolved profile (flange, side, dome arc), not a union: no seam slivers.
    arc_lo = float(np.arcsin(EYE_R / rho))
    arc = [(rho * np.sin(t), c + rho * np.cos(t)) for t in np.linspace(arc_lo, 0.0, 16)]
    profile = np.array([(0.0, a0), (flange_r, a0), (flange_r, a_flange), (EYE_R, a_flange), *arc])
    to_d = trimesh.geometry.align_vectors([0, 0, 1], d)
    eye = trimesh.creation.revolve(profile, sections=96, transform=to_d)
    # The pupil sits towards the front and a little low. Its axis runs through the dome's centre, so
    # the hole meets the dome square-on (a hole parallel to d would leave a knife edge on one side).
    ex = np.array([1.0, 0.0, -0.4])
    lat = ex - ex.dot(d) * d
    lat /= np.linalg.norm(lat)
    centre = d * c
    n_p = d * np.cos(PUPIL_SHIFT / rho) + lat * np.sin(PUPIL_SHIFT / rho)
    top = centre + n_p * rho
    depth = 4.0
    eye = difference(eye, [cylinder_between(top - n_p * (depth + 0.2), top + n_p * 3, PUPIL_R + GLUE_GAP, 64)])
    pupil = intersection([cylinder_between(top - n_p * depth, top + n_p * 3, PUPIL_R, 64), _sphere(rho + 0.6, centre)])
    hole = cylinder_between(d * (r_wall - 8), d * (R + 5), EYE_R + GLUE_GAP, 96)
    return eye, pupil, hole, d


# ---------------------------------------------------------------- head

def build_head(diameter: float = 100.0, wall: float = 2.4, clearance: float = 0.3,
               jaw_range: tuple[float, float] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the head parts (assembled, jaw at REST_DEG) and their mates.

    jaw_range is (rest, fully open) in degrees of jaw opening; the hinge mate's range runs from 0
    (the built pose) to fully open minus rest.
    """
    rest, full = jaw_range if jaw_range else (REST_DEG, MAX_DEG)
    if not TOOTH_DEG + 3 <= rest < full <= 75:
        raise ValueError(f"jaw range must satisfy {TOOTH_DEG + 3} <= rest < open <= 75 degrees")
    if full - rest > JAW_SPAN - 19:
        raise ValueError(f"jaw travel (open - rest) must be at most {JAW_SPAN - 19:g} degrees, or the mouth floor hits the body's band")
    R, c = diameter / 2, clearance
    g = c + GAP_EXTRA
    r_wall = R - wall                     # inside of the outer layer
    r_i_out, r_i_in = r_wall - g, r_wall - g - wall   # the body's recessed inner layer
    reach = R + 10
    outer, inner = _shell(R, r_wall), _shell(r_i_out, r_i_in)
    back_edge = -(JAW_SPAN + full + SLIDE_MARGIN)     # body's outer layer ends here (alpha)
    cap_hole = CAP_DEG + CAP_GAP_DEG
    cap_in = cap_hole + 4.0

    # ---- body_upper
    body_sector = union([_box((-reach, -reach, g / 2), (reach, reach, reach)), _wedge_y(175.0, 360.0 + back_edge, reach)])
    body = difference(intersection([outer, body_sector]), _cones(cap_hole, reach))
    # The band starts 4 degrees under the jaw's back edge at rest. Fully open, the mouth floor (thick near the
    # axis) must still clear it, hence the check on the range in the signature.
    band = intersection([inner, _wedge_y(back_edge - 6, -(JAW_SPAN + rest) + 4, reach)])
    # bridges stay 0.3 off the inner layer's inside so no two cut surfaces coincide
    bridge = difference(intersection([_shell(r_wall + 0.5, r_i_in + 0.3), _wedge_y(back_edge - 6, back_edge, reach)]),
                        _cones(cap_hole + 0.5, reach))   # stays out of the jaw's pole caps
    caps = [intersection([inner, k]) for k in _cones(cap_in, reach)]
    ring_zone = difference(intersection([_shell(r_wall + 0.5, r_i_in + 0.3), body_sector]), _cones(cap_hole + 0.5, reach))
    cap_bridges = [intersection([ring_zone, k]) for k in _cones(cap_in - 1.0, reach)]
    eyes = [_eye(s, r_wall, R) for s in (1, -1)]
    u = np.array([np.cos(np.radians(190)), 0.0, np.sin(np.radians(190))])   # chain ring: the back, a little low
    ring_t = trimesh.transformations.translation_matrix(u * (R + 7.5)) @ trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
    ring = trimesh.creation.torus(8.0, 2.5, 48, 24, transform=ring_t)
    body = union([body, band, bridge, *caps, *cap_bridges, ring])
    pin_holes = [cylinder_between((0, s * (r_i_in - 3), 0), (0, s * (R + 1), 0), PIN_R + GLUE_GAP) for s in (1, -1)]
    body = difference(body, [*pin_holes, *(e[2] for e in eyes)])

    # ---- jaw_lower, closed frame, then opened to rest
    jaw_sector = intersection([_box((-reach, -reach, -reach), (reach, reach, -g / 2)), _wedge_y(-JAW_SPAN, 5.0, reach)])
    jaw = union([intersection([outer, jaw_sector]), *(intersection([outer, k]) for k in _cones(CAP_DEG, reach))])
    jaw = difference(jaw, [cylinder_between((0, s * (r_i_in - 3), 0), (0, s * (R + 1), 0), PIN_R + g) for s in (1, -1)])
    pins = [cylinder_between((0, s * (r_i_in - 1.5), 0), (0, s * float(np.sqrt((R - 0.2) ** 2 - PIN_R ** 2)), 0), PIN_R)
            for s in (1, -1)]

    # ---- mouth
    y_lim = r_i_in * float(np.cos(np.radians(cap_in + 2.0))) - 0.4   # plates stay off the inner caps
    roof, teeth_u = _mouth_upper(r_wall, g / 2, stagger=False, y_lim=y_lim)
    floor_up, teeth_l_up = _mouth_upper(r_wall, g / 2, stagger=True, y_lim=y_lim)
    floor, teeth_l = _mirror_z(floor_up), _mirror_z(teeth_l_up)
    opened = _rot_y(rest)
    for m in (jaw, floor, teeth_l):
        m.apply_transform(opened)
    down = tuple(float(v) for v in opened[:3, :3] @ [0, 0, -1])
    up = tuple(-v for v in down)

    body, jaw, roof, floor, teeth_u, teeth_l = (clean(m) for m in (body, jaw, roof, floor, teeth_u, teeth_l))
    eyes = [(clean(e[0]), clean(e[1]), e[2], e[3]) for e in eyes]
    parts = [
        part("body_upper", body, "black", (0, 0, 1)),
        part("jaw_lower", jaw, "black", down),             # lip on the bed
        part("hinge_pin_left", pins[0], "black", (0, 1, 0)),
        part("hinge_pin_right", pins[1], "black", (0, -1, 0)),
        part("mouth_roof", roof, "red", (0, 0, 1)),
        part("mouth_floor", floor, "red", up),
        part("teeth_upper", teeth_u, "white", (0, 0, -1)),  # strip back on the bed, teeth up
        part("teeth_lower", teeth_l, "white", up),
        part("eye_left", eyes[0][0], "white", tuple(-eyes[0][3])),     # flange back on the bed
        part("eye_right", eyes[1][0], "white", tuple(-eyes[1][3])),
        part("pupil_left", eyes[0][1], "black", tuple(-eyes[0][3])),
        part("pupil_right", eyes[1][1], "black", tuple(-eyes[1][3])),
    ]
    axis = {"axis_origin": [0.0, 0.0, 0.0], "axis_direction": [0.0, 1.0, 0.0]}   # +angle: front of jaw drops
    mates: list[dict[str, Any]] = [
        {"name": "jaw_hinge", "type": "hinge", "a": "body_upper", "b": "jaw_lower", "clearance_mm": c,
         **axis, "range_deg": [0.0, float(full - rest)]},
    ]
    for side in ("left", "right"):
        mates += [
            {"name": f"pin_{side}_in_upper", "type": "fixed", "a": "body_upper", "b": f"hinge_pin_{side}", "clearance_mm": 0},
            # the jaw hole gives g; ask for 0.8 c because the mesh is faceted
            {"name": f"pin_{side}_in_jaw", "type": "link", "a": f"hinge_pin_{side}", "b": "jaw_lower", "clearance_mm": c * 0.8},
        ]
    mates += [
        {"name": "mouth_roof_seat", "type": "fixed", "a": "body_upper", "b": "mouth_roof"},
        {"name": "mouth_floor_seat", "type": "fixed", "a": "jaw_lower", "b": "mouth_floor"},
        {"name": "teeth_upper_seat", "type": "fixed", "a": "mouth_roof", "b": "teeth_upper"},
        {"name": "teeth_lower_seat", "type": "fixed", "a": "mouth_floor", "b": "teeth_lower"},
        {"name": "eye_left_seat", "type": "fixed", "a": "body_upper", "b": "eye_left"},
        {"name": "eye_right_seat", "type": "fixed", "a": "body_upper", "b": "eye_right"},
        {"name": "pupil_left_seat", "type": "fixed", "a": "eye_left", "b": "pupil_left"},
        {"name": "pupil_right_seat", "type": "fixed", "a": "eye_right", "b": "pupil_right"},
    ]
    return parts, mates


HEAD_PREFIXES = ("body_upper", "jaw_lower", "hinge_pin", "mouth_", "teeth_", "eye_", "pupil_")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gen.head", description="Build the Chain Chomp head parts.")
    ap.add_argument("--job-dir", required=True)
    ap.add_argument("--job")
    ap.add_argument("--diameter", type=float, default=100.0)
    ap.add_argument("--wall", type=float, default=2.4)
    ap.add_argument("--jaw-rest", type=float, default=REST_DEG, help="jaw opening as built, degrees")
    ap.add_argument("--jaw-open", type=float, default=MAX_DEG, help="jaw fully open, degrees")
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
        if not 1.2 <= args.wall <= 4:
            raise ValueError("--wall must be between 1.2 and 4 mm")
        limits = job_limits(job_dir)
        job = args.job or (load_json(job_dir / "brief.json").get("job") if (job_dir / "brief.json").exists() else None) or "head"
        parts, mates = build_head(args.diameter, args.wall, limits["clearance_mm"], (args.jaw_rest, args.jaw_open))
        save_parts(job_dir, job, parts, mates, limits["clearance_mm"], limits["min_wall_mm"], drop_prefixes=HEAD_PREFIXES)
    except (OSError, ValueError, KeyError) as exc:
        print(f"gen.head: {exc}", file=sys.stderr)
        return 2
    for p in parts:
        size = p["mesh"].extents
        print(f"{p['name']}: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm, {p['mesh'].volume:.0f} mm3, {len(p['mesh'].faces)} tris")
    return 0


if __name__ == "__main__":
    sys.exit(main())
