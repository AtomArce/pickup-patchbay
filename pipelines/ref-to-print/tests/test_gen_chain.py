import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from checks import fit_check, mate_check, mesh_check
from checks.report import load_json
from gen import chain

BRIEF = {**json.loads((Path(__file__).parents[1] / "jobs/chain-chomp/brief.json").read_text()), "job": "chain-test"}


@pytest.fixture(scope="module")
def built():
    return chain.build_chain()


def test_default_chain_watertight_free_and_interlocked(built):
    parts, mates = built
    meshes = [p["mesh"] for p in parts]
    assert [p["name"] for p in parts] == [f"chain_link_{i}" for i in range(1, 7)]
    assert len(mates) == 5 and all(m["type"] == "link" and m["clearance_mm"] == 0.4 for m in mates)
    assert all(m.is_watertight for m in meshes)
    for a, b in zip(meshes, meshes[1:]):
        assert mate_check.overlap_volume(a, b) == 0
        assert mate_check.min_gap(a, b) >= 0.4 - 0.05
        # Interlocked: each link's end arc lies inside its neighbour's opening, so the X extents
        # overlap by far more than one wire thickness and the pair cannot be pulled apart along X.
        x_overlap = min(a.bounds[1][0], b.bounds[1][0]) - max(a.bounds[0][0], b.bounds[0][0])
        assert x_overlap > 5.0 + 5.0
    for a, c in zip(meshes, meshes[2:]):  # non-neighbours stay apart too
        assert mate_check.overlap_volume(a, c) == 0
        assert mate_check.min_gap(a, c) > 0.3


def test_links_sit_on_the_bed_with_a_flat_footprint(built):
    for p in built[0]:
        m = p["mesh"]
        assert abs(m.bounds[0][2]) < 1e-6
        on_bed = (np.abs(m.triangles[:, :, 2]) < 1e-6).all(axis=1)
        assert m.area_faces[on_bed].sum() > 1.0


def run_cli(d, *extra):
    return chain.main(["--job-dir", str(d), *extra])


def test_cli_passes_the_pipeline_checks(tmp_path, capsys):
    (tmp_path / "brief.json").write_text(json.dumps(BRIEF))
    assert run_cli(tmp_path, "--count", "4") == 0
    assert "smallest neighbour gap" in capsys.readouterr().out
    d = str(tmp_path)
    assert mesh_check.main(["--job-dir", d, "--manifest", "parts", "--min-wall", "1.2"]) == 0
    assert fit_check.main(["--job-dir", d, "--printer", "ender3-v3se"]) == 0
    assert mate_check.main(["--job-dir", d]) == 0
    manifest = load_json(tmp_path / "parts.manifest.json")
    assert manifest["job"] == "chain-test"
    stake = next(p for p in manifest["parts"] if p["name"] == "stake")
    assert stake["colour"] == "brown" and stake["print_up"] == [0.0, 0.0, 1.0]
    chain_ymax = max(p["bbox_mm"]["max"][1] for p in manifest["parts"] if p["name"].startswith("chain_link_"))
    assert stake["bbox_mm"]["min"][1] - chain_ymax >= 8.0


def test_lower_count_replaces_old_links(tmp_path):
    assert run_cli(tmp_path, "--count", "6") == 0
    assert run_cli(tmp_path, "--count", "3") == 0
    names = sorted(p["name"] for p in load_json(tmp_path / "parts.manifest.json")["parts"])
    assert names == ["chain_link_1", "chain_link_2", "chain_link_3", "stake"]
    assert not (tmp_path / "parts/chain_link_4.stl").exists()


def test_bad_input_exits_2(tmp_path, capsys):
    assert run_cli(tmp_path, "--count", "1") == 2
    assert capsys.readouterr().err.strip()
    assert run_cli(tmp_path, "--gap", "50") == 2


def test_stake_geometry():
    s = chain.build_stake()["mesh"]
    assert isinstance(s, trimesh.Trimesh) and s.is_watertight and abs(s.bounds[0][2]) < 1e-6
