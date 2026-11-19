# ref-to-print

Reference images to 3D-printable parts. A skeleton, started 2026-11-16. The plan is in [docs/plan.md](docs/plan.md); the brief it answers is in [docs/plan-brief.md](docs/plan-brief.md).

## Stages

| Step | What | Where it runs | Status |
|---|---|---|---|
| S0 | Brief: `jobs/<job>/brief.json` plus reference images | anywhere | contract written |
| S1 | Form model in Maya, through an MCP server | minimott | not started. Code-built jobs use `gen.build --stage form` in its place |
| G1 | Form gate: watertight, triangle cap | anywhere | working |
| S2 | Print prep: solids, splits, joints | anywhere (code route) or minimott (Fusion route) | code route working; Fusion route not started |
| G2 | Parts gate: wall, fits the bed, parts mate and move | anywhere | working |
| S3 | Slice | where a slicer is installed | wrapper written, never run against a real slicer |
| G3 | Slice gate | anywhere | written |
| S4 | Print | the Ender 3 V3 SE | not started. Nothing here has been printed |

## Two routes to parts

- **Code route (working):** `gen/` builds parts directly with booleans, no CAD program. It covers shapes that are simple to describe: the chain, the stake, and a ball head with a hinged jaw, teeth and eyes. It is not modelled from reference images.
- **Maya and Fusion route (planned):** an agent models the form from images in Maya, and Fusion adds the joints. See [docs/plan.md](docs/plan.md).

Both routes write the same `parts.manifest.json`, so the gates, the renderer and the slicer stage do not care which one made the parts.

## Jobs in this repo

| Job | What | State |
|---|---|---|
| `coupon` | Clearance test: seven holes from 0.10 to 0.50 mm gap and one peg. Print it, then set the measured gap with `r2p set` | generated, checks pass, not printed |
| `chain-m1` | Milestone M1: two chain links, printed in place | passes G1 and G2 |
| `chain-chomp` | Head (second pass, from a side-view reference): Pac-Man jaw pivoting on pins at the sides of the ball, red mouth plates, two rows of interleaved teeth, domed eyes with pupils; six links, stake | passes G1 and G2. The chain is not yet hooked to the head or the stake |

Rebuild any of them (geometry is not committed):

```bash
uv run python -m gen.coupon --job-dir jobs/coupon
uv run python -m r2p run chain-chomp S2      # or: uv run python -m gen.build --job-dir jobs/chain-chomp
uv run python -m viz.render --job-dir jobs/chain-chomp
uv run python -m viz.render --job-dir jobs/chain-chomp --pose jaw_hinge=40 --out-dir jobs/chain-chomp/views/open
```

## View a job

A browser viewer (three.js, no build step, the same pattern as morph-hanger's viewer; no code is shared):

```bash
uv run python -m viewer.serve            # loopback only; prints the URL and an ssh -L line
uv run python -m viewer.serve --tailnet  # also tailscale serve on 8445; Ctrl-C removes only that entry
```

`--tailnet` needs this user to be the tailscale operator (`sudo tailscale set --operator=$USER`, once); until then tailscale refuses the serve config and the SSH tunnel is the way in. It refuses to start if 8445 is already served (for example by `hanger up`). It never uses funnel and never touches another port. The viewer is read-only: nothing in it writes files or runs a stage. Geometry is gitignored, so build it first (`uv run python -m r2p run JOB S2`).

The PNG renderer in `viz/` stays for headless use and for the driver skill.

### Server contract (shared by `viewer/serve.py` and `web/r2p-viewer/`)

Bound to 127.0.0.1 only. GET and HEAD only; anything else is 405. Requests whose `Host` is not loopback or the tailnet name get 403. A path that is not listed, or that resolves outside its folder, is 404.

| Path | What |
|---|---|
| `/` | redirect (302) to `/web/r2p-viewer/` |
| `/web/r2p-viewer/<file>` | the page: `.html`, `.mjs`, `.css`, `.json` |
| `/printer/<name>.json` | printer profiles |
| `/jobs/<job>/<file>.json` | `parts.manifest.json`, `job.state.json`, `brief.json`, `form.manifest.json` |
| `/jobs/<job>/reports/<file>.json` | check and slice reports |
| `/jobs/<job>/parts/<part>.stl` | part meshes (`model/stl`) |
| `/jobs/<job>/views/<...>.png` | renderer output |
| `/api/jobs` | JSON list, below |

`/api/jobs` returns jobs (folders under `jobs/`) that have a `parts.manifest.json`, sorted by name:

```json
{"jobs": [{"job": "chain-chomp", "parts": 14, "printer": "ender3-v3se",
           "next": "S3", "gates": {"G1": "done", "G2": "done", "G3": "pending"},
           "reports": ["reports/G1.check.report.json", "reports/G2.check.report.json"]}]}
```

`next` is the first step in `job.state.json` that is not `done` (null when all are done or there is no state file), `gates` the status of G1 to G3 (`"pending"` when absent), `reports` every `reports/*.json` path relative to the job folder. `printer` is the brief's printer id, or null.

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
- `gen/`: code-built parts (coupon, chain, head) and `gen.build`, the code route for stage S2.
- `viz/`: a software renderer (PNG views, posed hinges) and a silhouette score against a reference image.
- `skills/ref-to-print/`: the skill a local model follows to drive a job with `r2p`.
- `maya/`, `fusion/`, `dsh/`: empty until the Mac-side work starts.
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
