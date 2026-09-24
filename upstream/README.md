# Upstream MeteorRadio

The acquisition/detection foundation is:

<https://github.com/rabssm/MeteorRadio>

Upstream licensing was clarified on **2026-09-24** as **GNU GPLv3**:

<https://github.com/rabssm/MeteorRadio/issues/14>

The upstream repository now contains a standard GPLv3 `LICENSE` file and modified MeteorRadio source may be redistributed under GPLv3 subject to its requirements.

This V5 repository still does **not** vendor the locally modified acquisition core by default. After local import, the exact modified reference core is kept under:

```text
private_reference/upstream-meteorradio-modified/
```

That directory is ignored by Git. This is a packaging/audit choice, not a licensing prohibition. Before intentionally publishing the modified core, follow `docs/UPSTREAM_GPLV3_PUBLICATION_CHECKLIST.md`.
