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
                  error_class: str = "none", blocked: bool = False) -> str:
    body = f"""# REALDATA-REPLAY

- Copy time (UTC): 2026-10-06T23:00:00Z
- Control SHA: 0123456789abcdef0123456789abcdef01234567
- Candidate SHA: 89abcdef0123456789abcdef0123456789abcdef
- Local copy: Mac-local database bound to loopback only; production data never leaves the Mac.
- Production source: read-only; no production writes were performed.
- Privacy: counts only; no row IDs or PII are included.
- Blocked rows: {2 if blocked else 0}; external provider boundary was not needed for this replay.

| Goal | Target rows | Control count | Candidate count | Verdict | Reason | Error class |
|---|---:|---:|---:|---|---|---|
| repair ingestion projection | 3 | 0 | {candidate_count} | {"BLOCKED" if blocked else "PASS"} | {reason} | {error_class} |
{note}'''
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
        git(self.repo, "branch", "origin/develop", self.base)
        (self.repo / "src/server/ingestion").mkdir(parents=True)
        (self.repo / "src/server/ingestion/worker.ts").write_text("candidate\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "data fix")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def check(self, action: str = "review", command: str = "pre-review.py",
              env: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        result = subprocess.run([sys.executable, str(GATE), "check", "--repo", str(self.repo),
                                 "--base", self.base, "--action", action, "--command", command, "--json"],
                                text=True, capture_output=True, env=env)
        return result, json.loads(result.stdout)

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
        print(json.dumps({"body":"report cited", "headRefOid":"abc", "files":[{"path":"src/server/ingestion/job.ts"}]}))
        sys.exit(0)
    if mode == "ambient-success" and not os.environ.get("GH_TOKEN"):
        print(json.dumps({"body":"report cited", "headRefOid":"abc", "files":[{"path":"src/server/ingestion/job.ts"}]}))
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
        request.write_text(f"Evidence: {request.parent / 'REALDATA-REPLAY.md'} SHA-256 {digest}\n", encoding="utf-8")
        allowed, _ = self.check("release", "release-request --evidence release-request.md")
        self.assertEqual(allowed.returncode, 0)

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

    def test_report_without_blocked_rows_allows_digest_only_release_request(self) -> None:
        report = replay_report()
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "commit unblocked report")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        request = self.repo / "release-request.md"
        request.write_text(f"REALDATA-REPLAY.md SHA-256 {digest}\n", encoding="utf-8")
        allowed, payload = self.check("release", f"release-request --body-file {request}")
        self.assertEqual(allowed.returncode, 0, payload["reason"])

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
        response = json.dumps({"body": f"{report_path.name} {digest}", "headRefOid": head,
                               "files": [{"path": "src/server/ingestion/worker.ts"},
                                         {"path": "REALDATA-REPLAY.md"}]})
        gh.write_text(f"#!/bin/sh\nprintf '%s\\n' '{response}'\n", encoding="utf-8")
        gh.chmod(0o755)
        import os
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        allowed, _ = self.check("pr", "gh pr ready", env)
        self.assertEqual(allowed.returncode, 0)

    def test_blocked_rows_do_not_add_readback_requirement_to_pr_ready(self) -> None:
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
        response = json.dumps({"body": f"{report_path.name} {digest}", "headRefOid": head,
                               "files": [{"path": "src/server/ingestion/worker.ts"}]})
        gh.write_text(f"#!/bin/sh\nprintf '%s\\n' '{response}'\n", encoding="utf-8")
        gh.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        allowed, payload = self.check("pr", "gh pr ready", env)
        self.assertEqual(allowed.returncode, 0, payload["reason"])

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
