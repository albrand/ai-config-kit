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

# 3. A change between the digest check and the copy cannot reach a home. A shasum shim on the installer's
# PATH hashes as usual, then on its first call appends a line to a file: either the vendored SKILL.md (a
# source change after it was checked) or the file it just hashed.
REAL_SHASUM=$(command -v shasum)
midrun() {
  name=$1 target=$2 want_rc=$3
  W=$(mktemp -d); cp -R "$HERE" "$W/writing"; mkdir "$W/bin"
  cat > "$W/bin/shasum" <<EOF
#!/bin/sh
"$REAL_SHASUM" "\$@"; rc=\$?
if [ ! -e "$W/done" ]; then
  : > "$W/done"
  for last in "\$@"; do :; done
  if [ "$target" = source ]; then f="$W/writing/shared/no-ai-slop/SKILL.md"; else f=\$last; fi
  echo "changed mid-run" >> "\$f"
fi
exit \$rc
EOF
  chmod +x "$W/bin/shasum"
  HOME=$H PATH="$W/bin:$PATH" sh "$W/writing/install.sh" >/dev/null 2>&1; check "$name: exit" "$want_rc" $?
  check "$name: the shim changed a file" yes "$([ -e "$W/done" ] && echo yes || echo no)"
  check "$name: installed copy is still the pinned one" "$before" "$(shasum -a 256 "$H"/.claude/skills/no-ai-slop/* | shasum -a 256)"
  check "$name: no extra entry installed" "./LICENSE ./SKILL.md ./eval.md " "$(installed "$H/.claude/skills")"
  rm -rf "$W"
}
midrun "source changed after its check" source 0
midrun "checked copy changed before it is installed" hashed 1
rm -rf "$H"
[ "$fail" = 0 ] && echo "test-install: all passed"
exit $fail
