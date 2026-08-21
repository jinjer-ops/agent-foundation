---
name: github-publish
description: Prepare a repository change, new repository, commit, push, or pull request for sharing on GitHub. Use whenever material could become visible to people outside the current chat, team, or machine.
---

# GitHub publish readiness

## Before modifying Git state

1. Confirm target repository, visibility, remote owner, branch, and intended audience. External publication or a visibility change requires explicit user approval.
2. Inspect `git status --short`, the diff, tracked files, `.gitignore`, and existing project conventions.
3. Preserve unrelated working-tree changes. Stage only the intended paths.

## Rewrite for an unfamiliar reader

- Remove organization-specific names, customer data, personal data, absolute local paths, internal URLs, credentials, exports, and chat-dependent wording.
- Define unavoidable abbreviations at first use.
- Make failure messages tell the reader what safe action to take next.
- Name the owner and trigger for each operational procedure.
- Keep a single source of truth; replace duplicate explanations with links.
- Do not describe planned work as complete.

## Mechanical checks

Run the checks appropriate to the repository and record their results:

1. `git diff --check`
2. A targeted secret scan for keys, tokens, private keys, connection strings, and exported credentials.
3. A targeted search for local user paths and organization-only identifiers.
4. The project's formatter, lint, test, build, or documented verification command.
5. A fresh-clone or first-time-reader check for reusable projects: README setup, license, contribution path, and minimal verification must be understandable.

Correct findings and repeat affected checks. Do not bypass a failing check without documenting the reason and remaining risk.

## Commit and handoff

- Use one purpose per commit. Describe what changed and why.
- Prefer a branch and pull request over a direct default-branch push.
- In the handoff include changed paths, checks run and their results, the Git remote/branch, and anything intentionally not verified.
