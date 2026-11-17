# Slicer profiles

No printer profile is stored here yet.

The shop slices with PrusaSlicer 2.9.4 and OrcaSlicer 2.4.2. This comes from
another repo's docs and was checked on 2026-11-16.

To add one: export a profile from either slicer for the Creality Ender 3 V3 SE
(0.4 mm nozzle, PLA, 220 x 220 x 250 mm build volume), save it in this folder,
and pass it to the checker:

    python -m slicer.slice_check --job-dir jobs/NAME --profile slicer/profiles/FILE

The shop's required start and end G-code macros are documented in the separate
`metaware` repo at `docs/slicer-conventions.md`. Read that file and follow it
when you build the profile. Do not copy code from it.

The slicer command lines in `slicer/slice_check.py` (function `build_command`)
are unverified. No slicer was installed when they were written (2026-11-16).
They need a test run against a real PrusaSlicer or OrcaSlicer before you rely
on them. `R2P_SLICER_CMD` can override them without editing code.
