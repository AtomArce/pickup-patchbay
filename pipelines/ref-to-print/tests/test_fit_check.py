"""Tests for checks/fit_check.py: build volume fit and manifest bbox agreement."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import trimesh

from checks import report
from checks.fit_check import check_fit, main
from checks.report import load_printer


def _rule(doc: dict[str, Any], rule: str) -> dict[str, Any]:
    return next(r for r in doc["results"] if r["rule"] == rule)


def _write_job(folder: Path, parts: list[dict[str, Any]]) -> Path:
    """Write parts.manifest.json for the given parts into folder and return folder."""
    manifest = {
        "schema": "parts.manifest/1",
        "job": "test-job",
        "units": "mm",
        "up_axis": "Z",
        "clearance_mm": 0.3,
        "parts": parts,
        "mates": [],
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "parts.manifest.json").write_text(json.dumps(manifest))
    return folder


def test_cube_fits(cube, save_mesh, tmp_path):
    path = save_mesh(cube, tmp_path, "cube.stl")
    out = tmp_path / "report.json"
    assert main(["--mesh", str(path), "--out", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert doc["passed"] is True
    assert _rule(doc, "fits_build_volume")["part"] == "cube"


def test_big_box_fails(big_box, save_mesh, tmp_path):
    path = save_mesh(big_box, tmp_path, "big.stl")
    out = tmp_path / "report.json"
    assert main(["--mesh", str(path), "--out", str(out)]) == 1
    rule = _rule(json.loads(out.read_text()), "fits_build_volume")
    assert rule["passed"] is False
    assert rule["value"] >= 50


def test_long_box_stands_on_end_without_print_up():
    box = trimesh.creation.box(extents=(240, 100, 100))
    results = check_fit(box, "long", load_printer("ender3-v3se"))
    assert results[0]["rule"] == "fits_build_volume"
    assert results[0]["passed"] is True


def test_long_box_fails_with_print_up_in_manifest(tmp_path, save_mesh):
    box = trimesh.creation.box(extents=(240, 100, 100))
    job = tmp_path / "job"
    save_mesh(box, job, "long.stl")
    _write_job(job, [{"name": "long", "stl": "long.stl", "print_up": [0, 0, 1]}])
    out = tmp_path / "report.json"
    assert main(["--job-dir", str(job), "--out", str(out)]) == 1
    rule = _rule(json.loads(out.read_text()), "fits_build_volume")
    assert rule["passed"] is False
    assert rule["value"] > 0


def test_bbox_wrong_by_5mm_fails(tmp_path, cube, save_mesh):
    save_mesh(cube, tmp_path, "cube.stl")
    # Cube bounds are -10..10; the manifest says the top is at 15, which is 5 mm off.
    parts = [{"name": "cube", "stl": "cube.stl",
              "bbox_mm": {"min": [-10, -10, -10], "max": [10, 10, 15]}}]
    job = _write_job(tmp_path, parts)
    out = tmp_path / "report.json"
    assert main(["--job-dir", str(job), "--out", str(out)]) == 1
    rule = _rule(json.loads(out.read_text()), "bbox_matches_manifest")
    assert rule["passed"] is False
    assert abs(rule["value"] - 5) < 1e-6
    assert rule["limit"] == 0.5


def test_missing_file_exits_2(tmp_path):
    assert main(["--mesh", str(tmp_path / "nope.stl")]) == 2


def test_out_file_matches_report_schema(cube, save_mesh, tmp_path):
    path = save_mesh(cube, tmp_path, "cube.stl")
    out = tmp_path / "nested" / "report.json"
    main(["--mesh", str(path), "--out", str(out), "--job", "demo"])
    doc = json.loads(out.read_text())
    report.validate(doc, "check.report")
    assert doc["job"] == "demo"
