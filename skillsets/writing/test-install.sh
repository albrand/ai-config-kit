#!/bin/sh
# Tests for install.sh, each in a throwaway HOME. Run from anywhere: sh skillsets/writing/test-install.sh
# Exits non-zero if any case fails.
HERE=$(cd "$(dirname "$0")" && pwd)
fail=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (want $2, got $3)"; fail=1; fi; }
newhome() { h=$(mktemp -d); mkdir -p "$h/.claude/skills" "$h/.codex/skills"; echo "$h"; }
installed() { (cd "$1/no-ai-slop" 2>/dev/null && find . -mindepth 1 | sort | tr '\n' ' '); }

# 1. A clean copy installs exactly the three pinned files into each existing home, and skips absent ones.
H=$(newhome)
HOME=$H sh "$HERE/install.sh" >/dev/null 2>&1; check "clean copy installs" 0 $?
check "claude home holds exactly the pinned files" "./LICENSE ./SKILL.md ./eval.md " "$(installed "$H/.claude/skills")"
check "codex home holds exactly the pinned files" "./LICENSE ./SKILL.md ./eval.md " "$(installed "$H/.codex/skills")"
check "absent bb home is not created" no "$([ -e "$H/.bb" ] && echo yes || echo no)"
for f in SKILL.md eval.md LICENSE; do
  cmp -s "$HERE/shared/no-ai-slop/$f" "$H/.claude/skills/no-ai-slop/$f"; check "installed $f is byte-identical" 0 $?
done
before=$(shasum -a 256 "$H"/.claude/skills/no-ai-slop/* | shasum -a 256)

# 2. Each tampered source is refused, and the copy already installed is unchanged.
tamper() {
  name=$1; shift
  W=$(mktemp -d); cp -R "$HERE" "$W/writing"
  (cd "$W/writing/shared/no-ai-slop" && sh -c "$*")
  HOME=$H sh "$W/writing/install.sh" >/dev/null 2>&1; check "refuses: $name" 1 $?
  check "installed copy unchanged after: $name" "$before" "$(shasum -a 256 "$H"/.claude/skills/no-ai-slop/* | shasum -a 256)"
  check "no extra entry installed after: $name" "./LICENSE ./SKILL.md ./eval.md " "$(installed "$H/.claude/skills")"
  rm -rf "$W"
}
tamper "a modified SKILL.md" 'echo "appended" >> SKILL.md'
tamper "an extra file" 'echo x > UNPINNED.md'
tamper "an extra hidden file" 'echo x > .hidden'
tamper "an extra directory" 'mkdir scripts && echo x > scripts/run.sh'
tamper "a missing eval.md" 'rm eval.md'
tamper "SKILL.md replaced by a link" 'mv SKILL.md real && ln -s real SKILL.md && mv real ../real-skill'
rm -rf "$H"
[ "$fail" = 0 ] && echo "test-install: all passed"
exit $fail
