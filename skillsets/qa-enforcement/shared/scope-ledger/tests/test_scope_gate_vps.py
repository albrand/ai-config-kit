import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
FIXTURES = HERE / "fixtures"


def load_scope_gate():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("scope_gate", SCRIPTS / "scope-gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestScopeGateVpsCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sg = load_scope_gate()

    def test_help_probe_gaps_vps_shaped_bb(self):
        fixture = (FIXTURES / "vps-bb-help-top.txt").read_text()
        carries = {
            "settings writing correct",
            "settings writing transcribe",
            "thread tell",
        }
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-bb"
            fake.write_text(
                f"""#!{{py}}
import sys
TOP = {fixture!r}
PROBE = {sorted(self.sg.HELP_PROBE_VERBS)!r}
if len(sys.argv) >= 2 and sys.argv[1] == '--help' and len(sys.argv) == 2:
    print(TOP)
    sys.exit(0)
if len(sys.argv) >= 3 and sys.argv[-1] == '--help':
    cmd = ' '.join(sys.argv[1:-1])
    if cmd in PROBE:
        sys.stderr.write(f"error: unknown command {{cmd.split()[0]!r}}\\n")
        sys.exit(1)
    if cmd == 'settings writing correct':
        print('Usage: bb settings writing correct [options] <text>\\nOptions:\\n  --context <text>\\n')
        sys.exit(0)
    if cmd == 'settings writing transcribe':
        print('Usage: bb settings writing transcribe [options] <audio-file>\\nOptions:\\n  --context <text>\\n')
        sys.exit(0)
sys.exit(1)
""".replace("{py}", sys.executable)
            )
            fake.chmod(0o755)
            gaps, absent, errors = self.sg.help_probe_gaps(carries, bb=str(fake))
        self.assertEqual(errors, [])
        self.assertEqual(gaps, [])
        self.assertEqual(
            set(absent),
            {
                "automation create",
                "automation update",
                "instructions set",
                "notify send",
                "thread interactions answer",
                "thread interactions respond",
                "thread queue create",
            },
        )

    def test_help_probe_timeout_is_fail_not_absent(self):
        carries = self.sg.HELP_PROBE_VERBS - {"automation create"}

        def fake_run(cmd, **kwargs):
            if cmd[1:4] == ["automation", "create", "--help"]:
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 60))
            return subprocess.CompletedProcess(cmd, 1, "", "error: unknown command 'automation'\n")

        with mock.patch.object(subprocess, "run", side_effect=fake_run):
            gaps, absent, errors = self.sg.help_probe_gaps(carries, bb="bb")
        self.assertEqual(gaps, [])
        self.assertNotIn("automation create", absent)
        self.assertTrue(any("automation create" in e and "help probe timed out" in e for e in errors))

    def test_help_probe_gaps_shared_budget_wall_clock(self):
        carries = self.sg.HELP_PROBE_VERBS - {"automation create"}
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "slow-help-bb"
            fake.write_text(
                f"""#!{{py}}
import sys, time
if len(sys.argv) >= 4 and sys.argv[1:4] == ["automation", "create", "--help"]:
    time.sleep(16)
    sys.exit(0)
sys.stderr.write("error: unknown command 'probe'\\n")
sys.exit(1)
""".replace("{py}", sys.executable)
            )
            fake.chmod(0o755)
            t0 = time.monotonic()
            gaps, absent, errors = self.sg.help_probe_gaps(carries, bb=str(fake))
            elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 12.0, f"help_probe_gaps took {elapsed:.2f}s")
        self.assertNotIn("automation create", absent)
        self.assertTrue(
            any("automation create" in e and "help probe timed out" in e for e in errors),
            errors,
        )

    def _plugin_list_mock(self, stdout):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
        with mock.patch.object(subprocess, "run", return_value=proc):
            return self.sg.plugin_tools_from_bb("bb")

    def test_plugin_tools_empty_listing_ok_error_fails(self):
        bad = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="Error: HTTP 401: Unauthorized")
        for empty in ("[]", '{"plugins": []}'):
            with self.subTest(empty=empty):
                tools, err = self._plugin_list_mock(empty)
                self.assertIsNone(err, err)
                self.assertEqual(tools, {})
        with mock.patch.object(subprocess, "run", return_value=bad):
            tools, err = self.sg.plugin_tools_from_bb("bb")
        self.assertIsNone(tools)
        self.assertIn("401", err)

    def test_plugin_tools_error_object_in_stdout_fails(self):
        tools, err = self._plugin_list_mock('{"error":"HTTP 401: Unauthorized"}')
        self.assertIsNone(tools)
        self.assertIn("401", err)

    def test_plugin_tools_vps_error_envelope_fails(self):
        stdout = json.dumps(
            {"ok": False, "error": {"code": "http_401", "message": "HTTP 401: Unauthorized"}}
        )
        tools, err = self._plugin_list_mock(stdout)
        self.assertIsNone(tools)
        self.assertIn("401", err)

    def test_plugin_tools_empty_object_listing_fails(self):
        tools, err = self._plugin_list_mock("{}")
        self.assertIsNone(tools)
        self.assertIn("empty object", err)

    def test_plugin_tools_null_listing_fails_selftest_registry_check(self):
        tools, err = self._plugin_list_mock("null")
        self.assertIsNone(tools)
        self.assertIsNotNone(err)
        self.assertIn("invalid plugin listing", err)

    def test_plugin_tools_listing_with_registered_tool_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo-plugin"
            root.mkdir()
            (root / "register.ts").write_text('bb.agents.registerTool({name: "AskUserQuestion"});')
            listing = json.dumps(
                [{"id": "demo-plugin", "enabled": True, "rootDir": str(root)}]
            )
            tools, err = self._plugin_list_mock(listing)
        self.assertIsNone(err, err)
        self.assertIn("AskUserQuestion", tools)

    def test_loose_tools_empty_registry_passes(self):
        self.assertEqual(self.sg.loose_tools({}), [])

    def test_settings_writing_correct_gated_without_serves(self):
        base = json.loads((FIXTURES / "scope-ledger.json").read_text())
        thread = base["thread_id"]
        with tempfile.TemporaryDirectory() as tmp:
            self.sg.LEDGER_DIR = tmp
            self.sg.DECISIONS = os.path.join(tmp, "decisions.jsonl")
            self.sg.write_ledger(thread, base)
            payload = {
                "tool_name": "Bash",
                "tool_input": {"command": 'bb settings writing correct "fix teh typo"'},
            }
            self.assertEqual(self.sg.hook(json.dumps(payload), thread), 2)
            payload["tool_input"]["command"] = 'bb settings writing correct "serves: P1 fix teh typo"'
            self.assertEqual(self.sg.hook(json.dumps(payload), thread), 0)


if __name__ == "__main__":
    unittest.main()
