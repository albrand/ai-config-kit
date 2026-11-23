import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / "security/secrets-guard/install.py"
SOURCE = ROOT / "security/secrets-guard"
FAKE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def codex_hash(command, matcher, timeout=600):
    identity = {
        "event_name": "pre_tool_use",
        "hooks": [{"type": "command", "command": command, "timeout": timeout, "async": False}],
        "matcher": matcher,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def seed_home(home, codex_hooks, config_text="", gemini_hooks=None):
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    (home / ".gemini/config").mkdir(parents=True)
    (home / ".cursor").mkdir()
    (home / ".claude/settings.json").write_text(json.dumps({"hooks": {"PreToolUse": []}}))
    (home / ".codex/hooks.json").write_text(json.dumps(codex_hooks))
    (home / ".codex/config.toml").write_text(config_text)
    (home / ".gemini/config/hooks.json").write_text(json.dumps(gemini_hooks or {}) + "\n")
    (home / ".cursor/hooks.json").write_text("{}\n")


class SecretsGuardInstallTests(unittest.TestCase):
    def test_installer_copies_adapters_registers_hooks_and_trusts_only_guard(self):
        with tempfile.TemporaryDirectory(prefix="secrets-guard-install-") as tmp:
            home = Path(tmp)
            old = {"matcher": "run_command", "hooks": [{"type": "command", "command": "/usr/bin/python3 /old/.agent-hooks/gemini-pretool.py", "timeout": 5}]}
            other = {"matcher": "run_command", "hooks": [{"type": "command", "command": "/bin/true"}]}
            seed_home(home,{"hooks": {"PreToolUse": []}},"[profiles.default]\nmodel = 'test'\n",
                      {"secrets-guard": {"BeforeTool": [old]}, "legacy-copy": {"BeforeTool": [old]},
                       "unrelated": {"BeforeTool": [other]}})
            env = {"HOME":str(home),"PATH":FAKE_PATH,"TMPDIR":str(home)}
            result = subprocess.run([sys.executable, str(INSTALLER)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertRegex(result.stdout, r"running session|started after their guard hook")

            installed = home / ".agent-hooks"
            for source_name, installed_name in (
                ("guard.py", "secrets-guard.py"),
                ("scrub-exec.py", "secrets-scrub-exec.py"),
                ("secret-names", "secret-names"),
                ("claude-pretool.sh", "claude-pretool.sh"),
                ("codex-pretool.sh", "codex-pretool.sh"),
                ("gemini-pretool.py", "gemini-pretool.py"),
                ("cursor-pretool.py", "cursor-pretool.py"),
            ):
                self.assertEqual((SOURCE / source_name).read_bytes(), (installed / installed_name).read_bytes())

            claude = json.loads((home / ".claude/settings.json").read_text())
            self.assertIn("claude-pretool.sh", claude["hooks"]["PreToolUse"][-1]["hooks"][0]["command"])
            codex = json.loads((home / ".codex/hooks.json").read_text())
            entry = codex["hooks"]["PreToolUse"][-1]
            self.assertEqual(entry["matcher"], "Bash")
            command = entry["hooks"][0]["command"]
            self.assertIn("codex-pretool.sh", command)
            config = tomllib.loads((home / ".codex/config.toml").read_text())
            hooks_path = str(home / ".codex/hooks.json")
            state_key = f"{hooks_path}:pre_tool_use:0:0"
            trust = config["hooks"]["state"][state_key]
            self.assertEqual(trust["trusted_hash"], codex_hash(command, "Bash"))
            self.assertTrue(trust["enabled"])

            gemini = json.loads((home / ".gemini/config/hooks.json").read_text())
            # Antigravity fires PreToolUse, never BeforeTool; an old registration is migrated.
            entry = gemini["secrets-guard"]["PreToolUse"][0]
            self.assertEqual(entry["matcher"], "run_command")
            self.assertIn(str(installed / "gemini-pretool.py"), entry["hooks"][0]["command"])
            self.assertNotIn("BeforeTool", gemini["secrets-guard"])
            self.assertNotIn("legacy-copy", gemini)
            self.assertEqual(gemini["unrelated"], {"BeforeTool": [other]})
            cursor = json.loads((home / ".cursor/hooks.json").read_text())
            cursor_hook = cursor["hooks"]["beforeShellExecution"][-1]
            self.assertTrue(cursor_hook["failClosed"])
            self.assertIn("cursor-pretool.py", cursor_hook["command"])
            self.assertEqual(
                (SOURCE / "opencode-plugin.js").read_bytes(),
                (home / ".config/opencode/plugin/secrets-guard.js").read_bytes(),
            )

            for path in (
                home / ".claude/settings.json.*.bak",
                home / ".codex/hooks.json.*.bak",
                home / ".codex/config.toml.*.bak",
                home / ".gemini/config/hooks.json.*.bak",
                home / ".cursor/hooks.json.*.bak",
            ):
                self.assertTrue(list(path.parent.glob(path.name)), str(path))

    def test_reinstall_preserves_other_codex_hook_indexes_and_trust(self):
        with tempfile.TemporaryDirectory(prefix="secrets-guard-reinstall-") as tmp:
            home=Path(tmp)
            old_guard=f"/bin/sh {home}/.agent-hooks/codex-pretool.sh"
            user_hook="/bin/sh /tmp/user-hook.sh"
            codex_hooks={"hooks":{"PreToolUse":[
                {"matcher":"Bash","hooks":[{"type":"command","command":old_guard}]},
                {"matcher":"Bash","hooks":[{"type":"command","command":user_hook,"timeout":7}]},
            ]}}
            hooks_path=str(home/".codex/hooks.json")
            old_guard_key=f"{hooks_path}:pre_tool_use:0:0"
            user_hook_key=f"{hooks_path}:pre_tool_use:1:0"
            user_hook_hash=codex_hash(user_hook,"Bash",timeout=7)
            config=(f'[hooks.state.{json.dumps(old_guard_key)}]\ntrusted_hash = "old-guard-hash"\nenabled = true\n\n'
                    f'[hooks.state.{json.dumps(user_hook_key)}]\ntrusted_hash = "{user_hook_hash}"\nenabled = true\n')
            seed_home(home,codex_hooks,config)
            env={"HOME":str(home),"PATH":FAKE_PATH,"TMPDIR":str(home)}
            result=subprocess.run([sys.executable,str(INSTALLER)],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

            updated=json.loads((home/".codex/hooks.json").read_text())["hooks"]["PreToolUse"]
            self.assertEqual(len(updated),2)
            self.assertIn("codex-pretool.sh",updated[0]["hooks"][0]["command"])
            self.assertEqual(updated[1]["hooks"][0]["command"],user_hook)
            config=tomllib.loads((home/".codex/config.toml").read_text())
            self.assertEqual(config["hooks"]["state"][user_hook_key]["trusted_hash"],user_hook_hash)
            self.assertTrue(config["hooks"]["state"][user_hook_key]["enabled"])
            self.assertEqual(config["hooks"]["state"][old_guard_key]["trusted_hash"],codex_hash(updated[0]["hooks"][0]["command"],"Bash"))


if __name__ == "__main__":
    unittest.main()
