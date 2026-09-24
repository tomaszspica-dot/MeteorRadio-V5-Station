# GitHub upload guide

## Recommended first publication: Private repository

1. Run `IMPORT_FROM_INSTALLER.command`.
2. Add sanitized screenshots if desired.
3. Run `VALIDATE_BEFORE_GITHUB.command`.
4. Complete `docs/PUBLICATION_CHECKLIST.md`.
5. Run `INIT_GIT_REPO.command`.
6. Review `git status` carefully.
7. Commit locally.
8. Create a new **Private** repository on GitHub.
9. Add the remote and push `main`.
10. Review the rendered repository online before changing visibility.

## Example Git commands

Replace `YOUR_ACCOUNT` and `YOUR_REPO`:

```bash
git add .
git status --short
git commit -m "Initial MeteorRadio V5 station overlay"
git remote add origin git@github.com:YOUR_ACCOUNT/YOUR_REPO.git
git push -u origin main
```

HTTPS can be used instead of SSH if preferred.

## Before publishing upstream-derived core

The previous upstream licensing blocker is resolved: MeteorRadio is now explicitly **GPLv3**. The current V5 packaging still keeps the locally modified core in `private_reference/` by default until its exact upstream base, retained notices and modification information are prepared.

Follow `UPSTREAM_LICENSE_NOTICE.md` and `docs/UPSTREAM_GPLV3_PUBLICATION_CHECKLIST.md` before intentionally adding upstream-derived source to the public tree.
