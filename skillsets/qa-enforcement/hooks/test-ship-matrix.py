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


def run(mode, cmd, cwd):
    payload = json.dumps({"session_id": "matrix", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})
    if mode == "gate":
        return sh(f'python3 "{GATE}" hook', cwd, payload).returncode
    env = {**os.environ, "HOME": fake_home}
    return sh(f'sh "{ADAPTER}"', cwd, payload, env).returncode


rows, bad = [], 0
for cwd_name, cwd in (("plain checkout", P), ("non-repo dir", N)):
    cases = [(c, 2) for c in DENY] + [(c, 0) for c in ALLOW]
    if cwd is P:
        cases.append((f"GIT_DIR={REL} git push origin main", 2))
    for cmd, want in cases:
        for mode in ("gate", "fallback"):
            got = run(mode, cmd, cwd)
            ok = got == want
            bad += not ok
            rows.append((cmd.replace(O, "<opted>"), cwd_name, mode, "deny" if want == 2 else "allow",
                         {0: "allow", 2: "deny"}.get(got, f"rc {got}"), ok))
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
