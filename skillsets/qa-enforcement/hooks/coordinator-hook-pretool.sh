#!/bin/sh
# pretool adapter for coordinator-mode (no argv: Codex runs hook commands as a path).
# Since 2026-09-24 the QA ship gate runs first: it denies ship commands
# (git push, gh pr create/merge, bb fleet validate, deploys) in repos that
# opted in with a committed .qa/config.json, and allows everything else.
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
def blank: gsub("(?<k>\\$\\x27(?:\\\\[\\s\\S]|[^\\x27\\\\])*\\x27|\\x27[^\\x27]*\\x27|\"(?:\\\\[\\s\\S]|[^\"\\\\])*\"|\\\\[\\s\\S])|(?:^|(?<=[\\s;&|()]))(?<c>#[^\\n]*)";
  if .k != null then .k else (.c | gsub("[^;&|()]"; " ")) end);
def coarse: test("fleet_member_(spawn|tell)|fleet_delegate|fleet_task_(create|update)|fleet_advise|fleet_context_set|bb_workflow_run|thread.{0,40}(spawn|create|fork|tell|message|edit-message|queue|interactions.{0,60}(answer|respond))|fleet.{0,20}(group-create|task-add|advise|member-add)|automation.{0,40}(create|update|run|resume)|instructions.{0,20}set|[^\\s]`|[^\\s]\\$\\{|[^\\s$=]\\$$"; "i")
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
        | select(($raw[$i] | flat | coarse) or ($raw[$i] | test("\\$\\x27[^\\x27]*\\\\")))
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
  scope_flat | grep -qiE 'fleet_member_(spawn|tell)|fleet_delegate|fleet_task_(create|update)|fleet_advise|fleet_context_set|bb_workflow_run|thread.{0,40}(spawn|create|fork|tell|message|edit-message|queue|interactions)|fleet.{0,20}(group-create|task-add|advise|member-add)|automation.{0,40}(create|update|run|resume)|instructions.{0,20}set|[^[:space:]]\$\(|[^[:space:]]\$\{|[^[:space:]]`'
}
# --- end scope shape ---

# Ship shape (the ship gate's coarse classes). At the deadline a ship-shaped
# command is denied whether or not its repo opted in: there was no time to read.
ship_shape() {
  scope_flat | grep -qE 'git( [^ ;&|]+)* push|gh pr (merge|ready)|gh (release (create|edit)|workflow run)|vercel[^;&|]*(--prod|--target[= ]production|promote|redeploy|alias|rolling-release)|netlify[^;&|]*deploy[^;&|]*--prod|fly(ctl)? deploy|/v[0-9]+/deployments|/v[0-9]+/projects/[^ ]*/promote/|repos/[^ ]*/(pulls/[0-9]+/merge|merges|releases|git/refs|dispatches|contents/|deployments)|mergePullRequest|createCommitOnBranch|updateRef'
}
# The scope shape decision is made now, while there is time: after a stage
# is killed at the deadline the shell only reads the answer (review r2b: the
# post-kill path started about 10 processes, and each can cost 0.6 s at high
# load). Only a thread with a ledger starts anything here (one jq).
scope_shape_deny=1
scope_dispatch_denied && scope_shape_deny=0
LATE="the hook chain could not finish within $GATE_DEADLINE s of starting (the host's hook timeout is 15 s, and a timed-out hook lets the command run)"

printf '%s' "$input" | run "$GATE_DEADLINE" "$H/qa-ship-gate-hook.sh"
rc=$?
[ "$rc" = 2 ] && exit 2
if [ "$rc" = 124 ] && ship_shape; then
  deny "[qa-ship-gate] Ship denied: $LATE; this command is ship-shaped, so it is denied. Retry it."
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
