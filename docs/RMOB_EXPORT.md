# RMOB exporter, summary JPEG and uploader

The RMOB layer is deliberately independent from the RTL-SDR acquisition process.

Upstream MeteorRadio documents `monthly_rmob.py` as a tool that produces data
for RMOB Colorgramme software. The V5 station layer keeps that separation:
MeteorRadio records detections; this directory converts them to the standard
monthly RMOB table, renders a summary JPEG, and optionally calls the official
RMOBclient transfer utility.

## Pipeline

```text
MeteorRadio RYYYYMMDD_*.csv
        |
        v
rmob_utc_export.py
        |
        +--> Observer_MMYYYYrmob.TXT
        +--> RMOB-YYMM.DAT
        |
        v
rmob_colorgramme.py
        |
        +--> Observer_MMYYYY.jpg
        |
        v
rmob_upload.py
        |
        v
official RMOBclient -> RMOB server
```

`rmob_colorgramme.py` is an independent renderer. It does **not** contain or
run Colorgramme/Colorgramme Lab code. It follows the public RMOB summary
convention:

- station metadata
- latest observed day's hourly histogram
- month/day-hour heatmap
- UTC hour labelling

The JPEG is generated headlessly with Matplotlib. No Qt, Xvfb, desktop session,
trajectory analysis or saved-signal/spectrogram visualizer is required.

RMOBclient is a separately distributed binary-only transfer utility from the
Echoes project. It is not redistributed by this repository.

## Time handling

RMOB hourly bins are UTC.

MeteorRadio daily CSV timestamps are naive, so the source timezone must be
explicit in the local INI file:

```ini
[paths]
source_timezone = UTC
```

or, if the acquisition host writes local Polish time:

```ini
source_timezone = Europe/Warsaw
```

Do not guess this value. Verify the acquisition host and one known CSV timestamp
before enabling automatic uploads.

## Configuration

Copy:

```text
config/rmob_station.example.ini
```

to a private local path, for example:

```text
/home/pi/.config/meteorradio/rmob.ini
```

Fill in station metadata locally. Do not commit private coordinates or
credentials.

## Safe pre-upload test

Generate TXT/DAT/JPEG without network upload:

```bash
/home/pi/vMeteorRadio/bin/python \
  /home/pi/meteorradio-rmob/rmob_publish.py \
  --config /home/pi/.config/meteorradio/rmob.ini \
  --no-upload
```

Then inspect:

```text
/home/pi/meteorradio-rmob/output/Observer_MMYYYYrmob.TXT
/home/pi/meteorradio-rmob/output/Observer_MMYYYY.jpg
```

The upload adapter also has a dry-run mode:

```bash
/home/pi/vMeteorRadio/bin/python \
  /home/pi/meteorradio-rmob/rmob_publish.py \
  --config /home/pi/.config/meteorradio/rmob.ini \
  --dry-run-upload
```

## Upload adapter validation

The adapter invokes the official RMOBclient with the TXT and JPEG filenames in
the output directory. A run is accepted only when:

- RMOBclient exits with status 0
- output contains exactly two `QNetworkReply::NoError` confirmations

This preserves the useful validation from the previous station while removing
Ebrow/Qt from the RMOB generation path.

## Automatic schedule

Reference units are provided as:

- `deployment/systemd/reference/meteorradio-rmob.service`
- `deployment/systemd/reference/meteorradio-rmob.timer`

The reference timer runs at minute `:57`. Treat the units as templates until
paths, source timezone, station metadata and RMOBclient have been verified on
the target host.

## Migration scope

The RMOB migration profile needs only:

- MeteorRadio acquisition/detection
- RMOB TXT/DAT exporter
- RMOB summary JPEG renderer
- RMOB upload adapter
- passive health monitoring

The optional 3D trajectory analyzer and saved-signal/spectrogram visualization
services are **not part of this migration profile** and should remain disabled
unless the operator explicitly chooses to deploy them later.
