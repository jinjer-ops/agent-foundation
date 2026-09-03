---
title: Agent foundation handover
type: handover
status: active
created_at: 2026-09-03
updated_at: 2026-09-03
owners: [foundation-maintainers]
tags: [handover, foundation, skills]
---

# Handover

## Purpose and boundary

This repository is the public, product-neutral source of shared agent working rules and reusable
skills. It contains portable safety, quality, publication, audit, and handover guidance. It does
not contain organization configuration, customer or employee data, credentials, local paths,
runtime state, approval history, or project-specific operating procedures.

Acceptance criteria: a new maintainer can identify the source of truth, install or link the shared
files, run a local layout check, and decide whether a proposed rule belongs in this repository or a
private or repository-local layer.

## Current state — 2026-09-03

`AGENTS.md` is the common working agreement. `skills/` contains the reusable `audit`,
`github-publish`, and `project-handover` workflows. `scripts/install.ps1` links those assets into
supported local agent locations; `scripts/verify-layout.ps1` checks the required layout and scans
the repository for selected private-data patterns.

The audit skill requires an explicit audit contract, risk-based lenses, evidence labels, a
claim-to-proof trace, a separate approval boundary for remediation, and post-fix verification. Its
design review is recorded in `docs/audits/2026-09-03-audit-skill-design/`.

## How to continue

1. Read `README.md`, `AGENTS.md`, and `CONTRIBUTING.md`; then inspect `git status --short`.
2. Keep portable rules in the smallest suitable shared file. Put organization, customer, service,
   account, and repository-specific details outside this foundation.
3. For a skill change, state the reusable problem, update only the affected skill and direct
   supporting material, then run the verification commands below.
4. Use a feature branch and pull request for a shared change. Before publication, use the
   `github-publish` skill and review the change as a first-time reader would.

## Decisions in force

- `AGENTS.md` is the common baseline; repository-local instructions may make it stricter but do
  not weaken its safety boundary.
- A skill records non-obvious, reusable decision guidance. It does not replace user authority or
  grant access to an external system.
- Learning-log entries must be portable, anonymized, evidence-backed, and useful as a future safe
  default. One project's threshold, terminology, or configuration does not become a global rule.
- An audit starts read-only. A state-changing remediation requires its own preview, approval,
  input binding, rollback method, and evidence.

## Environment and verification

The foundation has no application dependencies. PowerShell is required for the supplied install and
layout commands. When the Skill Creator is available, its metadata validator uses Python.

Run from the repository root:

```powershell
& .\scripts\verify-layout.ps1 -Root (Get-Location).Path
git diff --check
```

Use the Skill Creator's `quick_validate.py` in UTF-8 mode to validate changed skill metadata and
unfinished scaffold markers. The layout check validates required foundation paths and selected
private-data patterns; it is not a substitute for a project-specific public-boundary review.
`git diff --check` reports whitespace errors. Before a release, additionally scan the exact staged
paths for credentials, local context, and copied external content.

## Artifacts

- Common agreement: `AGENTS.md`
- Foundation overview: `README.md`
- Contribution boundary: `CONTRIBUTING.md`
- Reusable skills: `skills/`
- Install and layout verification: `scripts/install.ps1`, `scripts/verify-layout.ps1`
- Audit-skill design evidence: `docs/audits/2026-09-03-audit-skill-design/`
