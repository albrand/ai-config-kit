#!/bin/sh
# install-coordinator.sh into a throwaway HOME: files land executable, second run is
# a no-op, and coordinator-mode.py still injects the coordinator block on prompt.
set -eu
KIT="$(cd "$(dirname "$0")/../../.." && pwd)"
T="$(mktemp -d "${TMPDIR:-/tmp}/coord-install.XXXXXX")"
trap 'rm -rf "$T"' EXIT
fail=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: got [$2] want [$3]"; fail=1; fi; }

mkdir -p "$T/.agent-hooks"
HOME="$T" sh "$KIT/skillsets/qa-enforcement/hooks/install-coordinator.sh" > "$T/install.log" 2>&1 || {
  cat "$T/install.log"; echo "FAIL installer exited non-zero"; exit 1;
}
for f in coordinator-hook.sh coordinator-hook-prompt.sh coordinator-mode.py spawn-route.py; do
  check "installed: $f executable" "$([ -x "$T/.agent-hooks/$f" ] && echo yes)" "yes"
done
check "installed: spawn-route.mode present" "$([ -f "$T/.agent-hooks/spawn-route.mode" ] && echo yes)" "yes"

digest() {
  for f in coordinator-hook.sh coordinator-hook-prompt.sh coordinator-mode.py spawn-route.py spawn-route.mode; do
    shasum -a 256 "$T/.agent-hooks/$f"
  done
}
before=$(digest | shasum -a 256)
HOME="$T" sh "$KIT/skillsets/qa-enforcement/hooks/install-coordinator.sh" >> "$T/install2.log" 2>&1
after=$(digest | shasum -a 256)
check "installer twice: file digests unchanged" "$after" "$before"

payload='{"session_id":"coord-install-test","prompt":"orchestrate this and spawn children"}'
out=$(printf '%s' "$payload" | HOME="$T" python3 "$T/.agent-hooks/coordinator-mode.py" prompt)
block=$(printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("ok" if "[coordinator-mode]" in d.get("context","") else d)')
check "coordinator-mode prompt: coordinator context block" "$block" "ok"

# Negative control: partial kit tree must fail installation.
T2="$(mktemp -d "${TMPDIR:-/tmp}/coord-install-miss.XXXXXX")"
FKIT="$(mktemp -d "${TMPDIR:-/tmp}/coord-install-fkit.XXXXXX")"
mkdir -p "$FKIT/skillsets/qa-enforcement/hooks" "$T2/.agent-hooks"
cp "$KIT/skillsets/qa-enforcement/hooks/install-coordinator.sh" "$FKIT/skillsets/qa-enforcement/hooks/"
for f in coordinator-hook-prompt.sh coordinator-mode.py spawn-route.py spawn-route.mode; do
  cp "$KIT/skillsets/qa-enforcement/hooks/$f" "$FKIT/skillsets/qa-enforcement/hooks/"
done
if HOME="$T2" sh "$FKIT/skillsets/qa-enforcement/hooks/install-coordinator.sh" >> "$T2/install.log" 2>&1; then
  echo "FAIL installer succeeded with a missing source file"; fail=1
else
  echo "ok   missing source file: installer exits non-zero"
fi
rm -rf "$FKIT" "$T2"

[ $fail -eq 0 ] && echo "coordinator install: all pass" || { echo "coordinator install: FAIL"; exit 1; }
