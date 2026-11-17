---
name: ref-to-print
description: Drive a ref-to-print job (reference images to 3D-printable parts) one step at a time with the r2p command. Use when asked to run, resume, re-run or check a print-prep job, or to change a clearance or wall value and rebuild.
---

# Driving a ref-to-print job

You do not decide what comes next. The `r2p` command does. Your loop is:

1. Run `python -m r2p status JOB`.
2. Read the line that starts with `NEXT:`.
3. If it is a command, run exactly that command. If it is a sentence, do what it says or stop and tell the person.
4. Go back to 1.

Run everything from the `pipelines/ref-to-print` folder, with `uv run` in front (`uv run python -m r2p status JOB`).

## Rules

- One step per turn. After each command, run `status` again before doing anything else.
- Never edit `job.state.json`, a manifest or a report by hand.
- Never mark a gate as passed. Gates (G1, G2, G3) can only pass by running `r2p gate`.
- If `status` exits with code 3 or prints `STOPPED`, stop. Read `jobs/JOB/escalate.md`, summarise it for the person, and do nothing else. Only a person runs `r2p resume`.
- Steps that say they need a modelling agent or a person are not yours. Say so and stop.
- Do not install anything, call any paid service, or use the network.

## When a gate fails

`r2p gate` prints one line per failed rule. Each line names a part, a rule and a number against its limit.

| Failed rule | What it means | What you may try, once |
|---|---|---|
| `mate.min_gap` | parts are closer than the clearance | nothing: report it. The geometry needs a design change |
| `mate.no_intersection` or `mate.sweep_clear` | parts overlap, or collide when moving | nothing: report it |
| `mesh.min_wall` | a wall is thinner than the limit | nothing: report it |
| `fit.fits_build_volume` | a part is too big for the bed | nothing: report it |
| `mesh.watertight` | a mesh has holes | re-run the stage that made it (`r2p run JOB S2`), then the gate |

You get two attempts at a gate. After the second failure the job stops by itself.

## Changing a number and rebuilding

When the person gives a new clearance (for example after printing the clearance coupon):

```
uv run python -m r2p set JOB clearance_mm=0.25
uv run python -m r2p status JOB
```

`set` sends the job back to print prep (S2). Follow `NEXT:` from there.

## Looking at the result

```
uv run python -m viz.render --job-dir jobs/JOB
uv run python -m viz.render --job-dir jobs/JOB --pose jaw_hinge=40 --out-dir jobs/JOB/views/open
```

This writes PNG pictures of the parts to `jobs/JOB/views/`. Show them to the person. Do not judge likeness yourself.

## What to report at the end of a turn

The step you ran, whether it passed, the failed rules if any (part, rule, value, limit), and the `NEXT:` line.
