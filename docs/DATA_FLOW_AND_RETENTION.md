# Detection data flow and retention

## Detection lifecycle

1. MeteorRadio detects a candidate event around 143.050 MHz.
2. The adaptive capture window saves the raw I/Q detection as an SMP `.npz` file.
3. The image renderer creates a cached visual representation.
4. The scoring worker assigns a local score from 1 to 7.
5. The retention state tracks the detection.
6. A user may like the detection or delete it manually.
7. Unliked detections expire according to score.

## Reference retention policy

| Score | Unliked retention |
|---:|---:|
| 1 | 1 day |
| 2 | 2 days |
| 3 | 3 days |
| 4 | 4 days |
| 5 | 5 days |
| 6 | 6 days |
| 7 | 7 days |

Liked detections are kept indefinitely until manual deletion.

## Manual deletion

The 8096 interface can delete a detection immediately. The reference workflow removes the SMP and corresponding cache/state entries so stale index records are not intentionally retained.

## What is excluded from GitHub

Runtime observation data is not source code. This repository therefore ignores:

- SMP files
- raw audio
- generated detection PNGs
- live likes/score/retention state
- health history

Curated example data should be published separately and intentionally, with its own privacy review.
