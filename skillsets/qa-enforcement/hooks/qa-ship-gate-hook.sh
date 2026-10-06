#!/bin/sh
# PreToolUse adapter for the QA ship gate (Claude Code + Codex via
# coordinator-hook-pretool.sh). Reads the hook payload on stdin.
#   exit 0 + no output = allow; exit 2 + JSON/stderr = deny.
# Fails OPEN except for ship commands in .qa-opted-in repos, where the python
# gate denies on any internal error (fail closed). If python itself is
# missing, a POSIX fallback still denies ship commands in an opted-in repo (or
# one that moves to another directory first) so the fail-closed property does
# not depend on the interpreter being present. PR merges are never denied
# (owner decision 2026-10-06).
GATE="$HOME/.agents/skills/qa-sweep/scripts/ship-gate.py"
input=$(cat)
set +e
if [ -f "$GATE" ]; then
  printf '%s' "$input" | python3 "$GATE" hook
  rc=$?
else
  # v4: `python3 <missing file>` exits 2, which read as a DENY of every
  # command (ls included); a missing gate goes to the shape fallback instead
  rc=127
fi
set -e
if [ "$rc" = 0 ] || [ "$rc" = 2 ]; then
  exit "$rc"
fi
scope_flat() { printf '%s' "$input" | tr -d '\\"'"'"; }
# --- opted-in shape (identical in coordinator-hook-pretool.sh and
# qa-ship-gate-hook.sh; test-hook-chain.sh checks the two copies match) ---
# The command as one line of words, read from the JSON payload. A line
# continuation (backslash-newline) is removed, as /bin/sh does. Other newline,
# tab and CR escapes become spaces, quotes and backslashes go, and runs of
# spaces squeeze to one.
ship_flat() { printf '%s' "$input" | sed -e 's/\\\\\\n//g' -e 's/\\[ntr]/ /g' | tr -d '\\"'"'" | tr -s ' '; }
# Ship shape: the gate's coarse classes, read with quotes and backslashes
# removed so a quoted path cannot hide the command. PR merges are not in it:
# no gate ever denies a PR merge (owner decision 2026-10-06).
ship_shape() {
  ship_flat | grep -qE 'git( [^ ;&|]+)* push|gh (release (create|edit)|workflow run)|vercel[^;&|]*(--prod|--target[= ]production|promote|redeploy|alias|rolling-release)|netlify[^;&|]*deploy[^;&|]*--prod|fly(ctl)? deploy|/v[0-9]+/deployments|/v[0-9]+/projects/[^ ]*/promote/|repos/[^ ]*/(merges|releases|git/refs|dispatches|contents/|deployments)|createCommitOnBranch|updateRef'
}
qa_opted_in() {
  _d=${input#*\"cwd\"}
  if [ "$_d" = "$input" ]; then _d=$PWD; else _d=${_d#*\"}; _d=${_d%%\"*}; fi
  while [ -n "$_d" ] && [ "$_d" != / ]; do
    [ -f "$_d/.qa/config.json" ] && return 0
    _d=${_d%/*}
  done
  return 1
}
# A command that picks another repository before it ships: cd/pushd (also in
# a subshell or sh -c), git -C, env -C/--chdir, --git-dir, GIT_DIR. A work
# tree alone (--work-tree, GIT_WORK_TREE) does not pick the repository.
moves_dir() {
  ship_flat | grep -qE '(^|[^A-Za-z0-9_./-])(cd|pushd) |git( [^ ;&|]+)* -C |env( [^ ;&|]+)* (-C |--chdir)|--git-dir|GIT_DIR='
}
# A plain PR merge: the payload's command is only `gh pr merge ...`, after
# optional `cd DIR &&` steps and NAME=value prefixes, with no other separator
# and no substitution, so it runs nothing else. Quoted text in it is an
# argument: a subject or body naming a push or a deploy is not a ship. The
# same scanner as ship-gate.py's pure_pr_merge; test-ship-matrix.py checks
# that the two agree.
pure_merge() {
  printf '%s' "$input" | tr '\n' ' ' | LC_ALL=C awk -v sq="'" '
  { s = s $0 }
  END {
    if (!match(s, /"command"[ \t]*:[ \t]*"/)) exit 1
    n = length(s); cmd = ""
    for (i = RSTART + RLENGTH; i <= n; i++) {
      c = substr(s, i, 1)
      if (c == "\"") break
      if (c == "\\") {
        e = substr(s, ++i, 1)
        if (e == "n") c = "\n"; else if (e == "t") c = "\t"; else if (e == "r") c = "\r"
        else if (e == "\"" || e == "\\" || e == "/") c = e
        else if (e == "u" && tolower(substr(s, i + 1, 4)) ~ /^00[89a-f][0-9a-f]|^0[1-9a-f][0-9a-f][0-9a-f]|^[1-9a-f][0-9a-f][0-9a-f][0-9a-f]/) { c = "?"; i += 4 }
        else exit 1
      }
      cmd = cmd c
    }
    if (i > n) exit 1
    n = length(cmd); q = ""; cur = ""; has = 0; nw = 0
    for (i = 1; i <= n; i++) {
      c = substr(cmd, i, 1); d = substr(cmd, i + 1, 1)
      if (q == sq) { if (c == sq) q = ""; else cur = cur c; continue }
      if (q == "\"") {
        if (c == "\"") q = ""
        else if (c == "\\" && d != "" && index("$`\"\\\n", d)) { if (d != "\n") cur = cur d; i++ }
        else if (c == "`" || (c == "$" && d == "(")) exit 1
        else cur = cur c
        continue
      }
      if (c == "\\" && d != "") { if (d != "\n") { cur = cur d; has = 1 }; i++; continue }
      if (c == " " || c == "\t") { if (has) { w[++nw] = cur; cur = ""; has = 0 }; continue }
      if (c == "&" && d == "&") {
        if (has) { w[++nw] = cur; cur = ""; has = 0 }
        if (!(nw == 2 && (w[1] == "cd" || w[1] == "pushd"))) exit 1
        nw = 0; i++; continue
      }
      if (c == "&" && i > 1 && index("<>", substr(cmd, i - 1, 1))) { cur = cur c; continue }
      if (index(";&|()`\n\r", c)) exit 1
      if (c == "\"" || c == sq) { q = c; has = 1; continue }
      cur = cur c; has = 1
    }
    if (q != "") exit 1
    if (has) w[++nw] = cur
    for (k = 1; k <= nw && w[k] ~ /^[A-Za-z_][A-Za-z0-9_]*=/; k++) ;
    exit !(w[k] == "gh" && w[k + 1] == "pr" && w[k + 2] == "merge")
  }'
}
# --- end opted-in shape ---
# python missing or crashed before it could decide: decide by shape alone.
# v4: releases (v5: gh release edit too), workflow dispatch and deployments-API
# posts join the coarse shapes (any git push already covers tags/--tags/--mirror); the shapes match
# anywhere in the command (`cd x && git push` included), and fly(ctl) is a
# real alternation (the old `flyctl\?` only matched a literal "?").
if ship_shape && ! pure_merge && { qa_opted_in || moves_dir; }; then
  echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "[qa-ship-gate] gate could not run but a ship command was attempted in a QA opted-in repo; treat as denied and complete the .qa pipeline"}}'
  echo "[qa-ship-gate] gate could not run; ship treated as denied" >&2
  exit 2
fi
exit 0
