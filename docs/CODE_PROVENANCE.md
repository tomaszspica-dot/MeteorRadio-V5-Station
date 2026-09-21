# Code provenance and external project references

This document records which external projects were used as an upstream base, which methods or data formats were reimplemented from documented behavior, and which projects were reviewed only as conceptual references.

The purpose is to avoid both under-crediting and over-claiming. A project listed as **reference / inspiration** should not be read as a claim that its source code was copied.

Audit date: **2026-09-21**.

## Provenance map

| External project | Relationship to MeteorRadio V5 | Local/public area | Code relationship |
|---|---|---|---|
| [rabssm/MeteorRadio](https://github.com/rabssm/MeteorRadio) | Primary upstream acquisition and radio-meteor detection foundation | local acquisition core; V5 station layer around it | The locally modified upstream acquisition core is intentionally **not vendored** in this public repository while redistribution/licensing remains unclear. |
| [MeteorRadio `src/smp2wav.py`](https://github.com/rabssm/MeteorRadio/blob/main/src/smp2wav.py) | Reference for converting saved complex IQ SMP data to USB audio by taking the real component and writing 16-bit PCM | `software/meteorradio-web/render_audio_original_v1.py`, `render_audio_v1.py` | Method adapted/reimplemented. Current public renderers were rewritten for the V5 station; the filtered renderer adds local band-pass, DC removal, normalization and fade handling. |
| [MeteorRadio `src/monthly_rmob.py`](https://github.com/rabssm/MeteorRadio/blob/main/src/monthly_rmob.py) | Reference for MeteorRadio/RMOB monthly-output workflow | `software/meteorradio-rmob/rmob_utc_export.py` | Format/workflow reference; V5 exporter is independently implemented. |
| [bolidozor/rmob-export](https://github.com/bolidozor/rmob-export) | Reference for RMOB-compatible export/colorgramme workflows and network interoperability | `software/meteorradio-rmob/rmob_utc_export.py` and RMOB docs | Format/workflow reference; no direct source-code copy identified in the current V5 exporter. |
| [MLAB-project/pysdr](https://github.com/MLAB-project/pysdr) — Freya / [`tools/3dwf.py`](https://github.com/MLAB-project/pysdr/blob/master/tools/3dwf.py) | Visual reference for a 3D spectral-waterfall surface | `software/meteorradio-3d/server.py` / port 8099 | **Visualization inspiration only.** The V5 viewer is an independent HTTP/HTML/JS implementation over saved MeteorRadio NPZ data; no Freya source-code copy was identified in the current file. |
| [bolidozor/RTbolidozor](https://github.com/bolidozor/RTbolidozor) | Reference for real-time web presentation of radio-meteor events and event metadata flow | V5 web/dashboard design research | Concept/reference only; no direct source-code copy identified in current V5 public files. |
| [bolidozor/BolidozorKiosk](https://github.com/bolidozor/BolidozorKiosk) | Reference for visitor-facing exploration of live and historical meteor detections | dashboard/showcase research | Concept/reference only; no direct source-code copy identified. |
| [bolidozor/MeteorDataAnalyser](https://github.com/bolidozor/MeteorDataAnalyser) | Reference for post-processing and histogram-based analysis of radio-meteor observations | statistics/analysis research | Concept/reference only; no direct source-code copy identified. |
| [bolidozor/trails-processing](https://github.com/bolidozor/trails-processing) | Reference for notebook-based meteor-trail post-processing workflows | trajectory/post-processing research | Concept/reference only; no direct source-code copy identified. |
| [bolidozor/RMDS02](https://github.com/bolidozor/RMDS02) | Reference implementation of a GRAVES-oriented radio meteor detection station and its measurement workflow | hardware/system and Doppler-analysis research | Architecture/scientific reference only; no direct source-code copy identified. |
| [bolidozor/python-bolidozor-postprocessing](https://github.com/bolidozor/python-bolidozor-postprocessing) | Reference for modular meteor-data post-processing | post-processing architecture research | Concept/reference only; no direct source-code copy identified. |
| [carmelo-meteor/carmelo_meteor](https://github.com/carmelo-meteor/carmelo_meteor) | Alternative GRAVES radio-meteor logger studied for comparison | detector/network research | Consulted reference only; no source code from CARMELo is intentionally incorporated in the current V5 public tree. |
| [jrb985/radio-meteor-project](https://github.com/jrb985/radio-meteor-project) | Reference for a modern Raspberry Pi radio-meteor workflow, dashboard/data products and heuristic event classification | dashboard/classification architecture research | Inspiration/reference only; no direct source-code copy identified. |

## Current V5 modules and attribution

### Acquisition core
The actual acquisition/detection foundation is **MeteorRadio by `rabssm`**. Local changes to that upstream-derived core are kept outside this public repository until redistribution terms are clear.

### Audio renderers
The basic SMP IQ-to-USB-audio method follows the documented MeteorRadio `smp2wav.py` approach: load complex IQ samples, use the real component for USB audio, and convert to signed 16-bit PCM. The V5 files are separately structured implementations and add validation, atomic output, optional filtering, normalization and fades.

### 3D Spectrogram Viewer
Freya / PySDR `tools/3dwf.py` was reviewed as a **visual concept** for presenting a spectral waterfall as a 3D surface. The V5 8099 service does not use the PySDL/OpenGL implementation and instead serves an independent browser-based viewer from stored MeteorRadio NPZ observations.

### RMOB export
MeteorRadio's RMOB tooling and Bolidozor's `rmob-export` were used as references for expected RMOB-oriented workflows. The V5 UTC exporter is station-local code designed around the V5 CSV logs and UTC-hour accounting.

### Trajectory-family analysis
The 8100 solver was developed as a V5 station module around single-station bistatic GRAVES geometry and measured Doppler evolution. Bolidozor analysis/station projects and CARMELo were reviewed as context, not copied as solver source.

## License/status notes

- **rabssm/MeteorRadio:** no root license file was found during the 2026-09-21 publication audit; therefore the modified upstream acquisition core remains outside the public V5 tree.
- **MLAB-project/pysdr:** its README states GNU GPL v3.
- **bolidozor/RTbolidozor** and **bolidozor/MeteorDataAnalyser:** upstream repositories contain GPL license material.
- **bolidozor/rmob-export:** upstream repository contains GPL license material; consult that repository for the exact applicable terms.
- **bolidozor/python-bolidozor-postprocessing:** upstream repository contains a permissive BSD-style license.
- **jrb985/radio-meteor-project:** MIT licensed.
- **CARMELo, BolidozorKiosk, trails-processing and RMDS02:** no claim of code reuse is made here; they are credited as references.

If a future audit identifies a direct copied or modified third-party code block, this document and the affected source file must be updated to name the exact upstream file, commit and license.
