"""Tests for verify.py. Run: python3 -m unittest discover -s skillsets/repo-bootstrap/shared/verify/scripts/tests"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("verify", HERE.parent / "verify.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def make_repo(files, config=None):
    d = Path(tempfile.mkdtemp(prefix="verify-test-"))
    git(d, "init", "-q", "-b", "main")
    git(d, "config", "user.email", "t@example.invalid")
    git(d, "config", "user.name", "t")
    for rel, text in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    if config is not None:
        (d / ".verify").mkdir(exist_ok=True)
        (d / ".verify/config.json").write_text(json.dumps(config))
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "init")
    return d


def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        rc = fn(*a)
    return rc, buf.getvalue()


class WeakenFindings(unittest.TestCase):
    def diff(self, path, body, header=""):
        return f"diff --git a/{path} b/{path}\n{header}--- a/{path}\n+++ b/{path}\n@@ -1,3 +1,3 @@\n{body}"

    def test_added_skip_is_found(self):
        f = verify.weaken_findings(self.diff("src/a.test.ts", "+it.skip('works', () => {})\n"))
        self.assertTrue(any("adds a skip" in x for x in f), f)

    def test_env_gated_node_test_skip_is_found(self):
        f = verify.weaken_findings(self.diff("test/db.test.mjs", "+test('rs', { skip: !process.env.MONGO_URL }, async () => {})\n"))
        self.assertTrue(any("adds a skip" in x for x in f), f)

    def test_deleted_test_file_is_found(self):
        text = ("diff --git a/test/user.test.ts b/test/user.test.ts\ndeleted file mode 100644\nindex 1..0\n"
                "--- a/test/user.test.ts\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-expect(a).toBe(1)\n-expect(b).toBe(2)\n")
        f = verify.weaken_findings(text)
        self.assertIn("test/user.test.ts: deletes a test file", f)
        self.assertFalse(any("removes" in x for x in f), "a deleted file is reported once, not twice")

    def test_net_removed_assertions(self):
        f = verify.weaken_findings(self.diff("tests/test_api.py", "-    assert r.status == 200\n-    assert r.json()['ok']\n"))
        self.assertTrue(any("removes 2 more assertions" in x for x in f), f)

    def test_changed_expected_value(self):
        f = verify.weaken_findings(self.diff("src/sum.spec.ts", "-expect(sum(1, 2)).toBe(3)\n+expect(sum(1, 2)).toBe(4)\n"))
        self.assertTrue(any("changes an expected value" in x for x in f), f)

    def test_source_files_are_ignored(self):
        self.assertEqual(verify.weaken_findings(self.diff("src/sum.ts", "-it.skip('x')\n+it.skip('y')\n")), [])

    def test_removed_line_starting_with_dashes_is_not_a_header(self):
        # A removed SQL comment '-- x' shows up as '--- x' inside a hunk; it must be read as content.
        f = verify.weaken_findings(self.diff("test/q.test.ts", "--- select 1\n-expect(q()).toBe(1)\n"))
        self.assertTrue(any("removes 1 more" in x for x in f), f)

    def test_rewriting_an_assertion_is_not_weakening(self):
        f = verify.weaken_findings(self.diff("src/a.test.ts", "-expect(x).toEqual({a: 1})\n+expect(x).toEqual({a: 1})\n"))
        self.assertEqual(f, [])


class EvalScore(unittest.TestCase):
    def test_pass_at_1_and_pass_all_k(self):
        ds = [{"id": 1, "expected": "urgent"}, {"id": 2, "expected": "routine"}]
        preds = [{"id": 1, "output": "urgent"}, {"id": 1, "output": "urgent"}, {"id": 1, "output": "routine"},
                 {"id": 2, "output": "routine"}, {"id": 2, "output": "routine"}, {"id": 2, "output": "routine"}]
        r = verify.eval_score(ds, preds)
        self.assertAlmostEqual(r["pass_at_1"], 5 / 6)
        self.assertAlmostEqual(r["pass_all_k"], 0.5)
        self.assertAlmostEqual(r["labels"]["urgent"]["recall"], 2 / 3)
        self.assertAlmostEqual(r["labels"]["routine"]["precision"], 3 / 4)

    def test_thresholds_fail(self):
        ds = [{"id": 1, "expected": "a"}]
        r = verify.eval_score(ds, [{"id": 1, "output": "b"}], {"pass_all_k": 0.9, "labels": {"a": {"recall": 0.8}}})
        self.assertEqual(len(r["failures"]), 2, r["failures"])

    def test_missing_predictions_fail(self):
        r = verify.eval_score([{"id": 1, "expected": "a"}, {"id": 2, "expected": "a"}], [{"id": 1, "output": "a"}])
        self.assertEqual(r["missing_predictions"], ["2"])
        self.assertTrue(r["failures"])

    def test_structured_expectations(self):
        ds = [{"id": "s", "expected": {"contains": ["dose", "mg"]}}, {"id": "n", "expected": {"not_contains": ["diagnosis"]}}]
        r = verify.eval_score(ds, [{"id": "s", "output": "Dose: 5 MG"}, {"id": "n", "output": "see your doctor"}])
        self.assertEqual(r["pass_all_k"], 1.0)

    def test_judge_calibration(self):
        ds = [{"id": i, "expected": "x", "human": i < 5} for i in range(10)]
        preds = [{"id": i, "output": "x", "judge": i < 4 or i == 9} for i in range(10)]
        r = verify.eval_score(ds, preds, {"judge_min": 0.9})
        self.assertAlmostEqual(r["judge"]["tpr"], 0.8)
        self.assertAlmostEqual(r["judge"]["tnr"], 0.8)
        self.assertTrue(any("judge" in f for f in r["failures"]))


class Helpers(unittest.TestCase):
    def test_skipped_count_formats(self):
        self.assertEqual(verify.skipped_count("# tests 10\n# pass 8\n# skip 2\n"), 2)          # node:test TAP
        self.assertEqual(verify.skipped_count("ℹ tests 10\nℹ skipped 3\n"), 3)                  # node:test spec
        self.assertEqual(verify.skipped_count("Tests  5 passed | 4 skipped (9)"), 4)           # vitest
        self.assertEqual(verify.skipped_count("==== 3 passed, 1 skipped in 0.2s ===="), 1)    # pytest
        self.assertEqual(verify.skipped_count("Passed!  - Failed: 0, Passed: 9, Skipped: 5"), 5)  # dotnet
        self.assertEqual(verify.skipped_count("12 passed (3.1s)"), 0)                           # playwright

    def test_overall(self):
        st = lambda *s: [{"status": x} for x in s]
        self.assertEqual(verify.overall(st("pass", "na", "untouched")), "pass")
        self.assertEqual(verify.overall(st("pass", "missing")), "not-verified")
        self.assertEqual(verify.overall(st("missing", "fail")), "fail")

    def test_touched(self):
        self.assertTrue(verify.touched(None, ["**/jobs/**"]))
        self.assertTrue(verify.touched(["src/jobs/sync.ts"], ["**/jobs/**"]))
        self.assertTrue(verify.touched(["jobs/sync.ts"], ["**/jobs/**"]))
        self.assertFalse(verify.touched(["src/ui/button.tsx"], ["**/jobs/**"]))

    def test_stage_env_strips_forge_tokens(self):
        env = verify.stage_env({"GH_TOKEN": "x", "GITHUB_TOKEN": "y", "PATH": "/bin"}, {})
        self.assertEqual(env, {"PATH": "/bin"})
        self.assertIn("GH_TOKEN", verify.stage_env({"GH_TOKEN": "x"}, {"env": ["GH_TOKEN"]}))

    def test_slug_of(self):
        self.assertEqual(verify.slug_of("git@github.com:acme/app.git"), "acme/app")
        self.assertEqual(verify.slug_of("https://github.com/acme/app"), "acme/app")
        self.assertIsNone(verify.slug_of("https://gitlab.com/acme/app.git"))

    def test_load_env_file(self):
        p = Path(tempfile.mkdtemp()) / "x.env"
        p.write_text("# c\nexport A=1\nB='two'\n\nC=\"3\"\n")
        self.assertEqual(verify.load_env_file(p), {"A": "1", "B": "two", "C": "3"})


class Detection(unittest.TestCase):
    def test_node_repo_proposal(self):
        pkg = {"scripts": {"lint": "eslint .", "build": "next build", "test": "node --test",
                           "test:integration:db": "node --test test/int", "test:e2e": "playwright test"},
               "dependencies": {"next": "15", "openai": "5"}, "devDependencies": {"@playwright/test": "1"}}
        repo = make_repo({"package.json": json.dumps(pkg), "pnpm-lock.yaml": "", "src/jobs/sync.ts": "export {}\n",
                          "e2e/login.spec.ts": "await page.route('**/api/**', r => r.fulfill({}))\n",
                          "test/a.test.ts": "test('x', { skip: !process.env.DB }, () => {})\n"})
        d = verify.detect(repo)
        cfg = verify.proposal(d)
        self.assertEqual(cfg["setup"], "pnpm install --frozen-lockfile")
        self.assertEqual(cfg["stages"]["static"]["run"], "pnpm run lint && pnpm run build")
        self.assertEqual(cfg["stages"]["integration"]["run"], "pnpm run test:integration:db")
        self.assertEqual(cfg["stages"]["journeys"]["run"], "pnpm run test:e2e")
        self.assertIn("todo", cfg["stages"]["evals"])            # LLM dependency, no eval set yet
        self.assertIn("todo", cfg["stages"]["rehearsal"])        # background code found
        self.assertEqual(d["e2e_mocking_files"], ["e2e/login.spec.ts"])
        self.assertEqual(d["env_gated_skip_files"], 1)
        areas = {(f["severity"], f["area"]) for f in verify.doctor(repo)["findings"]}
        self.assertIn(("high", "contract"), areas)
        self.assertIn(("high", "journeys"), areas)               # network-mocked e2e
        self.assertIn(("high", "evals"), areas)

    def test_only_faking_the_own_backend_counts_as_mocking(self):
        allow_list = "await page.route(/^https?:/u, r => allowed.has(new URL(r.request().url()).origin) ? r.continue() : r.abort())\n"
        fake_api = "await page.route('**/api/trpc/payment.startCardSetup**', r => r.fulfill({ status: 200, body: '[]' }))\n"
        fake_page = "await page.route('**/qa-ready', r => r.fulfill({ body: '<h1>ok</h1>' }))\n"
        self.assertFalse(verify.fakes_backend(allow_list))
        self.assertFalse(verify.fakes_backend(fake_page))
        self.assertTrue(verify.fakes_backend(fake_api))
        self.assertTrue(verify.fakes_backend("await page.route(/\\/api\\/trpc\\//u, async (route) => {\n  await route.fulfill({ body })\n})\n"))
        self.assertTrue(verify.fakes_backend("const proc = /\\/api\\/trpc\\/invites\\./u;\nawait page.route(proc, (r) => r.fulfill({}))\n"))
        self.assertTrue(verify.fakes_backend("import { http } from 'msw'\nconst s = setupServer()\n"))
        repo = make_repo({"package.json": "{}", "e2e/qa/pay.spec.ts": fake_api, "e2e/qa/nav.spec.ts": allow_list,
                          "e2e/component/card.spec.tsx": fake_api, "e2e/button.ct.tsx": fake_api})
        self.assertEqual(verify.detect(repo)["e2e_mocking_files"], ["e2e/qa/pay.spec.ts"])

    def test_every_template_doctor_points_to_exists(self):
        import re
        src = (HERE.parent / "verify.py").read_text()
        refs = set(re.findall(r"\btemplates/[A-Za-z0-9_./-]+(?:#[a-z-]+)?", src))
        self.assertTrue(refs)
        for ref in refs:
            path, _, anchor = ref.partition("#")
            target = verify.TEMPLATES.parent / path
            self.assertTrue(target.exists(), ref)
            if anchor:
                self.assertIn(f"## {anchor}", target.read_text(), ref)

    def test_plain_repo_marks_na_with_reasons(self):
        cfg = verify.proposal(verify.detect(make_repo({"README.md": "x\n"})))
        self.assertEqual(cfg["stages"]["evals"]["na"], "no LLM features detected")
        self.assertEqual(cfg["stages"]["rehearsal"]["na"], "no background processing detected")
        self.assertIsNone(cfg["stages"]["unit"]["run"])
        self.assertIn("todo", cfg["stages"]["unit"])


class RunStage(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo({"a.txt": "x\n"})

    def test_missing_env_fails_only_in_strict_mode(self):
        spec = {"run": "true", "env": ["VERIFY_TEST_NOPE"]}
        self.assertEqual(verify.run_stage(self.repo, "integration", spec, True, None, {})["status"], "fail")
        self.assertEqual(verify.run_stage(self.repo, "integration", spec, False, None, {})["status"], "missing")

    def test_skipped_tests_fail_in_strict_mode(self):
        spec = {"run": "echo '# skip 2'"}
        self.assertEqual(verify.run_stage(self.repo, "integration", spec, True, None, dict(os.environ))["status"], "fail")
        self.assertEqual(verify.run_stage(self.repo, "integration", spec, False, None, dict(os.environ))["status"], "pass")
        self.assertEqual(verify.run_stage(self.repo, "unit", spec, True, None, dict(os.environ))["status"], "pass")

    def test_path_filter_and_na(self):
        self.assertEqual(verify.run_stage(self.repo, "rehearsal", {"run": "false", "paths": ["jobs/**"]}, True, ["ui/x.ts"], {})["status"], "untouched")
        self.assertEqual(verify.run_stage(self.repo, "evals", {"run": None, "na": "no LLM"}, True, None, {})["status"], "na")
        self.assertEqual(verify.run_stage(self.repo, "evals", {"run": None}, True, None, {})["status"], "missing")

    def test_timeout_kills_child_processes(self):
        marker = Path(tempfile.mkdtemp()) / "child-alive"
        cmd = f"(sleep 4; touch {marker}) & sleep 30"
        t0 = time.time()
        rc, out = verify.sh(cmd, timeout=1)
        self.assertEqual(rc, 124)
        self.assertLess(time.time() - t0, 15)
        time.sleep(5)
        self.assertFalse(marker.exists(), "a background child outlived the timeout")


class EndToEnd(unittest.TestCase):
    def test_run_writes_artifact_and_reports_not_verified(self):
        cfg = {"version": 1, "stages": {"static": {"run": "true"}, "unit": {"run": "true"},
                                        "integration": {"run": None, "todo": "add"}, "journeys": {"run": None, "na": "cli tool"},
                                        "evals": {"run": None, "na": "no LLM"}, "rehearsal": {"run": None, "na": "no data"}}}
        repo = make_repo({"a.txt": "x\n"}, cfg)
        rc, out = quiet(verify.main, ["run", str(repo)])
        self.assertEqual(rc, 1)
        self.assertIn("NOT VERIFIED", out)
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        art = json.loads((repo / ".verify/runs" / f"{sha}.json").read_text())
        self.assertEqual(art["verdict"], "not-verified")

    def test_run_passes_when_every_stage_passes_or_is_na(self):
        cfg = {"version": 1, "stages": {s: {"run": "true"} for s in verify.PER_CHANGE}}
        rc, out = quiet(verify.main, ["run", str(make_repo({"a.txt": "x\n"}, cfg))])
        self.assertEqual(rc, 0, out)
        self.assertIn("PASS", out)

    def test_weaken_check_needs_a_reason(self):
        repo = make_repo({"test/a.test.ts": "expect(1).toBe(1)\n"})
        git(repo, "checkout", "-q", "-b", "change")
        git(repo, "rm", "-q", "test/a.test.ts")
        git(repo, "commit", "-q", "-m", "drop test")
        rc, out = quiet(verify.main, ["weaken-check", str(repo), "--base", "main"])
        self.assertEqual(rc, 1, out)
        git(repo, "commit", "-q", "--allow-empty", "-m", "note\n\ntest-change-reason: feature removed in this PR")
        rc, out = quiet(verify.main, ["weaken-check", str(repo), "--base", "main"])
        self.assertEqual(rc, 0, out)

    def test_hook_ignores_ordinary_commands_and_never_blocks(self):
        for cmd in ("ls -la", "gh pr merge 12 --admin --squash"):
            payload = json.dumps({"tool_input": {"command": cmd}, "cwd": tempfile.mkdtemp()})
            p = subprocess.run([sys.executable, str(HERE.parent / "verify.py"), "hook"], input=payload,
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 0)
            self.assertEqual(p.stdout.strip(), "")  # not a git repo: nothing to say, never a deny

    def test_hook_notes_missing_contract_after_a_deploy(self):
        repo = make_repo({"README.md": "x\n"})
        payload = json.dumps({"tool_input": {"command": "vercel deploy --prod"}, "cwd": str(repo)})
        p = subprocess.run([sys.executable, str(HERE.parent / "verify.py"), "hook"], input=payload,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0)
        out = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PostToolUse")
        self.assertNotIn("permissionDecision", out)
        self.assertIn("no .verify/config.json", out["additionalContext"])
        self.assertIn("NOT VERIFIED", out["additionalContext"])
        self.assertIn("postdeploy", out["additionalContext"])


if __name__ == "__main__":
    unittest.main()
