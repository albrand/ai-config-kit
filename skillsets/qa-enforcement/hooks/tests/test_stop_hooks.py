#!/usr/bin/env python3
"""Focused fixtures for final-claim Stop behavior and Codex trust scope."""
import ast
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE = ROOT.parent / "shared/qa-sweep/scripts/evidence-stop.py"
SHIP = ROOT.parent / "shared/qa-sweep/scripts/ship-gate.py"
TRUST = ROOT / "codex-hook-trust.py"
STOP = ROOT / "qa-stop-hook.sh"


def run(cmd, *, env=None, cwd=None, data=None):
    return subprocess.run(cmd, cwd=cwd, env=env, input=data, text=True, capture_output=True, check=True)


class StopHooksTests(unittest.TestCase):
    def test_transcript_fallback_reads_last_assistant_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            transcript = pathlib.Path(temp) / "transcript.jsonl"
            transcript.write_text("\n".join([
                json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "old"}]}}),
                json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done — the workflow is fixed."}]}}),
            ]) + "\n")
            result = run(["python3", str(EVIDENCE)], data=json.dumps({"transcript_path": str(transcript)}))
            self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def test_claim_events_record_metadata_without_message_text(self):
        with tempfile.TemporaryDirectory() as temp:
            events = pathlib.Path(temp) / "events.jsonl"
            repo = pathlib.Path(temp) / "repo"
            repo.mkdir()
            run(["git", "init", "-q", "-b", "main"], cwd=repo)
            env = dict(os.environ, QA_GATE_EVENTS_FILE=str(events))
            messages = [
                {"cwd": str(repo), "runtime": "fixture-runtime", "provider": "fixture-provider",
                 "text": "Done — PRIVATE_MESSAGE_MUST_NOT_BE_LOGGED."},
                {"cwd": str(repo), "text": "Implemented; workflow NOT RUN; remaining: execute the workflow."},
                {"cwd": str(repo), "text": "Still working through the change."},
                {"cwd": str(repo), "runtime": "PRIVATE RUNTIME LABEL MUST NOT BE LOGGED",
                 "text": "Done."},
            ]
            decisions = []
            for payload in messages:
                result = run(["python3", str(EVIDENCE)], env=env, data=json.dumps(payload))
                decisions.append(json.loads(result.stdout)["decision"])
            self.assertEqual(decisions, ["block", "allow", "allow", "block"])
            rows = [json.loads(line) for line in events.read_text().splitlines()]
            self.assertEqual(len(rows), 3)
            self.assertEqual([row["decision"] for row in rows], ["block", "allow", "block"])
            self.assertEqual([row["claim"] for row in rows], ["done", "implemented", "done"])
            self.assertEqual(rows[0]["runtime"], "fixture-runtime")
            self.assertEqual(rows[0]["provider"], "fixture-provider")
            self.assertEqual(rows[0]["cwd"], str(repo.resolve()))
            self.assertEqual(rows[2]["runtime"], "")
            self.assertTrue(rows[0]["ts"])
            self.assertNotIn("PRIVATE_MESSAGE_MUST_NOT_BE_LOGGED", events.read_text())
            self.assertNotIn("PRIVATE RUNTIME LABEL MUST NOT BE LOGGED", events.read_text())

    def test_stop_hook_inventory_precedes_evidence_nudge(self):
        self.assert_stop_fixture("opted-in inventory row wins", opted_in=True, transcript=False,
                                 expected="[qa-sweep]", claim="Done — the workflow is fixed.")

    def test_stop_hook_nudges_without_repo_opt_in(self):
        self.assert_stop_fixture("default claim nudge", opted_in=False, transcript=False,
                                 expected="[qa-evidence]", claim="Done — the workflow is fixed.")

    def test_stop_hook_uses_transcript_when_last_message_is_missing(self):
        self.assert_stop_fixture("transcript fallback nudge", opted_in=False, transcript=True,
                                 expected="[qa-evidence]", claim="Done — the workflow is fixed.")

    def assert_stop_fixture(self, label, *, opted_in, transcript, expected, claim):
        with tempfile.TemporaryDirectory() as temp:
            home = pathlib.Path(temp) / "home"
            scripts = home / ".agents/skills/qa-sweep/scripts"
            scripts.mkdir(parents=True)
            shutil.copy2(EVIDENCE, scripts / "evidence-stop.py")
            shutil.copy2(SHIP, scripts / "ship-gate.py")
            repo = pathlib.Path(temp) / "repo"
            repo.mkdir()
            run(["git", "init", "-q", "-b", "main"], cwd=repo)
            if opted_in:
                qa = repo / ".qa"
                qa.mkdir()
                (qa / "config.json").write_text("{}\n")
                (qa / "inventory.jsonl").write_text(json.dumps({
                    "id": "fixture-row", "status": "open", "step": "fixture", "symptom": "fixture"}) + "\n")
            payload = {"cwd": str(repo), "last_assistant_message": claim}
            if transcript:
                path = pathlib.Path(temp) / "codex-rollout.jsonl"
                path.write_text(json.dumps({"type": "response_item", "payload": {
                    "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": claim}]
                }}) + "\n")
                payload.pop("last_assistant_message")
                payload["transcript_path"] = str(path)
            env = dict(os.environ, HOME=str(home))
            response = run(["sh", str(STOP)], env=env, data=json.dumps(payload))
            self.assertIn(expected, response.stdout, label)
            if opted_in:
                self.assertNotIn("[qa-evidence]", response.stdout, label)

    def test_codex_trust_only_updates_agent_hooks_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            home = pathlib.Path(temp)
            hooks_dir = home / ".agent-hooks"
            codex_dir = home / ".codex"
            hooks_dir.mkdir()
            codex_dir.mkdir()
            own = hooks_dir / "qa-stop-hook.sh"
            other = home / "third-party-hook.sh"
            own.write_text("#!/bin/sh\n")
            other.write_text("#!/bin/sh\n")
            hooks = codex_dir / "hooks.json"
            hooks.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": str(own), "timeout": 5},
                {"type": "command", "command": str(other), "timeout": 5},
            ]}]}}))
            config = codex_dir / "config.toml"
            config.write_text("")
            env = dict(os.environ, HOME=str(home))
            proc = run(["python3", str(TRUST), "--trust"], env=env)
            self.assertIn("SKIP untrusted hook outside ~/.agent-hooks", proc.stdout)
            state = subprocess.run(["python3", "-c", "import tomllib,sys;print(tomllib.load(open(sys.argv[1],'rb'))['hooks']['state'])", str(config)], capture_output=True, text=True, check=True).stdout
            parsed = ast.literal_eval(state)
            self.assertEqual(len(parsed), 1)
            self.assertIn("trusted_hash", next(iter(parsed.values())))


if __name__ == "__main__":
    unittest.main()
