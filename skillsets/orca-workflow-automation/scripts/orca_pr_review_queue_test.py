#!/usr/bin/env python3
"""Offline unit tests for orca-pr-review-queue.py business logic.

No network, no gh, no real home writes. All tests exercise the pure business
logic with fixtures; gh and state IO are isolated behind injectable seams.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MODULE_PATH = (SCRIPT_DIR.parent / "codex" / "orca-workflow-automation" / "scripts"
               / "orca-pr-review-queue.py")
_spec = importlib.util.spec_from_file_location("orca_pr_review_queue", MODULE_PATH)
q = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(q)  # type: ignore


def pr(number, **over):
    base = {
        "number": number,
        "title": f"PR {number}",
        "state": "OPEN",
        "isDraft": False,
        "headRefOid": "A" * 40,
        "headRefName": "branch",
        "author": "someone",
        "authorIsBot": False,
        "reviewRequests": ["me"],
        "authorActivityAt": "2024-01-01T00:00:00Z",
    }
    base.update(over)
    return base


def fake_runner(prs_payload, login="me"):
    """Return a GhRunner that serves ``api user`` and ``pr list`` from fixtures."""
    def runner(args):
        if args[:2] == ["api", "user"]:
            return login
        if args[:2] == ["pr", "list"]:
            return json.dumps(prs_payload)
        raise AssertionError(f"unexpected gh args: {args}")
    return runner


class EligibilityTest(unittest.TestCase):
    def test_eligible_open_non_draft_review_requested(self):
        ok, reason = q.compute_eligibility(pr(1), "me")
        self.assertTrue(ok)
        self.assertEqual(reason, "eligible")

    def test_draft_pr_rejected(self):
        ok, reason = q.compute_eligibility(pr(1, isDraft=True), "me")
        self.assertFalse(ok)
        self.assertEqual(reason, "draft-pr")

    def test_bot_author_rejected(self):
        ok, reason = q.compute_eligibility(pr(1, author="dependabot[bot]",
                                              authorIsBot=True), "me")
        self.assertFalse(ok)
        self.assertEqual(reason, "bot-author")

    def test_self_review_rejected(self):
        ok, reason = q.compute_eligibility(pr(1, author="me"), "me")
        self.assertFalse(ok)
        self.assertEqual(reason, "self-authored")

    def test_not_review_requested_rejected(self):
        ok, reason = q.compute_eligibility(pr(1, reviewRequests=["other"]), "me")
        self.assertFalse(ok)
        self.assertEqual(reason, "not-review-requested")

    def test_missing_sha_rejected(self):
        ok, reason = q.compute_eligibility(pr(1, headRefOid=None), "me")
        self.assertFalse(ok)
        self.assertEqual(reason, "missing-head-sha")

    def test_closed_rejected(self):
        ok, reason = q.compute_eligibility(pr(1, state="CLOSED"), "me")
        self.assertFalse(ok)
        self.assertEqual(reason, "not-open")


class NormalizeTest(unittest.TestCase):
    def test_bot_detected_from_login_suffix(self):
        n = q.normalize_pr({"number": 1, "author": {"login": "dependabot[bot]"},
                            "reviewRequests": [], "state": "OPEN"})
        self.assertTrue(n["authorIsBot"])

    def test_review_requests_extracted(self):
        n = q.normalize_pr({"number": 1, "author": {"login": "x"},
                            "reviewRequests": [{"login": "me"}, {"login": "you"}],
                            "state": "OPEN"})
        self.assertEqual(n["reviewRequests"], ["me", "you"])

    def test_missing_head_becomes_none(self):
        n = q.normalize_pr({"number": 1, "author": {"login": "x"},
                            "reviewRequests": [], "state": "OPEN"})
        self.assertIsNone(n["headRefOid"])

    def test_invalid_non_hex_head_becomes_none(self):
        n = q.normalize_pr({"number": 1, "headRefOid": "refs/heads/main",
                            "author": {"login": "x"}, "reviewRequests": [],
                            "state": "OPEN"})
        self.assertIsNone(n["headRefOid"])

    def test_latest_top_level_author_comment_is_activity_marker(self):
        n = q.normalize_pr({
            "number": 1, "headRefOid": "A" * 40,
            "author": {"login": "author"}, "reviewRequests": [],
            "state": "OPEN",
            "comments": [
                {"author": {"login": "other"}, "createdAt": "2024-02-01T00:00:00Z"},
                {"author": {"login": "author"}, "createdAt": "2024-01-01T00:00:00Z"},
                {"author": {"login": "author"}, "createdAt": "2024-01-03T00:00:00Z"},
            ],
        })
        self.assertEqual(n["authorActivityAt"], "2024-01-03T00:00:00Z")


class ExactShaDedupTest(unittest.TestCase):
    def test_acked_same_head_skipped(self):
        records = {}
        q.record_ack(records, pr_number=1, head="A" * 40, reviewer="me")
        work, skipped = q.compute_work_items([pr(1)], "me", records)
        self.assertEqual(work, [])
        self.assertEqual(skipped[0]["reason"], "already-reviewed-exact-sha")

    def test_head_change_is_eligible(self):
        records = {}
        q.record_ack(records, pr_number=1, head="A" * 40, reviewer="me")
        new = pr(1, headRefOid="B" * 40)
        work, _ = q.compute_work_items([new], "me", records)
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["headRefOid"], "B" * 40)
        self.assertEqual(work[0]["reason"], "eligible")

    def test_different_reviewer_not_deduped(self):
        records = {}
        q.record_ack(records, pr_number=1, head="A" * 40, reviewer="other")
        # same head, but reviewer 'me' has not acked
        work, _ = q.compute_work_items([pr(1)], "me", records)
        self.assertEqual(len(work), 1)

    def test_exact_sha_keyed_not_by_branch(self):
        records = {}
        q.record_ack(records, pr_number=1, head="A" * 40, reviewer="me")
        # same head SHA but a different branch name => still deduped (SHA-keyed)
        new = pr(1, headRefOid="A" * 40, headRefName="other-branch")
        work, skipped = q.compute_work_items([new], "me", records)
        self.assertEqual(work, [])
        self.assertEqual(skipped[0]["reason"], "already-reviewed-exact-sha")


class AuthorReplyReopenTest(unittest.TestCase):
    def test_later_author_reply_reopens(self):
        records = {}
        q.record_ack(records, pr_number=1, head="A" * 40, reviewer="me",
                     author_activity_marker="2024-01-01T00:00:00Z")
        new = pr(1, headRefOid="A" * 40,
                 authorActivityAt="2024-01-02T00:00:00Z")
        work, _ = q.compute_work_items([new], "me", records)
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["reason"], "reopened-author-comment")

    def test_earlier_or_equal_marker_does_not_reopen(self):
        records = {}
        q.record_ack(records, pr_number=1, head="A" * 40, reviewer="me",
                     author_activity_marker="2024-01-05T00:00:00Z")
        new = pr(1, headRefOid="A" * 40,
                 authorActivityAt="2024-01-04T00:00:00Z")
        work, skipped = q.compute_work_items([new], "me", records)
        self.assertEqual(work, [])
        self.assertEqual(skipped[0]["reason"], "already-reviewed-exact-sha")

    def test_no_marker_stored_does_not_reopen(self):
        records = {}
        q.record_ack(records, pr_number=1, head="A" * 40, reviewer="me")
        new = pr(1, headRefOid="A" * 40,
                 authorActivityAt="2024-01-09T00:00:00Z")
        work, _ = q.compute_work_items([new], "me", records)
        self.assertEqual(work, [])


class DeterministicOrderTest(unittest.TestCase):
    def test_deterministic_order_by_number(self):
        prs = [pr(3), pr(1), pr(2)]
        work, _ = q.compute_work_items(prs, "me", {})
        self.assertEqual([w["number"] for w in work], [1, 2, 3])


class StateIoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orca-queue-state-")
        self.state_path = Path(self.tmp) / "state.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_then_load_roundtrip(self):
        records = {}
        q.record_ack(records, pr_number=7, head="D" * 40, reviewer="me",
                     author_activity_marker="2024-01-01T00:00:00Z")
        q.save_state({"records": records}, self.state_path)
        loaded = q.load_state(self.state_path)
        self.assertEqual(loaded["schema_version"], q.SCHEMA_VERSION)
        rec = next(iter(loaded["records"].values()))
        self.assertEqual(rec["head"], "D" * 40)
        self.assertEqual(rec["reviewer"], "me")

    def test_state_file_mode_is_restrictive(self):
        records = {}
        q.record_ack(records, pr_number=7, head="D" * 40, reviewer="me")
        q.save_state({"records": records}, self.state_path)
        mode = self.state_path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_load_missing_returns_empty(self):
        loaded = q.load_state(self.state_path)
        self.assertEqual(loaded["records"], {})

    def test_load_corrupt_fails_closed(self):
        self.state_path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(q.QueueStateError):
            q.load_state(self.state_path)

    def test_state_stores_no_secrets_or_repo_url(self):
        records = {}
        q.record_ack(records, pr_number=7, head="D" * 40, reviewer="me")
        q.save_state({"records": records}, self.state_path)
        text = self.state_path.read_text(encoding="utf-8")
        # No title, no repo url, no branch, no tokens stored.
        for forbidden in ("PR 7", "https://", "token", "branch"):
            self.assertNotIn(forbidden, text)


class AckValidationTest(unittest.TestCase):
    def test_ack_rejects_empty_head(self):
        with self.assertRaises(ValueError):
            q.record_ack({}, pr_number=1, head="", reviewer="me")

    def test_ack_rejects_moving_ref(self):
        with self.assertRaises(ValueError):
            q.record_ack({}, pr_number=1, head="refs/heads/main", reviewer="me")

    def test_ack_accepts_sha256_oid(self):
        entry = q.record_ack({}, pr_number=1, head="A" * 64, reviewer="me")
        self.assertEqual(entry["head"], "A" * 64)

    def test_ack_rejects_invalid_reviewer_and_activity_marker(self):
        with self.assertRaises(ValueError):
            q.record_ack({}, pr_number=1, head="A" * 40, reviewer="not a login")
        with self.assertRaises(ValueError):
            q.record_ack({}, pr_number=1, head="A" * 40, reviewer="me",
                         author_activity_marker="not-a-timestamp")


class CliScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orca-queue-cli-")
        os.environ["XDG_STATE_HOME"] = str(Path(self.tmp) / "state")

    def tearDown(self):
        os.environ.pop("XDG_STATE_HOME", None)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scan_outputs_eligible_with_pinned_sha(self):
        captured = {}
        import io
        buf = io.StringIO()
        orig = sys.stdout
        sys.stdout = buf
        try:
            rc = q.main(["--reviewer", "me", "scan"],
                        runner=fake_runner([
                            {"number": 1, "state": "OPEN", "isDraft": False,
                             "headRefOid": "C" * 40, "author": {"login": "x"},
                             "reviewRequests": [{"login": "me"}],
                             "comments": []},
                        ]))
        finally:
            sys.stdout = orig
        captured["out"] = buf.getvalue()
        self.assertEqual(rc, 0)
        payload = json.loads(captured["out"])
        self.assertEqual(payload["work_items"][0]["headRefOid"], "C" * 40)
        self.assertIn("note", payload)

    def test_default_reviewer_uses_raw_gh_jq_output(self):
        rc = q.main(["precheck"], runner=fake_runner([
            {"number": 1, "state": "OPEN", "isDraft": False,
             "headRefOid": "C" * 40, "author": {"login": "x"},
             "reviewRequests": [{"login": "me"}], "comments": []},
        ]))
        self.assertEqual(rc, 0)

    def test_precheck_exit_codes_nonleaking(self):
        # eligible -> exit 0
        rc_yes = q.main(["--reviewer", "me", "precheck"],
                        runner=fake_runner([
                            {"number": 1, "state": "OPEN", "isDraft": False,
                             "headRefOid": "C" * 40, "author": {"login": "x"},
                             "reviewRequests": [{"login": "me"}]},
                        ]))
        self.assertEqual(rc_yes, 0)
        # nothing eligible -> exit 1
        rc_no = q.main(["--reviewer", "me", "precheck"],
                       runner=fake_runner([
                           {"number": 1, "state": "OPEN", "isDraft": True,
                            "headRefOid": "C" * 40, "author": {"login": "x"},
                            "reviewRequests": [{"login": "me"}]},
                       ]))
        self.assertEqual(rc_no, 1)

    def test_ack_then_scan_dedupes_end_to_end(self):
        rc = q.main(["--reviewer", "me", "ack", "--pr", "1", "--head", "C" * 40],
                    runner=fake_runner([]))
        self.assertEqual(rc, 0)
        import io
        buf = io.StringIO()
        orig = sys.stdout
        sys.stdout = buf
        try:
            q.main(["--reviewer", "me", "scan"],
                   runner=fake_runner([
                       {"number": 1, "state": "OPEN", "isDraft": False,
                        "headRefOid": "C" * 40, "author": {"login": "x"},
                        "reviewRequests": [{"login": "me"}]},
                   ]))
        finally:
            sys.stdout = orig
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["work_items"], [])
        self.assertTrue(payload["skipped"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
