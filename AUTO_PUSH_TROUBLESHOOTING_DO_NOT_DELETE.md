# Auto-Push Troubleshooting (Compatibility Pointer)

This file is intentionally retained for compatibility with existing references.

Canonical documentation now lives in:

- `docs/DEPLOYMENT_SYSTEM.md`

Use that document for:

- deployment architecture
- operational troubleshooting
- failure recovery steps
- hook safety guardrails

## Quick Triage Commands

```bash
cat .post-commit-output/bundle.txt
cat .post-commit-output/bundle-push.log
cat .post-commit-output/import-test.txt
```

## Critical Safety Rule

Never add destructive cleanup commands (`git rm -rf .`, broad `rm -rf`) to deployment hooks.
