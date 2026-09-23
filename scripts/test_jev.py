#!/usr/bin/env python3
"""Focused regression test for the Jev connector request contract."""

import importlib.util
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
