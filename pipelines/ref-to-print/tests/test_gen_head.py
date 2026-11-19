"""The head generator is accepted by the project's own checks (mesh, fit, mate) plus swing tests."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from checks import fit_check, mate_check, mesh_check
from checks.report import load_json
from gen.head import build_head, main as head_main

NAMES = ["body_upper", "jaw_lower", "hinge_pin_left", "hinge_pin_right", "mouth_roof", "mouth_floor",
         "teeth_upper", "teeth_lower", "eye_left", "eye_right", "pupil_left", "pupil_right"]
MOVING = {"jaw_lower", "mouth_floor", "teeth_lower"}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("head")
    assert head_main(["--job-dir", str(d)]) == 0
    manifest = load_json(d / "parts.manifest.json")
    meshes = {p["name"]: trimesh.load(d / p["stl"], force="mesh") for p in manifest["parts"]}
    return d, manifest, meshes


def test_parts_are_single_watertight_bodies(built):
    _, manifest, meshes = built
    assert sorted(meshes) == sorted(NAMES)
    for name, mesh in meshes.items():
        assert mesh.is_watertight, name
        assert len(mesh.split()) == 1, name
        assert mesh.volume > 0, name
    assert {m["name"] for m in manifest["mates"]} >= {"jaw_hinge", "pin_left_in_upper", "pin_left_in_jaw", "pin_right_in_jaw"}


def test_mesh_check(built):
    assert mesh_check.main(["--job-dir", str(built[0]), "--manifest", "parts", "--min-wall", "1.2"]) == 0


def test_fit_check(built):
    assert fit_check.main(["--job-dir", str(built[0]), "--printer", "ender3-v3se"]) == 0


def test_mate_check(built):
    assert mate_check.main(["--job-dir", str(built[0])]) == 0


def _rot(angle: float, mate: dict) -> np.ndarray:
    return trimesh.transformations.rotation_matrix(np.radians(angle), mate["axis_direction"], mate["axis_origin"])


def test_jaw_and_lower_teeth_swing_clear(built):
    _, manifest, meshes = built
    hinge = next(m for m in manifest["mates"] if m["name"] == "jaw_hinge")
    fixed = [meshes[n] for n in NAMES if n not in MOVING]
    for angle in (10, 25, 40):
        for name in sorted(MOVING):
            moved = meshes[name].copy()
            moved.apply_transform(_rot(angle, hinge))
            for other in fixed:
                assert mate_check.overlap_volume(other, moved) <= mate_check.MAX_OVERLAP_MM3, (name, angle)


def test_mouth_really_opens(built):
    _, manifest, meshes = built
    hinge = next(m for m in manifest["mates"] if m["name"] == "jaw_hinge")
    jaw = meshes["jaw_lower"]
    front = jaw.vertices[np.argmax(jaw.vertices[:, 0])]
    moved = trimesh.transformations.transform_points([front], _rot(40, hinge))[0]
    assert front[2] - moved[2] > 20
    assert hinge["axis_origin"] == [0.0, 0.0, 0.0]   # mouth corners at the sides of the ball, as in the reference


def test_hinge_gap_and_bbox(built):
    _, manifest, meshes = built
    assert mate_check.min_gap(meshes["body_upper"], meshes["jaw_lower"]) >= manifest["clearance_mm"]
    bounds = np.vstack([m.bounds for m in meshes.values()])
    assert np.all(bounds.max(axis=0) - bounds.min(axis=0) <= 125)


def test_build_head_api_and_bad_input(tmp_path, capsys):
    parts, mates = build_head()
    assert len(parts) == 12 and mates[0]["axis_direction"] == [0.0, 1.0, 0.0]
    with pytest.raises(ValueError):
        build_head(jaw_range=(10.0, 40.0))   # rest below the teeth's reach
    with pytest.raises(ValueError):
        build_head(jaw_range=(30.0, 75.0))   # travel would hit the band
    assert head_main(["--job-dir", str(tmp_path / "missing")]) == 2
    assert head_main(["--job-dir", str(tmp_path), "--diameter", "5"]) == 2
    assert "gen.head" in capsys.readouterr().err


def test_no_two_parts_overlap_as_built(built):
    # mate_check only looks at mated pairs; glued parts that are not mated must not overlap either.
    _, _, meshes = built
    names = sorted(meshes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert mate_check.overlap_volume(meshes[a], meshes[b]) <= mate_check.MAX_OVERLAP_MM3, (a, b)


def test_teeth_interleave_without_touching(built):
    _, _, meshes = built
    assert mate_check.min_gap(meshes["teeth_upper"], meshes["teeth_lower"]) > 0.3
