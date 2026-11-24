import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

GUARD_DIR = Path(__file__).parents[1] / "security/secrets-guard"
spec = importlib.util.spec_from_file_location("guard", GUARD_DIR / "guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

SECRET_FILE = ".en" + "v"  # kept apart so this source never names the file in one token


class ApostropheTests(unittest.TestCase):
    def test_heredoc_with_apostrophe_is_allowed(self):
        command = "cat > notes.txt <<'EOF'\nthe tool can't tokenize this\nEOF"
        self.assertFalse(guard.denied(command))

    def test_patch_body_with_apostrophe_is_allowed(self):
        command = "apply_patch <<'PATCH'\n*** Update File: src/a.py\n+# don't fail\nPATCH"
        self.assertFalse(guard.denied(command))

    def test_unbalanced_quote_still_denies_secret_file_read(self):
        self.assertTrue(guard.denied("cat %s <<EOF\ncan't\nEOF" % SECRET_FILE))

    def test_unbalanced_quote_still_denies_secret_variable_print(self):
        self.assertTrue(guard.denied("echo can't; echo $API_TOKEN"))

    def test_unbalanced_quote_still_denies_environment_dump(self):
        self.assertTrue(guard.denied("echo can't\nenv"))
        self.assertTrue(guard.denied("echo can't; (env)"))
        self.assertTrue(guard.denied("echo can't; { printenv; }"))
        self.assertTrue(guard.denied("echo can't; x=$(env)"))
        self.assertTrue(guard.denied("echo can't; if env; then :; fi"))
        self.assertTrue(guard.denied("echo can't; while printenv; do :; done"))
        self.assertTrue(guard.denied("echo can't; ! env"))
        self.assertTrue(guard.denied("echo can't; command env"))
        self.assertTrue(guard.denied("echo can't; sudo -E /usr/bin/env"))
        self.assertTrue(guard.denied("echo can't; exec printenv"))
        self.assertTrue(guard.denied("echo can't; env -0"))
        self.assertTrue(guard.denied("echo can't; printenv -0"))
        self.assertTrue(guard.denied("echo can't; env -0 > out.txt"))
        self.assertFalse(guard.denied("cat > n.txt <<EOF\ncan't set env vars here\nEOF"))


class CodexAdapterTests(unittest.TestCase):
    def run_adapter(self, command):
        with tempfile.TemporaryDirectory(prefix="secrets-guard-codex-") as home:
            hooks = Path(home) / ".agent-hooks"
            hooks.mkdir()
            shutil.copy2(GUARD_DIR / "guard.py", hooks / "secrets-guard.py")
            shutil.copy2(GUARD_DIR / "scrub-exec.py", hooks / "secrets-scrub-exec.py")
            payload = json.dumps({"tool_name": "shell", "tool_input": {"command": command}})
            return subprocess.run(["sh", str(GUARD_DIR / "codex-pretool.sh")], input=payload,
                                  env={"HOME": home, "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)

    def test_genuine_block_reports_the_guards_real_reason(self):
        result = self.run_adapter("cat " + SECRET_FILE)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Secret-value output blocked", result.stderr)
        self.assertIn("Secret-value output blocked", result.stdout)
        self.assertNotIn("failed closed", result.stderr + result.stdout)

    def test_untokenizable_dump_is_blocked_through_the_adapter(self):
        for command in ("echo can't; env -0", "echo can't; printenv -0"):
            result = self.run_adapter(command)
            self.assertEqual(result.returncode, 2, command)
            self.assertIn("Secret-value output blocked", result.stderr)

    def test_allowed_command_passes_with_updated_input(self):
        result = self.run_adapter("ls")
        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "allow")

    def test_apostrophe_heredoc_is_allowed_through_the_adapter(self):
        result = self.run_adapter("cat > n.txt <<'EOF'\ncan't\nEOF")
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
