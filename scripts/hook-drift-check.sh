#!/bin/sh
# Compare the installed QA hooks and skill copies with their maintained sources.
set -u
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
HOOKS="$ROOT/skillsets/qa-enforcement/hooks"
SKILL="$ROOT/skillsets/qa-enforcement/shared/qa-sweep"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/hook-drift.XXXXXX") || exit 2
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
status=0

check_file() {
  cf_source=$1
  cf_installed=$2
  if [ ! -f "$cf_installed" ]; then
    printf 'MISSING %s\n' "$cf_installed"
    status=1
  elif ! cmp -s "$cf_source" "$cf_installed"; then
    printf 'DIFF %s\n' "$cf_installed"
    status=1
  fi
}

check_tree() {
  ct_source=$1
  ct_installed=$2
  source_list="$TMP/source-files"
  installed_list="$TMP/installed-files"
  if [ ! -d "$ct_installed" ]; then
    printf 'MISSING %s\n' "$ct_installed"
    status=1
    return
  fi
  (cd "$ct_source" && find . -type f \
    ! -path '*/__pycache__/*' ! -path '*/.pytest_cache/*' \
    ! -name '*.pyc' ! -name '*.bak*' -print | LC_ALL=C sort) > "$source_list"
  (cd "$ct_installed" && find . -type f \
    ! -path '*/__pycache__/*' ! -path '*/.pytest_cache/*' \
    ! -name '*.pyc' ! -name '*.bak*' -print | LC_ALL=C sort) > "$installed_list"
  while IFS= read -r relative; do
    check_file "$ct_source/$relative" "$ct_installed/$relative"
  done < "$source_list"
  while IFS= read -r relative; do
    if ! [ -f "$ct_source/$relative" ]; then
      printf 'EXTRA %s\n' "$ct_installed/$relative"
      status=1
    fi
  done < "$installed_list"
}

for name in qa-ship-gate-hook.sh qa-stop-hook.sh keepgoing-stop.py thread-wait-guard.py qa-bindings-push-gate.py codex-hook-trust.py coordinator-hook-pretool.sh; do
  check_file "$HOOKS/$name" "$HOME/.agent-hooks/$name"
done
check_file "$HOOKS/plugin/opencode-qa-evidence.js" "$HOME/.config/opencode/plugin/qa-evidence-gate.js"
check_file "$HOOKS/lib/qa-evidence-policy.mjs" "$HOME/.config/opencode/lib/qa-evidence-policy.mjs"
for home in .agents .bb .claude .codex; do
  check_tree "$SKILL" "$HOME/$home/skills/qa-sweep"
done

if [ "$status" -eq 0 ]; then
  printf 'All installed QA hook and skill files match repository sources.\n'
fi
exit "$status"
