#!/usr/bin/env python3
"""Focused regression test for the Jev connector request contract."""

import importlib.util
import argparse
import contextlib
import copy
import io
import json
import os
import sys

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(os.environ["JEV_TEST_SOURCE"]) if os.environ.get("JEV_TEST_SOURCE") else (
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

    def test_peer_labels_are_not_sent_in_the_typesafe_request(self):
        state = {"rules": {"j1": "classify"}, "items": [{"id": "F1", "summary": "A bounded finding."}]}
        bodies = []
        response = {"model": "synthetic-jev", "answers": {"fF1_j1": {
            "type": "choice", "choice": "evidence-method", "confidence": 0.9,
            "probabilities": {"named-defect": 0.05, "evidence-method": 0.9, "unclear": 0.05},
        }}, "usage": {"input_tokens": 300, "output_tokens": 30}}
        argv = ["jev.py", "--state-file", "-", "--pick", "fF1_j1", "classify", "named-defect|evidence-method|unclear",
                "--peer-answer", "fF1_j1", "named-defect"]
        with (
            patch.object(sys, "argv", argv),
            patch.object(sys, "stdin", io.StringIO(json.dumps(state))),
            patch.object(jev, "call", lambda body, timeout: bodies.append(body) or response),
            patch.object(jev, "record"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(jev.main(), 0)
        self.assertEqual(bodies[0]["state"], state)
        self.assertNotIn("peer_answer", bodies[0])
        self.assertNotIn("named-defect", json.dumps(bodies[0]["state"]))

    def test_http_auth_failure_does_not_echo_response_body_or_retry(self):
        error = jev.urllib.error.HTTPError(
            "https://connector.example/v1/systemone", 401, "Unauthorized", {},
            io.BytesIO(b'provider echoed a private credential'))
        with patch.object(jev.urllib.request, "urlopen", side_effect=error) as transport:
            with self.assertRaisesRegex(RuntimeError, "HTTP 401") as caught:
                jev.call({}, timeout=7)
        self.assertNotIn("private credential", str(caught.exception))
        self.assertEqual(transport.call_count, 1)

    def test_invalid_json_is_a_service_failure(self):
        response = _Response()
        response.read = lambda *_: b'not JSON private provider body'
        with patch.object(jev.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "invalid JSON response"):
                jev.call({}, timeout=7)


QUESTIONS = {
    "yn": {"type": "noul", "instructions": "Is the fixture missing an import?"},
    "pick": {"type": "choice", "instructions": "Which category?",
             "criteria": {"import": "Missing import", "syntax": "Syntax failure"}},
    "level": {"type": "score", "instructions": "Which impact level?",
              "criteria": ["Cosmetic", "Build fails"]},
}
RESPONSE = {
    "model": "synthetic-jev",
    "answers": {
        "yn": {"type": "noul", "noul": 0.99},
        "pick": {"type": "choice", "choice": "import", "confidence": 0.9,
                 "probabilities": {"import": 0.95, "syntax": 0.05}},
        "level": {"type": "score", "score": 0.95, "confidence": 0.9,
                  "probabilities": {"0": 0.05, "1": 0.95},
                  "legend": {"0": "Cosmetic", "1": "Build fails"}},
    },
    "usage": {"input_tokens": 300, "output_tokens": 30},
}


class JevResponseContractTest(unittest.TestCase):
    def cli(self, response, flags=(), questions=None, record=False):
        stdout, stderr = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "questions.json"
            spec.write_text(json.dumps(questions if questions is not None else QUESTIONS))
            argv = [str(SOURCE), "--state", "Anonymous compiler fixture", "--spec", str(spec), *flags]
            if record:
                argv += ["--record", "--point", "triage", "--ref", "synthetic-contract-test"]
            with (patch.object(sys, "argv", argv),
                  patch.dict(os.environ, {"JEV_DRY_RUN": "0"}),
                  patch.object(jev, "call", return_value=response) as transport,
                  patch.object(jev, "record") as ledger,
                  contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr)):
                rc = jev.main()
        return rc, stdout.getvalue(), stderr.getvalue(), ledger, transport

    def assert_refused(self, response, questions=None):
        # Raw output and --record must not provide alternate paths around validation.
        for flags in ((), ("--raw",)):
            rc, stdout, stderr, ledger, _ = self.cli(
                response, flags, questions=questions, record=True)
            self.assertEqual(rc, 3, stderr)
            self.assertEqual(stdout, "")
            self.assertIn("invalid service response", stderr)
            ledger.assert_not_called()

    def test_complete_batch_is_shaped_and_recorded(self):
        rc, stdout, stderr, ledger, _ = self.cli(copy.deepcopy(RESPONSE), record=True)
        self.assertEqual((rc, stderr), (0, ""))
        answers = json.loads(stdout)["answers"]
        self.assertEqual({key: value["answer"] for key, value in answers.items()},
                         {"yn": "yes", "pick": "import", "level": "L1"})
        ledger.assert_called_once()

    def test_valid_raw_response_is_preserved(self):
        rc, stdout, stderr, _, _ = self.cli(copy.deepcopy(RESPONSE), ("--raw",))
        self.assertEqual((rc, stderr), (0, ""))
        self.assertEqual(json.loads(stdout), RESPONSE)

    def test_question_ids_must_match_exactly(self):
        for kind in ("missing", "extra", "empty", "wrong-map"):
            with self.subTest(kind=kind):
                response = copy.deepcopy(RESPONSE)
                if kind == "missing": del response["answers"]["level"]
                elif kind == "extra": response["answers"]["unasked"] = {"type": "noul", "noul": 1}
                elif kind == "empty": response["answers"] = {}
                else: response["answers"] = []
                self.assert_refused(response)

    def test_noul_requires_finite_unit_interval_number(self):
        for value in (-0.1, 1.5, True, "0.99", None, float("nan"), float("inf"), 10**400):
            with self.subTest(value=str(value)[:20]):
                response = copy.deepcopy(RESPONSE)
                response["answers"]["yn"]["noul"] = value
                self.assert_refused(response)

    def test_unit_interval_boundaries_are_valid(self):
        for value in (0, 1, 0.5):
            response = copy.deepcopy(RESPONSE)
            response["answers"]["yn"]["noul"] = value
            self.assertEqual(self.cli(response)[0], 0)

    def test_choice_must_belong_to_declared_space(self):
        response = copy.deepcopy(RESPONSE)
        response["answers"]["pick"]["choice"] = "unrequested-action"
        self.assert_refused(response)

    def test_choice_must_match_a_highest_probability_option(self):
        response = copy.deepcopy(RESPONSE)
        response["answers"]["pick"]["choice"] = "syntax"
        self.assert_refused(response)

    def test_confidence_is_required_and_bounded(self):
        for qid in ("pick", "level"):
            for value in (None, True, -0.1, 1.1, float("nan"), float("inf"), "high"):
                with self.subTest(qid=qid, value=value):
                    response = copy.deepcopy(RESPONSE)
                    response["answers"][qid]["confidence"] = value
                    self.assert_refused(response)

    def test_probability_maps_cover_declared_space(self):
        for qid in ("pick", "level"):
            for values in ({}, [], {"unknown": 1}, None):
                with self.subTest(qid=qid, values=values):
                    response = copy.deepcopy(RESPONSE)
                    response["answers"][qid]["probabilities"] = values
                    self.assert_refused(response)

    def test_distribution_values_and_sum_are_validated(self):
        for values in ({"import": -0.1, "syntax": 1.1},
                       {"import": float("nan"), "syntax": 0.1},
                       {"import": True, "syntax": 0},
                       {"import": 0.9, "syntax": 0.9}):
            with self.subTest(values=values):
                response = copy.deepcopy(RESPONSE)
                response["answers"]["pick"]["probabilities"] = values
                self.assert_refused(response)

    def test_score_is_finite_and_within_declared_levels(self):
        for value in (-1, 2, None, "1", True, float("nan"), float("inf")):
            with self.subTest(value=value):
                response = copy.deepcopy(RESPONSE)
                response["answers"]["level"]["score"] = value
                self.assert_refused(response)

    def test_score_must_match_probability_weighted_levels(self):
        response = copy.deepcopy(RESPONSE)
        response["answers"]["level"]["score"] = 0
        self.assert_refused(response)

    def test_score_accepts_float_serialization_noise(self):
        response = copy.deepcopy(RESPONSE)
        response["answers"]["level"]["score"] = 0.9500000000000001
        self.assertEqual(self.cli(response)[0], 0)

    def test_score_normalizes_accepted_probability_rounding(self):
        questions, response = copy.deepcopy(QUESTIONS), copy.deepcopy(RESPONSE)
        questions["level"]["criteria"] = [str(i) for i in range(10)]
        answer = response["answers"]["level"]
        answer["legend"] = {str(i): str(i) for i in range(10)}
        for p9 in (0.9999995, 0.9999985):
            with self.subTest(p9=p9):
                probabilities = {str(i): 0.0 for i in range(10)}
                probabilities.update({"0": 0.000001, "9": p9})
                answer["probabilities"] = probabilities
                weighted = 9 * p9
                answer["score"] = weighted / sum(probabilities.values())
                self.assertEqual(self.cli(response, questions=questions)[0], 0)

    def test_score_refuses_unnormalized_probability_rounding(self):
        questions, response = copy.deepcopy(QUESTIONS), copy.deepcopy(RESPONSE)
        questions["level"]["criteria"] = [str(i) for i in range(10)]
        answer = response["answers"]["level"]
        answer["legend"] = {str(i): str(i) for i in range(10)}
        for p9 in (0.9999995, 0.9999985):
            with self.subTest(p9=p9):
                answer["probabilities"] = {str(i): 0.0 for i in range(10)}
                answer["probabilities"].update({"0": 0.000001, "9": p9})
                answer["score"] = 9 * p9
                self.assert_refused(response, questions=questions)

    def test_legend_must_match_the_requested_rubric(self):
        for legend in ({}, [], None, {"0": "Cosmetic", "1": "Changed meaning"}):
            with self.subTest(legend=legend):
                response = copy.deepcopy(RESPONSE)
                response["answers"]["level"]["legend"] = legend
                self.assert_refused(response)

    def test_structured_score_anchors_are_supported(self):
        questions, response = copy.deepcopy(QUESTIONS), copy.deepcopy(RESPONSE)
        questions["level"]["criteria"] = [{"impact": "Cosmetic"}, ["Build fails"]]
        response["answers"]["level"]["legend"] = {
            str(i): anchor for i, anchor in enumerate(questions["level"]["criteria"])}
        self.assertEqual(self.cli(response, questions=questions)[0], 0)

    def test_wrong_or_missing_answer_type_is_rejected(self):
        for value in (None, [], {"type": "unknown"}, {"type": "noul", "noul": 0.9}):
            with self.subTest(value=value):
                response = copy.deepcopy(RESPONSE)
                response["answers"]["level"] = value
                self.assert_refused(response)

    def test_invalid_envelope_is_rejected(self):
        for response in (None, [], {}, {**RESPONSE, "model": None}, {**RESPONSE, "usage": []},
                         {**RESPONSE, "usage": {"input_tokens": -1}},
                         {**RESPONSE, "usage": {"input_tokens": True}},
                         {**RESPONSE, "usage": {"cost_usd": float("inf")}},
                         {**RESPONSE, "usage": {"spend_usd": "unknown"}}):
            with self.subTest(response=response):
                self.assert_refused(response)

    def test_unknown_metadata_does_not_break_valid_responses(self):
        response = copy.deepcopy(RESPONSE)
        response["provider_metadata"] = {"new_field": True}
        self.assertEqual(self.cli(response)[0], 0)

    def test_malformed_question_specs_do_not_spend_a_call(self):
        for questions in ([], {"q": None}, {"q": {"type": "score", "instructions": "Impact?"}},
                          {"q": {"type": "choice", "instructions": "Category?", "criteria": []}}):
            with self.subTest(questions=questions):
                rc, stdout, _, ledger, transport = self.cli(RESPONSE, questions=questions)
                self.assertEqual((rc, stdout), (2, ""))
                ledger.assert_not_called()
                transport.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
