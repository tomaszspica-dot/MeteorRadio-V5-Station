# Deployment

Run `../IMPORT_FROM_INSTALLER.command` to populate `systemd/reference/` with the sanitized reference units from the final installer.

Reference units should be reviewed before deployment because they may contain `User=pi`, `/home/pi` paths and shared-RTL-SDR assumptions.
