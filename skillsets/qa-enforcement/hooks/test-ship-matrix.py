"""Push and PR-merge command forms, run through the full ship gate and the adapter's shell fallback
from a plain checkout and from a non-repo dir. Every form that picks the opted-in repo is denied on
both paths; PR merges and work-tree-only forms are allowed (Hermes 2026-10-06, kit-never-block-pr-merge).
Usage: test-ship-matrix.py [--markdown]
Prints one row per (command, cwd, mode): expected, observed. Exit 1 on any mismatch."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOKS = os.path.dirname(os.path.abspath(__file__))
md = "--markdown" in sys.argv
GATE = os.path.join(HOOKS, "..", "shared", "qa-sweep", "scripts", "ship-gate.py")
ADAPTER = os.path.join(HOOKS, "qa-ship-gate-hook.sh")
tmp = tempfile.mkdtemp(prefix="gate-matrix-")


def sh(cmd, cwd, inp=None, env=None):
    return subprocess.run(cmd, shell=True, cwd=cwd, input=inp, capture_output=True, text=True, env=env)


def repo(name, optin):
    r = os.path.join(tmp, name)
    os.makedirs(r)
    sh("git init -q -b main && git config user.email t@t && git config user.name t", r)
    if optin:
        os.makedirs(os.path.join(r, ".qa"))
        with open(os.path.join(r, ".qa", "config.json"), "w") as fh:
            json.dump({"schema_version": 1, "personas": ["admin"], "workflows": [{"name": "w1"}]}, fh)
    open(os.path.join(r, "f"), "w").close()
    sh("git add -A && git commit -qm init", r)
    return r


O = repo("opted repo", True)
P = repo("plain repo", False)
N = os.path.join(tmp, "nonrepo")
os.makedirs(N)
fake_home = os.path.join(tmp, "home")          # no qa-sweep skill here, so the adapter takes its fallback
os.makedirs(os.path.join(fake_home, ".agents/skills"))

q = '"%s"' % O
DENY = [
    f"git -C {q} push origin main",
    f"cd {q} && git push origin main",
    f"pushd {q} && git push origin main",
    f"(cd {q} && git push origin main)",
    f"sh -c 'cd {q}; git push origin main'",
    f"env -C {q} git push origin main",
    f"env --chdir={q} git push origin main",
    f'export GIT_DIR="{O}/.git"; git push origin main',
    f'GIT_DIR="{O}/.git" git push origin main',
    f'git --git-dir "{O}/.git" push origin main',
    f'git --git-dir="{O}/.git" push origin main',
    f'GIT_WORK_TREE={q} GIT_DIR="{O}/.git" git push origin main',
]
ALLOW = [
    f"GIT_WORK_TREE={q} git push origin main",
    f"git --work-tree={q} push origin main",
    "gh pr merge 5 --admin",
    f"cd {q} && gh pr merge 5 --admin",
    f"git -C {q} fetch && gh pr merge 5 --admin",
    f'GIT_DIR="{O}/.git" gh pr merge 5 --admin',
    f"GIT_WORK_TREE={q} gh pr merge 5 --admin",
    f"env -C {q} gh pr merge 5 --admin --squash",
    f"cd {q} && gh pr ready 5",
]
# A relative GIT_DIR only means the opted repo from the plain checkout (a sibling dir).
REL = '../"opted repo"/.git'
# From inside the opted repo: any shell whitespace between words (a line continuation, a run of
# spaces, a tab) still spells a push, and still is not a PR merge.
LOCAL_DENY = ["git push origin main", "git \\\npush origin main", "git  push origin main", "git\tpush origin main",
              "git \\\n  -c core.x=y \\\n  push origin main", "git pu\\\nsh origin main",
              # a merge that also runs something else is judged by what else it runs
              "gh pr merge 5; git push origin main", "gh pr merge 5 && git push origin main",
              "gh pr merge 5\ngit push origin main", 'gh pr merge 5 --subject "$(git push origin main)"',
              "gh pr merge 5 --subject `git push origin main`",
              # a push in a substitution runs, quoted or not
              'echo "$(git push origin main)"', "echo `git push origin main`", 'echo "`git push origin main`"',
              "echo $(git push origin main)", 'echo "x $(echo "$(git push origin main)")"',
              'git push origin main && gh pr merge 5', 'gh pr merge 5 | sh -c "git push origin main"',
              'bash -c "git push origin main"', "eval git push origin main", 'X=$(git push origin main) gh pr merge 5',
              # a # inside a word, quoted or escaped starts no comment; a comment ends at the newline
              "gh pr merge 5 #x\ngit push origin main", "echo a#b && git push origin main",
              "echo \\# && git push origin main", 'echo "#" && git push origin main',
              # an ordinary comment ends at the newline; a real continuation joins; a heredoc body is text
              "gh pr merge 5 # comment\ngit push origin main", "gh pr merge 5 \\\n&& git push origin main",
              "gh pr merge 5 &&\ngit push origin main", "cat <<EOF\n&& x\nEOF\ngit push origin main",
              # a real heredoc operator, unspaced or in a substitution, still makes its body text
              "cat<<EOF\n&& x\nEOF\ngit push origin main", "x=$(cat <<EOF\n&& y\nEOF\n)\ngit push origin main"]
# A PR merge whose quoted subject or body names a push or a deploy is still only a merge.
MERGE_TEXT = [# a << in a comment or in quotes is no heredoc: the line-start && stops the shell (Hermes r8)
              'gh pr merge 5 # see <<notes \\\n&& git push origin main',
              'gh pr merge 5 --subject "a <<b"\n&& git push origin main',
              'gh pr merge 5 --subject "git \\\npush"', 'gh pr merge 5 --admin --subject "git push origin main"',
              "gh pr merge 5 --body 'run vercel --prod; git push --tags'",
              'gh pr merge 5 \\\n  --subject "git \\\n  -c x=y \\\n  push" --admin',
              'cd "/x y" && gh pr merge 5 -t "git push"', 'GH_TOKEN=x gh pr merge 5 --subject "deploy --prod" 2>&1',
              """gh pr merge 5 --subject 'it'"'"'s git push'""", 'gh pr merge 5 --subject "a \\" git push"',
              # ... also beside other commands, piped, or run through sh -c
              "gh pr merge 5 --subject 'git push origin main' && echo done",
              'echo start; gh pr merge 5 -b "git push --tags"; echo done', 'gh pr merge 5 -t "git push" | tee log',
              """bash -c "gh pr merge 5 --subject 'git push origin main'" """,
              "env GH_TOKEN=x gh pr merge 5 -t 'vercel --prod'",
              # a comment never runs (Hermes 2026-10-06 r6)
              "gh pr merge 5 # && git push origin main", "gh pr merge 5 --admin # `git push origin main`",
              # a line that starts with && || or | is a syntax error: nothing after it runs (Hermes r7)
              "gh pr merge 5 # comment \\\n&& git push origin main", "gh pr merge 5\n&& git push origin main",
              "gh pr merge 5\n  || git push origin main"]
LOCAL_ALLOW = ["gh pr merge 5 --admin", "gh pr merge 5 \\\n  --admin --squash", "git \\\n  status"] + MERGE_TEXT


def run(mode, cmd, cwd):
    payload = json.dumps({"session_id": "matrix", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})
    if mode == "gate":
        return sh(f'python3 "{GATE}" hook', cwd, payload).returncode
    env = {**os.environ, "HOME": fake_home}
    return sh(f'sh "{ADAPTER}"', cwd, payload, env).returncode


rows, bad = [], 0
for cwd_name, cwd in (("opted repo", O), ("plain checkout", P), ("non-repo dir", N)):
    cases = [(c, 2) for c in DENY] + [(c, 0) for c in ALLOW]
    if cwd is O:
        cases = [(c, 2) for c in LOCAL_DENY] + [(c, 0) for c in LOCAL_ALLOW]
    if cwd is P:
        cases.append((f"GIT_DIR={REL} git push origin main", 2))
    for cmd, want in cases:
        for mode in ("gate", "fallback"):
            got = run(mode, cmd, cwd)
            ok = got == want
            bad += not ok
            rows.append((cmd.replace(O, "<opted>").replace("\n", "\\n").replace("\t", "\\t"), cwd_name, mode,
                         "deny" if want == 2 else "allow",
                         {0: "allow", 2: "deny"}.get(got, f"rc {got}"), ok))

# The gate's ship_view and the shell fallback's ship_scan are one scanner written twice: they must
# read every form above, and these edge cases, as the same words (or both fall back to the raw text).
import importlib.util
import re

spec = importlib.util.spec_from_file_location("ship_gate", GATE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
func = re.search(r"^ship_scan\(\) \{\n.*?^\}\n", open(ADAPTER).read(), re.S | re.M).group(0)
EDGE = ['"gh" pr merge 5', "gh pr merge", "gh pr", "cd && gh pr merge 5", "cd x && cd y && gh pr merge 5",
        "gh pr merge 5 >/dev/null 2>&1", "gh pr merge 5 & git push", 'gh pr merge 5 --subject "unterminated',
        "gh pr merge 5 | tee x", "sh -c 'gh pr merge 5'", "(gh pr merge 5)", 'gh pr merge 5 --subject "ü git push"',
        "gh pr merge 5 # note", "X=$(git push) gh pr merge 5", "LD_PRELOAD=x gh pr merge 5", "gh pr merge 5 \\",
        "gh pr merge 5 --subject 'a \\' git push'", "gh pr merge 5 -t \"x\" -b 'y' --auto",
        "/opt/homebrew/bin/gh pr merge 5 -t 'git push'", "env -C /x gh pr merge 5 -t 'git push'",
        "sudo -u me gh pr merge 5 -t 'git push'", 'sh -c "sh -c \\"sh -c \\\\\\"git push\\\\\\"\\""',
        "eval 'gh pr merge 5 -t \"git push\"'", 'gh pr merge 5 -b "$(cat <<EOF\ngit push\nEOF\n)"',
        "echo ${X:-$(git push)}", "cat <(git push)", "gh pr merge 5 -t \"`echo \\`x\\``\"", "git push \\\\\ngit push", 'gh pr merge 5 -t "x && git push origin main']
agree = total = 0
for cmd in LOCAL_DENY + LOCAL_ALLOW + DENY + ALLOW + EDGE:
    for ascii_only in (True, False):
        if ascii_only and not cmd.isascii():
            continue  # the awk decoder reads a \\u escape as one placeholder character
        payload = json.dumps({"tool_input": {"command": cmd}, "cwd": N}, ensure_ascii=ascii_only)
        shell = sh(f"input=$(cat)\n{func}ship_scan", N, payload, {**os.environ, "SHIP_SCAN_VIEW": "1"}).stdout.rstrip("\n")
        view = gate.ship_view(cmd)
        py = gate.flat_words(view) if view is not None else None
        ok = shell.startswith("FLAT ") if py is None else shell == py
        agree += ok
        bad += not ok
        if not ok or not md:
            print(f"{'ok ' if ok else 'BAD'} scanners  gate {py!r} shell {shell[:120]!r} {cmd!r}")
        total += 1
print(f"scanners agree on {agree} of {total} payloads")
if md:
    print("| command | cwd | path | expected | observed |\n|---|---|---|---|---|")
    for c, w, m, e, o, ok in rows:
        print(f"| `{c}` | {w} | {m} | {e} | {o}{'' if ok else ' **MISMATCH**'} |")
else:
    for c, w, m, e, o, ok in rows:
        print(f"{'ok ' if ok else 'BAD'} {m:<8} {w:<14} want {e:<5} got {o:<5} {c}")
print(f"{len(rows)} rows, {bad} mismatches")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if bad else 0)
