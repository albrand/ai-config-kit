"""The oracle names each shell as what runs, whatever version variables it inherits (Hermes 2026-10-07, r14)."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
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

    def test_user_startup_files_do_not_change_what_is_measured(self):
        # zsh sources $ZDOTDIR/.zshenv (default ~) even under -c; RC_QUOTES makes 'a''b' the word a'b, so a heredoc
        # delimited by <<'a''b' would end at a different line. BASH_ENV runs a file before any bash -c script.
        with tempfile.TemporaryDirectory() as home:
            Path(home, ".zshenv").write_text("setopt RC_QUOTES\n")
            Path(home, "bash_env").write_text("set -o posix\n")
            script = "cat <<'a''b'\nBODY\nab\necho RAN"
            # TMPPREFIX: zsh can write the heredoc here even in a sandboxed job, so the control differs only by RC_QUOTES
            hostile = {**os.environ, "HOME": home, "ZDOTDIR": home, "BASH_ENV": str(Path(home, "bash_env")),
                       "TMPPREFIX": str(Path(home, "zsh"))}
            control = subprocess.run(["/bin/zsh", "-c", script], capture_output=True, text=True, env=hostile)
            self.assertNotEqual(control.stdout, "BODY\nRAN\n")  # the startup file really changes the reading
            with patch.dict(os.environ, hostile):
                env = oracle.shell_env()
            self.assertEqual(subprocess.run(["/bin/zsh", "-c", script], capture_output=True, text=True,
                                            env=env).stdout, "BODY\nRAN\n")
            self.assertNotEqual(env["HOME"], home)
            posix = subprocess.run(["/bin/bash", "-c", 'echo ":$SHELLOPTS:"'], capture_output=True, text=True,
                                   env=hostile).stdout
            self.assertIn(":posix:", posix)  # control: BASH_ENV switches bash to POSIX mode
            self.assertNotIn(":posix:", subprocess.run(["/bin/bash", "-c", 'echo ":$SHELLOPTS:"'],
                                                       capture_output=True, text=True, env=env).stdout)

    def test_a_missing_shell_fails_naming_it(self):
        with self.assertRaises(SystemExit) as cm:
            oracle.shell_versions(("/bin/bash", "/bin/no-such-shell"))
        self.assertIn("BAD required shell missing: /bin/no-such-shell", str(cm.exception.code))


if __name__ == "__main__":
    unittest.main()
