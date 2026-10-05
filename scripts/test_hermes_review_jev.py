import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skillsets/agent-runtime/shared/typed-decisions/scripts/hermes-review-jev.py"
SPEC = importlib.util.spec_from_file_location("hermes_review_jev", SCRIPT)
review_jev = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(review_jev)


def packet():
    return {
        "review_ref": "pr-17@abc123",
        "hermes_verdict": "revise",
        "sensitive_context": False,
        "changed_paths": ["lib/review.ts"],
        "findings": [{
            "id": "F1",
            "kind": "named-defect",
            "path": "lib/review.ts",
            "severity": "high",
            "cause": "delta",
            "relation": "new",
            "prior_id": "",
            "prior_summary": "",
            "changed_path": "changed",
            "summary": "Changed review handling skips the required ownership check.",
        }],
    }


class HermesReviewJevTest(unittest.TestCase):
    def test_client_path_prefers_worktree_client(self):
        self.assertEqual(review_jev.client_path(), SCRIPT.with_name("jev.py"))

    def fake_client(self, directory):
        capture = Path(directory) / "captured.json"
        client = Path(directory) / "fake-jev.py"
        client.write_text(
            "import json,os,sys\n"
            "args=sys.argv[1:]\n"
            "state=sys.stdin.read()\n"
            "open(os.environ['JEV_TEST_CAPTURE'],'w').write(state)\n"
            "answers={}\n"
            "for i,arg in enumerate(args):\n"
            " if arg == '--pick': answers[args[i+1]]={'answer':args[i+3].split('|')[0].split('=')[0],'ledger':'decision-id'}\n"
            " if arg == '--peer-answer': answers[args[i+1]]={'answer':args[i+2],'ledger':'decision-id'}\n"
            "if os.environ.get('JEV_TEST_DISAGREE') == '1': answers['fF1_j1']['answer']='evidence-method'\n"
            "if os.environ.get('JEV_TEST_SPLIT') == '1': answers['fF1_j3_severity']['answer']='info'\n"
            "print(json.dumps({'model':'test','answers':answers,'usage':{'input_tokens':20,'output_tokens':5},'latency_ms':30}))\n",
            encoding="utf-8",
        )
        return client, capture

    def test_payload_contains_only_bounded_finding_text_rules_and_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            client, capture = self.fake_client(directory)
            value = packet()
            with patch.dict(os.environ, {"JEV_TEST_CAPTURE": str(capture)}):
                result = review_jev.run_judge(review_jev.validate_packet(value), client)
            payload = capture.read_text(encoding="utf-8")
            state = json.loads(payload)
            self.assertEqual(result["status"], "AGREEMENT")
            self.assertIn("Changed review handling", payload)
            self.assertNotIn("diff", payload.lower())
            self.assertNotIn("source_excerpt", payload)
            self.assertEqual(set(state["items"][0]), {"id", "path", "prior_summary", "summary"})
            self.assertNotIn("hermes_verdict", state)
            self.assertFalse({"kind", "severity", "cause", "relation", "changed_path"} & set(state["items"][0]))

    def test_raw_diff_or_source_excerpt_fields_are_rejected(self):
        for field in ("diff", "source_excerpt", "project_source"):
            value = packet()
            value[field] = "SOURCE-EXCERPT-MUST-NOT-LEAK"
            with self.subTest(field=field), self.assertRaises(ValueError):
                review_jev.validate_packet(value)

    def test_code_excerpt_and_personal_data_are_rejected(self):
        for summary in (
            "`const account = value` is missing a check.",
            "Patient contact 555-222-1000 is exposed.",
            "+ const sourceExcerpt = true",
        ):
            value = packet()
            value["findings"][0]["summary"] = summary
            with self.subTest(summary=summary), self.assertRaises(ValueError):
                review_jev.validate_packet(value)

    def test_synthetic_agreement_is_reported_without_changing_hermes_verdict(self):
        with tempfile.TemporaryDirectory() as directory:
            client, capture = self.fake_client(directory)
            with patch.dict(os.environ, {"JEV_TEST_CAPTURE": str(capture), "JEV_TEST_DISAGREE": "0"}):
                result = review_jev.run_judge(review_jev.validate_packet(packet()), client)
            self.assertEqual(result["status"], "AGREEMENT")
            self.assertEqual(result["hermes_verdict"], "revise")
            self.assertTrue(result["items"][0]["recorded"])

    def test_synthetic_disagreement_escalates_without_changing_hermes_verdict(self):
        with tempfile.TemporaryDirectory() as directory:
            client, capture = self.fake_client(directory)
            with patch.dict(os.environ, {"JEV_TEST_CAPTURE": str(capture), "JEV_TEST_DISAGREE": "1"}):
                result = review_jev.run_judge(review_jev.validate_packet(packet()), client)
            self.assertEqual(result["status"], "ESCALATED")
            self.assertEqual(result["hermes_verdict"], "revise")

    def test_split_judgments_record_independently_and_escalate(self):
        with tempfile.TemporaryDirectory() as directory:
            client, capture = self.fake_client(directory)
            with patch.dict(os.environ, {"JEV_TEST_CAPTURE": str(capture), "JEV_TEST_SPLIT": "1"}):
                result = review_jev.run_judge(review_jev.validate_packet(packet()), client)
            item = result["items"][0]
            self.assertEqual(result["status"], "ESCALATED")
            self.assertEqual(item["answers"]["j1"], "named-defect")
            self.assertEqual(item["answers"]["j3_severity"], "info")
            self.assertTrue(item["recorded"])
            self.assertEqual(len(item["refs"]), 5)
            self.assertIn("#fF1_j1", item["refs"][0])
            self.assertIn("#fF1_j3_severity", item["refs"][-1])

    def test_sensitive_context_skips_jev(self):
        value = packet()
        value["sensitive_context"] = True
        result = review_jev.run_judge(review_jev.validate_packet(value), Path("unused"))
        self.assertEqual(result["status"], "NOT RUN")
        self.assertEqual(result["hermes_verdict"], "revise")


if __name__ == "__main__":
    unittest.main(verbosity=2)
