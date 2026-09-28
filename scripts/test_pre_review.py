from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pre-review.py"
FIXTURES = ROOT / "scripts" / "fixtures" / "pre-review"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class PreReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="pre-review-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Pre-review fixture")
        git(self.repo, "config", "user.email", "pre-review@example.invalid")
        (self.repo / "README.md").write_text("fixture base\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "fixture base")
        self.initial_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        git(self.repo, "update-ref", "refs/remotes/origin/main", self.initial_sha)
        self.output = self.base / "packet"

    def add_fixture(self, fixture: str, target: str | None = None) -> Path:
        relative = Path(target or fixture)
        destination = self.repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / fixture, destination)
        return destination

    def run_pre_review(self, *args: str, env: dict[str, str] | None = None,
                       base: str | None = None) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        command = [sys.executable, str(SCRIPT), "--repo", str(self.repo),
                   "--output-dir", str(self.output)]
        if base:
            command.extend(["--base", base])
        command.extend(args)
        result = subprocess.run(command, cwd=self.repo, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, check=False)
        packet = json.loads((self.output / "pre-review.json").read_text(encoding="utf-8"))
        summary = (self.output / "pre-review.md").read_bytes()
        encoded = (self.output / "pre-review.json").read_bytes()
        self.assertEqual(packet["packet_bytes"], len(encoded) + len(summary))
        self.assertLessEqual(packet["packet_bytes"], packet["packet_budget_bytes"])
        self.assertEqual(packet["packet_budget_bytes"], 64 * 1024)
        self.assertEqual(packet["schema_version"], 1)
        self.assertIn("head_sha", packet)
        self.assertIn("merge_base_sha", packet["base"])
        self.assertIn("changed_paths", packet)
        self.assertIn("raw_diff_bytes", packet)
        self.assertTrue(all(len(item["output_tail"].encode("utf-8")) <= 4096 for item in packet["commands"]))
        self.assertTrue(all("duration_ms" in item for item in packet["commands"]))
        self.assertTrue(any(item["name"] == "built-in-rule-scan" for item in packet["commands"]))
        return result, packet

    @staticmethod
    def rule_ids(packet: dict[str, object]) -> set[str]:
        return {str(hit["rule_id"]) for hit in packet["rule_hits"]}  # type: ignore[index]

    def assert_rule_pair(self, failing_fixture: str, passing_fixture: str, target: str,
                         rule_id: str, passing_target: str | None = None) -> None:
        failed_path = self.add_fixture(failing_fixture, target)
        result, packet = self.run_pre_review()
        self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(rule_id, self.rule_ids(packet))
        failed_path.unlink()
        self.add_fixture(passing_fixture, passing_target or target)
        _result, passing_packet = self.run_pre_review()
        self.assertNotIn(rule_id, self.rule_ids(passing_packet))

    def test_floating_promise_fixture_fails_with_named_rule(self) -> None:
        self.add_fixture("floating-promise.ts", "src/floating-promise.mts")
        result, packet = self.run_pre_review()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pre_review.no_floating_promises", self.rule_ids(packet))
        self.assertTrue(any(item["name"] == "eslint-no-floating-promises" for item in packet["commands"]))
        self.assertIn("src/floating-promise.mts", packet["changed_paths"])

    def test_floating_promise_regex_fixture_fails_and_safe_fixture_passes(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        failing = (FIXTURES / "floating-promise.ts").read_text(encoding="utf-8")
        passing = (FIXTURES / "floating-promise-safe.ts").read_text(encoding="utf-8")
        self.assertIn("pre_review.no_floating_promises",
                      {hit["rule_id"] for hit in namespace["study_regex_hits"](self.repo, {"src/floating.ts": failing})})
        self.assertNotIn("pre_review.no_floating_promises",
                         {hit["rule_id"] for hit in namespace["study_regex_hits"](self.repo, {"src/floating.ts": passing})})

    def test_rule_fixture_sources_do_not_self_report_in_pre_review(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        paths = [
            "scripts/fixtures/pre-review/date-validation.py",
            "scripts/fixtures/pre-review/floating-promise.ts",
            "scripts/fixtures/pre-review/url-parser-mismatch.ts",
        ]
        hits, check = namespace["builtin_rule_scan"](ROOT, paths)
        self.assertEqual(hits, [])
        self.assertEqual(check["status"], "pass")

    def test_clean_fixture_has_no_rule_hits(self) -> None:
        self.add_fixture("clean.ts", "src/clean.ts")
        result, packet = self.run_pre_review()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(packet["rule_hits"], [])

    def test_workflow_without_permissions_fails_with_named_rule(self) -> None:
        self.add_fixture("missing-permissions.yml", ".github/workflows/token-use.yml")
        result, packet = self.run_pre_review()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pre_review.github_token_permissions", self.rule_ids(packet))

    def test_python_date_digit_regex_fails_with_named_rule(self) -> None:
        self.add_fixture("date-validation.py", "scripts/date_validation.py")
        result, packet = self.run_pre_review()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pre_review.python_unicode_digits", self.rule_ids(packet))

    def test_python_date_regex_with_re_ascii_has_no_digit_rule_hit(self) -> None:
        self.add_fixture("ascii-date-validation.py", "scripts/date_validation.py")
        _result, packet = self.run_pre_review()
        self.assertNotIn("pre_review.python_unicode_digits", self.rule_ids(packet))

    def test_api_version_detector_has_no_digit_rule_hit(self) -> None:
        self.add_fixture("api-version-detector.py", "scripts/api_version_detector.py")
        _result, packet = self.run_pre_review()
        self.assertNotIn("pre_review.python_unicode_digits", self.rule_ids(packet))

    def test_safe_url_vetting_does_not_hit_mismatch_rule(self) -> None:
        self.add_fixture("safe-database-url.ts", "src/safe-database-url.ts")
        result, packet = self.run_pre_review()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("pre_review.url_parser_mismatch", self.rule_ids(packet))

    def test_url_parser_mismatch_fixture_has_named_rule(self) -> None:
        self.add_fixture("url-parser-mismatch.ts", "src/database-url.ts")
        result, packet = self.run_pre_review()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pre_review.url_parser_mismatch", self.rule_ids(packet))

    def test_identity_label_normalization_rule_failing_and_passing_fixtures(self) -> None:
        self.assert_rule_pair("identity-label-raw.ts", "identity-label-normalized.ts", "src/identity.ts",
                              "pre_review.identity_label_normalization")

    def test_python_identity_membership_rule_failing_and_passing_fixtures(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        failed = (FIXTURES / "identity-membership-raw.py").read_text(encoding="utf-8")
        passed = (FIXTURES / "identity-membership-normalized.py").read_text(encoding="utf-8")
        self.assertIn("pre_review.identity_label_normalization",
                      {hit["rule_id"] for hit in namespace["study_regex_hits"](self.repo, {"src/identity.py": failed})})
        self.assertNotIn("pre_review.identity_label_normalization",
                         {hit["rule_id"] for hit in namespace["study_regex_hits"](self.repo, {"src/identity.py": passed})})

    def test_remote_demo_database_guard_rule_failing_and_passing_fixtures(self) -> None:
        self.assert_rule_pair("remote-demo-db-unprotected.ts", "remote-demo-db-guarded.ts", "src/demo-seed.ts",
                              "pre_review.remote_database_seed_target_guard")

    def test_demo_login_password_rule_failing_and_passing_fixtures(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        failed = (FIXTURES / "demo-login-unprotected.ts").read_text(encoding="utf-8")
        passed = (FIXTURES / "demo-login-guarded.ts").read_text(encoding="utf-8")
        self.assertIn("pre_review.remote_database_seed_target_guard",
                      {hit["rule_id"] for hit in namespace["study_regex_hits"](self.repo, {"src/demo-seed.ts": failed})})
        self.assertNotIn("pre_review.remote_database_seed_target_guard",
                         {hit["rule_id"] for hit in namespace["study_regex_hits"](self.repo, {"src/demo-seed.ts": passed})})

    def test_legacy_identity_hostname_rule_failing_and_passing_fixtures(self) -> None:
        self.assert_rule_pair("legacy-identity-hostname.ts", "shared-identity-target-guard.ts", "src/target.ts",
                              "pre_review.legacy_identity_hostname_guard")

    def test_external_json_shape_rule_failing_and_passing_fixtures(self) -> None:
        self.assert_rule_pair("external-json-unchecked.py", "external-json-checked.py", "scripts/api_reply.py",
                              "pre_review.external_response_shape")

    def test_external_json_shape_rule_respects_exception_guard(self) -> None:
        self.assert_rule_pair("external-json-exception-unchecked.py", "external-json-exception-guarded.py",
                              "scripts/api_reply.py", "pre_review.external_response_shape")

    def test_workflow_gh_run_permissions_rule_failing_and_passing_fixtures(self) -> None:
        self.assert_rule_pair("workflow-gh-run-missing-access.yml", "workflow-gh-run-authorized.yml",
                              ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        self.assert_rule_pair("workflow-gh-run-multiline-missing-access.yml",
                              "workflow-gh-run-multiline-authorized.yml",
                              ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        self.assert_rule_pair("workflow-gh-run-named-literal-missing-token.yml",
                              "workflow-gh-run-named-authorized.yml",
                              ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        self.assert_rule_pair("workflow-gh-run-named-folded-missing-actions.yml",
                              "workflow-gh-run-named-authorized.yml",
                              ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        self.assert_rule_pair("workflow-gh-run-unrelated-token-step.yml",
                              "workflow-gh-run-named-authorized.yml",
                              ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        self.assert_rule_pair("workflow-gh-run-unrelated-job-permission.yml",
                              "workflow-gh-run-named-authorized.yml",
                              ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        self.assert_rule_pair("workflow-gh-run-named-literal-missing-token.yml",
                              "workflow-gh-run-workflow-inherited-authorized.yml",
                              ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        self.assert_rule_pair("workflow-gh-run-named-folded-missing-actions.yml",
                              "workflow-gh-run-job-inherited-authorized.yml",
                              ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        for fixture in (
                "workflow-gh-run-mixed-jobs-authorized-first.yml",
                "workflow-gh-run-mixed-jobs-unauthorized-first.yml",
                "workflow-gh-run-mixed-steps-authorized-first.yml",
                "workflow-gh-run-mixed-steps-unauthorized-first.yml"):
            self.assert_rule_pair(fixture, "workflow-gh-run-named-authorized.yml",
                                  ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        self.assert_rule_pair("workflow-gh-run-empty-step-token-override.yml",
                              "workflow-gh-run-workflow-inherited-authorized.yml",
                              ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        self.assert_rule_pair("workflow-gh-run-empty-step-token-override-commented-steps.yml",
                              "workflow-gh-run-workflow-inherited-authorized.yml",
                              ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        for fixture in (
                "workflow-gh-run-empty-step-token-override-aligned-sequence.yml",
                "workflow-gh-run-empty-step-token-override-quoted-steps.yml",
                "workflow-gh-run-empty-step-token-override-quoted-env.yml",
                "workflow-gh-run-empty-step-token-override-spaced-item.yml"):
            self.assert_rule_pair(fixture, "workflow-gh-run-workflow-inherited-authorized.yml",
                                  ".github/workflows/inspect-run.yml",
                                  "pre_review.workflow_gh_run_permissions")
        for fixture in (
                "workflow-gh-run-quoted-inline-env-workflow-single-empty.yml",
                "workflow-gh-run-quoted-inline-env-workflow-double-empty.yml",
                "workflow-gh-run-quoted-inline-env-job-single-empty.yml",
                "workflow-gh-run-quoted-inline-env-job-double-empty.yml",
                "workflow-gh-run-quoted-inline-env-step-single-empty.yml",
                "workflow-gh-run-quoted-inline-env-step-double-empty.yml"):
            self.assert_rule_pair(fixture, "workflow-gh-run-quoted-inline-env-all-scopes-authorized.yml",
                                  ".github/workflows/inspect-run.yml",
                                  "pre_review.workflow_gh_run_permissions")
        for fixture in (
                "workflow-gh-run-quoted-job-id-double-job-empty.yml",
                "workflow-gh-run-quoted-job-id-single-job-empty.yml",
                "workflow-gh-run-quoted-job-id-double-step-empty.yml",
                "workflow-gh-run-quoted-job-id-single-step-empty.yml",
                "workflow-gh-run-quoted-job-id-double-job-empty-extra-indent.yml",
                "workflow-gh-run-quoted-job-id-single-step-empty-extra-indent.yml",
                "workflow-gh-run-job-indent-flow-map-continuation.yml"):
            self.assert_rule_pair(fixture, "workflow-gh-run-workflow-inherited-authorized.yml",
                                  ".github/workflows/inspect-run.yml",
                                  "pre_review.workflow_gh_run_permissions")
        self.assert_rule_pair("workflow-gh-run-empty-job-token-override.yml",
                              "workflow-gh-run-workflow-inherited-authorized.yml",
                              ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        for fixture in (
                "workflow-gh-run-step-env-first-empty-override.yml",
                "workflow-gh-run-step-inline-map-empty-override.yml",
                "workflow-gh-run-step-block-scalar-empty-override.yml"):
            self.assert_rule_pair(fixture, "workflow-gh-run-workflow-inherited-authorized.yml",
                                  ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        for fixture in (
                "workflow-gh-run-inline-after-run-empty-override.yml",
                "workflow-gh-run-inline-after-name-omitted-token.yml",
                "workflow-gh-run-explicit-indent-empty-token.yml"):
            self.assert_rule_pair(fixture, "workflow-gh-run-workflow-inherited-authorized.yml",
                                  ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        for fixture in (
                "workflow-gh-run-quoted-step-inline-empty-token.yml",
                "workflow-gh-run-quoted-step-block-empty-token.yml",
                "workflow-gh-run-quoted-job-inline-empty-token.yml",
                "workflow-gh-run-quoted-job-block-empty-token.yml"):
            self.assert_rule_pair(fixture, "workflow-gh-run-workflow-inherited-authorized.yml",
                                  ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        for fixture in (
                "workflow-gh-run-expression-before-empty-step-token.yml",
                "workflow-gh-run-expression-before-empty-job-token.yml"):
            self.assert_rule_pair(fixture, "workflow-gh-run-workflow-inherited-authorized.yml",
                                  ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        for fixture in (
                "workflow-gh-run-quoted-note-before-empty-step-token.yml",
                "workflow-gh-run-quoted-note-before-empty-job-token.yml"):
            self.assert_rule_pair(fixture, "workflow-gh-run-workflow-inherited-authorized.yml",
                                  ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")
        for fixture in (
                "workflow-gh-run-single-quote-backslash-job.yml",
                "workflow-gh-run-plain-apostrophe-job.yml",
                "workflow-gh-run-single-quote-backslash-step.yml",
                "workflow-gh-run-plain-apostrophe-step.yml",
                "workflow-gh-run-escaped-quote-job.yml",
                "workflow-gh-run-quote-only-job.yml",
                "workflow-gh-run-escaped-quote-step.yml",
                "workflow-gh-run-quote-only-step.yml",
                "workflow-gh-run-embedded-quote-job.yml",
                "workflow-gh-run-embedded-double-quote-job.yml",
                "workflow-gh-run-embedded-quote-step.yml",
                "workflow-gh-run-embedded-double-quote-step.yml",
                "workflow-gh-run-multiline-flow-job.yml",
                "workflow-gh-run-multiline-flow-job-brace-next-line.yml",
                "workflow-gh-run-multiline-flow-step.yml",
                "workflow-gh-run-multiline-flow-step-brace-next-line.yml",
                "workflow-gh-run-multiline-flow-comment-job.yml",
                "workflow-gh-run-multiline-flow-comment-step.yml",
                "workflow-gh-run-doubled-quote-comment-job.yml",
                "workflow-gh-run-doubled-quote-comment-step.yml",
                "workflow-gh-run-multiline-quoted-hash-job.yml",
                "workflow-gh-run-multiline-quoted-hash-step.yml",
                "workflow-gh-run-multiline-quoted-hash-job-aligned-close.yml",
                "workflow-gh-run-multiline-quoted-hash-step-aligned-close.yml",
                "workflow-gh-run-unindented-comment-job-boundary.yml",
                "workflow-gh-run-unindented-comment-step-boundary.yml"):
            self.assert_rule_pair(fixture, "workflow-gh-run-workflow-inherited-authorized.yml",
                                  ".github/workflows/inspect-run.yml", "pre_review.workflow_gh_run_permissions")

    def test_cited_symbol_rule_failing_and_passing_fixtures(self) -> None:
        failed_path = self.add_fixture("cited-absent-symbol.md", "docs/review-citation.md")
        self.add_fixture("cited-symbol-comment-only.ts", "src/comment.ts")
        result, packet = self.run_pre_review()
        self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("pre_review.cited_symbol_exists", self.rule_ids(packet))
        failed_path.unlink()
        self.add_fixture("cited-present-symbol.md", "docs/review-citation.md")
        self.add_fixture("cited-symbol-defined.ts", "src/gate.ts")
        git(self.repo, "add", "src/gate.ts")
        _result, passing_packet = self.run_pre_review()
        self.assertNotIn("pre_review.cited_symbol_exists", self.rule_ids(passing_packet))

    def test_markdown_glob_rule_failing_and_passing_fixtures(self) -> None:
        self.assert_rule_pair("markdown-unbackticked-glob.md", "markdown-backticked-glob.md",
                              "docs/glob.md", "pre_review.markdown_glob_code_span")

    def test_plan_rewalk_consistency_rule_failing_and_passing_fixtures(self) -> None:
        plan = self.add_fixture("unresolved-plan.md", ".qa/plan.md")
        rewalk = self.add_fixture("passing-rewalk.json", ".qa/rewalk.json")
        result, packet = self.run_pre_review()
        self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("pre_review.plan_rewalk_unresolved_conflict", self.rule_ids(packet))
        rewalk.unlink()
        rewalk = self.add_fixture("failing-rewalk-verdict.json", ".qa/rewalk.json")
        result, packet = self.run_pre_review()
        self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("pre_review.plan_rewalk_unresolved_conflict", self.rule_ids(packet))
        plan.unlink()
        rewalk.unlink()
        self.add_fixture("passing-plan.md", ".qa/plan.md")
        self.add_fixture("passing-rewalk.json", ".qa/rewalk.json")
        _result, passing_packet = self.run_pre_review()
        self.assertNotIn("pre_review.plan_rewalk_unresolved_conflict", self.rule_ids(passing_packet))
        (self.repo / ".qa/rewalk.json").unlink()
        self.add_fixture("passing-rewalk-verdict.json", ".qa/rewalk.json")
        _result, passing_verdict_packet = self.run_pre_review()
        self.assertNotIn("pre_review.plan_rewalk_unresolved_conflict", self.rule_ids(passing_verdict_packet))

    def test_static_study_coverage_is_11_of_11(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        self.assertEqual(len(namespace["STUDY_STATIC_DEFECT_RULES"]), 11)
        self.assertEqual(set(namespace["STUDY_STATIC_DEFECT_RULES"]),
                         {"12", "30", "31", "33", "45", "47", "48", "49", "51", "52", "55"})

    def test_builtin_rule_pack_is_active_without_semgrep(self) -> None:
        self.add_fixture("clean.ts", "src/clean.ts")
        result, packet = self.run_pre_review()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertGreaterEqual(len(packet["active_builtin_rules"]), 12)
        self.assertEqual(packet["study_static_covered"], packet["study_static_total"])
        self.assertTrue(any(str(path).endswith("pre-review.yml") for path in packet["active_rule_files"]))

    def test_project_rules_are_passed_to_semgrep_when_installed(self) -> None:
        self.add_fixture("date-validation.py", "src/date_validation.py")
        project_rules = self.repo / ".review-rules" / "local.yml"
        project_rules.parent.mkdir()
        project_rules.write_text("rules: []\n", encoding="utf-8")
        fake_bin = self.base / "bin"
        fake_bin.mkdir()
        semgrep = fake_bin / "semgrep"
        semgrep.write_text("#!/usr/bin/env python3\nimport json\nprint(json.dumps({'results': []}))\n", encoding="utf-8")
        semgrep.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        result, packet = self.run_pre_review(env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(packet["active_rule_files"], [
            str((ROOT / "skillsets/pr-review/semgrep/pre-review.yml").resolve()),
            str(project_rules.resolve()),
        ])
        semgrep_command = next(item for item in packet["commands"] if item["name"] == "semgrep")
        self.assertIn(str(project_rules.resolve()), semgrep_command["command"])

    def test_unresolvable_base_fails_closed_without_packet(self) -> None:
        result = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(self.repo), "--base", "missing/base",
                                 "--output-dir", str(self.output)], cwd=self.repo, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("base ref cannot be resolved", result.stderr)
        self.assertFalse(self.output.exists())

    def test_skip_tests_is_explicit_and_does_not_run_a_test_command(self) -> None:
        self.add_fixture("date-validation.py", "scripts/test_date_validation.py")
        result, packet = self.run_pre_review("--skip-tests")
        self.assertNotEqual(result.returncode, 0)
        test_command = next(item for item in packet["commands"] if item["name"] == "focused-tests")
        self.assertEqual(test_command["status"], "skip")
        self.assertIn("skipped by --skip-tests", test_command["output_tail"])
        self.assertIsNone(test_command["exit_code"])

    def test_skip_repo_lint_records_skip_without_running_package_script(self) -> None:
        (self.repo / "package.json").write_text(
            json.dumps({"scripts": {"lint": "node -e \"process.exit(99)\""}}), encoding="utf-8"
        )
        result, packet = self.run_pre_review("--skip-repo-lint")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        lint = next(item for item in packet["commands"] if item["name"] == "repo-lint")
        self.assertEqual(lint["status"], "skip")
        self.assertIsNone(lint["exit_code"])
        self.assertIn("skipped by --skip-repo-lint", lint["output_tail"])

    def test_typescript_test_runner_missing_is_skipped_without_package_manager_exec(self) -> None:
        (self.repo / "package.json").write_text(
            json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8"
        )
        namespace = runpy.run_path(str(SCRIPT))
        with patch.object(shutil, "which", return_value=None):
            commands = namespace["focused_test_commands"](self.repo, ["src/example.test.ts"], self.output)
        self.assertEqual(commands, [("focused-typescript-tests", [], "vitest not installed")])

    def test_python_pytest_style_file_is_not_reported_as_run_without_pytest(self) -> None:
        test_file = self.repo / "tests" / "test_sample.py"
        test_file.parent.mkdir()
        test_file.write_text("def test_example():\n    assert True\n", encoding="utf-8")
        namespace = runpy.run_path(str(SCRIPT))
        with patch.object(shutil, "which", return_value=None):
            commands = namespace["focused_test_commands"](self.repo, ["tests/test_sample.py"], self.output)
        self.assertEqual(commands, [(
            "focused-python-tests", [],
            "pytest not installed; test files are not standalone unittest scripts",
        )])

    def test_standalone_unittest_uses_python_even_when_pytest_shim_exists(self) -> None:
        test_file = self.repo / "tests" / "test_sample.py"
        test_file.parent.mkdir()
        test_file.write_text("import unittest\nif __name__ == '__main__': unittest.main()\n", encoding="utf-8")
        namespace = runpy.run_path(str(SCRIPT))
        with patch.object(shutil, "which", return_value="/pyenv/shims/pytest"):
            commands = namespace["focused_test_commands"](self.repo, ["tests/test_sample.py"], self.output)
        self.assertEqual(commands, [("focused-python-tests", [sys.executable, "./tests/test_sample.py"], None)])

    def test_command_timeout_is_unverified_not_failure(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        with patch.object(namespace["subprocess"], "run", side_effect=subprocess.TimeoutExpired(["slow-check"], 1, output=b"still running")):
            command = namespace["record_command"]("slow-check", ["slow-check"], self.repo)
        self.assertEqual(command["status"], "timeout")
        self.assertEqual(command["verification"], "unverified")
        self.assertIsNone(command["exit_code"])
        self.assertIn("result is unverified", command["output_tail"])
        self.assertNotEqual(command["status"], "fail")

    def test_environment_failures_are_unverified_errors(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        for output in (b"EPERM: operation not permitted", b"DATABASE_URL is not set",
                       b"refusing to provision fixture identities: DATABASE_URL is not a postgres:// URL",
                       b"no server is available", b"Operation not permitted (os error 1)",
                       b"Process from config.webServer was not able to start. Exit code: 127; next: command not found"):
            with self.subTest(output=output), patch.object(
                namespace["subprocess"], "run",
                return_value=subprocess.CompletedProcess(["check"], 1, output),
            ):
                command = namespace["record_command"]("environment-check", ["check"], self.repo)
                self.assertEqual(command["status"], "error")
                self.assertEqual(command["verification"], "unverified")
                self.assertEqual(command["error_kind"], "environment")
                self.assertNotEqual(command["status"], "fail")

    def test_generated_or_dependency_module_missing_is_environment_error(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        for output in (b"Cannot find module '@/prisma/client' or its corresponding type declarations.",
                       b"Cannot find package 'node_modules/example-runtime' imported from app.ts",
                       b"Cannot find module 'react' or its corresponding type declarations.",
                       b"Cannot find package '@radix-ui/react-tabs' imported from app.ts"):
            with self.subTest(output=output), patch.object(
                namespace["subprocess"], "run",
                return_value=subprocess.CompletedProcess(["tsc"], 2, output),
            ):
                command = namespace["record_command"]("typescript-typecheck", ["tsc"], self.repo)
                self.assertEqual(command["status"], "error")
                self.assertEqual(command["verification"], "unverified")
                self.assertEqual(command["error_kind"], "environment")

        with patch.object(
            namespace["subprocess"], "run",
            return_value=subprocess.CompletedProcess(
                ["tsc"], 2, b"Cannot find module './missing-source' or its corresponding type declarations."
            ),
        ):
            source_error = namespace["record_command"]("typescript-typecheck", ["tsc"], self.repo)
        self.assertEqual(source_error["status"], "fail")
        with patch.object(
            namespace["subprocess"], "run",
            return_value=subprocess.CompletedProcess(
                ["tsc"], 2, b"Cannot find module '@/missing-source' or its corresponding type declarations."
            ),
        ):
            alias_error = namespace["record_command"]("typescript-typecheck", ["tsc"], self.repo)
        self.assertEqual(alias_error["status"], "fail")

    def test_source_base_shas_override_stale_clone_origin_ref(self) -> None:
        git(self.repo, "checkout", "-b", "source-base")
        source_file = self.repo / "src" / "source-base.ts"
        source_file.parent.mkdir()
        source_file.write_text("export const sourceBase = true;\n", encoding="utf-8")
        git(self.repo, "add", "src/source-base.ts")
        git(self.repo, "commit", "-m", "source base commit")
        source_base_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        git(self.repo, "update-ref", "refs/remotes/origin/main", source_base_sha)

        git(self.repo, "checkout", "-b", "stale-base", self.initial_sha)
        wrong_file = self.repo / "stale-base-only.txt"
        wrong_file.write_text("wrong ref\n", encoding="utf-8")
        git(self.repo, "add", "stale-base-only.txt")
        git(self.repo, "commit", "-m", "stale clone origin ref")
        stale_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()

        git(self.repo, "checkout", "source-base")
        changed = self.repo / "src" / "change.ts"
        changed.write_text("export const change = true;\n", encoding="utf-8")
        git(self.repo, "add", "src/change.ts")
        git(self.repo, "commit", "-m", "PR change")
        head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()

        clone = self.base / "clone"
        subprocess.run(["git", "clone", "--no-hardlinks", "--branch", "source-base",
                        str(self.repo), str(clone)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        git(clone, "update-ref", "refs/remotes/origin/main", stale_sha)
        clone_output = self.base / "clone-packet"
        result = subprocess.run([
            sys.executable, str(SCRIPT), "--repo", str(clone), "--base", "origin/main",
            "--base-sha", source_base_sha, "--merge-base-sha", source_base_sha,
            "--output-dir", str(clone_output), "--skip-tests", "--skip-repo-lint",
        ], cwd=clone, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        packet = json.loads((clone_output / "pre-review.json").read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(packet["base"]["sha"], source_base_sha)
        self.assertEqual(packet["base"]["merge_base_sha"], source_base_sha)
        self.assertEqual(packet["head_sha"], head_sha)
        self.assertEqual(packet["changed_paths"], ["src/change.ts"])

    def test_playwright_output_is_external_to_reviewed_repo(self) -> None:
        (self.repo / "playwright.config.ts").write_text("export default {};\n", encoding="utf-8")
        namespace = runpy.run_path(str(SCRIPT))
        with patch.object(namespace["shutil"], "which", return_value="/bin/playwright"):
            commands = namespace["focused_test_commands"](self.repo, ["e2e/example.spec.ts"], self.output)
        output_dir = Path(commands[0][1][commands[0][1].index("--output") + 1])
        self.assertFalse(output_dir.is_relative_to(self.repo))
        self.assertIn("--reporter=json", commands[0][1])
        namespace = runpy.run_path(str(SCRIPT))
        with patch.object(namespace["subprocess"], "run",
                          return_value=subprocess.CompletedProcess(["playwright"], 0, b"")) as run:
            namespace["record_command"]("focused-playwright-tests", ["playwright", "test"], self.repo,
                                        output_dir=self.output)
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["PLAYWRIGHT_JSON_OUTPUT_FILE"], str(self.output / "playwright-report.json"))
        self.assertEqual(environment["TMPDIR"], str(self.output))
        namespace = runpy.run_path(str(SCRIPT))
        with patch.object(namespace["subprocess"], "run",
                          return_value=subprocess.CompletedProcess(["playwright"], 0, b"")) as run:
            namespace["record_command"]("focused-playwright-tests", ["playwright", "test"], self.repo,
                                        output_dir=self.output)
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["PLAYWRIGHT_JSON_OUTPUT_FILE"], str(self.output / "playwright-report.json"))
        self.assertEqual(environment["TMPDIR"], str(self.output))

    def test_clean_matching_checkout_uses_in_place_even_below_disk_floor(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        gib = 1024**3
        self.assertEqual(namespace["execution_plan"](True, True, 17 * gib), ("in-place", None))

    def test_clean_pr_head_runs_in_place_and_preserves_porcelain(self) -> None:
        changed = self.repo / "src" / "change.ts"
        changed.parent.mkdir()
        changed.write_text("export const change = true;\n", encoding="utf-8")
        git(self.repo, "add", "src/change.ts")
        git(self.repo, "commit", "-m", "PR change")
        before = subprocess.check_output(["git", "status", "--porcelain"], cwd=self.repo)
        result, packet = self.run_pre_review("--base", "origin/main")
        after = subprocess.check_output(["git", "status", "--porcelain"], cwd=self.repo)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(packet["execution"]["mode"], "in-place")
        self.assertTrue(packet["source_porcelain_unchanged"])
        self.assertEqual(before, after)
        self.assertEqual(next(item for item in packet["commands"]
                              if item["name"] == "source-porcelain-unchanged")["status"], "pass")

    def test_dirty_or_mismatched_checkout_uses_detached_worktree_when_capacity_allows(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        gib = 1024**3
        self.assertEqual(namespace["execution_plan"](False, True, 21 * gib), ("detached-worktree", None))
        self.assertEqual(namespace["execution_plan"](True, False, 21 * gib), ("detached-worktree", None))

    def test_dirty_checkout_skips_worktree_hydration_below_disk_floor(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        gib = 1024**3
        mode, reason = namespace["execution_plan"](False, True, 17 * gib)
        self.assertEqual(mode, "unverified")
        self.assertIn("disk 17.0 GiB free is below 20 GiB", reason)

    def test_source_porcelain_unchanged_assertion_reports_both_outcomes(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        before = b"?? journals/draft.md\n"
        same = namespace["porcelain_result"](before, before)
        changed = namespace["porcelain_result"](before, before + b" M src/index.ts\n")
        self.assertEqual(same["status"], "pass")
        self.assertEqual(changed["status"], "fail")
        self.assertEqual(changed["error_kind"], "tier-defect")
        self.assertEqual(same["command"], ["git", "status", "--porcelain"])

    def test_runner_records_tier_defect_when_a_check_changes_source_porcelain(self) -> None:
        (self.repo / "package.json").write_text(
            json.dumps({"scripts": {"lint": "configured repository lint"}}), encoding="utf-8"
        )
        (self.repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        changed = self.repo / "src" / "change.ts"
        changed.parent.mkdir()
        changed.write_text("export const changed = true;\n", encoding="utf-8")
        git(self.repo, "add", "package.json", "pnpm-lock.yaml", "src/change.ts")
        git(self.repo, "commit", "-m", "PR change")
        fake_bin = self.base / "bin"
        fake_bin.mkdir()
        pnpm = fake_bin / "pnpm"
        pnpm.write_text("#!/bin/sh\nprintf 'tier side effect\\n' > tier-created.txt\n", encoding="utf-8")
        pnpm.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        result, packet = self.run_pre_review("--base", "origin/main", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(packet["source_porcelain_unchanged"])
        status = next(item for item in packet["commands"] if item["name"] == "source-porcelain-unchanged")
        self.assertEqual(status["status"], "fail")
        self.assertEqual(status["error_kind"], "tier-defect")

    def test_direct_tsc_typecheck_disables_incremental_output(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        package = {"scripts": {"typecheck": "tsc --noEmit --incremental --tsBuildInfoFile .cache/types.tsbuildinfo"}}
        with patch.object(shutil, "which", return_value="/repo/node_modules/.bin/tsc"):
            command = namespace["readonly_typecheck_command"](self.repo, package, "pnpm")
        self.assertEqual(command, ["/repo/node_modules/.bin/tsc", "--noEmit", "--incremental", "false"])

    def test_bare_webserver_binary_resolves_from_repo_node_modules(self) -> None:
        self.add_fixture("playwright-bare-bin.config.ts", "playwright.config.ts")
        local_bin = self.repo / "node_modules" / ".bin"
        local_bin.mkdir(parents=True)
        server = local_bin / "fixture-web-server"
        server.write_text("#!/bin/sh\nprintf 'fixture server started\\n'\n", encoding="utf-8")
        server.chmod(0o755)
        namespace = runpy.run_path(str(SCRIPT))
        command = namespace["record_command"]("web-server", ["fixture-web-server"], self.repo)
        self.assertEqual(command["status"], "pass", command["output_tail"])
        self.assertIn("fixture server started", command["output_tail"])

    def test_pr_mode_ignores_worktree_paths_and_reports_out_of_diff_lint(self) -> None:
        (self.repo / "package.json").write_text(
            json.dumps({"scripts": {"lint": "configured repository lint"}}), encoding="utf-8"
        )
        (self.repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        changed = self.repo / "src" / "change.ts"
        changed.parent.mkdir()
        changed.write_text("export const changed = true;\n", encoding="utf-8")
        git(self.repo, "add", "package.json", "pnpm-lock.yaml", "src/change.ts")
        git(self.repo, "commit", "-m", "PR change")
        outside_path = "journals/card17-untracked.md"
        outside = self.repo / outside_path
        outside.parent.mkdir()
        outside.write_text("format issue outside the PR\n", encoding="utf-8")
        fake_bin = self.base / "bin"
        fake_bin.mkdir()
        pnpm = fake_bin / "pnpm"
        pnpm.write_text("#!/bin/sh\nprintf '[warn] journals/card17-untracked.md\\n'\nexit 1\n", encoding="utf-8")
        pnpm.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")

        pr_result, pr_packet = self.run_pre_review(env=env, base=self.initial_sha)
        self.assertEqual(pr_packet["review_scope"], "committed-range")
        self.assertCountEqual(pr_packet["changed_paths"], ["package.json", "pnpm-lock.yaml", "src/change.ts"])
        self.assertEqual(pr_packet["excluded_worktree_paths"], [outside_path])
        pr_lint = next(item for item in pr_packet["commands"] if item["name"] == "repo-lint")
        self.assertEqual(pr_lint["status"], "outside_diff")
        self.assertEqual(pr_lint["outside_diff_paths"], [outside_path])
        self.assertEqual(pr_result.returncode, 0, pr_result.stderr + pr_result.stdout)

        worktree_result, worktree_packet = self.run_pre_review(env=env)
        self.assertEqual(worktree_packet["review_scope"], "working-tree")
        self.assertIn(outside_path, worktree_packet["changed_paths"])
        worktree_lint = next(item for item in worktree_packet["commands"] if item["name"] == "repo-lint")
        self.assertEqual(worktree_lint["status"], "fail")
        self.assertNotIn("_raw_output", worktree_lint)
        self.assertNotEqual(worktree_result.returncode, 0)

    def test_pr_lint_does_not_hide_in_diff_findings_before_output_tail(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        command = {
            "status": "fail",
            "output_tail": "journals/card17-untracked.md:1: format issue",
            "_raw_output": "src/change.ts:1: actual PR defect\n" + ("padding\n" * 1000)
                            + "journals/card17-untracked.md:1: format issue",
        }
        classified = namespace["classify_outside_diff_lint"](command, ["src/change.ts"])
        self.assertEqual(classified["status"], "fail")
        self.assertNotIn("outside_diff_paths", classified)
        self.assertNotIn("_raw_output", classified)

    def test_hyphenated_python_source_finds_underscored_test_file(self) -> None:
        test_file = self.repo / "scripts" / "test_pre_review.py"
        test_file.parent.mkdir()
        test_file.write_text("import unittest\nunittest.main()\n", encoding="utf-8")
        git(self.repo, "add", "scripts/test_pre_review.py")
        namespace = runpy.run_path(str(SCRIPT))
        self.assertEqual(
            namespace["related_test_paths"](self.repo, ["scripts/pre-review.py"]),
            ["scripts/test_pre_review.py"],
        )

    def test_typescript_source_finds_sibling_spec_test(self) -> None:
        spec = self.repo / "src" / "module.spec.ts"
        spec.parent.mkdir()
        spec.write_text("import { test } from 'node:test';\n", encoding="utf-8")
        git(self.repo, "add", "src/module.spec.ts")
        namespace = runpy.run_path(str(SCRIPT))
        self.assertEqual(
            namespace["related_test_paths"](self.repo, ["src/module.ts"]),
            ["src/module.spec.ts"],
        )

    def test_default_packet_directory_is_excluded_on_repeated_run(self) -> None:
        self.add_fixture("clean.ts", "src/clean.ts")
        command = [sys.executable, str(SCRIPT), "--repo", str(self.repo), "--base", "HEAD"]
        first = subprocess.run(command, cwd=self.repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        first_packet_path = Path(first.stdout.split("JSON packet: ", 1)[1].splitlines()[0])
        self.assertFalse(first_packet_path.is_relative_to(self.repo))
        first_packet = json.loads(first_packet_path.read_text(encoding="utf-8"))
        second = subprocess.run(command, cwd=self.repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        second_packet_path = Path(second.stdout.split("JSON packet: ", 1)[1].splitlines()[0])
        self.assertFalse(second_packet_path.is_relative_to(self.repo))
        second_packet = json.loads(second_packet_path.read_text(encoding="utf-8"))
        self.assertEqual(first_packet["changed_paths"], second_packet["changed_paths"])
        self.assertEqual(first_packet["dirty"], second_packet["dirty"])

    def test_oversized_packet_is_bounded_and_fails_explicitly(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        packet: dict[str, object] = {
            "schema_version": 1,
            "repo": str(self.repo),
            "head_sha": "a" * 40,
            "base": {"ref": "main", "sha": "b" * 40, "merge_base_sha": "b" * 40},
            "dirty": True,
            "changed_paths": [f"src/module-{index:04d}.py" for index in range(2400)],
            "commands": [],
            "rule_hits": [{"rule_id": "fixture.rule", "path": f"src/module-{index:04d}.py",
                           "line": index + 1, "message": "fixture finding"} for index in range(2400)],
            "active_rule_files": [],
            "available_project_rule_files": [],
            "raw_diff_bytes": 0,
            "packet_bytes": 0,
            "packet_budget_bytes": 64 * 1024,
            "budget_excess_bytes": 0,
        }
        json_bytes, markdown_bytes = namespace["finalize_packet"](packet)
        self.assertLessEqual(len(json_bytes) + len(markdown_bytes), 64 * 1024)
        self.assertTrue(packet["packet_overflow"])
        self.assertGreater(packet["budget_excess_bytes"], 0)
        self.assertGreater(packet["changed_paths_omitted"], 0)
        self.assertGreater(packet["rule_hits_omitted"], 0)
        self.assertTrue(any(command["name"] == "packet-budget" and command["status"] == "fail"
                            for command in packet["commands"]))


if __name__ == "__main__":
    unittest.main()
