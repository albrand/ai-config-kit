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
# Pallium production-data changes have an additional mandatory evidence gate,
# independent of whether the repository opted into the general .qa pipeline.
REALDATA_GATE="$HOME/.agents/skills/qa-sweep/scripts/realdata-replay-gate.py"
scope_flat() { printf '%s' "$input" | tr -d '\\"'"'"; }
# --- opted-in shape (identical in coordinator-hook-pretool.sh and
# qa-ship-gate-hook.sh; test-hook-chain.sh checks the two copies match) ---
# What the command would run, as one line of words, read from the JSON
# payload in one awk pass. The command string is decoded, then split into
# segments at unquoted ; & | ( ) and newlines, comments dropped; a line that
# starts with && || or | is a syntax error, so nothing after it runs (unless
# the command has a heredoc). A `gh pr
# merge` segment (after
# NAME=value prefixes and env/command/nohup/time/exec/sudo/nice) keeps only
# the bodies of its $(...) and backtick substitutions: its quoted subject or
# body is an argument and never runs, so a PR merge is never denied for what
# it says (owner decision 2026-10-06). `sh -c SCRIPT` and `eval` are read as
# the script they run. A line continuation is removed, as /bin/sh does; quotes
# and backslashes go; whitespace becomes single spaces. If the command can't
# be read (no command field, unbalanced quotes, an escape it doesn't decode),
# the whole payload is read flat instead. ship-gate.py's ship_view is the same
# scanner; test-ship-matrix.py checks that the two agree.
# Prints "<ship> <moves>": ship, the gate's coarse ship classes; moves, a
# command that picks another repository first (cd/pushd, git -C, env
# -C/--chdir, --git-dir, GIT_DIR; a work tree alone does not pick one).
ship_scan() {
  printf '%s' "$input" | LC_ALL=C awk -v sq="'" -v show="${SHIP_SCAN_VIEW:-}" '
  function decode(s,   i, n, c, e, out) {
    if (!match(s, /"command"[ \t]*:[ \t]*"/)) return "\001"
    n = length(s); out = ""
    for (i = RSTART + RLENGTH; i <= n; i++) {
      c = substr(s, i, 1)
      if (c == "\"") return out
      if (c == "\\") {
        e = substr(s, ++i, 1)
        if (e == "n") c = "\n"; else if (e == "t") c = "\t"; else if (e == "r") c = "\r"
        else if (e == "\"" || e == "\\" || e == "/") c = e
        else if (e == "u" && tolower(substr(s, i + 1, 4)) ~ /^(00[89a-f]|0[1-9a-f][0-9a-f]|[1-9a-f][0-9a-f][0-9a-f])[0-9a-f]$/) { c = "?"; i += 4 }
        else return "\001"
      }
      out = out c
    }
    return "\001"
  }
  function bare(w) { sub(/.*\//, "", w); return w }
  function shscript(d, k, nw,   j, c, w) {
    # The index of the script that the -c of a shell runs, after its options (sh -e -c, bash -lc, bash -o pipefail -c,
    # bash -c -e, bash --norc -c), or 0. Same reading as ship-gate.py shell_script_index (Hermes r22).
    c = 0
    for (j = k + 1; j <= nw; j++) {
      w = W[d, j]
      if (w == "--") { j++; break }
      if (w ~ /^[-+][oO]$/ || w == "--rcfile" || w == "--init-file" || w == "--emulate") { j++; continue }
      if (w ~ /^--./) continue
      if (w ~ /^-[A-Za-z]+$/) { if (w ~ /c/) c = 1; continue }
      if (w ~ /^\+[A-Za-z]+$/) continue
      break
    }
    return (c && j <= nw) ? j : 0
  }
  function emit(d, nw, seg, subs,   k, h, script, j) {
    k = 1
    while (k <= nw) {
      h = bare(W[d, k])
      if (W[d, k] ~ /^[A-Za-z_][A-Za-z0-9_]*=/) { k++; continue }
      if (h == "env" || h == "command" || h == "nohup" || h == "time" || h == "exec" || h == "sudo" || h == "nice") {
        k++
        while (k <= nw && W[d, k] ~ /^-/) { if (W[d, k] ~ /^(-C|-u|-n|--chdir|--unset)$/) k++; k++ }
        continue
      }
      break
    }
    if (k > nw) return seg
    h = bare(W[d, k])
    if (h == "gh" && k + 2 <= nw && W[d, k + 1] == "pr" && W[d, k + 2] == "merge") return subs
    if (d < 3 && (h == "sh" || h == "bash" || h == "zsh" || h == "dash") && (j = shscript(d, k, nw)))
      return view(W[d, j], d + 1) subs
    if (d < 3 && h == "eval" && k < nw) {
      script = W[d, k + 1]
      for (j = k + 2; j <= nw; j++) script = script " " W[d, j]
      return view(script, d + 1) subs
    }
    return seg
  }
  function hdword(s, j,   n, k, c, x, nx, e, body, out, tail, d, t, plain, hp, hq) {
    # The heredoc word at s[j]: sets HW (delimiter) and HK (index after it) and returns 1, or returns 0 when the
    # shells might read it differently. Same reader as ship-gate.py _heredoc_word, measured against bash, zsh,
    # sh and dash by hooks/test-heredoc-words.py (Hermes r10, r11, r13). Bytes above 127 are plain (LC_ALL=C).
    hp = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.+,:@%/!^-#~=*?[]{}$"
    hq = "\"" sq "()`"
    n = length(s); k = j; out = ""; tail = ""
    c = substr(s, j, 1)
    if (c == "#" || c == "-") return 0
    while (k <= n) {
      c = substr(s, k, 1); nx = substr(s, k + 1, 1)
      plain = (index(hp, c) > 0 || c > "\177")
      if (!(plain || c == "\\" || c == sq || c == "\"")) break
      tail = plain ? c : ""
      if (c == "\\") {
        if (nx == "" || nx == "\n" || index(hq, nx)) return 0
        out = out nx; k += 2
      } else if (c == "$" && (nx == sq || nx == "\"")) {
        return 0
      } else if (c == sq) {
        k++
        e = index(substr(s, k), sq); if (!e) return 0
        body = substr(s, k, e - 1)
        if (index(body, "\n") || index(body, "\"") || index(body, "(") || index(body, ")") || index(body, "`")) return 0
        out = out body; k += e
      } else if (c == "\"") {
        k++
        for (;;) {
          d = substr(s, k, 1)
          if (d == "" || d == "\n" || (d != "\"" && index(hq, d))) return 0
          k++
          if (d == "\"") break
          if (d == "\\") {
            x = substr(s, k, 1)
            if (x == "" || x == "\n" || index(hq, x)) return 0
            out = out ((x == "$" || x == "\\") ? x : "\\" x); k++
          } else out = out d
        }
      } else { out = out c; k++ }
    }
    if (k == j || (k <= n && !index(" \t\n;&|<>", substr(s, k, 1)))) return 0
    if (out == "" || substr(out, length(out), 1) == "\\" || tail == "}") return 0
    t = substr(s, j, k - j)
    if (index(t, "${") || index(t, "$[") || index(t, "$(")) return 0
    HW = out; HK = k; return 1
  }
  function strip(s,   out, st, top, pd, pw, ps, np, hp, w, i, n, c, nx, j, k, dl, dash, line) {
    # The command without heredocs, or SFAIL = 1 when one is not read exactly. Same contract as the ship-gate.py
    # _strip_heredoc_bodies (Hermes r10, r11): a real << is code, not quoted, escaped, commented, arithmetic or in
    # ${...} / $[...]; <<< is a here-string. Its delimiter must be a word hdword() reads (one the shells read
    # alike), its context must still be open where the body starts, a terminator line must exist, and no body
    # line may start with the delimiter and go on. Anything else is unreadable, so the raw text is scanned.
    out = ""; st = ""; np = 0; hp = 1; w = 0; n = length(s); SFAIL = 0
    for (i = 1; i <= n; i++) {
      c = substr(s, i, 1); nx = substr(s, i + 1, 1); top = substr(st, length(st), 1)
      if (top == sq) { out = out c; if (c == sq) st = substr(st, 1, length(st) - 1); continue }
      if (c == "\\" && nx != "") { out = out c nx; i++; w = 1; continue }
      if (top == "\"" || top == "{" || top == "[") {
        out = out c
        if ((top == "\"" && c == "\"") || (top == "{" && c == "}") || (top == "[" && c == "]")) st = substr(st, 1, length(st) - 1)
        else if (c == "`") st = st "`"
        else if (c == "$" && (nx == "(" || nx == "{" || nx == "[")) { out = out nx; st = st (nx == "(" ? "$" : nx); i++ }
        else if ((c == sq || c == "\"") && top != "\"") st = st c
        continue
      }
      if (top == "A" || top == "a") {
        out = out c
        if (c == "(") st = st "a"
        else if (c == ")" && top == "a") st = substr(st, 1, length(st) - 1)
        else if (c == ")" && nx == ")") { out = out nx; st = substr(st, 1, length(st) - 1); i++ }
        continue
      }
      if (c == "\n" && np >= hp) {
        for (k = hp; k <= np; k++) if (ps[k] != st) { SFAIL = 1; return "" }
        out = out c; i++
        for (; hp <= np; hp++) {
          for (;;) {
            if (i > n) { SFAIL = 1; return "" }
            for (j = i; j <= n && substr(s, j, 1) != "\n"; j++);
            line = substr(s, i, j - i); i = j + 1
            if (pd[hp]) sub(/^\t+/, "", line)
            if (line == pw[hp]) break
            if (index(line, pw[hp]) == 1) { SFAIL = 1; return "" }
          }
        }
        np = 0; hp = 1; w = 0; i--; continue
      }
      if (c == "#" && !w) { for (j = i; j <= n && substr(s, j, 1) != "\n"; j++); out = out substr(s, i, j - i); i = j - 1; continue }
      if (c == "<" && nx == "<" && substr(s, i + 2, 1) != "<" && (i == 1 || substr(s, i - 1, 1) != "<")) {
        j = i + 2; dash = (substr(s, j, 1) == "-"); if (dash) j++
        while (j <= n && (substr(s, j, 1) == " " || substr(s, j, 1) == "\t")) j++
        if (!hdword(s, j)) { SFAIL = 1; return "" }
        k = HK; dl = HW
        np++; pd[np] = dash; pw[np] = dl; ps[np] = st; i = k - 1; w = 1; continue
      }
      out = out c
      if (c == sq || c == "\"") st = st c
      else if (c == "`") { if (top == "`") st = substr(st, 1, length(st) - 1); else st = st "`" }
      else if (c == "$" && substr(s, i + 1, 2) == "((") { out = out "(("; st = st "A"; i += 2 }
      else if (c == "$" && (nx == "(" || nx == "{" || nx == "[")) { out = out nx; st = st (nx == "(" ? "$" : nx); i++ }
      else if (c == "(" && nx == "(" && !w) { out = out "("; st = st "A"; i++ }
      else if (c == "(") st = st "("
      else if (c == ")" && (top == "$" || top == "(")) st = substr(st, 1, length(st) - 1)
      w = !index(" \t\n;&|()<>", c)
    }
    if (np >= hp) { SFAIL = 1; return "" }
    return out
  }
  function view(cmd, d,   out, seg, subs, nw, cur, has, q, i, n, c, nx, j, dep, body, ls, hd) {
    cmd = strip(cmd); if (SFAIL) { FAIL = 1; return "" }
    out = ""; seg = ""; subs = ""; nw = 0; cur = ""; has = 0; q = ""; n = length(cmd)
    ls = 1; hd = 0
    for (i = 1; i <= n; i++) {
      c = substr(cmd, i, 1); nx = substr(cmd, i + 1, 1)
      if (q == sq) { seg = seg c; if (c == sq) q = ""; else cur = cur c; continue }
      if (c == "\\" && nx != "") {
        i++
        if (nx == "\n") continue
        seg = seg c nx; has = 1
        if (q == "\"" && index("$`\"\\", nx) == 0) cur = cur c nx; else cur = cur nx
        continue
      }
      if (c == "`" || (c == "$" && nx == "(")) {
        if (c == "`") {
          for (j = i + 1; j <= n && substr(cmd, j, 1) != "`"; j++) if (substr(cmd, j, 1) == "\\") j++
          if (j > n) { FAIL = 1; return "" }
          body = substr(cmd, i + 1, j - i - 1)
        } else {
          dep = 1
          for (j = i + 2; j <= n && dep > 0; j++) { if (substr(cmd, j, 1) == "(") dep++; else if (substr(cmd, j, 1) == ")") dep-- }
          if (dep > 0) { FAIL = 1; return "" }
          j--
          body = substr(cmd, i + 2, j - i - 2)
        }
        subs = subs " ; " body; seg = seg substr(cmd, i, j - i + 1); cur = cur "$()"; has = 1; i = j
        continue
      }
      if (q == "\"") { seg = seg c; if (c == "\"") q = ""; else cur = cur c; continue }
      if (c == sq || c == "\"") { q = c; has = 1; seg = seg c; continue }
      if (c == " " || c == "\t") { if (has) { W[d, ++nw] = cur; cur = ""; has = 0 }; seg = seg c; continue }
      if (c == "&" && i > 1 && index("<>", substr(cmd, i - 1, 1))) { cur = cur c; has = 1; seg = seg c; continue }
      if (c == "#" && !has) { for (j = i; j <= n && substr(cmd, j, 1) != "\n"; j++); i = j - 1; continue }
      if ((c == "&" || c == "|") && ls && !has && nw == 0 && !hd) return out
      if (index(";&|()\n\r", c)) {
        ls = (c == "\n")
        if (has) { W[d, ++nw] = cur; cur = ""; has = 0 }
        out = out emit(d, nw, seg, subs) " ; "; seg = ""; subs = ""; nw = 0
        continue
      }
      if (c == "<" && nx == "<") hd = 1
      cur = cur c; has = 1; seg = seg c
    }
    if (q != "") { FAIL = 1; return "" }
    if (has) W[d, ++nw] = cur
    return out emit(d, nw, seg, subs)
  }
  { s = s (NR > 1 ? " " : "") $0 }
  END {
    FAIL = 0; cmd = decode(s); flat = 0
    if (cmd != "\001") { v = view(cmd, 0); if (FAIL) flat = 1 } else flat = 1
    if (flat) { v = s; gsub(/\\\\\\n/, "", v); gsub(/\\[ntr]/, " ", v) }
    gsub(/[\t\r\n]/, " ", v); gsub(/[\\"]/, "", v); gsub(sq, "", v); gsub(/  +/, " ", v)
    if (show) { print (flat ? "FLAT " : "") v; exit }
    ship = v ~ /git( [^ ;&|]+)* push|gh (release (create|edit)|workflow run)|vercel[^;&|]*(--prod|--target[= ]production|promote|redeploy|alias|rolling-release)|netlify[^;&|]*deploy[^;&|]*--prod|fly(ctl)? deploy|\/v[0-9]+\/deployments|\/v[0-9]+\/projects\/[^ ]*\/promote\/|repos\/[^ ]*\/(merges|releases|git\/refs|dispatches|contents\/|deployments)|createCommitOnBranch|updateRef/
    moves = v ~ /(^|[^A-Za-z0-9_.\/-])(cd|pushd) |git( [^ ;&|]+)* -C |env( [^ ;&|]+)* (-C |--chdir)|--git-dir|GIT_DIR=/
    print ship " " moves
  }'
}
ship_shape() { [ -n "${ship_flags:-}" ] || ship_flags=$(ship_scan); [ -n "$ship_flags" ] || ship_flags="1 0"; case $ship_flags in 1*) return 0 ;; esac; return 1; }
moves_dir() { [ -n "${ship_flags:-}" ] || ship_flags=$(ship_scan); [ -n "$ship_flags" ] || ship_flags="1 0"; case $ship_flags in *1) return 0 ;; esac; return 1; }
qa_opted_in() {
  _d=${input#*\"cwd\"}
  if [ "$_d" = "$input" ]; then _d=$PWD; else _d=${_d#*\"}; _d=${_d%%\"*}; fi
  while [ -n "$_d" ] && [ "$_d" != / ]; do
    [ -f "$_d/.qa/config.json" ] && return 0
    _d=${_d%/*}
  done
  return 1
}
# --- end opted-in shape ---
# The replay gate reads what the command would run: a PR merge or ready, and
# whatever its quoted subject or body says, is never denied (owner decision
# 2026-10-08). The awk view (in its own subshell, so no variable leaks into the
# shape checks below) goes to the gate, which uses it when ship-gate.py can't
# give its own reading (Hermes 2026-10-08 r18). A missing gate denies review,
# PR creation and release, read from the same view; a command that can't be
# read is matched in the payload's command field.
realdata_view=$(SHIP_SCAN_VIEW=1 ship_scan) || realdata_view="FLAT "
if [ -f "$REALDATA_GATE" ]; then
  set +e
  printf '%s' "$input" | python3 "$REALDATA_GATE" hook --view-fd=3 3<<REALDATA_VIEW
$realdata_view
REALDATA_VIEW
  realdata_rc=$?
  set -e
  if [ "$realdata_rc" = 2 ]; then
    exit 2
  elif [ "$realdata_rc" != 0 ]; then
    echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[realdata-replay-gate] the gate failed; retry after repairing the installed gate"}}'
    echo "[realdata-replay-gate] gate failed (exit $realdata_rc); command denied" >&2
    exit 2
  fi
else
  case $realdata_view in
    "FLAT "*) printf '%s' "$input" | grep -qiE '"command"[^:]*:[^"]*"[^"]*(hermes-one\.zsh?|bb[[:space:]]+fleet[[:space:]]+validate|gh[[:space:]]+pr[[:space:]]+create|gh[[:space:]]+release|release[-[:space:]]request)' ;;
    *) printf '%s' "$realdata_view" | grep -qiE '(hermes-one\.zsh?|bb fleet validate|gh pr create|gh release|release[- ]request)' ;;
  esac && {
    echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[realdata-replay-gate] the required gate is missing; review or release denied"}}'
    echo "[realdata-replay-gate] required gate is missing; command denied" >&2
    exit 2
  }
fi
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
# python missing or crashed before it could decide: decide by shape alone.
# v4: releases (v5: gh release edit too), workflow dispatch and deployments-API
# posts join the coarse shapes (any git push already covers tags/--tags/--mirror); the shapes match
# anywhere in the command (`cd x && git push` included), and fly(ctl) is a
# real alternation (the old `flyctl\?` only matched a literal "?").
if ship_shape && { qa_opted_in || moves_dir; }; then
  echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "[qa-ship-gate] gate could not run but a ship command was attempted in a QA opted-in repo; treat as denied and complete the .qa pipeline"}}'
  echo "[qa-ship-gate] gate could not run; ship treated as denied" >&2
  exit 2
fi
exit 0
