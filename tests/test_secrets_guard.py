import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("guard", Path(__file__).parents[1] / "security/secrets-guard/guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardTests(unittest.TestCase):
    def test_incident_and_denials(self):
        for command in [
            "ssh hsrpc-wsl 'cd ~/pfull && node -e \"console.log(process.env.DATABASE_URL)\"'",
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
            "set -a; . ~/pfull/prod.env; set +a; node script.js",
            "bb thread tell --message-file note.txt", "grep -c TOKEN .env",
            "grep BB_ACCOUNT_POOL_PARENT_TOKEN file", "git status", "pnpm lint", "ls -la",
        ]:
            self.assertFalse(guard.denied(command), command)


if __name__ == "__main__":
    unittest.main()
