# Upstream license / redistribution notice

## Why the upstream core is not in the public tree

The reference station is based on `rabssm/MeteorRadio`:

<https://github.com/rabssm/MeteorRadio>

During preparation of this GitHub package on 2026-09-19:

- no root `LICENSE` file was visible in the upstream repository listing;
- the inspected beginning of `src/meteor_radar.py` did not contain an explicit license header.

Without an explicit software license, public redistribution and relicensing of copied/modified upstream source should **not** be assumed to be permitted.

Therefore this repository template uses a conservative structure:

- public docs and station-layer code can live in the repository;
- the modified upstream core is imported only into `private_reference/`;
- `private_reference/` is excluded by `.gitignore`;
- a public full-source release should wait until the upstream author clarifies or grants redistribution rights.

This file is a practical publication precaution, not legal advice.

A ready-to-send permission request is available at:

`docs/UPSTREAM_PERMISSION_REQUEST_TEMPLATE.md`
