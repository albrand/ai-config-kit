#!/usr/bin/env python3
"""Offline tests for the execution-ownership lease."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MODULE_PATH = SCRIPT_DIR.parent / "scripts" / "execution-ownership.py"
SPEC = importlib.util.spec_from_file_location("execution_ownership", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class LeaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="execution-ownership-test-"))
        self.root = self.tmp / "leases"
        self.repo = self.tmp / "repo"
        self.worktree = self.tmp / "worktree"
        self.repo.mkdir()
        self.worktree.mkdir()
        self.target = module.canonical_target(
            str(self.repo), str(self.worktree), "fix/example", "A" * 40, "expensive-gate"
        )
        self.store = module.LeaseStore(self.root, stale_after=30)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_canonical_target_is_stable(self):
        same = module.canonical_target(
            str(self.repo / "."), str(self.worktree / ".." / "worktree"),
            "fix/example", "a" * 40, "expensive-gate"
        )
        self.assertEqual(self.target.key, same.key)
        self.assertEqual(same.as_dict()["commit"], "a" * 40)

    def test_malformed_target_is_refused(self):
        with self.assertRaises(module.TargetError):
            module.canonical_target("relative", str(self.worktree), "main", "a" * 40, "op")
        with self.assertRaises(module.TargetError):
            module.canonical_target(str(self.repo), str(self.worktree), "main", "not-a-sha", "op")
        with self.assertRaises(module.TargetError):
            module.canonical_target(str(self.repo), str(self.worktree), "main\n", "a" * 40, "op")
        symlink = self.tmp / "repo-link"
        symlink.symlink_to(self.repo, target_is_directory=True)
        with self.assertRaises(module.TargetError):
            module.canonical_target(str(symlink), str(self.worktree), "main", "a" * 40, "op")

    def test_concurrent_cli_acquire_has_one_owner(self):
        common = [
            sys.executable, str(MODULE_PATH), "--root", str(self.root),
            "--repo", str(self.repo), "--worktree", str(self.worktree),
            "--branch", "fix/example", "--commit", "a" * 40,
            "--operation", "expensive-gate", "acquire",
        ]
        first = subprocess.Popen(common, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        second = subprocess.Popen(common, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        first_out, first_err = first.communicate(timeout=10)
        second_out, second_err = second.communicate(timeout=10)
        self.assertEqual(first_err, "")
        self.assertEqual(second_err, "")
        results = [json.loads(first_out), json.loads(second_out)]
        self.assertEqual(sorted(result["status"] for result in results), ["acquired", "held"])
        self.assertEqual(sorted([first.returncode, second.returncode]), [0, module.EXIT_HELD])

    def test_release_removes_lease_and_preserves_secure_modes(self):
        acquired = self.store.acquire(self.target)
        state = json.loads(self.store.lease_path(self.target).read_text())
        self.assertEqual(state["owner"]["pgid"], os.getpgid(os.getpid()))
        released = self.store.release(self.target, acquired["owner_id"])
        self.assertEqual(released["status"], "released")
        self.assertEqual(self.store.inspect(self.target)["status"], "missing")
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / ".lock").stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.root.glob(".lease-*.tmp")), [])

    def test_heartbeat_renews_owner(self):
        acquired = self.store.acquire(self.target)
        state_path = self.store.lease_path(self.target)
        before = json.loads(state_path.read_text())["owner"]["heartbeat_unix"]
        time.sleep(0.01)
        renewed = self.store.heartbeat(self.target, acquired["owner_id"])
        after = json.loads(state_path.read_text())["owner"]["heartbeat_unix"]
        self.assertEqual(renewed["status"], "renewed")
        self.assertGreaterEqual(after, before)
        self.assertEqual(self.store.heartbeat(self.target, "0" * 32)["status"], "not_owner")

    def _make_stale(self, pid):
        acquired = self.store.acquire(self.target)
        path = self.store.lease_path(self.target)
        state = json.loads(path.read_text())
        state["owner"]["pid"] = pid
        state["owner"]["heartbeat_unix"] = time.time() - 120
        path.write_text(json.dumps(state), encoding="utf-8")
        os.chmod(path, 0o600)
        return acquired

    def test_stale_live_owner_is_refused(self):
        self._make_stale(os.getpid())
        result = self.store.acquire(self.target)
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["code"], "stale_owner_alive")
        self.assertTrue(self.store.lease_path(self.target).exists())

    def test_pid_reuse_with_different_process_group_is_ambiguous(self):
        self._make_stale(os.getpid())
        path = self.store.lease_path(self.target)
        state = json.loads(path.read_text())
        state["owner"]["pgid"] += 1
        path.write_text(json.dumps(state), encoding="utf-8")
        os.chmod(path, 0o600)
        with self.assertRaises(module.LeaseError) as error:
            self.store.acquire(self.target)
        self.assertEqual(error.exception.code, "ambiguous_owner")

    def test_bb_thread_metadata_is_optional_and_recorded_when_present(self):
        previous = os.environ.get("BB_THREAD_ID")
        os.environ["BB_THREAD_ID"] = "thr_fixture"
        try:
            store = module.LeaseStore(self.root)
            store.acquire(self.target)
            state = json.loads(store.lease_path(self.target).read_text())
            self.assertEqual(state["owner"]["owner_thread"], "thr_fixture")
            store.release(self.target, state["owner"]["owner_id"])
        finally:
            if previous is None:
                os.environ.pop("BB_THREAD_ID", None)
            else:
                os.environ["BB_THREAD_ID"] = previous

    def test_stale_dead_owner_is_reclaimed(self):
        old = self._make_stale(99999999)
        result = self.store.acquire(self.target)
        self.assertEqual(result["status"], "reclaimed")
        self.assertNotEqual(result["owner_id"], old["owner_id"])
        self.assertEqual(self.store.lease_path(self.target).stat().st_mode & 0o777, 0o600)
        self.store.release(self.target, result["owner_id"])

    def test_malformed_state_and_symlink_fail_closed(self):
        self.store.acquire(self.target)
        path = self.store.lease_path(self.target)
        path.write_text("not-json", encoding="utf-8")
        with self.assertRaises(module.LeaseError) as error:
            self.store.acquire(self.target)
        self.assertEqual(error.exception.code, "malformed_lease")
        path.unlink()
        victim = self.tmp / "victim"
        victim.write_text("untouched", encoding="utf-8")
        path.symlink_to(victim)
        with self.assertRaises(module.LeaseError) as error:
            self.store.inspect(self.target)
        self.assertEqual(error.exception.code, "state_error")
        self.assertEqual(victim.read_text(), "untouched")

    def test_symlink_root_is_refused(self):
        real = self.tmp / "real-root"
        real.mkdir()
        link = self.tmp / "root-link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(module.LeaseError) as error:
            module.LeaseStore(link).acquire(self.target)
        self.assertEqual(error.exception.code, "unsafe_root")


if __name__ == "__main__":
    unittest.main(verbosity=2)
