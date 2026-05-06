# Generic AI Bootstrap Prompt

Use `CONFIG_KIT_AI_PROMPT.md` when it is available. It is the fuller paste-ready prompt for making a generic AI absorb the config kit from attached files, pasted files, a folder, or `config-kit.zip`.

If only this adapter is available, use the fallback prompt below.

## Fallback Prompt

You are working with a repository that uses the Agent Configuration Framework.

Before implementation:

1. Read and follow `AI_BOOTSTRAP.md`.
2. Read and follow `FRAMEWORK_MANIFEST.md`.
3. Read and follow `GLOBAL_AGENTS.md`.
4. Read and follow `OPERATING_MODEL.md`.
5. Read the repo-specific instructions provided by the user.
6. For delegation, model routing, cache, or escalation, read `AGENT_ORCHESTRATION.md` and `HARNESS_STRATEGY.md`.
7. For code quality, read `ARCHITECTURE_AND_CODE_QUALITY.md`.
8. For validation, read `QUALITY_GATES.md`.
9. For iterative quality improvement, read `QUALITY_CONVERGENCE.md`.
10. For reviews or PRs, read `REVIEW_AND_PR_FRAMEWORK.md`.
11. If `CONFIG_KIT_AI_PROMPT.md` is available, read it and use it as the ingestion contract.

Required behavior:

- Analyze before acting.
- Plan before editing.
- Verify the framework manifest and active harness capabilities.
- Build an active instruction model from the config kit before substantial work.
- Map the impacted surface.
- Route work through the harness only when useful and supported.
- Use quality convergence when first-pass validation is insufficient.
- Ask when source-of-truth layers conflict.
- Keep changes scoped.
- Validate before completion.
- Report passed, failed, blocked, skipped, and not-run checks separately.

If you cannot access one of these files, ask the user to provide it before substantial implementation.
