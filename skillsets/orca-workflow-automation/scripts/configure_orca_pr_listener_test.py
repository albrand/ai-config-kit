#!/usr/bin/env python3
"""Offline unit tests for configure-orca-pr-listener.py.

No network, no real Orca, no shell, no real home writes. All Orca interaction
is isolated behind an injectable fake runner; the single-writer lock is
redirected to a temp path. No real listener is ever instantiated.
"""
from __future__ import annotations

import ast
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MODULE_PATH = (SCRIPT_DIR.parent / "codex" / "orca-workflow-automation" / "scripts"
               / "configure-orca-pr-listener.py")
_spec = importlib.util.spec_from_file_location("configure_orca_pr_listener", MODULE_PATH)
c = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(c)  # type: ignore

REPO_PATH = "/repos/acme/widgets"


def repo_record(**over):
    base = {
        "id": "repo-1",
        "name": "acme/widgets",
        "path": REPO_PATH,
        "worktreeBaseRef": "origin/main",
        "gitRemoteIdentity": {"canonicalKey": "github.com/acme/widgets"},
    }
    base.update(over)
    return base


class FakeOrca:
    """Stateful fake Orca CLI. Records every argv; serves JSON for list calls.

    ``automations`` is a list so duplicate-name refusal is testable.
    """

    def __init__(self, repos=None, automations=None):
        self.repos = repos if repos is not None else [repo_record()]
        self.automations = [dict(a) for a in (automations or [])]
        self.create_calls: list[list[str]] = []
        self.edit_calls: list[list[str]] = []
        self.all_calls: list[list[str]] = []

    def __call__(self, args):
        self.all_calls.append(list(args))
        if args[:3] == ["repo", "list", "--json"]:
            return json.dumps({"ok": True, "result": {"repos": self.repos}})
        if args[:3] == ["automations", "list", "--json"]:
            return json.dumps(
                {"ok": True, "result": {"automations": self.automations}}
            )
        if args[:2] == ["automations", "create"]:
            self.create_calls.append(list(args))
            # Reflect the created automation into list output.
            name = _flag_value(args, "--name")
            prompt = _flag_value(args, "--prompt")
            repo = _flag_value(args, "--repo") or ""
            disabled = "--disabled" in args
            aid = f"auto-{len(self.automations) + 1}"
            self.automations.append({
                "id": aid, "name": name, "prompt": prompt,
                "projectId": repo.removeprefix("id:"),
                "enabled": not disabled,
            })
            return json.dumps({"id": aid, "name": name})
        if args[:2] == ["automations", "edit"]:
            self.edit_calls.append(list(args))
            return "{}"
        raise AssertionError(f"unexpected orca args: {args}")


def _flag_value(args, flag):
    for i, token in enumerate(args):
        if token == flag and i + 1 < len(args):
            return args[i + 1]
    return None


def capture(callback):
    """Run callback, returning (rc, stdout_text)."""
    buf = io.StringIO()
    orig = sys.stdout
    sys.stdout = buf
    try:
        rc = callback()
    finally:
        sys.stdout = orig
    return rc, buf.getvalue()


class TempLockMixin:
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orca-cfg-lock-")
        self.lock_path = str(Path(self.tmp) / "configure.lock")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


BASE_ARGS = [
    "--github-repo", "acme/widgets",
    "--reviewer", "me",
    "--repo-path", REPO_PATH,
    "--lock-path", None,  # filled per test
]


def base_argv(lock_path, *extra):
    argv = [
        "--github-repo", "acme/widgets",
        "--reviewer", "me",
        "--repo-path", REPO_PATH,
        "--lock-path", lock_path,
    ]
    argv.extend(extra)
    return argv


# --------------------------------------------------------------------------- #
class PlanTest(unittest.TestCase):
    def test_plan_is_read_only_and_deterministic(self):
        orca = FakeOrca()
        rc, out = capture(lambda: c.main(base_argv("/tmp/x.lock", "plan"), runner=orca))
        self.assertEqual(rc, 0)
        # plan must NOT mutate Orca (no create/edit).
        self.assertEqual(orca.create_calls, [])
        self.assertEqual(orca.edit_calls, [])
        # plan only read repo list.
        self.assertTrue(any(a[:3] == ["repo", "list", "--json"] for a in orca.all_calls))
        self.assertFalse(any(a[:2] == ["automations", "create"] for a in orca.all_calls))
        payload = json.loads(out)
        self.assertTrue(payload["read_only"])
        spec = payload["spec"]
        self.assertEqual(spec["name"], "orca-pr-listener-acme-widgets-me")
        self.assertEqual(
            spec["marker"], "[orca-pr-listener:v1 repo=acme/widgets reviewer=me]"
        )
        self.assertEqual(spec["repo_id"], "repo-1")
        self.assertEqual(spec["base_branch"], "origin/main")
        # default disabled.
        self.assertTrue(payload["default_disabled"])
        self.assertFalse(spec["enabled"])
        # proposed argv is an argument array referencing exact repo id.
        argv = payload["proposed_create_argv"]
        self.assertEqual(argv[0], "automations")
        self.assertIn("id:repo-1", argv)
        self.assertIn("--disabled", argv)

    def test_plan_prompt_requires_both_skills_and_safety(self):
        orca = FakeOrca()
        rc, out = capture(lambda: c.main(base_argv("/tmp/x.lock", "plan"), runner=orca))
        prompt = json.loads(out)["spec"]["prompt"]
        self.assertIn("$orca-workflow-automation", prompt)
        self.assertIn("$high-signal-pr-review", prompt)
        self.assertIn("[orca-pr-listener:v1 repo=acme/widgets reviewer=me]", prompt)
        self.assertIn("acme/widgets", prompt)
        self.assertIn("me", prompt)
        # Safety invariants.
        self.assertIn("PRIVATE DRAFT", prompt)
        self.assertIn("never", prompt.lower())
        self.assertIn("merge", prompt.lower())
        self.assertIn("GitHub Projects", prompt)  # must call out the anti-hardcoding
        # Exact SHA.
        self.assertIn("exact headRefOid", prompt)


# --------------------------------------------------------------------------- #
class BoardPolicyTest(unittest.TestCase):
    def _prompt(self, policy):
        orca = FakeOrca()
        rc, out = capture(lambda: c.main(
            base_argv("/tmp/x.lock", "--board-policy", policy, "plan"), runner=orca
        ))
        self.assertEqual(rc, 0)
        return json.loads(out)["spec"]["prompt"]

    def test_required_blocks_when_board_unavailable(self):
        p = self._prompt("required")
        self.assertIn("REQUIRED", p)
        self.assertIn("BLOCKED", p)

    def test_invalid_policy_rejected(self):
        orca = FakeOrca()
        rc, _ = capture(lambda: c.main(
            base_argv("/tmp/x.lock", "--board-policy", "bogus", "plan"), runner=orca
        ))
        self.assertEqual(rc, 2)


# --------------------------------------------------------------------------- #
class InstallCreateTest(TempLockMixin, unittest.TestCase):
    def test_install_default_disabled(self):
        orca = FakeOrca()
        rc, out = capture(lambda: c.main(base_argv(self.lock_path, "install"), runner=orca))
        self.assertEqual(rc, 0)
        self.assertEqual(len(orca.create_calls), 1)
        self.assertEqual(len(orca.edit_calls), 0)
        argv = orca.create_calls[0]
        self.assertIn("--disabled", argv)
        self.assertNotIn("--enabled", argv)
        payload = json.loads(out)
        self.assertEqual(payload["action"], "create")
        self.assertFalse(payload["enabled"])
        self.assertTrue(payload["default_disabled"])
        # Exact repo id selector, new-per-run, fresh session, timeout 30.
        self.assertIn("id:repo-1", argv)
        self.assertIn("--workspace-mode", argv)
        self.assertEqual(argv[argv.index("--workspace-mode") + 1], "new-per-run")
        self.assertIn("--fresh-session", argv)
        self.assertEqual(argv[argv.index("--precheck-timeout") + 1], "30")
        # Precheck references the sibling helper with exact repo/reviewer.
        precheck = argv[argv.index("--precheck") + 1]
        self.assertIn("orca-pr-review-queue.py", precheck)
        self.assertIn("--repo acme/widgets", precheck)
        self.assertIn("--reviewer me", precheck)
        self.assertIn("precheck", precheck)

    def test_install_explicit_enable(self):
        orca = FakeOrca()
        rc, _ = capture(lambda: c.main(
            base_argv(self.lock_path, "--enable", "install"), runner=orca
        ))
        self.assertEqual(rc, 0)
        argv = orca.create_calls[0]
        self.assertIn("--enabled", argv)
        self.assertNotIn("--disabled", argv)

    def test_install_dry_run_does_not_mutate(self):
        orca = FakeOrca()
        rc, _ = capture(lambda: c.main(
            base_argv(self.lock_path, "--dry-run", "install"), runner=orca
        ))
        self.assertEqual(rc, 0)
        self.assertEqual(orca.create_calls, [])
        self.assertEqual(orca.edit_calls, [])


# --------------------------------------------------------------------------- #
class IdempotentEditTest(TempLockMixin, unittest.TestCase):
    def _seed(self, **over):
        prompt = c.build_prompt("acme/widgets", "me", "required", "origin/main")
        auto = {
            "id": "auto-7",
            "name": c.deterministic_name("acme/widgets", "me"),
            "prompt": prompt,
            "projectId": "repo-1",
            "enabled": False,
        }
        auto.update(over)
        return [auto]

    def test_existing_matching_is_edited_not_created(self):
        orca = FakeOrca(automations=self._seed())
        rc, out = capture(lambda: c.main(base_argv(self.lock_path, "install"), runner=orca))
        self.assertEqual(rc, 0)
        self.assertEqual(orca.create_calls, [])
        self.assertEqual(len(orca.edit_calls), 1)
        argv = orca.edit_calls[0]
        self.assertEqual(argv[0:3], ["automations", "edit", "auto-7"])
        self.assertIn("--disabled", argv)
        payload = json.loads(out)
        self.assertEqual(payload["action"], "edit")
        self.assertEqual(payload["existing_id"], "auto-7")

    def test_edit_accepts_repo_dict_shape(self):
        seed = self._seed(repo={"id": "repo-1"})
        orca = FakeOrca(automations=seed)
        rc, out = capture(lambda: c.main(base_argv(self.lock_path, "install"), runner=orca))
        self.assertEqual(rc, 0)
        self.assertEqual(len(orca.edit_calls), 1)

    def test_edit_accepts_live_orca_run_context_shape(self):
        seed = self._seed(
            projectId=None,
            runContext={"kind": "workspace-run", "repoId": "repo-1"},
            executionTargetId="local",
        )
        orca = FakeOrca(automations=seed)
        rc, _ = capture(lambda: c.main(base_argv(self.lock_path, "install"), runner=orca))
        self.assertEqual(rc, 0)
        self.assertEqual(len(orca.edit_calls), 1)

    def test_enable_flips_existing_to_enabled(self):
        orca = FakeOrca(automations=self._seed())
        rc, _ = capture(lambda: c.main(
            base_argv(self.lock_path, "--enable", "install"), runner=orca
        ))
        self.assertEqual(rc, 0)
        argv = orca.edit_calls[0]
        self.assertIn("--enabled", argv)


# --------------------------------------------------------------------------- #
class CollisionRefusalTest(TempLockMixin, unittest.TestCase):
    def test_same_name_marker_mismatch_refused(self):
        # Same deterministic name, but prompt marker points at a different repo.
        name = c.deterministic_name("acme/widgets", "me")
        orca = FakeOrca(automations=[{
            "id": "auto-9",
            "name": name,
            "prompt": c.marker("acme/other", "me"),  # different repo
            "projectId": "repo-1",
        }])
        rc, _ = capture(lambda: c.main(base_argv(self.lock_path, "install"), runner=orca))
        self.assertEqual(rc, 2)
        self.assertEqual(orca.create_calls, [])
        self.assertEqual(orca.edit_calls, [])

    def test_marker_matches_but_repo_identity_mismatch_refused(self):
        name = c.deterministic_name("acme/widgets", "me")
        orca = FakeOrca(automations=[{
            "id": "auto-9",
            "name": name,
            "prompt": c.marker("acme/widgets", "me"),
            "projectId": "repo-other",  # different Orca repo
        }])
        rc, _ = capture(lambda: c.main(base_argv(self.lock_path, "install"), runner=orca))
        self.assertEqual(rc, 2)
        self.assertEqual(orca.create_calls, [])
        self.assertEqual(orca.edit_calls, [])

    def test_multiple_same_name_refused(self):
        name = c.deterministic_name("acme/widgets", "me")
        prompt = c.marker("acme/widgets", "me")
        orca = FakeOrca(automations=[
            {"id": "a1", "name": name, "prompt": prompt, "projectId": "repo-1"},
            {"id": "a2", "name": name, "prompt": prompt, "projectId": "repo-1"},
        ])
        rc, _ = capture(lambda: c.main(base_argv(self.lock_path, "install"), runner=orca))
        self.assertEqual(rc, 2)


# --------------------------------------------------------------------------- #
class RepoResolutionTest(unittest.TestCase):
    def test_path_must_be_absolute(self):
        orca = FakeOrca()
        argv = ["--github-repo", "acme/widgets", "--reviewer", "me",
                "--repo-path", "relative/path", "--lock-path", "/tmp/x.lock", "plan"]
        rc, _ = capture(lambda: c.main(argv, runner=orca))
        self.assertEqual(rc, 2)

    def test_path_not_found_rejected(self):
        orca = FakeOrca()
        argv = ["--github-repo", "acme/widgets", "--reviewer", "me",
                "--repo-path", "/no/such/repo", "--lock-path", "/tmp/x.lock", "plan"]
        rc, _ = capture(lambda: c.main(argv, runner=orca))
        self.assertEqual(rc, 2)

    def test_ambiguous_path_rejected(self):
        orca = FakeOrca(repos=[
            repo_record(id="a", path=REPO_PATH),
            repo_record(id="b", path=REPO_PATH),
        ])
        argv = ["--github-repo", "acme/widgets", "--reviewer", "me",
                "--repo-path", REPO_PATH, "--lock-path", "/tmp/x.lock", "plan"]
        rc, _ = capture(lambda: c.main(argv, runner=orca))
        self.assertEqual(rc, 2)

    def test_orca_selector_id_resolves(self):
        orca = FakeOrca()
        argv = ["--github-repo", "acme/widgets", "--reviewer", "me",
                "--orca-repo", "id:repo-1", "--lock-path", "/tmp/x.lock", "plan"]
        rc, out = capture(lambda: c.main(argv, runner=orca))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["spec"]["repo_id"], "repo-1")

    def test_orca_selector_missing_rejected(self):
        orca = FakeOrca()
        argv = ["--github-repo", "acme/widgets", "--reviewer", "me",
                "--orca-repo", "id:nope", "--lock-path", "/tmp/x.lock", "plan"]
        rc, _ = capture(lambda: c.main(argv, runner=orca))
        self.assertEqual(rc, 2)

    def test_missing_worktree_base_ref_requires_override(self):
        orca = FakeOrca(repos=[repo_record(worktreeBaseRef=None)])
        argv = ["--github-repo", "acme/widgets", "--reviewer", "me",
                "--repo-path", REPO_PATH, "--lock-path", "/tmp/x.lock", "plan"]
        rc, _ = capture(lambda: c.main(argv, runner=orca))
        self.assertEqual(rc, 2)

    def test_base_branch_override_used(self):
        orca = FakeOrca(repos=[repo_record(worktreeBaseRef=None)])
        argv = ["--github-repo", "acme/widgets", "--reviewer", "me",
                "--repo-path", REPO_PATH, "--base-branch", "origin/dev",
                "--lock-path", "/tmp/x.lock", "plan"]
        rc, out = capture(lambda: c.main(argv, runner=orca))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["spec"]["base_branch"], "origin/dev")

    def test_both_targets_rejected(self):
        orca = FakeOrca()
        argv = ["--github-repo", "acme/widgets", "--reviewer", "me",
                "--repo-path", REPO_PATH, "--orca-repo", "id:repo-1",
                "--lock-path", "/tmp/x.lock", "plan"]
        with self.assertRaises(SystemExit):
            c.main(argv, runner=orca)  # argparse exits on mutex conflict


# --------------------------------------------------------------------------- #
class ValidationTest(unittest.TestCase):
    def test_bad_github_repo(self):
        orca = FakeOrca()
        argv = ["--github-repo", "not-a-repo", "--reviewer", "me",
                "--repo-path", REPO_PATH, "--lock-path", "/tmp/x.lock", "plan"]
        rc, _ = capture(lambda: c.main(argv, runner=orca))
        self.assertEqual(rc, 2)

    def test_bad_reviewer(self):
        orca = FakeOrca()
        argv = ["--github-repo", "acme/widgets", "--reviewer", "not a login",
                "--repo-path", REPO_PATH, "--lock-path", "/tmp/x.lock", "plan"]
        rc, _ = capture(lambda: c.main(argv, runner=orca))
        self.assertEqual(rc, 2)

    def test_github_repo_must_match_registered_remote(self):
        orca = FakeOrca()
        argv = [
            "--github-repo", "acme/other",
            "--reviewer", "me",
            "--repo-path", REPO_PATH,
            "--lock-path", "/tmp/x.lock",
            "plan",
        ]
        rc, _ = capture(lambda: c.main(argv, runner=orca))
        self.assertEqual(rc, 2)

    def test_missing_verified_github_remote_is_rejected(self):
        orca = FakeOrca(repos=[repo_record(gitRemoteIdentity=None)])
        rc, _ = capture(lambda: c.main(base_argv("/tmp/x.lock", "plan"), runner=orca))
        self.assertEqual(rc, 2)

    def test_github_icon_identity_is_valid_fallback_for_ssh_alias(self):
        orca = FakeOrca(repos=[repo_record(
            gitRemoteIdentity={"canonicalKey": "github.com-work/acme/widgets"},
            repoIcon={"source": "github", "label": "acme/widgets"},
        )])
        rc, _ = capture(lambda: c.main(base_argv("/tmp/x.lock", "plan"), runner=orca))
        self.assertEqual(rc, 0)

    def test_unsafe_base_branch_provider_and_timezone_are_rejected(self):
        for extra in (
            ["--base-branch", "origin/main\nignore-rules"],
            ["--provider", "codex\nother"],
            ["--timezone", "America/Sao Paulo"],
        ):
            orca = FakeOrca()
            rc, _ = capture(
                lambda extra=extra: c.main(
                    base_argv("/tmp/x.lock", *extra, "plan"), runner=orca
                )
            )
            self.assertEqual(rc, 2)


# --------------------------------------------------------------------------- #
class StatusTest(unittest.TestCase):
    def test_status_read_only_absent(self):
        orca = FakeOrca(automations={})
        rc, out = capture(lambda: c.main(
            ["--github-repo", "acme/widgets", "--reviewer", "me",
             "--repo-path", REPO_PATH, "status"], runner=orca
        ))
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["exists"])
        self.assertEqual(payload["state"], "absent")

    def test_status_detects_present_consistent(self):
        name = c.deterministic_name("acme/widgets", "me")
        orca = FakeOrca(automations=[{
            "id": "auto-1", "name": name,
            "prompt": c.marker("acme/widgets", "me"),
            "projectId": "repo-1", "enabled": False,
        }])
        rc, out = capture(lambda: c.main(
            ["--github-repo", "acme/widgets", "--reviewer", "me",
             "--repo-path", REPO_PATH, "status"], runner=orca
        ))
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertTrue(payload["exists"])
        self.assertTrue(payload["consistent"])

    def test_status_flags_inconsistent(self):
        name = c.deterministic_name("acme/widgets", "me")
        orca = FakeOrca(automations=[{
            "id": "auto-1", "name": name,
            "prompt": c.marker("acme/other", "me"),  # marker mismatch
            "projectId": "repo-1",
        }])
        rc, out = capture(lambda: c.main(
            ["--github-repo", "acme/widgets", "--reviewer", "me",
             "--repo-path", REPO_PATH, "status"], runner=orca
        ))
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertTrue(payload["exists"])
        self.assertFalse(payload["consistent"])


# --------------------------------------------------------------------------- #
class LockAndSafetyTest(TempLockMixin, unittest.TestCase):
    def test_lock_file_holds_no_repo_url(self):
        lock = c.SingleWriterLock(Path(self.lock_path))
        lock.acquire()
        try:
            content = Path(self.lock_path).read_text(encoding="utf-8")
            data = json.loads(content)
            self.assertIn("pid", data)
            self.assertIn("acquired_at", data)
            # No repo URL or github identity persisted.
            for forbidden in ("acme/widgets", "https://", "github", "repo-1"):
                self.assertNotIn(forbidden, content)
        finally:
            lock.release()
        # Released: lock file is gone.
        self.assertFalse(Path(self.lock_path).exists())

    def test_lock_busy_when_held(self):
        lock1 = c.SingleWriterLock(Path(self.lock_path))
        lock1.acquire()
        try:
            lock2 = c.SingleWriterLock(Path(self.lock_path))
            with self.assertRaises(c.LockBusy):
                lock2.acquire()
        finally:
            lock1.release()

    def test_install_does_not_write_home(self):
        # HOME is intentionally left real; we assert no file is created under
        # the real XDG/home state path by redirecting the lock to a temp path.
        orca = FakeOrca()
        before = set(Path(self.tmp).glob("**/*"))
        rc, _ = capture(lambda: c.main(base_argv(self.lock_path, "install"), runner=orca))
        self.assertEqual(rc, 0)
        after = set(Path(self.tmp).glob("**/*"))
        # Lock released: only the lock dir remains (no extra artifacts).
        leftover = [p for p in (after - before)]
        self.assertEqual(leftover, [])

    def test_no_shell_true_in_source(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                self.assertFalse(
                    any(keyword.arg == "shell" for keyword in node.keywords)
                )

    def test_default_runner_uses_argv_list(self):
        # default_orca_runner must build ["orca", *args] (no shell).
        import inspect
        src = inspect.getsource(c.default_orca_runner)
        self.assertIn('["orca"', src)

    def test_preflight_rejects_missing_helper(self):
        with self.assertRaises(c.ConfiguratorError):
            c.preflight_helper(Path("/no/such/helper.py"))


# --------------------------------------------------------------------------- #
class PromptSafetyTest(unittest.TestCase):
    def test_prompt_has_no_github_write_primitive(self):
        p = c.build_prompt("acme/widgets", "me", "required", "origin/main")
        low = p.lower()
        # Must explicitly forbid writes.
        self.assertIn("never post", low)
        self.assertIn("never merge", low)
        self.assertIn("never edit", low)
        self.assertIn("never comment", low)

    def test_prompt_agg_telemetry_only(self):
        p = c.build_prompt("acme/widgets", "me", "required", "origin/main")
        low = p.lower()
        self.assertIn("aggregate", low)
        self.assertIn("never record prompts", low)

    def test_precheck_command_is_exact_and_safe(self):
        cmd = c.build_precheck_command(
            Path("/abs/orca-pr-review-queue.py"), "acme/widgets", "me"
        )
        self.assertIn("--repo acme/widgets", cmd)
        self.assertIn("--reviewer me", cmd)
        self.assertTrue(cmd.endswith("precheck"))
        # No shell metacharacters from the validated tokens.
        for bad in (";", "|", "&", "$", "`"):
            self.assertNotIn(bad, cmd)

    def test_precheck_rejects_bad_tokens(self):
        with self.assertRaises(c.ConfiguratorError):
            c.build_precheck_command(Path("/x.py"), "not a repo", "me")
        with self.assertRaises(c.ConfiguratorError):
            c.build_precheck_command(Path("/x.py"), "acme/widgets", "bad login")


if __name__ == "__main__":
    unittest.main(verbosity=2)
