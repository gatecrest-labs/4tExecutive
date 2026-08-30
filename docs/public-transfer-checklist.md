# Public transfer checklist

Use this checklist immediately before transferring to an organization and making the repository public.

## 1) Verify working tree and branch state

```bash
git branch --show-current
git rev-parse --short HEAD
git status --short
```

Expected: correct branch, expected commit, and clean working tree.

## 2) Confirm sensitive runtime files are not tracked

```bash
git ls-files | egrep '^(\.env|\.env\.|certs/|config/[^/]+\.json|metrics\.db)$'
```

Expected: no output.

## 3) Confirm ignore rules still protect local secret locations

```bash
git check-ignore -v .env .env.local .env.production certs/key.pem certs/cert.pem config/users.json config/sources.json metrics.db
```

Expected: each file is matched by a rule in .gitignore.

## 4) Quick history signal scan

```bash
git log --all -G 'SECRET_KEY=|ghp_|github_pat_|AKIA|ASIA|AIza|BEGIN PRIVATE KEY|password_hash\s*:\s*"\$2' --pretty=format:'%h %ad %s' --date=short | head -n 30
```

Expected: only known commits related to examples/docs, no real secrets.

## 5) Rotate and regenerate before public exposure

- Rotate SECRET_KEY.
- Rotate all source bearer tokens that may have existed in local config files.
- Regenerate local cert material under certs/ if it was shared.

## 6) Transfer and enable org security defaults

After transfer to the organization and before/when making public:

- Confirm Dependabot alerts and security updates are enabled.
- Confirm Dependabot update PRs are enabled (dependabot.yml is present).
- Confirm Secret scanning is enabled for the public repository.
- Confirm private vulnerability reporting is enabled.

## 7) Post-transfer validation

- Open the Security tab and verify all checks are green.
- Confirm first Dependabot run picks up Python, GitHub Actions, and Docker ecosystems.
