#!/bin/sh
# PreToolUse adapter for the scope gate (Claude Code + Codex via
# coordinator-hook-pretool.sh). Reads the hook payload on stdin.
#   exit 0 + no output = allow; exit 2 + JSON/stderr = deny.
# Only a thread with a scope ledger is ever gated: everything else leaves at
# the first test, before python starts. For a ledger thread, a dispatch
# (a bb verb that hands a thread text, or an agent tool that does:
# scope-gate.py MCP_FIELDS) must carry `serves: P<n>` for an open purpose or
# `serves: revision "<quote>"` for an accepted revision.
DIR="${SCOPE_LEDGER_DIR:-$HOME/.local/state/agent-quality/scope}"
GATE="$HOME/.agents/skills/scope-ledger/scripts/scope-gate.py"
[ -n "${BB_THREAD_ID:-}" ] && [ -f "$DIR/$BB_THREAD_ID.json" ] || exit 0
input=$(cat)
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
# stretch and does not count (a deny; the normal decision reads them).
SCOPE_SHAPE_JQ='
def flat: gsub("[\\\\\"\\x27]"; "");
def collapse: gsub("\\s+"; " ") | sub("^ "; "") | sub(" $"; "");
def blank: gsub("(?<k>\\$\\x27(?:\\\\[\\s\\S]|[^\\x27\\\\])*\\x27|\\x27[^\\x27]*\\x27|\"(?:\\\\[\\s\\S]|[^\"\\\\])*\"|\\\\[\\s\\S])|(?:^|(?<=[\\s;&|()]))(?<c>#[^\\n]*)";
  if .k != null then .k else (.c | gsub("[^;&|()]"; " ")) end);
def coarse: test("fleet_member_(spawn|tell)|fleet_delegate|fleet_task_(create|update)|fleet_advise|fleet_context_set|bb_workflow_run|thread.{0,40}(spawn|create|fork|tell|message|edit-message|queue|interactions.{0,60}(answer|respond))|fleet.{0,20}(group-create|task-add|advise|member-add)|automation.{0,40}(create|update|run|resume)|instructions.{0,20}set"; "i");
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
  scope_flat | grep -qiE 'fleet_member_(spawn|tell)|fleet_delegate|fleet_task_(create|update)|fleet_advise|fleet_context_set|bb_workflow_run|thread.{0,40}(spawn|create|fork|tell|message|edit-message|queue|interactions)|fleet.{0,20}(group-create|task-add|advise|member-add)|automation.{0,40}(create|update|run|resume)|instructions.{0,20}set'
}
# --- end scope shape ---
flat=$(scope_flat)
# Cheap prefilter: no dispatch shape anywhere in the payload, nothing to gate.
printf '%s' "$flat" | grep -qiE 'thread|fleet|bb_workflow_run|automation|instructions' || exit 0
set +e
if [ -f "$GATE" ] && command -v python3 >/dev/null 2>&1; then
  printf '%s' "$input" | python3 "$GATE" hook
  rc=$?
else
  rc=127
fi
set -e
if [ "$rc" = 0 ] || [ "$rc" = 2 ]; then
  exit "$rc"
fi
# The gate could not run: decide by shape alone (an open purpose or an
# accepted revision, read from the ledger with jq).
if scope_dispatch_denied; then
  echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "[scope-gate] gate could not run and this dispatch names no open purpose; add `serves: P<n>` for one of the ledger'"'"'s open purposes"}}'
  echo "[scope-gate] gate could not run; dispatch without an open purpose denied" >&2
  exit 2
fi
exit 0
