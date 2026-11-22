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
        self.assertEqual(scrubber.redact(("out="+fake).encode(),[fake]),b"out=[MASKED]")
        self.assertEqual(scrubber.redact(("err="+fake).encode(),[fake]),b"err=[MASKED]")

    def test_scrubs_values_loaded_from_command_sourced_env_file(self):
        scrubber_path=Path(__file__).parents[1] / "security/secrets-guard/scrub-exec.py"
        spec=importlib.util.spec_from_file_location("scrubber_paths",scrubber_path)
        scrubber=importlib.util.module_from_spec(spec); spec.loader.exec_module(scrubber)
        fake="mongodb+srv://fake:fake@x"
        with tempfile.TemporaryDirectory(prefix="secrets-guard-fake-") as temp:
            env_file=Path(temp) / "prod.env"
            env_file.write_text("FAKE_DB_URI="+fake+"\n")
            self.assertEqual(scrubber.sourced_env_paths("cd "+shlex.quote(temp)+" && . prod.env"),[str(env_file)])
            command=("set -a; . "+shlex.quote(str(env_file))+"; set +a; python3 -c "+
                     shlex.quote("import os; raise RuntimeError(os.environ['FAKE_DB_URI'])"))
            result=subprocess.run([sys.executable,str(scrubber_path),"--",command],capture_output=True)
        combined=result.stdout+result.stderr
        self.assertNotIn(fake.encode(),combined)
        self.assertIn(b"RuntimeError: [MASKED]",combined)
        self.assertNotEqual(result.returncode,0)


if __name__ == "__main__":
    unittest.main()
