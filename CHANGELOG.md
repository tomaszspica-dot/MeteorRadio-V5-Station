# Changelog

## 2026-09-24 — upstream licensing clarification

- upstream `rabssm/MeteorRadio` licensing confirmed as **GNU GPLv3** in issue #14
- confirmed the upstream repository now contains a standard GPLv3 `LICENSE`
- recorded that modified MeteorRadio source may be redistributed under GPLv3
- updated V5 documentation to remove the obsolete "license unclear" blocker
- kept the modified upstream acquisition core in `private_reference/` by current packaging policy until GPLv3 attribution, modification notices and source provenance are prepared
- kept the independent V5 station-layer repository-wide license decision separate

## V5 — 2026-09-21 Golden refresh

- refreshed the public station layer from the verified 2026-09-21 Golden
- updated Adaptive Capture pre-trigger context to 3.0 s
- added corrupt-NPZ validation to scoring and prerender
- extended health monitoring to ports 8099 and 8100
- added the 3D Spectrogram Viewer on port 8099
- added the 3D Trajectory Analyzer on port 8100
- moved receiver coordinates to local environment configuration
- added RMOB-oriented export tooling
- added new 8099 and 8100 screenshots
- removed station-specific hostnames, private IP addresses and receiver coordinates
- strengthened publication validation
- kept the modified upstream acquisition core outside the public repository
- confirmed private mobile-client components are absent from the public repository
- added explicit code-provenance and project-credit mapping for MeteorRadio, Bolidozor/MLAB, Freya/PySDR, CARMELo and Radio Meteor Project

## V5 — 2026-09-19

- added sanitized project screenshots and GitHub showcase/discoverability documentation
- added adaptive capture with pre-trigger context and fade-based stop
- added local scoring pipeline 1–7
- added score-based 1–7 day retention policy
- added favourites with indefinite retention
- added manual deletion workflow
- added 8095 scoring queue/status service
- added 8096 favourites panel with full-size image modal
- added 8097 statistics dashboard
- added background image pre-rendering
- added health monitoring
- added optional RTL-SDR owner arbitration and boot restore
- removed visible trigger marker from final waterfall view
- cleaned stale score-index entry and legacy V5 cache images before Golden V5
- produced verified Golden V5 snapshot with SHA-256 manifest
