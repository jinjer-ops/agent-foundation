---
title: Audit skill design review manifest
date: 2026-09-03
scope: focused
---

# Audit skill design review manifest

## Target and baseline

The target is `skills/audit/SKILL.md` at `54a8ec9`, plus its relationship to
`AGENTS.md`, `CONTRIBUTING.md`, and `skills/audit/LEARNINGS.md`. The learning log is not changed
by this review because no newly confirmed recurring failure mode is in scope.

## Intended result and acceptance criteria

Produce a portable audit skill that preserves the useful evidence-first workflow while making an
audit's scope, proof standard, mutation boundary, remediation verification, and residual risk
explicit. It must not prescribe organization-specific tools, thresholds, approvals, or deployment
methods. Its instructions must remain short enough to load as one skill and pass the repository's
layout verification.

## Boundary

This is a read-first documentation and skill-design review. It may create a separate feature
branch and a pull request, but it does not authorize any live-system mutation. The repository is
public; no local paths, names, credentials, customer data, or incident details belong in output.

## Evidence plan

| Lens | Question | Evidence |
| --- | --- | --- |
| Correctness | Does the skill route an audit from claim to verifiable result? | Current skill text and proposed instructions |
| Safety | Does it preserve approval and fail-closed boundaries? | `AGENTS.md` and the proposed mutation controls |
| Operability | Can a reviewer distinguish an observation, an issue, and a verified remediation? | Report requirements and current source-adoption audit |
| Succession | Can another maintainer use the skill without local context? | `README.md`, `CONTRIBUTING.md`, skill wording |
| Environment | Is a special environment check needed for this documentation-only change? | Omitted: no runtime, deployment, or data operation is in scope |

## Known facts and decisions

The current skill already requires an audit manifest, independent lenses, evidence, attempts to
disprove findings, a report, and anonymized learning. The review compares those controls with a
zero-based audit design; it does not infer authorship or evaluate any individual agent.
