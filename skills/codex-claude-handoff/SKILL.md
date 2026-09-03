---
name: codex-claude-handoff
description: Prepare an evidence-backed implementation brief for Claude Code and review its handoff when Codex is the design authority and Claude is the scoped coding executor. Use for work that must preserve an existing worktree and separate architecture decisions from implementation.
---

# Codex–Claude Handoff

Use this workflow when Codex owns analysis, scope, acceptance criteria, and final review while Claude Code carries out the coding.

## Before handing off

1. Inspect the worktree and identify all existing user/Codex changes that Claude must preserve.
2. Create or update `docs/codex-briefs/ACTIVE.md` in the target repository. It must state: goal, non-goals, decided behavior, unresolved decisions, allowed paths, forbidden operations, ordered work, acceptance tests, exact validation target, and a factual handback template.
3. Add a short project-level guard to `CLAUDE.md` if one is absent: Claude reads the active brief first, preserves existing changes, stays inside allowed paths, and does not perform production mutation.
4. Provide a short Claude command or prompt that references the brief instead of copying audit evidence or large histories into the chat.

## While Claude works

- Keep architectural choices in the brief; do not ask Claude to rediscover them.
- Require it to stop with `BLOCKED_FOR_CODEX` where a decision exceeds the brief.
- Ask only for targeted tests and the factual handback record. Do not request a parallel audit or broad codebase exploration unless it is explicitly necessary.

## On handback

1. Read Claude's handback record, `git diff`, and test output.
2. Check that modified paths are within scope and that existing work was preserved.
3. Independently decide whether the acceptance criteria are met; implementation completion is not acceptance.
4. Issue a new brief for remaining decisions rather than having Claude infer them.
