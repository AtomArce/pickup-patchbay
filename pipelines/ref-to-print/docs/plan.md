# Plan: reference images to a printable 3D object (ref-to-print)

Written 2026-11-16 on `ciara-ai`. Nothing here is built. Every fact is labelled **V** (verified today, by reading files or a cited source) or **U** (unverified).

## Context

Atom wants a skeleton pipeline that takes reference images to print-ready parts: model the form in Maya through an MCP server, prepare it for printing in Fusion 360, prototype with Claude Fable as the agent, then move what works into dsh skills and tools so a local model can run it. A Meshy comparison is an option for later.

The work lives in `~/dev/pickup-patchbay` (V: exists on ciara, remote `AtomArce/pickup-patchbay`, currently only `README.md` and `index.html`). The brief's line that the repo does not exist on ciara is wrong; it checked a misspelt path.

## Atom's answers (2026-11-16)

| Question | Answer |
|---|---|
| Fusion 360 machine and licence | Not installed yet. Install and licence become a Step 0 task for Atom. |
| First test case | A functioning Chain Chomp with all the pieces. |
| Modelling share | The agent models from images alone; Atom reviews. |
| Code home | Pipeline, contracts, checks and skills in `pickup-patchbay`. Maya and Fusion servers are called as external MCP tools. No hub Python is imported. |

## Assumptions to confirm at approval

1. "Functioning" means: the jaw opens on a hinge, the chain links move freely, and the chain anchors to the body and to a stake. Pieces: upper body, lower jaw, hinge pin, teeth, two eyes, chain links, stake.
2. Body is about 100 mm across (fits the 220 x 220 x 250 mm bed in one piece per half).
3. Single-colour PLA, so colour comes from separate parts: black body, white teeth and eyes, grey chain.
4. The Chain Chomp is larger than the brief's "one small object", so Phase 1 runs it as three milestones, smallest first (below).
5. This is a personal prop. If it is ever sold, two things change: Fusion's Personal licence is non-commercial only (V, Autodesk FAQ), and the character is Nintendo's.

## Findings that shape the plan

| Fact | Label | Source |
|---|---|---|
| Printer: Creality Ender 3 V3 SE on Klipper, 220 x 220 x 250 mm, 0.4 mm nozzle, PLA | V | `metaware/docs/printers/`, `metaware/fixtures/*.gcode` |
| Slicers in use: PrusaSlicer 2.9.4, OrcaSlicer 2.4.2 | V | `metaware/docs/PRD.md:63` |
| No joint clearance or minimum wall rule is recorded; flow and pressure advance are not calibrated | V | `metaware/docs/printers/printer-a-ender3-v3se/build-checklist.md` |
| `metaware` holds no meshes, CAD files or reference images | V | repo search |
| Maya 2027 is on minimott (M4 Pro, 24 GB, macOS 15.7.7); licence is education or trial; its terms on automation have not been read | V (file) | `ai-vfx-lab/hardware/mac-mini.md`, `docs/research/flow-access.md` |
| Hub picked `abrahamADSK/maya-mcp` (commandPort `localhost:8100`), not installed, trial card HUB-008 blocked on Atom | V (file) | `ai-vfx-lab/docs/research/flow-access.md` |
| `GimbalGoats/GG_MayaMCP`: 71 typed tools, viewport capture, raw execution opt-in, localhost only | V (source) | project docs |
| GG_MayaMCP on macOS with Maya 2027 | U | not stated |
| Maya commandPort must not be forwarded over Tailscale; tailnet lets ciara reach only `minimott:22,11435` | V (file) | `ai-vfx-lab/hardware/tailscale-policy.hujson` |
| Fusion has Windows and macOS builds only; runs on Apple Silicon; needs macOS 15.3.1 or newer | V (source) | Autodesk system requirements |
| Official Autodesk Fusion MCP server: local, `http://127.0.0.1:27182/mcp`, needs Fusion and a document open | V (source) | Autodesk help |
| Official Fusion MCP works on the Personal licence; its tool list | U | |
| Personal licence allows API, scripts, add-ins, STEP and STL export; 10 active documents | V (source) | Autodesk FAQ |
| Personal licence gets Faceted mesh conversion only | U | forum posts |
| Fusion has no supported headless mode | V (source) | Autodesk forum |
| Insert Mesh accepts STL, OBJ, 3MF (not FBX or USD) | V (source) | Autodesk help |
| Fusion can plane-cut and combine mesh bodies without conversion | V (source) | Autodesk help |
| dsh supports MCP servers on paper; none has run live; tool calls time out at 60 s | V (file) | `ai-vfx-lab/docs/research/dsh-mcp-check.md` |
| ciara's dsh containers have no network; DCC work goes through a dsh Host on the mini (ADR-0020) | V (file) | hub ADRs |
| Local model (Flash-Next) takes images, about 18 of 20 valid tool calls; MCP routing reliability unmeasured | V (file) | ADR-0010 |
| Meshy API needs a paid plan (Pro US$20 a month); image-to-3D costs 20 to 30 credits | V (source) | docs.meshy.ai |
| Hunyuan3D 2.1 shape-only needs about 10 GB VRAM | V (source) | model README |

## Stages and file contracts

All job files live in `pipelines/ref-to-print/jobs/<job>/`. Units are millimetres everywhere; the up axis is recorded in each manifest.

| Stage | Tool and machine | Input | Output (the contract) | Gate |
|---|---|---|---|---|
| S0 Brief | Atom | reference images | `refs/*.png` (gitignored), `brief.json`: target size, printer profile, parts list, what must move | brief validates against schema |
| S1 Form | Maya 2027 via MCP, minimott | `brief.json`, refs | `form.ma`, one `form/<part>.obj` per part, `form.manifest.json` (units, up axis, bounding boxes, triangle counts, locators for hinge axis, split planes and chain anchor), `views/*.png` turntable | G1 |
| S2 Print prep | Fusion 360 via MCP or API scripts, minimott | S1 outputs | `parts/<part>.step`, `parts/<part>.stl`, `assembly.f3d`, `parts.manifest.json` (per part: bounding box, volume, print orientation, clearance used, mates) | G2 |
| S3 Slice | OrcaSlicer CLI, ciara or minimott | `parts/*.stl`, printer profile | `sliced/*.3mf` or `.gcode`, `slice.report.json` (time, filament, errors) | G3 |
| S4 Print | Atom, Ender 3 V3 SE | sliced files | printed parts, `fit.notes.md` | parts mate and move |

OBJ is the S1 to S2 file because Fusion's Insert Mesh takes it and it keeps part names. STEP is the S2 master; STL goes to the slicer. USD is not on the path (Fusion cannot insert it).

**Rule that splits the work:** Maya makes form only. Functional geometry (hinge, pin, sockets, chain link clearances, split faces) is built in Fusion from the locators in `form.manifest.json`. Joints are never modelled as polygons.

### The weak point: mesh to solid

Faceted conversion makes one solid face per triangle, so solids are heavy and booleans on them are slow and fragile. Mitigations, in order:

1. **Rebuild, don't convert, for simple shapes.** The body is a sphere and the links are tori. Fusion builds these natively from manifest dimensions; the mesh is used only as a visual check.
2. **Stay on the mesh** for cuts that need no precision (Plane Cut, Combine).
3. **Convert only low-triangle organic parts** (teeth, eyes), with a triangle cap set in Step 0 by trial.
4. **Linux fallback** if Fusion is late or the licence blocks a step: `manifold3d` and `trimesh` for splits and peg-and-socket booleans, `build123d` for parametric joints with STEP out. This also unblocks Lane A before Fusion is installed.

### Gates

- **G1 (form):** each part watertight and manifold; bounding box within 2% of the brief; triangle count under the cap; turntable views compared with refs by the agent, then by Atom.
- **G2 (parts):** each part watertight; minimum wall at least 1.2 mm (U, default until measured); each part fits 220 x 220 x 250 mm with a margin; assembled parts do not intersect; the smallest gap at every joint is at least the measured clearance; the jaw sweeps its range and each link passes its neighbour with no collision (sampled poses).
- **G3 (slice):** slices with no error, nothing off the plate, time and filament reported. Start and end macros follow `metaware/docs/slicer-conventions.md` (read as a reference; nothing is imported).

## Tooling choices

**Maya (S1).** Try `GG_MayaMCP` first: it has viewport capture, which image-driven modelling needs, and typed tools. It differs from the hub's pick, so Step 0 tests both against three requirements: runs on macOS with Maya 2027, runs Python, returns a viewport image. Whichever passes is used; the result is written up for the hub, not edited into it. Fallback with no MCP: `mayapy` scripts plus playblast images, which is also what the `dcc-dev` preset already targets.

**Fusion (S2).** Official Autodesk Fusion MCP first. If it is missing tools or blocked on the licence, use Fusion API Python scripts run from the Scripts panel, or the `faust-machines/fusion360-mcp-server` add-in (has `execute_code` and `render_view`; its socket has no authentication, so localhost only).

**Where the Phase 1 agent runs.** Claude Code with Fable on minimott, in a clone of this repo. Both MCP servers bind to localhost on the mini, and the hub forbids forwarding the Maya port. Fable is a cloud model, so ADR-0003 (no local model while Maya is open) holds. Checks are plain Python and run on either machine.

**Needs from Atom before Lane B and C start:** Fusion installed on minimott with a licence chosen; an OK to install a Maya MCP server on the mini (no `install.sh`; manual venv); a read of the Maya licence terms on automation; Claude Code available on the mini (U).

## Phase 1: prototype (Fable as agent)

Three milestones, each a full pass S0 to S4 with every gate:

1. **M1 Chain: two links.** Smallest possible job. Proves the whole path and the clearance value.
2. **M2 Head:** upper body, lower jaw, hinge and pin, teeth, eyes.
3. **M3 Whole:** head, full chain, anchor on the body, stake.

Before M1's joints are final, Atom prints a **clearance coupon** (gaps from 0.1 to 0.5 mm) and records which gap moves freely in `printer/ender3-v3se.json`. Until then the default is 0.3 mm (U).

Every run writes a log (`jobs/<job>/run.log.md`): what the agent did at each stage, which gate failed, how it was fixed. That log is the raw material for Phase 2.

### Built so dsh can drive the follow-up runs

Fable drives the first pass only (M1). Everything is shaped from day one so dsh can drive what follows: M1 replays, M2 and M3 print prep, re-runs after a failed print, and later objects.

- **One driver CLI, `r2p`.** `r2p status <job>` reads `jobs/<job>/job.state.json` and prints the current stage, the last gate result and the single next command. `r2p run <job> <stage>` runs one stage script; `r2p gate <job> <G1|G2|G3>` runs the checks and writes `check.report.json`. A driver never has to decide what comes next; it reads it.
- **Resumable state.** `job.state.json` records each stage as pending, done or failed, with the parameters used (clearance, wall, split planes, orientation). A run can stop and resume in another session or under another driver.
- **Stages are scripts with parameters, not improvisation.** Whatever Fable works out in M1 for S2 and S3 is saved as a script that takes numbers from the manifests. A follow-up run changes parameters, not code.
- **Small steps.** Each `r2p` call finishes well inside dsh's 60 s MCP tool timeout; long Fusion or slicer work runs as a background job that `r2p status` polls.
- **Escalation rule in the state file.** After two failed attempts at the same gate, or any step marked `needs: modelling`, the driver stops and writes `escalate.md` for Fable or Atom. dsh does not retry forever.
- **Skills are written during Phase 1**, as `SKILL.md` files Fable itself follows, so the same text is what dsh loads later.

**Hand-over test at the end of M1:** dsh replays M1's S2, S3 and gates from a clean job folder, using only `r2p` and the skills. If it passes, dsh drives S2 onward for M2 and M3, and Fable is called only for S1 form work and escalations. If it fails, the failure is logged and Fable keeps driving while the scripts are tightened.

## Phase 2: local (dsh)

Phase 2 is the wiring, not a rewrite: the driver CLI, state file and skills already exist from Phase 1. dsh wiring starts once the dsh prod promotion is finished and Atom says so, and it is done in a dsh session, not from this repo.

**Which dsh drives:** the dsh Host on minimott (ADR-0020), because Maya, Fusion and the job folder are there and ciara's dsh containers have no network. Its brain is Flash-Next on ciara through the existing SSH tunnel. ADR-0001 applies: one GPU user at a time, so pipeline runs queue behind other work.

**What this repo hands to the dsh session** (`pipelines/ref-to-print/dsh/`, proposals only, never applied from here):

- `preset-print-prep.patch.yml`: a draft preset in dsh's patch format, starting from `dcc-dev`'s plugin list, adding the skill folder through `customSkillDirs` (U) and `dsh-mcp-client` rows for `print-checks`, Maya and Fusion. It replaces the `print-help` stub named in `guest-dcc-dev.patch.yml`.
- `AGENTS.md`: workspace rules for the preset: use `r2p status` first, one stage per turn, stop on `escalate.md`.
- `handover.md`: what was verified in Phase 1 and what dsh must check live (no MCP server has ever run in dsh).

**Follow-up runs dsh is expected to drive:** replay of a finished job; print prep and slicing for a new form mesh; a re-run with a new clearance or wall value after a failed print; a nightly or queued batch through dsh's job plugins (left out of `dcc-dev` today, so the draft preset adds them back; U whether that is wanted).

| Becomes | What | Where |
|---|---|---|
| Skills (`SKILL.md`, agentskills format) | `ref-to-print` (orchestrates stages and gates), `maya-form-model`, `fusion-print-prep`, `print-checks` | `pipelines/ref-to-print/skills/`, linked into dsh through `customSkillDirs` (U) |
| Tools | the check and slice scripts as a CLI first, then one small stdio MCP server `print-checks` with under 10 tools | `pipelines/ref-to-print/checks/` |
| External servers | Maya and Fusion MCP, run under the mini's dsh Host with ciara's model as the brain (ADR-0020) | not in this repo |

What to expect from the local model:

- **Can:** run a fixed stage from a skill, call typed tools with parameters, read a gate report and adjust a number, re-run scripts Fable wrote in Phase 1.
- **Cannot be relied on to:** model a form from images, judge likeness, or finish a long multi-stage run without a bad tool call. The 60 s MCP timeout also rules out long Fusion operations in one call.
- **So:** the local model runs S2 to S3 from parameterised scripts and all the gates. S1 stays with Fable, Atom, or an image-to-3D tool.
- **Measure:** replay each Phase 1 stage with the local model and count failed turns; the hub's gate is a ratio of 0.25 or less. ADR-0001 applies: one GPU user at a time, so these runs queue.

## Phase 3: optional image-to-3D comparison

No money is spent without Atom's say.

- **Free first:** Hunyuan3D 2.1 shape-only on ciara (about 10 GB VRAM). Needs the GPU in `vfx` mode, so it needs Atom's OK to stop the engine. Weights are never committed.
- **Meshy:** the API needs a paid plan, Pro at US$20 a month. One multi-image generation is 20 to 30 credits; printability analysis is free; repair and auto split are 10 credits each. Credits included per month and the price per credit are U. One month should cover the test (U).
- **Where it plugs in:** it replaces S1 only and must deliver the same contract (`form/<part>.obj` plus manifest). It cannot produce working joints, so S2 onwards is identical.
- **What is compared, on the M2 head:** whether G1 passes first time, repair steps needed, triangle count, Atom's blind ranking of likeness, time to a G1 pass, and how much S2 work remains.

## Lanes

**Step 0, serial (shared contracts; everything else depends on them):**

1. Save the brief as `pipelines/ref-to-print/docs/plan-brief.md` (the only copy is in another session's scratchpad) and this plan beside it.
2. Create the layout below, `.gitignore` for `refs/`, meshes, weights and `.env`.
3. Write the JSON schemas: `brief`, `form.manifest`, `parts.manifest`, `check.report`, `slice.report`; and `printer/ender3-v3se.json`.
4. Write `jobs/chain-chomp/brief.json` with Atom.
5. Atom: install Fusion, choose the licence, give the Maya MCP OK.

**Then in parallel, as small subagent tasks.** Each task owns one or two files, has one shell check, and should take under about 30 minutes. Fable writes the contracts, reviews every diff and does the form modelling; the tasks themselves go to smaller models. (I read "smaller subagents" as both smaller scope and smaller models; say if you meant only one.)

| Task | Owns | Model | Check | Machine |
|---|---|---|---|---|
| A1 mesh check | `checks/mesh_check.py`, its test | Haiku | `pytest tests/test_mesh_check.py` | ciara, worktree |
| A2 fit check | `checks/fit_check.py`, its test | Haiku | `pytest tests/test_fit_check.py` | ciara, worktree |
| A3 mate and sweep check | `checks/mate_check.py`, its test | Sonnet | `pytest tests/test_mate_check.py` | ciara, worktree |
| A4 slice check | `slicer/slice_check.py`, `slicer/profiles/` | Sonnet | slices a test cube | ciara, worktree |
| A5 driver CLI and state | `r2p/`, its test | Sonnet | `pytest tests/test_r2p.py` | ciara, worktree |
| B1 Maya MCP spike | `maya/SPIKE.md` | Sonnet | sphere made, image returned | minimott |
| B2 form export | `maya/export_form.py` | Haiku | exported OBJ passes A1 | minimott |
| B3 turntable | `maya/turntable.py` | Haiku | four PNGs written | minimott |
| C1 Fusion spike | `fusion/SPIKE.md` | Sonnet | OBJ in, STEP out | minimott |
| C2 insert and convert | `fusion/insert_convert.py` | Sonnet | solid body count matches | minimott |
| C3 split | `fusion/split.py` | Sonnet | parts pass A2 | minimott |
| C4 joints | `fusion/joints.py` | Fable | parts pass A3 | minimott |
| C5 export | `fusion/export_parts.py` | Haiku | manifest validates | minimott |
| D1 to D4 skills | one `skills/<name>/SKILL.md` each | Haiku | frontmatter lint | ciara, after M1's log exists |
| D5 dsh hand-over pack | `dsh/` | Sonnet | YAML parses | ciara, after M1 |

- A1 to A5 are independent of each other and of Maya and Fusion (they test on synthetic meshes), so up to five run at once on ciara, each in its own worktree.
- B and C tasks run on minimott, so they are subagents of a Claude Code session there, not of a ciara session. B and C do not share files; C develops against the A tasks' synthetic meshes, not B's output.
- Within B and within C the tasks are serial (spike first, then scripts in stage order). Running Maya and Fusion together in 24 GB is U; if it is tight, B and C alternate.
- The local Qwen worker (`delegate-ciara`) is not used: the hub records 3 of 10 worker cards as wrong and the skill is being retired.

**Must stay serial, and why:**

- Step 0, because all lanes read the schemas.
- The clearance coupon before final joints, because the joint gap is a measured input.
- M1, then M2, then M3, because each stage consumes the previous stage's files and each milestone reuses the last one's fixes.
- The dsh hand-over test after M1, because it replays M1's saved scripts and state.
- dsh wiring after the prod promotion, because `~/dev/dsh` is read-only until then.
- Phase 3 after G1 exists, because G1 is the yardstick.

## Files to create (all under `pipelines/ref-to-print/`)

```
docs/plan-brief.md, docs/plan.md
contracts/*.schema.json
printer/ender3-v3se.json
r2p/                                             # driver CLI: status, run, gate; job.state.json
dsh/{preset-print-prep.patch.yml,AGENTS.md,handover.md}   # proposals for the dsh session
checks/{mesh_check,fit_check,mate_check}.py     # CLI, trimesh + manifold3d
slicer/slice_check.py, slicer/profiles/
maya/{export_form,turntable}.py
fusion/{insert_convert,split,joints,export_parts}.py
skills/<name>/SKILL.md                           # Phase 2
tests/
jobs/chain-chomp/brief.json
```

The existing `README.md` and `index.html` (the GitHub Pages site) are not touched, beyond one README line pointing at the pipeline.

## Verification

- **Lane A:** `pytest` on synthetic meshes: a closed cube passes, an open one fails watertight, an oversize box fails fit, two overlapping parts fail mate, a thin shell fails wall.
- **Maya spike:** the agent creates a sphere through MCP, gets a viewport image back, exports an OBJ that passes `mesh_check`.
- **Fusion spike:** insert that OBJ, build a native sphere from the manifest, split it, export STEP and STL, both pass `fit_check`.
- **M1 end to end:** two links pass G1 to G3, print, and move freely by hand.
- **dsh hand-over:** from a clean job folder, dsh replays M1's S2, S3 and gates with only `r2p` and the skills; failed-turn ratio 0.25 or less.
- **M3 end to end:** the jaw opens, the chain swings, every part printed within the bed.

## Constraints carried over

- `~/dev/dsh`, `~/dsh-home`, `~/dev/metaware` and `~/dev/ai-vfx-lab` are read-only for this work.
- No docker build, up or restart and no engine start or stop on ciara without Atom's say.
- No paid API or cloud spend without asking. No secrets, weights or `.env` files in git. No employer code or data.
- Repos never import each other's Python.

## Still open

- Fusion licence (Personal, paid or education) and whether the official MCP works on it.
- Which Maya MCP passes the Step 0 spike.
- Whether Atom has the Chain Chomp reference images, and the final size.
- Whether OrcaSlicer's CLI is installed on ciara or the mini.
