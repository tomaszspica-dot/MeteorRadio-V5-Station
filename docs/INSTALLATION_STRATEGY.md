# Installation strategy

This GitHub package is not intended to be a blind one-command installer.

## 1. Install upstream acquisition core

Use the upstream MeteorRadio project as the acquisition/detection foundation:

<https://github.com/rabssm/MeteorRadio>

Verify RTL-SDR access with `rtl_test` before enabling any persistent service.

## 2. Choose radio ownership model

### Dedicated RTL-SDR

If the dongle is used only by MeteorRadio, the acquisition service can be managed directly by systemd after paths and permissions are reviewed.

### Shared RTL-SDR

If the same dongle is shared with radiosonde, SatNOGS or another receiver, use an arbitration layer. The reference implementation is in `software/tools/radio-owner-control` after importing from the installer.

## 3. Adapt paths

Reference units may contain `/home/pi` and `User=pi`. Do not copy these blindly. Adapt:

- `User=`
- `Group=`
- `WorkingDirectory=`
- `ExecStart=`
- virtual-environment path
- radar-data path

## 4. Deploy the station overlay

After running `IMPORT_FROM_INSTALLER.command`, the public custom components are under `software/` and reference systemd units under `deployment/systemd/reference/`.

Treat those units as templates until all local paths have been checked.

## 5. Core V5 adaptive-capture modification

The reference station uses a modified upstream `meteor_radar.py` implementing `ADAPTIVE_CAPTURE_V2`. Upstream MeteorRadio is now confirmed as **GPLv3**, so redistribution of a compliant modified version is permitted.

The current V5 package still stores the modified core locally under `private_reference/` and excludes it from Git by default. This preserves a clean boundary while the exact upstream base, retained notices and V5 modification information are prepared.

A public source copy or reproducible patch may now be prepared under GPLv3. Follow `UPSTREAM_LICENSE_NOTICE.md` and `docs/UPSTREAM_GPLV3_PUBLICATION_CHECKLIST.md`.

## 6. Verification

Verify:

- RTL-SDR opens successfully
- 8094, 8095, 8096 and 8097 respond
- scoring timer runs
- retention timer runs
- healthcheck produces valid state
- a new SMP detection reaches scoring and rendering
- shared-radio switching, if enabled, does not leave both receivers active
