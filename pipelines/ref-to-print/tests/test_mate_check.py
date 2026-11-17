"""Tests for checks.mate_check, using tiny manifests and meshes written to tmp_path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from checks import mate_check
from checks.report import validate


def write_job(folder: Path, save_mesh, meshes: dict[str, trimesh.Trimesh], mates: list[dict[str, Any]]) -> Path:
    parts = []
    for name, mesh in meshes.items():
        save_mesh(mesh, folder, f"{name}.stl")
        parts.append({"name": name, "stl": f"{name}.stl"})
    manifest = {"schema": "parts.manifest/1", "job": "t", "units": "mm", "up_axis": "Z",
                "clearance_mm": 0.3, "parts": parts, "mates": mates}
    (folder / "parts.manifest.json").write_text(json.dumps(manifest))
    return folder


def run(folder: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    out = folder / "report.json"
    code = mate_check.main(["--job-dir", str(folder), "--out", str(out), *extra])
    return code, json.loads(out.read_text()) if out.exists() else {}


def by_rule(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["rule"]: r for r in report["results"]}


def true_link_gap() -> float:
    """Gap between the two wires: closest centre-line distance minus both wire radii."""
    t = np.linspace(0, 2 * np.pi, 2000, endpoint=False)
    a = np.stack([20 * np.cos(t), 20 * np.sin(t), 0 * t], axis=1)  # first link centre line
    b = np.stack([20 + 20 * np.cos(t), 0 * t, 20 * np.sin(t)], axis=1)  # second link, turned and shifted
    dist = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2).min()
    return float(dist - 8)


def link_job(tmp_path, save_mesh, link_pair, clearance=0.3, extra_shift=0.0):
    first, second = link_pair
    second = second.copy()
    second.apply_translation((extra_shift, 0, 0))
    mate = {"name": "m", "type": "link", "a": "l1", "b": "l2", "clearance_mm": clearance}
    return write_job(tmp_path, save_mesh, {"l1": first, "l2": second}, [mate])


def test_link_pair_passes_and_gap_matches_geometry(tmp_path, save_mesh, link_pair):
    code, report = run(link_job(tmp_path, save_mesh, link_pair))
    rules = by_rule(report)
    assert code == 0
    assert rules["no_intersection"]["passed"] and rules["min_gap"]["passed"]
    # True gap is 12 mm. The 32-segment test torus bulges into its own hole by up to ~0.06 mm per
    # link (chord sagitta), so the mesh gap reads ~0.115 low; that is mesh error, not search error.
    assert abs(rules["min_gap"]["value"] - true_link_gap()) < 0.15


def test_overlapping_links_fail_no_intersection(tmp_path, save_mesh, link_pair):
    code, report = run(link_job(tmp_path, save_mesh, link_pair, extra_shift=20))
    rules = by_rule(report)
    assert code == 1
    assert not rules["no_intersection"]["passed"] and rules["no_intersection"]["value"] > 1
    assert rules["min_gap"]["value"] == 0


def test_clearance_larger_than_gap_fails_min_gap_only(tmp_path, save_mesh, link_pair):
    code, report = run(link_job(tmp_path, save_mesh, link_pair, clearance=true_link_gap() + 1))
    rules = by_rule(report)
    assert code == 1
    assert rules["no_intersection"]["passed"] and not rules["min_gap"]["passed"]


def hinge_job(tmp_path, save_mesh, range_deg):
    # Block fills x 0..20, y -10..10. Flap is a thin plate x -21..-6, y -1..1, so it sits 6 mm clear
    # of the block at 0 degrees. The hinge axis is z through the origin. Turning the flap about z
    # keeps its tip near x < 0 for small angles (clear at 20), but at 90 degrees it lies along
    # y -21..-6 with x -1..1, running into the block's corner region (x 0..1, y -10..-6).
    block = trimesh.creation.box(bounds=[(0, -10, 0), (20, 10, 10)])
    flap = trimesh.creation.box(bounds=[(-21, -1, 0), (-6, 1, 10)])
    mate = {"name": "hinge", "type": "hinge", "a": "block", "b": "flap",
            "axis_origin": [0, 0, 0], "axis_direction": [0, 0, 1], "range_deg": range_deg}
    return write_job(tmp_path, save_mesh, {"block": block, "flap": flap}, [mate])


def test_hinge_small_range_passes_sweep(tmp_path, save_mesh):
    code, report = run(hinge_job(tmp_path, save_mesh, [0, 20]))
    assert code == 0 and by_rule(report)["sweep_clear"]["passed"]


def test_hinge_large_range_fails_sweep(tmp_path, save_mesh):
    code, report = run(hinge_job(tmp_path, save_mesh, [0, 90]))
    sweep = by_rule(report)["sweep_clear"]
    assert code == 1 and not sweep["passed"] and sweep["value"] > 0.01
    assert "90.0 deg" in sweep["note"]


def test_fixed_boxes_sharing_a_face_pass(tmp_path, save_mesh):
    left = trimesh.creation.box(bounds=[(0, 0, 0), (10, 10, 10)])
    right = trimesh.creation.box(bounds=[(10, 0, 0), (20, 10, 10)])
    mate = {"name": "glue", "type": "fixed", "a": "left", "b": "right", "clearance_mm": 0}
    code, report = run(write_job(tmp_path, save_mesh, {"left": left, "right": right}, [mate]))
    assert code == 0
    assert "min_gap" not in by_rule(report)
    assert by_rule(report)["no_intersection"]["value"] < 0.01


def test_unknown_part_gives_exit_2(tmp_path, save_mesh, cube, capsys):
    mate = {"name": "bad", "type": "fixed", "a": "cube", "b": "ghost"}
    folder = write_job(tmp_path, save_mesh, {"cube": cube}, [mate])
    assert mate_check.main(["--job-dir", str(folder)]) == 2
    assert "ghost" in capsys.readouterr().err


def test_missing_manifest_gives_exit_2(tmp_path):
    assert mate_check.main(["--job-dir", str(tmp_path)]) == 2


def test_out_file_validates_against_schema(tmp_path, save_mesh, link_pair):
    _, report = run(link_job(tmp_path, save_mesh, link_pair), "--job", "demo")
    validate(report, "check.report")
    assert report["check"] == "mate" and report["job"] == "demo"
