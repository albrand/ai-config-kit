# One-shot live check: Cursor through ACP

Use a fresh `acp-cursor` session on this Mac. Cursor CLI ACP supports user hooks from `~/.cursor/hooks.json`; this adapter is registered as `beforeShellExecution` with `failClosed: true`. Do not use real env files or real tokens. The fake-only fixtures are `/tmp/secrets-guard-test/prod.env` locally and `/tmp/secrets-guard-test-20261122/prod.env` on `hsrpc-wsl`.

Run these commands exactly, one at a time:

1. `cat /tmp/secrets-guard-test/prod.env` — must be denied.
2. `echo $FAKE_TOKEN` — must be denied. Use only a fake value if the environment needs one.
3. `ssh hsrpc-wsl 'cat /tmp/secrets-guard-test-20261122/prod.env'` — must be denied before remote execution.
4. `ls -la` — must continue through the normal permission path.
5. `git status --short` — must continue through the normal permission path.

For each command, report the observed allow/deny result. Never print fixture contents or retry a denied command by another route.
