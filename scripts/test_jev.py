#!/usr/bin/env python3
"""Focused regression test for the Jev connector request contract."""

import importlib.util
import argparse
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE = (
    Path(__file__).parents[1]
    / "skillsets/agent-runtime/shared/typed-decisions/scripts/jev.py"
)
SPEC = importlib.util.spec_from_file_location("jev_under_test", SOURCE)
jev = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(jev)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return json.dumps({"model": "synthetic-jev", "answers": {}}).encode()


class JevRequestContractTest(unittest.TestCase):
    def test_call_sets_connector_user_agent_and_preserves_auth(self):
        requests = []

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            return _Response()

        with (
            patch.dict(
                os.environ,
                {
                    "TYPESAFE_BASE_URL": "https://connector.example",
                    "TYPESAFE_API_KEY": "synthetic-key",
                },
            ),
            patch.object(jev.urllib.request, "urlopen", fake_urlopen),
        ):
            response = jev.call({"state": {"synthetic": True}}, timeout=7)

        self.assertEqual(response["model"], "synthetic-jev")
        self.assertEqual(len(requests), 1)
        request, timeout = requests[0]
        self.assertEqual(timeout, 7)
        self.assertEqual(request.headers.get("User-agent"), "TypeSafeJev/1.0")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-key")
        self.assertEqual(request.headers.get("Content-type"), "application/json")

    def test_record_attaches_peer_agreement_and_usage_cost(self):
        commands = []

        def fake_run(command, **_):
            commands.append(command)
            return type("Result", (), {"returncode": 0, "stdout": "decision-id", "stderr": ""})()

        args = argparse.Namespace(point="q=hermes-finding-kind", peer_answer=[("q", "named-defect")], ref="jev-hermes:pr-17:c01")
        questions = {"q": {"type": "choice", "criteria": {"named-defect": "", "evidence-method": "", "unclear": ""}}}
        answers = {"q": {"answer": "named-defect", "tier": "high", "confidence": 0.91}}
        with patch.object(jev.subprocess, "run", fake_run):
            jev.record(args, questions, "synthetic-jev", answers, 30, 25, 0.001)

        self.assertIn(["--agreement", "agreed"], [commands[0][index:index + 2] for index in range(len(commands[0]) - 1)])
        self.assertIn(["--spend-usd", "0.001"], [commands[0][index:index + 2] for index in range(len(commands[0]) - 1)])
        self.assertIn("system-one", commands[0])
        self.assertIn("jev-hermes:pr-17:c01", commands[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
