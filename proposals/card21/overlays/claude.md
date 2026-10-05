## Claude Code adapter

bb appends the provider-neutral baseline in `~/.bb/AGENTS.md` to each provider-backed thread. Apply this Claude-specific adapter with active repository instructions; system and current user instructions remain higher priority.

- Keep architecture, security, authentication, data-loss, release, and final-review work on Claude. Do not route bounded or bulk execution to Claude; those tasks use the verified Codex route.
- Hermes PR reviews run on Codex through `bb fleet validate`; Hermes remains independent and must never receive project source.
