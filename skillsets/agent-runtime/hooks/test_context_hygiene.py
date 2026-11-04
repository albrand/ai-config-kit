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
            "P=/usr/bin/pgrep; $P -f bb",
            'F=-f; pgrep "$F" bb',
            "CMD='pgrep -f bb'; $CMD",
            "pgrep -l -f node",
            "pgrep -af node",
            "bash -c 'pgrep -f bb'",
            "bash -c 'pgrep -f x'",
            "echo $(pgrep -f bb)",
            'echo "$(pgrep -f bb)"',
            'echo "`pgrep -f bb`"',
            "x=$(pgrep -f bb)",
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
            "printf '%s' '$(pgrep -f)'",
            "echo 'x `pgrep -f y` z'",
            "echo '$(pgrep --full a)'",
        )
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd)

    def test_pgrep_invocation_routes_use_command_position(self):
        allowed = (
            'P=pgrep; echo "$P" -f bb',
            "P=pgrep; printf '%s\\n' $P -f",
            'F=-f; echo pgrep "$F" x',
            "bash -c 'echo pgrep -f x'",
        )
        blocked = (
            'P=pgrep; "$P" -f bb',
            "P=/usr/bin/pgrep; $P -f bb",
            'F=-f; pgrep "$F" bb',
            "bash -c 'pgrep -f x'",
        )
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd)
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_pgrep_assignment_bindings_ignore_quoted_data(self):
        allowed = (
            "printf 'P=pgrep'; P=echo; $P -f",
            "P=pgrep; P=echo; $P -f x",
            "echo 'F=-f'; pgrep x",
        )
        blocked = (
            "P=echo; P=pgrep; $P -f x",
            "P=pgrep; $P -f",
            "F=-f; pgrep $F x",
        )
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd)
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_pgrep_heredoc_bodies_are_data_unless_shell_stdin(self):
        allowed = (
            "cat <<'EOF' > f.md\nNever use pgrep -f\nEOF",
            "cat > AGENTS.md <<EOF\n- Never use pkill or pgrep -f; a safety-hook block is final.\nEOF",
            "tee x <<-EOF\n\tpgrep -f y\n\tEOF",
            "S=/tmp; cat >> $S/n.md <<'EOF'\nthe hook blocks killall bb and pkill -f bb\nEOF",
            "cat > /tmp/b.md <<EOF\nplain text about killall bb\nEOF",
        )
        blocked = (
            "bash <<'EOF'\npgrep -f bb\nEOF",
            "ssh h <<EOF\npgrep -f bb\nEOF",
            "cat <<EOF\nx\nEOF\npgrep -f bb",
        )
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd)
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_pgrep_data_heredoc_backslash_lines_stay_fast_at_depth_20000(self):
        import time

        n = 20000
        cmd = "cat <<'EOF'\n" + "x \\n" * n + "EOF\n"
        t0 = time.monotonic()
        v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 8.0)
        self.assertFalse(v["block"], cmd[:48])

    def test_top_level_case_scan_many_case_stays_fast_at_200k(self):
        import time

        pk = "p" + "kill"
        n = 200_000
        k = n // 22
        cmd = ("case x in y) :;; esac; " * k) + f"case x in x) {pk} node;; esac"
        t0 = time.monotonic()
        v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 2.0)
        self.assertTrue(v["block"], cmd[:48])

    def test_pgrep_data_heredoc_trailing_backslash_not_shell_fault(self):
        # echo x + backslash-newline + pgrep: joined echo args (main parity).
        data_hd = "cat > f.md <<'EOF'\nline \\\\\nno pgrep -f here\nEOF"
        allowed = (
            data_hd,
            data_hd + "\necho ok",
            'echo x \
pgrep -f bb',
        )
        blocked = (
            "bash <<'EOF'\nline \\\\\npgrep -f x\nEOF",
        )
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_pgrep_prefix_assignments_do_not_persist_across_commands(self):
        allowed = (
            "P=echo; P=pgrep echo; $P -f x",
            "P=pgrep true; $P -f x",
        )
        blocked = (
            "P=pgrep; $P -f x",
            "P=pgrep F=-f; $P $F x",
            "P=x pgrep -f y",
        )
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd)
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_pgrep_wrappers_skip_to_real_command_word(self):
        blocked = (
            "timeout 5 pgrep -f worker",
            "timeout -s KILL 10s pgrep -f w",
            "nice -n 5 pgrep -f w",
            "ionice -c3 pgrep -f w",
            "stdbuf -oL pgrep -f w",
            "flock /tmp/l pgrep -f w",
            "setsid pgrep -f w",
            "watch -n 1 'pgrep -f w'",
            "sudo timeout 5 nice -n 5 pgrep -f x",
        )
        allowed = (
            "timeout 5 pgrep -x worker",
            "nice -n 5 echo pgrep -f",
            "timeout 5 grep -n 'pgrep -f' f",
        )
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd)

    def test_pgrep_command_launch_arguments(self):
        blocked = (
            r"find . -exec pgrep -f worker \;",
            "find . -execdir pgrep -f w {} +",
            "parallel pgrep -f ::: a b",
            "su root -c 'pgrep -f w'",
            "script -q -c 'pgrep -f w' /dev/null",
            "chroot /srv pgrep -f w",
            "strace -f pgrep -f w",
        )
        allowed = (
            "find . -name '*pgrep -f*'",
            r"find . -exec grep -l 'pgrep -f' {} \;",
            "strace -f ls",
        )
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd)

    def test_pgrep_ssh_quoted_remote_shell_blocks_in_any_command_position(self):
        blocked = (
            "for i in 1; do ssh h 'pgrep -f x' || break; done",
            "timeout 30 ssh vps 'uptime; pgrep -a -f bb | head'",
            "out=$(ssh h 'cat f; pgrep -fa x >/dev/null && echo R')",
            "while true; do ssh h 'pgrep -f x' >/dev/null || break; done",
            "if ssh h 'pgrep -f x'; then :; fi",
            "true && sudo ssh h 'pgrep -f x'",
            "x=`ssh h 'pgrep -f x'`",
        )
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_pgrep_ssh_script_quotes_block_inside_shell_grouping(self):
        blocked = (
            "f() { ssh h 'pgrep -f x'; }",
            "procs(){ ssh h 'for p in $(pgrep -f \"a b\"); do echo $p; done'; }; procs",
            "function f { ssh h 'pgrep -f x'; }",
            "{ ssh h 'pgrep -f x'; }",
            "! ssh h 'pgrep -f x'",
            "case a in a) ssh h 'pgrep -f x';; esac",
        )
        for cmd in blocked:
            with self.subTest(cmd=cmd[:48]):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_pgrep_nested_dollar_paren_depth_400_still_blocks_tail_kill(self):
        import time

        tail = "; p" + "kill node"
        cmd = "echo " + "$(" * 400 + "x" + ")" * 400 + tail
        t0 = time.monotonic()
        v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 2.0)
        self.assertTrue(v["block"])
        self.assertTrue(
            v["reason"].startswith("[no-pgrep-f]") or v["reason"].startswith("[bb-lifecycle]")
        )

    def test_pgrep_deep_dollar_paren_and_bash_c_nesting_still_blocks_pkill(self):
        import time

        tail = "; p" + "kill node"
        for cmd in (
            "echo " + "$(" * 1000 + "x" + ")" * 1000 + tail,
            'bash -c "' + "$(" * 1000 + "x" + ")" * 1000 + tail + '"',
        ):
            with self.subTest(cmd=cmd[:40]):
                t0 = time.monotonic()
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                elapsed = time.monotonic() - t0
                self.assertLess(elapsed, 2.0)
                self.assertTrue(v["block"])
                self.assertTrue(
                    v["reason"].startswith("[no-pgrep-f]")
                    or v["reason"].startswith("[bb-lifecycle]")
                )

    def test_pgrep_executable_quote_scan_stays_linear_and_keeps_long_ssh_blocks(self):
        import time

        loop_cmd = "for i in 1; do ssh h 'echo'; done; " * 2400
        t0 = time.monotonic()
        v = verdict(bash(loop_cmd), env={"CONTEXT_HYGIENE": "off"})
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 2.0)
        self.assertFalse(v["block"], loop_cmd[:48])

        long_ssh = "ssh h " + "-o A=b " * 200 + "'pgrep -f x'"
        v = verdict(bash(long_ssh), env={"CONTEXT_HYGIENE": "off"})
        self.assertTrue(v["block"], long_ssh[:48])
        self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_pgrep_dense_inputs_finish_within_deadline(self):
        import time

        cases = (
            (False, "echo " + " ".join(["pgrep"] * 1800)),
            (True, "; ".join(["pgrep -f x"] * 600)),
            (False, "echo " + " ".join(["'pgrep -f'"] * 1500)),
            (False, "echo " + " ".join(["'pgrep -f'"] * 6000)),
        )
        for want_block, cmd in cases:
            with self.subTest(cmd=cmd[:48]):
                t0 = time.monotonic()
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                elapsed = time.monotonic() - t0
                self.assertLess(elapsed, 2.0)
                self.assertEqual(v["block"], want_block)

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

    def test_pgrep_argv_parsing_distinguishes_full_match_flag(self):
        blocked = (
            "pgrep -f node",
            "pgrep --full node",
            "pgrep -af node",
            "pgrep -lf node",
            "pgrep -u 1 -f x",
            "pgrep --list-full -f node",
            "pgrep -d , -f worker",
            "pgrep -d -f -f worker",
            "pgrep -f worker",
            "P=pgrep; $P -d , -f w",
            "ssh h 'pgrep -d , -f w'",
        )
        allowed = (
            "pgrep --list-full node",
            "pgrep --pidfile /tmp/p",
            "pgrep -x -- -f",
            "pgrep --list-name node",
            "pgrep -F /tmp/pid",
            "pgrep -a node",
            "pgrep -l node",
            "pgrep --signal TERM node",
            "pgrep --ns 1 node",
            "pgrep --cgroup a node",
            "pgrep -A node",
            "pgrep --ignore-ancestors node",
            "pgrep -d -f worker",
            "pgrep --delimiter -f worker",
            "pgrep -u -f x",
            "pgrep -g -f x",
            "pgrep -G -f x",
            "pgrep -P -f x",
            "pgrep -s -f x",
            "pgrep -t -f x",
            "pgrep -U -f x",
            "pgrep -F -f x",
            "pgrep --signal -f x",
            'pgrep -d "-f" w',
            "P=pgrep; $P -d -f w",
            "ssh h 'pgrep -d -f w'",
            "pgrep -d, worker",
        )
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd)

    def test_pgrep_scanner_heredoc_hash_comment_bodies(self):
        allowed = (
            "cat <<E\n# pgrep -f x\nE\ntrue",
        )
        blocked = (
            "cat <<E\n# not a comment\nE\npgrep -f x",
            "cat <<'E'\n# x\nE\npgrep -f x",
            "cat <<E\nx # y\nE\npgrep -f x",
            "cat > f <<E\n#!/bin/sh\nE\npgrep -f x",
            "cat <<E\n# c\nE\npkill node",
        )
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd)
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                if "pgrep" in cmd:
                    self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_hook_gaps_followup_unquoted_ssh_heredoc_pkill_comment(self):
        blocked = (
            "ssh host pgrep -f worker",
            "ssh -o A=b host pgrep -f w",
            "ssh -p 22 host pgrep -f w",
            "ssh -i k host pgrep -f w",
            "ssh -l u host pgrep -f w",
            "ssh -J j host pgrep -f w",
            "ssh -p 22 -i k u@h pgrep -f w",
            "cat <<E | sh\npgrep -f x\nE",
            "cat <<E | bash -s\npgrep -f x\nE",
            "cat <<E | ssh h\npgrep -f x\nE",
            "true # c\npkill node",
            "echo '#'; pkill node",
        )
        allowed = (
            "ssh host echo pgrep -f w",
            "cat <<E | grep x\npgrep -f x\nE",
            "true # note; pkill node",
        )
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd)

    def test_pgrep_mask_deep_dollar_paren(self):
        pk = "p" + "kill"

        def deep_cmd(depth, body, tail):
            return "$(" * depth + body + ")" * depth + "; " + tail

        for body in ("echo '#'", 'echo "#"', "true # c"):
            cmd = deep_cmd(500, body, pk + " node")
            with self.subTest(depth=500, body=body):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd[:80])
                self.assertTrue(v["reason"].startswith("[bb-lifecycle]"), v["reason"][:40])
        cmd1k = deep_cmd(1000, "echo '#'", pk + " node")
        v = verdict(bash(cmd1k), env={"CONTEXT_HYGIENE": "off"})
        self.assertTrue(v["block"])
        pgrep_cmd = deep_cmd(1000, "echo '#'", "pgrep -f x")
        v2 = verdict(bash(pgrep_cmd), env={"CONTEXT_HYGIENE": "off"})
        self.assertTrue(v2["block"])
        self.assertTrue(v2["reason"].startswith("[no-pgrep-f]"))

    def test_pgrep_deep_dollar_paren_comment_mask_stays_fast_at_depth_5000(self):
        import time

        pk = "p" + "kill"
        cmd = "$(" * 5000 + "echo '#'" + ")" * 5000 + "; " + pk + " node"
        t0 = time.monotonic()
        v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 8.0)
        self.assertTrue(v["block"])

    def test_pgrep_heredoc_pipe_env_shell(self):
        cmd = "cat <<E | env sh\npgrep -f x\nE"
        v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
        self.assertTrue(v["block"], cmd)
        self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_pgrep_heredoc_opener_line_pipe_respects_comments(self):
        allowed = (
            'cat <<E # note | sh\npgrep -f x\nE',
            'cat <<E # | bash\npgrep -f x\nE',
            "cat <<E '|' sh\npgrep -f x\nE",
        )
        blocked = (
            'cat <<E | sh # c\npgrep -f x\nE',
            "cat <<'E' | sh\npgrep -f x\nE",
            'cat <<E | sh\npgrep -f x\nE',
            'cat <<E | sh\necho a#b\npgrep -f x\nE',
        )
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd)
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_pgrep_scanner_respects_shell_comments(self):
        allowed = (
            "true # note; pgrep -f worker",
            "ls # pgrep -f",
            "x=1 # c; pgrep -f x",
            "bash -c 'true # c; pgrep -f x'",
            "ssh h 'true # c; pgrep -f x'",
        )
        blocked = (
            "echo '#'; pgrep -f x",
            'echo "#"; pgrep -f x',
            "echo a#b; pgrep -f x",
            "echo ${#x}; pgrep -f x",
            "echo $#; pgrep -f x",
            "echo \\#; pgrep -f x",
            "x=1 # c\npgrep -f x",
            "true #c\npgrep -f x",
            "ssh h 'true # c\npgrep -f x'",
        )
        for cmd in allowed:
            with self.subTest(cmd=cmd):
                self.assertFalse(verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd)
        for cmd in blocked:
            with self.subTest(cmd=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))


    def test_guard_followups_2_ssh_pkill_quoted_grep_subst_fault(self):
        pk = "p" + "kill"
        blocked = (
            f"ssh host {pk} node",
            f"ssh -p 22 host {pk} -f x",
            "ssh host 'pgrep -f x'",
            'ssh host "pgrep -f x"',
            "ssh host bash -c 'pgrep -f x'",
            'ssh host sh -c "pgrep -f x"',
            "ssh -p 22 host bash -lc 'pgrep -f x'",
            f"$(true # c\n); {pk} node",
            f'echo "$(true; {pk} node)"',
            f"`true; {pk} node`",
            'echo "it\'s"; pgrep -f x',
            "cat <<'EOF'\nIt's\nEOF\n" + pk + " node",
            "echo 'unterminated\npgrep -f bb",
            "echo 'pgrep -f bb\npgrep -f bb",
            'echo "pgrep -f bb\npgrep -f bb',
        )
        allowed = (
            "cat <<EOF\nline\npgrep -f bb",
            "echo \\\npgrep -f bb",
            f"ssh host echo {pk} node",
            "ssh host grep -n 'pgrep -f' f",
            f'echo "$(true # note; {pk} node\n)"',
            f"x=$(true # c; {pk} node\n)",
            "cat > /tmp/r.md <<'EOF'\nIt's done; never use pgrep -f here.\nEOF\necho ok",
            f"bb thread tell t --message-file - <<'EOF'\nDon't run {pk} node.\nEOF",
            "printf '%s\\n' \"note: don't use pgrep -f (it's banned)\"",
            "sed -e 's/a/b/' -e 's/single-quote cases/x/' f; echo \"avoid pgrep -f\"",
            '{ echo "2026 notes: it\'s fine, no ' + pk + '"; } >> log',
            'L="SC4 it\'s ok"; echo "$L pgrep -f is banned"',
            'git commit -m "Don\'t use pgrep -f"',
            'echo "don\'t"; echo \'never pgrep -f\'',
        )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:60]):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
        for cmd in allowed:
            with self.subTest(allowed=cmd[:60]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )




    def test_pgrep_unterminated_data_heredoc_delimiter_suffix_allows_body(self):
        cmd = "cat <<EOF\nline \\nno pgrep -f\nEOF; echo ok"
        self.assertFalse(
            verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
        )

    def test_pgrep_interpreter_stdin_heredoc_scans_dollar_paren(self):
        cmd = (
            "python3 -I - <<'EOF'\n"
            '"w=$(ssh h \'cat f; pgrep -fa x >w && w R\')",\n'
            "EOF"
        )
        v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
        self.assertTrue(v["block"], cmd)
        self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_pgrep_r12_expandable_data_heredoc_substitutions(self):
        pg = "p" + "grep"
        pk = "p" + "kill"
        blocked = (
            f"cat <<EOF\n$({pg} -f x)\nEOF",
            f"cat <<EOF\n`{pg} -f x`\nEOF",
            f"cat > f <<EOF\nnote $({pk} node)\nEOF",
            f"tee f <<EOF\n`{pk} node`\nEOF",
            f"cat <<EOF\n$(echo a; {pg} -f x)\nEOF",
        )
        allowed = (
            f"cat <<'EOF'\n$({pg} -f x)\nEOF",
            f'cat <<"EOF"\n`{pg} -f x`\nEOF',
            f"cat <<\\EOF\n$({pg} -f x)\nEOF",
            "cat <<EOF\nnever use pgrep -f here\nEOF",
            f"cat <<EOF\n\\$({pg} -f x) is escaped\nEOF",
            f"python3 - <<'EOF'\nprint('$({pg} -f x)')\nEOF",
        )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:60]):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
        for cmd in allowed:
            with self.subTest(allowed=cmd[:60]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_pgrep_interpreter_stdin_heredoc_comment_and_lone_quote_allowed(self):
        allowed = (
            "python <<''\n#$(pgrep-f \n",
            "python <<''\n'$(pgrep-f \n",
        )
        for cmd in allowed:
            with self.subTest(cmd=cmd[:40]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_pgrep_r10_backslash_fold_and_data_heredoc(self):
        allowed_a = (
            'echo a \\\nno pgrep -f',
            "git commit -m x \\\n  --trailer 'note: no pgrep -f'",
            "printf '%s\\n' \\\n  'do not use pgrep -f'",
            "echo ok \\\n  && echo 'never pgrep -f'",
            'ls \\\npgrep -f x',
        )
        allowed_b = (
            "cat <<'E'\npgrep -f",
            "<<'E'\npgrep -f",
            'cat <<E\npgrep -f bb',
        )
        blocked = (
            'sudo \\\n pgrep -f x',
            'echo a\n\\\npgrep -f x',
        )
        for cmd in allowed_a + allowed_b:
            with self.subTest(allowed=cmd[:55]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:55]):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_pgrep_fail_closed_skips_apostrophe_in_shell_comments(self):
        allowed = (
            "echo ok # it's a note about pgrep -f",
            "x=1 # can't stop; pgrep -f y",
        )
        blocked = (
            "echo ok # it's a note\npgrep -f x",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[no-pgrep-f]"))

    def test_r15_quoted_word_list_heredoc_literal(self):
        cmd = 'for c in "cat <<E | sh\npgrep -f x\nE"; do echo "$c"; done'
        self.assertFalse(
            verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
        )

    def test_heredoc_exec_gaps_table_rows(self):
        pk = "p" + "kill"
        pg = "p" + "grep -f x"
        blocked = (
            "ssh -p 22 host bash <<'EOF'\nI can't\npgrep -f x\nEOF",
            'eval "$(cat <<EOF\npgrep -f x\nEOF\n)"',
            "bash -c \"$(cat <<'EOF'\npgrep -f x\nEOF\n)\"",
            'eval "X=1 $(cat <<\'EOF\'\n' + pg + "\nEOF\n)\"",
            'bash -c "A=1 B=2 $(cat <<EOF\n' + pg + "\nEOF\n)\"",
            'eval "A=\'x y\' $(cat <<EOF\n' + pg + "\nEOF\n)\"",
            'eval "X= $(cat <<\'EOF\'\n' + pg + "\nEOF\n)\"",
            'bash -c "A= B=1 $(cat <<EOF\n' + pg + "\nEOF\n)\"",
            'eval "X=\'\' $(cat <<EOF\n' + pg + "\nEOF\n)\"",
            "python3 - <<EOF\nimport os; os.system('pgrep -f x')\nEOF",
        )
        _py_now_blocked = (
            "python3 - <<EOF\nimport os; os.system('pgrep -f x')\nEOF",
        )
        allowed = (
            "python3 - <<EOF\nimport os; os.system('pgrep -f x')\nEOF",
            "python3 - <<'EOF'\nprint(\"os.system('pgrep -f x')\")\nEOF",
            'eval "echo X=1 $(cat <<EOF\n' + pg + "\nEOF\n)\"",
            'eval ": X=1 $(cat <<EOF\n' + pg + "\nEOF\n)\"",
            'eval "X= echo $(cat <<EOF\n' + pg + "\nEOF\n)\"",
        )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                if cmd in _py_now_blocked:
                    continue
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_guard_followups_2_interpreter_heredoc_and_quote_idiom(self):
        sq = '\'"\'"\''
        blocked_interp = (
            f"printf 'a {sq}b{sq}\n'; pgrep -f x",
            "echo ''\"\"\"; pgrep -f x",
            "python3 - <<EOF\nimport os; os.system('pgrep -f x')\nEOF",
            "python3 -I - <<'EOF'\nimport subprocess; subprocess.run([\"pgrep\",\"-f\",\"x\"])\nEOF",
        )
        _py_now_blocked = (
            "python3 - <<EOF\nimport os; os.system('pgrep -f x')\nEOF",
            "python3 -I - <<'EOF'\nimport subprocess; subprocess.run([\"pgrep\",\"-f\",\"x\"])\nEOF",
        )
        allowed_interp = (
            "cat <<EOF\npgrep -f x\nEOF",
            "python3 - <<'EOF'\nprint(\"os.system('pgrep -f x')\")\nEOF",
            "python3 - <<EOF\nimport os; os.system('pgrep -f x')\nEOF",
            "python3 script.py <<EOF\npgrep -f x\nEOF",
            "python3 -I - <<'EOF'\nimport subprocess; subprocess.run([\"pgrep\",\"-f\",\"x\"])\nEOF",
            "node - <<'EOF'\nrequire('child_process').execSync('pgrep -f x')\nEOF",
            "echo ''\"\"'\\n'\"\"' -f`pgrep'",
            f"printf 'a {sq}b -f `pgrep x`{sq} c\n'",
            f"x='it{sq}s -f `pgrep`'; echo \"$x\"",
        )
        for cmd in blocked_interp:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in allowed_interp:
            with self.subTest(allowed=cmd[:70]):
                if cmd in _py_now_blocked:
                    continue
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )


    def test_guard_followups_2_fault_repro2(self):
        pk = "p" + "kill"
        sq = '\'"\'"\''
        allowed = (
            "bb thread tell t --message-file - <<'EOF'\nI can't do it.\nSlip: I ran `pgrep -f` once.\nEOF\necho sent",
            f"cat > r.md <<'EOF'\nIt didn't work; don't use {pk}.\nEOF",
            "cat <<EOF\nwe can't use pgrep -f here\nEOF",
            f"printf 'a {sq}%s{sq} b: `pgrep -f x` is banned\\n' y",
            "echo 'it'\\''s fine, never pgrep -f'",
            'echo "a"\'b\'"c pgrep -f"',
            f"x='don{sq}t'; echo \"$x pgrep -f\"",
        )
        blocked = (
            "cat <<'EOF' | sh\nI can't\npgrep -f x\nEOF",
            "cat <<'EOF'\nI can't\nEOF\npgrep -f x",
            f"printf 'a {sq}b{sq}\\n'; pgrep -f x",
            f"echo 'it'\''s'; {pk} node",
            "echo 'unterminated\npgrep -f bb",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:60]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:60]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )



    def test_r42_addside_heredoc_exec_false_blocks(self):
        pg = "p" + "grep -f x"
        allowed = (
            "echo ssh host bash <<'EOF'\n" + pg + "\nEOF",
            'eval "echo $(cat <<\'EOF\'\n' + pg + '\nEOF\n)"',
            "printf '%s\\n' ssh host bash <<EOF\n" + pg + "\nEOF",
        )
        blocked = (
            "ssh host bash <<EOF\n" + pg + "\nEOF",
            'eval "$(cat <<EOF\n' + pg + '\nEOF\n)"',
            "echo hi; ssh host bash <<EOF\n" + pg + "\nEOF",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )




    def test_r43_eval_heredoc_owner(self):
        pg = "p" + "grep -f x"
        blocked = (
            "eval sh <<EOF\n" + pg + "\nEOF",
            "eval `cat` <<EOF\n" + pg + "\nEOF",
            "eval $(cat) <<EOF\n" + pg + "\nEOF",
            'eval "$(</dev/stdin)" <<EOF\n' + pg + "\nEOF",
        )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )


    def test_r16_python_subprocess_pgrep_executable(self):
        allowed = (
            "python3 -I - <<'EOF'\nimport subprocess\nsubprocess.run([\"echo\", \"pgrep\", \"-f\"])\nEOF",
            "python3 -I - <<'EOF'\nimport subprocess\nsubprocess.run([\"printf\", \"%s\", \"pgrep\", \"-f\"])\nEOF",
        )
        blocked = (
            "python3 -I - <<'EOF'\nimport subprocess\nsubprocess.check_call([\"pgrep\", \"-f\", \"x\"])\nEOF",
            "python3 -I - <<'EOF'\nimport subprocess\nsubprocess.run([\"/usr/bin/pgrep\", \"-f\", \"x\"])\nEOF",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )



    def test_r17_python_subprocess_keyword_data_not_scanned(self):
        allowed = (
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"echo\", \"ok\"], input=\"pgrep -f x\")\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"cat\"], input=\"pgrep -f x\", text=True)\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"echo\"], env={\"X\": \"pgrep -f x\"})\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"echo\"], cwd=\"pgrep -f x\")\nEOF",
        )
        blocked = (
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"pgrep\", \"-f\", \"x\"])\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(\"pgrep -f x\", shell=True, input=\"y\")\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(args=[\"pgrep\", \"-f\", \"x\"])\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(cwd=\"/\", args=[\"pgrep\", \"-f\", \"x\"])\nEOF",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )



    def test_r19_python_subprocess_executable_overrides_argv0(self):
        allowed = (
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"pgrep\", \"-f\", \"x\"], executable=\"/bin/echo\")\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.Popen([\"pgrep\", \"-f\", \"x\"], executable=\"/bin/echo\", text=True)\nEOF",
        )
        blocked = (
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"pgrep\", \"-f\", \"x\"])\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"pgrep\", \"-f\", \"x\"], executable=\"/usr/bin/pgrep\")\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"x\", \"-f\", \"y\"], executable=\"/usr/bin/pgrep\")\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"pgrep\", \"-f\", \"x\"], executable=\"pgrep\")\nEOF",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )



    def test_r20_python_string_is_shell_only_with_shell_true(self):
        allowed = (
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run(\"pgrep -f x\", executable=\"/bin/echo\")\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run(\"pgrep -f x\")\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.Popen(\"pgrep -f x\", shell=False)\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.check_output(args=\"pgrep -f x\")\nEOF",
        )
        blocked = (
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run(\"pgrep -f x\", shell=True)\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run(\"pgrep -f x\", shell=True, executable=\"/bin/bash\")\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run(args=\"pgrep -f x\", shell=True)\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.check_output(\"pgrep -f x\", text=True, shell=True)\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nos.system(\"pgrep -f x\")\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nos.popen(\"pgrep -f x\")\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run([\"pgrep\", \"-f\", \"x\"], shell=False)\nEOF",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )



    def test_r29_nonliteral_program_or_shell_is_unknown(self):
        G = "p" + "grep"

        def py(call):
            return (
                "python3 - <<'EOF'\nimport os, subprocess\n" + call + "\nEOF"
            )

        allowed = (
            py(
                'subprocess.run(["'
                + G
                + '", "-f", "x"], executable=os.path.join("/bin", "echo"))'
            ),
            py('subprocess.run(["' + G + '", "-f", "x"], executable=exe)'),
            py('subprocess.run(["' + G + '", "-f", "x"], **kw)'),
            py('subprocess.run("' + G + ' -f x", shell=use_shell)'),
            py('subprocess.run([prog, "-f", "x"])'),
            py("subprocess.run(cmd, shell=True)"),
            py(
                'subprocess.run(["'
                + G
                + '", "-f", "x"], executable="/bin/echo")'
            ),
            py(
                'subprocess.Popen(["'
                + G
                + '", "-f", "x"], -1, "/bin/echo")'
            ),
        )
        blocked = (
            py('subprocess.run(["' + G + '", "-f", "x"])'),
            py(
                'subprocess.run(["'
                + G
                + '", "-f", "x"], executable="/usr/bin/'
                + G
                + '")'
            ),
            py('subprocess.run(["' + G + '", "-f", "x"], cwd=os.getcwd())'),
            py(
                'subprocess.run("' + G + ' -f x", shell=True, env=dict(os.environ))'
            ),
            "python3 - <<'EOF'\nimport os\nos.system(\"" + G + " -f x\")\nEOF",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"],
                    cmd,
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"],
                    cmd,
                )


    def test_r25_python_bytes_and_fstring_literals(self):
        allowed = (
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run([\"pgrep\", \"-f\", \"x\"], executable=b\"/bin/echo\")\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run(b\"pgrep -f x\")\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run([\"echo\"], input=b\"pgrep -f x\")\nEOF",
        )
        blocked = (
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run(b\"pgrep -f x\", shell=True)\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run([b\"pgrep\", b\"-f\", b\"x\"])\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nos.system(b\"pgrep -f x\")\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run(args=b\"pgrep -f x\", shell=True)\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run([\"pgrep\", \"-f\", \"x\"], executable=b\"/usr/bin/pgrep\")\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run(f\"pgrep -f x\", shell=True)\nEOF",
            "python3 - <<'EOF'\nimport os, subprocess\nsubprocess.run(r\"pgrep -f x\", shell=True)\nEOF",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )






    def test_r45_executable_resolves_runner(self):
        G = "p" + "grep"

        def py(call):
            return "python3 - <<'EOF'\nimport os, subprocess\n" + call + "\nEOF"

        allowed = (
            py(
                'subprocess.run(["bash", "-c", "'
                + G
                + ' -f x"], executable="/bin/echo")'
            ),
            py(
                'subprocess.run("'
                + G
                + ' -f x", shell=True, executable="/bin/echo")'
            ),
            py('subprocess.Popen(["bash", "-c", "' + G + ' -f x"], -1, "/bin/echo")'),
        )
        blocked = (
            py('subprocess.run(["' + G + '", "-f", "x"], executable=None)'),
            py('subprocess.call(["' + G + '", "-f", "x"], executable=None)'),
            py('subprocess.check_call(["' + G + '", "-f", "x"], executable=None)'),
            py('subprocess.check_output(["' + G + '", "-f", "x"], executable=None)'),
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )



    def test_python_stdin_prose_and_alias_examples(self):
        allowed = (
            "python3 - <<'EOF'\nprint(\"never use pgrep -f\")\nEOF",
            "python3 - <<'EOF'\nimport subprocess as sp\nsp.run([\"echo\", \"pgrep\", \"-f\", \"x\"])\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.Popen([\"pgrep\", \"-f\", \"x\"], -1, \"/bin/echo\")\nEOF",
        )
        blocked = (
            "python3 - <<'EOF'\nimport subprocess as sp\nsp.run([\"pgrep\", \"-f\", \"x\"])\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"bash\", \"-c\", \"pgrep -f x\"])\nEOF",
            "python3 - <<'EOF'\nimport os\nos.execvp(\"pgrep\", [\"pgrep\", \"-f\", \"x\"])\nEOF",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_py_subprocess_gaps_shell_true_list_and_from_imports(self):
        blocked = (
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"pgrep -f x\"], shell=True)\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.Popen([\"pkill node\"], shell=True)\nEOF",
            "python3 - <<'EOF'\nfrom subprocess import run\nrun([\"pgrep\",\"-f\",\"x\"])\nEOF",
            "python3 - <<'EOF'\nfrom subprocess import Popen as P\nP([\"pgrep\",\"-f\",\"x\"])\nEOF",
            "python3 - <<'EOF'\nfrom os import system\nsystem(\"pgrep -f x\")\nEOF",
            "python3 - <<'EOF'\nfrom subprocess import check_output\ncheck_output(\"pgrep -f x\", shell=True)\nEOF",
        )
        allowed = (
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"echo pgrep -f x\"], shell=True)\nEOF",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run([\"pgrep -f x\"], shell=True, executable=\"/bin/echo\")\nEOF",
            "python3 - <<'EOF'\nfrom subprocess import run\nrun([\"echo\",\"pgrep -f x\"])\nEOF",
            "python3 - <<'EOF'\ndef run(x): pass\nrun([\"pgrep\",\"-f\",\"x\"])\nEOF",
            "python3 - <<'EOF'\nprint(\"from subprocess import run; run(['pgrep','-f','x']\")\nEOF",
        )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )



    def test_python_stdin_list_noise_before_os_system(self):
        cmd = (
            "python3 - <<'EOF'\n"
            "xs=[1]\n"
            'import os\nos.system("pgrep -f x")\n'
            "EOF"
        )
        self.assertTrue(
            verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
        )

    def test_python_stdin_nested_comps_hermes_k3000(self):
        import time

        k = 3000
        inner = ",".join(f"[0 for v{i} in []]" for i in range(k))
        body = (
            "x=[(" + inner + ") for outer in []]\n"
            "from subprocess import run\n"
            'run(["pgrep","-f","x"])\n'
        )
        cmd = "python3 - <<'EOF'\n" + body + "EOF"
        start = time.monotonic()
        v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
        elapsed = time.monotonic() - start
        self.assertTrue(v["block"], cmd[:80])
        self.assertLess(elapsed, 1.5, f"scan took {elapsed:.2f}s")

    def test_python_stdin_deep_brackets_scan_bounded(self):
        import time

        n = 500
        line = "x=" + "[" * 199 + "0" + "]" * 199
        body = (line + "\n") * (n // 20) + "import subprocess\nsubprocess.run(['echo','hi'])\n"
        cmd = "python3 - <<'EOF'\n" + body + "EOF"
        start = time.monotonic()
        v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
        elapsed = time.monotonic() - start
        self.assertFalse(v["block"], cmd[:80])
        self.assertLess(elapsed, 8.0, f"scan took {elapsed:.2f}s")

    def test_python_stdin_import_shadow_parameter(self):
        allowed = (
            "python3 - <<'EOF'\n"
            "from subprocess import run\n"
            'def invoke(run): run(["pgrep","-f","x"])\n'
            "invoke(print)\n"
            "EOF",
        )
        blocked = (
            "python3 - <<'EOF'\n"
            "from subprocess import run; run(['pgrep','-f','x'])\n"
            "EOF",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_python_stdin_launcher_prefix_argv(self):
        blocked = (
            "python3 - <<'EOF'\n"
            "import subprocess\n"
            'subprocess.run(["sudo", "pgrep", "-f", "x"])\n'
            "EOF",
            "python3 - <<'EOF'\n"
            "import subprocess\n"
            'subprocess.run(["sudo pgrep -f x"], shell=True)\n'
            "EOF",
        )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_python_stdin_annotation_does_not_shadow_import(self):
        blocked = (
            "python3 - <<'EOF'\n"
            "from subprocess import run\n"
            "def go(x: run = None): run(['pgrep', '-f', 'x'])\n"
            "EOF",
            "python3 - <<'EOF'\n"
            "from os import system\n"
            "v: system = None\n"
            'system("pgrep -f x")\n'
            "EOF",
        )
        allowed = (
            "python3 - <<'EOF'\n"
            "from subprocess import run\n"
            'def invoke(run): run(["pgrep","-f","x"])\n'
            "invoke(print)\n"
            "EOF",
        )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_python_stdin_parenthesised_from_import(self):
        blocked = (
            "python3 - <<'EOF'\n"
            "from subprocess import (run,)\n"
            'run(["pgrep", "-f", "x"])\n'
            "EOF",
            "python3 - <<'EOF'\n"
            "from os import (system,)\n"
            'system("pgrep -f x")\n'
            "EOF",
        )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_r35_fail_closed_unclosed_subst_comment(self):
        pk = "p" + "kill"
        cmd = "$(true # c)); " + pk + " node\necho hi"
        self.assertTrue(
            verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
        )

    def test_lifecycle_masker_paren_inside_subst_comment_is_masked(self):
        pk = "p" + "kill"
        cmd = (
            'echo "$(true # ) '
            + pk
            + " node\n"
            + 'true)"'
        )
        import importlib.util
        pol_path = Path(__file__).with_name("context-hygiene-policy.py")
        spec = importlib.util.spec_from_file_location("context_hygiene_policy", pol_path)
        pol = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pol)
        self.assertNotIn(pk, pol._pgrep_mask_lifecycle_comments(cmd))
        self.assertFalse(
            verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
        )

    def test_lifecycle_masker_comment_apostrophe_in_subst_still_blocks(self):
        pk = "p" + "kill"
        blocked = (
            'echo "$(true # note ' + "'" + "\n" + pk + " node; echo 'x'\n" + ')"',
            "echo \"$(true # don't\n" + pk + " -f x; echo 'y'\n)\"",
        )
        allowed = (
            "printf '%s\\n' 'a\n" + pk + " node is banned\nb'",
            'echo "$(printf \'%s\' \'a $( ' + pk + " b')\"",
        )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_lifecycle_case_unreachable_arm_reachability(self):
        pk = "p" + "kill"
        allowed = (
            f"case x in z) {pk} node;; esac",
            f"case x in x) true;; z) {pk} node;; esac",
            f"x=$(case x in z) {pk} node;; esac)",
            f"case x in z) true ;& y) {pk} node;; esac",
            f"case x in 'z') {pk} node;; esac",
        )
        blocked = (
            "shopt -s nocasematch; case x in X) "
            + pk
            + " node;; esac",
            'shopt -s nocasematch; echo "$(case x in X) '
            + pk
            + ' node;; esac)"',
            "shopt -s extglob\ncase x in @(x|y)) "
            + pk
            + " node;; esac",
            'shopt -s extglob\necho "$(case x in @(x|y)) '
            + pk
            + ' node;; esac)"',
            "shopt -s extglob\ncase x in !(z)) " + pk + " node;; esac",
            f"case x in x) true ;& z) {pk} node;; esac",
            f'case "$1" in z) {pk} node;; esac',
            f"case $v in z) {pk} node;; esac",
            f"case x in *) {pk} node;; esac",
            f"case x in [xy]) {pk} node;; esac",
            f"case x in z|x) {pk} node;; esac",
            f'case "x" in x) {pk} node;; esac',
            f'echo "$(case x in x\'\') {pk} node;; esac)"',
            f"case x in 'x') {pk} node;; esac",
            f'case x in x"") {pk} node;; esac',
            f"case 'x' in x) {pk} node;; esac",
            f'case "x\\q" in \'x\\q\') {pk} node;; esac',
            f'echo "$(case "x\\q" in \'x\\q\') {pk} node;; esac)"',
            f"case x in '*') {pk} node;; esac",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_data_heredoc_bodies_exempt_wherever_they_appear(self):
        pk = "p" + "kill"
        allowed = (
            "cat > f1 <<'EOF'\nx\nEOF\ncat > f2 <<'EOF'\n" + pk + " node\nEOF",
            "cat > f1 <<'EOF'\n" + pk + " node\nEOF\ncat > f2 <<'EOF'\n" + pk + " node\nEOF",
            "cat > f1 <<'A'\n" + pk + " node\nA\ncat > f2 <<'B'\n" + pk + " node\nB",
            "cat > f1 <<EOF\n" + pk + " node\nEOF\ncat > f2 <<EOF\n" + pk + " node\nEOF",
            "echo start\ncat > f1 <<'EOF'\n" + pk + " node\nEOF",
        )
        blocked = (
            "cat > f1 <<'EOF'\nx\nEOF\ncat > f2 <<'EOF'\ny\nEOF\n"
            + pk
            + " node | sh",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_lifecycle_blocks_pkill_reached_by_case_fallthrough(self):
        pk = "p" + "kill"
        blocked = (
            f"case x in x) true ;& y) {pk} node;; esac",
            f"case x in x) true ;;& x) {pk} node;; esac",
            f'echo "$(case x in x) true ;& y) {pk} node;; esac)"',
        )
        allowed = (
            f"case x in x) true ;& y) echo '{pk} node';; esac",
            f"case x in x) true ;;& y) printf '%s' {pk};; esac",
            f'echo "$(case x in x) true ;;& z) {pk} node;; esac)"',
            "case x in x) echo '; pkill node ;&';; esac",
        )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_lifecycle_blocks_pkill_in_case_arm_inside_dollar_paren(self):
        pk = "p" + "kill"
        blocked = (f'echo "$(case x in x) {pk} node;; esac)"',)
        allowed = (
            f'echo "$(case x in x) echo \'{pk} node\';; esac)"',
            f'echo "$(case x in {pk}) true;; esac)"',
        )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                self.assertTrue(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_lifecycle_blocks_pkill_reached_through_nested_exec(self):
        pk = "p" + "kill"
        blocked = (
            f"bash -c '{pk} node'",
            f'bash -c "{pk} node"',
            f"sh -c '{pk} node'",
            f"bash -lc 'cd /tmp && {pk} node'",
            f"eval '{pk} node'",
            f'eval "{pk} node"',
            f"CMD='{pk} node'; $CMD",
            f"CMD='{pk} node'; eval \"$CMD\"",
            f"CMD='{pk} node'; bash -c \"$CMD\"",
            f"env {pk} node",
            f"nohup {pk} node",
            f"timeout 5 {pk} node",
            f"command {pk} node",
            f"exec {pk} node",
            f'echo "$(bash -c \'{pk} node\')"',
        )
        allowed = (
            f'echo \'bash -c "{pk} node"\'',
            f"printf '%s\\n' \"eval '{pk} node'\"",
            "grep -n 'bash -c pk' notes.txt",
            f"CMD='{pk} node'; echo \"$CMD\"",
            f'git commit -m "bash -c \'{pk} node\' is blocked"',
        )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)
                self.assertTrue(v["reason"].startswith("[bb-lifecycle]"), v["reason"][:40])
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )

    def test_lifecycle_masker_multiline_single_quote_and_subst_opener_are_data(self):
        pk = "p" + "kill"
        allowed = (
            "printf '%s\\n' 'a\n" + pk + " node is banned\nb'",
            'echo "$(printf \'%s\' \'a $( ' + pk + " b')\"",
        )
        blocked = (
            "bash -c 'true\npgrep -f x'",
            "ssh host 'cd /tmp\n" + pk + " node'",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd[:70]):
                self.assertFalse(
                    verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})["block"], cmd
                )
        for cmd in blocked:
            with self.subTest(blocked=cmd[:70]):
                v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
                self.assertTrue(v["block"], cmd)

    def test_python_stdin_large_heredoc_scan_bounded(self):
        import time

        n = 5000
        body = "x=0\n" * n + "import subprocess\nsubprocess.run(['echo', 'hi'])\n"
        cmd = "python3 - <<'EOF'\n" + body + "EOF"
        start = time.monotonic()
        v = verdict(bash(cmd), env={"CONTEXT_HYGIENE": "off"})
        elapsed = time.monotonic() - start
        self.assertFalse(v["block"], cmd[:80])
        self.assertLess(elapsed, 8.0, f"scan took {elapsed:.2f}s")


    def test_many_python_heredocs_in_one_command_stays_fast(self):
        import time

        n = 600
        cmd = "".join("python3 - <<'EOF'\nprint(%d)\nEOF\n" % i for i in range(n))
        start = time.monotonic()
        v = verdict(bash(cmd + "pkill node"), env={"CONTEXT_HYGIENE": "off"})
        elapsed = time.monotonic() - start
        self.assertTrue(v["block"], cmd[:80])
        self.assertLess(elapsed, 2.0, f"many-heredoc scan took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
