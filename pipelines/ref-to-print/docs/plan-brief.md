# Plan brief: reference images to a printable 3D object

Status: a brief for a planning session, written 2026-11-16. Nothing here is built or verified yet.
Home for the work: `dev/pick-packbay` (Atom's choice). Reference only: `~/dev/metaware` (printer details and the
Mario cosplay objects already made), `~/dev/dsh` (how skills, plugins and presets load), `~/dev/ai-vfx-lab` (hub:
hardware, ADRs, roadmap).

## How to use this file
Open a Claude Code session in `dev/pick-packbay`, in plan mode, and paste:

> Read `ref-to-print-plan-brief.md` and produce the plan it asks for. Stay in plan mode; ask me the open questions
> first, few and short, with choices.

## Goal
A skeleton pipeline that goes from reference images to a 3D object ready for printing:
1. Develop the asset in Maya, driven through a Maya MCP.
2. Move it to Fusion 360 to prepare it for printing: solids, tolerances, splitting into sub pieces where needed,
   linkages and joints.
3. Prototype with a high-level model (Claude Fable) driving the whole pipeline as an agent.
4. Then turn it into a skill or plugin for dsh (maybe a series of skills and tools) so it runs locally.
5. Later, nice to have: A/B test against an image-to-3D tool such as Meshy. It may help or may not be needed.
   Paid API: plan it as an option only.

## Read first (read-only)
- `~/dev/metaware`: `CLAUDE.md`, `README.md`, `docs/`. Record the printer model, build volume, materials, and how
  the existing objects were made, split and joined. Pick one existing object as the first test case if one fits.
- `~/dev/dsh`: `CLAUDE.md`, `docs/guest-access.md`, `services/dsh/home/guest-dcc-dev.patch.yml`,
  `scripts/dsh_preset.py`, `services/dsh/home/`. The `dcc-dev` preset (Maya/mayapy plus USD) names 3D printing as
  a later feature; this pipeline is the start of it.
- `~/dev/ai-vfx-lab`: `docs/handoff.md`, `tasks/plan-of-plans.md`, `hardware/`.

## What the plan must cover
1. **Stages and contracts.** Reference images -> blockout and model in Maya (MCP) -> export -> Fusion 360 (solids,
   tolerances, split to the build volume, joints and linkages, print orientation) -> slicer-ready output. Name the
   file that passes between stages (for example OBJ/FBX/USD -> STEP/3MF/STL) and say where mesh-to-solid
   conversion is the weak point.
2. **Tooling that really exists.** Which Maya MCP, and which Fusion 360 automation route (Fusion API add-in, an MCP
   server, or scripts). What each needs and which machine runs it.
3. **Phase 1, prototype.** Fable as the agent, one small object, a check at every stage: watertight mesh, wall
   thickness, fits the build volume, parts mate.
4. **Phase 2, local.** What becomes a dsh skill, what becomes a tool or plugin, and what a local model can and
   cannot be expected to do here.
5. **Phase 3, optional.** The Meshy A/B: cost, and what would be compared.
6. **Parallel lanes.** Where two or more parts are independent, split them into lanes with disjoint file
   ownership, put shared contracts in a serial Step 0, and name what must stay serial and why. Otherwise say
   briefly why the plan stays serial.

## Facts and constraints (unverified unless marked)
- `ciara`: Linux workstation, one 24 GB GPU, one GPU user at a time (ADR-0001); runs the local engine and dsh.
- `minimott`: Mac mini; Maya runs there; no local model while Maya is open (ADR-0003).
- Fusion 360 has no Linux build, so it would run on the Mac or another machine. Check this.
- `dev/pick-packbay` does not exist on ciara (**verified** 2026-11-16, `ls ~/dev/pick-packbay`). It is on another
  machine or still to be created.
- Ask a clarifying question when unclear; do not guess. Label every fact verified or unverified.
- Never commit secrets, model weights or `.env` files. Never reuse employer code or data.
- Do not spend money (cloud, Meshy or other paid APIs) without asking.
- No docker build/up/restart and no engine start/stop on ciara without Atom's say. Treat `~/dev/dsh` and
  `~/dsh-home` as read-only: another session is mid prod promotion there.
- Repos never import each other's Python.

## Open questions for Atom
- Where does `dev/pick-packbay` live (which machine), and is it a new repo?
- Which object is the first test case?
- Which machine runs Fusion 360, and is there a licence that allows the API/add-ins?
- How much of the modelling should the agent do from images alone, versus refining a blockout you start?

## Done looks like
A written plan Atom can approve: stages, file contracts, tooling choices with evidence, the three phases, lanes,
and the open questions answered or listed.
