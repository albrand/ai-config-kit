#!/usr/bin/env python3
"""Offline unit tests for orca-automation-workspace-cleanup.py.

No network, no real Orca, no real worktree deletion, no real sleep. All Orca
interaction is isolated behind an injectable fake runner; Popen and sleep are
injected fakes. No workspace is ever really removed.
"""
from __future__ import annotations

import ast
import inspect
import io
import json
import os
import subprocess
import sys
import unittest
import importlib.util
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MODULE_PATH = (SCRIPT_DIR.parent / "codex" / "orca-workflow-automation" / "scripts"
               / "orca-automation-workspace-cleanup.py")
_spec = importlib.util.spec_from_file_location("orca_automation_workspace_cleanup", MODULE_PATH)
c = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(c)  # type: ignore

REPO_PATH = "/repos/acme/widgets"
REPO_ID = "repo-1"
NAME = "orca-pr-listener-acme-widgets-me"
WT_ID = f"{REPO_ID}::/ws/wt-full-1"


def repo_record(**over):
    base = {
        "id": REPO_ID,
        "name": "acme/widgets",
        "path": REPO_PATH,
        "gitRemoteIdentity": {"canonicalKey": "github.com/acme/widgets"},
    }
    base.update(over)
    return base


def automation_record(name=NAME, github_repo="acme/widgets", reviewer="me",
                      repo_id=REPO_ID, **over):
    auto = {
        "id": "auto-1",
        "name": name,
        "prompt": c.marker(github_repo, reviewer),
        "projectId": repo_id,
        "enabled": True,
    }
    auto.update(over)
    return auto


def worktree_record(wid=WT_ID, repo_id=REPO_ID, is_main=False, path="/ws/wt-full-1", **over):
    wt = {
        "id": wid,
        "repoId": repo_id,
        "isMainWorktree": is_main,
        "path": path,
    }
    wt.update(over)
    return wt


def run_record(automation_id="auto-1", workspace_id=WT_ID, status="completed",
               snapshot=None, **over):
    if snapshot is None:
        snapshot = {"format": "plain_text", "content": "persisted output body"}
    run = {
        "automationId": automation_id,
        "workspaceId": workspace_id,
        "status": status,
        "outputSnapshot": snapshot,
    }
    run.update(over)
    return run


class FakeOrca:
    """Stateful fake Orca CLI. Records every argv; serves canned JSON."""

    def __init__(self, *, repos=None, automations=None, current=None,
                 worktrees=None, runs=None):
        self.repos = repos if repos is not None else [repo_record()]
        self.automations = automations if automations is not None else [automation_record()]
        self.current = current if current is not None else worktree_record()
        self.worktrees = worktrees if worktrees is not None else [worktree_record()]
        self.runs = runs if runs is not None else []
        self.all_calls: list[list[str]] = []
        self.rm_calls: list[list[str]] = []

    def __call__(self, args):
        self.all_calls.append(list(args))
        if args[:3] == ["repo", "list", "--json"]:
            return json.dumps({"ok": True, "result": {"repos": self.repos}})
        if args[:3] == ["automations", "list", "--json"]:
            return json.dumps({"ok": True, "result": {"automations": self.automations}})
        if args[:3] == ["worktree", "current", "--json"]:
            return json.dumps({"ok": True, "result": {"worktree": self.current}})
        if args[:2] == ["worktree", "show"]:
            selector = args[args.index("--worktree") + 1]
            wid = selector.removeprefix("id:")
            found = next((w for w in self.worktrees if w.get("id") == wid), {})
            return json.dumps({"ok": True, "result": {"worktree": found}})
        if args[:3] == ["automations", "runs", "--id"] and args[-1] == "--json":
            return json.dumps({"ok": True, "result": {"runs": self.runs}})
        if args[:2] == ["worktree", "rm"]:
            self.rm_calls.append(list(args))
            return json.dumps({"ok": True, "removed": args})
        raise AssertionError(f"unexpected orca args: {args}")


class FakePopen:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), "kwargs": kwargs})
        return self  # act as the proc object too

    @property
    def pid(self):
        return 4242


def capture(callback):
    buf = io.StringIO()
    orig = sys.stdout
    sys.stdout = buf
    try:
        rc = callback()
    finally:
        sys.stdout = orig
    return rc, buf.getvalue()


# --------------------------------------------------------------------------- #
class JsonWrapperTest(unittest.TestCase):
    def test_fetch_runs_envelope_and_bare_list(self):
        def runner(args):
            if args == ["automations", "runs", "--id", "a", "--json"]:
                return json.dumps({"result": {"runs": [{"automationId": "a"}]}})
            raise AssertionError(args)
        self.assertEqual(c.fetch_automation_runs(runner, "a"), [{"automationId": "a"}])

        def runner2(args):
            if args == ["automations", "runs", "--id", "b", "--json"]:
                return json.dumps([{"automationId": "b"}])
            raise AssertionError(args)
        self.assertEqual(c.fetch_automation_runs(runner2, "b"), [{"automationId": "b"}])

    def test_fetch_worktrees_envelope(self):
        def runner(args):
            if args == ["worktree", "show", "--worktree", "id:x", "--json"]:
                return json.dumps({"result": {"worktree": {"id": "x"}}})
            raise AssertionError(args)
        self.assertEqual(c.fetch_worktree_by_id(runner, "x"), {"id": "x"})

    def test_current_worktree_unwraps_result(self):
        def runner(args):
            if args[:3] == ["worktree", "current", "--json"]:
                return json.dumps({"result": {"worktree": {
                    "id": "r::/tmp/z", "repoId": "r", "isMainWorktree": False
                }}})
            raise AssertionError(args)
        wt = c.fetch_current_worktree(runner)
        self.assertEqual(wt["id"], "r::/tmp/z")

    def test_non_json_rejected(self):
        with self.assertRaises(c.CleanupError):
            c.fetch_automations(lambda a: "not-json")


# --------------------------------------------------------------------------- #
class ExactAutomationMatchTest(unittest.TestCase):
    def test_matches_exact_name_marker_repo(self):
        auto = c.find_exact_automation(
            [automation_record()], NAME, "acme/widgets", "me", REPO_ID
        )
        self.assertEqual(auto["id"], "auto-1")

    def test_accepts_run_context_repo_shape(self):
        seed = automation_record(projectId=None,
                                 runContext={"repoId": REPO_ID})
        auto = c.find_exact_automation([seed], NAME, "acme/widgets", "me", REPO_ID)
        self.assertEqual(auto["id"], "auto-1")

    def test_missing_name_rejected(self):
        with self.assertRaises(c.CleanupError):
            c.find_exact_automation([], NAME, "acme/widgets", "me", REPO_ID)

    def test_multiple_same_name_rejected(self):
        with self.assertRaises(c.CleanupError):
            c.find_exact_automation(
                [automation_record(id="a"), automation_record(id="b")],
                NAME, "acme/widgets", "me", REPO_ID,
            )

    def test_marker_mismatch_rejected(self):
        seed = automation_record(prompt=c.marker("acme/other", "me"))
        with self.assertRaises(c.CleanupError):
            c.find_exact_automation([seed], NAME, "acme/widgets", "me", REPO_ID)

    def test_repo_id_mismatch_rejected(self):
        seed = automation_record(projectId="repo-other")
        with self.assertRaises(c.CleanupError):
            c.find_exact_automation([seed], NAME, "acme/widgets", "me", REPO_ID)

    def test_no_id_rejected(self):
        seed = automation_record(id="")
        with self.assertRaises(c.CleanupError):
            c.find_exact_automation([seed], NAME, "acme/widgets", "me", REPO_ID)


# --------------------------------------------------------------------------- #
class CompletedRunGateTest(unittest.TestCase):
    def test_matches_completed_nonempty_snapshot(self):
        run = run_record()
        self.assertIs(
            c.match_completed_run([run], "auto-1", WT_ID), run
        )

    def test_wrong_workspace_id_rejected(self):
        run = run_record(workspace_id="other-wt")
        self.assertIsNone(c.match_completed_run([run], "auto-1", WT_ID))

    def test_wrong_automation_id_rejected(self):
        run = run_record(automation_id="auto-9")
        self.assertIsNone(c.match_completed_run([run], "auto-1", WT_ID))

    def test_non_completed_status_rejected(self):
        for status in ("running", "failed", "blocked", "partial", "skipped"):
            self.assertIsNone(
                c.match_completed_run([run_record(status=status)], "auto-1", WT_ID),
                msg=status,
            )

    def test_empty_string_snapshot_rejected(self):
        self.assertIsNone(
            c.match_completed_run([run_record(snapshot="")], "auto-1", WT_ID)
        )

    def test_empty_dict_snapshot_rejected(self):
        self.assertIsNone(
            c.match_completed_run([run_record(snapshot={})], "auto-1", WT_ID)
        )

    def test_missing_snapshot_rejected(self):
        run = run_record()
        del run["outputSnapshot"]
        self.assertIsNone(c.match_completed_run([run], "auto-1", WT_ID))

    def test_nonempty_dict_snapshot_accepted(self):
        run = run_record(snapshot={"format": "plain_text", "content": "x"})
        self.assertEqual(c.match_completed_run([run], "auto-1", WT_ID), run)

    def test_snapshot_metadata_without_content_rejected(self):
        run = run_record(snapshot={"format": "plain_text", "content": "  "})
        self.assertIsNone(c.match_completed_run([run], "auto-1", WT_ID))

    def test_nested_automation_id_shape(self):
        run = {"automation": {"id": "auto-1"}, "workspaceId": WT_ID,
               "status": "completed", "outputSnapshot": "y"}
        self.assertEqual(
            c.match_completed_run([run], "auto-1", WT_ID), run
        )


# --------------------------------------------------------------------------- #
class RemovalGateTest(unittest.TestCase):
    def test_none_preserved(self):
        self.assertFalse(c.worktree_safe_for_removal(None, WT_ID, REPO_ID))

    def test_id_inequality_preserved(self):
        wt = worktree_record(wid="different")
        self.assertFalse(c.worktree_safe_for_removal(wt, WT_ID, REPO_ID))

    def test_repo_mismatch_preserved(self):
        wt = worktree_record(repo_id="repo-other")
        self.assertFalse(c.worktree_safe_for_removal(wt, WT_ID, REPO_ID))

    def test_main_worktree_preserved(self):
        wt = worktree_record(is_main=True)
        self.assertFalse(c.worktree_safe_for_removal(wt, WT_ID, REPO_ID))

    def test_exact_match_safe(self):
        self.assertTrue(c.worktree_safe_for_removal(worktree_record(), WT_ID, REPO_ID))


# --------------------------------------------------------------------------- #
class RmArgvTest(unittest.TestCase):
    def test_exact_rm_argv(self):
        self.assertEqual(
            c.build_rm_argv(WT_ID),
            ["worktree", "rm", "--worktree", f"id:{WT_ID}", "--force", "--json"],
        )

    def test_no_shell_metacharacters(self):
        argv = c.build_rm_argv("safe-id-1")
        self.assertNotIn(";", " ".join(argv))
        self.assertNotIn("|", " ".join(argv))


# --------------------------------------------------------------------------- #
class WatchArmTest(unittest.TestCase):
    def _arm_kwargs(self, **over):
        kw = dict(
            automation_name=NAME, github_repo="acme/widgets", reviewer="me",
            repo_id=REPO_ID, worktree_id=WT_ID, watch_timeout=60, poll_interval=1,
        )
        kw.update(over)
        return kw

    def test_removes_after_completed_persisted_run(self):
        sleeps = []
        orca = FakeOrca(runs=[run_record(snapshot="persisted")])
        rc = c.run_watch_arm(runner=orca, sleep=lambda s: sleeps.append(s),
                             **self._arm_kwargs())
        self.assertEqual(rc, 0)
        self.assertEqual(len(orca.rm_calls), 1)
        self.assertEqual(orca.rm_calls[0], c.build_rm_argv(WT_ID))
        self.assertEqual(sleeps, [])  # removed on first poll, no sleep needed

    def test_timeout_preserves_when_no_match(self):
        sleeps = []
        orca = FakeOrca(runs=[run_record(workspace_id="other")])  # never matches
        rc = c.run_watch_arm(runner=orca, sleep=lambda s: sleeps.append(s),
                             **self._arm_kwargs(watch_timeout=0))
        self.assertEqual(rc, 75)
        self.assertEqual(orca.rm_calls, [])

    def test_completed_but_empty_snapshot_preserves(self):
        orca = FakeOrca(runs=[run_record(snapshot="")])
        rc = c.run_watch_arm(runner=orca, sleep=lambda s: None,
                             **self._arm_kwargs(watch_timeout=0))
        self.assertEqual(rc, 75)
        self.assertEqual(orca.rm_calls, [])

    def test_non_completed_status_preserves(self):
        orca = FakeOrca(runs=[run_record(status="running", snapshot="x")])
        rc = c.run_watch_arm(runner=orca, sleep=lambda s: None,
                             **self._arm_kwargs(watch_timeout=0))
        self.assertEqual(rc, 75)
        self.assertEqual(orca.rm_calls, [])

    def test_marker_mismatch_preserves(self):
        orca = FakeOrca(automations=[automation_record(prompt=c.marker("acme/other", "me"))])
        rc = c.run_watch_arm(runner=orca, sleep=lambda s: None, **self._arm_kwargs())
        self.assertEqual(rc, 2)
        self.assertEqual(orca.rm_calls, [])

    def test_removal_when_worktree_becomes_main_preserves(self):
        orca = FakeOrca(
            runs=[run_record(snapshot="x")],
            worktrees=[worktree_record(is_main=True)],
        )
        rc = c.run_watch_arm(runner=orca, sleep=lambda s: None, **self._arm_kwargs())
        self.assertEqual(rc, 2)
        self.assertEqual(orca.rm_calls, [])

    def test_removal_when_worktree_id_drifts_preserves(self):
        orca = FakeOrca(
            runs=[run_record(snapshot="x")],
            worktrees=[worktree_record(wid="different")],
        )
        rc = c.run_watch_arm(runner=orca, sleep=lambda s: None, **self._arm_kwargs())
        self.assertEqual(rc, 2)
        self.assertEqual(orca.rm_calls, [])

    def test_removal_when_worktree_gone_preserves(self):
        orca = FakeOrca(runs=[run_record(snapshot="x")], worktrees=[])
        rc = c.run_watch_arm(runner=orca, sleep=lambda s: None, **self._arm_kwargs())
        self.assertEqual(rc, 2)
        self.assertEqual(orca.rm_calls, [])

    def test_removal_when_repo_id_drifts_preserves(self):
        orca = FakeOrca(
            runs=[run_record(snapshot="x")],
            worktrees=[worktree_record(repo_id="repo-other")],
        )
        rc = c.run_watch_arm(runner=orca, sleep=lambda s: None, **self._arm_kwargs())
        self.assertEqual(rc, 2)
        self.assertEqual(orca.rm_calls, [])

    def test_orca_subprocess_failure_preserves(self):
        def runner(args):
            if args[:3] == ["automations", "runs", "--id"]:
                raise subprocess.CalledProcessError(1, ["orca"])
            if args[:3] == ["automations", "list", "--json"]:
                return json.dumps({"result": {"automations": [automation_record()]}})
            raise AssertionError(args)
        rc = c.run_watch_arm(runner=runner, sleep=lambda s: None, **self._arm_kwargs())
        self.assertEqual(rc, 1)


# --------------------------------------------------------------------------- #
class SpawnAndCwdTest(unittest.TestCase):
    def test_spawn_watcher_detached_argv_and_options(self):
        captured = {}

        def popen(argv, **kwargs):
            captured["argv"] = list(argv)
            captured["kwargs"] = kwargs
            return FakePopen()

        argv = ["python3", "/x/script.py", "--watch-arm"]
        c.spawn_watcher(argv, Path("/outside"), popen)
        self.assertEqual(captured["argv"], argv)
        self.assertTrue(captured["kwargs"]["start_new_session"])
        self.assertEqual(captured["kwargs"]["stdin"], subprocess.DEVNULL)
        self.assertEqual(captured["kwargs"]["stdout"], subprocess.DEVNULL)
        self.assertEqual(captured["kwargs"]["stderr"], subprocess.DEVNULL)
        self.assertTrue(captured["kwargs"]["close_fds"])
        self.assertEqual(captured["kwargs"]["cwd"], "/outside")

    def test_choose_watcher_cwd_outside_returns_home(self):
        self.assertEqual(c.choose_watcher_cwd("/some/other/workspace"),
                         Path(os.path.expanduser("~")))

    def test_choose_watcher_cwd_when_home_inside_worktree_avoids_it(self):
        home = Path(os.path.expanduser("~"))
        self.assertEqual(c.choose_watcher_cwd(str(home)), Path(os.sep))

    def test_watch_arm_argv_exact_shape(self):
        argv = c.build_watch_arm_argv(
            Path("/abs/orca-automation-workspace-cleanup.py"),
            automation_name=NAME, github_repo="acme/widgets", reviewer="me",
            repo_id=REPO_ID, worktree_id=WT_ID, watch_timeout=90, poll_interval=5,
        )
        self.assertEqual(argv[0], sys.executable)
        self.assertTrue(argv[1].endswith("orca-automation-workspace-cleanup.py"))
        self.assertEqual(argv[2], "--watch-arm")
        self.assertIn("--automation-name", argv)
        self.assertEqual(argv[argv.index("--automation-name") + 1], NAME)
        self.assertEqual(argv[argv.index("--repo-id") + 1], REPO_ID)
        self.assertEqual(argv[argv.index("--worktree-id") + 1], WT_ID)
        self.assertEqual(argv[argv.index("--watch-timeout") + 1], "90")
        self.assertEqual(argv[argv.index("--poll-interval") + 1], "5")


# --------------------------------------------------------------------------- #
class CmdWatchTest(unittest.TestCase):
    def _argv(self, **over):
        argv = [
            "--automation-name", NAME,
            "--github-repo", "acme/widgets",
            "--reviewer", "me",
            "--orca-repo", f"id:{REPO_ID}",
            "watch",
        ]
        # mutate via known flags
        for k, v in over.items():
            flag = "--" + k.replace("_", "-")
            if flag in argv:
                argv[argv.index(flag) + 1] = v
            else:
                argv.insert(-1, flag)
                argv.insert(-1, str(v))
        return argv

    def test_watch_spawns_watcher_and_emits_json(self):
        orca = FakeOrca()
        popen = FakePopen()
        rc, out = capture(lambda: c.main(self._argv(), runner=orca, popen=popen,
                                         sleep=lambda s: None))
        self.assertEqual(rc, 0)
        self.assertEqual(len(popen.calls), 1)
        call = popen.calls[0]
        kwargs = call["kwargs"]
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertTrue(kwargs["close_fds"])
        # argv is the detached watch arm
        wargv = call["argv"]
        self.assertEqual(wargv[0], sys.executable)
        self.assertIn("--watch-arm", wargv)
        self.assertEqual(wargv[wargv.index("--worktree-id") + 1], WT_ID)
        self.assertEqual(wargv[wargv.index("--repo-id") + 1], REPO_ID)
        # cwd is outside the workspace path
        self.assertNotEqual(kwargs["cwd"], "/ws/wt-full-1")
        payload = json.loads(out)
        self.assertTrue(payload["armed"])
        self.assertNotIn("worktree_id", payload)
        self.assertNotIn("automation_id", payload)
        self.assertNotIn("watcher_argv", payload)

    def test_watch_rejects_wrong_repo_id_selector(self):
        orca = FakeOrca()
        rc, _ = capture(lambda: c.main([
            "--automation-name", NAME, "--github-repo", "acme/widgets",
            "--reviewer", "me", "--orca-repo", "id:nope", "watch",
        ], runner=orca, popen=FakePopen(), sleep=lambda s: None))
        self.assertEqual(rc, 2)

    def test_watch_rejects_nondeterministic_name(self):
        orca = FakeOrca()
        rc, _ = capture(lambda: c.main([
            "--automation-name", "not-the-deterministic-name",
            "--github-repo", "acme/widgets", "--reviewer", "me",
            "--orca-repo", f"id:{REPO_ID}", "watch",
        ], runner=orca, popen=FakePopen(), sleep=lambda s: None))
        self.assertEqual(rc, 2)

    def test_watch_preserves_when_current_is_main_worktree(self):
        orca = FakeOrca(current=worktree_record(is_main=True))
        popen = FakePopen()
        rc, _ = capture(lambda: c.main(self._argv(), runner=orca, popen=popen,
                                       sleep=lambda s: None))
        self.assertEqual(rc, 2)
        self.assertEqual(popen.calls, [])  # never spawned

    def test_watch_preserves_when_repo_id_mismatch_on_worktree(self):
        orca = FakeOrca(current=worktree_record(repo_id="repo-other"))
        popen = FakePopen()
        rc, _ = capture(lambda: c.main(self._argv(), runner=orca, popen=popen,
                                       sleep=lambda s: None))
        self.assertEqual(rc, 2)
        self.assertEqual(popen.calls, [])

    def test_watch_repo_id_override_resolves(self):
        orca = FakeOrca()
        rc, out = capture(lambda: c.main([
            "--automation-name", NAME, "--github-repo", "acme/widgets",
            "--reviewer", "me", "--repo-id", REPO_ID, "watch",
        ], runner=orca, popen=FakePopen(), sleep=lambda s: None))
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(out)["armed"])

    def test_internal_arm_rejects_non_full_worktree_id(self):
        orca = FakeOrca(runs=[run_record()])
        rc = c.run_watch_arm(
            runner=orca,
            sleep=lambda _: None,
            automation_name=NAME,
            github_repo="acme/widgets",
            reviewer="me",
            repo_id=REPO_ID,
            worktree_id="not-a-full-id",
            watch_timeout=0,
            poll_interval=1,
        )
        self.assertEqual(rc, 2)
        self.assertEqual(orca.rm_calls, [])

    def test_watch_repo_id_and_selector_mutually_exclusive(self):
        orca = FakeOrca()
        with self.assertRaises(SystemExit):
            c.main([
                "--automation-name", NAME, "--github-repo", "acme/widgets",
                "--reviewer", "me", "--repo-id", REPO_ID,
                "--orca-repo", f"id:{REPO_ID}", "watch",
            ], runner=orca, popen=FakePopen(), sleep=lambda s: None)


# --------------------------------------------------------------------------- #
class WatchArmDispatchTest(unittest.TestCase):
    def test_watch_arm_dispatches_and_removes(self):
        orca = FakeOrca(runs=[run_record(snapshot="persisted")])
        rc = c.main(
            ["--watch-arm",
             "--automation-name", NAME, "--github-repo", "acme/widgets",
             "--reviewer", "me", "--repo-id", REPO_ID, "--worktree-id", WT_ID,
             "--watch-timeout", "10", "--poll-interval", "1"],
            runner=orca, popen=FakePopen(), sleep=lambda s: None,
        )
        self.assertEqual(rc, 0)
        self.assertEqual(len(orca.rm_calls), 1)


# --------------------------------------------------------------------------- #
class SourceSafetyTest(unittest.TestCase):
    def test_no_shell_true_in_source(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                self.assertFalse(
                    any(kw.arg == "shell" for kw in node.keywords),
                    "shell= keyword must never appear",
                )

    def test_default_runner_uses_argv_list(self):
        src = inspect.getsource(c.default_orca_runner)
        self.assertIn('["orca"', src)

    def test_spawn_watcher_uses_argv_not_shell(self):
        src = inspect.getsource(c.spawn_watcher)
        self.assertNotIn("shell=True", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
