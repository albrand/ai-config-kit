"""The oracle names each shell as what runs, whatever version variables it inherits (Hermes 2026-10-07, r14)."""
import importlib.util
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("shell_oracle", Path(__file__).resolve().parents[1] / "shell_oracle.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
BOGUS = {"ZSH_VERSION": "bogus", "BASH_VERSION": "bogus", "KSH_VERSION": "bogus", "SHELLOPTS": "posix",
         "BASH_ENV": "/nonexistent", "ENV": "/nonexistent"}


class ShellIdentityTests(unittest.TestCase):
    def test_inherited_version_variables_do_not_change_the_identity(self):
        clean = {s: oracle.identify(s) for s in oracle.SHELLS}
        with patch.dict(os.environ, BOGUS):
            for s in oracle.SHELLS:
                self.assertEqual(oracle.identify(s), clean[s], s)
                self.assertNotIn("bogus", oracle.identify(s), s)

    def test_each_shell_is_named_as_itself_under_conflicting_variables(self):
        with patch.dict(os.environ, BOGUS):
            self.assertRegex(oracle.identify("/bin/bash"), r"^/bin/bash( -> \S+)? is bash \d")
            self.assertNotIn("POSIX mode", oracle.identify("/bin/bash"))  # an inherited SHELLOPTS=posix is ignored
            self.assertRegex(oracle.identify("/bin/zsh"), r"^/bin/zsh( -> \S+)? is zsh \d")
            self.assertRegex(oracle.identify("/bin/dash"), r"^/bin/dash( -> \S+)? is dash \(reports no version")

    def test_measurement_shells_ignore_inherited_shell_state(self):
        with patch.dict(os.environ, BOGUS):
            env = oracle.shell_env()
        self.assertFalse(set(oracle.SHELL_STATE) & set(env))
        r = subprocess.run(["/bin/bash", "-c", 'echo "$BASH_VERSION :$SHELLOPTS:"'], capture_output=True, text=True,
                           env=env)
        self.assertNotIn(":posix:", r.stdout.replace(" :", ":"))  # bash measured as bash, not in POSIX mode
        self.assertNotIn("bogus", r.stdout)

    def test_a_missing_shell_fails_naming_it(self):
        with self.assertRaises(SystemExit) as cm:
            oracle.shell_versions(("/bin/bash", "/bin/no-such-shell"))
        self.assertIn("BAD required shell missing: /bin/no-such-shell", str(cm.exception.code))


if __name__ == "__main__":
    unittest.main()
