# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| latest (0.1.x) | ✅ |
| older | ❌ |

## Reporting a vulnerability

Please **do not open a public issue** for security vulnerabilities. Report
privately instead:

- GitHub private vulnerability reporting:
  https://github.com/bpshil/litkit-search/security/advisories/new
- Or email the maintainers (see the git log / PyPI metadata) with the subject
  `[litkit-security] ...`.

Include:

1. Affected version(s) and environment (OS, Python).
2. Steps to reproduce (minimal).
3. Impact and any suggested fix (if known).

You should receive an acknowledgement within 3 business days, and a fix
timeline after triage.

## Scope

- The Python package (`src/litkit`) and adapters (`adapters/`).
- Secrets handling: `.env` loading, cookies, institutional credentials —
  these are read from the user's own environment only and never logged.
- Supply-chain: dependencies pinned to major versions; `gitleaks` runs in CI
  on every push/PR.

## Out of scope / by design

- **Shadow-library & institutional download paths** are declared functionality
  (see README **Legal notice**); legal/abuse concerns are not security bugs.
- Misuse of a user's own credentials is the user's responsibility.
