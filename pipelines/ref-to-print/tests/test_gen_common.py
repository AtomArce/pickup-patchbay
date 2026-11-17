import trimesh

from checks.report import load_json
from gen import common


def test_save_parts_writes_merges_and_drops(tmp_path):
    a = trimesh.creation.box(extents=(10, 10, 10))
    b = a.copy()
    b.apply_translation((20, 0, 0))
    mate = {"name": "ab", "type": "fixed", "a": "x_1", "b": "x_2"}
    common.save_parts(tmp_path, "t", [common.part("x_1", a, "black", (0, 0, 1)), common.part("x_2", b)], [mate], 0.3, 1.2)
    common.save_parts(tmp_path, "t", [common.part("y", a)], [], 0.25)
    m = load_json(tmp_path / "parts.manifest.json", "parts.manifest")
    assert [p["name"] for p in m["parts"]] == ["x_1", "x_2", "y"] and m["clearance_mm"] == 0.25
    common.save_parts(tmp_path, "t", [common.part("x_1", a)], [], 0.25, drop_prefixes=("x_",))
    m = load_json(tmp_path / "parts.manifest.json", "parts.manifest")
    assert sorted(p["name"] for p in m["parts"]) == ["x_1", "y"] and m["mates"] == []
    assert not (tmp_path / "parts/x_2.stl").exists()


def test_booleans_stay_watertight():
    box = trimesh.creation.box(extents=(20, 20, 20))
    hole = common.cylinder_between((0, 0, -15), (0, 0, 15), 4)
    assert common.difference(box, [hole]).is_watertight
