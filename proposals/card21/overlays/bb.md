## bb adapter

- bb appends this data-dir file to every provider-backed thread. Keep it provider-neutral; workspace-specific rules belong in the workspace `.bb/AGENTS.md`.
- Before login handoff, use `verified-qa-e2e` and its deterministic `manual_login` gate. Enumerate instances, reuse the thread-owned one (or create exactly one), disclose shared-window tab count/title before takeover, never type credentials, then release and verify auth on that same instance. Close only duplicates owned by this thread.
- Hermes defects block merges. Hermes runs independently; use `bb fleet validate` with bounded evidence. Fix transport faults instead of asking Hermes to mount a project source.
- Never pass a `--model` override to `acp-hermes-agent`.
- Before child work, route with `bb fleet route` and use exactly its provider/model/reasoning. Keep one writer per worktree; stop on collisions. Never quit or replace the running bb app.
