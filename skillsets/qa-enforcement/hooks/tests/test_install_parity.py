#!/usr/bin/env python3
"""Exercise the QA hook installer without touching the user's HOME."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[4]
INSTALLER = ROOT / "skillsets/qa-enforcement/hooks/install.sh"


class InstallParityTests(unittest.TestCase):
    def test_temp_home_install_matches_repo_sources_byte_for_byte(self):
        with tempfile.TemporaryDirectory(prefix="qa-hook-install-") as temporary:
            base = Path(temporary)
            stage = base / "stage"
            home = base / "home"
            (stage / "hooks").parent.mkdir(parents=True)
            shutil.copytree(
                ROOT / "skillsets/qa-enforcement/hooks",
                stage / "hooks",
                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "*.bak*"),
            )
            shutil.copytree(
                ROOT / "skillsets/qa-enforcement/shared/qa-sweep",
                stage / "qa-sweep",
                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "*.bak*"),
            )
            home.mkdir()
            for provider_home in (".agents/skills", ".bb/skills", ".claude/skills", ".codex/skills"):
                (home / provider_home).mkdir(parents=True)

            result = subprocess.run(
                ["sh", str(stage / "hooks/install.sh"), str(stage)],
                cwd=ROOT,
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            files = {
                "hooks/qa-ship-gate-hook.sh": ".agent-hooks/qa-ship-gate-hook.sh",
                "hooks/qa-stop-hook.sh": ".agent-hooks/qa-stop-hook.sh",
                "hooks/keepgoing-stop.py": ".agent-hooks/keepgoing-stop.py",
                "hooks/thread-wait-guard.py": ".agent-hooks/thread-wait-guard.py",
                "hooks/qa-bindings-push-gate.py": ".agent-hooks/qa-bindings-push-gate.py",
                "hooks/codex-hook-trust.py": ".agent-hooks/codex-hook-trust.py",
                "hooks/coordinator-hook-pretool.sh": ".agent-hooks/coordinator-hook-pretool.sh",
                "hooks/plugin/opencode-qa-evidence.js": ".config/opencode/plugin/qa-evidence-gate.js",
                "hooks/lib/qa-evidence-policy.mjs": ".config/opencode/lib/qa-evidence-policy.mjs",
            }
            for source, installed in files.items():
                with self.subTest(installed=installed):
                    self.assertEqual((stage / source).read_bytes(), (home / installed).read_bytes())

            for provider_home in (".agents/skills", ".bb/skills", ".claude/skills", ".codex/skills"):
                source_root = stage / "qa-sweep"
                installed_root = home / provider_home / "qa-sweep"
                ignored = lambda path: any(
                    part in {"__pycache__", ".pytest_cache"} or part.endswith(".pyc") or ".bak" in part
                    for part in path.parts
                )
                expected = sorted(
                    path.relative_to(source_root) for path in source_root.rglob("*") if path.is_file() and not ignored(path)
                )
                actual = sorted(
                    path.relative_to(installed_root) for path in installed_root.rglob("*") if path.is_file() and not ignored(path)
                )
                self.assertEqual(actual, expected, provider_home)
                for relative in expected:
                    with self.subTest(home=provider_home, file=str(relative)):
                        self.assertEqual((source_root / relative).read_bytes(), (installed_root / relative).read_bytes())

            drift = subprocess.run(
                ["sh", str(ROOT / "scripts/hook-drift-check.sh")],
                cwd=ROOT,
                env={**os.environ, "HOME": str(home)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(drift.returncode, 0, drift.stdout + drift.stderr)


if __name__ == "__main__":
    unittest.main()
