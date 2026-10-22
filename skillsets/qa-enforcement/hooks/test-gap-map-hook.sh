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
echo 946684800 > "$T/.local/state/agent-quality/scope-passed/$TID.nudged"  # last shown in 2000
passed 1
check "recorded map: silent" "$(hook $TID)" ""
python3 - "$T/.local/state/agent-quality/scope/$TID.json" <<'EOF2'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["gap_maps"] = []; json.dump(d, open(p, "w"))
EOF2
echo 946684800 > "$T/.local/state/agent-quality/scope-passed/$TID.nudged"
touch -t 200001010000 "$T/.local/state/agent-quality/scope-passed/$TID"
check "no dispatch in the last 2 minutes: python never starts, silent" "$(hook $TID)" ""
# Eight dispatches passing at the same moment (review of #92, round 3): eight processes released
# together each record one; all eight count and the note shows.
C=thr_gapmapconcurrent
python3 - "$SRC/shared/scope-ledger/tests/fixtures/scope-ledger.json" "$T/.local/state/agent-quality/scope/$C.json" "$C" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1])); d["thread_id"] = sys.argv[3]
json.dump(d, open(sys.argv[2], "w"))
EOF
cat > "$T/concurrent.py" <<'EOF'
import importlib.util, multiprocessing as mp, sys

def one(path, thread, go):
    spec = importlib.util.spec_from_file_location("sg", path); sg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sg)
    go.wait()
    sg.mark_passed(thread)

if __name__ == "__main__":
    go = mp.Event()
    ps = [mp.Process(target=one, args=(sys.argv[1], sys.argv[2], go)) for _ in range(8)]
    [p.start() for p in ps]
    go.set()
    [p.join() for p in ps]
EOF
HOME="$T" python3 "$T/concurrent.py" "$T/.agents/skills/scope-ledger/scripts/scope-gate.py" "$C"
n=$(wc -l < "$T/.local/state/agent-quality/scope-passed/$C" | tr -d ' ')
check "8 simultaneous passed dispatches: all recorded" "$n" "8"
out="$(hook $C)"
case "$out" in *'"additionalContext"'*"8 dispatches"*) got=note ;; *) got="$out" ;; esac
check "8 simultaneous passed dispatches: note shown" "$got" "note"
# Eight PostToolUse hooks deciding at the same moment, past the threshold (review of #92,
# round 4): exactly one note, and the ledger is not rewritten.
cat > "$T/concurrent_nudge.py" <<'EOF'
import importlib.util, multiprocessing as mp, sys

def one(path, thread, go, out):
    spec = importlib.util.spec_from_file_location("sg", path); sg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sg)
    go.wait()
    out.put(1 if sg.gap_map_nudge(thread) else 0)

if __name__ == "__main__":
    go, out = mp.Event(), mp.Queue()
    ps = [mp.Process(target=one, args=(sys.argv[1], sys.argv[2], go, out)) for _ in range(8)]
    [p.start() for p in ps]
    go.set()
    [p.join() for p in ps]
    print(sum(out.get() for _ in ps))
EOF
C2=thr_gapmapconcurrentnudge
cp "$SRC/shared/scope-ledger/tests/fixtures/scope-ledger.json" "$T/.local/state/agent-quality/scope/$C2.json"
python3 - "$T/.local/state/agent-quality/scope/$C2.json" "$C2" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1])); d["thread_id"] = sys.argv[2]; json.dump(d, open(sys.argv[1], "w"))
EOF
passed_as() { HOME="$T" python3 -c 'import importlib.util, sys
spec = importlib.util.spec_from_file_location("sg", sys.argv[1]); sg = importlib.util.module_from_spec(spec); spec.loader.exec_module(sg)
[sg.mark_passed(sys.argv[2]) for _ in range(int(sys.argv[3]))]' "$T/.agents/skills/scope-ledger/scripts/scope-gate.py" "$1" "$2"; }
passed_as $C2 8
before=$(shasum "$T/.local/state/agent-quality/scope/$C2.json" | cut -d' ' -f1)
notes=$(HOME="$T" SCOPE_LEDGER_DIR="$T/.local/state/agent-quality/scope" python3 "$T/concurrent_nudge.py" "$T/.agents/skills/scope-ledger/scripts/scope-gate.py" $C2)
after=$(shasum "$T/.local/state/agent-quality/scope/$C2.json" | cut -d' ' -f1)
check "8 concurrent nudges past the threshold: exactly one note" "$notes" "1"
check "8 concurrent nudges: the ledger is not rewritten" "$after" "$before"
echo "python: $(python3 --version 2>&1); kit head: $(git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo unknown)"
[ $fail -eq 0 ] && echo "gap-map hook: all pass" || { echo "gap-map hook: FAIL"; exit 1; }
