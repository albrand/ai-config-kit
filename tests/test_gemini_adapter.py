import json, subprocess, sys, unittest
from pathlib import Path
from os.path import expanduser

SCRIPT=Path(expanduser('~/.agent-hooks/gemini-pretool.py'))

class GeminiAdapterTests(unittest.TestCase):
    def call(self,event):
        return subprocess.run([sys.executable,str(SCRIPT)],input=json.dumps(event),text=True,capture_output=True)
    def test_before_tool_denials_and_allowed_commands(self):
        deny=["cat /tmp/secrets-guard-test/prod.env","echo $FAKE_TOKEN","ssh hsrpc-wsl 'cat ~/pfull/prod.env'"]
        allow=["ls -la","git status --short"]
        for command in deny:
            result=self.call({'toolCall':{'name':'run_command','args':{'CommandLine':command}}})
            self.assertEqual(json.loads(result.stdout)['decision'],'deny',command)
        for command in allow:
            result=self.call({'toolCall':{'name':'run_command','args':{'CommandLine':command}}})
            self.assertEqual(json.loads(result.stdout)['decision'],'ask',command)
    def test_malformed_input_fails_closed(self):
        result=subprocess.run([sys.executable,str(SCRIPT)],input='{bad',text=True,capture_output=True)
        self.assertEqual(json.loads(result.stdout)['decision'],'deny')

if __name__=='__main__': unittest.main()
