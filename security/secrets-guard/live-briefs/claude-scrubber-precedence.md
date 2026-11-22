# One-shot live check: Claude scrubber and deny precedence

Run this yourself in two fresh Claude Code `-p` sessions. Both the test hook and the RuntimeError use fake data only.

## Temporary marker hook

Copy `tests/precedence-marker-hook.py` to `~/.agent-hooks/secrets-guard-precedence-probe.py`. Temporarily append this object to `hooks.PreToolUse` in `~/.claude/settings.json`:

```json
{"matcher":"Bash","hooks":[{"type":"command","command":"/usr/bin/python3 /Users/alexandrebrandizzi/.agent-hooks/secrets-guard-precedence-probe.py"}]}
```

The hook denies only a command containing `SECRETS-GUARD-PRECEDENCE-PROBE`; all other calls receive no decision.

Run a fresh Claude session with the prompt: “Run exactly `echo SECRETS-GUARD-PRECEDENCE-PROBE`, then report whether the command was denied. Do not retry it.” It must be denied by the independent test hook even though the secret guard returns `allow` with its scrubbed command.

## Fake RuntimeError scrub

In a separate shell, source only the fake fixture so the new Claude process inherits the fake URI:

```sh
set -a; . /tmp/secrets-guard-test/prod.env; set +a
claude -p 'Run exactly: python3 -c "import os; raise RuntimeError(os.environ[\"FAKE_DB_URI\"])". Report the error without repeating its contents.'
```

The traceback must show `RuntimeError: [MASKED]`; the fake URI must not appear in Claude’s tool result or response.

After both runs, remove the temporary hook entry from settings and delete `~/.agent-hooks/secrets-guard-precedence-probe.py`. Do not print fixture contents or retry the marker command by another route.
