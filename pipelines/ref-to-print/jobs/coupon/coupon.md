# Clearance coupon (coupon)

## How to print
- Print `coupon_plate` and `coupon_peg` flat on the bed, with no supports.
- Use the same material and settings as the real parts (PLA, 0.4 mm nozzle).

## How to test
1. Start at the chamfered corner: that end holds the smallest hole.
2. Try the peg in each hole in turn, from hole 1 towards the last hole.
3. Pick the smallest gap where the peg drops in and turns freely by hand.

Count the dimples on the plate edge to read the hole number (hole 1 has one dimple, hole 2 has two, and so on).

## Holes
| Hole | Dimples | Gap (mm) | Hole diameter (mm) |
|---|---|---|---|
| 1 | 1 | 0.10 | 8.20 |
| 2 | 2 | 0.15 | 8.30 |
| 3 | 3 | 0.20 | 8.40 |
| 4 | 4 | 0.25 | 8.50 |
| 5 | 5 | 0.30 | 8.60 |
| 6 | 6 | 0.40 | 8.80 |
| 7 | 7 | 0.50 | 9.00 |

## After the test
Run this with the smallest gap that fitted (replace VALUE):

    python -m r2p set JOB clearance_mm=VALUE

JOB is the job whose joints should use this gap, for example chain-chomp.
