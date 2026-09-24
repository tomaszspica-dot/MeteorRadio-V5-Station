# License decision for this repository

## Upstream status

The previous licensing uncertainty around `rabssm/MeteorRadio` was resolved on **2026-09-24**.

The upstream author confirmed in <https://github.com/rabssm/MeteorRadio/issues/14> that MeteorRadio is intended to be licensed under **GNU GPLv3**, and the upstream repository now contains the standard GPLv3 `LICENSE` file.

Accordingly, copied or modified MeteorRadio source that is distributed by this project must remain under GPLv3, retain the existing copyright / license notices, identify modifications as required, and provide the corresponding source as required by GPLv3.

## Independent V5 station-layer code

No repository-wide `LICENSE` file is intentionally added yet for the independently developed V5 station-layer code.

That is now a separate project decision rather than an upstream-permission problem. A root license should be selected only after deciding how the independent station-layer components should be reusable.

Until such a license is selected, others should **not** assume broad reuse rights for the original station-layer code merely because this repository is public.

## Component boundary

- **MeteorRadio upstream and distributed modifications of it:** GPLv3.
- **Genuinely independent V5 station-layer components:** license not yet selected.
- **Third-party references / inspiration:** governed by their respective upstream licenses and the provenance notes in `docs/CODE_PROVENANCE.md`.

See also `UPSTREAM_LICENSE_NOTICE.md`.
