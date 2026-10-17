#!/usr/bin/env python3
"""Exercise bounded publishing through its real CLI in an isolated fixture."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class PublishSelectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        scripts = self.root / "scripts"
        scripts.mkdir()
        shutil.copy2(SOURCE / "scripts/publish.mjs", scripts / "publish.mjs")
        shutil.copytree(SOURCE / "scripts/lib", scripts / "lib")
        self.dest = self.root / "installed"
        (scripts / "targets.json").write_text(json.dumps({
            "local": [{"agent": "fixture", "path": str(self.dest)}], "remote": {}}))
        self.overlay = self.root / "overlay.json"
        self.overlay.write_text('{"SYSTEM_ONE_BASE_URL":"https://fixture.example"}')
        for lesson in ("typed-decisions", "unrelated"):
            folder = self.root / "skillsets/fixture/shared" / lesson
            (folder / "scripts").mkdir(parents=True)
            (folder / "SKILL.md").write_text(
                f'---\nname: {lesson}\ndescription: "Fixture lesson"\nverify: "true"\n'
                'verified: 2026-10-17\n---\nFixture\n')
            (folder / "scripts/jev.py").write_text('BASE = "{{SYSTEM_ONE_BASE_URL}}"\n')
            (folder / "scripts/other.py").write_text('print("unrelated")\n')
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"],
                       check=True, capture_output=True)

    def run_cli(self, *args):
        env = os.environ.copy()
        env.update(AGENT_LIBRARY_OVERLAY=str(self.overlay),
                   AGENT_LIBRARY_LESSONS=str(self.root / "no-local-lessons"))
        return subprocess.run(["node", str(self.root / "scripts/publish.mjs"), *args],
                              env=env, capture_output=True, text=True, timeout=15)

    def files(self):
        return sorted(str(p.relative_to(self.dest)) for p in self.dest.rglob("*") if p.is_file())

    def test_resource_selection_only_writes_requested_file(self):
        result = self.run_cli("--lesson", "typed-decisions", "--resource", "scripts/jev.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.files(), ["typed-decisions/scripts/jev.py"])
        self.assertIn("https://fixture.example", (self.dest / self.files()[0]).read_text())

    def test_lesson_selection_preserves_other_lessons(self):
        result = self.run_cli("--lesson", "typed-decisions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.files()), 3)
        self.assertTrue(all(p.startswith("typed-decisions/") for p in self.files()))

    def test_check_never_writes(self):
        result = self.run_cli("--lesson", "typed-decisions", "--resource", "scripts/jev.py", "--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.dest.exists())

    def test_invalid_selection_refuses_before_writes(self):
        for args in (("--lesson", "missing"), ("--lesson",),
                     ("--resource", "scripts/jev.py"),
                     ("--lesson", "typed-decisions", "--resource", "../escape"),
                     ("--lesson", "typed-decisions", "--resource", "missing.py")):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertIn(result.returncode, (1, 2), result.stderr)
                self.assertFalse(self.dest.exists())

    def test_in_place_edit_is_refused_without_force(self):
        target = self.dest / "typed-decisions/scripts/jev.py"
        target.parent.mkdir(parents=True)
        target.write_text("user modification\n")
        result = self.run_cli("--lesson", "typed-decisions", "--resource", "scripts/jev.py")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(target.read_text(), "user modification\n")
        self.assertEqual(len(self.files()), 1)

    def test_known_version_under_old_overlay_is_updated(self):
        target = self.dest / "typed-decisions/scripts/jev.py"
        target.parent.mkdir(parents=True)
        target.write_text('BASE = "https://previous-fixture.example"\n')
        result = self.run_cli("--lesson", "typed-decisions", "--resource", "scripts/jev.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_text(), 'BASE = "https://fixture.example"\n')

    def test_no_selection_retains_full_publish_behavior(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.files()), 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
