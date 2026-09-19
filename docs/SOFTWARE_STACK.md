# Software stack

## Reference system

- Debian GNU/Linux on Raspberry Pi / aarch64
- Python 3 virtual environment: reference path `/home/pi/vMeteorRadio`
- upstream MeteorRadio acquisition/detection core
- custom station web layer and local workers
- systemd for service supervision and timers

## Main station components

| Component | Purpose |
|---|---|
| `meteorradio.service` | SDR acquisition and meteor detection |
| `meteorradio-web.service` | main panel, port 8094 |
| `meteorradio-queue-status.service` | scoring queue/status, port 8095 |
| `meteorradio-likes.service` | favourites/retention UI, port 8096 |
| `meteorradio-stats.service` | statistics panel, port 8097 |
| `meteorradio-prerender.service` | background image rendering/cache |
| `meteorradio-score-new.timer` | periodic automatic scoring |
| `meteorradio-retention.timer` | periodic retention cleanup |
| `meteorradio-healthcheck.timer` | periodic passive health check |
| `radio-owner-restore.service` | optional shared-RTL-SDR ownership restore |

## Reference dependency information

The final installer contains a sanitized copy of the Golden metadata, including:

- Python version
- pip freeze
- Debian package list
- systemd unit snapshot
- source file metadata
- upstream Git state

`IMPORT_FROM_INSTALLER.command` stores that information under `private_reference/` so it can be consulted locally without publishing the entire machine fingerprint.
