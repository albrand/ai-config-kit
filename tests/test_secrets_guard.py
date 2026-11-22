import importlib.util
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("guard", Path(__file__).parents[1] / "security/secrets-guard/guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

FAKE_ENV_BASE = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}


class GuardTests(unittest.TestCase):
    def test_incident_and_denials(self):
        for command in [
            "ssh hsrpc-wsl 'cd ~/pfull && node -e \"console.log(process.env.DATABASE_URL)\"'",
            "ssh hsrpc-wsl 'set -a; . ~/pfull/prod.env; set +a; python3 -c \"import os; print(os.environ.get(\\\"DATABASE_URL\\\"))\"'",
            "bb config get BB_ACCOUNT_POOL_PARENT_TOKEN",
            "bb variables dump",
            "echo $BB_ACCOUNT_POOL_PARENT_TOKEN",
            "env", "printenv", "set", "export -p", "declare -x",
            "cat ~/pfull/prod.env", "sed -n '1,20p' .env.local",
            "mongodb://fake:fake@host/db", "vercel env ls",
            "git config --get credential.helper",
        ]:
            self.assertTrue(guard.denied(command), command)

    def test_allowed(self):
        for command in [
            "ssh hsrpc-wsl 'cd ~/pfull && ./prodmongo.sh q.js'",
            "ssh hsrpc-wsl './prodmongo.sh q.js'",
            "set -a; . ~/pfull/prod.env; set +a; node script.js",
            "bb thread tell --message-file note.txt", "grep -c TOKEN .env",
            "grep BB_ACCOUNT_POOL_PARENT_TOKEN file", "git status", "pnpm lint", "ls -la",
        ]:
            self.assertFalse(guard.denied(command), command)

    def test_exact_output_scrubber(self):
        p=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        s=importlib.util.spec_from_file_location("scrubber",p); scrubber=importlib.util.module_from_spec(s); s.loader.exec_module(scrubber)
        fake="mongodb+srv://fake:fake@x"
        self.assertEqual(scrubber.redact(("out="+fake).encode(),[fake]),b"out=[MASKED]", "stdout exact-value redaction failed")
        self.assertEqual(scrubber.redact(("err="+fake).encode(),[fake]),b"err=[MASKED]", "stderr exact-value redaction failed")

    def test_env_parser_masks_expansions_and_unquoted_comments(self):
        p=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        s=importlib.util.spec_from_file_location("scrubber_env_parser",p); scrubber=importlib.util.module_from_spec(s); s.loader.exec_module(scrubber)
        values=scrubber.parse_env("FILLER=12345\nFAKE_TOKEN=\"prefix${FILLER}\"\nFAKE_COMMENT_TOKEN=synthetic-token-123 # comment\n")
        self.assertIn("prefix12345",values,"shell-expanded fake token was not collected")
        self.assertIn("synthetic-token-123",values,"comment-trimmed fake token was not collected")

    def test_remote_mask_fetch_requires_actual_ssh_command(self):
        p=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        s=importlib.util.spec_from_file_location("scrubber_ssh_detection",p); scrubber=importlib.util.module_from_spec(s); s.loader.exec_module(scrubber)
        self.assertTrue(scrubber.has_hsrpc_ssh("cd ~/pfull && ssh -p 22 hsrpc-wsl './prodmongo.sh q.js'"))
        self.assertTrue(scrubber.has_hsrpc_ssh("bash -c 'ssh hsrpc-wsl ./prodmongo.sh'"))
        self.assertFalse(scrubber.has_hsrpc_ssh("echo 'ssh hsrpc-wsl is only documentation'"))
        self.assertFalse(scrubber.has_hsrpc_ssh("# ssh hsrpc-wsl cat ~/pfull/prod.env\nls"))

    def test_scrubs_values_loaded_from_command_sourced_env_file(self):
        scrubber_path=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        spec=importlib.util.spec_from_file_location("scrubber_paths",scrubber_path)
        scrubber=importlib.util.module_from_spec(spec); spec.loader.exec_module(scrubber)
        fake="mongodb+srv://fake:fake@x"
        with tempfile.TemporaryDirectory(prefix="secrets-guard-fake-") as temp:
            env_file=Path(temp) / "prod.env"
            env_file.write_text("FAKE_DB_URI="+fake+"\n")
            self.assertEqual(set(scrubber.env_mask_paths("cd "+shlex.quote(temp)+" && . prod.env")),{str(env_file)})
            command=("set -a; . "+shlex.quote(str(env_file))+"; set +a; python3 -c "+
                     shlex.quote("import os; raise RuntimeError(os.environ['FAKE_DB_URI'])"))
            env=dict(FAKE_ENV_BASE,HOME=temp,TMPDIR=temp)
            result=subprocess.run([sys.executable,str(scrubber_path),"--",command],cwd=temp,capture_output=True,env=env)
        combined=result.stdout+result.stderr
        self.assertFalse(fake.encode() in combined,"fake sourced value survived output redaction")
        self.assertIn(b"RuntimeError: [MASKED]",combined)
        self.assertNotEqual(result.returncode,0)

    def test_scrubs_values_loaded_from_cwd_dotenv_by_the_application(self):
        scrubber=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        fake="fake-token-value-123456"
        with tempfile.TemporaryDirectory(prefix="secrets-guard-dotenv-") as temp:
            workdir=Path(temp) / "project"
            workdir.mkdir()
            (workdir / ".env").write_text("FAKE_TOKEN="+fake+"\n")
            app="import os; from pathlib import Path; os.environ.update(dict(line.split('=',1) for line in Path('.env').read_text().splitlines())); raise RuntimeError(os.environ['FAKE_TOKEN'])"
            command="cd "+shlex.quote(str(workdir))+" && python3 -c "+shlex.quote(app)
            env=dict(FAKE_ENV_BASE,HOME=temp,TMPDIR=temp)
            result=subprocess.run([sys.executable,str(scrubber),"--",command],cwd=temp,capture_output=True,env=env)
        combined=result.stdout+result.stderr
        self.assertFalse(fake.encode() in combined,"fake dotenv value survived output redaction")
        self.assertIn(b"RuntimeError: [MASKED]",combined)
        self.assertNotEqual(result.returncode,0)

    def test_scrubs_shell_expansion_and_comment_values_from_sourced_file(self):
        scrubber=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        expanded="prefix12345"
        commented="synthetic-token-123"
        with tempfile.TemporaryDirectory(prefix="secrets-guard-env-expansion-") as temp:
            env_file=Path(temp)/"prod.env"
            env_file.write_text('FILLER=12345\nFAKE_TOKEN="prefix${FILLER}"\nFAKE_COMMENT_TOKEN=synthetic-token-123 # fake comment\n')
            app="import os; print(os.environ['FAKE_COMMENT_TOKEN']); raise RuntimeError(os.environ['FAKE_TOKEN'])"
            command=("set -a; . "+shlex.quote(str(env_file))+"; set +a; python3 -c "+shlex.quote(app))
            env=dict(FAKE_ENV_BASE,HOME=temp,TMPDIR=temp)
            result=subprocess.run([sys.executable,str(scrubber),"--",command],cwd=temp,capture_output=True,env=env)
        combined=result.stdout+result.stderr
        self.assertFalse(expanded.encode() in combined,"expanded fake value survived redaction")
        self.assertFalse(commented.encode() in combined,"commented fake value survived redaction")
        self.assertEqual(combined.count(b"[MASKED]"),2,"expected stdout and stderr values to be masked")


if __name__ == "__main__":
    unittest.main()
