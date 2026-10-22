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
            if getattr(self, "remote_path", None):
                env["PUBLISH_REMOTE_PATH"] = self.remote_path
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

    def setup_remote(self, remote_tools=None):
        # serves: P11. This fixture never runs an actual SSH client.
        # remote_tools: run the remote shell with only these programs on PATH (a macOS
        # target has md5 and may lack md5sum); None keeps the host PATH and the fake md5sum.
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
            "env=dict(os.environ)\n"
            "if os.environ.get('PUBLISH_REMOTE_PATH'): env['PATH']=os.environ['PUBLISH_REMOTE_PATH']\n"
            "sys.exit(subprocess.run(['/bin/sh','-c',sys.argv[2]],input=body,env=env).returncode)\n")
        ssh.chmod(0o755)
        if remote_tools is not None:
            remote_bin = self.root / "remote-bin"
            remote_bin.mkdir()
            for tool in remote_tools:
                (remote_bin / Path(tool).name).symlink_to(tool)
            self.remote_path = str(remote_bin)
        # Simulate the Linux peer's md5sum on a macOS fixture host. It runs once per remote
        # file, so it is sh + md5, not a Python start-up: 701 of those under a loaded runner
        # passed the CLI timeout (verify/unit on PR #97, 2026-10-22).
        md5 = self.fake_bin / "md5sum"
        md5.write_text("#!/bin/sh\nprintf '%s  %s\\n' \"$(/sbin/md5 -q \"$1\")\" \"$1\"\n")
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
        # Long names reach the limit with few files; each file is one fake-ssh write.
        for i in range(160):
            (big / "references" / (f"reference-{i:03d}-" + "n" * 226 + ".md")).write_text(f"{i}\n")
        result = self.run_cli("--lesson", "big-lesson", "--remote", "fixture-only.invalid")
        self.assertEqual(result.returncode, 0, result.stderr)
        reads = [c for c in self.remote_calls() if not c["input_bytes"]]
        self.assertGreater(sum(len(c["command"].encode()) for c in reads), 131072, "one unbatched read would be refused")
        self.assertGreater(len(reads), 1, "the read must be split to fit")
        self.assertTrue(all(len(c["command"].encode()) <= 64 * 1024 for c in reads))
        published = {str(p.relative_to(self.remote / "big-lesson")) for p in (self.remote / "big-lesson").rglob("*")
                     if p.is_file()}
        self.assertEqual(len(published), 161)
        self.ssh_log.write_text("")
        result = self.run_cli("--lesson", "big-lesson", "--remote", "fixture-only.invalid")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(c["input_bytes"] for c in self.remote_calls()), "every hash was read back")

    def test_remote_read_batches_by_utf8_bytes_not_characters(self):
        # Linux counts the limit in bytes. Batching by JavaScript string length let
        # 3-byte filename characters build a command over 128 KiB (Hermes 2026-10-22).
        self.setup_remote()
        wide = self.root / "skillsets/fixture/shared/wide-lesson"
        wide.mkdir(parents=True)
        (wide / "SKILL.md").write_text('---\nname: wide-lesson\ndescription: "Fixture"\nverify: "true"\n'
                                       'verified: 2026-10-22\n---\nWide\n')
        name = "参" * 84  # 252 bytes: within a 255-byte path component
        for i in range(100):
            folder = wide / "references" / (name[:-3] + f"{i:03d}") / name
            folder.mkdir(parents=True)
            (folder / (name[:-3] + ".md")).write_text(f"{i}\n")
        result = self.run_cli("--lesson", "wide-lesson", "--remote", "fixture-only.invalid")
        self.assertEqual(result.returncode, 0, result.stderr)
        reads = [c for c in self.remote_calls() if not c["input_bytes"]]
        # The same lines batched by characters would build a command over 128 KiB in bytes.
        batch, by_chars = [], []
        for line in (l for c in reads for l in c["command"].split("\n")):
            if batch and len("\n".join(batch + [line])) > 64 * 1024:
                by_chars.append("\n".join(batch)); batch = []
            batch.append(line)
        by_chars.append("\n".join(batch))
        self.assertGreater(max(len(b.encode()) for b in by_chars), 131072)
        self.assertGreater(len(reads), 1)
        self.assertTrue(all(len(c["command"].encode()) <= 64 * 1024 for c in reads),
                        max(len(c["command"].encode()) for c in reads))
        published = [p for p in (self.remote / "wide-lesson").rglob("*") if p.is_file()]
        self.assertEqual(len(published), 101)

    def test_remote_unknown_edit_is_preserved_without_force(self):
        self.setup_remote()
        self.remote_target.write_text("remote user modification\n")
        before = self.remote_snapshot()
        result = self.remote_cli()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(before, self.remote_snapshot())
        self.assertFalse(any(call["input_bytes"] for call in self.remote_calls()))

    MAC_TOOLS = ["/sbin/md5", "/usr/bin/cut", "/bin/mkdir", "/usr/bin/base64", "/bin/chmod", "/bin/cat", "/bin/cp"]

    @unittest.skipUnless(os.path.exists("/sbin/md5"), "needs macOS md5")
    def test_macos_remote_without_md5sum_reads_hashes(self):
        # `md5sum f | cut ... || md5 -q f` never reached md5: cut succeeded on empty input,
        # so an existing file read as absent and an edit on the remote was overwritten unchecked.
        self.setup_remote(remote_tools=self.MAC_TOOLS)
        result = self.remote_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.remote_target.read_text(), 'BASE = "https://fixture.example"\n')
        self.ssh_log.write_text("")
        result = self.remote_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(c["input_bytes"] for c in self.remote_calls()), "a repeat publish writes nothing")
        self.remote_target.write_text("remote user modification\n")
        before = self.remote_snapshot()
        self.ssh_log.write_text("")
        result = self.remote_cli()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(before, self.remote_snapshot(), "an unknown edit on the remote is preserved")
        self.assertFalse(any(c["input_bytes"] for c in self.remote_calls()))

    def test_remote_with_no_hasher_refuses_before_writing(self):
        self.setup_remote(remote_tools=[t for t in self.MAC_TOOLS if not t.endswith("/md5")])
        before = self.remote_snapshot()
        result = self.remote_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("neither md5sum nor md5 -q", result.stderr)
        self.assertEqual(before, self.remote_snapshot())
        self.assertFalse(any(c["input_bytes"] for c in self.remote_calls()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
