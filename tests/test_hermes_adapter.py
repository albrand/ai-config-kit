import json
import subprocess
import sys
import unittest
from pathlib import Path

ADAPTER = Path(__file__).parents[1] / "security/secrets-guard/hermes-pretool.py"


class HermesAdapterTests(unittest.TestCase):
    def call_hook(self, payload):
        return subprocess.run(
            [sys.executable, str(ADAPTER)],
            input=payload,
            text=True,
            capture_output=True,
        )

    def test_terminal_secret_shapes_are_blocked_and_safe_commands_continue(self):
        for command in (
            "cat /tmp/secrets-guard-test/prod.env",
            "echo $FAKE_TOKEN",
            "ssh hsrpc-wsl 'cat /tmp/secrets-guard-test-20261122/prod.env'",
        ):
            result = self.call_hook(json.dumps({"tool_name": "terminal", "tool_input": {"command": command}}))
            self.assertEqual(json.loads(result.stdout)["decision"], "block", command)

        result = self.call_hook(json.dumps({"tool_name": "terminal", "tool_input": {"command": "ls -la"}}))
        self.assertEqual(json.loads(result.stdout), {})

    def test_direct_credential_file_reads_and_internal_errors_are_blocked(self):
        result = self.call_hook(json.dumps({"tool_name": "read_file", "tool_input": {"path": "/tmp/secrets-guard-test/prod.env"}}))
        self.assertEqual(json.loads(result.stdout)["decision"], "block")
        result = self.call_hook("{bad")
        self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def decision(self, tool, args):
        result = self.call_hook(json.dumps({"tool_name": tool, "tool_input": args}))
        return json.loads(result.stdout).get("decision", "allow")

    def test_content_search_of_credential_files_is_blocked_but_name_search_continues(self):
        self.assertEqual(self.decision("search_files", {"pattern": "TOKEN", "path": "/tmp/fake/prod.env"}), "block")
        self.assertEqual(self.decision("search_files", {"pattern": ".", "path": "/tmp/fake", "file_glob": "*.env"}), "block")
        self.assertEqual(self.decision("search_files", {"pattern": "*.env", "target": "files", "path": "/tmp/fake"}), "allow")
        self.assertEqual(self.decision("search_files", {"pattern": "def main", "path": "/tmp/fake"}), "allow")

    def test_execute_code_secret_reads_are_blocked_and_ordinary_code_continues(self):
        for code in (
            "print(open('/tmp/fake/prod.env').read())",
            "from pathlib import Path\nprint(Path('/tmp/fake/.env').read_text())",
            "import os\nprint(os.environ['FAKE_TOKEN'])",
            "import os\nprint(dict(os.environ))",
            "import subprocess\nsubprocess.run(['cat', '/tmp/fake/credentials.json'])",
        ):
            self.assertEqual(self.decision("execute_code", {"code": code}), "block", code)
        for code in (
            "print('it\\'s fine'); x = \"a 'quoted' value\"",
            "import os\nprint(os.environ.get('HOME'))",
            "print(sum(range(10)))",
        ):
            self.assertEqual(self.decision("execute_code", {"code": code}), "allow", code)

    def test_text_written_to_a_running_process_is_guarded(self):
        self.assertEqual(self.decision("process", {"action": "submit", "session_id": "p1", "data": "cat /tmp/fake/prod.env"}), "block")
        self.assertEqual(self.decision("process", {"action": "submit", "session_id": "p1", "data": "ls -la"}), "allow")
        self.assertEqual(self.decision("process", {"action": "poll", "session_id": "p1"}), "allow")


if __name__ == "__main__":
    unittest.main()
