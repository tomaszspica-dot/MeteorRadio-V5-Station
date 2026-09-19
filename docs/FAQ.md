# FAQ

## Is this the original MeteorRadio project?

No. The acquisition foundation comes from `rabssm/MeteorRadio`. This repository documents a V5 station overlay and operational layer built around it.

## Why is the upstream core missing from the public tree?

Because an explicit upstream software license was not visible during preparation. The modified reference core is kept locally under ignored `private_reference/` until redistribution rights are clarified.

## Why is `meteorradio.service` disabled in the reference system?

The reference station shares its RTL-SDR with another receiver. `radio-owner-restore.service` restores the selected owner after boot. A dedicated station can use a different boot design.

## Are detections uploaded somewhere automatically?

The documented V5 overlay focuses on local acquisition, scoring, retention and web views. Any external data-sharing integration should be documented and enabled separately.

## Are raw detections stored in Git?

No. Raw SMP files and generated cache images are ignored by default.

## Can the exact reference station be cloned 1:1?

Not safely without adapting usernames, paths, RTL-SDR ownership, station configuration and radio environment. The reference package is intended to be audited and adapted per station.
