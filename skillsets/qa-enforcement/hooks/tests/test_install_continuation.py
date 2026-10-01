"""Exercise installation, backups and refusal before modifying a fixture home."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("continuation_installer", ROOT / "hooks/install-continuation.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


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
        (self.home / ".codex/config.toml").write_text('model = "fixture"\n')
        return path, config

    def test_install_updates_delivery_budget_and_native_trust(self):
        path, before = self.native_config()
        installer.install(ROOT, self.home, self.backup)
        after = json.loads(path.read_text())
        after["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 5
        self.assertEqual(after, before)
        states = tomllib.loads((self.home / ".codex/config.toml").read_text())["hooks"]["state"]
        self.assertEqual(len(states), 2)
        self.assertTrue(all(state["enabled"] and state["trusted_hash"].startswith("sha256:") for state in states.values()))
        self.assertEqual((self.home / ".agent-hooks/hook-timeouts.py").read_bytes(), (ROOT / "hooks/hook-timeouts.py").read_bytes())

    def test_symlink_native_trust_config_refuses_before_changing_any_gate(self):
        self.native_config()
        config = self.home / ".codex/config.toml"
        outside = Path(self.temp.name) / "unrelated-config.toml"
        config.rename(outside)
        config.symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            installer.install(ROOT, self.home, self.backup)
        self.assertEqual(outside.read_text(), 'model = "fixture"\n')
        self.assertEqual((self.home / ".agent-hooks/qa-stop-hook.sh").read_text(), "original stop wrapper\n")
        self.assertFalse(self.backup.exists())

    def test_install_updates_all_copies_and_preserves_backups_and_other_gates(self):
        result = installer.install(ROOT, self.home, self.backup)
        self.assertEqual(result["installed_files"], 10)
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
