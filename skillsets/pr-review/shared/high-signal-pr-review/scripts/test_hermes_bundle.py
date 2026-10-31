#!/usr/bin/env python3
"""Offline tests for hermes-bundle.py: a fake `gh` on PATH serves canned PR data.

Run: python3 -I test_hermes_bundle.py
HERMES_BUNDLE_SCRIPT overrides the script under test (used to run mutants).
"""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = Path(os.environ.get("HERMES_BUNDLE_SCRIPT", HERE / "hermes-bundle.py"))
FIXTURE = HERE / "fixtures" / "no-fire-manifest.md"
HEAD = "a" * 40
BASE = "b" * 40

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_GH_DIR"]
a = sys.argv[1:]
def out(s):
    sys.stdout.write(s if isinstance(s, str) else s.decode()); sys.exit(0)
if a[:2] == ["pr", "view"]:
    out(open(d + "/view.json").read())
if a[:2] == ["pr", "diff"]:
    out(open(d + "/diff.txt").read())
if a[0] == "api" and "--paginate" in a:
    out(open(d + "/files.json").read())
if a[0] == "api":
    url = a[-1]
    path = url.split("/contents/", 1)[1].split("?ref=")[0]
    ref = url.split("?ref=")[1]
    if ref != json.load(open(d + "/view.json"))["headRefOid"]:
        sys.stderr.write("wrong ref"); sys.exit(1)
    try:
        sys.stdout.buffer.write(open(d + "/contents/" + path, "rb").read())
    except FileNotFoundError:
        sys.stderr.write("404"); sys.exit(1)
    sys.exit(0)
sys.stderr.write("unexpected gh call: %r" % a); sys.exit(2)
'''


def diff_block(path, body="x"):
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1 @@\n+{body}\n"


class BundleCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake = self.tmp / "fake"
        (self.fake / "contents").mkdir(parents=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.out = self.tmp / "out"

    def serve(self, files, diff, tests=None, checks=None, statuses=None, renames=None, body="PR explains the behaviour change."):
        view = {
            "headRefOid": HEAD, "baseRefOid": BASE, "title": "Add thing",
            "url": "https://github.com/o/r/pull/7", "mergeable": "MERGEABLE", "state": "OPEN",
            "body": body,
            "statusCheckRollup": checks if checks is not None else [
                {"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"context": "legacy/status", "state": "PENDING"},
            ],
        }
        (self.fake / "view.json").write_text(json.dumps(view))
        (self.fake / "diff.txt").write_text(diff)
        status_map = statuses or {}
        renames = renames or {}
        file_entries = []
        for f in files:
            entry = {"filename": f, "status": status_map.get(f, "modified")}
            if f in renames:
                entry["status"] = "renamed"
                entry["previous_filename"] = renames[f]
            file_entries.append(entry)
        (self.fake / "files.json").write_text(json.dumps(file_entries))
        for p, body in (tests or {}).items():
            fp = self.fake / "contents" / p
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_bytes(body)

    def run_script(self, *extra):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "FAKE_GH_DIR": str(self.fake),
               "HOME": str(self.tmp)}
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--repo", "o/r", "--pr", "7",
             "--out", str(self.out), *extra],
            capture_output=True, text=True, env=env)

    # --- the four parts -------------------------------------------------
    def test_stamp_cleanup_rejects_traversal(self):
        self.serve(["src/a.py"], diff_block("src/a.py"))
        self.out.mkdir(parents=True, exist_ok=True)
        outside = self.tmp / "outside.txt"
        outside.write_text("keep\n")
        stamp = self.out / ".hermes-bundle-artifacts.json"
        stamp.write_text('["../outside.txt"]\n')
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(outside.exists())
        self.assertEqual(outside.read_text(), "keep\n")

    def test_reused_out_preserves_unrelated_files(self):
        self.serve(["src/a.py"], diff_block("src/a.py"))
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "tests").mkdir(exist_ok=True)
        (self.out / "fixtures").mkdir(exist_ok=True)
        (self.out / "provenance").mkdir(exist_ok=True)
        keeper = self.out / "stale.env"
        keep_test = self.out / "tests" / "keep.py"
        keep_fix = self.out / "fixtures" / "keep.md"
        keep_prov = self.out / "provenance" / "keep.log"
        for path, body in ((keeper, "TOPSECRET=1\n"), (keep_test, "# stay\n"), (keep_fix, "stay\n"), (keep_prov, "stay\n")):
            path.write_text(body)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        for path, body in ((keeper, "TOPSECRET=1\n"), (keep_test, "# stay\n"), (keep_fix, "stay\n"), (keep_prov, "stay\n")):
            self.assertTrue(path.exists(), path)
            self.assertEqual(path.read_text(), body)
        self.assertNotIn("stale.env", r.stdout)
        self.assertNotIn("keep.py", r.stdout)


    def test_stamp_cleanup_never_removes_out_root(self):
        self.serve(["src/a.py"], diff_block("src/a.py"))
        self.out.mkdir(parents=True, exist_ok=True)
        keeper = self.out / "user-data.txt"
        keeper.write_text("keep\n")
        stamp = self.out / ".hermes-bundle-artifacts.json"
        for payload in ('["."]', '[""]', '["./"]', '["sub/.."]'):
            with self.subTest(stamp=payload):
                keeper.write_text("keep\n")
                stamp.write_text(payload + "\n")
                r = self.run_script()
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(self.out.is_dir(), self.out)
                self.assertTrue(keeper.is_file(), keeper)
                self.assertEqual(keeper.read_text(), "keep\n")

    def test_stamp_cleanup_symlink_to_outside_unlink_only_link(self):
        self.serve(["src/a.py"], diff_block("src/a.py"))
        self.out.mkdir(parents=True, exist_ok=True)
        outside = self.tmp / "outside-secret.txt"
        outside.write_text("secret\n")
        link = self.out / "escape-link"
        link.symlink_to(outside)
        (self.out / ".hermes-bundle-artifacts.json").write_text('["escape-link"]\n')
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(outside.is_file())
        self.assertEqual(outside.read_text(), "secret\n")
        self.assertFalse(link.exists())

    def _assert_victim_unchanged(self, victim, before_mtime, before_body):
        self.assertEqual(victim.read_text(), before_body)
        self.assertEqual(victim.stat().st_mtime, before_mtime)

    def test_write_refuses_symlink_at_artifact_path(self):
        self.serve(["src/a.py"], diff_block("src/a.py"))
        self.out.mkdir(parents=True, exist_ok=True)
        victim = self.tmp / "victim-artifact.txt"
        victim.write_text("unchanged\n")
        before_mtime = victim.stat().st_mtime
        (self.out / "pr.diff").symlink_to(victim)
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("symlink", r.stderr.lower())
        self._assert_victim_unchanged(victim, before_mtime, "unchanged\n")

    def test_write_refuses_symlink_at_stamp_path(self):
        self.serve(["src/a.py"], diff_block("src/a.py"))
        self.out.mkdir(parents=True, exist_ok=True)
        victim = self.tmp / "victim-stamp.json"
        victim.write_text('["prior"]\n')
        before_mtime = victim.stat().st_mtime
        (self.out / ".hermes-bundle-artifacts.json").symlink_to(victim)
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("symlink", r.stderr.lower())
        self._assert_victim_unchanged(victim, before_mtime, '["prior"]\n')

    def test_write_refuses_symlink_parent_directory(self):
        self.serve(
            ["src/a.py", "tests/test_a.py"],
            diff_block("src/a.py") + diff_block("tests/test_a.py"),
            tests={"tests/test_a.py": b"def test_a(): pass\n"},
        )
        self.out.mkdir(parents=True, exist_ok=True)
        outside = self.tmp / "outside-tests"
        outside.mkdir()
        victim = outside / "never.txt"
        victim.write_text("stay\n")
        before_mtime = victim.stat().st_mtime
        (self.out / "tests").symlink_to(outside)
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("symlink", r.stderr.lower())
        self._assert_victim_unchanged(victim, before_mtime, "stay\n")

    def test_stamp_cleanup_directory_leaves_unlisted_files(self):
        self.serve(["src/a.py"], diff_block("src/a.py"))
        self.out.mkdir(parents=True, exist_ok=True)
        sub = self.out / "artifact-dir"
        sub.mkdir()
        (sub / "old-only.txt").write_text("old\n")
        (sub / "user-keep.txt").write_text("stay\n")
        (self.out / ".hermes-bundle-artifacts.json").write_text('["artifact-dir"]\n')
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(sub.is_dir())
        self.assertTrue((sub / "user-keep.txt").is_file())
        self.assertEqual((sub / "user-keep.txt").read_text(), "stay\n")
    def test_four_parts_present(self):
        self.serve(["src/a.py", "tests/test_a.py"],
                   diff_block("src/a.py") + diff_block("tests/test_a.py"),
                   tests={"tests/test_a.py": b"def test_a(): pass\n"})
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        # 1. diff
        self.assertIn("src/a.py", (self.out / "pr.diff").read_text())
        # 2. head.json: SHA + check states
        head = json.loads((self.out / "head.json").read_text())
        self.assertEqual(head["head_sha"], HEAD)
        self.assertEqual(head["base_sha"], BASE)
        self.assertEqual(head["mergeable"], "MERGEABLE")
        self.assertEqual(head["statusCheckRollup"][0],
                         {"name": "ci", "state": "COMPLETED", "conclusion": "SUCCESS"})
        self.assertEqual(head["statusCheckRollup"][1]["name"], "legacy/status")
        self.assertEqual(head["statusCheckRollup"][1]["state"], "PENDING")
        # 3. test sources fetched at head; non-test file is not
        self.assertEqual((self.out / "tests/tests/test_a.py").read_bytes(), b"def test_a(): pass\n")
        self.assertFalse((self.out / "tests/src/a.py").exists())
        # 4. manifest binds the head
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn(HEAD, man)
        self.assertIn("bound to head", man)
        # validate command printed, not run
        self.assertIn("bb fleet validate", r.stdout)
        self.assertIn("--evidence", r.stdout)
        self.assertIn(str(self.out / "MANIFEST.md"), r.stdout)

    # --- splitting ------------------------------------------------------
    def test_diff_split_at_cap(self):
        blocks = [diff_block(f"src/f{i}.py", "y" * 100) for i in range(10)]
        self.serve([f"src/f{i}.py" for i in range(10)], "".join(blocks))
        r = self.run_script("--diff-cap", "400")
        self.assertEqual(r.returncode, 0, r.stderr)
        parts = sorted(self.out.glob("pr.diff.part*"))
        self.assertGreater(len(parts), 1)
        self.assertFalse((self.out / "pr.diff").exists())
        for p in parts:
            self.assertLessEqual(p.stat().st_size, 400)
        self.assertEqual(b"".join(p.read_bytes() for p in sorted(
            parts, key=lambda p: int(p.name.rsplit("part", 1)[1]))), "".join(blocks).encode())
        idx = (self.out / "pr.diff.index.md").read_text()
        for p in parts:
            self.assertIn(p.name, idx)

    def test_diff_under_cap_not_split(self):
        self.serve(["src/a.py"], diff_block("src/a.py"))
        self.assertEqual(self.run_script().returncode, 0)
        self.assertTrue((self.out / "pr.diff").exists())
        self.assertEqual(list(self.out.glob("pr.diff.part*")), [])

    def test_single_oversize_file_block_is_cut(self):
        self.serve(["src/big.py"], diff_block("src/big.py", ("z" * 49 + "\n+") * 20))
        self.assertEqual(self.run_script("--diff-cap", "300").returncode, 0)
        parts = list(self.out.glob("pr.diff.part*"))
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(p.stat().st_size <= 300 for p in parts))

    def test_oversize_test_file_split_with_index(self):
        body = "".join(f"  it('case {i}', () => {{\n    expect({i}).toBe({i});\n  }});\n" for i in range(40)).encode()
        self.serve(["src/a.ts", "src/a.test.ts"], diff_block("src/a.ts"), tests={"src/a.test.ts": body})
        r = self.run_script("--diff-cap", "800")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.out / "tests/src/a.test.ts").exists())
        parts = sorted(self.out.glob("tests/src/a.test.ts.part*"), key=lambda p: int(p.name.rsplit("part", 1)[1]))
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(p.stat().st_size <= 800 for p in parts))
        self.assertEqual(b"".join(p.read_bytes() for p in parts), body)
        idx = (self.out / "tests/src/a.test.ts.index.md").read_text()
        self.assertIn("case 39", idx)
        for p in parts:
            self.assertIn(p.name, idx)
        self.assertIn(str(self.out / "tests/src/a.test.ts.index.md"), r.stdout)

    def test_manifest_states_bundle_is_the_whole_universe(self):
        self.serve(["src/a.py"], diff_block("src/a.py"))
        self.assertEqual(self.run_script().returncode, 0)
        manifest = (self.out / "MANIFEST.md").read_text()
        self.assertIn("only files you have", manifest)
        self.assertIn("do not retry", manifest)

    # --- sensitive names ------------------------------------------------
    def test_sensitive_name_refused(self):
        for name in (".env.local", "keys/server.pem", "src/my_secret.py", "cfg/Credentials.json"):
            with self.subTest(name=name):
                shutil.rmtree(self.out, ignore_errors=True)
                self.serve(["src/a.py", name], diff_block("src/a.py") + diff_block(name, "TOPSECRET"))
                r = self.run_script()
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("sensitive", r.stderr)
                self.assertFalse((self.out / "MANIFEST.md").exists())
                self.assertFalse(self.out.exists() and any(self.out.rglob("pr.diff*")))

    def test_sensitive_allowed_lists_without_content(self):
        self.serve([".env.prod", "tests/test_a.py"],
                   diff_block(".env.prod", "TOPSECRET=1") + diff_block("tests/test_a.py"),
                   tests={".env.prod": b"TOPSECRET=1\n", "tests/test_a.py": b"ok\n"})
        r = self.run_script("--allow-sensitive-names")
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn(".env.prod", man)
        self.assertIn("content withheld", man)
        blob = b"".join(p.read_bytes() for p in self.out.rglob("*") if p.is_file())
        self.assertNotIn(b"TOPSECRET", blob)

    # --- manifest digests -----------------------------------------------
    def test_sensitive_quoted_path_with_embedded_quote_redacted(self):
        name = 'keys/private"key.pem'
        esc = name.replace('"', '\\"')
        header = f'diff --git "a/{esc}" "b/{esc}"\n'
        diff = (
            header
            + f'--- "a/{esc}"\n'
            + f'+++ "b/{esc}"\n'
            + "@@ -0,0 +1 @@\n"
            + "+SECRET\n"
        )
        self.serve([name, "src/a.py"], diff + diff_block("src/a.py"), tests={name: b"SECRET\n"})
        r = self.run_script("--allow-sensitive-names")
        self.assertEqual(r.returncode, 0, r.stderr)
        pr_diff = b"".join(p.read_bytes() for p in self.out.rglob("pr.diff*") if p.is_file())
        self.assertNotIn(b"SECRET", pr_diff)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn(name, man)
        self.assertIn("content withheld", man)

    def test_sensitive_git_octal_quoted_space_redacted(self):
        name = "keys/private key.pem"
        header = 'diff --git "a/keys/private\\040key.pem" "b/keys/private\\040key.pem"\n'
        diff = (
            header
            + '--- "a/keys/private\\040key.pem"\n'
            + '+++ "b/keys/private\\040key.pem"\n'
            + "@@ -0,0 +1 @@\n"
            + "+SECRET\n"
        )
        self.serve([name, "src/a.py"], diff + diff_block("src/a.py"), tests={name: b"SECRET\n"})
        r = self.run_script("--allow-sensitive-names")
        self.assertEqual(r.returncode, 0, r.stderr)
        pr_diff = b"".join(p.read_bytes() for p in self.out.rglob("pr.diff*") if p.is_file())
        self.assertNotIn(b"SECRET", pr_diff)


    def test_sensitive_git_octal_quoted_utf8_path_redacted(self):
        name = "café/id_rsa"
        esc = "caf\\303\\251/id_rsa"
        header = f'diff --git "a/{esc}" "b/{esc}"\n'
        diff = (
            header
            + f'--- "a/{esc}"\n'
            + f'+++ "b/{esc}"\n'
            + "@@ -0,0 +1 @@\n"
            + "+-----BEGIN OPENSSH PRIVATE KEY-----\n"
        )
        self.serve([name, "src/a.py"], diff + diff_block("src/a.py"), tests={name: b"KEY\n"})
        r = self.run_script("--allow-sensitive-names")
        self.assertEqual(r.returncode, 0, r.stderr)
        pr_diff = b"".join(p.read_bytes() for p in self.out.rglob("pr.diff*") if p.is_file())
        self.assertNotIn(b"BEGIN OPENSSH", pr_diff)
    def test_sensitive_unquoted_path_with_space_redacted(self):
        name = "private b/server.pem"
        diff = (
            f"diff --git a/{name} b/{name}\n"
            f"--- a/{name}\n"
            f"+++ b/{name}\n"
            + "@@ -0,0 +1 @@\n"
            + "+SECRET\n"
        )
        self.serve([name, "src/a.py"], diff + diff_block("src/a.py"), tests={name: b"SECRET\n"})
        r = self.run_script("--allow-sensitive-names")
        self.assertEqual(r.returncode, 0, r.stderr)
        pr_diff = b"".join(p.read_bytes() for p in self.out.rglob("pr.diff*") if p.is_file())
        self.assertNotIn(b"SECRET", pr_diff)

    def test_sensitive_id_rsa_redacted(self):
        name = "keys/id_rsa"
        body = "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        self.serve([name, "src/a.py"], diff_block(name, body) + diff_block("src/a.py"), tests={name: body.encode()})
        r = self.run_script("--allow-sensitive-names")
        self.assertEqual(r.returncode, 0, r.stderr)
        pr_diff = b"".join(p.read_bytes() for p in self.out.rglob("pr.diff*") if p.is_file())
        self.assertNotIn(b"BEGIN OPENSSH", pr_diff)

    def test_secret_in_ordinary_path_redacted(self):
        self.serve(["src/config.ts"], diff_block("src/config.ts", 'api_key: "leak"'))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        blob = b"".join(p.read_bytes() for p in self.out.rglob("*") if p.is_file())
        self.assertNotIn(b"leak", blob)
        self.assertIn(b"[redacted: secret-like content]", blob)

    def test_ec_private_key_redacted(self):
        body = "-----BEGIN EC PRIVATE KEY-----\nMIIB\n"
        self.serve(["src/config.ts"], diff_block("src/config.ts", body.strip()))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        blob = b"".join(p.read_bytes() for p in self.out.rglob("*") if p.is_file())
        self.assertNotIn(b"BEGIN EC PRIVATE KEY", blob)
        self.assertIn(b"[redacted: secret-like content]", blob)


    def test_multiline_pem_redacted_in_added_diff_hunk(self):
        diff = (
            "diff --git a/src/added.ts b/src/added.ts\n"
            "--- a/src/added.ts\n+++ b/src/added.ts\n"
            "@@ -0,0 +1,4 @@\n"
            "+-----BEGIN RSA PRIVATE KEY-----\n"
            "+MIIBFAKEKEYPAYLOAD\n"
            "+YW5vdGhlcmxpbmU=\n"
            "+-----END RSA PRIVATE KEY-----\n"
        )
        self.serve(["src/added.ts"], diff)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        pr_diff = b"".join(p.read_bytes() for p in self.out.rglob("pr.diff*") if p.is_file())
        self.assertNotIn(b"MIIBFAKEKEYPAYLOAD", pr_diff)
        self.assertNotIn(b"YW5vdGhlcmxpbmU=", pr_diff)

    def test_multiline_pem_redacted_in_context_diff_hunk(self):
        diff = (
            "diff --git a/src/ctx.ts b/src/ctx.ts\n"
            "--- a/src/ctx.ts\n+++ b/src/ctx.ts\n"
            "@@ -1,5 +1,5 @@\n"
            " -----BEGIN OPENSSH PRIVATE KEY-----\n"
            " MIIBFAKEKEYPAYLOAD\n"
            " YW5vdGhlcmxpbmU=\n"
            " -----END OPENSSH PRIVATE KEY-----\n"
            "-old\n"
            "+new\n"
        )
        self.serve(["src/ctx.ts"], diff)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        pr_diff = b"".join(p.read_bytes() for p in self.out.rglob("pr.diff*") if p.is_file())
        self.assertNotIn(b"MIIBFAKEKEYPAYLOAD", pr_diff)

    def test_multiline_pem_redacted_in_staged_test_file(self):
        path = "tests/fixture_key.ts"
        body = (
            "-----BEGIN ENCRYPTED PRIVATE KEY-----\n"
            "MIIBFAKEKEYPAYLOAD\n"
            "-----END ENCRYPTED PRIVATE KEY-----\n"
        )
        self.serve([path], diff_block(path, "x"), tests={path: body.encode()})
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        blob = b"".join(p.read_bytes() for p in self.out.rglob("*") if p.is_file())
        self.assertNotIn(b"MIIBFAKEKEYPAYLOAD", blob)
    def test_prefixed_env_secret_names_redacted(self):
        for body in (
            "OPENAI_API_KEY=sk-live\n",
            "CLIENT_SECRET=abc\n",
            "refresh_token=rt\n",
        ):
            with self.subTest(body=body):
                shutil.rmtree(self.out, ignore_errors=True)
                self.serve(["src/config.ts"], diff_block("src/config.ts", body.strip()))
                r = self.run_script()
                self.assertEqual(r.returncode, 0, r.stderr)
                blob = b"".join(p.read_bytes() for p in self.out.rglob("*") if p.is_file())
                self.assertNotIn(body.split("=", 1)[1][:3].encode(), blob)
                self.assertIn(b"[redacted: secret-like content]", blob)

    def test_secret_diff_context_line_redacted(self):
        diff = (
            "diff --git a/src/a.env b/src/a.env\n"
            "--- a/src/a.env\n"
            "+++ b/src/a.env\n"
            "@@ -1,3 +1,3 @@\n"
            " API_TOKEN=unchanged\n"
            "-OLD=1\n"
            "+NEW=2\n"
        )
        self.serve(["src/a.env"], diff)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        blob = b"".join(p.read_bytes() for p in self.out.rglob("pr.diff*") if p.is_file())
        self.assertNotIn(b"unchanged", blob)
        self.assertIn(b"[redacted: secret-like content]", blob)

    def test_sensitive_rename_redacted(self):
        old, new = "my_secret.txt", "notes.txt"
        diff = (
            f"diff --git a/{old} b/{new}\n"
            f"rename from {old}\n"
            f"rename to {new}\n"
            f"--- a/{old}\n"
            f"+++ b/{new}\n"
            "@@ -1 +1 @@\n"
            "-SECRET=1\n"
            "+SECRET=2\n"
        )
        self.serve([new], diff, renames={new: old}, statuses={new: "renamed"})
        r = self.run_script("--allow-sensitive-names")
        self.assertEqual(r.returncode, 0, r.stderr)
        blob = b"".join(p.read_bytes() for p in self.out.rglob("pr.diff*") if p.is_file())
        self.assertNotIn(b"SECRET=", blob)

    def test_manifest_digests_match_files(self):
        self.serve(["src/a.py", "tests/test_a.py", "web/a.test.ts"],
                   diff_block("src/a.py") + diff_block("tests/test_a.py") + diff_block("web/a.test.ts"),
                   tests={"tests/test_a.py": b"one\n", "web/a.test.ts": b"two\n"})
        self.assertEqual(self.run_script().returncode, 0)
        man = (self.out / "MANIFEST.md").read_text()
        rows = re.findall(r"^\| (\S+) \| (\d+) \| ([0-9a-f]{64}) \|$", man, re.M)
        names = {n for n, _, _ in rows}
        self.assertEqual(names, {"pr.diff", "pr-body.md", "head.json", "tests/tests/test_a.py", "tests/web/a.test.ts"})
        for name, size, digest in rows:
            data = (self.out / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest, name)
            self.assertEqual(len(data), int(size), name)

    def test_head_moving_midway_aborts(self):
        self.serve(["src/a.py"], diff_block("src/a.py"))
        # fake gh flips the head after the first view call
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH.replace(
            'out(open(d + "/view.json").read())',
            'n = d + "/n"; c = int(open(n).read()) if os.path.exists(n) else 0; open(n, "w").write(str(c + 1))\n'
            '    v = json.load(open(d + "/view.json"))\n'
            '    if c >= 1: v["headRefOid"] = "c" * 40\n'
            '    out(json.dumps(v))'))
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("head moved", r.stderr)

    def test_changed_fixtures_are_fetched_with_digests_and_warning(self):
        files = ["src/__fixtures__/a/b.ndjson", "src/__fixtures__/row-counts.json", "src/x.json"]
        bodies = {files[0]: b'{"event":1}\n', files[1]: b'{"rows":1}\n', files[2]: b'{"ordinary":true}\n'}
        self.serve(files, "".join(diff_block(p) for p in files), tests=bodies)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("fixtures changed; no provenance supplied", r.stderr)
        manifest = (self.out / "MANIFEST.md").read_text()
        for path in files[:2]:
            dest = self.out / "fixtures" / path
            self.assertEqual(dest.read_bytes(), bodies[path])
            self.assertRegex(manifest, re.escape(str(dest.relative_to(self.out))) + r" \| \d+ \| " + hashlib.sha256(bodies[path]).hexdigest())
        self.assertFalse((self.out / "fixtures/src/x.json").exists())
        self.assertFalse((self.out / "tests/src/x.json").exists())
        self.assertIn("fixtures changed; no provenance supplied", manifest)

    def test_provenance_refuses_secret_content(self):
        self.serve(["src/a.py"], diff_block("src/a.py"))
        source = self.tmp / "regen.log"
        source.write_bytes(b"export API_KEY=supersecret\n")
        r = self.run_script("--provenance", str(source))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("secret-like content", r.stderr)

    def test_provenance_is_copied_and_listed(self):
        self.serve(["src/__fixtures__/a.ndjson"], diff_block("src/__fixtures__/a.ndjson"),
                   tests={"src/__fixtures__/a.ndjson": b"record\n"})
        source = self.tmp / "regen.log"
        source.write_bytes(b"python regenerate.py\n")
        r = self.run_script("--provenance", str(source))
        self.assertEqual(r.returncode, 0, r.stderr)
        dest = self.out / "provenance" / "regen.log"
        self.assertEqual(dest.read_bytes(), source.read_bytes())
        self.assertIn(hashlib.sha256(source.read_bytes()).hexdigest(), (self.out / "MANIFEST.md").read_text())
        self.assertNotIn("fixtures changed; no provenance supplied", r.stderr)

    def _bundle_bytes(self):
        return sum(p.stat().st_size for p in self.out.rglob("*") if p.is_file())

    def _evidence_paths(self, stdout):
        return [Path(m.group(1)) for m in re.finditer(r"--evidence\s+(\S+)", stdout)]

    def _manifest_table_paths(self, manifest):
        return {m.group(1) for m in re.finditer(r"^\| (\S+) \| \d+ \| [0-9a-f]{64} \|$", manifest, re.M)}

    def _index_part_names(self):
        names = set()
        for idx in self.out.rglob("*.index.md"):
            for m in re.finditer(r"\| (\S+\.part\d+) \|", idx.read_text()):
                names.add(m.group(1))
            for m in re.finditer(r"^- (pr\.diff\.part\d+):", idx.read_text(), re.M):
                names.add(m.group(1))
        return names

    def _assert_evidence_matches_disk(self, stdout):
        disk = {p.resolve() for p in self.out.rglob("*") if p.is_file()}
        evidence = {p.resolve() for p in self._evidence_paths(stdout)}
        self.assertEqual(evidence, disk)
        manifest = (self.out / "MANIFEST.md").read_text()
        table = self._manifest_table_paths(manifest)
        for rel in table:
            self.assertTrue((self.out / rel).is_file(), rel)
        for part in self._index_part_names():
            hits = list(self.out.rglob(part))
            self.assertEqual(len(hits), 1, part)
            self.assertTrue(hits[0].is_file(), part)

    def test_two_large_tests_omitted_under_total_budget(self):
        big = b"x" * (110 * 1024)
        paths = ["tests/test_one.py", "tests/test_two.py"]
        diff = diff_block("src/a.py") + diff_block(paths[0], "change1") + diff_block(paths[1], "change2")
        self.serve(paths + ["src/a.py"], diff, tests={paths[0]: big, paths[1]: big})
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLessEqual(self._bundle_bytes(), 128 * 1024)
        self.assertEqual(list(self.out.rglob("*.part*")), [])
        for p in paths:
            omitted = self.out / "tests" / f"{p}.omitted.md"
            self.assertTrue(omitted.is_file(), p)
            text = omitted.read_text()
            self.assertIn("sha256:", text)
            self.assertIn("Changed line ranges", text)
            self.assertIn("pr.diff", text)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("Omitted for size", man)
        for p in paths:
            self.assertIn(p, man)
        self._assert_evidence_matches_disk(r.stdout)

    def test_no_dangling_paths_invariant(self):
        shapes = [
            (["src/a.py"], diff_block("src/a.py"), {}),
            ([f"src/f{i}.py" for i in range(8)], "".join(diff_block(f"src/f{i}.py", "y" * 80) for i in range(8)), {}),
        ]
        big = b"z" * (110 * 1024)
        shapes.append((["tests/big.py"], diff_block("tests/big.py", "big"), {"tests/big.py": big}))
        for files, diff, tests in shapes:
            with self.subTest(files=files[:2]):
                shutil.rmtree(self.out, ignore_errors=True)
                self.serve(files, diff, tests=tests)
                extra = ["--diff-cap", "400"] if len(files) > 3 else []
                r = self.run_script(*extra)
                self.assertEqual(r.returncode, 0, r.stderr)
                self._assert_evidence_matches_disk(r.stdout)

    def test_huge_diff_kept_with_over_budget_warning(self):
        blocks = [diff_block(f"src/f{i}.py", "w" * 200) for i in range(200)]
        self.serve([f"src/f{i}.py" for i in range(200)], "".join(blocks))
        r = self.run_script("--diff-cap", "8000", "--total-budget", str(48 * 1024))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.out / "pr.diff").exists())
        parts = list(self.out.glob("pr.diff.part*"))
        self.assertGreater(len(parts), 1)
        self.assertIn("warning:", r.stderr.lower())
        self.assertIn("total budget", r.stderr.lower())
        self._assert_evidence_matches_disk(r.stdout)



    def test_changed_existing_test_assertions_in_manifest_and_claim(self):
        path = "apps/server/test/archive-undo-grace.test.ts"
        diff = (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n"
            "@@ -10,8 +10,8 @@\n"
            " context\n"
            "-  it('leaves a running turn alone while the archive undo grace has not elapsed', () => {\n"
            "+  it('interrupts a running turn without waiting for the grace', () => {\n"
            "     const s = state();\n"
            "-    expect(s.status).toBe('active');\n"
            "+    expect(s.status).toBe('stopping');\n"
            "   });\n"
        )
        self.serve([path], diff, tests={path: b"it('x', () => {});\n"})
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("Changed assertions in tests this PR did not create", man)
        self.assertIn("leaves a running turn alone", man)
        self.assertIn("interrupts a running turn", man)
        self.assertIn("toBe('active')", man)
        self.assertIn("toBe('stopping')", man)
        self.assertRegex(man, r"L\d+: -  it\('leaves")
        self.assertRegex(man, r"L\d+: \+  it\('interrupts")
        self.assertIn("rule on every entry under", r.stdout)
        self.assertIn("Changed assertions in tests this PR did not create", r.stdout)

    def test_unittest_assert_in_not_in_in_changed_assertions(self):
        path = "scripts/test_hermes_bundle.py"
        diff = (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n"
            "@@ -120,6 +120,6 @@\n"
            "         for path, body in ((keeper, \"STALE=1\\n\"),):\n"
            "             self.assertTrue(path.exists(), path)\n"
            "             self.assertEqual(path.read_text(), body)\n"
            '-        self.assertIn("stale.env", r.stdout)\n'
            '+        self.assertNotIn("stale.env", r.stdout)\n'
        )
        self.serve([path], diff, tests={path: b"class T(unittest.TestCase): pass\n"})
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("assertIn", man)
        self.assertIn("assertNotIn", man)
        self.assertNotIn("No assertions changed in pre-existing tests.", man)

    def test_removed_existing_test_file_lists_assertions(self):
        path = "tests/old.test.ts"
        diff = (
            "diff --git a/tests/old.test.ts b/tests/old.test.ts\n"
            "deleted file mode 100644\n"
            "--- a/tests/old.test.ts\n"
            "+++ /dev/null\n"
            "@@ -1,3 +0,0 @@\n"
            "-expect(1).toBe(1);\n"
            "-it('kept', () => {});\n"
        )
        self.serve([path], diff, statuses={path: "removed"})
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("toBe(1)", man)
        self.assertNotIn("No assertions changed in pre-existing tests.", man)

    def test_changed_rule_strings_in_existing_test(self):
        path = "scripts/test_review_skill_source.py"
        diff = (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n"
            "@@ -320,7 +320,7 @@\n"
            '         for rule in (\n'
            '             "Hermes reviews every one of our PRs before merge",\n'
            '+            "Hermes reviews every one of our PRs. Start its round when the PR opens, alongside CI, not after CI is green",\n'
            "-            \"Hermes reviews every one of our PRs before merge\",\n"
            "         ):\n"
        )
        self.serve([path], diff, tests={path: b"def test_x(): pass\n"})
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("before merge", man)
        self.assertNotIn("No assertions changed in pre-existing tests.", man)

    def test_added_test_file_not_listed_in_changed_assertions(self):
        path = "tests/new.test.ts"
        diff = diff_block(path, "expect(x).toBe(1);")
        self.serve([path], diff, statuses={path: "added"}, tests={path: b"expect(1).toBe(1);\n"})
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("No assertions changed in pre-existing tests.", man)
        self.assertNotIn("### tests/new.test.ts", man)


    def test_added_it_block_only_not_in_changed_assertions(self):
        path = "apps/server/test/feature.test.ts"
        diff = (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n"
            "@@ -40,3 +40,10 @@\n"
            " unchanged();\n"
            "+  it('covers the new path', () => {\n"
            "+    expect(fn()).toBe('ok');\n"
            "+  });\n"
        )
        self.serve([path], diff, tests={path: b"unchanged();\n"})
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("No assertions changed in pre-existing tests.", man)
        self.assertNotIn("toBe('ok')", man)
        self.assertIn("New tests added to existing files", man)
        self.assertIn("covers the new path", man)
        self.assertNotIn("@@ -40,3 +40,10 @@", man)

    def test_mixed_diff_splits_changed_assertions_and_new_tests(self):
        path = "tests/mixed.test.ts"
        diff = (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n"
            "@@ -1,4 +1,4 @@\n"
            " setup();\n"
            "-  expect(s.status).toBe('active');\n"
            "+  expect(s.status).toBe('stopping');\n"
            "@@ -20,3 +20,7 @@\n"
            " tail();\n"
            "+  it('added case', () => {\n"
            "+    expect(1).toBe(1);\n"
            "+  });\n"
        )
        self.serve([path], diff, tests={path: b"setup();\n"})
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("toBe('active')", man)
        self.assertIn("toBe('stopping')", man)
        self.assertIn("added case", man)
        idx_changed = man.index("Changed assertions in tests this PR did not create")
        idx_new = man.index("New tests added to existing files")
        self.assertLess(idx_changed, idx_new)
        self.assertRegex(man, r"L\d+: -  expect\(s\.status\)\.toBe\('active'\)")
        self.assertNotIn("toBe(1)", man)

    def test_agent_generated_sentence_in_manifest(self):
        self.serve(["src/a.py"], diff_block("src/a.py"))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("> AGENT GENERATED", man)
        self.assertIn("Do not report the PR body's wording", man)

    def test_pr_body_written_and_listed(self):
        body = "Justifies the archive undo behaviour change.\n"
        self.serve(["src/a.py"], diff_block("src/a.py"), body=body)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.out / "pr-body.md").read_text(), body)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("| pr-body.md |", man)
        self.assertIn(str(self.out / "pr-body.md"), r.stdout)

    def test_invariants_with_pr_body_and_assertions_section(self):
        path = "tests/existing.test.ts"
        diff = (
            f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            "@@ -1,3 +1,3 @@\n"
            "-  expect(old).toBe(true);\n"
            "+  expect(old).toBe(false);\n"
        )
        self.serve([path], diff, tests={path: b"expect(true).toBe(true);\n"})
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLessEqual(self._bundle_bytes(), 128 * 1024)
        self._assert_evidence_matches_disk(r.stdout)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("Changed assertions in tests this PR did not create", man)
        self.assertIn("| pr-body.md |", man)


    def test_safety_state_durability_fires_on_path(self):
        path = "lib/input-safety.ts"
        diff = diff_block(path, "export const x = 1;")
        self.serve([path], diff)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("## Safety-state durability", man)
        self.assertIn("lib/input-safety.ts", man)
        self.assertRegex(r.stdout, r"Safety-state durability")

    def test_safety_state_durability_fires_on_content(self):
        path = "lib/session.ts"
        diff = (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n"
            "@@ -1,3 +1,4 @@\n"
            " unchanged();\n"
            "+  recordIncident('input', 'unknown');\n"
        )
        self.serve([path], diff)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("## Safety-state durability", man)
        self.assertIn("lib/session.ts", man)

    def test_safety_state_durability_no_false_positive(self):
        test_path = "lib/input-safety.test.ts"
        src_path = "lib/helpers.ts"
        diff = diff_block(test_path, "expect(1).toBe(1);") + diff_block(src_path, "export function noop() {}")
        self.serve([test_path, src_path], diff, tests={test_path: b"expect(1).toBe(1);\n"})
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertNotIn("## Safety-state durability", man)
        self.assertNotIn("Safety-state durability", r.stdout)

    def test_safety_state_durability_no_fire_manifest_unchanged(self):
        diff = diff_block("src/a.py")
        self.serve(["src/a.py"], diff)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.out / "MANIFEST.md").read_text(), FIXTURE.read_text())




    def test_safety_state_durability_skips_prose_and_bundler_detector(self):
        bundler = "skillsets/pr-review/shared/high-signal-pr-review/scripts/hermes-bundle.py"
        md = "docs/incident-runbook.md"
        agents = "GLOBAL_AGENTS.md"
        diff = (
            diff_block(bundler, "# detector tweak")
            + (
                f"diff --git a/{md} b/{md}\n"
                f"--- a/{md}\n+++ b/{md}\n"
                "@@ -1,1 +1,1 @@\n"
                "-When quarantine triggers, document the workflow.\n"
                "+When quarantine triggers, document the workflow for reviewers.\n"
            )
            + (
                f"diff --git a/{agents} b/{agents}\n"
                f"--- a/{agents}\n+++ b/{agents}\n"
                "@@ -1,1 +1,1 @@\n"
                "-No quarantine here.\n"
                "+Browser quarantine must survive restart.\n"
            )
        )
        self.serve([bundler, md, agents], diff)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertNotIn("## Safety-state durability", man)
        self.assertNotIn("Safety-state durability", r.stdout)

    def test_safety_state_durability_lockfile_and_clock_excluded_target_lock_included(self):
        diff = (
            diff_block("pnpm-lock.yaml", "lockfileVersion: 9")
            + diff_block("src/clock.ts", "export const tick = () => 1;")
            + diff_block("lib/target-lock.ts", "export const held = true;")
        )
        self.serve(["pnpm-lock.yaml", "src/clock.ts", "lib/target-lock.ts"], diff)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        man = (self.out / "MANIFEST.md").read_text()
        self.assertIn("## Safety-state durability", man)
        idx = man.index("## Safety-state durability")
        section = man[idx:].split("\n## ", 1)[0]
        self.assertIn("lib/target-lock.ts", section)
        self.assertNotIn("pnpm-lock.yaml", section)
        self.assertNotIn("src/clock.ts", section)
        diff_only = diff_block("pnpm-lock.yaml", "lockfileVersion: 9") + diff_block(
            "src/clock.ts", "export const tick = () => 1;"
        )
        self.out = self.tmp / "out2"
        self.serve(["pnpm-lock.yaml", "src/clock.ts"], diff_only)
        r2 = self.run_script()
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertNotIn("## Safety-state durability", (self.out / "MANIFEST.md").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
