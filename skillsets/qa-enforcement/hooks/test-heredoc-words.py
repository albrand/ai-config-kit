#!/usr/bin/env python3
"""Heredoc delimiter words, measured in the real shells (Hermes 2026-10-07, kit-never-block-pr-merge r10, r11).

Generates delimiter spellings: every printable character in plain, escaped, single-, double- and $'-quoted shapes,
plus random mixes from fixed seeds. Each word runs in bash, zsh and sh, at top level and inside a `"$(...)"` merge
body. A word is read alike when every shell, in both places, ends the body at the same terminator, which is then
its delimiter. The gate's _heredoc_word and both hooks' awk hdword() must:
  - never read a word the shells disagree on, or read a different delimiter (safety: no hidden push);
  - read every word exactly as each other;
and, for the words they read, a merge body holding a push line must be allowed by command_segments and both awk
ship_scan copies, and the same merge followed by a push denied. Words the shells read alike that the reader
declines are listed as the residual: a merge using one is denied.
Usage: test-heredoc-words.py   (exits 1 on any failure)"""
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HOOKS = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("gate", os.path.join(HOOKS, "..", "shared", "qa-sweep", "scripts",
                                                                   "ship-gate.py"))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
SHELLS = [s for s in ("/bin/bash", "/bin/zsh", "/bin/sh") if os.path.exists(s)]
PUSH = "git push origin main"


def corpus():
    words = []
    for c in [chr(i) for i in range(0x20, 0x7F)] + ["\t"]:
        words += [f"E{c}x", f"{c}E", f"\\{c}E", f"E\\{c}", f"'a{c}b'", f'"a{c}b"', f'"a\\{c}b"', f"'a\\{c}b'",
                  f'"a\\\\{c}b"', f"$'a{c}b'", f"'a{c}'", f'"a{c}"']
    words += ["''", '""', "$'EOF'", "$'a\\nb'", '$"EOF"', "É", "aÉb", "'É'", "a'b'\"c\"\\d", "EOF", "'EOF'",
              '"EOF"', "\\EOF", "E'O'F", '"E O F"', "'a b'", '"a\\\\b"', "'a\\b'", '"a\\q"', "'EOF!'", "\\\\", "\\\\}",
              '"${"9', '"$["\\!', '"$$["', "$\"a''b'"]  # read apart: ${ and $[ in double quotes, an unclosed $"
    alpha = list("aEZ09_.+,:@%/!^-#~=*?[]{}$\\'\"()`é ")
    for seed in (7, 101, 113):
        rng = random.Random(seed)

        def piece():
            kind = rng.choice(["plain", "plain", "bs", "sq", "dq", "ansi"])
            body = "".join(rng.choice(alpha) for _ in range(rng.randint(1, 3)))
            if kind == "plain":
                return "".join(c for c in body if c not in " \\'\"()`$#") or "a"
            if kind == "bs":
                return "\\" + body[0]
            if kind == "sq":
                return "'" + body.replace("'", "") + "'"
            if kind == "dq":
                return '"' + body.replace('"', "") + '"'
            return "$'" + body.replace("'", "").replace("\\", "") + "'"
        words += ["".join(piece() for _ in range(rng.randint(1, 3))) for _ in range(500)]
    return [w for w in dict.fromkeys(words) if "\n" not in w]


def posix(w):
    """Quote removal as POSIX and the shells' $'...' (no escapes) do: the candidate terminator to try first."""
    out, i, n = [], 0, len(w)
    while i < n:
        c = w[i]
        if c == "\\" and i + 1 < n:
            out.append(w[i + 1]); i += 2
        elif c == "$" and w[i + 1:i + 2] == "'" and "\\" not in w[i + 2:w.find("'", i + 2)]:
            j = w.find("'", i + 2)
            if j < 0:
                return None
            out.append(w[i + 2:j]); i = j + 1
        elif c == "'":
            j = w.find("'", i + 1)
            if j < 0:
                return None
            out.append(w[i + 1:j]); i = j + 1
        elif c == '"':
            i += 1
            while i < n and w[i] != '"':
                if w[i] == "\\" and i + 1 < n and w[i + 1] in '$`"\\':
                    out.append(w[i + 1]); i += 2
                else:
                    out.append(w[i]); i += 1
            if i >= n:
                return None
            i += 1
        else:
            out.append(c); i += 1
    return "".join(out)


def candidates(w):
    cut = next((i for i, c in enumerate(w) if c in " \t;&|<>()"), len(w))
    naive = w.replace("'", "").replace('"', "").replace("\\", "")
    forms = (posix(w), posix(w[:cut]) if cut else None, naive, w, posix(w.replace("$'", "\\$'")), "EOF")
    return [t for t in dict.fromkeys(x for x in forms if x) if "\n" not in t]


def ends_at(shell, ctx, w, t):
    script = (f"cat <<{w}\nBODY\n{t}\necho RAN" if ctx == "top" else
              f'x="$(cat <<{w}\nBODY\n{t}\n)"\necho "$x"\necho RAN')
    try:
        r = subprocess.run([shell, "-c", script], capture_output=True, text=True, errors="replace", timeout=10,
                           cwd="/tmp")
    except subprocess.TimeoutExpired:
        return False
    return r.stdout == "BODY\nRAN\n"


def truth(w):
    reads = {next((t for t in candidates(w) if ends_at(s, ctx, w, t)), None)
             for s in SHELLS for ctx in ("top", "merge body")}
    return reads.pop() if len(reads) == 1 else None


def awk_func(hook):
    text = open(os.path.join(HOOKS, hook), encoding="utf-8").read()
    return re.search(r"^  function hdword\(.*?^  \}\n", text, re.S | re.M).group(0)


def ship_scan_func(hook):
    text = open(os.path.join(HOOKS, hook), encoding="utf-8").read()
    return re.search(r"^ship_scan\(\) \{\n.*?^\}\n", text, re.S | re.M).group(0)


words = corpus()
with ThreadPoolExecutor(8) as pool:
    shells = list(pool.map(truth, words))
funcs = {h: awk_func(h) for h in ("qa-ship-gate-hook.sh", "coordinator-hook-pretool.sh")}
bad = 0
if len(set(funcs.values())) != 1:
    print("BAD the two hooks' hdword() differ")
    bad += 1
prog = funcs["qa-ship-gate-hook.sh"] + ('{ if (hdword($0, 1)) { if (HK == length($0) + 1) print "R" HW; else print "P" }'
                                        ' else print "U" }')
awk = subprocess.run(["awk", "-v", "sq='", prog], input="\n".join(words).encode() + b"\n", capture_output=True,
                     env={**os.environ, "LC_ALL": "C"}).stdout.split(b"\n")[:len(words)]
read, residual = [], []
for w, want, a in zip(words, shells, awk):
    got = gate._heredoc_word(w + "\n", 0)
    py = b"P" if got is not None and got[1] != len(w) else (b"R" + got[0].encode() if got else b"U")
    if py != a:
        bad += 1
        print(f"BAD gate and awk differ on {w!r}: gate {py!r} awk {a!r}")
    if py[:1] == b"R":
        if want is None or py[1:] != want.encode():
            bad += 1
            print(f"BAD reads {w!r} as {py[1:]!r}; the shells read {want!r}")
        else:
            read.append(w)
    elif py == b"U" and want is not None:
        residual.append(w)
scans = {h: ship_scan_func(h) for h in funcs}
for i, w in enumerate(read):
    merge = f'gh pr merge 5 --body "$(cat <<{w}\n{PUSH}\n{gate._heredoc_word(w + chr(10), 0)[0]}\n)"'
    for cmd, want in ((merge, False), (merge + f"\n{PUSH}", True)):
        seen = any(s[:2] == ["git", "push"] for s in gate.command_segments(cmd))
        if seen != want:
            bad += 1
            print(f"BAD command_segments sees a push {seen}, want {want}: {cmd!r}")
        if i % 4:
            continue  # both awk copies on every fourth readable word
        payload = json.dumps({"tool_input": {"command": cmd}, "cwd": "/"})
        for h, f in scans.items():
            got = subprocess.run(["sh", "-c", f"input=$(cat)\n{f}ship_scan"], input=payload, capture_output=True,
                                 text=True).stdout.split()[:1] == ["1"]
            if got != want:
                bad += 1
                print(f"BAD {h} ship_scan sees a push {got}, want {want}: {cmd!r}")
agree = sum(t is not None for t in shells)
print(f"heredoc words: {len(words)} generated, {agree} read alike by {len(SHELLS)} shells at top level and in a merge "
      f"body; the gate and awk read {len(read)}, decline {len(residual)} of those (residual: a merge using one is "
      f"denied), {bad} bad")
for w in residual[:20]:
    print(f"  residual {w!r}")
sys.exit(1 if bad else 0)
