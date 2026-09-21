# MeteorRadio station overlay V5 — reference release

This release documents the verified V5 reference station for GRAVES meteor-scatter reception at 143.050 MHz.

## Highlights

- Adaptive Capture V2 with 3.0 s pre-trigger context and dynamic fade-based stop
- local automatic scoring 1–7
- 1–7 day score-based retention for unliked detections
- indefinite retention for favourites
- manual deletion workflow
- web UI on 8094, scoring status on 8095, favourites on 8096 and statistics on 8097
- pre-render image cache
- station health monitoring
- optional RTL-SDR owner arbitration for a shared receiver

## Reference verification

- Golden: `20260921_165532_GOLDEN`
- source snapshot files: 69
- Golden `SHA256SUMS.txt` SHA-256:
  `36dfebd31fec749266fa5f5b902635feef7bd75add4bd57c6205806f22c98b9f`

Raw SMP observations and generated PNG cache are not part of the reference release.

## Licensing note

The public repository does not include copied upstream MeteorRadio core source until its redistribution/license status is clarified. See `UPSTREAM_LICENSE_NOTICE.md`.
