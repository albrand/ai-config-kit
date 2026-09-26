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
# (review r2b): a gated agent tool's text fields, or the command with its
# comments dropped; never the tool call's description, and no brief file is
# read (a FIFO would block). One jq run reads the payload and the ledger, the
# same decision as scope-gate.py's `shape` (shape_text + shape_serves); no jq,
# or no answer from it, denies any dispatch word (fails closed).
SCOPE_SHAPE_JQ='
def flat: gsub("[\\\\\"\\x27]"; "");
def collapse: gsub("\\s+"; " ") | sub("^ "; "") | sub(" $"; "");
def uncomment: gsub("(?<k>\\x27[^\\x27]*\\x27|\"(?:\\\\.|[^\"\\\\])*\"|\\\\.)|(?:^|(?<=[\\s;&|()]))#[^\\n]*"; .k // "");
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
      else [fields[$mcp][] as $k | $in[$k] | select(. != null) | if type == "string" then . else tojson end] | join("\n") | flat end)
   else
     (($in.command // $in.cmd) | if type == "array" then (map(tostring) | if length >= 3 and (.[1] | IN("-c", "-lc", "-ic")) then .[2] else join(" ") end)
      elif type == "string" then . else "" end) as $cmd
     | ($cmd | uncomment | flat) as $f
     | if $f | test("fleet_member_(spawn|tell)|fleet_delegate|fleet_task_(create|update)|fleet_advise|fleet_context_set|bb_workflow_run|thread.{0,40}(spawn|create|fork|tell|message|edit-message|queue|interactions.{0,60}(answer|respond))|fleet.{0,20}(group-create|task-add|advise|member-add)"; "i")
       then $f else null end
   end) as $t
| if $t == null then "none"
  else ([$led.purposes[]? | select(.status == "open") | .id]) as $open
  | if [$t | scan("serves:\\s*((?:P\\d+\\b[\\s,/&+]*(?:and\\s+)?)+)"; "i") | .[0] | scan("P\\d+"; "i") | ascii_upcase]
       | any(. as $id | $open | any(. == $id)) then "allow"
    elif ($t | test("serves:\\s*revision"; "i"))
       and any($led.accepted_revisions[]?.quote | tostring | flat | collapse | select(length > 0); . as $q | $t | collapse | contains($q))
    then "allow"
    else "deny" end
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
  scope_flat | grep -qiE 'fleet_member_(spawn|tell)|fleet_delegate|fleet_task_(create|update)|fleet_advise|fleet_context_set|bb_workflow_run|thread.{0,40}(spawn|create|fork|tell|message|edit-message|queue|interactions)|fleet.{0,20}(group-create|task-add|advise|member-add)'
}
# --- end scope shape ---
flat=$(scope_flat)
# Cheap prefilter: no dispatch shape anywhere in the payload, nothing to gate.
printf '%s' "$flat" | grep -qiE 'thread|fleet|bb_workflow_run' || exit 0
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
