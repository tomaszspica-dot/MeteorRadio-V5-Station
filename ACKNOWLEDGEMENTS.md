# Acknowledgements

MeteorRadio V5 stands on work from the radio-meteor and SDR communities. This file names the projects explicitly and distinguishes **upstream/code-method provenance** from **reference/inspiration**.

For the file-by-file map, see [`docs/CODE_PROVENANCE.md`](docs/CODE_PROVENANCE.md).

## Primary upstream foundation

### MeteorRadio by rabssm

- Project: **MeteorRadio**
- Repository: https://github.com/rabssm/MeteorRadio

MeteorRadio is the acquisition and radio-meteor detection foundation used by this station. The locally modified upstream acquisition core is deliberately not vendored in this public repository while redistribution/licensing rights remain unclear.

Two public V5 audio renderers also credit MeteorRadio's `src/smp2wav.py` as the method reference for converting complex SMP IQ to USB 16-bit PCM. The V5 implementations are rewritten and extended rather than published as copies of that upstream file.

MeteorRadio's RMOB tooling, including `src/monthly_rmob.py`, was also used as a workflow/format reference for the V5 RMOB exporter.

## Bolidozor / MLAB ecosystem

- **RTbolidozor** — https://github.com/bolidozor/RTbolidozor — real-time browser/event-flow reference.
- **rmob-export** — https://github.com/bolidozor/rmob-export — RMOB export/colorgramme workflow reference.
- **BolidozorKiosk** — https://github.com/bolidozor/BolidozorKiosk — live/historical exploration reference.
- **MeteorDataAnalyser** — https://github.com/bolidozor/MeteorDataAnalyser — post-processing/histogram reference.
- **trails-processing** — https://github.com/bolidozor/trails-processing — meteor-trail post-processing reference.
- **RMDS02** — https://github.com/bolidozor/RMDS02 — GRAVES station architecture/measurement reference.
- **python-bolidozor-postprocessing** — https://github.com/bolidozor/python-bolidozor-postprocessing — modular post-processing reference.
- **PySDR / Freya** — https://github.com/MLAB-project/pysdr — especially https://github.com/MLAB-project/pysdr/blob/master/tools/3dwf.py — visual inspiration for the V5 3D Spectrogram Viewer.

These entries intentionally say **reference**, **workflow reference**, or **visual inspiration** where no direct source-code copying was identified.

## Other radio-meteor projects reviewed

- **CARMELo — Cheap Amatorial Radio MEteor Logger** — https://github.com/carmelo-meteor/carmelo_meteor — alternative GRAVES radio-meteor logger/station reference; no CARMELo source is intentionally incorporated in the current V5 public code.
- **Radio Meteor Project by jrb985** — https://github.com/jrb985/radio-meteor-project — reference for Raspberry Pi radio-meteor architecture, data products, dashboard ideas and heuristic event classification; no direct source-code copy was identified.

## MeteorRadio V5 station layer

The V5 station layer adds independently developed operational components including web detection interfaces, scoring/retention, cached rendering, health monitoring, 3D spectrogram inspection, single-station bistatic trajectory-family analysis, RMOB-oriented UTC export tooling, and systemd deployment/operating tools.

## GRAVES

GRAVES at 143.050 MHz is used as the distant illumination source for meteor-scatter reception. This is an independent receiving-station project and is not affiliated with the GRAVES operator.
