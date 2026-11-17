"""Tests for the clearance test coupon generator."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from checks import fit_check, mesh_check
from checks.report import validate
from gen import coupon
from gen.coupon import DEFAULT_GAPS, FIRST_X, PITCH, build, main


def _parts(gaps=DEFAULT_GAPS, peg_diameter=8.0) -> dict[str, trimesh.Trimesh]:
    return {p["name"]: p["mesh"] for p in build(gaps, peg_diameter)}


def _section_points(mesh: trimesh.Trimesh, z: float) -> np.ndarray:
    """XY vertices of the cut edges in a horizontal plane at height z (no path code needed)."""
    segments = trimesh.intersections.mesh_plane(mesh, plane_normal=[0, 0, 1], plane_origin=[0, 0, z])
    return segments.reshape(-1, 3)[:, :2]


def _diameter_near(points: np.ndarray, cx: float, cy: float, reach: float = 6.0) -> float:
    """Diameter of the loop around (cx, cy): twice the farthest cut point within reach."""
    dist = np.hypot(points[:, 0] - cx, points[:, 1] - cy)
    return 2 * float(dist[dist < reach].max())


def _polygon_area(radius: float, sides: int) -> float:
    return 0.5 * sides * radius**2 * np.sin(2 * np.pi / sides)


@pytest.mark.parametrize("gaps", [(0.2,), (0.2, 0.3, 0.4), DEFAULT_GAPS])
def test_both_parts_are_watertight(gaps):
    parts = _parts(gaps)
    assert parts["coupon_plate"].is_watertight
    assert parts["coupon_peg"].is_watertight


@pytest.mark.parametrize("gaps", [(0.2,), (0.2, 0.3, 0.4), DEFAULT_GAPS])
def test_plate_volume_shows_one_through_hole_per_gap(gaps):
    # Exact polygon areas: outline, one 96-sided hole per gap (through), and the dimples
    # (32-sided, 1 mm deep, 1 + 2 + ... + n of them). A missing or extra hole changes this by >100 mm3.
    plate = _parts(gaps)["coupon_plate"]
    length = plate.bounds[1][0]
    outline = length * coupon.PLATE_W - coupon.CHAMFER**2 / 2
    holes = sum(_polygon_area((8.0 + 2 * g) / 2, 96) for g in gaps) * coupon.PLATE_T
    dimples = len(gaps) * (len(gaps) + 1) // 2
    dimple_area = _polygon_area(coupon.DIMPLE_D / 2, 32) * coupon.DIMPLE_DEPTH
    expected = outline * coupon.PLATE_T - holes - dimples * dimple_area
    assert abs(plate.volume - expected) < 0.05


def test_default_hole_diameters_match_peg_plus_twice_gap():
    points = _section_points(_parts()["coupon_plate"], z=3.0)
    for i, gap in enumerate(DEFAULT_GAPS):
        measured = _diameter_near(points, FIRST_X + PITCH * i, 0.0)
        assert abs(measured - (8.0 + 2 * gap)) < 0.03, (i, measured)


def test_peg_diameter_and_height():
    peg = _parts()["coupon_peg"]
    points = _section_points(peg, z=8.0)
    assert abs(_diameter_near(points, *points.mean(axis=0)) - 8.0) < 0.03
    assert abs(peg.bounds[1][2] - 14.0) < 1e-6


def test_plate_and_peg_are_apart():
    parts = _parts()
    plate, peg = parts["coupon_plate"], parts["coupon_peg"]
    # Separation along the best axis: positive means the bounding boxes do not overlap on that axis.
    separation = np.maximum(peg.bounds[0] - plate.bounds[1], plate.bounds[0] - peg.bounds[1])
    assert separation.max() >= 5.0


def test_cli_writes_manifest_and_sheet(tmp_path: Path, capsys):
    job_dir = tmp_path / "job"
    assert main(["--job-dir", str(job_dir)]) == 0

    manifest = json.loads((job_dir / "parts.manifest.json").read_text())
    validate(manifest, "parts.manifest")
    assert {p["name"] for p in manifest["parts"]} == {"coupon_plate", "coupon_peg"}
    assert manifest["clearance_mm"] == pytest.approx(min(DEFAULT_GAPS))

    sheet = (job_dir / "coupon.md").read_text()
    assert sheet.strip()
    assert "python -m r2p set coupon clearance_mm=VALUE" in sheet
    assert str(job_dir / "coupon.md") in capsys.readouterr().out


def test_cli_rejects_bad_gaps(tmp_path: Path, capsys):
    assert main(["--job-dir", str(tmp_path), "--gaps", "0.1,abc"]) == 2
    assert capsys.readouterr().err.strip()


def test_cli_output_passes_checks(tmp_path: Path):
    job_dir = tmp_path / "job"
    assert main(["--job-dir", str(job_dir)]) == 0
    assert mesh_check.main(["--job-dir", str(job_dir), "--manifest", "parts", "--min-wall", "1.2"]) == 0
    assert fit_check.main(["--job-dir", str(job_dir), "--printer", "ender3-v3se"]) == 0
