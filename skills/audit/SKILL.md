---
name: audit
description: Perform an evidence-backed, adversarial review of a design, code change, automation, data operation, or handoff. Use for production-impacting work, security or authorization changes, irreversible operations, multi-component changes, and before a consequential release or transfer.
---

# Evidence-backed audit

## Choose the depth

- **Focused review**: use correctness plus the one or two most relevant lenses when scope and blast radius are small.
- **Full review**: use all five lenses for production mutation, authorization, secrets, finance, irreversible actions, or multi-component changes.
- **Do not audit by ritual**. State what is in scope, what is not, and why the chosen depth is sufficient.

## Phase 0 — audit manifest

Create `docs/audits/<yyyy-mm-dd>-<topic>/MANIFEST.md` (or an equivalent project location) before investigating. Record:

1. Target files, deployed version or base commit.
2. Intended outcome and measurable acceptance criteria.
3. Execution environment, data classification, authority boundary, and prohibited operations.
4. Known facts and measurements that need not be rediscovered.
5. Lens-specific questions, evidence locations, and unresolved decisions.

## Phase 1 — independent detection

Review each relevant lens independently. For a full review, keep lenses separate until their initial findings are recorded.

| Lens | Question |
| --- | --- |
| Correctness | Do inputs, logic, state changes, and outputs meet the stated contract? |
| Environment | Does this work in the actual OS, runtime, encoding, dependency, and scale conditions? |
| Security | Are trust boundaries, permissions, secrets, and untrusted inputs safe? |
| Operability | Can failures, partial success, retries, rollback, monitoring, and ownership be handled safely? |
| Succession | Is the source of truth clear and can another person operate this without hidden knowledge? |

Rules of evidence:

- Support each finding with a file and line, a reproducible command, or an observed result.
- Use counts, aggregates, and bounded samples for large datasets. Save necessary raw evidence to the audit directory, not the chat.
- Stop exploring a hypothesis once the smallest relevant evidence falsifies it.
- Consolidate findings with the same root cause. Do not invent findings to fill a quota.

## Phase 2 — disprove the findings

For every proposed issue, attempt to show that it is harmless or already controlled. Confirm:

1. The stated input-to-result path exists in code and configuration.
2. The reproduction is possible under the stated environment and authority.
3. Severity matches credible impact and blast radius.
4. The proposed remediation addresses the root cause without weakening another guard.

## Phase 3 — report and learn

Write `REPORT.md` with severity, evidence, impact, remediation, verification, residual risk, and out-of-scope items. Never use an unqualified “no issues found”; state the inspected scope and remaining uncertainty.

For new recurring failure modes, add an anonymized check to `LEARNINGS.md` using this form:

`Condition → failure mode → detection → safe default → evidence date`

## Core checks

- Verify character encoding, shell/runtime version, locale, paths, line endings, and real execution target.
- Check unique keys before using them as maps or merge keys.
- Ensure API success responses and partial-success results are inspected, not merely received.
- Ensure “preview approved” binds to the exact inputs later applied.
- Preserve before-images and write audit evidence before destructive mutation.
- Verify every execution path has the same required safety controls.
- Check that unknown enum values, parse failures, missing baselines, and empty limits do not produce fail-open or all-record behavior.
