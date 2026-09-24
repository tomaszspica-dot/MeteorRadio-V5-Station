# Reference changes relative to the upstream-style station

The V5 reference build includes station-specific changes and additions around the upstream acquisition core, notably:

- `ADAPTIVE_CAPTURE_V2`
- enlarged rolling buffer for adaptive pre/post context
- trigger metadata stored with SMP detections
- custom rendering/cache pipeline
- local scoring 1–7
- score-based retention
- favourites and manual delete
- local web dashboards
- health monitoring
- optional radio-owner arbitration

The exact modified upstream file is not published in this public tree by the current packaging policy. Upstream licensing is now confirmed as GPLv3, so a compliant source copy or patch may be prepared after its base commit, retained notices and modification information are verified. The behavior is documented in `docs/ADAPTIVE_CAPTURE_V2.md`.
