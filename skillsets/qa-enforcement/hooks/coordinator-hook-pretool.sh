#!/bin/sh
# pretool adapter for coordinator-mode (no argv: Codex runs hook commands as a path).
# Since 2026-09-24 the QA ship gate runs first: it denies ship commands
# (protected pushes, releases, deploys) in repos that opted in
# with a committed .qa/config.json, and allows everything else. PR merges are
# always allowed, gh pr ready included (2026-10-06).
# Since 2026-09-25 the scope gate runs second: from a thread with a scope
# ledger, a spawn or tell must say which open purpose it serves.
# Non-ship behaviour is unchanged: it falls through to coordinator-hook.sh,
# which still blocks coordinator-mode edits exactly as before.
#
# One clock for the whole chain, and this script holds it. A PreToolUse hook
# the host times out does not block: the command runs (Claude Code 2.1.282
# probed live; Codex 0.157.0 pre_tool_use.rs). A gate that keeps its own
# deadline in Python only starts keeping it after sh, the wrapper and the
# interpreter are up, which cost 2-3.5 s at load 160-213 (review r1). So each
# stage runs under a supervisor here: a gate stage still running
# GATE_DEADLINE s after HOOK_T0 is killed with its whole process group and
# the command is decided by shape in this shell, with no Python; a gate stage
# reached after the deadline is not started at all. The last stage is cut at
# CHAIN_DEADLINE and fails open, as a host timeout would, but inside it.
# Budget (host timeout 15 s, hooks/hook-timeouts.py): shell start before
# HOOK_T0 plus the shape decision plus exit stay under 3 s at load ~200.
GATE_DEADLINE=11
CHAIN_DEADLINE=12.5
HOOK_T0=$(perl -MTime::HiRes=time -e 'printf "%.3f", time' 2>/dev/null)
export HOOK_T0
input=$(cat)
H="$HOME/.agent-hooks"

# run <deadline> <command...>: stdin passes through. 124 when the deadline
# had passed or the stage was killed at it; otherwise the stage's own rc.
run() {
  perl -MTime::HiRes=time,alarm -e '
    my $left = shift(@ARGV) - (time - $ENV{HOOK_T0});
    exit 124 if $left <= 0;
    my $pid = fork;
    exit 125 unless defined $pid;
    if (!$pid) { setpgrp(0, 0); exec { $ARGV[0] } @ARGV; exit 127 }
    setpgrp($pid, $pid);
    $SIG{ALRM} = sub { kill "KILL", -$pid; kill "KILL", $pid; waitpid($pid, 0); exit 124 };
    alarm $left;
    waitpid($pid, 0);
    alarm 0;
    exit(($? & 127) ? 128 + ($? & 127) : $? >> 8);
  ' "$@"
}
if [ -z "$HOOK_T0" ]; then  # no perl: no supervisor, the stages run as before
  run() { shift; "$@"; }
fi

deny() {
  printf '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "%s"}}\n' "$1"
  printf '%s\n' "$1" >&2
  exit 2
}
# --- scope shape (identical in coordinator-hook-pretool.sh and scope-gate-hook.sh;
# test-hook-chain.sh checks the two copies match) ---
# A dispatch-shaped call from a thread with a scope ledger is allowed only
# when it names an OPEN purpose (serves: P<n>) or quotes an accepted revision;
# an unknown or blocked id does not count. Only the call's own words count
# (review r2b): a gated agent tool's text fields, or the command; never the
# tool call's description or a comment, and no brief file is read (a FIFO
# would block). Each dispatch serves on its own (review r2c): the command is
# split at every ; & | ( ) and newline, quoted or not, and each stretch that
# reads like a dispatch must name the purpose itself; a stretch that runs a
# nested script (sh -c, eval, --script, <<<, env -S) never serves. One jq run
# reads the payload and the ledger, the same decision as scope-gate.py's
# `shape` (shape_text + shape_serves); no jq, or no answer from it, denies any
# dispatch word or ANSI-C escape (fails closed). At the deadline a serves line
# after a separator inside the brief, or in a heredoc body, is in another
# stretch and does not count (a deny; the normal decision reads them). A
# command, group or verb word a substitution is glued into is dispatch-shaped
# (review r2d: the split eats a `$(...`'s parens, so `bb automation$(echo)
# run` survives only as a word-final `$`; a backtick or `${` glued to a word
# (`bb th`x`read tell`, `bb automation${X} run`) keeps the stretch whole),
# and so is a `$(...)` as its own word in the verb zone (`bb thread $(echo)
# tell`: a space before the stretch's final `$`, with a dispatch word in the
# stretch; `echo "$(date)"` has none and stays allowed): what runs is
# unknown, and the stretch must serve like any dispatch.
SCOPE_SHAPE_JQ='
def flat: gsub("[\\\\\"\\x27]"; "");
def collapse: gsub("\\s+"; " ") | sub("^ "; "") | sub(" $"; "");
def gluedvar: test("(^|\\s)([^\\s;&|()]+/)?(bb|\\$BB_CLI|\\$\\{BB_CLI[^}]*\\})\\s+(--[A-Za-z-]+(=\\S+)?\\s+)*(thread|fleet|automation|instructions)\\$[A-Za-z0-9_]|(^|\\s)([^\\s;&|()]+/)?(bb|\\$BB_CLI|\\$\\{BB_CLI[^}]*\\})\\s+(--[A-Za-z-]+(=\\S+)?\\s+)*(thread\\s+(spawn|create|fork|tell|message|edit-message)|thread\\s+queue\\s+(create|update|send)|thread\\s+interactions\\s+(answer|respond)|fleet\\s+(group-create|task-add|advise|member-add)|automation\\s+(create|update|run|resume)|instructions\\s+set)\\$[A-Za-z0-9_]"; "i");
def blank: gsub("(?<k>\\$\\x27(?:\\\\[\\s\\S]|[^\\x27\\\\])*\\x27|\\x27[^\\x27]*\\x27|\"(?:\\\\[\\s\\S]|[^\"\\\\])*\"|\\\\[\\s\\S])|(?:^|(?<=[\\s;&|()]))(?<c>#[^\\n]*)";
  if .k != null then .k else (.c | gsub("[^;&|()]"; " ")) end);
def coarse: test("fleet_member_(spawn|tell)|fleet_delegate|fleet_task_(create|update)|fleet_advise|fleet_context_set|bb_workflow_run|thread.{0,40}(spawn|create|fork|tell|message|edit-message|queue|interactions.{0,60}(answer|respond))|fleet.{0,20}(group-create|task-add|advise|member-add)|automation.{0,40}(create|update|run|resume)|instructions.{0,20}set|plugin.{0,20}rpc.{0,20}call|[^\\s]`|[^\\s]\\$\\{|[^\\s$=]\\$$"; "i")
  or (test("\\s\\$$") and test("(^|\\s)(bb|\\$BB_CLI|\\$\\{BB_CLI[^}]*\\}|thread|fleet|automation|instructions)(\\s|$)"; "i"));
def nested: test("(^|\\s)-[A-Za-z]*[ce](\\s|$)|(^|[\\s/])eval(\\s|$)|--script|<<<|(^|\\s)(-[A-Za-z]*S|--split-string)"; "i");
def fields: {fleet_member_spawn: ["prompt", "concern"], fleet_member_tell: ["message"],
  fleet_delegate: ["task", "context"], fleet_task_create: ["title", "body"], fleet_task_update: ["title", "body", "blockedReason"],
  fleet_advise: ["question", "context"], fleet_context_set: ["key", "content"], bb_workflow_run: ["script", "source", "args"]};
def when: {fleet_task_update: ["title", "body", "blockedReason", "assigneeMemberId"]};
input as $p | (try input catch null) as $led
| ($p.tool_name // $p.toolName // "" | tostring) as $tool
| ($p.tool_input // $p.toolInput // $p.input // {}
   | if type == "string" then (try fromjson catch {command: .}) else . end
   | if type == "object" then . else {} end
   | if (.arguments | type) == "object" then . + .arguments else . end) as $in
| ((fields | keys) | map(select(. as $k | $tool | test("(^|[^a-z])" + $k + "$"))) | first) as $mcp
| (if $mcp != null then
     (if (when[$mcp] // null) != null and ([when[$mcp][] as $k | $in[$k] | select(. != null and . != "")] | length) == 0
      then null
      else [[fields[$mcp][] as $k | $in[$k] | select(. != null) | if type == "string" then . else tojson end] | join("\n") | flat] end)
   else
     (($in.command // $in.cmd) | if type == "array" then (map(tostring) | if length >= 3 and (.[1] | IN("-c", "-lc", "-ic")) then .[2] else join(" ") end)
      elif type == "string" then . else "" end | gsub("\\\\\\n"; "")) as $cmd
     | [$cmd | splits("[;&|()\n]")] as $raw
     | [$cmd | blank | splits("[;&|()\n]")] as $own
     | if ($raw | length) != ($own | length) then [""] else
       [range(0; $raw | length) as $i
        | select(($raw[$i] | flat | coarse) or ($raw[$i] | flat | gluedvar) or ($raw[$i] | test("\\$\\x27[^\\x27]*\\\\")))
        | if $raw[$i] | flat | nested then "" else $own[$i] | flat end]
     | if length == 0 then null else . end end
   end) as $t
| if $t == null then "none"
  else ([$led.purposes[]? | select(.status == "open") | .id]) as $open
  | ([$led.accepted_revisions[]?.quote | tostring | flat | collapse | select(length > 0)
      | . as $q | ([$q | splits("[;&|()\n]")][0] | collapse) as $h | if ($h | length) >= 20 then $h else $q end]) as $revs
  | if all($t[]; . as $s
        | ([$s | scan("serves:\\s*((?:P\\d+\\b[\\s,/&+]*(?:and\\s+)?)+)"; "i") | .[0] | scan("P\\d+"; "i") | ascii_upcase]
           | any(. as $id | $open | any(. == $id)))
          or (($s | test("serves:\\s*revision"; "i")) and any($revs[]; . as $q | $s | collapse | contains($q))))
    then "allow" else "deny" end
  end'
scope_flat() { printf '%s' "$input" | tr -d '\\"'"'"; }

# 0 when the call must be denied.
scope_dispatch_denied() {
  [ -n "${BB_THREAD_ID:-}" ] || return 1
  _ledger="${SCOPE_LEDGER_DIR:-$HOME/.local/state/agent-quality/scope}/$BB_THREAD_ID.json"
  [ -f "$_ledger" ] || return 1
  _v=$(printf '%s' "$input" | jq -rn "$SCOPE_SHAPE_JQ" - "$_ledger" 2>/dev/null)
  case "$_v" in
    none|allow) return 1 ;;
    deny) return 0 ;;
  esac
  printf '%s' "$input" | grep -q "\\$'[^']*\\\\" && return 0
  scope_flat | grep -qiE 'fleet_member_(spawn|tell)|fleet_delegate|fleet_task_(create|update)|fleet_advise|fleet_context_set|bb_workflow_run|thread.{0,40}(spawn|create|fork|tell|message|edit-message|queue|interactions)|fleet.{0,20}(group-create|task-add|advise|member-add)|automation.{0,40}(create|update|run|resume)|instructions.{0,20}set|plugin.{0,20}rpc.{0,20}call|[^[:space:]=]\$\(|[^[:space:]]\$\{|[^[:space:]]`'
}
# --- end scope shape ---

# Ship shape (the ship gate's coarse classes). PR merges are not in it: no
# gate ever denies a PR merge (owner decision 2026-10-06: prod fixes keep
# shipping, admin merges stay available). At the deadline a ship-shaped
# command is denied only where the gate could have denied it: a repo that
# opted in (a .qa/config.json at or above the payload cwd), or a command that
# moves to another directory first, which there was no time to resolve.
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
    if (d < 3 && (h == "sh" || h == "bash" || h == "zsh" || h == "dash") && k + 2 <= nw && W[d, k + 1] ~ /^-[A-Za-z]*c[A-Za-z]*$/)
      return view(W[d, k + 2], d + 1) subs
    if (d < 3 && h == "eval" && k < nw) {
      script = W[d, k + 1]
      for (j = k + 2; j <= nw; j++) script = script " " W[d, j]
      return view(script, d + 1) subs
    }
    return seg
  }
  function hdword(s, j,   n, k, c, x, nx, e, body, out, tail, d, t, plain, hp, hq) {
    # The heredoc word at s[j]: sets HW (delimiter) and HK (index after it) and returns 1, or returns 0 when the
    # shells might read it differently. Same reader as ship-gate.py _heredoc_word, measured against bash, zsh
    # and sh by hooks/test-heredoc-words.py (Hermes r10, r11). Bytes above 127 are plain (LC_ALL=C).
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
      } else if (c == sq || (c == "$" && (nx == sq || nx == "\""))) {
        if (c == "$" && nx == "\"") return 0
        k += (c == sq) ? 1 : 2
        e = index(substr(s, k), sq); if (!e) return 0
        body = substr(s, k, e - 1)
        if (index(body, "\n") || index(body, "\"") || index(body, "(") || index(body, ")") || index(body, "`")) return 0
        if (c == "$" && index(body, "\\")) return 0
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
# The scope shape decision is made now, while there is time: after a stage
# is killed at the deadline the shell only reads the answer (review r2b: the
# post-kill path started about 10 processes, and each can cost 0.6 s at high
# load). Only a thread with a ledger starts anything here (one jq).
# The ship shape decision is made now too, in one awk pass, so the post-kill
# path only reads the answer.
ship_shape_deny=1
ship_shape && { qa_opted_in || moves_dir; } && ship_shape_deny=0
scope_shape_deny=1
scope_dispatch_denied && scope_shape_deny=0
LATE="the hook chain could not finish within $GATE_DEADLINE s of starting (the host's hook timeout is 15 s, and a timed-out hook lets the command run)"

printf '%s' "$input" | run "$GATE_DEADLINE" "$H/qa-ship-gate-hook.sh"
rc=$?
[ "$rc" = 2 ] && exit 2
if [ "$rc" = 124 ] && [ "$ship_shape_deny" = 0 ]; then
  deny "[qa-ship-gate] Ship denied: $LATE; this command is ship-shaped in a QA opted-in repo, so it is denied. Retry it."
fi
if [ -x "$H/scope-gate-hook.sh" ]; then
  printf '%s' "$input" | run "$GATE_DEADLINE" "$H/scope-gate-hook.sh"
  rc=$?
  [ "$rc" = 2 ] && exit 2
  if [ "$rc" = 124 ] && [ "$scope_shape_deny" = 0 ]; then
    deny "[scope-gate] the gate could not finish: $LATE; this dispatch names no open purpose, so it is denied: add serves: P<n> and retry"
  fi
fi
printf '%s' "$input" | run "$CHAIN_DEADLINE" "$H/coordinator-hook.sh" pretool
[ $? = 2 ] && exit 2
exit 0
