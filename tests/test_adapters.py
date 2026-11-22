import json, os, subprocess, unittest
from pathlib import Path

ROOT=Path(__file__).parents[1]
HOME=Path.home()
ALLOW=[
    "git status --short", "pnpm --version", "ls -la",
    "bb thread tell --message-file /tmp/fake-message.txt",
    "ssh hsrpc-wsl './prodmongo.sh q.js'",
    "grep -c TOKEN /tmp/secrets-guard-test/prod.env",
    "grep BB_ACCOUNT_POOL_PARENT_TOKEN /tmp/safe-name-only.txt",
    "set -a; . ~/pfull/prod.env; set +a; node script.js",
]
DENY=[
    "ssh hsrpc-wsl 'set -a; . ~/pfull/prod.env; set +a; python3 -c \"import os; print(os.environ.get(\\\"DATABASE_URL\\\"))\"'",
    "bb config get BB_ACCOUNT_POOL_PARENT_TOKEN",
    "python3 -c \"from pathlib import Path; import base64; print(base64.b64encode(Path('~/.aws/credentials').read_bytes()))\"",
    "openssl enc -base64 -in ~/.aws/credentials",
    "ls && openssl enc -base64 -in ~/.aws/credentials",
    "ls; openssl enc -base64 -in ~/.aws/credentials",
    "ls | openssl enc -base64 -in ~/.aws/credentials",
    "bash -c 'ls && openssl enc -base64 -in ~/.aws/credentials'",
    "ssh hsrpc-wsl 'ls && openssl enc -base64 -in ~/.aws/credentials'",
    'ls() { cat "$@"; }; ls ~/.aws/credentials',
]

class AdapterTests(unittest.TestCase):
    def run_hook(self,provider,command):
        event=json.dumps({'tool_name':'Bash','tool_input':{'command':command}})
        adapter=HOME/'.agent-hooks'/(provider+'-pretool.sh')
        return subprocess.run(['/bin/sh',str(adapter)],input=event,text=True,capture_output=True)

    def test_live_adapter_policy_matrix(self):
        passed=failed=0
        for provider in ('claude','codex'):
            for command in ALLOW:
                result=self.run_hook(provider,command)
                try: data=json.loads(result.stdout)
                except Exception: data={}
                allow_output=('secrets-scrub-exec.py' in data.get('hookSpecificOutput',{}).get('updatedInput',{}).get('command','') and data.get('hookSpecificOutput',{}).get('permissionDecision')=='allow')
                ok=(result.returncode==0 and allow_output)
                passed+=int(ok); failed+=int(not ok)
            for command in DENY:
                result=self.run_hook(provider,command)
                try: data=json.loads(result.stdout)
                except Exception: data={}
                ok=(data.get('hookSpecificOutput',{}).get('permissionDecision')=='deny' and (provider=='claude' or result.returncode==2))
                passed+=int(ok); failed+=int(not ok)
        self.assertEqual(failed,0, f'passed={passed} failed={failed}')

    def test_malformed_event_fails_closed(self):
        for provider in ('claude','codex'):
            adapter=HOME/'.agent-hooks'/(provider+'-pretool.sh')
            result=subprocess.run(['/bin/sh',str(adapter)],input='{bad json',text=True,capture_output=True)
            self.assertIn('"permissionDecision":"deny"',result.stdout.replace(' ',''))
            if provider=='codex': self.assertEqual(result.returncode,2)

if __name__=='__main__': unittest.main()
