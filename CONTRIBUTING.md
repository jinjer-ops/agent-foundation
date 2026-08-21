# Contributing

## What belongs here

Submit only rules and skills that are portable across organizations and LLM products. A contribution must not contain:

- organization, customer, or employee information;
- credentials, tokens, internal URLs, local user paths, exports, or screenshots;
- a permission grant that only makes sense for one machine or service;
- project-specific implementation detail that belongs in a repository-local instruction file.

## Change process

1. Explain the user problem and why the rule or workflow is reusable.
2. Keep the baseline short; put detailed repeatable procedures in a skill.
3. Add acceptance criteria and a verification method.
4. Run `powershell -ExecutionPolicy Bypass -File scripts/verify-layout.ps1`.
5. Have a first-time reader check the instructions before merge.

## Learning from incidents

Add anonymous, generalized failure modes to `skills/audit/LEARNINGS.md`. Describe the condition, failure, detection, and safe default—not the organization or incident record.
