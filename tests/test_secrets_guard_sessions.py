import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

GUARD = Path(__file__).parents[1] / "security/secrets-guard/guard.py"
spec = importlib.util.spec_from_file_location("guard", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

HOOK_TIME = time.mktime(time.strptime("Sun Nov 22 18:31:20 2026", "%a %b %d %H:%M:%S %Y"))
MTIMES = {"claude": HOOK_TIME, "codex": HOOK_TIME, "antigravity": HOOK_TIME}

# Fake `ps -axo pid=,ppid=,lstart=,command=` table; every name and path is made up.
PS = """\
  100     1 Thu Nov 12 14:35:17 2026     /fake/node /fake/bb thread native-hold thr_fakeold0001 --socket /fake/s
  101   100 Thu Nov 12 14:35:18 2026     claude --model fake
  200     1 Mon Nov 23 12:47:42 2026     /fake/node /fake/bb thread native-hold thr_fakenew0002 --socket /fake/s
  201   200 Mon Nov 23 12:47:43 2026     claude --model fake
  300     1 Wed Nov 18 21:39:28 2026     /fake/bridge-worker
  301   300 Wed Nov 18 21:39:29 2026     /fake/.local/bin/claude --output-format stream-json
  400     1 Tue Nov 17 23:31:25 2026     /fake/bin/codex app-server
  401   400 Tue Nov 17 23:31:26 2026     /fake/bin/codex-code-mode-host --listen
  500     1 Sat Nov 21 00:38:18 2026     agy
  600     1 garbled-start-time           claude --model fake
  800     1 Thu Nov 12 09:00:00 2026     node /fake/lib/node_modules/@anthropic-ai/claude-code/cli.js --model fake
  801     1 Thu Nov 12 09:00:01 2026     /fake/bin/node --max-old-space-size=4096 /fake/lib/node_modules/@openai/codex/bin/codex.js
  802     1 Thu Nov 12 09:00:02 2026     /fake/bin/node /fake/bb thread native-hold thr_fakenode0003
  803     1 Thu Nov 12 09:00:03 2026     node --require ./preload.js /fake/lib/node_modules/@anthropic-ai/claude-code/cli.js
  804     1 Thu Nov 12 09:00:04 2026     node --max-old-space-size 4096 --import /fake/hook.mjs /fake/lib/claude.js
  805     1 Mon Nov 23 12:30:00 2026     node --require ./preload.js /fake/lib/node_modules/@anthropic-ai/claude-code/cli.js
  700     1 Mon Nov 23 12:00:00 2026     /bin/zsh -c claude is only mentioned here
"""


class SessionCoverageTests(unittest.TestCase):
    def test_old_new_and_unparseable_sessions(self):
        found = {row[1]: row for row in guard.stale_sessions(PS, MTIMES)}
        self.assertEqual(set(found), {101, 301, 400, 500, 600, 800, 801, 803, 804})
        self.assertEqual(found[101][3:], ("thr_fakeold0001", "started before hook"))
        self.assertEqual(found[301][3], "-")
        self.assertEqual(found[400][0], "codex")
        self.assertEqual(found[500][0], "antigravity")
        self.assertEqual(found[600][4], "unparseable start time")
        self.assertEqual((found[800][0], found[801][0]), ("claude", "codex"))  # node-launched forms
        self.assertEqual((found[803][0], found[804][0]), ("claude", "claude"))  # value-taking node options
        self.assertNotIn(805, found)  # same form, started after the hook
        self.assertNotIn(802, found)  # a node process that is not one of the tools
        self.assertNotIn(201, found)  # started after the hook
        self.assertNotIn(401, found)  # codex-code-mode-host is not a session
        self.assertNotIn(700, found)  # only mentions claude in its arguments

    def test_missing_hook_file_is_listed_not_assumed_covered(self):
        rows = guard.stale_sessions(PS, dict(MTIMES, claude=None))
        self.assertIn((201, "hook file missing"), [(r[1], r[4]) for r in rows])

    def test_check_sessions_exit_status_and_output(self):
        with tempfile.TemporaryDirectory(prefix="secrets-guard-sessions-") as tmp:
            hooks = Path(tmp)
            for name in guard.HOOK_FILES.values():
                (hooks / name).write_text("fake\n")
                os.utime(hooks / name, (HOOK_TIME, HOOK_TIME))
            ps_file = hooks / "ps.txt"
            ps_file.write_text(PS)
            env = {"PATH": "/usr/bin:/bin", "HOME": tmp}
            (hooks / ".agent-hooks").symlink_to(hooks)
            result = subprocess.run([sys.executable, str(GUARD), "--check-sessions", "--ps-file", str(ps_file)],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("9 running session(s)", result.stdout)
            self.assertIn("thr_fakeold0001", result.stdout)
            self.assertIn("bb thread native <thr> --json", result.stdout)
            self.assertIn("bb terminal close <term>", result.stdout)

            ps_file.write_text(PS.split("\n")[2] + "\n" + PS.split("\n")[3] + "\n")  # only the new session
            result = subprocess.run([sys.executable, str(GUARD), "--check-sessions", "--ps-file", str(ps_file)],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
