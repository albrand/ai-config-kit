"""Exercise installation, backups and refusal before modifying a fixture home."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("continuation_installer", ROOT / "hooks/install-continuation.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
trust_spec = importlib.util.spec_from_file_location("continuation_trust", ROOT / "hooks/codex-hook-trust.py")
trust = importlib.util.module_from_spec(trust_spec)
trust_spec.loader.exec_module(trust)


class ContinuationInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.backup = Path(self.temp.name) / "backup"
        hooks = self.home / ".agent-hooks"
        hooks.mkdir(parents=True)
        (hooks / "qa-stop-hook.sh").write_text("original stop wrapper\n")
        (hooks / "other-safety-hook.sh").write_text("preserve this safety check\n")
        for provider_home in (".agents", ".bb", ".claude", ".codex"):
            root = self.home / provider_home / "skills/scope-ledger"
            (root / "scripts").mkdir(parents=True)
            (root / "SKILL.md").write_text("old skill\n")
            shutil.copy2(ROOT / "shared/scope-ledger/scripts/scope-gate.py", root / "scripts/scope-gate.py")

    def native_config(self):
        config = {"hooks": {
            "PreToolUse": [{"hooks": [{"type": "command", "command": str(self.home / ".agent-hooks/coordinator-hook-pretool.sh"), "timeout": 20}]}],
            "Stop": [{"hooks": [{"type": "command", "command": str(self.home / ".agent-hooks/qa-stop-hook.sh"), "timeout": 5}]}],
        }, "keep": "unchanged"}
        path = self.home / ".codex/hooks.json"
        path.write_text(json.dumps(config))
        key = f"{path}:pre_tool_use:0:0"
        fingerprint = trust.codex_hook_hash("pre_tool_use", config["hooks"]["PreToolUse"][0]["hooks"][0]["command"], 20)
        (self.home / ".codex/config.toml").write_text('model = "fixture"\n\n[hooks.state.' + json.dumps(key)
                                                    + ']\ntrusted_hash = ' + json.dumps(fingerprint) + '\nenabled = true\n')
        return path, config

    def assert_native_trust(self):
        result = subprocess.run([sys.executable, str(ROOT / "hooks/codex-hook-trust.py"), "--check", "--only-event", "Stop", "--only-command",
                                 str(self.home / ".agent-hooks/qa-stop-hook.sh")],
                                env=dict(os.environ, HOME=str(self.home)), capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unrelated_disabled_hook_and_its_trust_state_are_preserved(self):
        path, _ = self.native_config()
        key = f"{path}:pre_tool_use:0:0"
        trust_config = self.home / ".codex/config.toml"
        original = {"trusted_hash": "previous-user-trust", "enabled": False}
        trust_config.write_text('model = "fixture"\n\n[hooks.state.' + json.dumps(key) + ']\n'
                                'trusted_hash = "previous-user-trust"\nenabled = false\n')
        installer.install(ROOT, self.home, self.backup)
        self.assertEqual(tomllib.loads(trust_config.read_text())["hooks"]["state"][key], original)
        self.assert_native_trust()

    def test_scoped_trust_refuses_missing_or_unowned_command_without_writing_config(self):
        path, config = self.native_config()
        outside = "/unrelated/qa-stop-hook.sh"
        config["hooks"]["Stop"][0]["hooks"].append({"command": outside, "timeout": 5})
        path.write_text(json.dumps(config))
        trust_config = self.home / ".codex/config.toml"
        original = trust_config.read_bytes()
        for command in (outside, str(self.home / ".agent-hooks/missing.sh")):
            with self.subTest(command=command):
                result = subprocess.run([sys.executable, str(ROOT / "hooks/codex-hook-trust.py"),
                                         "--trust", "--only-command", command],
                                        env=dict(os.environ, HOME=str(self.home)), capture_output=True,
                                        text=True, timeout=10)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(trust_config.read_bytes(), original)

    def test_same_command_disabled_non_stop_registration_is_preserved(self):
        path, config = self.native_config()
        config["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = config["hooks"]["Stop"][0]["hooks"][0]["command"]
        path.write_text(json.dumps(config))
        key = f"{path}:pre_tool_use:0:0"
        trust_config = self.home / ".codex/config.toml"
        original = {"trusted_hash": "previous-user-trust", "enabled": False}
        trust_config.write_text('model = "fixture"\n\n[hooks.state.' + json.dumps(key) + ']\n'
                                'trusted_hash = "previous-user-trust"\nenabled = false\n')
        installer.install(ROOT, self.home, self.backup)
        self.assertEqual(tomllib.loads(trust_config.read_text())["hooks"]["state"][key], original)
        self.assert_native_trust()

    def test_unowned_stop_with_matching_basename_is_untouched(self):
        path, config = self.native_config()
        unrelated = {"type": "command", "command": "/unrelated/qa-stop-hook.sh", "timeout": 3}
        config["hooks"]["Stop"][0]["hooks"].append(unrelated)
        compound = {"command": str(self.home / ".agent-hooks/other-safety-hook.sh") + " && /unrelated/qa-stop-hook.sh", "timeout": 2}
        config["hooks"]["Stop"][0]["hooks"].append(compound)
        path.write_text(json.dumps(config))
        installer.install(ROOT, self.home, self.backup)
        self.assertEqual(json.loads(path.read_text())["hooks"]["Stop"][0]["hooks"][1], unrelated)
        self.assertEqual(json.loads(path.read_text())["hooks"]["Stop"][0]["hooks"][2], compound)
        states = tomllib.loads((self.home / ".codex/config.toml").read_text())["hooks"]["state"]
        self.assertNotIn(f"{path}:stop:0:1", states)
        self.assertNotIn(f"{path}:stop:0:2", states)
        self.assert_native_trust()

    def test_install_updates_delivery_budget_and_native_trust(self):
        path, before = self.native_config()
        installer.install(ROOT, self.home, self.backup)
        after = json.loads(path.read_text())
        after["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 5
        self.assertEqual(after, before)
        states = tomllib.loads((self.home / ".codex/config.toml").read_text())["hooks"]["state"]
        self.assertEqual(len(states), 2)
        self.assertTrue(all(state["enabled"] and state["trusted_hash"].startswith("sha256:") for state in states.values()))
        self.assert_native_trust()
        self.assertEqual((self.home / ".agent-hooks/hook-timeouts.py").read_bytes(), (ROOT / "hooks/hook-timeouts.py").read_bytes())

    def test_claude_config_without_pretool_chain_does_not_leave_native_hook_untrusted(self):
        path, _ = self.native_config()
        claude = self.home / ".claude/settings.json"
        unrelated = {"keep": "unchanged", "hooks": {"Stop": [{"hooks": [{"command": "/other/stop.sh", "timeout": 3}]}]}}
        claude.write_text(json.dumps(unrelated))
        installer.install(ROOT, self.home, self.backup)
        self.assertEqual(json.loads(claude.read_text()), unrelated)
        self.assertEqual(json.loads(path.read_text())["hooks"]["Stop"][0]["hooks"][0]["timeout"], 15)
        states = tomllib.loads((self.home / ".codex/config.toml").read_text())["hooks"]["state"]
        self.assertTrue(all(state["enabled"] for state in states.values()))
        self.assert_native_trust()

    def test_native_stop_without_pretool_chain_is_installed_and_trusted(self):
        path, config = self.native_config()
        del config["hooks"]["PreToolUse"]
        path.write_text(json.dumps(config))
        (self.home / ".codex/config.toml").write_text('model = "fixture"\n')
        installer.install(ROOT, self.home, self.backup)
        self.assertEqual(json.loads(path.read_text())["hooks"]["Stop"][0]["hooks"][0]["timeout"], 15)
        states = tomllib.loads((self.home / ".codex/config.toml").read_text())["hooks"]["state"]
        self.assertEqual(len(states), 1)
        self.assertTrue(next(iter(states.values()))["enabled"])
        self.assert_native_trust()

    def test_symlink_native_trust_config_refuses_before_changing_any_gate(self):
        self.native_config()
        config = self.home / ".codex/config.toml"
        outside = Path(self.temp.name) / "unrelated-config.toml"
        original = config.read_text()
        config.rename(outside)
        config.symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            installer.install(ROOT, self.home, self.backup)
        self.assertEqual(outside.read_text(), original)
        self.assertEqual((self.home / ".agent-hooks/qa-stop-hook.sh").read_text(), "original stop wrapper\n")
        self.assertFalse(self.backup.exists())

    def test_install_updates_all_copies_and_preserves_backups_and_other_gates(self):
        result = installer.install(ROOT, self.home, self.backup)
        self.assertEqual(result["installed_files"], 11)
        self.assertEqual((self.backup / "0").read_text(), "original stop wrapper\n")
        self.assertEqual((self.home / ".agent-hooks/other-safety-hook.sh").read_text(), "preserve this safety check\n")
        for provider_home in (".agents", ".bb", ".claude", ".codex"):
            root = self.home / provider_home / "skills/scope-ledger"
            for relative in ("SKILL.md", "scripts/closeout-stop.py"):
                self.assertEqual((root / relative).read_bytes(), (ROOT / "shared/scope-ledger" / relative).read_bytes())

    def test_helper_drift_refuses_before_changing_any_gate(self):
        helper = self.home / ".codex/skills/scope-ledger/scripts/scope-gate.py"
        helper.write_text("different helper\n")
        with self.assertRaisesRegex(RuntimeError, "helper differs"):
            installer.install(ROOT, self.home, self.backup)
        self.assertEqual((self.home / ".agent-hooks/qa-stop-hook.sh").read_text(), "original stop wrapper\n")
        self.assertFalse(self.backup.exists())

    def test_symlink_target_refuses_before_changing_any_gate(self):
        outside = Path(self.temp.name) / "unrelated-file"
        outside.write_text("untouched\n")
        target = self.home / ".codex/skills/scope-ledger/scripts/closeout-stop.py"
        target.symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, "symlink target"):
            installer.install(ROOT, self.home, self.backup)
        self.assertEqual(outside.read_text(), "untouched\n")
        self.assertEqual((self.home / ".agent-hooks/qa-stop-hook.sh").read_text(), "original stop wrapper\n")
        self.assertFalse(self.backup.exists())

    def test_symlink_parent_refuses_before_changing_any_gate(self):
        root = self.home / ".agents/skills/scope-ledger"
        outside = Path(self.temp.name) / "unrelated-skill-directory"
        root.rename(outside)
        root.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            installer.install(ROOT, self.home, self.backup)
        self.assertEqual((outside / "SKILL.md").read_text(), "old skill\n")
        self.assertFalse((outside / "scripts/closeout-stop.py").exists())
        self.assertEqual((self.home / ".agent-hooks/qa-stop-hook.sh").read_text(), "original stop wrapper\n")
        self.assertFalse(self.backup.exists())


if __name__ == "__main__":
    unittest.main()
