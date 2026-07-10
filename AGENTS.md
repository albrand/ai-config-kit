# Agent Configuration Kit

This repository is the canonical source for the framework. Read
`AI_BOOTSTRAP.md` and `FRAMEWORK_MANIFEST.md` for the smallest applicable
profile, then keep edits scoped to the requested skillset or adapter.

- Preserve source/install parity for mirrored Codex and Claude entrypoints.
- Run the router `--check`, syntax checks for changed scripts, and
  `git diff --check` before claiming completion.
- Do not place secrets, machine-specific credentials, or private operational
  details in tracked framework files.
- Treat `adapters/AGENTS.md` as a copyable template, not as this repository's
  governing instructions.
