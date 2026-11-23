import json, shlex, subprocess, sys, unittest
from pathlib import Path
from os.path import expanduser

SCRIPT=Path(__file__).parents[1] / "security/secrets-guard/gemini-pretool.py"
SCRUBBER=expanduser('~/.agent-hooks/secrets-scrub-exec.py')

class GeminiAdapterTests(unittest.TestCase):
    def call(self,event):
        return subprocess.run([sys.executable,str(SCRIPT)],input=json.dumps(event),text=True,capture_output=True)
    def test_pre_tool_use_denials_and_scrubbed_allowed_commands(self):
        deny=["cat /tmp/secrets-guard-test/prod.env","echo $FAKE_TOKEN","ssh hsrpc-wsl 'cat ~/pfull/prod.env'"]
        allow=["ls -la","git status --short","echo 'fake-allowed-value'"]
        for command in deny:
            result=json.loads(self.call({'toolCall':{'name':'run_command','args':{'CommandLine':command}}}).stdout)
            self.assertEqual(result['decision'],'deny',command)
            self.assertNotIn('overwrite',result)
        for command in allow:
            result=json.loads(self.call({'toolCall':{'name':'run_command','args':{'CommandLine':command}}}).stdout)
            self.assertEqual(result['decision'],'allow',command)
            self.assertEqual(list(result['overwrite']),['CommandLine'])
            self.assertEqual(shlex.split(result['overwrite']['CommandLine']),['/usr/bin/python3',SCRUBBER,'--',command])
        # A tool that names the argument `command` gets that key rewritten.
        result=json.loads(self.call({'toolCall':{'name':'run_command','args':{'command':'ls'}}}).stdout)
        self.assertEqual(shlex.split(result['overwrite']['command']),['/usr/bin/python3',SCRUBBER,'--','ls'])
    def test_allowed_command_output_is_scrubbed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,".env").write_text("FAKE_SCRUB_TOKEN=fake-scrub-value-0123456789\n")
            result=json.loads(self.call({'toolCall':{'name':'run_command',
                'args':{'CommandLine':'printf "%s\\n" fake-scrub-value-0123456789'}}}).stdout)
            self.assertEqual(result['decision'],'allow')
            run=subprocess.run(['/bin/sh','-c',result['overwrite']['CommandLine']],cwd=directory,capture_output=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(run.stdout,b"[MASKED]\n")
    def test_malformed_input_fails_closed(self):
        for payload in ('{bad','{}','{"toolCall":{"args":{"CommandLine":7}}}'):
            result=subprocess.run([sys.executable,str(SCRIPT)],input=payload,text=True,capture_output=True)
            self.assertEqual(json.loads(result.stdout)['decision'],'deny',payload)

if __name__=='__main__': unittest.main()
