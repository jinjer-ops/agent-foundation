---
title: Audit skill design review report
date: 2026-09-03
scope: focused
result: revised
---

# Audit skill design review report

## Result

The existing audit skill had a sound backbone: choose a depth, write a manifest, investigate
through independent lenses, challenge proposed findings, report residual risk, and keep portable
learnings. The revised skill keeps that backbone. A zero-based design adds the controls needed to
turn a careful review into an auditable decision: an explicit audit contract, a claim-to-proof
trace, evidence labels, mutation binding, finding classification, and post-remediation evidence.

A source-adoption review was used as a bounded comparison case. Its manifest, source-by-source
decisions, and safety boundary were already consistent with the existing skill. The revised
version makes its useful distinctions explicit and reusable; it does not change that review's
conclusions.

## Comparison

| Concern | Previous skill | Revised skill | Reason |
| --- | --- | --- | --- |
| Audit start | Required a useful manifest | Defines target baseline, acceptance criteria, invariants, authority, evidence plan, and decision triggers | A finding cannot be assessed without a claim and boundary |
| Depth | Focused or five-lens full review | Retains both and requires a reason for omitted lenses | Prevents ritual coverage while retaining risk-based review |
| Evidence | Required a path, command, or observation | Adds requirement → control → execution path → proof and observed/static/assumed labels | Avoids treating code inspection or assumptions as runtime proof |
| State changes | Listed destructive-operation checks | Separates read-only audit from approved remediation and binds preview, input/version, rollback, and result evidence | An audit must not silently become an apply operation |
| Domain checks | One universal core-check list | Selects data, automation, runtime, or release checks only when applicable | Reduces irrelevant checklists without losing high-risk controls |
| Findings | Required attempts to disprove | Adds a definition of a confirmed issue and a place for non-defect uncertainty | Keeps reports actionable and avoids invented severity |
| Closure | Required remediation and residual risk | Requires post-fix rerun and residual-risk owner and review trigger | Distinguishes a proposed fix from a verified fix |

## Findings and remediation

### A-01 — Medium — audit contract and proof status were implicit

**Condition and impact:** The previous manifest asked for targets and lens questions, but did not
require an acceptance criterion, invariant, evidence plan, or distinction between observed and
static evidence. Different reviewers could call the same implementation "verified" at materially
different proof levels.

**Evidence:** `skills/audit/SKILL.md` required evidence but had no claim-to-control-to-proof trace
or evidence labels. The source-adoption review had to supply those decisions manually in its own
manifest and report.

**Root cause:** The skill described review phases but not the audit contract that makes their
results comparable.

**Remediation:** Add an audit-contract section and evidence labels; require the trace for important
claims.

**Verification:** The revised skill requires all contract fields before investigation and names the
three evidence states.

**Residual risk, owner, and review trigger:** Foundation maintainers own the remaining judgment
over sufficient evidence. Review this rule after a real audit cannot classify a material claim
with the supplied categories.

### A-02 — Medium — remediation could be confused with audit authority

**Condition and impact:** The prior skill required before-images for destructive mutation but did
not explicitly separate a read-only audit from a later authorized remediation. A reviewer could
infer that discovering a defect grants authority to apply a fix.

**Evidence:** `AGENTS.md` already requires approval and operation classification, while the prior
skill did not connect that boundary to its remediation phase.

**Root cause:** The skill assumed the global safety contract rather than restating the audit-specific
handoff from diagnosis to mutation.

**Remediation:** Require a later preview, approval, exact input or version, rollback, and result
evidence before a state-changing remedy; otherwise leave the system unchanged.

**Verification:** The revised skill states this boundary in both the contract and remediation
sections.

**Residual risk, owner, and review trigger:** Foundation maintainers own the fact that the skill
cannot enforce platform permissions. Review after a case where approval could not be bound to the
exact applied input.

## Scope limits

This was a focused review of documentation and skill behavior. It did not execute a production
audit, change a live system, or perform a behavioral study with independent operators. The revised
skill is syntax-validated and its repository layout is verified separately.
