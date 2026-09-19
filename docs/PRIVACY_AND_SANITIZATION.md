# Privacy and sanitization

A radio-observation repository can unintentionally reveal more than expected.

## Keep private unless intentionally public

- exact latitude/longitude of a home station
- street address
- SSH usernames if personally identifying
- passwords and tokens
- Wi-Fi configuration
- private hostnames
- raw detection archives if they contain unrelated recordings or metadata you do not want public
- live operational state copied from `/var/lib` or private cache databases

## Safe approach

Use `config/radar_config.example` with obvious placeholders. Keep the real `.radar_config` outside Git.

The supplied `.gitignore` excludes the most important runtime/private artifacts, and `scripts/validate_public_repo.sh` performs a final scan before publishing.

## Screenshots

Before committing a screenshot, inspect browser tabs, bookmarks, terminal prompts, hostnames, usernames and other windows in the background. Crop aggressively.
