# Configuration examples

These files are intentionally sanitized examples.

- `radar_config.example` mirrors the fields expected by the upstream acquisition core without publishing a real station location.
- `station.example.env` documents the reference directory/port layout. The current V5 services do not necessarily source this file directly; treat it as a deployment reference.

Never replace the examples with real secret/private configuration in Git.

- `rmob_station.example.ini` documents the private local metadata/path inputs used by the RMOB TXT/JPEG publisher. Keep the real file outside Git.
