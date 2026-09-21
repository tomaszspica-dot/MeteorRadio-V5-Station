# Acknowledgements

## MeteorRadio

The radio-acquisition and meteor-detection foundation used by this station is based on:

- **MeteorRadio** by `rabssm`
- https://github.com/rabssm/MeteorRadio

The modified acquisition core is deliberately not vendored in this public repository while redistribution/licensing rights remain unclear.

See `UPSTREAM_LICENSE_NOTICE.md`.

## MeteorRadio V5 station layer

The station layer adds independently developed operational components including:

- web detection interfaces,
- scoring and retention,
- cached rendering,
- system health monitoring,
- 3D spectrogram inspection,
- single-station bistatic trajectory-family analysis,
- RMOB-oriented export tooling,
- systemd deployment and operating tools.

## Radio-meteor ecosystem

RMOB is referenced as a community interoperability and monthly-data target.

Other radio-meteor visualization and multi-station workflows were useful conceptual references during development. Such references do not imply incorporation of third-party source code unless explicitly stated in a file.

## GRAVES

GRAVES at 143.050 MHz is used as the distant illumination source for meteor-scatter reception.

This is an independent receiving-station project and is not affiliated with the GRAVES operator.
