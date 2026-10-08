from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts/realdata-replay-gate.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, text=True,
                          capture_output=True).stdout.strip()


def replay_report(candidate_count: int = 3, note: str = "", reason: str = "source_revision_conflict",
                  error_class: str = "none", blocked: bool = False,
                  prose_blocked: bool = False) -> str:
    body = f"""# REALDATA-REPLAY

- Copy time (UTC): 2026-10-06T23:00:00Z
- Control SHA: 0123456789abcdef0123456789abcdef01234567
- Candidate SHA: 89abcdef0123456789abcdef0123456789abcdef
- Local copy: Mac-local database bound to loopback only; production data never leaves the Mac.
- Production source: read-only; no production writes were performed.
- Privacy: counts only; no row IDs or PII are included.
- Blocked rows: {2 if blocked or prose_blocked else 0}; external provider boundary was not needed for this replay.

| Goal | Target rows | Control count | Candidate count | Verdict | Reason | Error class |
|---|---:|---:|---:|---|---|---|
| repair ingestion projection | 3 | 0 | {candidate_count} | {"BLOCKED" if blocked else "PASS"} | {reason} | {error_class} |
{note or ('- A2 verdict: BLOCKED at page-member identity. Not run; blocked rows are held for read-back.' if prose_blocked else '')}'''
"""
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return body + f"- Artifact SHA-256 (excluding this line): {digest}\n"


class RealdataReplayGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "pallium-app"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "develop")
        git(self.repo, "config", "user.email", "gate@example.invalid")
        git(self.repo, "config", "user.name", "Gate fixture")
        git(self.repo, "remote", "add", "origin", "https://github.com/palliumai-com/pallium-app.git")
        (self.repo / "README.md").write_text("baseline\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/develop", self.base)
        git(self.repo, "update-ref", "refs/remotes/origin/main", self.base)
        (self.repo / "src/server/ingestion").mkdir(parents=True)
        (self.repo / "src/server/ingestion/worker.ts").write_text("candidate\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "data fix")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def check(self, action: str = "review", command: str = "pre-review.py",
              env: dict[str, str] | None = None, default_base: bool = False,
              base_arg: str | None = None
              ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        args = [sys.executable, str(GATE), "check", "--repo", str(self.repo)]
        if not default_base:
            args.extend(("--base", base_arg or self.base))
        args.extend(("--action", action, "--command", command, "--json"))
        result = subprocess.run(args,
                                text=True, capture_output=True, env=env)
        return result, json.loads(result.stdout)

    def merge_with_manual_conflict_resolution(self, conflict_path: str) -> tuple[str, str]:
        git(self.repo, "reset", "--hard", self.base)
        conflicted = self.repo / conflict_path
        conflicted.parent.mkdir(parents=True, exist_ok=True)
        conflicted.write_text("base-side\n", encoding="utf-8")
        git(self.repo, "add", conflict_path)
        git(self.repo, "commit", "-m", "add conflict fixture base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/develop", self.base)
        git(self.repo, "update-ref", "refs/remotes/origin/main", self.base)
        git(self.repo, "checkout", "-b", "feature")
        conflicted.write_text("feature-side\n", encoding="utf-8")
        git(self.repo, "add", conflict_path)
        git(self.repo, "commit", "-m", "feature change")

        report = replay_report()
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "feature replay report")

        git(self.repo, "checkout", "-b", "develop-source", self.base)
        conflicted.write_text("develop-side\n", encoding="utf-8")
        git(self.repo, "add", conflict_path)
        git(self.repo, "commit", "-m", "develop conflict change")
        develop_head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/develop", develop_head)

        git(self.repo, "checkout", "feature")
        merge = subprocess.run(["git", "merge", "--no-ff", "develop-source", "-m", "merge develop"],
                               cwd=self.repo, text=True, capture_output=True)
        self.assertNotEqual(merge.returncode, 0, "fixture must produce a merge conflict")
        conflicted.write_text("manual-resolution\n", encoding="utf-8")
        git(self.repo, "add", conflict_path)
        git(self.repo, "commit", "-m", "resolve merge conflict")
        return develop_head, git(self.repo, "rev-parse", "HEAD")

    def merge_develop_report_then_advance_develop(self) -> tuple[str, str]:
        git(self.repo, "reset", "--hard", self.base)
        git(self.repo, "checkout", "-b", "feature")
        source = self.repo / "src/server/ingestion/worker.ts"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("feature production-data change\n", encoding="utf-8")
        git(self.repo, "add", "src/server/ingestion/worker.ts")
        git(self.repo, "commit", "-m", "feature production-data change")

        git(self.repo, "checkout", "-b", "develop-source", self.base)
        report = replay_report(note="- Develop replay report.")
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "develop replay report")

        git(self.repo, "checkout", "feature")
        git(self.repo, "merge", "--no-ff", "develop-source", "-m", "merge develop report")

        git(self.repo, "checkout", "develop-source")
        (self.repo / "README.md").write_text("develop advanced without changing report\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "advance develop without report change")
        develop_head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/develop", develop_head)
        git(self.repo, "checkout", "feature")
        return develop_head, git(self.repo, "rev-parse", "HEAD")

    def merge_with_report_conflict_resolution(self) -> tuple[str, str]:
        git(self.repo, "reset", "--hard", self.base)
        base_report = replay_report(note="- Base report.")
        (self.repo / "REALDATA-REPLAY.md").write_text(base_report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "base replay report")
        report_base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/develop", report_base)

        git(self.repo, "checkout", "-b", "feature")
        source = self.repo / "src/server/ingestion/worker.ts"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("feature production-data change\n", encoding="utf-8")
        git(self.repo, "add", "src/server/ingestion/worker.ts")
        git(self.repo, "commit", "-m", "feature production-data change")
        feature_report = replay_report(note="- Feature report.")
        (self.repo / "REALDATA-REPLAY.md").write_text(feature_report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "feature replay report")

        git(self.repo, "checkout", "-b", "develop-source", report_base)
        develop_report = replay_report(note="- Develop report.")
        (self.repo / "REALDATA-REPLAY.md").write_text(develop_report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "develop replay report revision")
        develop_head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/develop", develop_head)

        git(self.repo, "checkout", "feature")
        merge = subprocess.run(["git", "merge", "--no-ff", "develop-source", "-m", "merge report revision"],
                               cwd=self.repo, text=True, capture_output=True)
        self.assertNotEqual(merge.returncode, 0, "report fixture must produce a merge conflict")
        resolved_report = replay_report(note="- Replay report resolved at the merge.")
        (self.repo / "REALDATA-REPLAY.md").write_text(resolved_report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "resolve replay report conflict")
        return develop_head, git(self.repo, "rev-parse", "HEAD")

    def gate_module(self):
        from importlib.util import module_from_spec, spec_from_file_location
        spec = spec_from_file_location("realdata_gate_for_gh_tests", GATE)
        assert spec and spec.loader
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def install_account_gh_stub(self, mode: str) -> tuple[dict[str, str], Path]:
        fake_bin = self.repo / "account-gh-bin"
        fake_bin.mkdir(exist_ok=True)
        gh = fake_bin / "gh"
        gh.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
mode = os.environ["GH_TEST_MODE"]
log = Path(os.environ["GH_TEST_LOG"])
def record():
    rows = json.loads(log.read_text()) if log.exists() else []
    rows.append({"args": args, "token_present": bool(os.environ.get("GH_TOKEN")),
                 "second_account": os.environ.get("GH_TOKEN") == "token-second-account"})
    log.write_text(json.dumps(rows))
if args[:3] == ["auth", "status", "--hostname"]:
    print("Logged in to github.com account first-account (keyring)\\nLogged in to github.com account second-account (keyring)")
    sys.exit(0)
if args[:3] == ["auth", "token", "--user"]:
    print("token-" + args[3])
    sys.exit(0)
if args[:2] == ["pr", "view"]:
    record()
    if mode == "ambient-then-second" and os.environ.get("GH_TOKEN") == "token-second-account":
        print(json.dumps({"body":"report cited", "headRefOid":"abc", "baseRefOid":"base", "files":[{"path":"src/server/ingestion/job.ts"}]}))
        sys.exit(0)
    if mode == "ambient-success" and not os.environ.get("GH_TOKEN"):
        print(json.dumps({"body":"report cited", "headRefOid":"abc", "baseRefOid":"base", "files":[{"path":"src/server/ingestion/job.ts"}]}))
        sys.exit(0)
    print("denied", file=sys.stderr)
    sys.exit(1)
sys.exit(2)
''', encoding="utf-8")
        gh.chmod(0o755)
        log = self.repo / "gh-calls.json"
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        env["GH_TEST_MODE"] = mode
        env["GH_TEST_LOG"] = str(log)
        return env, log

    def test_pr_info_retries_second_logged_in_account_and_forwards_repo(self) -> None:
        env, log = self.install_account_gh_stub("ambient-then-second")
        env["GH_TOKEN"] = "ambient-token"
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, env, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
            info = self.gate_module().pull_request_info(
                self.repo, "gh pr ready 1701 -R palliumai-com/pallium-app")
        self.assertIsNotNone(info)
        self.assertEqual(info["files"], [{"path": "src/server/ingestion/job.ts"}])
        calls = json.loads(log.read_text())
        self.assertEqual(len(calls), 3)
        self.assertIn(["--repo", "palliumai-com/pallium-app"],
                      [calls[0]["args"][i:i + 2] for i in range(len(calls[0]["args"]) - 1)])
        self.assertFalse(calls[1]["second_account"])
        self.assertTrue(calls[2]["second_account"])
        self.assertNotIn("token-second-account", stdout.getvalue() + stderr.getvalue() + json.dumps(info))

    def test_pr_info_derives_github_repo_when_command_has_no_repo_flag(self) -> None:
        env, log = self.install_account_gh_stub("ambient-success")
        env.pop("GH_TOKEN", None)
        with patch.dict(os.environ, env, clear=True):
            info = self.gate_module().pull_request_info(self.repo, "gh pr ready 1701")
        self.assertIsNotNone(info)
        calls = json.loads(log.read_text())
        self.assertIn(["--repo", "palliumai-com/pallium-app"],
                      [calls[0]["args"][i:i + 2] for i in range(len(calls[0]["args"]) - 1)])

    def test_pr_info_fails_closed_when_every_logged_in_account_fails(self) -> None:
        env, _ = self.install_account_gh_stub("all-fail")
        env["GH_TOKEN"] = "ambient-token"
        result, payload = self.check("pr", "gh pr ready 1701 -R palliumai-com/pallium-app", env)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertIn("cannot read the target PR's changed files", payload["reason"])
        self.assertNotIn("token-", result.stdout + result.stderr)

    def test_missing_artifact_fails_then_valid_artifact_passes(self) -> None:
        missing, missing_json = self.check()
        self.assertEqual(missing.returncode, 2)
        self.assertFalse(missing_json["allowed"])
        self.assertIn("missing REALDATA-REPLAY.md", missing_json["reason"])

        (self.repo / "REALDATA-REPLAY.md").write_text(replay_report(), encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit valid report")
        passed, passed_json = self.check()
        self.assertEqual(passed.returncode, 0)
        self.assertTrue(passed_json["allowed"])
        self.assertEqual(passed_json["artifact"], "REALDATA-REPLAY.md")
        self.assertRegex(str(passed_json["sha256"]), r"^[0-9a-f]{64}$")

    def test_local_clone_with_pallium_package_identity_is_gated(self) -> None:
        clone = Path(self.temp.name) / "repo"
        self.repo.rename(clone)
        self.repo = clone
        git(self.repo, "remote", "set-url", "origin",
            "ssh://hsrpc-wsl/home/alex_/projects/pallium/pallium-app")
        (self.repo / "package.json").write_text('{"name":"pallium-app"}\n', encoding="utf-8")
        git(self.repo, "add", "package.json")
        git(self.repo, "commit", "-m", "identify Pallium clone")

        denied, payload = self.check()
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["reason"], "missing REALDATA-REPLAY.md at reviewed head")
        self.assertIn("src/server/ingestion/worker.ts", payload["affected_paths"])

    def test_package_name_identifies_clone_with_unrelated_local_remote(self) -> None:
        clone = Path(self.temp.name) / "another-clone"
        self.repo.rename(clone)
        self.repo = clone
        git(self.repo, "remote", "set-url", "origin", "../upstream.git")
        (self.repo / "package.json").write_text('{"name":"pallium-app"}\n', encoding="utf-8")
        git(self.repo, "add", "package.json")
        git(self.repo, "commit", "-m", "identify Pallium package")

        denied, payload = self.check()
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["reason"], "missing REALDATA-REPLAY.md at reviewed head")

    def test_hermes_must_attach_report_or_a_packet_that_cites_it(self) -> None:
        report = replay_report()
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit valid report")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        missing_citation, _ = self.check("review", "bb fleet validate 'review data fix'")
        self.assertEqual(missing_citation.returncode, 2)
        command_only_citation, _ = self.check("review", f"bb fleet validate 'REALDATA-REPLAY.md {digest}'")
        self.assertEqual(command_only_citation.returncode, 2)
        packet_only, _ = self.check("review", f"bb fleet validate --evidence packet.md")
        self.assertEqual(packet_only.returncode, 2)
        with_citation, _ = self.check("review", "bb fleet validate --evidence REALDATA-REPLAY.md")
        self.assertEqual(with_citation.returncode, 0)

    def test_digest_tampering_fails(self) -> None:
        report = replay_report().replace("| 3 | 0 | 3 |", "| 3 | 0 | 4 |")
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit tampered report")
        result, payload = self.check()
        self.assertEqual(result.returncode, 2)
        self.assertIn("SHA-256 does not match", payload["reason"])
        self.assertIn("likely stale footer", payload["reason"])

    def test_release_requires_committed_report_and_citation(self) -> None:
        report = replay_report()
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        missing_commit, _ = self.check("release", "release-request --evidence REALDATA-REPLAY.md")
        self.assertEqual(missing_commit.returncode, 2)
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "attach replay")
        request = self.repo / "release-request.md"
        request.write_text(
            f"Evidence: {request.parent / 'REALDATA-REPLAY.md'} SHA-256 {digest}\n"
            "Post-release read-back +30 minutes: affected-goal counts and reason/error-class counts.\n"
            "Rollback target: d9038526c5436cdd24dd8ed2a7e5ca3b84416e06.\n", encoding="utf-8")
        allowed, _ = self.check("release", "release-request --body-file release-request.md")
        self.assertEqual(allowed.returncode, 0)

    def test_release_defaults_to_origin_main_and_requires_replay(self) -> None:
        git(self.repo, "update-ref", "refs/remotes/origin/main", self.base)
        git(self.repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
        denied, payload = self.check("release", "release-request", default_base=True)
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertIn("missing REALDATA-REPLAY.md", payload["reason"])

        report = replay_report(blocked=True)
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit release replay")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        request = self.repo / "release-request.md"
        request.write_text(
            f"REALDATA-REPLAY.md SHA-256 {digest}\n"
            "Post-release read-back +30 minutes: affected-goal counts, BLOCKED row counts, reason and error-class counts.\n"
            "Rollback target: d9038526c5436cdd24dd8ed2a7e5ca3b84416e06.\n", encoding="utf-8")
        allowed, payload = self.check("release", f"release-request --body-file {request}", default_base=True)
        self.assertEqual(allowed.returncode, 0, payload["reason"])
        self.assertTrue(payload["allowed"])

    def test_release_denies_when_origin_main_is_missing(self) -> None:
        git(self.repo, "update-ref", "-d", "refs/remotes/origin/main")
        git(self.repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
        denied, payload = self.check("release", "release-request", default_base=True)
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertIn("cannot resolve production branch refs/remotes/origin/main", payload["reason"])

    def test_release_explicit_base_cannot_hide_changes_since_origin_main(self) -> None:
        # origin/main has no data-path change, while the explicit release base
        # already contains it. The release check must still include main's diff.
        git(self.repo, "update-ref", "refs/remotes/origin/main", self.base)
        git(self.repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
        denied, payload = self.check("release", "release-request", base_arg="HEAD")
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertIn("missing REALDATA-REPLAY.md", payload["reason"])

        report = replay_report()
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit replay for explicit-base release")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        request = self.repo / "release-request.md"
        request.write_text(f"REALDATA-REPLAY.md SHA-256 {digest}\n", encoding="utf-8")
        denied_plan, payload = self.check("release", f"release-request --body-file {request}", base_arg="HEAD~1")
        self.assertEqual(denied_plan.returncode, 2)
        self.assertIn("post-release read-back offset and counts", payload["reason"])

        request.write_text(
            f"REALDATA-REPLAY.md SHA-256 {digest}\n"
            "Post-release read-back +30 minutes: affected-goal counts and reason/error-class counts.\n"
            "Rollback target: d9038526c5436cdd24dd8ed2a7e5ca3b84416e06.\n", encoding="utf-8")
        allowed, payload = self.check("release", f"release-request --body-file {request}", base_arg="HEAD~1")
        self.assertEqual(allowed.returncode, 0, payload["reason"])
        self.assertTrue(payload["allowed"])

    def test_release_ignores_ambiguous_local_origin_main(self) -> None:
        # The remote-tracking ref is the production baseline, but a conflicting
        # local branch at HEAD would make the shorthand origin/main miss changes.
        git(self.repo, "update-ref", "refs/remotes/origin/main", self.base)
        git(self.repo, "branch", "origin/main", "HEAD")
        denied, payload = self.check("release", "release-request", default_base=True)
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertIn("missing REALDATA-REPLAY.md", payload["reason"])

    def test_release_older_explicit_base_cannot_admit_inherited_production_report(self) -> None:
        git(self.repo, "reset", "--hard", self.base)
        source = self.repo / "src/server/repositories/integrations/ingestion-work-auto-rearm.repository.ts"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("export const fixture = 0;\n", encoding="utf-8")
        git(self.repo, "add", "src/server/repositories/integrations/ingestion-work-auto-rearm.repository.ts")
        git(self.repo, "commit", "-m", "older base without report")
        older = git(self.repo, "rev-parse", "HEAD")

        production_report = replay_report()
        (self.repo / "REALDATA-REPLAY.md").write_text(production_report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "production report")
        production = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/main", production)
        git(self.repo, "update-ref", "refs/remotes/origin/develop", production)

        source.write_text("export const fixture = 1;\n", encoding="utf-8")
        git(self.repo, "add", "src/server/repositories/integrations/ingestion-work-auto-rearm.repository.ts")
        git(self.repo, "commit", "-m", "candidate source change inheriting report")
        inherited_digest = production_report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        request = self.repo / "release-request.md"
        request.write_text(
            f"REALDATA-REPLAY.md SHA-256 {inherited_digest}\n"
            "Read-back +30 min counts: affected goals, blocked rows, reasons and error classes.\n"
            "Rollback target: d9038526c5436cdd24dd8ed2a7e5ca3b84416e06.\n", encoding="utf-8")

        denied, payload = self.check("release", f"release-request --body-file {request}", base_arg=older)
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertIn("report inherited from base; replay this change", payload["reason"])

        candidate_report = replay_report(note="- Own candidate replay for this release.")
        (self.repo / "REALDATA-REPLAY.md").write_text(candidate_report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "candidate-owned report")
        candidate_digest = candidate_report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        request.write_text(
            f"REALDATA-REPLAY.md SHA-256 {candidate_digest}\n"
            "Read-back +30 min counts: affected goals, blocked rows, reasons and error classes.\n"
            "Rollback target: d9038526c5436cdd24dd8ed2a7e5ca3b84416e06.\n", encoding="utf-8")
        allowed, payload = self.check("release", f"release-request --body-file {request}", base_arg=older)
        self.assertEqual(allowed.returncode, 0, payload["reason"])
        self.assertTrue(payload["allowed"])

    def test_stacked_child_must_refresh_inherited_parent_report(self) -> None:
        git(self.repo, "reset", "--hard", self.base)
        git(self.repo, "update-ref", "refs/remotes/origin/main", self.base)
        git(self.repo, "update-ref", "refs/remotes/origin/develop", self.base)
        source = self.repo / "src/server/ingestion/worker.ts"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("parent data change\n", encoding="utf-8")
        git(self.repo, "add", "src/server/ingestion/worker.ts")
        git(self.repo, "commit", "-m", "parent production-data change")
        parent_code = git(self.repo, "rev-parse", "HEAD")

        parent_report = replay_report()
        (self.repo / "REALDATA-REPLAY.md").write_text(parent_report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "parent replay report")
        source.write_text("child data change\n", encoding="utf-8")
        git(self.repo, "add", "src/server/ingestion/worker.ts")
        git(self.repo, "commit", "-m", "stacked child production-data change")
        child_code = git(self.repo, "rev-parse", "HEAD")

        parent_digest = parent_report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        request = self.repo / "release-request.md"
        request.write_text(
            f"REALDATA-REPLAY.md SHA-256 {parent_digest}\n"
            "Read-back +30 min counts: affected goals and blocked rows.\n"
            "Rollback target: d9038526c5436cdd24dd8ed2a7e5ca3b84416e06.\n", encoding="utf-8")
        release_denied, release_payload = self.check(
            "release", f"release-request --body-file {request}", default_base=True)
        self.assertEqual(release_denied.returncode, 2)
        self.assertIn(child_code[:8], release_payload["reason"])
        review_denied, review_payload = self.check("review", "pre-review.py", default_base=True)
        self.assertEqual(review_denied.returncode, 2)
        self.assertIn(child_code[:8], review_payload["reason"])

        child_report = replay_report(note="- Refreshed for the stacked child production-data change.")
        (self.repo / "REALDATA-REPLAY.md").write_text(child_report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "stacked child replay report")
        child_digest = child_report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        request.write_text(
            f"REALDATA-REPLAY.md SHA-256 {child_digest}\n"
            "Read-back +30 min counts: affected goals and blocked rows.\n"
            "Rollback target: d9038526c5436cdd24dd8ed2a7e5ca3b84416e06.\n", encoding="utf-8")
        release_allowed, release_payload = self.check(
            "release", f"release-request --body-file {request}", default_base=True)
        self.assertEqual(release_allowed.returncode, 0, release_payload["reason"])
        review_allowed, review_payload = self.check("review", "pre-review.py", default_base=True)
        self.assertEqual(review_allowed.returncode, 0, review_payload["reason"])
        self.assertTrue(review_payload["allowed"])

    def test_production_data_commit_after_report_is_denied(self) -> None:
        git(self.repo, "reset", "--hard", self.base)
        git(self.repo, "update-ref", "refs/remotes/origin/develop", self.base)
        source = self.repo / "src/server/projections/account.ts"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("first data change\n", encoding="utf-8")
        git(self.repo, "add", "src/server/projections/account.ts")
        git(self.repo, "commit", "-m", "first production-data change")
        report = replay_report()
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "replay report")
        source.write_text("second data change after replay\n", encoding="utf-8")
        git(self.repo, "add", "src/server/projections/account.ts")
        git(self.repo, "commit", "-m", "production-data change after replay")
        late_code = git(self.repo, "rev-parse", "HEAD")
        denied, payload = self.check("review", "pre-review.py", default_base=True)
        self.assertEqual(denied.returncode, 2)
        self.assertIn("a production-data change postdates REALDATA-REPLAY.md", payload["reason"])
        self.assertIn(late_code[:8], payload["reason"])

    def test_develop_merge_data_commits_do_not_make_report_stale(self) -> None:
        git(self.repo, "reset", "--hard", self.base)
        git(self.repo, "checkout", "-b", "feature")
        feature_source = self.repo / "src/server/ingestion/worker.ts"
        feature_source.parent.mkdir(parents=True, exist_ok=True)
        feature_source.write_text("feature data change\n", encoding="utf-8")
        git(self.repo, "add", "src/server/ingestion/worker.ts")
        git(self.repo, "commit", "-m", "feature production-data change")
        report = replay_report()
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "feature replay report")

        git(self.repo, "branch", "-f", "develop", self.base)
        git(self.repo, "checkout", "develop")
        develop_source = self.repo / "src/server/projections/develop-owned.ts"
        develop_source.parent.mkdir(parents=True, exist_ok=True)
        develop_source.write_text("develop data change\n", encoding="utf-8")
        git(self.repo, "add", "src/server/projections/develop-owned.ts")
        git(self.repo, "commit", "-m", "develop production-data change")
        git(self.repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
        git(self.repo, "checkout", "feature")
        git(self.repo, "merge", "--no-ff", "develop", "-m", "merge develop")

        allowed, payload = self.check("review", "pre-review.py", default_base=True)
        self.assertEqual(allowed.returncode, 0, payload["reason"])
        self.assertTrue(payload["allowed"])

    def test_production_merge_resolution_after_report_is_denied(self) -> None:
        develop_head, merge_commit = self.merge_with_manual_conflict_resolution(
            "src/server/ingestion/worker.ts")
        denied, payload = self.check("review", "pre-review.py", base_arg=develop_head)
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertIn("production-data change postdates REALDATA-REPLAY.md", payload["reason"])
        self.assertIn(merge_commit[:8], payload["reason"])

    def test_refreshed_report_after_production_merge_resolution_is_allowed(self) -> None:
        develop_head, _ = self.merge_with_manual_conflict_resolution(
            "src/server/ingestion/worker.ts")
        report = replay_report(note="- Refreshed after the production merge conflict resolution.")
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "refresh report after production merge resolution")
        allowed, payload = self.check("review", "pre-review.py", base_arg=develop_head)
        self.assertEqual(allowed.returncode, 0, payload["reason"])
        self.assertTrue(payload["allowed"])

    def test_nonproduction_merge_resolution_does_not_make_report_stale(self) -> None:
        develop_head, _ = self.merge_with_manual_conflict_resolution("docs/notes.md")
        allowed, payload = self.check("review", "pre-review.py", base_arg=develop_head)
        self.assertEqual(allowed.returncode, 0, payload["reason"])
        self.assertTrue(payload["allowed"])

    def test_unavailable_remerge_diff_fails_closed(self) -> None:
        develop_head, _ = self.merge_with_manual_conflict_resolution(
            "src/server/ingestion/worker.ts")
        module = self.gate_module()
        real_git = module.git

        def git_without_remerge_diff(repo: Path, *args: str, timeout: float = 4) -> str:
            if args and args[0] == "show" and "--remerge-diff" in args:
                raise RuntimeError("unsupported remerge diff")
            return real_git(repo, *args, timeout=timeout)

        with patch.object(module, "git", side_effect=git_without_remerge_diff):
            allowed, reason, _, _ = module.evaluate(
                self.repo, develop_head, "review", command="pre-review.py")
        self.assertFalse(allowed)
        self.assertIn("cannot inspect merge resolution", reason)
        self.assertIn("--remerge-diff", reason)

    def test_report_inherited_from_moved_develop_is_denied(self) -> None:
        develop_head, _ = self.merge_develop_report_then_advance_develop()
        denied, payload = self.check("review", "pre-review.py", base_arg=develop_head)
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertIn("report inherited from base", payload["reason"])

    def test_refreshed_report_after_develop_moves_is_allowed(self) -> None:
        develop_head, _ = self.merge_develop_report_then_advance_develop()
        refreshed = replay_report(note="- Feature-owned replay after develop advanced.")
        (self.repo / "REALDATA-REPLAY.md").write_text(refreshed, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "feature refreshes replay report")
        allowed, payload = self.check("review", "pre-review.py", base_arg=develop_head)
        self.assertEqual(allowed.returncode, 0, payload["reason"])
        self.assertTrue(payload["allowed"])

    def test_manual_report_conflict_resolution_is_report_owner(self) -> None:
        develop_head, merge_commit = self.merge_with_report_conflict_resolution()
        changed_paths = git(self.repo, "show", "--remerge-diff", "--format=", "--name-only", merge_commit)
        self.assertIn("REALDATA-REPLAY.md", changed_paths.splitlines())
        allowed, payload = self.check("review", "pre-review.py", base_arg=develop_head)
        self.assertEqual(allowed.returncode, 0, payload["reason"])
        self.assertTrue(payload["allowed"])

    def test_review_default_base_remains_origin_develop(self) -> None:
        git(self.repo, "update-ref", "refs/remotes/origin/develop", self.base)
        denied, payload = self.check("review", "pre-review.py", default_base=True)
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertIn("missing REALDATA-REPLAY.md", payload["reason"])

    def test_inherited_report_is_denied_but_report_changed_in_branch_is_allowed(self) -> None:
        # Put a valid report on the PR base, then make a data-path change without
        # changing it. Inherited evidence must not validate a different change.
        git(self.repo, "reset", "--hard", self.base)
        inherited = replay_report()
        (self.repo / "REALDATA-REPLAY.md").write_text(inherited, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "base replay report")
        report_base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/develop", report_base)

        (self.repo / "src/server/ingestion/worker.ts").parent.mkdir(parents=True, exist_ok=True)
        (self.repo / "src/server/ingestion/worker.ts").write_text("branch change\n", encoding="utf-8")
        git(self.repo, "add", "src/server/ingestion/worker.ts")
        git(self.repo, "commit", "-m", "change ingestion without replay")
        denied, payload = self.check("review", "pre-review.py", base_arg=report_base)
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertIn("report inherited from base; replay this change", payload["reason"])

        updated = replay_report(note="- Replay updated for this branch change.")
        (self.repo / "REALDATA-REPLAY.md").write_text(updated, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "update replay for ingestion change")
        allowed, payload = self.check("review", "pre-review.py", base_arg=report_base)
        self.assertEqual(allowed.returncode, 0, payload["reason"])
        self.assertTrue(payload["allowed"])

    def test_blocked_report_denies_digest_only_release_request(self) -> None:
        report = replay_report(blocked=True)
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit report with blocked rows")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        request = self.repo / "release-request.md"
        request.write_text(f"REALDATA-REPLAY.md SHA-256 {digest}\n", encoding="utf-8")
        denied, payload = self.check("release", f"release-request --body-file {request}")
        self.assertEqual(denied.returncode, 2)
        self.assertIn("post-release read-back offset and counts", payload["reason"])

    def test_blocked_report_allows_release_with_readback_and_rollback(self) -> None:
        report = replay_report(blocked=True)
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit report with blocked rows")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        request = self.repo / "release-request.md"
        request.write_text(
            f"REALDATA-REPLAY.md SHA-256 {digest}\n"
            "Post-release read-back +30 minutes: affected-goal counts, BLOCKED row counts, reason and error-class counts.\n"
            "Rollback target: d9038526c5436cdd24dd8ed2a7e5ca3b84416e06.\n", encoding="utf-8")
        allowed, payload = self.check("release", f"release-request --body-file {request}")
        self.assertEqual(allowed.returncode, 0, payload["reason"])
        self.assertTrue(payload["allowed"])

    def test_prose_blocked_rows_still_deny_digest_only_release(self) -> None:
        report = replay_report(prose_blocked=True)
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit report with prose blocked rows")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        request = self.repo / "release-request.md"
        request.write_text(f"REALDATA-REPLAY.md SHA-256 {digest}\n", encoding="utf-8")
        denied, payload = self.check("release", f"release-request --body-file {request}")
        self.assertEqual(denied.returncode, 2)
        self.assertIn("post-release read-back offset and counts", payload["reason"])

    def test_report_without_blocked_rows_still_requires_release_plan(self) -> None:
        report = replay_report()
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit unblocked report")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        request = self.repo / "release-request.md"
        request.write_text(f"REALDATA-REPLAY.md SHA-256 {digest}\n", encoding="utf-8")
        denied, payload = self.check("release", f"release-request --body-file {request}")
        self.assertEqual(denied.returncode, 2)
        self.assertIn("post-release read-back offset and counts", payload["reason"])

    def test_pr_create_rejects_cited_unstaged_report_different_from_committed_blob(self) -> None:
        committed = replay_report(candidate_count=3)
        (self.repo / "REALDATA-REPLAY.md").write_text(committed, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit report A")

        unstaged = replay_report(candidate_count=4)
        (self.repo / "REALDATA-REPLAY.md").write_text(unstaged, encoding="utf-8")
        digest_b = unstaged.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        request = self.repo / "pr-body.md"
        request.write_text(f"REALDATA-REPLAY.md SHA-256 {digest_b}\n", encoding="utf-8")

        denied, payload = self.check("pr-create", f"gh pr create --body-file {request}")
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertIn("has uncommitted changes", payload["reason"])

    def test_review_rejects_report_that_is_only_uncommitted(self) -> None:
        (self.repo / "REALDATA-REPLAY.md").write_text(replay_report(), encoding="utf-8")
        denied, payload = self.check("review", "bb fleet validate --evidence REALDATA-REPLAY.md")
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])
        self.assertIn("missing REALDATA-REPLAY.md at reviewed head", payload["reason"])

    def assert_sensitive_report_denied(self, marker: str) -> None:
        report = replay_report(reason=marker)
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit report with identifying content")
        denied, payload = self.check()
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(payload["allowed"])

    def test_object_id_in_reason_cell_is_rejected(self) -> None:
        self.assert_sensitive_report_denied("64f1a2b3c4d5e6f789012345")

    def test_email_in_reason_cell_is_rejected(self) -> None:
        self.assert_sensitive_report_denied("operator@example.com")

    def test_credentialed_uri_in_reason_cell_is_rejected(self) -> None:
        self.assert_sensitive_report_denied("postgres://user:password@db.example.invalid/prod")

    def test_labelled_personal_name_in_reason_cell_is_rejected(self) -> None:
        self.assert_sensitive_report_denied("patient name: Example Person")

    def test_underscore_patient_name_in_reason_cell_is_rejected(self) -> None:
        self.assert_sensitive_report_denied("patient_name: Alice")

    def test_hyphenated_patient_name_in_reason_cell_is_rejected(self) -> None:
        self.assert_sensitive_report_denied("patient-name: Alice")

    def test_long_numeric_identifier_in_reason_cell_is_rejected(self) -> None:
        self.assert_sensitive_report_denied("123456789012")

    def test_phone_like_number_in_reason_cell_is_rejected(self) -> None:
        for phone in ("+1 555 123 4567", "+44 20 7946 0958", "(555) 123-4567",
                      "555-123-4567", "555.123.4567"):
            with self.subTest(phone=phone):
                self.assert_sensitive_report_denied(phone)

    def test_ordinary_dates_and_counts_are_allowed_in_reason_cells(self) -> None:
        for text in ("Copy time 2026-10-07 03:41Z", "window (2026-10-06) 21:59",
                     "counts 1 2 3 4 5 6 7 8 9", "10 12 22 25 2 0"):
            with self.subTest(text=text):
                report = replay_report(reason=text)
                (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
                git(self.repo, "add", "REALDATA-REPLAY.md")
                git(self.repo, "commit", "-m", "commit report with ordinary dates or counts")
                allowed, payload = self.check()
                self.assertEqual(allowed.returncode, 0, payload["reason"])
                self.assertTrue(payload["allowed"])

    def test_secret_patterns_in_report_are_rejected(self) -> None:
        for marker in ("Bearer abcdefghijklmnop", "eyJhbGciOiJIUzI1NiJ9.payload.signature",
                       "api_key=topsecret", "secret=topsecret", "password=topsecret", "key=topsecret"):
            with self.subTest(marker=marker):
                self.assert_sensitive_report_denied(marker)

    def test_plain_prose_reason_and_error_class_are_allowed(self) -> None:
        report = replay_report(reason="External provider fetch is required before settlement",
                               error_class="Provider response is pending")
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit report with descriptive text")
        allowed, payload = self.check()
        self.assertEqual(allowed.returncode, 0)
        self.assertTrue(payload["allowed"])

    def test_pr_ready_requires_report_digest_in_live_pr_body(self) -> None:
        report = replay_report()
        report_path = self.repo / "REALDATA-REPLAY.md"
        report_path.write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "attach replay")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        fake_bin = self.repo / "fake-bin"
        fake_bin.mkdir()
        gh = fake_bin / "gh"
        head = git(self.repo, "rev-parse", "HEAD")
        response = json.dumps({"body": f"{report_path.name} {digest}", "headRefOid": head, "baseRefOid": self.base,
                               "files": [{"path": "src/server/ingestion/worker.ts"},
                                         {"path": "REALDATA-REPLAY.md"}]})
        gh.write_text(f"#!/bin/sh\nprintf '%s\\n' '{response}'\n", encoding="utf-8")
        gh.chmod(0o755)
        import os
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        allowed, _ = self.check("pr", "gh pr ready", env, default_base=True)
        self.assertEqual(allowed.returncode, 0)

    def test_blocked_rows_do_not_add_readback_requirement_to_pr_ready_or_merge(self) -> None:
        report = replay_report(blocked=True)
        report_path = self.repo / "REALDATA-REPLAY.md"
        report_path.write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit blocked replay report")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        fake_bin = self.repo / "fake-gh-blocked-pr"
        fake_bin.mkdir()
        gh = fake_bin / "gh"
        head = git(self.repo, "rev-parse", "HEAD")
        response = json.dumps({"body": f"{report_path.name} {digest}", "headRefOid": head, "baseRefOid": self.base,
                               "files": [{"path": "src/server/ingestion/worker.ts"},
                                         {"path": report_path.name}]})
        gh.write_text(f"#!/bin/sh\nprintf '%s\\n' '{response}'\n", encoding="utf-8")
        gh.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        for command in ("gh pr ready 1701", "gh pr merge 1701"):
            with self.subTest(command=command):
                allowed, payload = self.check("pr", command, env)
                self.assertEqual(allowed.returncode, 0, payload["reason"])

    def hook(self, command: str, gate: Path = GATE) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        """Run the hook on a production-data change with no replay report; gh calls are recorded, never made."""
        fake_bin = self.repo / "hook-gh-bin"
        fake_bin.mkdir(exist_ok=True)
        log = self.repo / "hook-gh-calls.txt"
        (fake_bin / "gh").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexit 1\n', encoding="utf-8")
        (fake_bin / "gh").chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(self.repo)})
        result = subprocess.run([sys.executable, str(gate), "hook"], input=payload, text=True,
                                capture_output=True, env=env)
        return result, log.read_text().splitlines() if log.exists() else []

    def test_hook_never_denies_a_pr_merge(self) -> None:
        # Owner decision 2026-10-08: a PR merge is never denied, including for what its subject or body says;
        # nor is gh pr ready, since GitHub cannot merge a draft.
        for command in ("gh pr merge 1701 --admin --squash", "gh pr merge 1701", "gh pr ready 1701",
                        "gh pr merge 1701 --body 'after bb fleet validate and gh release create v1'",
                        'gh pr merge 1701 --subject "gh pr create; hermes-one.zsh" --squash',
                        "GH_TOKEN= gh pr merge 1701 --body 'release-request pre-review.py'"):
            with self.subTest(command=command):
                result, calls = self.hook(command)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(calls, [])  # the PR is not even looked up

    def test_hook_still_gates_what_runs_alongside_a_merge(self) -> None:
        for command in ("gh pr merge 1701 && gh release create v1", "gh pr merge 1701 --body \"$(bb fleet validate x)\"",
                        "gh pr create --fill", "bb fleet validate --evidence x", "gh release create v1"):
            with self.subTest(command=command):
                result, _ = self.hook(command)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("[realdata-replay-gate]", result.stdout)

    def test_hook_without_ship_gate_beside_it_allows_merges_and_other_commands(self) -> None:
        # The gate installs on its own; with no ship-gate.py next to it the raw command is classified.
        alone = Path(self.temp.name) / "alone/scripts"
        alone.mkdir(parents=True)
        (alone / GATE.name).write_bytes(GATE.read_bytes())
        (alone.parent / "realdata-paths.json").write_bytes((ROOT / "realdata-paths.json").read_bytes())
        for command, rc in (("ls", 0), ("gh pr merge 1701 --admin", 0), ("gh pr create --fill", 2)):
            with self.subTest(command=command):
                result, _ = self.hook(command, alone / GATE.name)
                self.assertEqual(result.returncode, rc, result.stdout + result.stderr)

    def test_hook_beside_a_broken_ship_gate_allows_merges_and_other_commands(self) -> None:
        # A stale or broken ship-gate.py, even one that exits while loading, must not deny every command.
        for name, source in (("exits", "import sys\nsys.exit(3)\n"), ("syntax", "def broken(:\n"),
                             ("no-view", "X = 1\n")):
            scripts = Path(self.temp.name) / name / "scripts"
            scripts.mkdir(parents=True)
            (scripts / GATE.name).write_bytes(GATE.read_bytes())
            (scripts / "ship-gate.py").write_text(source, encoding="utf-8")
            (scripts.parent / "realdata-paths.json").write_bytes((ROOT / "realdata-paths.json").read_bytes())
            for command, rc in (("ls", 0), ("gh pr merge 1701 --admin", 0), ("gh pr create --fill", 2)):
                with self.subTest(ship_gate=name, command=command):
                    result, _ = self.hook(command, scripts / GATE.name)
                    self.assertEqual(result.returncode, rc, result.stdout + result.stderr)

    def test_installed_hook_never_denies_a_merge_whatever_the_ship_gate_beside_it(self) -> None:
        # Through qa-ship-gate-hook.sh, as installed: it passes its own reading of the command (the awk view), which
        # decides whatever ship-gate.py is beside the gate, so a merge is never read as its body (Hermes r18, r19):
        # missing, failing to load, or loading with a ship_view that returns the raw command or nothing at all.
        hook = ROOT.parents[1] / "hooks/qa-ship-gate-hook.sh"
        rows = (("ls", 0), ("gh pr merge 1701 --admin --squash", 0), ("gh pr ready 1701", 0),
                ("gh pr merge 1701 --body 'notes on gh release create'", 0),
                ('gh pr merge 1701 --subject "bb fleet validate; gh pr create" --squash', 0),
                ("gh pr merge 1701 && gh release create v1", 2), ('gh pr merge 1701 --body "$(bb fleet validate x)"', 2),
                ("gh pr create --fill", 2), ("bb fleet validate --evidence x", 2))
        for name, source in (("working", (ROOT / "scripts/ship-gate.py").read_text(encoding="utf-8")),
                             ("missing", None), ("exits", "import sys\nsys.exit(3)\n"), ("syntax", "def broken(:\n"),
                             ("raw view", "def ship_view(command, depth=0):\n    return command\n"),
                             ("empty view", "def ship_view(command, depth=0):\n    return ''\n")):
            home = Path(self.temp.name) / f"home-{name}"
            scripts = home / ".agents/skills/qa-sweep/scripts"
            scripts.mkdir(parents=True)
            (scripts / GATE.name).write_bytes(GATE.read_bytes())
            (scripts.parent / "realdata-paths.json").write_bytes((ROOT / "realdata-paths.json").read_bytes())
            if source is not None:
                (scripts / "ship-gate.py").write_text(source, encoding="utf-8")
            fake_bin = home / "bin"
            fake_bin.mkdir()
            (fake_bin / "gh").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            (fake_bin / "gh").chmod(0o755)
            env = {**os.environ, "HOME": str(home), "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", "")}
            for command, rc in rows:
                with self.subTest(ship_gate=name, command=command):
                    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(self.repo)})
                    result = subprocess.run(["sh", str(hook)], input=payload, text=True, capture_output=True, env=env)
                    self.assertEqual(result.returncode, rc, result.stdout + result.stderr)
                    if rc:
                        self.assertIn("[realdata-replay-gate]", result.stderr)

    def test_installed_hook_with_an_empty_view_still_denies_gated_commands(self) -> None:
        # The real hook, its view forced empty (as a scanner fault would give): gated commands are denied from their
        # raw text, and a merge, whose empty view is its true reading, stays allowed.
        source = (ROOT.parents[1] / "hooks/qa-ship-gate-hook.sh").read_text(encoding="utf-8")
        forced = 'realdata_view=$(SHIP_SCAN_VIEW=1 ship_scan) || realdata_view="FLAT "'
        self.assertEqual(source.count(forced), 1)
        hook = Path(self.temp.name) / "empty-view-hook.sh"
        hook.write_text(source.replace(forced, 'realdata_view=""'), encoding="utf-8")
        home = Path(self.temp.name) / "home-empty-view"
        scripts = home / ".agents/skills/qa-sweep/scripts"
        scripts.mkdir(parents=True)
        (scripts / GATE.name).write_bytes(GATE.read_bytes())
        (scripts / "ship-gate.py").write_bytes((ROOT / "scripts/ship-gate.py").read_bytes())
        (scripts.parent / "realdata-paths.json").write_bytes((ROOT / "realdata-paths.json").read_bytes())
        env = {**os.environ, "HOME": str(home)}
        for command, rc in (("ls", 0), ("gh pr merge 1701 --admin", 0),
                            ("gh pr merge 1701 --body 'notes on gh release create'", 0),
                            ("gh pr create --fill", 2), ("bb fleet validate --evidence x", 2),
                            ("gh release create v1", 2)):
            with self.subTest(command=command):
                payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(self.repo)})
                result = subprocess.run(["sh", str(hook)], input=payload, text=True, capture_output=True, env=env)
                self.assertEqual(result.returncode, rc, result.stdout + result.stderr)

    def test_hook_uses_a_supplied_view_only_when_the_command_was_read(self) -> None:
        # A view of "FLAT ..." means the hook could not read the command either: the raw text is classified.
        scripts = Path(self.temp.name) / "viewed/scripts"
        scripts.mkdir(parents=True)
        (scripts / GATE.name).write_bytes(GATE.read_bytes())
        (scripts / "ship-gate.py").write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        (scripts.parent / "realdata-paths.json").write_bytes((ROOT / "realdata-paths.json").read_bytes())
        merge = "gh pr merge 1701 --body 'notes on gh release create'"
        for command, view, rc in ((merge, "", 0), (merge, " ; ", 0),
                                  (merge, "FLAT gh pr merge 1701 --body notes on gh release create", 2),
                                  ("gh pr create --fill", "FLAT ls", 2),
                                  # an empty view of a command with no merge is not a reading of it (Hermes r20)
                                  ("gh pr create --fill", "", 2), ("gh pr create --fill", " ; ", 2),
                                  ("bb fleet validate --evidence x", "", 2), ("gh release create v1", "", 2)):
            with self.subTest(command=command, view=view):
                read, write = os.pipe()
                os.write(write, (view + "\n").encode())
                os.close(write)
                payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(self.repo)})
                result = subprocess.run([sys.executable, str(scripts / GATE.name), "hook", f"--view-fd={read}"],
                                        input=payload, text=True, capture_output=True, pass_fds=(read,))
                os.close(read)
                self.assertEqual(result.returncode, rc, result.stdout + result.stderr)

    def test_hook_reads_a_gated_command_across_a_line_continuation(self) -> None:
        result, _ = self.hook("gh pr \\\n  create --fill")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_ssn_identifiers_and_labelled_fields_are_rejected(self) -> None:
        for marker in ("123-45-6789", "123 45 6789", "ssn: 123456789",
                       "ssn_number: 123456789", "ssn-number: 123456789",
                       "social security: 123456789", "social_security: 123456789",
                       "social-security-number: 123456789"):
            with self.subTest(marker=marker):
                self.assert_sensitive_report_denied(marker)

    def test_ssn_detector_allows_dates_shas_and_count_tables(self) -> None:
        report = replay_report(reason="date 2026-10-07; timestamp 2026-10-07 03:41Z; counts 1 2 3")
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit report with ordinary dates and counts")
        allowed, payload = self.check()
        self.assertEqual(allowed.returncode, 0, payload["reason"])
        self.assertTrue(payload["allowed"])

    def test_editable_path_inventory_matches_data_surfaces(self) -> None:
        from importlib.util import module_from_spec, spec_from_file_location
        spec = spec_from_file_location("realdata_gate", GATE)
        assert spec and spec.loader
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        expected = {
            "src/server/ingestion/job.ts", "src/server/services/integrations/client.ts",
            "src/server/intelligence/scoring.ts", "src/server/projections/account.ts",
            "src/server/readers/summary.ts", "src/server/repositories/account.ts",
            "prisma/migrations/20261001/migration.sql", "scripts/backfill.ts",
        }
        self.assertEqual(module.production_paths(expected), expected)


if __name__ == "__main__":
    unittest.main()
