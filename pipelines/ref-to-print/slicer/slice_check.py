"""Slice each part with PrusaSlicer or OrcaSlicer and report time and filament use.

Usage: python -m slicer.slice_check --mesh a.stl b.stl [--out-dir DIR]
       python -m slicer.slice_check --job-dir jobs/NAME
Exit codes: 0 all parts sliced, 1 a part failed, 2 usage error or no slicer found.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from checks.report import EXIT_ERROR, EXIT_FAIL, EXIT_PASS, load_json, validate

SLICER_NAMES = ["orca-slicer", "OrcaSlicer", "prusa-slicer", "PrusaSlicer"]
UNVERIFIED = "UNVERIFIED on this machine: no slicer installed on 2026-11-16"


def slicer_kind(slicer: str) -> str:
    """'orcaslicer' or 'prusaslicer', guessed from the binary name."""
    name = Path(slicer).name.lower().replace("-", "").replace("_", "")
    return "orcaslicer" if "orca" in name else "prusaslicer"


# --- THE SLICER COMMAND LINE LIVES HERE (only place to edit) -----------------
def build_command(slicer: str, input_stl: Path, output: Path, profile: Path | None) -> list[str]:
    """Return argv for one slice. R2P_SLICER_CMD overrides the templates below."""
    override = os.environ.get("R2P_SLICER_CMD")
    if override:
        # Placeholders: {slicer} {input} {output} {profile} (profile is "" when unset).
        text = override.format(
            slicer=shlex.quote(slicer),
            input=shlex.quote(str(input_stl)),
            output=shlex.quote(str(output)),
            profile=shlex.quote(str(profile)) if profile else "",
        )
        return shlex.split(text)
    if slicer_kind(slicer) == "orcaslicer":
        # UNVERIFIED on this machine: no slicer installed on 2026-11-16.
        # Flags --slice 0, --load-settings "a.json;b.json", --outputdir are on
        # orcaslicer.com/wiki/cli. The G-code file name is chosen by Orca (plate_N.gcode
        # is assumed), so we give it a directory and collect the file afterwards.
        cmd = [slicer, "--slice", "0", "--outputdir", str(orca_outdir(output))]
        if profile:
            cmd += ["--load-settings", str(profile)]
        return cmd + [str(input_stl)]
    # UNVERIFIED on this machine: no slicer installed on 2026-11-16.
    cmd = [slicer, "--export-gcode"]
    if profile:
        cmd += ["--load", str(profile)]
    return cmd + ["--output", str(output), str(input_stl)]


def orca_outdir(output: Path) -> Path:
    return output.parent / f".{output.stem}.orca"
# -----------------------------------------------------------------------------


def find_slicer(explicit: str | None) -> str | None:
    """Explicit argument, then R2P_SLICER, then PATH search. None if nothing found."""
    for cand in (explicit, os.environ.get("R2P_SLICER")):
        if cand:
            return shutil.which(cand) or (cand if Path(cand).exists() else None)
    for name in SLICER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def slicer_version(slicer: str) -> str | None:
    for flag in ("--version", "--help"):
        try:
            p = subprocess.run([slicer, flag], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        for line in (p.stdout + p.stderr).splitlines():
            if line.strip():
                return line.strip()
    return None


def parse_duration(text: str) -> float | None:
    """'1d 2h 3m 4s' -> seconds. None if no part is found."""
    parts = re.findall(r"(\d+)\s*([dhms])", text)
    if not parts:
        return None
    mult = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return float(sum(int(n) * mult[u] for n, u in parts))


def parse_gcode(path: Path) -> tuple[float | None, float | None]:
    """Return (time_s, filament_g) from slicer comments; None when absent.

    The comments sit at the start (Orca) or end (Prusa) of the file, so only
    the first and last 256 KiB are read.
    """
    size = path.stat().st_size
    chunk = 256 * 1024
    with path.open("rb") as f:
        head = f.read(chunk)
        tail = b""
        if size > chunk:
            f.seek(max(chunk, size - chunk))
            tail = f.read()
    lines = (head + b"\n" + tail).decode("utf-8", errors="replace").splitlines()
    time_s: float | None = None
    filament: float | None = None
    total: float | None = None
    for line in lines:
        if not line.startswith(";"):
            continue
        m = re.match(r";\s*estimated printing time \(normal mode\)\s*=\s*(.+)", line)
        if m and time_s is None:
            time_s = parse_duration(m.group(1))
        m = re.match(r";\s*total filament used \[g\]\s*=\s*([\d.]+)", line)
        if m and total is None:
            total = float(m.group(1))
        m = re.match(r";\s*filament used \[g\]\s*=\s*([\d.,\s]+)", line)
        if m and filament is None:
            nums = [float(x) for x in re.findall(r"[\d.]+", m.group(1))]
            filament = sum(nums) if nums else None
    return time_s, (total if total is not None else filament)


def slice_one(slicer: str, mesh: Path, output: Path, profile: Path | None, timeout: float) -> dict[str, Any]:
    plate: dict[str, Any] = {"input": str(mesh), "output": str(output), "passed": False,
                             "time_s": None, "filament_g": None, "errors": []}
    errors: list[str] = plate["errors"]
    if not mesh.is_file():
        errors.append(f"input file not found: {mesh}")
        return plate
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    cmd = build_command(slicer, mesh, output, profile)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        errors.append(f"slicer timed out after {timeout:g} s")
        return plate
    except OSError as e:
        errors.append(f"could not run slicer: {e}")
        return plate
    if slicer_kind(slicer) == "orcaslicer" and not os.environ.get("R2P_SLICER_CMD"):
        outdir = orca_outdir(output)
        found = sorted(outdir.glob("*.gcode")) if outdir.is_dir() else []
        if found:
            shutil.move(str(found[0]), output)
        shutil.rmtree(outdir, ignore_errors=True)
    if p.returncode != 0:
        tail = [ln for ln in (p.stderr or p.stdout).splitlines() if ln.strip()][-5:]
        errors.append(f"slicer exited with code {p.returncode}")
        errors.extend(tail)
        return plate
    if not output.is_file() or output.stat().st_size == 0:
        errors.append("slicer exited 0 but wrote no G-code (missing or empty output file)")
        return plate
    plate["time_s"], plate["filament_g"] = parse_gcode(output)
    plate["passed"] = True
    return plate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="slicer.slice_check", description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--mesh", nargs="+", metavar="FILE")
    src.add_argument("--job-dir", metavar="DIR")
    ap.add_argument("--out-dir", metavar="DIR", help="G-code folder for --mesh (default: next to each mesh)")
    ap.add_argument("--slicer", metavar="PATH_OR_NAME")
    ap.add_argument("--profile", metavar="FILE")
    ap.add_argument("--report", metavar="FILE")
    ap.add_argument("--job", metavar="NAME")
    ap.add_argument("--timeout", type=float, default=600, metavar="SECONDS")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return EXIT_ERROR if e.code else EXIT_PASS

    slicer = find_slicer(args.slicer)
    if slicer is None:
        print("slice_check: no slicer found (tried orca-slicer, OrcaSlicer, prusa-slicer, "
              "PrusaSlicer on PATH, --slicer and R2P_SLICER); nothing was sliced", file=sys.stderr)
        return EXIT_ERROR

    jobs: list[tuple[Path, Path]] = []
    job_name = args.job
    report_path = args.report
    if args.job_dir:
        job_dir = Path(args.job_dir)
        try:
            manifest = load_json(job_dir / "parts.manifest.json", "parts.manifest")
        except Exception as e:  # unreadable or invalid manifest is a usage error
            print(f"slice_check: cannot use manifest in {job_dir}: {e}", file=sys.stderr)
            return EXIT_ERROR
        job_name = job_name or manifest["job"]
        report_path = report_path or str(job_dir / "slice.report.json")
        jobs = [(job_dir / p["stl"], job_dir / "sliced" / f"{p['name']}.gcode") for p in manifest["parts"]]
    else:
        for m in args.mesh:
            mesh = Path(m)
            out_dir = Path(args.out_dir) if args.out_dir else mesh.parent
            jobs.append((mesh, out_dir / f"{mesh.stem}.gcode"))

    profile = Path(args.profile) if args.profile else None
    if profile and not profile.is_file():
        print(f"slice_check: profile not found: {profile}", file=sys.stderr)
        return EXIT_ERROR

    plates = [slice_one(slicer, mesh, out, profile, args.timeout) for mesh, out in jobs]
    report = {
        "schema": "slice.report/1",
        "job": job_name,
        "slicer": slicer_kind(slicer),
        "slicer_version": slicer_version(slicer),
        "profile": str(profile) if profile else None,
        "passed": bool(plates) and all(p["passed"] for p in plates),
        "plates": plates,
    }
    validate(report, "slice.report")
    import json
    text = json.dumps(report, indent=2) + "\n"
    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(text)
    else:
        sys.stdout.write(text)
    return EXIT_PASS if report["passed"] else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
