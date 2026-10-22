#!/bin/sh
# gap-map-hook.sh end to end, in a throwaway HOME: silent for a thread with no ledger and for a
# call long after its last passed dispatch; after the 8th passed dispatch in 6h with no gap map it
# prints the PostToolUse note once; a recorded map silences it.
set -eu
SRC="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/.agents/skills" "$T/.local/state/agent-quality/scope"
cp -R "$SRC/shared/scope-ledger" "$T/.agents/skills/scope-ledger"
TID=thr_gapmaphook
python3 - "$SRC/shared/scope-ledger/tests/fixtures/scope-ledger.json" "$T/.local/state/agent-quality/scope/$TID.json" "$TID" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1])); d["thread_id"] = sys.argv[3]
json.dump(d, open(sys.argv[2], "w"))
EOF
LOG="$T/.local/state/agent-quality/scope-decisions.jsonl"
fail=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: got [$2] want [$3]"; fail=1; fi; }
hook() { HOME="$T" BB_THREAD_ID="$1" SCOPE_LEDGER_DIR="$T/.local/state/agent-quality/scope" sh "$SRC/hooks/gap-map-hook.sh" </dev/null; }
passed() {  # what the gate does on each passed dispatch (scope-gate.py mark_passed)
  HOME="$T" python3 -c 'import importlib.util, sys
spec = importlib.util.spec_from_file_location("sg", sys.argv[1]); sg = importlib.util.module_from_spec(spec); spec.loader.exec_module(sg)
[sg.mark_passed(sys.argv[2]) for _ in range(int(sys.argv[3]))]' "$T/.agents/skills/scope-ledger/scripts/scope-gate.py" "$TID" "$1"
}
noise() {  # the rest of the fleet writing the shared log
  i=0; while [ $i -lt "$1" ]; do
    echo "{\"schema_version\": 1, \"at\": \"x\", \"event\": \"scope_passed\", \"thread\": \"thr_other$i\"}" >> "$LOG"
    i=$((i + 1))
  done
}
passed 7
check "below the threshold: silent" "$(hook $TID)" ""
check "thread with no ledger: silent" "$(hook thr_noledgerhere)" ""
passed 1
noise 40  # review of #92: 40 other threads' lines after the eligible dispatch
out="$(hook $TID)"
case "$out" in *'"additionalContext"'*"8 dispatches"*"gap map"*) got=note ;; *) got="$out" ;; esac
check "8th passed dispatch: note shown" "$got" "note"
check "shown once" "$(hook $TID)" ""
echo "# gap map" > "$T/map.md"
HOME="$T" SCOPE_LEDGER_DIR="$T/.local/state/agent-quality/scope" python3 "$T/.agents/skills/scope-ledger/scripts/scope-gate.py" map $TID --artifact "$T/map.md" >/dev/null
python3 - "$T/.local/state/agent-quality/scope/$TID.json" <<'EOF'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["gap_map_nudged_at"] = "2000-01-01T00:00:00Z"; json.dump(d, open(p, "w"))
EOF
passed 1
check "recorded map: silent" "$(hook $TID)" ""
python3 - "$T/.local/state/agent-quality/scope/$TID.json" <<'EOF2'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["gap_maps"] = []; d["gap_map_nudged_at"] = "2000-01-01T00:00:00Z"; json.dump(d, open(p, "w"))
EOF2
touch -t 200001010000 "$T/.local/state/agent-quality/scope-passed/$TID"
check "no dispatch in the last 2 minutes: python never starts, silent" "$(hook $TID)" ""
[ $fail -eq 0 ] && echo "gap-map hook: all pass" || { echo "gap-map hook: FAIL"; exit 1; }
