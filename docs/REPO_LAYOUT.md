# Repository layout

```text
MR_GH/
├── README.md
├── README_PL.md
├── software/
│   ├── meteorradio-web/       custom web/scoring/retention layer
│   ├── meteorradio-stats/     statistics service
│   └── tools/                 healthcheck + optional radio owner tool
├── deployment/
│   └── systemd/reference/     reference units copied from final installer
├── config/                    sanitized examples only
├── docs/                      public documentation
├── upstream/                  upstream references, no copied core source
├── assets/                    diagrams/screenshots
├── scripts/                   validation/release helpers
└── private_reference/         created locally, Git-ignored
```

`private_reference/` is intentionally absent until `IMPORT_FROM_INSTALLER.command` is run.
