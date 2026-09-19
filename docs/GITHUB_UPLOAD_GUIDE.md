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

## Before Public

The main blocker to a full-source public release is the unclear upstream license. Keep `private_reference/` private and follow `UPSTREAM_LICENSE_NOTICE.md`.
