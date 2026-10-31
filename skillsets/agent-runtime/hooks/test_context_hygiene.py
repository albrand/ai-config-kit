"""Tests for context-hygiene-policy.py. Run: python3 -m unittest skillsets/agent-runtime/hooks/test_context_hygiene.py"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

POLICY = Path(__file__).with_name("context-hygiene-policy.py")


def verdict(payload, env=None):
    p = subprocess.run([sys.executable, str(POLICY)], input=json.dumps(payload), capture_output=True, text=True,
                       env={**os.environ, **(env or {})}, timeout=30)
    return json.loads(p.stdout)


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


BIG_HEREDOC = "python3 - <<'EOF'\n" + "\n".join(f"print({i}, '{'x' * 80}')" for i in range(20)) + "\nEOF"


class ContextHygiene(unittest.TestCase):
    def test_heredoc_message_is_guidance_with_a_way_forward(self):
        v = verdict(bash(BIG_HEREDOC))
        self.assertTrue(v["block"])
        self.assertIn("Not a safety rule", v["reason"])
        self.assertIn("carry on", v["reason"])
        self.assertNotIn("Bypass", v["reason"])

    def test_its_own_remedy_is_allowed(self):
        self.assertFalse(verdict(bash("cat > /tmp/x.py <<'EOF'\n" + BIG_HEREDOC.split("\n", 1)[1]))["block"])

    def test_codex_argv_form_is_checked(self):
        v = verdict({"tool_name": "shell", "tool_input": {"command": ["/bin/zsh", "-lc", BIG_HEREDOC]}})
        self.assertTrue(v["block"])

    def test_unbounded_read_message(self):
        f = Path(tempfile.mkdtemp()) / "big.txt"
        f.write_text("x" * 20_000)
        v = verdict({"tool_name": "Read", "tool_input": {"file_path": str(f)}})
        self.assertTrue(v["block"])
        self.assertIn("Not a safety rule", v["reason"])
        self.assertFalse(verdict({"tool_name": "Read", "tool_input": {"file_path": str(f), "limit": 50}})["block"])

    def test_pgrep_full_match_is_blocked_plain_pgrep_is_allowed(self):
        blocked = (
            "pgrep -f bb",
            "sudo pgrep -f bb",
            "sudo -u alice pgrep -f bb",
            "env -u FOO pgrep -f bb",
            "env FOO=1 pgrep --full bb",
            "true && pgrep -f bb",
            "true && sudo -u bob pgrep -f x",
            "if pgrep -f bb; then echo hi; fi",
            "if pgrep -f x; then :; fi",
            "pgrep \\\n-f bb",
            'P=pgrep; "$P" -f bb',
            "p''grep -f bb",
            'p"g"rep -f bb',
            "pgrep '-f' bb",
            'pgrep "--full" bb',
            r"pgrep \-f node",
            r"p\grep -f bb",
            'P=/usr/bin/pgrep; "$P" -f bb',
            'F=-f; pgrep "$F" bb',
            "CMD='pgrep -f bb'; $CMD",
            "pgrep -l -f node",
            "pgrep -af node",
            "bash -c 'pgrep -f bb'",
            "echo $(pgrep -f bb)",
            'echo "$(pgrep -f bb)"',
            "/usr/bin/pgrep --full=bb.app",
            "xargs pgrep -f < f",
        )
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))
                self.assertIn("pgrep -x NAME", v["reason"])
        allowed = ("pgrep bb", "pgrep -x bb", "pgrep -l node", "pkill -f bb")
        for cmd in allowed[:-1]:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd))["block"], cmd)
        self.assertTrue(verdict(bash(allowed[-1]))["block"])

    def test_pgrep_f_mentions_in_quoted_data_are_allowed(self):
        allowed = (
            "printf '%s\n' 'The pgrep -f option is prohibited here'",
            'echo "never use pgrep -f"',
            'git commit -m "block pgrep -f in hooks"',
            "grep -n 'pgrep -f' file.py",
            "echo harmless pgrep -f bb",
            "printf '%s %s\n' x 'pgrep -f'",
            "echo a b pgrep --full c",
            "grep -rn pgrep -f .",
            "grep pgrep -f file.txt",
        )
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd)

    def test_bb_lifecycle_stays_a_safety_block_even_when_hygiene_is_off(self):
        # The fixture is only fed to the policy as data; nothing here runs it.
        quit_bb = "osascript -e 'tell application " + '"bb"' + " to quit'"
        v = verdict(bash(quit_bb), env={"CONTEXT_HYGIENE": "off"})
        self.assertTrue(v["block"])
        self.assertTrue(v["reason"].startswith("[bb-lifecycle]"))
        self.assertNotIn("Not a safety rule", v["reason"])

    def test_the_electron_cache_that_fork_stage_installs_from_is_never_deleted(self):
        # A seahaven session freeing disk (2026-10-28 14:17Z) ran the first of these; the next bb install
        # (i31) then refused with "no cached electron-v44.9.3-darwin-arm64.zip". The fixtures are data only.
        for cmd in ("rm -rf ~/Library/Caches/com.tidal.desktop.ShipIt/* ~/Library/Caches/electron/* "
                    "~/Library/Caches/node-gyp/*",
                    "rm -r ~/Library/Caches/node-gyp ~/Library/Caches/electron ~/Library/Caches/pnpm",
                    'rm -rf "$HOME/Library/Caches/electron-builder"',
                    "rm -rf ~/Library/Caches/*",
                    "cd /tmp && rm -rf ~/Library/Caches/",
                    "rm -rf ~/Library/Caches",
                    'rm -rf "$HOME/Library/Caches"; df -h',
                    "find ~/Library/Caches/electron -mindepth 1 -delete",
                    "find ~/Library/Caches -name '*.zip' -delete",
                    "find ~/Library/Caches/electron -type f -exec rm {} +",
                    "find ~/Library/Caches/electron/* -mindepth 1 -delete",
                    "find ~/Library/Caches/electron/*/ -type f -exec rm {} +",
                    "find ~/Library/Caches/* -name '*.zip' -delete",
                    "cd ~/Library/Caches/electron && find . -mindepth 1 -delete",
                    "cd ~/Library/Caches && rm -rf electron",
                    'cd "$HOME/Library/Caches/electron"; rm -rf ./*',
                    "cd ~/Library/Caches && rm -rf ./*",
                    "cd ~/Library/Caches && find . -mindepth 1 -delete",
                    "cd ~/Library/Caches && find electron -mindepth 1 -delete",
                    "cd ~/Library/Caches && find ./electron -type f -exec rm {} +",
                    "mv ~/Library/Caches/electron /tmp/old-electron"):
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"])
                self.assertTrue(v["reason"].startswith("[electron-cache]"))
        # Other caches stay deletable, and reading the Electron cache is fine.
        for cmd in ("rm -rf ~/Library/Caches/node-gyp ~/Library/Caches/pnpm",
                    "rm -rf ~/Library/Caches/electronic-music-app",
                    "ls -la ~/Library/Caches/electron/",
                    "du -sh ~/Library/Caches/electron",
                    "find ~/Library/Caches/electron -name '*.zip'",
                    "find ~/Library/Caches/pnpm -mindepth 1 -delete",
                    "find ~/Library/Caches/pnpm/* -mindepth 1 -delete",
                    "cd ~/Library/Caches/pnpm && rm -rf ./*",
                    "cd ~/Library/Caches/electron && ls -la",
                    "cd ~/Library/Caches && rm -rf pnpm node-gyp"):
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd))["block"])


if __name__ == "__main__":
    unittest.main()
