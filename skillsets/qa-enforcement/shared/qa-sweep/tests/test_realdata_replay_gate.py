from __future__ import annotations

import hashlib
import io
import itertools
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
Blocked rows: {2 if blocked or prose_blocked else 0} (external provider boundary was not needed for this replay)

| Goal | Target rows | Control count | Candidate count | Verdict | Reason | Error class |
|---|---:|---:|---:|---|---|---|
| repair ingestion projection | 3 | 0 | {candidate_count} | {"BLOCKED" if blocked else "PASS"} | {reason} | {error_class} |
{note or ('- A2 verdict: BLOCKED at page-member identity. Not run; blocked rows are held for read-back.' if prose_blocked else '')}'''
"""
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return body + f"- Artifact SHA-256 (excluding this line): {digest}\n"


def replay_report_with_blocked_line(line: str | None) -> str:
    lines = replay_report().splitlines()
    index = next(i for i, value in enumerate(lines) if value.startswith("Blocked rows:"))
    if line is None:
        lines.pop(index)
    else:
        lines[index] = line
    body = "\n".join(lines[:-1]) + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return body + f"- Artifact SHA-256 (excluding this line): {digest}\n"


class RealdataReplayGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.original_denylist = os.environ.get("REALDATA_REPLAY_DENYLIST")
        self.denylist = Path(self.temp.name) / "tenant-labels.txt"
        self.denylist.write_text("Acme Energy\n", encoding="utf-8")
        os.environ["REALDATA_REPLAY_DENYLIST"] = str(self.denylist)
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
        if self.original_denylist is None:
            os.environ.pop("REALDATA_REPLAY_DENYLIST", None)
        else:
            os.environ["REALDATA_REPLAY_DENYLIST"] = self.original_denylist
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

    def test_report_rejects_private_tenant_label_without_echoing_it(self) -> None:
        valid, reason, _ = self.gate_module().validate_report_text(
            replay_report(note="- Persona: acme energy reviewer"))
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("acme energy", reason.lower())

    def assert_private_label_variant_denied(self, note: str) -> None:
        valid, reason, _ = self.gate_module().validate_report_text(replay_report(note=note))
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme", reason)

    def test_private_tenant_label_rejects_decimal_html_space_reference(self) -> None:
        self.assert_private_label_variant_denied("- Persona: Acme&#32;Energy reviewer")

    def test_private_tenant_label_rejects_named_html_space_reference(self) -> None:
        self.assert_private_label_variant_denied("- Persona: Acme&nbsp;Energy reviewer")

    def test_encoded_newline_entities_do_not_advance_source_line(self) -> None:
        gate = self.gate_module()
        for entity in ("&#10;", "&#x0a;", "&NewLine;"):
            with self.subTest(entity_kind="encoded newline"):
                valid, reason, _ = gate.validate_report_text(
                    replay_report(note=f"- Replay note: {entity}Acme Energy"))
                self.assertFalse(valid)
                self.assertIn("private tenant label", reason)
                self.assertIn("line 14", reason)
                self.assertNotIn("Acme Energy", reason)

    def test_encoded_newline_entity_inside_html_tag_does_not_advance_source_line(self) -> None:
        valid, reason, _ = self.gate_module().validate_report_text(
            replay_report(note='- Replay note: <b title="&#10;">Acme Energy'))
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_encoded_newline_after_real_source_newline_keeps_original_line(self) -> None:
        valid, reason, _ = self.gate_module().validate_report_text(
            replay_report(note="- Replay note: preceding text\r\n&#10;Acme Energy"))
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 15", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_encoded_newline_between_label_words_remains_a_visible_separator(self) -> None:
        valid, reason, _ = self.gate_module().validate_report_text(
            replay_report(note="- Replay note: Acme&#10;Energy"))
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_actual_source_newlines_advance_lines_inside_hidden_markup(self) -> None:
        gate = self.gate_module()
        notes_and_lines = (
            ("- Replay note: preceding text\rAcme Energy", "line 15"),
            ("- Replay note: preceding text\r\nAcme Energy", "line 15"),
            ("- Replay note: preceding text\r\n<!--\r\n\r-->Acme Energy", "line 17"),
        )
        for note, expected_line in notes_and_lines:
            with self.subTest(source_newline_case="actual source newline"):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertFalse(valid)
                self.assertIn("private tenant label", reason)
                self.assertIn(expected_line, reason)
                self.assertNotIn("Acme Energy", reason)

    def test_private_labels_in_nonrendered_report_values_are_refused(self) -> None:
        gate = self.gate_module()
        notes_and_lines = (
            ('- Replay note: <span title="Acme Energy">safe</span>', "line 14"),
            ("- Replay note: <span title=Acme&#32;Energy>safe</span>", "line 14"),
            ('- Replay note: <span title="hidden\nAcme Energy">safe</span>', "line 15"),
            ("- Replay note: [safe](https://example.invalid/Acme%20Energy)", "line 14"),
            ('- Replay note: [safe](https://example.invalid "Acme Energy")', "line 14"),
            ('- Replay note: [safe](https://example.invalid\n "Acme Energy")', "line 15"),
            ("- Replay note: [safe][r]\n\n[r]: https://example.invalid/Acme%20Energy", "line 16"),
            ("- Replay note: <!-- hidden\nAcme Energy -->safe", "line 15"),
        )
        for note, expected_line in notes_and_lines:
            with self.subTest(hidden_value="nonrendered report text"):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertFalse(valid)
                self.assertIn("private tenant label", reason)
                self.assertIn(expected_line, reason)
                self.assertNotIn("Acme Energy", reason)

    def test_nonrendered_report_label_scan_keeps_word_boundaries(self) -> None:
        gate = self.gate_module()
        notes = (
            '- Replay note: <span title="SuperAcme EnergyCo">safe</span>',
            "- Replay note: [safe](https://example.invalid/SuperAcme%20EnergyCo)",
            "- Replay note: <!-- SuperAcme EnergyCo -->safe",
        )
        for note in notes:
            with self.subTest(hidden_control="larger words"):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertTrue(valid, reason)

    def test_hidden_consumers_apply_both_format_character_normalizations(self) -> None:
        gate = self.gate_module()

        def encode_url_spaces(value: str) -> str:
            return value.replace(" ", "%20")

        consumers = (
            ("html title", lambda value: f'<span title="{value}">safe</span>', "line 14"),
            ("html unquoted attribute", lambda value: f"<span title={value.replace(' ', '&#32;')}>safe</span>", "line 14"),
            ("html href", lambda value: f'<a href="https://example.test/{encode_url_spaces(value)}">safe</a>', "line 14"),
            ("html src", lambda value: f'<img src="https://example.test/{encode_url_spaces(value)}">', "line 14"),
            ("html action", lambda value: f'<form action="https://example.test/{encode_url_spaces(value)}">safe</form>', "line 14"),
            ("html formaction", lambda value: f'<button formaction="https://example.test/{encode_url_spaces(value)}">safe</button>', "line 14"),
            ("html cite", lambda value: f'<blockquote cite="https://example.test/{encode_url_spaces(value)}">safe</blockquote>', "line 14"),
            ("object data", lambda value: f'<object data="https://example.test/{encode_url_spaces(value)}">safe</object>', "line 14"),
            ("html poster", lambda value: f'<video poster="https://example.test/{encode_url_spaces(value)}">safe</video>', "line 14"),
            ("html manifest", lambda value: f'<html manifest="https://example.test/{encode_url_spaces(value)}">safe</html>', "line 14"),
            ("html background", lambda value: f'<body background="https://example.test/{encode_url_spaces(value)}">safe</body>', "line 14"),
            ("object codebase", lambda value: f'<object codebase="https://example.test/{encode_url_spaces(value)}">safe</object>', "line 14"),
            ("object classid", lambda value: f'<object classid="https://example.test/{encode_url_spaces(value)}">safe</object>', "line 14"),
            ("html longdesc", lambda value: f'<img longdesc="https://example.test/{encode_url_spaces(value)}">', "line 14"),
            ("html usemap", lambda value: f'<img usemap="https://example.test/{encode_url_spaces(value)}">', "line 14"),
            ("svg xlink href", lambda value: f'<svg><use xlink:href="https://example.test/{encode_url_spaces(value)}"></use></svg>', "line 14"),
            ("microdata itemid", lambda value: f'<div itemid="https://example.test/{encode_url_spaces(value)}">safe</div>', "line 14"),
            ("html ping list", lambda value: f'<a ping="https://example.test/{encode_url_spaces(value)} https://example.test/other">safe</a>', "line 14"),
            ("object archive list", lambda value: f'<object archive="https://example.test/{encode_url_spaces(value)} https://example.test/other">safe</object>', "line 14"),
            ("microdata itemtype list", lambda value: f'<div itemtype="https://example.test/{encode_url_spaces(value)} https://example.test/other">safe</div>', "line 14"),
            ("head profile list", lambda value: f'<head profile="https://example.test/{encode_url_spaces(value)} https://example.test/other"></head>', "line 14"),
            ("html srcset list", lambda value: f'<img srcset="https://example.test/{encode_url_spaces(value)} 1x, https://example.test/other 2x">', "line 14"),
            ("html imagesrcset list", lambda value: f'<link imagesrcset="https://example.test/{encode_url_spaces(value)} 1x">', "line 14"),
            ("markdown destination", lambda value: f'[safe](https://example.test/{encode_url_spaces(value)})', "line 14"),
            ("markdown title", lambda value: f'[safe](https://example.test "{value}")', "line 14"),
            ("html comment", lambda value: f"<!-- {value} -->safe", "line 14"),
            ("reference destination", lambda value: f"[safe][r]\n\n[r]: https://example.test/{encode_url_spaces(value)}", "line 16"),
        )
        format_variants = ("Ac\u200bme Energy", "Acme\u200bEnergy")
        for consumer_name, render, expected_line in consumers:
            for value in format_variants:
                note = "- Replay note: " + render(value)
                with self.subTest(hidden_consumer=consumer_name, format_variant="zero width"):
                    valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                    self.assertFalse(valid)
                    self.assertIn("private tenant label", reason)
                    self.assertIn(expected_line, reason)
                    self.assertNotIn("Acme Energy", reason)
            control = "- Replay note: " + render("SuperAcme EnergyCo")
            with self.subTest(hidden_consumer=consumer_name, format_variant="larger word control"):
                valid, reason, _ = gate.validate_report_text(replay_report(note=control))
                self.assertTrue(valid, reason)

    def test_percent_decoding_is_limited_to_hidden_url_values(self) -> None:
        gate = self.gate_module()
        notes = (
            '- Replay note: <span title="Acme%20Energy">safe</span>',
            '- Replay note: <span data-note="Acme%20Energy">safe</span>',
            '- Replay note: <div data="Acme%20Energy">safe</div>',
            '- Replay note: [safe](https://example.test "Acme%20Energy")',
            "- Replay note: <!-- Acme%20Energy -->safe",
        )
        for note in notes:
            with self.subTest(non_url_text="percent-encoded space"):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertTrue(valid, reason)

    def test_css_url_values_are_scanned_without_decoding_other_style_text(self) -> None:
        gate = self.gate_module()
        self.denylist.write_text("Test Tenant\n", encoding="utf-8")
        refusing = (
            ('- Replay note: <div style="background-image:url(https://example.test/Test%20Tenant)">safe</div>', "line 14"),
            ("- Replay note: <div style='background-image:url(\"https://example.test/Test%20Tenant\")'>safe</div>", "line 14"),
            ('- Replay note: <div style=background-image:url(https://example.test/Test%20Tenant)>safe</div>', "line 14"),
            ('- Replay note: <div style="background-image:url(https://example.test/ordinary), url(https://example.test/Test%20Tenant)">safe</div>', "line 14"),
            ('- Replay note: &lt;div style=&quot;background-image:url(https://example.test/Test%20Tenant)&quot;&gt;safe&lt;/div&gt;', "line 14"),
            ('- Replay note: <div style="background-image:url(https://example.test/ordinary),\n url(https://example.test/Test%20Tenant)">safe</div>', "line 15"),
            ('- Replay note: <style> .x { background-image: url("https://example.test/Test%20Tenant") }</style>', "line 14"),
            ('- Replay note: &lt;style&gt;.x{background:url(https://example.test/Test%20Tenant)}&lt;/style&gt;', "line 14"),
        )
        for note, expected_line in refusing:
            with self.subTest(css_url="private URL value"):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertFalse(valid)
                self.assertIn("private tenant label", reason)
                self.assertIn(expected_line, reason)
                self.assertNotIn("Test Tenant", reason)

        passing = (
            '- Replay note: <div style="background-image:url(https://example.test/ordinary)">safe</div>',
            '- Replay note: <div style="--label:Test%20Tenant">safe</div>',
            '- Replay note: <div style="content:\'Test%20Tenant\'">safe</div>',
            '- Replay note: <div style="background-image:url(https://example.test/SuperTest%20TenantCo)">safe</div>',
            '- Replay note: <div style="/* url(https://example.test/Test%20Tenant) */ background:none">safe</div>',
            '- Replay note: <div style="content:\'url(https://example.test/Test%20Tenant)\'">safe</div>',
        )
        for note in passing:
            with self.subTest(css_url="clean or non-URL control"):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertTrue(valid, reason)

    def test_css_escaped_url_identifiers_and_payloads_keep_source_lines(self) -> None:
        gate = self.gate_module()
        self.denylist.write_text("Test Tenant\n", encoding="utf-8")
        refusing = (
            ("escaped function", '- Replay note: <div style="background-image:u\\72l(https://example.test/Test%20Tenant)">safe</div>', "line 14"),
            ("simple escaped function name", '- Replay note: <div style="background-image:\\url(https://example.test/Test%20Tenant)">safe</div>', "line 14"),
            ("encoded tag escaped function", '- Replay note: &lt;div style=&quot;background-image:u\\72l(https://example.test/Test%20Tenant)&quot;&gt;safe&lt;/div&gt;', "line 14"),
            ("hex terminator in function name", '- Replay note: <style>.a{background-image:u\\72 l(https://example.test/Test%20Tenant)}</style>', "line 14"),
            ("escaped percent", '- Replay note: <style>.a{background-image:url(https://example.test/Test\\25 20Tenant)}</style>', "line 14"),
            ("escaped label character", '- Replay note: <div style="background-image:url(https://example.test/T\\65 st%20Tenant)">safe</div>', "line 14"),
            ("simple escaped label character", '- Replay note: <div style="background-image:url(https://example.test/Te\\st%20Tenant)">safe</div>', "line 14"),
            ("physical CRLF function terminator", '- Replay note: <style>.a{background-image:u\\72\r\nl(https://example.test/Test%20Tenant)}</style>', "line 15"),
            ("physical CRLF payload terminator", '- Replay note: <div style="background-image:url(https://example.test/T\\65\r\nst%20Tenant)">safe</div>', "line 14"),
            ("quoted URL line continuation", "- Replay note: <div style='background-image:url(\"https://example.test/\\\r\nTest%20Tenant\")'>safe</div>", "line 15"),
            ("entity newline terminator", '- Replay note: <style>.a{background-image:url(https://example.test/T\\65&#10;st%20Tenant)}</style>', "line 14"),
        )
        for case_name, note, expected_line in refusing:
            with self.subTest(css_escape=case_name):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertFalse(valid)
                self.assertIn("private tenant label", reason)
                self.assertIn(expected_line, reason)
                self.assertNotIn("Test Tenant", reason)

        passing = (
            '- Replay note: <style>.a{background-image:u\\72l(https://example.test/ordinary)}</style>',
            '- Replay note: <style>.a{background-image:\\url(https://example.test/ordinary)}</style>',
            '- Replay note: <div style="background-image:url(https://example.test/SuperTest%20TenantCo)">safe</div>',
            '- Replay note: <div style="--label:Test%20Tenant">safe</div>',
            '- Replay note: <style>.a{content:"url(https://example.test/Test%20Tenant)"}</style>',
            '- Replay note: <div style="/* u\\72l(https://example.test/Test%20Tenant) */ background:none">safe</div>',
        )
        for note in passing:
            with self.subTest(css_escape="clean or non-URL control"):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertTrue(valid, reason)

    def test_css_string_url_consumers_are_scanned_without_decoding_other_strings(self) -> None:
        gate = self.gate_module()
        self.denylist.write_text("Test Tenant\n", encoding="utf-8")
        refusing = (
            ("import string", '- Replay note: <style>@import "https://example.test/Test%20Tenant.css";</style>', "line 14"),
            ("escaped import string", '- Replay note: <style>@\\69mport\n "https://example.test/Test%20Tenant.css";</style>', "line 15"),
            ("import string escaped CRLF continuation", '- Replay note: <style>@import "https://example.test/\\\r\nTest%20Tenant.css";</style>', "line 15"),
            ("image-set first source", '- Replay note: <style>.a{background:image-set("https://example.test/Test%20Tenant.png" 1x, url(https://example.test/clean) 2x)}</style>', "line 14"),
            ("image-set later source", '- Replay note: <style>.a{background:image-set("https://example.test/clean.png" 1x,\n "https://example.test/Test%20Tenant.png" 2x)}</style>', "line 15"),
            ("vendor image-set", '- Replay note: <style>.a{background:-webkit-image-set("https://example.test/Test%20Tenant.png" 1x)}</style>', "line 14"),
            ("image() source", '- Replay note: <style>.a{background:image("https://example.test/Test%20Tenant.svg")}</style>', "line 14"),
            ("nested image-set source", '- Replay note: <style>.a{background:linear-gradient(red, image-set("https://example.test/Test%20Tenant.png" 2x))}</style>', "line 14"),
            ("style attribute image-set source", '- Replay note: <div style="background:image-set(\'https://example.test/Test%20Tenant.png\' 1x)">safe</div>', "line 14"),
            ("escaped image-set function", '- Replay note: <style>.a{background:im\\61 ge-set("https://example.test/Test%20Tenant.png" 1x)}</style>', "line 14"),
            ("encoded style tag", '- Replay note: &lt;style&gt;@import &quot;https://example.test/Test%20Tenant.css&quot;;&lt;/style&gt;', "line 14"),
            ("CSS escaped URL label", '- Replay note: <style>@import "https://example.test/Test\\20 Tenant.css";</style>', "line 14"),
        )
        for case_name, note, expected_line in refusing:
            with self.subTest(css_string_url=case_name):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertFalse(valid)
                self.assertIn("private tenant label", reason)
                self.assertIn(expected_line, reason)
                self.assertNotIn("Test Tenant", reason)

        passing = (
            '- Replay note: <style>@import "https://example.test/clean.css";</style>',
            '- Replay note: <style>.a{background:image-set("https://example.test/clean.png" 1x, url(https://example.test/also-clean) 2x)}</style>',
            '- Replay note: <style>.a{background:-webkit-image-set("https://example.test/clean.png" 1x)}</style>',
            '- Replay note: <style>.a{background:image("https://example.test/clean.svg")}</style>',
            '- Replay note: <style>.a{background:image-set("https://example.test/clean.png" 1x type("Test%20Tenant"))}</style>',
            '- Replay note: <style>.a{content:"https://example.test/Test%20Tenant"}</style>',
            '- Replay note: <style>/* @import "https://example.test/Test%20Tenant.css"; */ .a{background:none}</style>',
            '- Replay note: <style>.a{content:"image-set(\\"https://example.test/Test%20Tenant.png\\" 1x)"}</style>',
            '- Replay note: <style>.a{background:image-set(linear-gradient("Test%20Tenant", red) 1x)}</style>',
            '- Replay note: <style>.a{background:image-set("https://example.test/SuperTest%20TenantCo.png" 1x)}</style>',
            '- Replay note: <style>.a{background:image-set("https://example.test/clean.png" 1x type("image/avif"), "https://example.test/clean.jpg" 2x type("image/jpeg"))}</style>',
        )
        for note in passing:
            with self.subTest(css_string_url="clean or non-URL control"):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertTrue(valid, reason)

    def test_quoted_greater_than_does_not_truncate_html_tag_privacy_scan(self) -> None:
        gate = self.gate_module()
        self.denylist.write_text("Test Tenant\n", encoding="utf-8")
        refusing = (
            ('- Replay note: <div title="x >" style="background:url(https://example.test/Test%20Tenant)">safe</div>', "line 14"),
            ('- Replay note: <div title="x >"\n style="background:url(https://example.test/Test%20Tenant)">safe</div>', "line 15"),
            ('- Replay note: &lt;div title=&quot;x &gt;&quot; style=&quot;background:url(https://example.test/Test%20Tenant)&quot;&gt;safe&lt;/div&gt;', "line 14"),
            ('- Replay note: &lt;div title=&quot;x &#62;&quot;\n style=&quot;background:url(https://example.test/Test%20Tenant)&quot;&gt;safe&lt;/div&gt;', "line 15"),
        )
        for note, expected_line in refusing:
            with self.subTest(quoted_tag_boundary="private URL hidden after quoted greater-than"):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertFalse(valid)
                self.assertIn("private tenant label", reason)
                self.assertIn(expected_line, reason)
                self.assertNotIn("Test Tenant", reason)

        passing = (
            '- Replay note: <div title="x >" style="background:url(https://example.test/ordinary)">safe</div>',
            '- Replay note: &lt;div title=&quot;x &gt;&quot; style=&quot;background:url(https://example.test/ordinary)&quot;&gt;safe&lt;/div&gt;',
            '- Replay note: <div title="Test%20Tenant >" data-note="ordinary">safe</div>',
            '- Replay note: <div title="x >" style="background:url(https://example.test/SuperTest%20TenantCo)">safe</div>',
        )
        for note in passing:
            with self.subTest(quoted_tag_boundary="clean or non-URL control"):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertTrue(valid, reason)

    def test_percent_encoded_url_newline_is_not_a_source_line_break(self) -> None:
        notes = (
            '- Replay note: <a href="https://example.test/%0AAcme%20Energy">safe</a>',
            "- Replay note: [safe](https://example.test/%0AAcme%20Energy)",
            '- Replay note: <blockquote cite="https://example.test/%0AAcme%20Energy">safe</blockquote>',
            '- Replay note: <img srcset="https://example.test/%0AAcme%20Energy 1x">',
            '- Replay note: <link imagesrcset="https://example.test/%0AAcme%20Energy 1x">',
        )
        for note in notes:
            with self.subTest(encoded_newline="URL percent escape"):
                valid, reason, _ = self.gate_module().validate_report_text(replay_report(note=note))
                self.assertFalse(valid)
                self.assertIn("private tenant label", reason)
                self.assertIn("line 14", reason)
                self.assertNotIn("Acme Energy", reason)

    def test_list_valued_url_attributes_keep_source_lines_and_item_boundaries(self) -> None:
        gate = self.gate_module()
        refusing = (
            ('- Replay note: <a ping="https://example.test/first\nhttps://example.test/Acme%20Energy">safe</a>', "line 15"),
            ('- Replay note: <img srcset="https://example.test/first 1x,\n https://example.test/Acme%20Energy 2x">', "line 15"),
            ('- Replay note: <link imagesrcset="https://example.test/first 1x,\n https://example.test/Acme%20Energy 2x">', "line 15"),
            ('- Replay note: <a ping="https://example.test/Acme\u00a0Energy">safe</a>', "line 14"),
            ('- Replay note: <img srcset="https://example.test/Acme\u00a0Energy 1x">', "line 14"),
        )
        for note, expected_line in refusing:
            with self.subTest(list_url="actual source line"):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertFalse(valid)
                self.assertIn("private tenant label", reason)
                self.assertIn(expected_line, reason)
                self.assertNotIn("Acme Energy", reason)

        unrelated_tokens = (
            '- Replay note: <a ping="https://example.test/Acme%20 https://example.test/Energy">safe</a>',
            '- Replay note: <img srcset="https://example.test/Acme%20 1x, https://example.test/Energy 2x">',
        )
        for note in unrelated_tokens:
            with self.subTest(list_url="separate token negative control"):
                valid, reason, _ = gate.validate_report_text(replay_report(note=note))
                self.assertTrue(valid, reason)

    def test_srcset_scans_each_candidate_url_and_not_its_descriptors(self) -> None:
        gate = self.gate_module()
        cases = (
            ('<img srcset="https://example.test/first 1x, https://example.test/Acme%20Energy 2x">', True),
            ('<img srcset="https://example.test/Acme%20Energy, https://example.test/other">', True),
            ('<img srcset="data:image/svg+xml,%3Csvg%3E 1x, https://example.test/Acme%20Energy 2x">', True),
            ('<img srcset="https://example.test/Acme%20 1x, https://example.test/Energy 2x">', False),
            ('<img srcset="https://example.test/first 1x, https://example.test/other 2x">', False),
        )
        for markup, should_refuse in cases:
            with self.subTest(srcset_candidate="URL token and descriptor boundary"):
                valid, reason, _ = gate.validate_report_text(
                    replay_report(note=f"- Replay note: {markup}"))
                self.assertEqual(not valid, should_refuse, reason)
                if should_refuse:
                    self.assertIn("private tenant label", reason)
                    self.assertIn("line 14", reason)
                    self.assertNotIn("Acme Energy", reason)

    def test_entity_encoded_html_tags_keep_private_attributes_visible_to_scan(self) -> None:
        gate = self.gate_module()
        cases = (
            ('&lt;span title="Acme Energy"&gt;safe&lt;/span&gt;', "line 14"),
            ('&lt;span title=&quot;Acme Energy&quot;&gt;safe&lt;/span&gt;', "line 14"),
            ('&lt;a href="https://example.test/Acme%20Energy"&gt;safe&lt;/a&gt;', "line 14"),
            ('&lt;a href=&quot;https://example.test/Acme%20Energy&quot;&gt;safe&lt;/a&gt;', "line 14"),
            ('&lt;span title=&quot;Ac&#8203;me Energy&quot;&gt;safe&lt;/span&gt;', "line 14"),
            ('&lt;a href=&quot;https://example.test/Acme&#8203;%20Energy&quot;&gt;safe&lt;/a&gt;', "line 14"),
            ('&lt;span title=&quot;hidden\nAcme Energy&quot;&gt;safe&lt;/span&gt;', "line 15"),
            ('&lt;span title=&quot;hidden\rAcme Energy&quot;&gt;safe&lt;/span&gt;', "line 15"),
            ('&#10;&lt;span title=&quot;Acme Energy&quot;&gt;safe&lt;/span&gt;', "line 14"),
            ('before\n&lt;span title=&quot;Acme Energy&quot;&gt;safe&lt;/span&gt;', "line 15"),
            ('before\r\n&lt;span title=&quot;Acme Energy&quot;&gt;safe&lt;/span&gt;', "line 15"),
            ('&lt;span title=&quot;&#10;Acme Energy&quot;&gt;safe&lt;/span&gt;', "line 14"),
            ('&lt;span title=&quot;&NewLine;Acme Energy&quot;&gt;safe&lt;/span&gt;', "line 14"),
            ('&lt;!-- Acme Energy --&gt;safe', "line 14"),
        )
        for encoded_markup, expected_line in cases:
            with self.subTest(encoded_markup="hidden attribute privacy"):
                valid, reason, _ = gate.validate_report_text(
                    replay_report(note=f"- Replay note: {encoded_markup}"))
                self.assertFalse(valid)
                self.assertIn("private tenant label", reason)
                self.assertIn(expected_line, reason)
                self.assertNotIn("Acme Energy", reason)

        passing = (
            '&lt;span title=&quot;ordinary&quot;&gt;safe&lt;/span&gt;',
            '&lt;span title=&quot;SuperAcme EnergyCo&quot;&gt;safe&lt;/span&gt;',
            '&lt;a href=&quot;https://example.test/SuperAcme%20EnergyCo&quot;&gt;safe&lt;/a&gt;',
            '&lt;span title=&quot;Acme%20Energy&quot;&gt;safe&lt;/span&gt;',
        )
        for encoded_markup in passing:
            with self.subTest(encoded_markup="clean or word-boundary control"):
                valid, reason, _ = gate.validate_report_text(
                    replay_report(note=f"- Replay note: {encoded_markup}"))
                self.assertTrue(valid, reason)

    def test_private_tenant_label_rejects_zero_width_character(self) -> None:
        self.assert_private_label_variant_denied("- Persona: Acme\u200bEnergy reviewer")

    def test_private_tenant_label_rejects_format_character_inside_word(self) -> None:
        self.assert_private_label_variant_denied("- Persona: Ac\u200bme Energy reviewer")

    def test_private_tenant_label_rejects_markdown_emphasis(self) -> None:
        self.assert_private_label_variant_denied("- Persona: **Acme** Energy reviewer")

    def test_private_tenant_label_rejects_markdown_code_markers(self) -> None:
        self.assert_private_label_variant_denied("- Persona: `Acme` Energy reviewer")

    def test_private_tenant_label_rejects_backslash_escape(self) -> None:
        self.assert_private_label_variant_denied("- Persona: Acme\\* Energy reviewer")

    def test_private_tenant_label_rejects_repeated_whitespace(self) -> None:
        self.assert_private_label_variant_denied("- Persona: Acme  Energy reviewer")

    def test_private_tenant_label_rejects_line_break_between_words(self) -> None:
        self.assert_private_label_variant_denied("- Persona: Acme\nEnergy reviewer")

    def test_private_tenant_label_rejects_full_width_unicode(self) -> None:
        self.assert_private_label_variant_denied("- Persona: Ａｃｍｅ Energy reviewer")

    def test_private_tenant_label_rejects_markdown_inline_link(self) -> None:
        self.assert_private_label_variant_denied(
            "- Persona: [Acme](https://example.invalid) Energy reviewer")

    def test_private_tenant_label_rejects_markdown_inline_link_with_title(self) -> None:
        self.assert_private_label_variant_denied(
            '- Persona: [Acme](https://example.invalid "title") Energy reviewer')

    def test_private_tenant_label_rejects_markdown_reference_link(self) -> None:
        self.assert_private_label_variant_denied("- Persona: [Acme][r] Energy reviewer")

    def test_private_tenant_label_rejects_collapsed_reference_link(self) -> None:
        self.assert_private_label_variant_denied("- Persona: [Acme][] Energy reviewer")

    def test_private_tenant_label_rejects_html_bold_text(self) -> None:
        self.assert_private_label_variant_denied("- Persona: <b>Acme</b> Energy reviewer")

    def test_private_tenant_label_rejects_empty_html_tag_between_words(self) -> None:
        self.assert_private_label_variant_denied("- Persona: Acme<span></span> Energy reviewer")

    def test_private_tenant_label_rejects_adjacent_table_cells(self) -> None:
        self.assert_private_label_variant_denied("| Acme | Energy |")

    def test_private_tenant_label_rejects_markdown_image_alt_text(self) -> None:
        self.assert_private_label_variant_denied("- Persona: ![Acme](image.png) Energy reviewer")

    def test_private_tenant_label_rejects_label_inside_html_tags(self) -> None:
        self.assert_private_label_variant_denied("- Persona: <span class='x'>Acme Energy</span>")

    def test_private_tenant_label_checks_autolink_visible_text(self) -> None:
        self.denylist.write_text("example.invalid\n", encoding="utf-8")
        valid, reason, _ = self.gate_module().validate_report_text(
            replay_report(note="- Replay note: <https://example.invalid>"))
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("example.invalid", reason)

    def test_private_tenant_label_uses_word_boundaries(self) -> None:
        valid, reason, _ = self.gate_module().validate_report_text(
            replay_report(note="- Persona: SuperAcme EnergyCo reviewer"))
        self.assertTrue(valid, reason)

    def test_report_rejects_objectid_without_echoing_it(self) -> None:
        valid, reason, _ = self.gate_module().validate_report_text(
            replay_report(note="- Replay note: 507f1f77bcf86cd799439011"))
        self.assertFalse(valid)
        self.assertIn("ObjectId-like token", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("507f1f77bcf86cd799439011", reason)

    def test_report_rejects_email_without_echoing_it(self) -> None:
        valid, reason, _ = self.gate_module().validate_report_text(
            replay_report(note="- Replay note: reviewer@example.invalid"))
        self.assertFalse(valid)
        self.assertIn("email address", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("reviewer@example.invalid", reason)

    def test_private_label_split_by_single_line_html_comment_is_rejected(self) -> None:
        text = replay_report(note="- Replay note: Ac<!-- -->me Energy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_split_by_multiline_html_comment_keeps_start_line(self) -> None:
        text = replay_report(note="- Replay note: Ac<!--\n -->me Energy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_after_multiline_html_comment_reports_its_line(self) -> None:
        text = replay_report(note="- Replay note: <!--\n -->Acme Energy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 15", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_split_by_comment_inside_html_tags_is_rejected(self) -> None:
        text = replay_report(note="- Replay note: <b>Ac<!-- -->me</b> Energy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_split_by_multiline_opening_html_tag_is_rejected(self) -> None:
        text = replay_report(note="- Replay note: Ac<b\n>me Energy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_after_multiline_opening_html_tag_reports_its_line(self) -> None:
        text = replay_report(note="- Replay note: <b\n>Acme Energy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 15", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_split_by_multiline_closing_html_tag_is_rejected(self) -> None:
        text = replay_report(note="- Replay note: Ac</b\n>me Energy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_split_by_multiline_link_title_is_rejected(self) -> None:
        text = replay_report(note='- Replay note: [Ac](https://example.invalid "title\nline")me Energy')
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_hidden_comment_and_link_newlines_do_not_create_label_spaces(self) -> None:
        gate = self.gate_module()
        self.denylist.write_text("Ac Energy\n", encoding="utf-8")
        comment_report = replay_report(note="- Replay note: Ac<!--\n -->Energy")
        comment_valid, comment_reason, _ = gate.validate_report_text(comment_report)
        self.assertTrue(comment_valid, comment_reason)

        self.denylist.write_text("Ac me Energy\n", encoding="utf-8")
        link_report = replay_report(note='- Replay note: [Ac](https://example.invalid "title\nline")me Energy')
        link_valid, link_reason, _ = gate.validate_report_text(link_report)
        self.assertTrue(link_valid, link_reason)

    def test_private_label_after_multiline_link_title_reports_its_line(self) -> None:
        text = replay_report(note='- Replay note: [hidden](https://example.invalid "title\nline") Acme Energy')
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 15", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_adjacent_multiline_opening_and_closing_tags_preserve_rendered_adjacency(self) -> None:
        text = replay_report(note="- Replay note: <span\n>Ac</span\n>me Energy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 15", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_with_visible_space_before_multiline_tag_is_rejected(self) -> None:
        text = replay_report(note="- Replay note: Acme <b\n>Energy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_with_visible_space_after_multiline_tag_is_rejected(self) -> None:
        text = replay_report(note="- Replay note: Acme</b\n> Energy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_with_visible_space_before_multiline_comment_is_rejected(self) -> None:
        text = replay_report(note="- Replay note: Acme <!--\n-->Energy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_with_visible_space_after_multiline_comment_is_rejected(self) -> None:
        text = replay_report(note="- Replay note: Acme<!--\n--> Energy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_markup_without_visible_space_does_not_split_private_label_words(self) -> None:
        gate = self.gate_module()
        self.denylist.write_text("Acme Energy\n", encoding="utf-8")
        for markup in ("Acme<b\n>Energy", "Acme</b\n>Energy",
                       "Acme<!--\n-->Energy",
                       'Acme![](https://example.invalid "title\nline")Energy'):
            with self.subTest(markup_type="hidden markup"):
                text = replay_report(note=f"- Replay note: {markup}")
                valid, reason, _ = gate.validate_report_text(text)
                self.assertTrue(valid, reason)

    def test_visible_line_break_after_multiline_markup_keeps_start_line_accurate(self) -> None:
        text = replay_report(note="- Replay note: <b\n>Acme \nEnergy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 15", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_matches_generated_marker_whitespace_interleavings(self) -> None:
        gate = self.gate_module()
        self.denylist.write_text("Acme Energy\n", encoding="utf-8")
        markers = ("<b\n>", "<!--\n-->")
        visible_spaces = (" ", "\t", "\n", "  ")
        case_number = 0
        failures = 0
        for length in range(2, 7):
            for sequence in itertools.product(("marker", "space"), repeat=length):
                if "marker" not in sequence or "space" not in sequence:
                    continue
                parts: list[str] = []
                marker_number = 0
                space_number = 0
                for item in sequence:
                    if item == "marker":
                        parts.append(markers[marker_number % len(markers)])
                        marker_number += 1
                    else:
                        parts.append(visible_spaces[space_number % len(visible_spaces)])
                        space_number += 1
                text = replay_report(note="- Replay note: Acme" + "".join(parts) + "Energy")
                valid, reason, _ = gate.validate_report_text(text)
                case_number += 1
                if (valid or "private tenant label" not in reason or "line 14" not in reason
                        or "Acme Energy" in reason):
                    failures += 1
        self.assertEqual(0, failures,
                         f"{failures} of {case_number} marker/whitespace interleavings failed")

    def test_all_reported_marker_whitespace_interleavings_are_refused(self) -> None:
        gate = self.gate_module()
        self.denylist.write_text("Acme Energy\n", encoding="utf-8")
        notes = (
            "- Replay note: Acme <b\n> Energy",
            "- Replay note: Acme <!--\n--> Energy",
            "- Replay note: Acme<b\n> <b\n> Energy",
            "- Replay note: Acme<!--\n--> <!--\n--> Energy",
            "- Replay note: Acme <b\n> <b\n>Energy",
        )
        for index, note in enumerate(notes, start=1):
            text = replay_report(note=note)
            valid, reason, _ = gate.validate_report_text(text)
            with self.subTest(reproducer_case=index):
                self.assertFalse(valid, f"reproducer case {index}: {reason}")
                if not valid:
                    self.assertIn("private tenant label", reason)
                    self.assertIn("line 14", reason)
                    self.assertNotIn("Acme Energy", reason)

    def test_marker_only_interleavings_do_not_create_word_boundaries(self) -> None:
        gate = self.gate_module()
        self.denylist.write_text("Acme Energy\n", encoding="utf-8")
        markers = ("<b\n>", "<!--\n-->")
        for length in range(1, 5):
            for sequence in itertools.product(markers, repeat=length):
                text = replay_report(note="- Replay note: Acme" + "".join(sequence) + "Energy")
                valid, reason, _ = gate.validate_report_text(text)
                self.assertTrue(valid, reason)

    def test_interleaved_whitespace_after_multiline_tag_keeps_start_line_accurate(self) -> None:
        text = replay_report(note="- Replay note: <b\n>Acme <!--\n--> Energy")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 15", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_matches_visible_spaces_around_hidden_multiline_image(self) -> None:
        text = replay_report(note='- Replay note: Acme ![](https://example.invalid "title\nline") Energy')
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_private_label_at_end_before_multiline_link_marker_is_rejected(self) -> None:
        text = replay_report(note='- Replay note: Acme [Energy](https://example.org\n "title")')
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 14", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_multiline_markup_does_not_invent_prefix_or_suffix_word_boundaries(self) -> None:
        gate = self.gate_module()
        self.denylist.write_text("Acme Energy\n", encoding="utf-8")
        notes = (
            "- Replay note: Acme Energy<b\n>x",
            "- Replay note: x<b\n>Acme Energy",
        )
        for index, note in enumerate(notes, start=1):
            text = replay_report(note=note)
            valid, reason, _ = gate.validate_report_text(text)
            with self.subTest(word_boundary=index):
                self.assertTrue(valid, reason)

    def test_multiline_tags_and_comments_do_not_hide_real_trailing_word_boundary(self) -> None:
        gate = self.gate_module()
        for index, note in enumerate((
                "- Replay note: Acme Energy</b\n>",
                "- Replay note: Acme Energy<!--\n-->"), start=1):
            text = replay_report(note=note)
            valid, reason, _ = gate.validate_report_text(text)
            with self.subTest(markup=index):
                self.assertFalse(valid)
                self.assertIn("private tenant label", reason)
                self.assertIn("line 14", reason)
                self.assertNotIn("Acme Energy", reason)

    def test_report_requires_explicit_blocked_rows_boundary(self) -> None:
        text = replay_report_with_blocked_line("Blocked rows: 0; no boundary")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("blocked external-call rows", reason)
        self.assertIn(f"line {len(text.splitlines()) + 1} (end of report)", reason)

    def test_blocked_rows_accepts_grouped_count_with_trailing_context(self) -> None:
        text = replay_report_with_blocked_line(
            "Blocked rows: 8,992 (boundary reached: provider limit). Additional blocked boundaries: two")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertTrue(valid, reason)

    def test_blocked_rows_rejects_split_digit_count(self) -> None:
        text = replay_report_with_blocked_line("Blocked rows: 8 992 (none)")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("blocked external-call rows", reason)

    def test_blocked_rows_rejects_space_before_grouping_comma(self) -> None:
        text = replay_report_with_blocked_line("Blocked rows: 8 ,992 (none)")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("blocked external-call rows", reason)

    def test_blocked_rows_accepts_single_count_with_trailing_period(self) -> None:
        text = replay_report_with_blocked_line("Blocked rows: 1 (boundary reached: provider limit).")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertTrue(valid, reason)

    def test_blocked_rows_accepts_zero_with_none_boundary(self) -> None:
        text = replay_report_with_blocked_line("Blocked rows: 0 (none)")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertTrue(valid, reason)

    def test_blocked_rows_accepts_ungrouped_five_digit_count(self) -> None:
        text = replay_report_with_blocked_line("Blocked rows: 12345 (x)")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertTrue(valid, reason)

    def test_blocked_rows_rejects_missing_count(self) -> None:
        text = replay_report_with_blocked_line("Blocked rows: (x)")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("blocked external-call rows", reason)

    def test_blocked_rows_is_case_sensitive(self) -> None:
        text = replay_report_with_blocked_line("blocked rows: 0 (none)")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("blocked external-call rows", reason)

    def test_blocked_rows_must_start_at_line_start(self) -> None:
        text = replay_report_with_blocked_line(" Blocked rows: 0 (none)")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("blocked external-call rows", reason)

    def test_blocked_rows_rejects_missing_line(self) -> None:
        text = replay_report_with_blocked_line(None)
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("blocked external-call rows", reason)

    def test_report_passes_with_clean_private_denylist(self) -> None:
        valid, reason, digest = self.gate_module().validate_report_text(replay_report())
        self.assertTrue(valid, reason)
        self.assertIsNotNone(digest)

    def test_required_artifact_sha_footer_does_not_match_private_label(self) -> None:
        self.denylist.write_text("SHA\n", encoding="utf-8")
        valid, reason, _ = self.gate_module().validate_report_text(
            replay_report(note="- Replay note: no additional boundary."))
        self.assertTrue(valid, reason)

    def test_private_label_in_malformed_additional_footer_is_not_exempt(self) -> None:
        text = replay_report() + "- Artifact SHA-256 (excluding this line): Acme Energy\n"
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 16", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_second_valid_looking_footer_is_refused(self) -> None:
        report = replay_report()
        footer = report.splitlines(keepends=True)[-1]
        valid, reason, _ = self.gate_module().validate_report_text(report + footer)
        self.assertFalse(valid)
        self.assertIn("additional Artifact SHA-256 footer", reason)
        self.assertIn("line 16", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_hash_keeps_malformed_additional_footer_line(self) -> None:
        report = replay_report()
        lines = report.splitlines(keepends=True)
        malformed = "- Artifact SHA-256 (excluding this line): not-a-digest\n"
        expected_body = "".join(lines[:-1]) + malformed
        actual = self.gate_module().normalized_report_hash(report + malformed)
        self.assertEqual(actual, hashlib.sha256(expected_body.encode("utf-8")).hexdigest())

    def test_malformed_sole_footer_is_refused(self) -> None:
        lines = replay_report().splitlines(keepends=True)
        lines[-1] = "- Artifact SHA-256 (excluding this line): not-a-digest\n"
        valid, reason, _ = self.gate_module().validate_report_text("".join(lines))
        self.assertFalse(valid)
        self.assertIn("invalid Artifact SHA-256 footer", reason)
        self.assertIn("line 15", reason)
        self.assertNotIn("not-a-digest", reason)

    def test_required_blocked_rows_key_does_not_match_private_label(self) -> None:
        self.denylist.write_text("Blocked\n", encoding="utf-8")
        valid, reason, _ = self.gate_module().validate_report_text(
            replay_report(note="- Replay note: no additional boundary."))
        self.assertTrue(valid, reason)

    def test_required_table_key_does_not_match_private_label(self) -> None:
        self.denylist.write_text("Goal\n", encoding="utf-8")
        valid, reason, _ = self.gate_module().validate_report_text(
            replay_report(note="- Replay note: no additional boundary."))
        self.assertTrue(valid, reason)

    def test_table_result_value_matching_header_word_is_still_checked(self) -> None:
        self.denylist.write_text("Goal\n", encoding="utf-8")
        valid, reason, _ = self.gate_module().validate_report_text(replay_report(reason="Goal"))
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 13", reason)
        self.assertNotIn("Goal", reason)

    def test_required_field_values_are_still_checked_for_private_labels(self) -> None:
        text = replay_report_with_blocked_line("Blocked rows: 0 (Acme Energy boundary)")
        valid, reason, _ = self.gate_module().validate_report_text(text)
        self.assertFalse(valid)
        self.assertIn("private tenant label", reason)
        self.assertIn("line 9", reason)
        self.assertNotIn("Acme Energy", reason)

    def test_missing_denylist_skips_label_check_but_runs_other_privacy_checks(self) -> None:
        missing = Path(self.temp.name) / "missing-labels.txt"
        with patch.dict(os.environ, {"REALDATA_REPLAY_DENYLIST": str(missing)}):
            clean, clean_reason, _ = self.gate_module().validate_report_text(replay_report())
            object_id, object_reason, _ = self.gate_module().validate_report_text(
                replay_report(note="- Replay note: 507f1f77bcf86cd799439011"))
        self.assertTrue(clean, clean_reason)
        self.assertIn("label check skipped", clean_reason.lower())
        self.assertFalse(object_id)
        self.assertIn("ObjectId-like token", object_reason)

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
