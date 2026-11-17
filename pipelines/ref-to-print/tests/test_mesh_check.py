"""Tests for checks/mesh_check.py: rules, exit codes and job-dir mode."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import trimesh

from checks.mesh_check import main
from checks.report import validate


def rules(path: Path) -> dict[str, dict]:
    """Map rule id to result for the single part in a written report."""
    return {r["rule"]: r for r in json.loads(path.read_text())["results"]}


def test_closed_cube_passes_all_rules(cube, save_mesh, tmp_path):
    mesh = save_mesh(cube, tmp_path, "cube.stl")
    out = tmp_path / "report.json"
    args = ["--mesh", str(mesh), "--max-triangles", "100", "--min-wall", "1.2", "--out", str(out)]
    assert main(args) == 0
    res = rules(out)
    assert {"watertight", "winding", "volume_positive", "max_triangles", "min_wall"} <= res.keys()
    assert all(r["passed"] for r in res.values())
    assert res["volume_positive"]["value"] == pytest.approx(8000)
    assert res["min_wall"]["value"] == pytest.approx(20, abs=0.01)


def test_open_cube_fails_watertight(open_cube, save_mesh, tmp_path):
    mesh = save_mesh(open_cube, tmp_path, "open.obj")
    out = tmp_path / "report.json"
    assert main(["--mesh", str(mesh), "--out", str(out)]) == 1
    res = rules(out)
    assert res["watertight"]["passed"] is False
    assert res["watertight"]["value"] > 0
    assert res["volume_positive"]["passed"] is False
    assert res["volume_positive"]["note"] == "not watertight"


def test_too_many_triangles_fails(cube, save_mesh, tmp_path):
    mesh = save_mesh(cube, tmp_path, "cube.stl")
    out = tmp_path / "report.json"
    assert main(["--mesh", str(mesh), "--max-triangles", "4", "--out", str(out)]) == 1
    res = rules(out)
    assert res["max_triangles"]["passed"] is False
    assert res["max_triangles"]["value"] == 12
    assert res["max_triangles"]["limit"] == 4


def test_thin_shell_fails_min_wall(save_mesh, tmp_path):
    outer = trimesh.creation.box(extents=(20, 20, 20))
    inner = trimesh.creation.box(extents=(19, 19, 19))
    shell = trimesh.boolean.difference([outer, inner], engine="manifold")
    mesh = save_mesh(shell, tmp_path, "shell.stl")
    out = tmp_path / "report.json"
    assert main(["--mesh", str(mesh), "--min-wall", "1.2", "--out", str(out)]) == 1
    wall = rules(out)["min_wall"]
    assert wall["passed"] is False
    assert wall["value"] == pytest.approx(0.5, abs=0.05)


def test_solid_cube_passes_min_wall(cube, save_mesh, tmp_path):
    mesh = save_mesh(cube, tmp_path, "cube.stl")
    assert main(["--mesh", str(mesh), "--min-wall", "1.2"]) == 0


def test_missing_file_is_usage_error(tmp_path, capsys):
    assert main(["--mesh", str(tmp_path / "nope.stl")]) == 2
    assert "no such file" in capsys.readouterr().err


def test_job_dir_mode_writes_valid_report(cube, save_mesh, tmp_path):
    job = tmp_path / "job"
    save_mesh(cube, job, "stl/cube.stl")
    (job / "parts.manifest.json").write_text(
        json.dumps(
            {
                "schema": "parts.manifest/1",
                "job": "demo",
                "units": "mm",
                "up_axis": "Z",
                "clearance_mm": 0.3,
                "parts": [{"name": "cube", "stl": "stl/cube.stl"}],
                "mates": [],
            }
        )
    )
    (job / "brief.json").write_text(
        json.dumps(
            {
                "schema": "brief/1",
                "job": "demo",
                "units": "mm",
                "printer": "ender3-v3se.json",
                "target": {"bbox_mm": [20, 20, 20]},
                "parts": [{"name": "cube"}],
                "constraints": {
                    "min_wall_mm": 1.2,
                    "clearance_mm": 0.3,
                    "max_triangles_per_part": 100,
                },
            }
        )
    )
    out = tmp_path / "out" / "mesh.json"
    assert main(["--job-dir", str(job), "--manifest", "parts", "--out", str(out)]) == 0
    doc = json.loads(out.read_text())
    validate(doc, "check.report")
    assert doc["job"] == "demo"
    assert doc["passed"] is True
    assert {r["part"] for r in doc["results"]} == {"cube"}
    assert {r["rule"] for r in doc["results"]} >= {"max_triangles", "min_wall"}
