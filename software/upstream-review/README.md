# Upstream review candidate — adaptive capture

Temporary GPLv3 review candidate based on current `rabssm/MeteorRadio/src/meteor_radar.py`.

- Upstream source blob: `b4dffd162db3a1a8fb61c66bbfae5de7ae1734a4`
- Prepared: 2026-09-24
- Existing MeteorRadio capture behaviour remains the default.
- Enable the new path with `--adaptivecapture`.
- Adaptive parameters: PRE 3.0 s, minimum POST 0.8 s, quiet/hang 1.0 s,
  maximum POST 10.0 s.
- SMP output receives trigger time, adaptive flag, pre/post duration and stop reason.
- The larger rolling buffer is used only with adaptive capture.

The V5 station's V3 multi-tier/rollover logic is deliberately excluded from
this first upstream candidate so the maintainer can review the adaptive-capture
foundation separately.

This directory is temporary review material and should not be merged into the
V5 station-layer main branch as a vendored upstream core.
