"""Tests for verify.py. Run: python3 -m unittest discover -s skillsets/repo-bootstrap/shared/verify/scripts/tests"""
import argparse
import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
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

    def test_stage_env_never_passes_forge_tokens(self):
        env = verify.stage_env({"GH_TOKEN": "x", "GITHUB_TOKEN": "y", "PATH": "/bin"}, {})
        self.assertEqual(env, {"PATH": "/bin"})
        # Naming a token in a stage's `env` list (a PR can edit it) does not let it through.
        self.assertNotIn("GH_TOKEN", verify.stage_env({"GH_TOKEN": "x"}, {"env": ["GH_TOKEN"]}))

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
        self.assertIn("todo", cfg["stages"]["mutation"])         # no mutation tool installed

    def test_installed_mutation_tool_fills_the_mutation_stage(self):
        node = make_repo({"package.json": json.dumps({"devDependencies": {"@stryker-mutator/core": "9"}})})
        self.assertEqual(verify.proposal(verify.detect(node))["stages"]["mutation"]["run"], "npx stryker run")
        py = make_repo({"pyproject.toml": "[tool.mutmut]\npaths_to_mutate = ['src/']\n"})
        self.assertEqual(verify.proposal(verify.detect(py))["stages"]["mutation"]["run"], "mutmut run")

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


class ForgeCalls(unittest.TestCase):
    """On a loaded host gh can take over a minute to start: the runner's forge calls get a long limit and one retry."""

    def fake_sh(self, results):
        calls = []

        def sh(cmd, cwd=None, env=None, timeout=None, merge=True):
            calls.append(timeout)
            return results[len(calls) - 1]
        return sh, calls

    def test_a_status_post_that_times_out_once_is_retried_with_the_long_limit(self):
        saved = verify.sh
        try:
            long = (verify.FORGE_TIMEOUT, verify.FORGE_ATTEMPTS)
            verify.sh, calls = self.fake_sh([(124, "timed out"), (0, "")])
            self.assertTrue(quiet(verify.post_status, "acme/app", "a" * 40, "verify/unit", "pass", "ok", *long)[0])
            self.assertEqual(calls, [verify.FORGE_TIMEOUT] * 2)
            verify.sh, calls = self.fake_sh([(124, "timed out")] * 3)
            self.assertFalse(quiet(verify.post_status, "acme/app", "a" * 40, "verify/unit", "pass", "ok", *long)[0])
            self.assertEqual(len(calls), verify.FORGE_ATTEMPTS)  # bounded: no third try
            verify.sh, calls = self.fake_sh([(124, "timed out"), (0, "")])
            self.assertFalse(quiet(verify.post_status, "acme/app", "a" * 40, "verify/unit", "pass", "ok")[0])
            self.assertEqual(calls, [30])  # `run --post-status` keeps one short try
        finally:
            verify.sh = saved
        self.assertGreaterEqual(verify.FORGE_TIMEOUT, 90)

    def test_the_runner_status_read_retries_but_the_default_read_does_not(self):
        saved = verify.sh
        try:
            verify.sh, calls = self.fake_sh([(124, ""), (0, '{"verify": {"state": "success", "at": "x"}}')])
            st = verify.forge_status("acme/app", "a" * 40, verify.FORGE_TIMEOUT, verify.FORGE_ATTEMPTS)
            self.assertEqual(st["verify"]["state"], "success")
            self.assertEqual(calls, [verify.FORGE_TIMEOUT] * 2)
            verify.sh, calls = self.fake_sh([(124, ""), (0, "{}")])
            self.assertIsNone(verify.forge_status("acme/app", "a" * 40))  # the hook and doctor keep one short try
            self.assertEqual(calls, [20])
        finally:
            verify.sh = saved

    def test_the_runner_posts_with_the_long_limit_and_a_retry(self):
        saved = verify.sh, verify.RUNNER_HOME
        tmp = Path(tempfile.mkdtemp(prefix="verify-forge-"))
        calls = []
        try:
            verify.RUNNER_HOME = tmp
            def sh(cmd, cwd=None, env=None, timeout=None, merge=True):
                calls.append((cmd, timeout))
                if cmd[:1] == ["git"] and ("rev-parse" in cmd or "merge-base" in cmd):
                    return 0, "b" * 40  # the base branch exists
                return (124, "timed out") if cmd[:1] == ["gh"] else (1, "")  # no config on the base; posts time out
            verify.sh = sh
            args = argparse.Namespace(unsandboxed=True, allow_read=None, allow_host_port=None)
            quiet(verify.run_job, "acme/app", tmp / "mirror.git", "a" * 40, "main", "PR #1", args)
            posts = [t for cmd, t in calls if cmd[:4] == ["gh", "api", "-X", "POST"]]
            self.assertTrue(posts, calls)  # the base config is unreadable here, so the job posts `missing`
            self.assertEqual(posts, [verify.FORGE_TIMEOUT] * verify.FORGE_ATTEMPTS)
        finally:
            verify.sh, verify.RUNNER_HOME = saved
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_budget_gives_the_long_limit_only_while_it_covers_the_worst_case(self):
        now = [0.0]
        budget = verify.ForgeBudget(clock=lambda: now[0])
        seen = []

        def slow(*a):  # every call takes the full worst case on a forge that never answers
            seen.append(a)
            now[0] += verify.FORGE_TIMEOUT * verify.FORGE_ATTEMPTS if len(a) == 3 else 30
        for _ in range(6):
            budget.call(slow, "x")
        long = ("x", verify.FORGE_TIMEOUT, verify.FORGE_ATTEMPTS)
        n = verify.FORGE_BUDGET // (verify.FORGE_TIMEOUT * verify.FORGE_ATTEMPTS)
        self.assertEqual(seen, [long] * n + [("x",)] * (6 - n))
        self.assertGreaterEqual(budget.left, 0)  # the long waits never exceed the budget

    def test_a_job_on_a_forge_that_never_answers_waits_at_most_the_budget_plus_short_tries(self):
        saved = verify.sh, verify.RUNNER_HOME
        tmp = Path(tempfile.mkdtemp(prefix="verify-forge-"))
        now, waits = [0.0], []
        try:
            verify.RUNNER_HOME = tmp

            def sh(cmd, cwd=None, env=None, timeout=None, merge=True):
                if cmd[:1] == ["gh"]:
                    waits.append(timeout)
                    now[0] += timeout
                    return 124, "timed out"
                if cmd[:1] == ["git"] and ("rev-parse" in cmd or "merge-base" in cmd):
                    return 0, "b" * 40
                return 1, ""
            verify.sh = sh
            args = argparse.Namespace(unsandboxed=True, allow_read=None, allow_host_port=None)
            budget = verify.ForgeBudget(seconds=verify.FORGE_TIMEOUT * verify.FORGE_ATTEMPTS, clock=lambda: now[0])
            for _ in range(3):  # three jobs in one tick share the tick's budget
                quiet(lambda: verify.run_job("acme/app", tmp / "mirror.git", "a" * 40, "main", "PR #1", args, budget=budget))
            self.assertEqual(waits, [verify.FORGE_TIMEOUT] * verify.FORGE_ATTEMPTS + [30, 30])
        finally:
            verify.sh, verify.RUNNER_HOME = saved
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_runner_reads_statuses_with_the_long_limit_and_a_retry(self):
        tmp = Path(tempfile.mkdtemp(prefix="verify-forge-"))
        names = ("RUNNER_HOME", "ensure_mirror", "pending_jobs", "forge_status", "run_job")
        saved = {n: getattr(verify, n) for n in names}
        seen = []
        try:
            verify.RUNNER_HOME = tmp
            verify.ensure_mirror = lambda slug, url: tmp
            verify.pending_jobs = lambda slug, mirror, args: iter([("a" * 40, "main", "PR #1", False, "pr")])
            verify.forge_status = lambda slug, sha, *a: seen.append(a) or None
            args = argparse.Namespace(max_jobs=1, stale_hours=3.0, rerun=None)
            rc, out = quiet(verify.serve_repo, "acme/app", args)
            self.assertEqual(rc, 1, out)
            self.assertEqual(seen, [(verify.FORGE_TIMEOUT, verify.FORGE_ATTEMPTS)])
            budgets = []
            verify.forge_status = lambda slug, sha, *a: {}
            verify.run_job = lambda *a, budget=None, **k: budgets.append(budget) or "done"
            verify.pending_jobs = lambda slug, mirror, args: iter([("a" * 40, "main", "PR #1", False, "pr"),
                                                                   ("c" * 40, "main", "PR #2", False, "pr")])
            quiet(verify.serve_repo, "acme/app", argparse.Namespace(max_jobs=2, stale_hours=3.0, rerun=None))
            self.assertEqual(len(budgets), 2)
            self.assertIs(budgets[0], budgets[1])  # one budget for the tick's reads and every job's posts
            self.assertIsInstance(budgets[0], verify.ForgeBudget)
        finally:
            for n, v in saved.items():
                setattr(verify, n, v)
            shutil.rmtree(tmp, ignore_errors=True)


class RunnerReuse(unittest.TestCase):
    """`run --strict` takes the runner's sandboxed result for exactly this commit and runs only the rest here."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verify-reuse-")).resolve()
        self.saved = verify.RUNNER_HOME
        verify.RUNNER_HOME = self.tmp / "runner"
        cfg = {"version": 1, "stages": {"static": {"run": "true"}, "unit": {"run": "echo ran-unit-here; exit 1"},
                                        "integration": {"run": "true"}, "journeys": {"run": None, "na": "cli"},
                                        "evals": {"run": None, "na": "no LLM"}, "rehearsal": {"run": None, "na": "no data"}}}
        self.repo = make_repo({"a.txt": "x\n", ".verify/runs/kept.json": "{}\n"}, cfg)  # a tracked file there too
        git(self.repo, "remote", "add", "origin", "https://github.com/acme/app.git")
        self.sha = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True,
                                  text=True).stdout.strip()

    def tearDown(self):
        verify.RUNNER_HOME = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.repo, ignore_errors=True)

    def runner_art(self, unit="pass", **over):
        art = {"sha": self.sha, "checked": self.sha, "sandboxed": True, "strict": True, "edited": [],
               "config_edited": False, "kind": "pr", "label": "PR #1", "base": "main", "base_sha": "b" * 40,
               "at": "2026-10-08T00:00:00Z", "verdict": "not-verified",
               "stages": [{"stage": "static", "status": "pass", "detail": "exit 0 in 2s"},
                          {"stage": "unit", "status": unit, "detail": "exit 0 in 1391s"},
                          {"stage": "integration", "status": "missing", "detail": "needs an unconfined host"},
                          *({"stage": s, "status": "na", "detail": "n/a"} for s in ("journeys", "evals", "rehearsal"))]}
        art.update(over)
        for k in [k for k, v in over.items() if v is None]:
            del art[k]
        d = verify.RUNNER_HOME / "runs" / "acme__app"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{self.sha}.json").write_text(json.dumps(art))

    def run_strict(self, *extra):
        rc, out = quiet(verify.main, ["run", str(self.repo), "--strict", *extra])
        art = json.loads((self.repo / ".verify/runs" / f"{self.sha}.json").read_text())
        return rc, out, {r["stage"]: r for r in art["stages"]}, art

    def test_an_exact_sandboxed_runner_result_is_reused_and_only_the_missing_stage_runs_here(self):
        self.runner_art()
        rc, out, stages, art = self.run_strict()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("ran-unit-here", out)  # the local unit command fails; it never ran
        self.assertEqual((stages["unit"]["status"], stages["unit"]["source"]), ("pass", "runner"))
        self.assertEqual((stages["integration"]["status"], stages["integration"]["source"]), ("pass", "local"))
        self.assertEqual(art["runner"]["base_sha"], "b" * 40)
        rc, out, _, _ = self.run_strict()  # its own artifact under .verify/runs doesn't count as a dirty tree
        self.assertEqual(rc, 0, out)

    def test_anything_short_of_an_exact_clean_sandboxed_result_runs_every_stage_here(self):
        cases = {"no runner result": None, "checked merged with a newer base": {"checked": "c" * 40},
                 "not sandboxed": {"sandboxed": False}, "not strict": {"strict": False},
                 "verifier edited": {"edited": ["scripts/check.sh"]}, "config edited": {"config_edited": True},
                 "no edit record": {"edited": None}, "no config record": {"config_edited": None},
                 "malformed edit record": {"edited": "scripts/check.sh"},
                 "malformed config record": {"config_edited": "no"}, "another commit's result": {"sha": "d" * 40},
                 "runner skipped the stage": {"unit": "untouched"}, "dirty tree": {}, "untracked file": {},
                 "tracked file under .verify/runs edited": {},
                 "untracked input under .verify/runs": {}, "another commit's artifact under .verify/runs": {},
                 "edit hidden by assume-unchanged": {}, "edit hidden by skip-worktree": {},
                 "edit hidden by an fsmonitor hook": {}, "same-size edit with stat restored": {},
                 "--fresh": {}}
        hook = self.tmp / "fsmonitor.sh"
        hook.write_text('#!/bin/sh\nprintf "token\\0"\n')  # always "nothing changed"
        hook.chmod(0o755)
        for name, over in cases.items():
            with self.subTest(name):
                shutil.rmtree(verify.RUNNER_HOME, ignore_errors=True)
                for key in ("core.fsmonitor", "core.trustctime"):
                    subprocess.run(["git", "-C", str(self.repo), "config", "--unset", key], capture_output=True)
                git(self.repo, "update-index", "--no-assume-unchanged", "a.txt")
                git(self.repo, "update-index", "--no-skip-worktree", "a.txt")
                (self.repo / "a.txt").write_text("x\n")  # stat may match the index, so checkout can't restore it
                git(self.repo, "checkout", "-q", "--", ".")
                git(self.repo, "clean", "-qfd")
                if over is not None:
                    self.runner_art(**over)
                if name == "dirty tree":
                    (self.repo / "a.txt").write_text("changed\n")
                if name == "untracked file":
                    (self.repo / "new.txt").write_text("new\n")
                if name == "untracked input under .verify/runs":
                    (self.repo / ".verify/runs/input.json").write_text('{"pass": true}\n')
                if name == "another commit's artifact under .verify/runs":
                    (self.repo / ".verify/runs" / ("e" * 40 + ".json")).write_text("{}\n")
                if name == "edit hidden by assume-unchanged":
                    git(self.repo, "update-index", "--assume-unchanged", "a.txt")
                    (self.repo / "a.txt").write_text("changed\n")
                if name == "edit hidden by skip-worktree":
                    git(self.repo, "update-index", "--skip-worktree", "a.txt")
                    (self.repo / "a.txt").write_text("changed\n")
                if name == "edit hidden by an fsmonitor hook":
                    git(self.repo, "config", "core.fsmonitor", str(hook))
                    git(self.repo, "config", "core.fsmonitorHookVersion", "2")
                    git(self.repo, "status", "--porcelain")  # marks every entry fsmonitor-valid
                    (self.repo / "a.txt").write_text("changed\n")
                if name == "same-size edit with stat restored":
                    git(self.repo, "config", "core.trustctime", "false")
                    old = time.time() - 100
                    os.utime(self.repo / "a.txt", (old, old))
                    git(self.repo, "update-index", "--refresh")  # the index records that stat, and isn't racy
                    (self.repo / "a.txt").write_text("y\n")
                    os.utime(self.repo / "a.txt", (old, old))
                if name == "tracked file under .verify/runs edited":
                    (self.repo / ".verify/runs/kept.json").write_text('{"verdict": "pass"}\n')
                rc, out, stages, _ = self.run_strict(*(["--fresh"] if name == "--fresh" else []))
                self.assertEqual(rc, 1, out)
                self.assertIn("ran-unit-here", out)
                self.assertEqual(stages["unit"]["source"], "local")

    def test_a_symlink_at_the_artifact_path_refuses_reuse_and_is_replaced_not_followed(self):
        sentinel = self.tmp / "sentinel.txt"
        sentinel.write_text("sentinel\n")
        self.runner_art()
        (self.repo / ".verify/runs").mkdir(parents=True, exist_ok=True)
        (self.repo / ".verify/runs" / f"{self.sha}.json").symlink_to(sentinel)
        rc, out, stages, _ = self.run_strict()
        self.assertEqual(rc, 1, out)
        self.assertIn("is a symlink", out)
        self.assertIn("ran-unit-here", out)
        self.assertEqual(stages["unit"]["source"], "local")
        self.assertEqual(sentinel.read_text(), "sentinel\n")
        self.assertFalse((self.repo / ".verify/runs" / f"{self.sha}.json").is_symlink())
        rc, out, stages, _ = self.run_strict()  # the replaced, regular artifact is this command's own again
        self.assertEqual((rc, stages["unit"]["source"]), (0, "runner"), out)

    def test_a_tracked_symlinked_runs_dir_refuses_reuse_and_nothing_is_written_through_it(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        shutil.rmtree(self.repo / ".verify/runs")
        (self.repo / ".verify/runs").symlink_to(outside)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "runs dir is a link")  # tracked and unchanged: git status is clean
        self.sha = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True,
                                  text=True).stdout.strip()
        self.runner_art()
        rc, out = quiet(verify.main, ["run", str(self.repo), "--strict"])
        self.assertEqual(rc, 1, out)
        self.assertIn(".verify/runs is a symlink", out)
        self.assertIn("ran-unit-here", out)  # every stage ran here
        self.assertEqual(os.listdir(outside), [])  # nothing written through the link

    def test_when_git_cannot_compare_the_worktree_with_head_nothing_is_reused(self):
        self.runner_art()
        tree = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD^{tree}"], capture_output=True,
                              text=True).stdout.strip()
        (self.repo / ".git/objects" / tree[:2] / tree[2:]).unlink()  # HEAD's tree can't be read
        self.assertIsNone(verify.worktree_changes(self.repo))
        rc, out = quiet(verify.main, ["run", str(self.repo), "--strict"])
        self.assertIn("git could not compare the worktree with HEAD", out)
        self.assertIn("ran-unit-here", out)

    def test_a_reused_failure_stays_a_failure_and_says_how_to_rerun_it(self):
        self.runner_art(unit="fail")
        rc, out, stages, _ = self.run_strict()
        self.assertEqual(rc, 1, out)
        self.assertNotIn("ran-unit-here", out)
        self.assertEqual(stages["unit"]["source"], "runner")
        self.assertIn("--fresh reruns it here", out)


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

    def hook(self, repo, cmd):
        payload = json.dumps({"tool_input": {"command": cmd}, "cwd": str(repo)})
        return subprocess.run([sys.executable, str(HERE.parent / "verify.py"), "hook"], input=payload,
                              capture_output=True, text=True, timeout=30)

    def test_hook_is_silent_in_repos_without_a_contract(self):
        p = self.hook(make_repo({"README.md": "x\n"}), "vercel deploy --prod")
        self.assertEqual((p.returncode, p.stdout.strip()), (0, ""))

    def test_hook_asks_to_run_verify_after_a_deploy(self):
        repo = make_repo({"README.md": "x\n"}, config={"stages": {"unit": {"run": "true"}}})
        p = self.hook(repo, "vercel deploy --prod")
        self.assertEqual(p.returncode, 0)
        out = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PostToolUse")
        self.assertNotIn("permissionDecision", out)
        self.assertIn("run", out["additionalContext"])
        self.assertIn("--strict", out["additionalContext"])
        self.assertIn("postdeploy", out["additionalContext"])


class PinnedVerifier(unittest.TestCase):
    """A PR job runs the base branch's verifier (the config's `verifier` paths), so a PR can't make its own checks
    pass by editing them. Run with --unsandboxed so it needs no OS sandbox; RunnerIsolation covers the sandbox."""
    CHECK = ("for f in tests/*.sh; do cat scripts/suites/* | grep -qx \"$f\" && continue; "
             "sh \"$f\" || { echo \"FAILED $f\"; exit 1; }; done; echo all-ran\n")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verify-pin-")).resolve()
        self.saved = verify.RUNNER_HOME, verify.DISK_FLOOR_GB
        verify.RUNNER_HOME, verify.DISK_FLOOR_GB = self.tmp / "runner", 0
        cfg = {"version": 1, "verifier": ["scripts/check.sh", "scripts/suites"],
               "stages": {"unit": {"run": "sh scripts/check.sh"},
                          **{s: {"run": None, "na": "test"} for s in verify.PER_CHANGE if s != "unit"}}}
        self.origin = make_repo({"scripts/check.sh": self.CHECK, "scripts/suites/excluded": "none\n",
                                 "tests/widget.sh": "exit 1\n"}, cfg)
        git(self.origin, "checkout", "-q", "-b", "pr")

    def tearDown(self):
        verify.RUNNER_HOME, verify.DISK_FLOOR_GB = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.origin, ignore_errors=True)

    def run_pr(self, change, branch_job=False):
        change(self.origin)
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "--allow-empty", "-m", "pr")
        sha = subprocess.run(["git", "-C", str(self.origin), "rev-parse", "HEAD"], capture_output=True,
                             text=True).stdout.strip()
        mirror = self.tmp / f"mirror-{sha[:9]}.git"
        subprocess.run(["git", "clone", "-q", "--mirror", str(self.origin), str(mirror)], check=True)
        self.posts = []
        args = argparse.Namespace(unsandboxed=True, allow_read=None, allow_host_port=None)
        record = lambda c, s, d: self.posts.append((c, s, d)) or True  # noqa: E731
        if branch_job:  # the head of an owner-listed branch: trusted, its own config and verifier
            rc, out = quiet(verify.run_job, "acme/app", mirror, sha, None, "pr", args, record, False, "branch")
        else:
            rc, out = quiet(verify.run_job, "acme/app", mirror, sha, "main", "PR #1", args, record)
        self.assertEqual(rc, "done", out)
        return self.posts[-1], out

    def write(self, rel, text, mode=None):
        def change(repo):
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
            if mode:
                p.chmod(mode)
        return change

    def test_a_pr_that_replaces_its_verifier_with_a_no_op_still_fails(self):
        final, _ = self.run_pr(self.write("scripts/check.sh", "exit 0\n"))
        self.assertEqual((final[0], final[1]), ("verify", "fail"), final)
        self.assertIn("ran main's verifier, not this PR's edit of scripts/check.sh", final[2])

    def test_a_pr_that_excludes_its_failing_test_in_the_pinned_list_still_fails(self):
        final, _ = self.run_pr(self.write("scripts/suites/excluded", "tests/widget.sh\n"))
        self.assertEqual(final[1], "fail", final)
        self.assertIn("this PR's edit of scripts/suites", final[2])

    def test_a_file_the_pr_adds_under_a_pinned_directory_is_dropped(self):
        final, _ = self.run_pr(self.write("scripts/suites/more", "tests/widget.sh\n"))
        self.assertEqual(final[1], "fail", final)

    def test_a_symlinked_verifier_directory_is_refused_and_nothing_outside_changes(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "check.sh").write_text("outside\n")

        def change(repo):
            shutil.rmtree(repo / "scripts")
            (repo / "scripts").symlink_to(outside)
        final, _ = self.run_pr(change)
        self.assertEqual(final[1], "fail", final)
        self.assertIn("scripts is not a plain directory in this PR", final[2])
        self.assertEqual(sorted(os.listdir(outside)), ["check.sh"])
        self.assertEqual((outside / "check.sh").read_text(), "outside\n")

    def test_a_verifier_path_missing_on_the_base_branch_fails_closed(self):
        git(self.origin, "checkout", "-q", "main")
        cfg = json.loads((self.origin / ".verify/config.json").read_text())
        cfg["verifier"].append("scripts/not-there.sh")
        (self.origin / ".verify/config.json").write_text(json.dumps(cfg))
        git(self.origin, "commit", "-qam", "names a missing verifier path")
        git(self.origin, "checkout", "-q", "pr")
        git(self.origin, "merge", "-q", "main")
        final, _ = self.run_pr(self.write("tests/widget.sh", "exit 0\n"))
        self.assertEqual(final, ("verify", "fail", "verifier path scripts/not-there.sh is not on the base branch"))

    def on_main_after_the_pr_branched(self, files, message):
        git(self.origin, "checkout", "-q", "main")
        for rel, text in files.items():
            self.write(rel, text)(self.origin)
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", message)
        git(self.origin, "checkout", "-q", "pr")

    def test_a_pr_that_predates_a_new_suite_on_main_is_checked_merged_and_not_blamed_for_main_s_edits(self):
        # main's verifier now refuses a listed suite that isn't in the tree, and lists one the PR's branch lacks
        strict = "for f in $(cat scripts/suites/*); do [ \"$f\" = none ] || [ -f \"$f\" ] || { echo \"listed, missing: $f\"; exit 1; }; done\n"
        cfg = json.loads((self.origin / ".verify/config.json").read_text())
        cfg["timeout"] = 900
        self.on_main_after_the_pr_branched({"scripts/check.sh": strict + self.CHECK, "tests/native.sh": "exit 0\n",
                                            "scripts/suites/native": "tests/native.sh\n",
                                            ".verify/config.json": json.dumps(cfg)}, "adds a native suite")
        final, out = self.run_pr(self.write("tests/widget.sh", "exit 0\n"))
        self.assertEqual(final[1], "missing", final)  # --unsandboxed caps the pass
        self.assertIn("unit=pass", final[2])
        self.assertNotIn("listed, missing", out)
        self.assertNotIn("PR's edit", final[2])  # main changed check.sh, suites and config; the PR changed none

    def test_a_pr_that_edits_the_verifier_after_main_moved_is_still_named(self):
        self.on_main_after_the_pr_branched({"tests/other.sh": "exit 0\n"}, "unrelated main change")
        final, _ = self.run_pr(self.write("scripts/check.sh", "exit 0\n"))
        self.assertEqual(final[1], "fail", final)
        self.assertIn("ran main's verifier, not this PR's edit of scripts/check.sh", final[2])

    def test_a_pr_that_conflicts_with_main_is_reported_missing_and_runs_nothing(self):
        self.on_main_after_the_pr_branched({"tests/widget.sh": "exit 2\n"}, "main edits the same line")
        final, _ = self.run_pr(self.write("tests/widget.sh", "exit 0\n"))
        self.assertEqual(final[:2], ("verify", "missing"), final)
        self.assertIn("conflicts with main at", final[2])
        self.assertEqual(len(self.posts), 1, self.posts)  # no stage ran

    def test_a_pr_s_gitattributes_cannot_run_a_merge_driver_or_filter_the_host_defines(self):
        ran = self.tmp / "ran"
        ran.mkdir()
        host = self.tmp / "host.gitconfig"
        host.write_text(f'[merge "probe"]\n\tdriver = touch {ran}/merge-driver\n'
                        f'[filter "probe"]\n\tsmudge = touch {ran}/smudge-filter; cat\n')
        git(self.origin, "checkout", "-q", "main")
        self.write("shared.txt", "one\ntwo\nthree\n")(self.origin)
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", "shared file")
        git(self.origin, "checkout", "-q", "-B", "pr")
        self.on_main_after_the_pr_branched({"shared.txt": "ONE\ntwo\nthree\n"}, "main edits line 1")

        def change(repo):  # both sides edit shared.txt, so the merge needs a content merge: the driver's moment
            self.write("shared.txt", "one\ntwo\nTHREE\n")(repo)
            self.write(".gitattributes", "*.txt merge=probe filter=probe\n")(repo)
            self.write("tests/widget.sh", "exit 0\n")(repo)
        saved = os.environ.get("GIT_CONFIG_GLOBAL")
        os.environ["GIT_CONFIG_GLOBAL"] = str(host)  # the host's own git config defines the drivers
        try:
            final, _ = self.run_pr(change)
        finally:
            os.environ.pop("GIT_CONFIG_GLOBAL") if saved is None else os.environ.update(GIT_CONFIG_GLOBAL=saved)
        self.assertEqual(sorted(os.listdir(ran)), [])
        self.assertIn("unit=pass", final[2])  # the job did check out, merge and run

    def test_git_in_a_pr_stage_sees_no_host_git_config(self):
        host = self.tmp / "host.gitconfig"
        host.write_text(f'[core]\n\thooksPath = {self.tmp}/host-hooks\n[filter "probe"]\n\tsmudge = cat\n')
        probe = ('out=$(git config --list --show-origin --includes 2>&1); '
                 '[ -z "$out" ] || { echo "host git config: $out"; exit 1; }\n')
        saved = os.environ.get("GIT_CONFIG_GLOBAL")
        os.environ["GIT_CONFIG_GLOBAL"] = str(host)  # outside any repo, so only global and system config can show
        try:
            final, out = self.run_pr(self.write("tests/widget.sh", "cd \"$TMPDIR\" && " + probe))
        finally:
            os.environ.pop("GIT_CONFIG_GLOBAL") if saved is None else os.environ.update(GIT_CONFIG_GLOBAL=saved)
        self.assertNotIn("host git config", out)
        self.assertIn("unit=pass", final[2])

    def test_the_runner_artifact_records_verifier_and_config_edits_for_reuse(self):
        def runner_art():
            sha = subprocess.run(["git", "-C", str(self.origin), "rev-parse", "HEAD"], capture_output=True,
                                 text=True).stdout.strip()
            return json.loads((verify.RUNNER_HOME / "runs" / "acme__app" / f"{sha}.json").read_text())
        self.run_pr(self.write("tests/widget.sh", "exit 0\n"))
        art = runner_art()
        self.assertEqual((art["edited"], art["config_edited"], art["checked"] == art["sha"]), ([], False, True))
        self.run_pr(self.write("scripts/check.sh", "exit 0\n"))
        self.assertEqual(runner_art()["edited"], ["scripts/check.sh"])

        def edit_config(repo):
            cfg = json.loads((repo / ".verify/config.json").read_text())
            cfg["timeout"] = 600
            (repo / ".verify/config.json").write_text(json.dumps(cfg))
        self.run_pr(edit_config)
        self.assertTrue(runner_art()["config_edited"])

    def test_bad_verifier_paths_in_the_base_config_fail_closed(self):
        for bad in (["../x"], ["/etc/passwd"], [".git/config"], ["a//b"], "scripts", [3]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    verify.verifier_paths({"verifier": bad})

    def test_a_pr_that_fixes_the_test_passes_its_stages_but_unsandboxed_never_reports_pass(self):
        final, _ = self.run_pr(self.write("tests/widget.sh", "exit 0\n"))
        self.assertEqual(final[1], "missing", final)  # --unsandboxed: a PR job's pass is not trusted
        self.assertIn("unit=pass", final[2])
        self.assertIn(verify.UNSANDBOXED_PR, final[2])
        self.assertNotIn("PR's edit", final[2])

    def test_an_unsandboxed_pr_job_that_rewrites_a_pinned_helper_between_stages_posts_no_pass(self):
        # A later stage runs pinned scripts/native.sh (exit 1 on main). The PR's unit-stage test rewrites it to
        # exit 0; with no sandbox nothing stops the write, so integration really passes. No status may be green.
        git(self.origin, "checkout", "-q", "main")
        (self.origin / "scripts/native.sh").write_text("exit 1\n")
        cfg = json.loads((self.origin / ".verify/config.json").read_text())
        cfg["verifier"].append("scripts/native.sh")
        cfg["stages"]["integration"] = {"run": "sh scripts/native.sh"}
        (self.origin / ".verify/config.json").write_text(json.dumps(cfg))
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-qm", "integration runs a pinned helper")
        git(self.origin, "checkout", "-q", "pr")
        git(self.origin, "merge", "-q", "main")

        def change(repo):
            (repo / "tests/widget.sh").write_text("exit 0\n")
            (repo / "tests/zz-rewrite.sh").write_text("printf 'exit 0\\n' > scripts/native.sh\n")
        final, _ = self.run_pr(change)
        green = [p for p in self.posts if verify.GH_STATE.get(p[1]) == "success"]
        self.assertEqual(green, [], self.posts)
        integration = [p for p in self.posts if p[0] == "verify/integration" and p[1] != "pending"]
        self.assertTrue(integration[-1][2].startswith("pass, not trusted"), integration)  # the attack worked
        self.assertEqual(final[1], "missing", final)
        self.assertIn(verify.UNSANDBOXED_PR, final[2])

    def test_an_unsandboxed_branch_job_still_reports_pass(self):
        # control: the cap is for PR jobs only; the head of an owner-listed branch runs its own trusted verifier
        final, _ = self.run_pr(self.write("tests/widget.sh", "exit 0\n"), branch_job=True)
        self.assertEqual(final[1], "pass", final)
        self.assertNotIn(verify.UNSANDBOXED_PR, final[2])
        self.assertIn(("verify/unit", "pass", "exit 0"), [(c, s, d.split(" in ")[0]) for c, s, d in self.posts])

    def test_a_pinned_helper_keeps_the_base_mode(self):
        final, _ = self.run_pr(self.write("scripts/check.sh", "exit 0\n", 0o755))
        self.assertEqual(final[1], "fail", final)


class UnconfinedStage(unittest.TestCase):
    def test_an_unconfined_stage_is_missing_in_the_sandbox_and_runs_locally(self):
        spec = {"run": "true", "unconfined": "applies its own sandbox"}
        r = verify.run_stage(".", "integration", spec, True, None, dict(os.environ), wrap=["/usr/bin/env"])
        self.assertEqual(r["status"], "missing")
        self.assertIn("needs an unconfined host", r["detail"])
        self.assertEqual(verify.run_stage(".", "integration", spec, True, None, dict(os.environ))["status"], "pass")
        self.assertEqual(verify.run_stage(".", "integration", spec, True, None, dict(os.environ), wrap=[])["status"],
                         "pass")  # --unsandboxed: the host accepted


if __name__ == "__main__":
    unittest.main()
