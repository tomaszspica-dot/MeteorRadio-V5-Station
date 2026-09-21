# Custom station software

This area is populated from `MeteorRadio_V5_ChatGPT_Installer.zip` by `IMPORT_FROM_INSTALLER.command`.

Public components are separated from the upstream acquisition core:

- `meteorradio-web/` — UI, rendering, scoring, retention and queue logic
- `meteorradio-stats/` — statistics service
- `meteorradio-3d/` — read-only 3D spectrogram analysis
- `meteorradio-trajectory/` — single-station bistatic trajectory-family analysis
- `meteorradio-rmob/` — RMOB-oriented UTC export tooling
- `tools/` — healthcheck and optional shared-radio ownership helper

The modified upstream `MeteorRadio` core is copied only to Git-ignored `private_reference/`.
