#!/usr/bin/env python3
"""Exercise bounded publishing through its real CLI in an isolated fixture."""
import hashlib
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
        if hasattr(self, "fake_bin"):
            env.update(PATH=str(self.fake_bin) + os.pathsep + env["PATH"],
                       PUBLISH_SSH_LOG=str(self.ssh_log))
        return subprocess.run(["node", str(self.root / "scripts/publish.mjs"), *args],
                              env=env, capture_output=True, text=True, timeout=120)

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

    def setup_remote(self):
        # serves: P11. This fixture never runs an actual SSH client.
        self.remote = self.root / "remote-installed"
        self.fake_bin = self.root / "fake-bin"
        self.fake_bin.mkdir()
        self.ssh_log = self.root / "ssh.jsonl"
        (self.root / "scripts/targets.json").write_text(json.dumps({
            "local": [{"agent": "fixture", "path": str(self.dest)}],
            "remote": {"fixture-only.invalid": [{"agent": "fixture", "path": str(self.remote)}]}}))
        ssh = self.fake_bin / "ssh"
        ssh.write_text("#!/usr/bin/env python3\n"
            "import json,os,subprocess,sys\n"
            "assert len(sys.argv)==3 and sys.argv[1]=='fixture-only.invalid'\n"
            "body=sys.stdin.buffer.read()\n"
            "with open(os.environ['PUBLISH_SSH_LOG'],'a') as log: "
            "log.write(json.dumps({'command':sys.argv[2],'input_bytes':len(body)})+'\\n')\n"
            # sshd hands the command to the remote shell as one argument; Linux refuses one over 128 KiB
            "if len(sys.argv[2].encode()) > 131072: sys.stderr.write('/bin/bash: Argument list too long\\n'); sys.exit(1)\n"
            "sys.exit(subprocess.run(['/bin/sh','-c',sys.argv[2]],input=body).returncode)\n")
        ssh.chmod(0o755)
        # Simulate the Linux peer's md5sum on a macOS fixture host.
        md5 = self.fake_bin / "md5sum"
        md5.write_text("#!/usr/bin/env python3\nimport hashlib,sys\n"
            "print(hashlib.md5(open(sys.argv[1],'rb').read()).hexdigest()+'  '+sys.argv[1])\n")
        md5.chmod(0o755)
        for lesson in ("typed-decisions", "unrelated"):
            for relative in ("SKILL.md", "scripts/jev.py", "scripts/other.py"):
                target = self.remote / lesson / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("preserve unrelated remote content\n")
        self.remote_target = self.remote / "typed-decisions/scripts/jev.py"
        self.remote_target.write_text('BASE = "https://previous-fixture.example"\n')

    def remote_snapshot(self):
        return {str(p.relative_to(self.remote)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.remote.rglob("*") if p.is_file()}

    def remote_cli(self, *args):
        return self.run_cli("--lesson", "typed-decisions", "--resource", "scripts/jev.py",
                            "--remote", "fixture-only.invalid", *args)

    def remote_calls(self):
        return [json.loads(line) for line in self.ssh_log.read_text().splitlines()]

    def test_remote_selection_writes_only_selected_resource_and_is_idempotent(self):
        self.setup_remote()
        before = self.remote_snapshot()
        result = self.remote_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        after = self.remote_snapshot()
        self.assertEqual(set(before), set(after))
        self.assertEqual([p for p in before if before[p] != after[p]],
                         ["typed-decisions/scripts/jev.py"])
        self.assertEqual(self.remote_target.read_text(), 'BASE = "https://fixture.example"\n')
        self.assertTrue(any(call["input_bytes"] for call in self.remote_calls()))
        for call in self.remote_calls():
            self.assertIn(str(self.remote_target), call["command"])
            self.assertNotIn("other.py", call["command"])
            self.assertNotIn("SKILL.md", call["command"])
            self.assertNotIn("/unrelated/", call["command"])
        self.ssh_log.write_text("")
        result = self.remote_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(after, self.remote_snapshot())
        self.assertTrue(self.remote_calls())
        self.assertFalse(any(call["input_bytes"] for call in self.remote_calls()))

    def test_remote_check_reads_selected_resource_without_writing(self):
        self.setup_remote()
        before = self.remote_snapshot()
        result = self.remote_cli("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.remote_snapshot())
        self.assertTrue(self.remote_calls())
        self.assertFalse(any(call["input_bytes"] for call in self.remote_calls()))
        self.assertTrue(all(str(self.remote_target) in call["command"] for call in self.remote_calls()))
        self.assertTrue(all("other.py" not in call["command"] for call in self.remote_calls()))

    def test_remote_read_of_a_large_library_stays_under_the_argument_limit(self):
        # 2026-10-22: one hash-read line per file for the whole library made a single ssh
        # argument over Linux's 128 KiB cap, so every remote publish failed before writing.
        self.setup_remote()
        big = self.root / "skillsets/fixture/shared/big-lesson"
        (big / "references").mkdir(parents=True)
        (big / "SKILL.md").write_text('---\nname: big-lesson\ndescription: "Fixture"\nverify: "true"\n'
                                      'verified: 2026-10-22\n---\nBig\n')
        for i in range(700):
            (big / "references" / f"reference-file-with-a-long-descriptive-name-{i:04d}.md").write_text(f"{i}\n")
        result = self.run_cli("--lesson", "big-lesson", "--remote", "fixture-only.invalid")
        self.assertEqual(result.returncode, 0, result.stderr)
        reads = [c for c in self.remote_calls() if not c["input_bytes"]]
        self.assertGreater(len(reads), 1, "the read must be split to fit")
        self.assertTrue(all(len(c["command"].encode()) <= 64 * 1024 for c in reads))
        published = {str(p.relative_to(self.remote / "big-lesson")) for p in (self.remote / "big-lesson").rglob("*")
                     if p.is_file()}
        self.assertEqual(len(published), 701)
        self.ssh_log.write_text("")
        result = self.run_cli("--lesson", "big-lesson", "--remote", "fixture-only.invalid")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(c["input_bytes"] for c in self.remote_calls()), "every hash was read back")

    def test_remote_unknown_edit_is_preserved_without_force(self):
        self.setup_remote()
        self.remote_target.write_text("remote user modification\n")
        before = self.remote_snapshot()
        result = self.remote_cli()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(before, self.remote_snapshot())
        self.assertFalse(any(call["input_bytes"] for call in self.remote_calls()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
