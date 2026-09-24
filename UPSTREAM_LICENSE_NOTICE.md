# Upstream MeteorRadio licensing / redistribution status

## Status: resolved on 2026-09-24

The reference station is based on `rabssm/MeteorRadio`:

<https://github.com/rabssm/MeteorRadio>

The upstream author clarified the licensing and redistribution terms in:

<https://github.com/rabssm/MeteorRadio/issues/14>

The upstream repository now contains a standard **GNU General Public License v3.0 (GPLv3)** `LICENSE` file. A verbatim copy of that upstream license is retained in this repository at [`third_party/MeteorRadio/LICENSE`](third_party/MeteorRadio/LICENSE) for MeteorRadio-derived material.

## What this means for MeteorRadio-derived code

The upstream author explicitly confirmed that:

- MeteorRadio is intended to be licensed under **GPLv3**;
- modified MeteorRadio source may be redistributed under GPLv3;
- commercial use and redistribution are permitted under GPLv3;
- existing copyright and GPL notices must be retained;
- modified upstream source files must carry appropriate modification information;
- corresponding source must be made available when required by GPLv3;
- submitting changes upstream as pull requests is welcome, but is not mandatory.

Any MeteorRadio-derived source distributed by this project must therefore remain under GPLv3 and preserve the upstream notices and authorship.

## Current V5 repository policy

The modified upstream acquisition core is still kept under Git-ignored `private_reference/` by default.

This is now a **packaging and audit choice, not a licensing blocker**. Before publishing the modified core in this repository, the project should:

1. identify the exact upstream base commit;
2. preserve the upstream copyright and GPLv3 notices;
3. mark the V5 modifications clearly;
4. include the applicable GPLv3 license text with the distributed upstream-derived component;
5. verify that the complete corresponding source is available;
6. prepare a clean diff suitable for possible upstream review / pull request.

The independent V5 station-layer software may have a separate license where it is genuinely independent of the GPL-covered MeteorRadio code. No repository-wide license for that independent station-layer code has been selected yet; see `docs/LICENSE_DECISION.md`.

This file records the project's publication policy and upstream clarification. It is not legal advice.
