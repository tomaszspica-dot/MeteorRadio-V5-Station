# 3D Trajectory Analyzer — port 8100

The analyzer uses saved observation data exposed through the 8099 analysis service.

It implements a single-station bistatic model.

## Interpretation

Its result is a family of geometries compatible with the measured Doppler evolution.

It is not a unique reconstruction of the meteoroid's physical trajectory.

## Receiver configuration

Public source code does not contain receiver coordinates.

Configure locally:

- `METEORRADIO_RX_LAT`
- `METEORRADIO_RX_LON`
- `METEORRADIO_RX_ALT_KM`

See:

`config/trajectory.example.env`

The GRAVES reference position is public and may also be overridden through environment variables.
