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
              "cat<<EOF\n&& x\nEOF\ngit push origin main", "x=$(cat <<EOF\n&& y\nEOF\n)\ngit push origin main",
              'x="$(cat <<EOF\n&& y\nEOF\n)"\ngit push origin main', 'x="`cat <<EOF\n&& y\nEOF\n`"\ngit push origin main',
              # a heredoc body may hold a ) line: zsh reads past it and runs the push (bash and sh stop)
              'x=$(cat <<EOF\n)\n&& y\nEOF\n)\ngit push origin main',
              'x=$(echo "$(cat <<EOF\n)")\n&& y\nEOF\n)")\ngit push origin main']
# A PR merge whose quoted subject or body names a push or a deploy is still only a merge.
MERGE_TEXT = [# a << in a comment or in quotes is no heredoc: the line-start && stops the shell (Hermes r8)
              'gh pr merge 5 # see <<notes \\\n&& git push origin main',
              'gh pr merge 5 --subject "a <<b"\n&& git push origin main',
              # ... also when quoted inside a substitution (Hermes r9)
              'gh pr merge 5 --subject "$(printf \'<<\')"\n&& git push origin main',
              'gh pr merge 5 --subject "`printf \'<<\'`"\n&& git push origin main',
              "gh pr merge 5 --subject $(printf '<<')\n&& git push origin main",
              'gh pr merge 5 --subject "$(printf "%s" "<<")"\n&& git push origin main',
              # a heredoc body is text: a merge whose body names a push is still only a merge
              'gh pr merge 5 --body "$(cat <<EOF\ngit push origin main\nEOF\n)"',
              'gh pr merge 5 --body "$(cat <<-EOF\n\tgit push origin main\n\tEOF\n)"',
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
        "echo ${X:-$(git push)}", "cat <(git push)", "gh pr merge 5 -t \"`echo \\`x\\``\"", "git push \\\\\ngit push", 'gh pr merge 5 -t "x && git push origin main',
        # heredoc shapes the strip must read like the gate (Hermes r10)
        "echo $((1<<2))\ngit push origin main", "(( x = 1 << 2 ))\ngit push origin main",
        "echo $(( (1+2) << 3 ))\ngit push origin main", 'cat << "E O F"\ngit push\nE O F\ngit push origin main',
        "cat <<-'E'\n\tgit push\n\tE\ngit push origin main", "a <<A; b <<B\ngit push\nA\n2\nB\ngit push origin main",
        "cat <<<word\ngit push origin main", "cat <<EOF\nnever ends\ngit push origin main",
        "cat <<\\EOF\ngit push\nEOF\ngit push origin main", "echo '<<x' \"<<y\" \\<<z # <<c\ngit push origin main",
        # unreadable on both scanners (Hermes r11): an operator on the last line, a context closed on its line
        "gh pr merge 5; cat <<E", "x=$(cat <<E )\ngit push origin main\nE", "echo ${x:-<<E }\ngit push origin main\nE"]

# Real-shell oracle (Hermes 2026-10-07, kit-never-block-pr-merge r11): heredoc delimiter words crossed with the
# contexts that hold them, run by every shell here with -c, as agents run commands. When a shell runs the line
# after the heredoc (a push in the scanned copy, an echo in the run copy), the gate's segments and the fallback's
# scan must both see the push, and one case per word and context goes through both hooks and must be denied. A
# PR merge whose body heredoc has a plain delimiter must still be allowed on both paths.
PUSH, RAN = "git push origin main", "echo ORACLE-RAN"
WORDS = ["EOF", "'EOF'", '"EOF"', "\\EOF", "E'O'F", '"E O F"', "$(echo E)", '$(echo "E")', "`echo E`", "$((1))",
         "E$(x)F", "E(x)", "E)", "${X}", "$X", "E{a,b}", "E*", "E=x",
         # read alike by every shell (Hermes r10 <<'EOF!', r11 <<"a\q"), so a merge body using one is allowed
         "EOF!", "!EOF", "a:b/c@d%e+f,g^h", "'EOF!'", '"EOF!"', "\\!EOF", "'a b$c'", "'a\\b'", "E\\ x", '"a\\q"',
         '"a\\\\b"', "$'EOF'",
         # bash 3.2 and sh misread a quote inside a "$(...)" merge body, so these stay unreadable (deny side);
         # test-heredoc-words.py measures every spelling
         "'a\"b'", '"a(b"']
READABLE = WORDS[:6] + WORDS[18:30]
CONTEXTS = {
    "top": "cat <<{W}\n{B}\n{T}\n{P}", "sub": "x=$(cat <<{W}\n{B}\n{T}\n)\n{P}",
    "quoted sub": 'x="$(cat <<{W}\n{B}\n{T}\n)"\n{P}', "backtick": "x=`cat <<{W}\n{B}\n{T}\n`\n{P}",
    "subshell": "(cat <<{W}\n{B}\n{T}\n)\n{P}", "two deep": 'x="$(echo "$(cat <<{W}\n{B}\n{T}\n)")"\n{P}',
    "closed on its line": "x=$(cat <<{W})\n{P}\n{T}", "quoted, closed on its line": 'x="$(cat <<{W})"\n{P}\n{T}',
    "<<-": "cat <<-{W}\n\t{B}\n\t{T}\n{P}", "merge body": 'gh pr merge 5 --body "$(cat <<{W}\n{B}\n{T}\n)"\n{P}',
    # each reaches one strip check with the others passing: a context closed after a blank or a ;, a body line
    # bash ends at (T then a parenthesis), and a << inside ${...}, which is text
    "closed on its line after a blank": "x=$(cat <<{W} )\n{P}\n{T}", "closed on its line by ;": "x=$(cat <<{W};)\n{P}\n{T}",
    "bash ends the body at T)": "x=$(cat <<{W}\n{B}\n{T})\n{P}\n{T}\n)", "in ${...}": "echo ${x:-<<{W} }\n{P}\n{T}",
}
SHELLS = [s for s in ("/bin/bash", "/bin/zsh", "/bin/sh") if os.path.exists(s)]


def unquote(w):
    """The delimiter the shells read from a word: the gate's reader where it reads the word (test-heredoc-words.py
    checks it against the shells), otherwise quotes removed in one pass, a backslash keeping the next character."""
    got = gate._heredoc_word(w + "\n", 0)
    if got:
        return got[0]
    return re.sub(r"'([^']*)'|\"([^\"]*)\"|\\(.)", lambda m: m.group(m.lastindex), w)


oracle_cases = oracle_bad = oracle_hooks = 0
sampled = set()
for wname in WORDS:
    for cname, tpl in CONTEXTS.items():
        for body in ("&& y", "{P}", '"'):  # a lone quote: read as code, it swallows the lines after it
            for term in dict.fromkeys((wname, unquote(wname))):
                src = tpl.replace("{B}", body).replace("{W}", wname).replace("{T}", term)
                scanned, runnable = src.replace("{P}", PUSH), src.replace("{P}", RAN).replace("gh pr merge", ": gh pr merge")
                ran = [s for s in SHELLS
                       if "ORACLE-RAN" in subprocess.run([s, "-c", runnable], cwd=N, capture_output=True, text=True,
                                                         timeout=20).stdout.splitlines()]
                oracle_cases += 1
                if not ran:
                    continue
                segs = gate.command_segments(scanned)
                seen_gate = any(s[:2] == ["git", "push"] for s in segs)
                payload = json.dumps({"tool_input": {"command": scanned}, "cwd": N})
                flags = sh(f"input=$(cat)\n{func}ship_scan", N, payload).stdout.split()
                seen_shell = flags[:1] == ["1"]
                ok = seen_gate and seen_shell
                if (wname, cname) not in sampled:
                    sampled.add((wname, cname))
                    for mode in ("gate", "fallback"):
                        oracle_hooks += 1
                        got = run(mode, f"cd {q}\n" + scanned, N)
                        ok = ok and got == 2
                oracle_bad += not ok
                if not ok:
                    print(f"BAD oracle {cname} <<{wname} terminator {term!r}: ran in {ran}, gate segments see the push "
                          f"{seen_gate}, fallback scan sees it {seen_shell}: {scanned!r}")
# Both awk copies of the fallback scanner, each called directly, besides the hook that runs one of them.
coord_func = re.search(r"^ship_scan\(\) \{\n.*?^\}\n", open(os.path.join(HOOKS, "coordinator-hook-pretool.sh")).read(),
                       re.S | re.M).group(0)
for wname in READABLE:
    merge = f'gh pr merge 5 --body "$(cat <<{wname}\n{PUSH}\n{unquote(wname)}\n)"'
    for cmd, want in ((merge, 0), (merge + f"\n{PUSH}", 2)):  # the body is allowed; a push after it is not
        for mode in ("gate", "fallback"):
            oracle_hooks += 1
            got = run(mode, cmd, O)
            oracle_bad += got != want
            if got != want:
                print(f"BAD oracle merge with a <<{wname} body: {mode} rc {got}, want {want}: {cmd!r}")
        payload = json.dumps({"tool_input": {"command": cmd}, "cwd": N})
        for name, f in (("qa-ship-gate-hook.sh", func), ("coordinator-hook-pretool.sh", coord_func)):
            seen = sh(f"input=$(cat)\n{f}ship_scan", N, payload).stdout.split()[:1] == ["1"]
            oracle_bad += seen != (want == 2)
            if seen != (want == 2):
                print(f"BAD oracle {name} ship_scan with a <<{wname} body sees a push {seen}, want {want == 2}: {cmd!r}")
bad += oracle_bad
print(f"real-shell oracle: {oracle_cases} cases on {len(SHELLS)} shells, {oracle_hooks} hook runs, {oracle_bad} bad")
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
