"""Tests for checks.mate_check, using tiny manifests and meshes written to tmp_path."""

from __future__ import annotations

import json
import warnings
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
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)  # the empty-boolean divide-by-zero must be gone
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


def box(x0, y0, z0, x1, y1, z1):
    return trimesh.creation.box(bounds=[(x0, y0, z0), (x1, y1, z1)])


def hinge_mate(range_deg=(0, 90)):
    return {"name": "hinge", "type": "hinge", "a": "wall", "b": "arm", "axis_origin": [0, 0, 0],
            "axis_direction": [0, 0, 1], "range_deg": list(range_deg)}


def glue(a, b):
    return {"name": f"glue_{a}_{b}", "type": "fixed", "a": a, "b": b, "clearance_mm": 0}


def block_job(tmp_path, save_mesh, block_x1):
    # Hinge about z at the origin. wall is the slab y 30..40. arm is x 2..12, y -1..1: it sweeps a
    # circle of radius <= 12.1, so it clears the wall at every angle. The block is fixed to the arm,
    # x 22..block_x1, y -2..2. With block_x1 = 33 its radius reaches ~33 > 30, so as the arm turns
    # towards +y the block enters the wall (about 72 deg and beyond; the sweep ends at 90). It is
    # clear at 0 deg (y <= 2). With block_x1 = 26 the block radius stays ~26 < 30: clear throughout.
    meshes = {"wall": box(-40, 30, 0, 40, 40, 10), "arm": box(2, -1, 0, 12, 1, 10),
              "blk": box(22, -2, 0, block_x1, 2, 10)}
    return write_job(tmp_path, save_mesh, meshes, [hinge_mate(), glue("arm", "blk")])


def test_block_fixed_to_b_swings_into_a_fails(tmp_path, save_mesh):
    code, report = run(block_job(tmp_path, save_mesh, 33))
    sweep = by_rule(report)["sweep_clear"]
    assert code == 1 and not sweep["passed"]
    assert "blk against wall" in sweep["note"]
    assert "skipped" not in sweep["note"]


def test_block_fixed_to_b_that_clears_passes(tmp_path, save_mesh):
    code, report = run(block_job(tmp_path, save_mesh, 26))
    sweep = by_rule(report)["sweep_clear"]
    assert code == 0 and sweep["passed"]
    assert "moving group: arm, blk" in sweep["note"]


def test_b_swings_into_part_fixed_to_a_fails(tmp_path, save_mesh):
    # post is glued to the wall (still group), x -2..2, y 6..10. The arm lies along +x at 0 deg
    # (clear of the post) and along +y at 90 deg (x -1..1, y 2..12), where it cuts into the post.
    meshes = {"wall": box(-40, 30, 0, 40, 40, 10), "arm": box(2, -1, 0, 12, 1, 10),
              "post": box(-2, 6, 0, 2, 10, 10)}
    code, report = run(write_job(tmp_path, save_mesh, meshes, [hinge_mate(), glue("wall", "post")]))
    sweep = by_rule(report)["sweep_clear"]
    assert code == 1 and not sweep["passed"]
    assert "arm against post" in sweep["note"]


def test_part_fixed_to_both_sides_gives_exit_2(tmp_path, save_mesh, capsys):
    meshes = {"wall": box(-40, 30, 0, 40, 40, 10), "arm": box(2, -1, 0, 12, 1, 10),
              "c": box(20, 0, 0, 24, 4, 10)}
    folder = write_job(tmp_path, save_mesh, meshes, [hinge_mate(), glue("wall", "c"), glue("arm", "c")])
    assert mate_check.main(["--job-dir", str(folder)]) == 2
    err = capsys.readouterr().err
    assert "hinge" in err and "c" in err
