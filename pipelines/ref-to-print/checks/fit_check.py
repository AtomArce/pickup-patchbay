"""Fit check: does each part fit the printer's usable build volume?

Usage:
    python -m checks.fit_check --mesh FILE [FILE ...] [--printer NAME]
    python -m checks.fit_check --job-dir DIR [--printer NAME] [--job NAME] [--out FILE]

Rules: fits_build_volume (any allowed orientation) and bbox_matches_manifest.
All sizes are millimetres. Exit codes: 0 passed, 1 a rule failed, 2 bad input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from checks.report import EXIT_ERROR, finish, load_json, load_printer, make_report, result

BBOX_TOLERANCE_MM = 0.5


def usable_volume(printer: dict[str, Any]) -> tuple[float, float, float]:
    """Build volume minus the bed margin on X and Y (no margin on height)."""
    x, y, z = printer["build_volume_mm"]
    margin = printer["bed_margin_mm"]
    return x - 2 * margin, y - 2 * margin, z


def _overshoot(ex: float, ey: float, ez: float, vol: tuple[float, float, float]) -> float:
    """Worst mm past the volume for one orientation, using the better X/Y swap."""
    vx, vy, vz = vol
    straight = max(ex - vx, ey - vy)
    swapped = max(ey - vx, ex - vy)
    return max(min(straight, swapped), ez - vz)


def _fit_rule(mesh: trimesh.Trimesh, name: str, vol: tuple[float, float, float],
              print_up: list[float] | None) -> dict[str, Any]:
    if print_up is not None:
        up = np.asarray(print_up, dtype=float)
        up = up / np.linalg.norm(up)
        rotated = mesh.copy()
        matrix = trimesh.geometry.align_vectors(up, [0, 0, 1])
        if matrix is not None:
            rotated.apply_transform(matrix)
        ex, ey, ez = (float(v) for v in rotated.extents)
        value = _overshoot(ex, ey, ez, vol)
        note = f"extents {ex:.2f} x {ey:.2f} x {ez:.2f} mm with print_up {up.round(3).tolist()}"
    else:
        ext = [float(v) for v in mesh.extents]
        options = []
        for axis in range(3):
            others = [i for i in range(3) if i != axis]
            options.append(_overshoot(ext[others[0]], ext[others[1]], ext[axis], vol))
        value = min(options)
        best = "XYZ"[options.index(value)]
        note = (f"extents {ext[0]:.2f} x {ext[1]:.2f} x {ext[2]:.2f} mm, "
                f"best with {best} up; no print_up given")
    return result(name, "fits_build_volume", value <= 0, value, 0, "mm", note)


def check_fit(mesh: trimesh.Trimesh, name: str, printer: dict[str, Any] | str,
              print_up: list[float] | None = None,
              manifest_bbox: dict[str, list[float]] | None = None) -> list[dict[str, Any]]:
    """Run the fit rules for one mesh. printer may be a loaded dict or a printer name."""
    if isinstance(printer, str):
        printer = load_printer(printer)
    vol = usable_volume(printer)
    results = [_fit_rule(mesh, name, vol, print_up)]
    if manifest_bbox is not None:
        want = np.array([manifest_bbox["min"], manifest_bbox["max"]], dtype=float)
        diff = float(np.abs(mesh.bounds - want).max())
        note = f"mesh bounds {mesh.bounds.round(3).tolist()} vs manifest {want.round(3).tolist()}"
        results.append(result(name, "bbox_matches_manifest", diff <= BBOX_TOLERANCE_MM,
                              diff, BBOX_TOLERANCE_MM, "mm", note))
    return results


def _load(path: Path) -> trimesh.Trimesh:
    """Load one mesh, raising ValueError for a missing or unreadable file."""
    if not path.is_file():
        raise ValueError(f"missing file: {path}")
    try:
        mesh = trimesh.load(path, force="mesh")
    except Exception as exc:  # trimesh raises many types for bad files
        raise ValueError(f"unreadable mesh {path}: {exc}") from exc
    if mesh.is_empty:
        raise ValueError(f"mesh has no geometry: {path}")
    return mesh


def _run(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.mesh:
        printer = load_printer(args.printer)
        results: list[dict[str, Any]] = []
        for file in args.mesh:
            path = Path(file)
            results += check_fit(_load(path), path.stem, printer)
        return results
    job_dir = Path(args.job_dir)
    manifest = load_json(job_dir / "parts.manifest.json")
    brief = job_dir / "brief.json"
    printer_name = load_json(brief)["printer"] if brief.is_file() else args.printer
    printer = load_printer(printer_name)
    results = []
    for part in manifest["parts"]:
        mesh = _load(job_dir / part["stl"])
        results += check_fit(mesh, part["name"], printer,
                             part.get("print_up"), part.get("bbox_mm"))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check parts fit the printer build volume.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--mesh", nargs="+", metavar="FILE", help="mesh files to check")
    source.add_argument("--job-dir", metavar="DIR", help="job folder with parts.manifest.json")
    parser.add_argument("--printer", default="ender3-v3se", help="printer name under printer/")
    parser.add_argument("--job", help="job name to record in the report")
    parser.add_argument("--out", help="write the JSON report here instead of stdout")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        results = _run(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return finish(make_report("fit", results, args.job), args.out)


if __name__ == "__main__":
    raise SystemExit(main())
