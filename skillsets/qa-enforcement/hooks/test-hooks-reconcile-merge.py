#!/usr/bin/env python3
"""Each side of the qa-ship-gate-hook merge must fail alone and pass merged (HOOKS-RECONCILE)."""
import json
import os
import re
import subprocess
import sys

HOOKS = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HOOKS, "..", "..", ".."))
HOOK_PATH = "skillsets/qa-enforcement/hooks/qa-ship-gate-hook.sh"
# origin/main immediately before this PR; reachable from the PR head without a named remote ref.
KIT_ONLY_REV = "127d59eb8481b767df447516532923fc9a66cf01"
MERGED = os.path.join(HOOKS, "qa-ship-gate-hook.sh")


def ship_scan_func(text: str) -> str:
    match = re.search(r"^ship_scan\(\) \{\n.*?^\}\n", text, re.S | re.M)
    if not match:
        raise SystemExit("hook text has no ship_scan() function block")
    return match.group(0)


def git_show_hook(rev: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", REPO_ROOT, "show", f"{rev}:{HOOK_PATH}"],
            text=True,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or exc.stdout or str(exc)).strip()
        raise SystemExit(f"cannot read {rev}:{HOOK_PATH} from repo root: {msg}") from exc


def rdel_scan(hook_text: str, command: str) -> str:
    payload = json.dumps({"tool_input": {"command": command}, "cwd": "/tmp"})
    script = f"input=$(cat)\n{ship_scan_func(hook_text)}ship_scan"
    return subprocess.run(
        ["sh", "-c", script],
        input=payload,
        text=True,
        capture_output=True,
        env={**os.environ, "SHIP_SCAN_RDEL": "1", "LC_ALL": "C"},
    ).stdout.strip()


def heredoc_unreadable(hook_text: str) -> bool:
    """Unquoted EOF body with $( sets SFAIL in strip(); ship_scan then fails to read (FAIL/flat)."""
    cmd = 'gh pr merge 5 --body "$(cat <<EOF\n$(id)\nEOF\n)"'
    payload = json.dumps({"tool_input": {"command": cmd}, "cwd": "/tmp"})
    script = f"input=$(cat)\n{ship_scan_func(hook_text)}ship_scan"
    out = subprocess.run(
        ["sh", "-c", script],
        input=payload,
        text=True,
        capture_output=True,
        env={**os.environ, "SHIP_SCAN_VIEW": "1", "LC_ALL": "C"},
    ).stdout.strip()
    return out.startswith("FLAT")


def without_pq_heredoc(hook_text: str) -> str:
    t = hook_text.replace(
        "function strip(s,   out, st, top, pd, pw, ps, pq, np, hp, w, i, n, c, nx, j, k, dl, dash, line, x) {",
        "function strip(s,   out, st, top, pd, pw, ps, np, hp, w, i, n, c, nx, j, k, dl, dash, line) {",
    )
    t = re.sub(
        r"            if \(!pq\[hp\] && \(index\(line, \"\$\(\".*?\n",
        "",
        t,
        count=1,
    )
    t = t.replace(
        "        k = HK; dl = HW; x = substr(s, j, k - j)\n"
        '        np++; pd[np] = dash; pw[np] = dl; ps[np] = st; pq[np] = (index(x, sq) || index(x, "\\"") || index(x, "\\\\")); i = k - 1; w = 1; continue',
        "        k = HK; dl = HW\n        np++; pd[np] = dash; pw[np] = dl; ps[np] = st; i = k - 1; w = 1; continue",
    )
    return t


def main() -> int:
    merged = open(MERGED, encoding="utf-8").read()
    kit_only = git_show_hook(KIT_ONLY_REV)
    inst_only = without_pq_heredoc(merged)
    rdel_cmd = "git push origin :refs/heads/gone"
    bad = 0
    cases = [
        ("rdel merged blocks", rdel_scan(merged, rdel_cmd) == "1", True),
        ("rdel kit-only allows", rdel_scan(kit_only, rdel_cmd) == "1", False),
        ("heredoc merged unreadable", str(heredoc_unreadable(merged)), "True"),
        ("heredoc installed-side reads", str(heredoc_unreadable(inst_only)), "False"),
    ]
    for name, got, want in cases:
        ok = got == want
        bad += not ok
        print(f"{'ok' if ok else 'BAD'} {name}: got {got!r} want {want!r}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
