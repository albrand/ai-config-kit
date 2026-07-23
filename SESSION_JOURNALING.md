# Session Journaling

Session journals are local execution logs for repository work. They make long-running or interrupted work resumable.

Journals should not contain secrets, credentials, sensitive data, private URLs, or closed-scope facts that do not belong in local working notes.

## Journal Challenge Rule

Journals are a fallback training base for future work, not authority. On resume
or when deriving durable lessons, challenge journal entries for drift, hidden
confounders, causal overfitting, and current-task relevance. Re-open current
source files, tests, runtime evidence, boards, and docs before relying on a
journal conclusion.

## When To Use Journals

Use a journal when:

- The repository has adopted journaling.
- The task inspects or changes code.
- The task spans multiple steps or tools.
- The task may be resumed later.
- The work touches architecture, security, data, release, or broad validation.

Skip journaling for:

- Tiny questions.
- One-line command output.
- Purely conversational answers.
- Work outside a repo that has not adopted journals.

## Journal Location

Recommended default:

```text
journals/
```

The repo decides whether journals are:

- Local-only and ignored by version control.
- Versioned project notes.
- Stored in an external system.

If local-only, add the journal path to ignore rules.

## Durable Remote Journals (Hermes)

For long work that runs on a remote host (e.g. the Hermes provider router on a
Tailscale-only VPS), keep a **durable** journal on that host so the work is
resumable across cmux/Hermes orchestration. This is the remote counterpart to
the local protocol above.

- Tool and contract: `skillsets/cmux-hermes-orchestration/scripts/hermes-work-journal.py`
  and `skillsets/cmux-hermes-orchestration/references/HERMES_WORK_JOURNALS.md`.
- Per-task directories under `HERMES_WORK_JOURNAL_DIR` (default
  `/var/lib/hermes/work-journals`): atomic JSON state plus an append-only
  markdown log. Directories `0700`, files `0600`, `fcntl`-locked.
- Commands: `start | append | heartbeat | checkpoint | resume | close | show | list`. There
  is **no delete**; close to finish.
- Same no-secrets rule: never paste credentials, tokens, private URLs, or
  closed-scope facts. The tool never stores environment values.
- On resume, re-open current source/tests/runtime evidence before trusting a
  prior journal conclusion — journals are a fallback trace, not authority.

## Journal Lifecycle

1. Start.

Record:

- Timestamp.
- Goal.
- Current repo path.
- Applicable instruction files.
- Initial assumptions.

2. Append after meaningful actions.

Entry types:

- `action`: command run, files inspected, files changed.
- `decision`: chosen approach, rejected alternative, scope boundary.
- `issue`: blocker, failing check, unclear source of truth.
- `result`: validation outcome, completed slice, residual risk.

3. Resume.

Before continuing:

- Read the current journal.
- Inspect current repository state.
- Reopen files on the active path.
- Do not rely on journal summary alone.

4. Close.

Record:

- Final state.
- Files or areas changed.
- Validation run.
- Blocked or skipped checks.
- Residual risk.
- Next step.

## Entry Format

Use a short, factual format:

```md
## <timestamp> - <type>

<one to three sentences>

Files:
- <path>

Validation:
- <command>: <passed|failed|blocked|skipped>
```

## What To Record

Record:

- Source-of-truth docs read.
- Important files inspected.
- Commands and outcomes.
- Why an approach was chosen.
- Validation results.
- Blockers and residual risk.
- Current workflow phase.
- Pending breakpoint or user decision.
- Next exact step for resumption.

Do not record:

- Secrets or credentials.
- Sensitive values.
- Large command output dumps.
- Private URLs unless local policy allows them.
- Speculative notes that could be mistaken for facts.

## Journal Close-Out Template

```md
## Close-Out

Summary:
- <what changed or was learned>

Workflow state:
- Phase: <current or completed phase>
- Pending breakpoint: <decision needed or "None">
- Next step: <exact resume action or "No next action">

Validation:
- <command>: <status>

Residual risk:
- <risk or "None identified">

Next:
- <next action or "No next action">
```

## Repo Adoption Checklist

- [ ] Decide whether journals are local-only or versioned.
- [ ] Add ignore rules if local-only.
- [ ] Add start, append, status, and close commands if tooling exists.
- [ ] Document required entry types.
- [ ] Include journal handling in repo instructions.
