# One-shot fresh-session check: Claude guard and scrubber

Run this in one fresh Claude Code session after confirming the fake fixture at `/tmp/secrets-guard-test/prod.env` contains only fake values. It checks the independent-hook deny precedence, an allowed command, and stderr scrubbing for values sourced inside the command.

## Temporary marker hook

Copy `tests/precedence-marker-hook.py` to `~/.agent-hooks/secrets-guard-precedence-probe.py`. Temporarily add this object to `hooks.PreToolUse` in `~/.claude/settings.json`:

```json
{"matcher":"Bash","hooks":[{"type":"command","command":"/usr/bin/python3 /Users/alexandrebrandizzi/.agent-hooks/secrets-guard-precedence-probe.py"}]}
```

In the fresh session, ask Claude to run these three rows exactly once, in order, and report each command's result without repeating any error contents:

| Row | Command | Expected result |
| --- | --- | --- |
| Precedence | `echo SECRETS-GUARD-PRECEDENCE-PROBE` | Denied by the independent test hook, even though the secret guard returns `allow` with a wrapped command. |
| Normal work | `ls` | Allowed. |
| Sourced-file error | `set -a; . /tmp/secrets-guard-test/prod.env; set +a; python3 -c "import os; raise RuntimeError(os.environ['FAKE_DB_URI'])"` | Command fails with a traceback, but Claude's tool result shows `RuntimeError: [MASKED]`; the fake URI appears nowhere in the tool result or response. |

After the session, remove the temporary hook entry from settings and delete `~/.agent-hooks/secrets-guard-precedence-probe.py`. Do not print fixture contents, repeat the marker command through another route, or retry a denied command.
