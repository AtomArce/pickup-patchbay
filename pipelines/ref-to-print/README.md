# ref-to-print

Reference images to 3D-printable parts. A skeleton, started 2026-11-16. The plan is in [docs/plan.md](docs/plan.md); the brief it answers is in [docs/plan-brief.md](docs/plan-brief.md).

## Stages

| Step | What | Where it runs | Status |
|---|---|---|---|
| S0 | Brief: `jobs/<job>/brief.json` plus reference images | anywhere | contract written |
| S1 | Form model in Maya, through an MCP server | minimott | not started |
| G1 | Form gate: watertight, triangle cap | anywhere | check written |
| S2 | Print prep in Fusion 360: solids, splits, joints | minimott | not started (Fusion not installed) |
| G2 | Parts gate: wall, fits the bed, parts mate and move | anywhere | checks written |
| S3 | Slice | where a slicer is installed | wrapper written, never run against a real slicer |
| G3 | Slice gate | anywhere | written |
| S4 | Print | the Ender 3 V3 SE | not started |

## Driving a job

```bash
uv sync
uv run python -m r2p init chain-chomp
uv run python -m r2p status chain-chomp
```

`status` prints the one next command. Run it, then run `status` again. After two failed attempts at a gate the driver stops and writes `escalate.md`.

## Layout

- `contracts/`: JSON schemas for every file that passes between stages.
- `printer/`: printer profiles, each value marked verified or unverified.
- `checks/`: mesh, fit and mate checks. Exit 0 pass, 1 fail, 2 bad input.
- `slicer/`: slicer wrapper and profiles.
- `r2p/`: the driver.
- `maya/`, `fusion/`, `skills/`, `dsh/`: empty until the Mac-side work starts.
- `jobs/<job>/`: one folder per job. Reference images and generated geometry are not committed.

## Rules

- Units are millimetres.
- Maya makes form only. Hinges, pins, sockets and clearances are built in the print-prep stage from locators in `form.manifest.json`.
- No paid API is called by anything here.
- This folder imports no code from other repos.

## Tests

```bash
uv run pytest -q
```
