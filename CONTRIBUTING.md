# Contributing

Contributions are welcome for the station overlay, documentation, monitoring, dashboards, scoring workflow and deployment tooling.

Before submitting a change:

1. Run `scripts/validate_public_repo.sh`.
2. Do not commit raw station data or exact private coordinates.
3. If adding copied or modified upstream MeteorRadio source, preserve the GPLv3 license/copyright notices, mark modifications clearly, and follow `UPSTREAM_LICENSE_NOTICE.md`.
4. Keep changes small and auditable.
5. For systemd changes, document whether a service restart is required and whether RTL-SDR ownership may be affected.
6. For scoring or retention changes, describe migration implications for existing station state.

When reporting a bug, include the relevant service name, platform, Python version, and a short sanitized log excerpt.
