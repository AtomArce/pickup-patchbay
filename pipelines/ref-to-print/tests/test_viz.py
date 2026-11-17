from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageOps

from checks.report import validate
from gen.common import part, save_parts
from viz import compare, render


def make_job(tmp_path: Path, parts: list[dict], mates: list[dict] | None = None) -> Path:
    save_parts(tmp_path, "t", parts, mates or [], clearance_mm=0.3)
    return tmp_path


def box(extents, at=(0, 0, 0)) -> trimesh.Trimesh:
    return trimesh.creation.box(extents=extents, transform=trimesh.transformations.translation_matrix(at))


def test_cube_front_silhouette(tmp_path, cube):
    job = make_job(tmp_path, [part("cube", cube)])
    scene = render.load_scene(job)
    shaded, sil = render.render_view(scene, "front", 300)
    scale = render.fit_scale(scene, 300)
    assert shaded.size == sil.size == (300, 300)
    black = np.asarray(sil)[:, :, 0] == 0
    ys, xs = np.nonzero(black)
    assert abs((xs.max() - xs.min() + 1) - 20 * scale) <= 2
    assert abs((ys.max() - ys.min() + 1) - 20 * scale) <= 2
    assert black.sum() == (xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1)  # filled
    px = np.asarray(shaded)
    for corner in (px[0, 0], px[0, -1], px[-1, 0], px[-1, -1]):
        assert tuple(corner) == render.BACKGROUND


def test_sphere_area(tmp_path):
    r = 15
    job = make_job(tmp_path, [part("ball", trimesh.creation.icosphere(subdivisions=4, radius=r))])
    scene = render.load_scene(job)
    _, sil = render.render_view(scene, "front", 512)
    area = (np.asarray(sil)[:, :, 0] == 0).sum()
    expect = math.pi * r**2 * render.fit_scale(scene, 512) ** 2
    assert abs(area - expect) / expect < 0.02


def test_two_colours_appear(tmp_path):
    job = make_job(tmp_path, [
        part("a", box((10, 10, 10), (0, -20, 0)), colour="white"),
        part("b", box((10, 10, 10), (0, 20, 0)), colour="brown"),
    ])
    shaded, _ = render.render_view(render.load_scene(job), "front", 256)
    px = np.asarray(shaded).astype(int).reshape(-1, 3)
    assert ((px[:, 0] > 150) & (px[:, 0] < 240) & (px[:, 0] == px[:, 2])).any()  # white
    assert ((px[:, 0] > px[:, 2] + 30) & (px[:, 0] < 140)).any()  # brown


def test_zbuffer(tmp_path):
    job = make_job(tmp_path, [
        part("big", box((20, 100, 100)), colour="white"),
        part("small", box((10, 20, 20), (30, 0, 0)), colour="red"),  # on the +X side, in front
    ])
    scene = render.load_scene(job)

    def centre(view: str) -> np.ndarray:
        img = np.asarray(render.render_view(scene, view, 256)[0]).astype(int)
        return img[128, 128]

    front, back = centre("front"), centre("back")
    assert front[0] > front[1] + 30
    assert not back[0] > back[1] + 30


def test_pose(tmp_path):
    mates = [
        {"name": "hinge", "type": "hinge", "a": "base", "b": "arm", "axis_origin": [0, 0, 0],
         "axis_direction": [0, 0, 1], "clearance_mm": 0.3},
        {"name": "glue", "type": "fixed", "a": "arm", "b": "tip", "clearance_mm": 0},
    ]
    job = make_job(tmp_path, [
        part("base", box((10, 10, 10))),
        part("arm", box((20, 6, 6), (30, 0, 0))),
        part("tip", box((6, 6, 6), (50, 0, 0))),
    ], mates)
    base = render.load_scene(job)
    posed = render.load_scene(job, pose={"hinge": 90})
    centroids = {n: m.bounds.mean(axis=0) for n, m, _ in posed}
    assert np.allclose(centroids["arm"], [0, 30, 0], atol=1e-6)
    assert np.allclose(centroids["tip"], [0, 50, 0], atol=1e-6)
    assert np.allclose(centroids["base"], [0, 0, 0], atol=1e-6)
    scale = render.fit_scale(base, 256)
    s0 = np.asarray(render.render_view(base, "top", 256, scale)[1])
    s45 = np.asarray(render.render_view(render.load_scene(job, pose={"hinge": 45}), "top", 256, scale)[1])
    assert (s0 != s45).any()
    assert render.main(["--job-dir", str(job), "--pose", "nope=10"]) == 2


def test_cli_writes_index(tmp_path, cube, capsys):
    job = make_job(tmp_path, [part("cube", cube)])
    assert render.main(["--job-dir", str(job), "--size", "64", "--views", "front,top"]) == 0
    index = json.loads((job / "views" / "index.json").read_text())
    assert index["scale_px_per_mm"] > 0
    assert (job / "views" / "silhouette_top.png").exists()
    assert render.main(["--job-dir", str(job), "--views", "sideways"]) == 2


def shape(draw_fn, size=200) -> Image.Image:
    img = Image.new("RGB", (size, size), "white")
    draw_fn(ImageDraw.Draw(img))
    return img


def run_compare(tmp_path: Path, render_img: Image.Image, ref_img: Image.Image, min_iou: float = 0.6):
    r, f, out = tmp_path / "r.png", tmp_path / "f.png", tmp_path / "report.json"
    render_img.save(r)
    ref_img.save(f)
    code = compare.main(["--render", str(r), "--ref", str(f), "--out", str(out), "--min-iou", str(min_iou)])
    return code, json.loads(out.read_text())


def test_compare_identical(tmp_path):
    img = shape(lambda d: d.ellipse((40, 60, 160, 140), fill="black"))
    code, rep = run_compare(tmp_path, img, img)
    assert code == 0
    assert rep["results"][0]["value"] == 1.0
    validate(rep, "check.report")


def test_compare_circle_vs_bar(tmp_path):
    circle = shape(lambda d: d.ellipse((50, 50, 150, 150), fill="black"))
    bar = shape(lambda d: d.rectangle((20, 95, 180, 105), fill="black"))
    code, rep = run_compare(tmp_path, circle, bar)
    assert code == 1
    assert rep["results"][0]["value"] < 0.3


def test_compare_shift_scale(tmp_path):
    def l_shape(d, o=0, k=1.0):
        pts = [(0, 0), (30, 0), (30, 70), (80, 70), (80, 100), (0, 100)]
        d.polygon([(o + x * k, o + y * k) for x, y in pts], fill="black")
    a = shape(lambda d: l_shape(d, 20, 1.0), 300)
    b = shape(lambda d: l_shape(d, 60, 1.8), 400)
    code, rep = run_compare(tmp_path, a, b)
    assert code == 0 and rep["results"][0]["value"] > 0.95


def test_compare_mirrored(tmp_path):
    a = shape(lambda d: d.polygon([(20, 20), (60, 20), (60, 120), (160, 120), (160, 160), (20, 160)], fill="black"))
    code, rep = run_compare(tmp_path, a, ImageOps.mirror(a))
    assert code == 0 and rep["results"][0]["value"] > 0.95
    assert "reference mirrored" in rep["results"][0]["note"]
    code, rep = run_compare(tmp_path, a, a)
    assert "not mirrored" in rep["results"][0]["note"]


def test_compare_alpha_and_bad_input(tmp_path):
    rgba = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(rgba).ellipse((20, 20, 80, 80), fill=(255, 0, 0, 255))
    code, rep = run_compare(tmp_path, rgba, rgba)
    assert code == 0 and "alpha" in rep["results"][0]["note"]
    assert compare.main(["--render", str(tmp_path / "missing.png"), "--ref", str(tmp_path / "r.png")]) == 2


def test_performance(tmp_path):
    ball = trimesh.creation.icosphere(subdivisions=5, radius=20)
    assert len(ball.faces) >= 20000
    scene = [("ball", ball, (150, 150, 155))]
    t = time.perf_counter()
    render.render_view(scene, "three_quarter", 512)
    assert time.perf_counter() - t < 5
