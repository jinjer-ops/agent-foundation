---
name: project-handover
description: Create, repair, or verify a durable handover for work that spans sessions, people, or coding agents. Use when beginning a non-trivial project, pausing work, delegating implementation, or completing a change that another person must operate.
---

# Durable project handover

Maintain `docs/HANDOVER.md` unless the repository names an equivalent canonical location.

## Required content

1. **Purpose and boundary**: objective, users, non-goals, and acceptance criteria.
2. **Current state**: completed work, in-progress work, known defects, and a dated status.
3. **How to continue**: ordered next actions with exact paths and commands.
4. **Decisions**: the decision, alternatives rejected, rationale, and owner where relevant.
5. **Environment**: prerequisites, safe access setup references, and commands to verify the environment. Never include secret values.
6. **Verification and operations**: tests run, expected results, monitoring, rollback, and remaining risks.
7. **Artifacts**: links to source-of-truth specifications, inputs, generated outputs, and evidence.

## Quality bar

- A new maintainer should be able to resume safely without chat history.
- Separate observed facts from assumptions and decisions.
- Update the handover in the same change that changes project state.
- Before declaring it current, test every command documented as a verification command or explicitly mark it untested.
