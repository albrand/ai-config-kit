#!/bin/sh
# Install the vendored no-ai-slop skill. Run from the kit checkout:
#   sh skillsets/writing/install.sh
# Installs exactly the three pinned files. It copies them once into a private staging directory and checks
# the digests recorded in README.md (the pinned upstream copy) on those copies, refusing before touching any
# home. Each home then gets the staged copies, checked before and again after they are moved into place; if
# the installed copy fails that last check, the previous copy is restored and the run exits 1. The source is
# never read after it is staged, so a change to it during the run cannot reach a home.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SRC="$HERE/shared/no-ai-slop"
FILES="SKILL.md eval.md LICENSE"
refuse() { echo "no-ai-slop: $1; not installing" >&2; exit 1; }
pin() {
  case $1 in
    SKILL.md) echo 992b365f51a2f62cf4c1c5ed22049a9ee551dfea677550c1a72b371c0ceadd62 ;;
    eval.md) echo 8ad8d83ed1abe7fc054ad74966bfca64fc182bc71f59d701b24b962c39d11ad7 ;;
    LICENSE) echo b7a7fe370cc4c9e974528c7cea7841cf8ac886bc9ed947edb11b289441fba4a8 ;;
  esac
}
# Exits non-zero unless every file in directory $1 matches its pin.
matches() {
  for f in $FILES; do
    [ -f "$1/$f" ] && [ ! -L "$1/$f" ] || return 1
    [ "$(shasum -a 256 "$1/$f" | cut -d' ' -f1)" = "$(pin "$f")" ] || return 1
  done
}

[ -d "$SRC" ] && [ ! -L "$SRC" ] || refuse "the vendored directory is missing or a link"
extra=$(cd "$SRC" && find . -mindepth 1 ! -path ./SKILL.md ! -path ./eval.md ! -path ./LICENSE -print | head -1)
[ -z "$extra" ] || refuse "unexpected entry ${extra#./} in the vendored copy"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
for f in $FILES; do
  [ -f "$SRC/$f" ] && [ ! -L "$SRC/$f" ] || refuse "$f is missing or not a regular file"
  cp "$SRC/$f" "$STAGE/$f"
done
matches "$STAGE" || refuse "a file does not match its pinned digest"

for h in "$HOME/.agents/skills" "$HOME/.bb/skills" "$HOME/.claude/skills" "$HOME/.codex/skills"; do
  [ -d "$h" ] || continue
  tmp=$(mktemp -d "$h/.no-ai-slop.XXXXXX")
  chmod 755 "$tmp"
  for f in $FILES; do cp "$STAGE/$f" "$tmp/$f"; done
  matches "$tmp" || { rm -rf "$tmp"; refuse "the copy staged for $h does not match its pinned digest"; }
  prev="$h/.no-ai-slop-previous.$$"
  rm -rf "$prev"
  [ ! -e "$h/no-ai-slop" ] || mv "$h/no-ai-slop" "$prev"
  mv "$tmp" "$h/no-ai-slop"
  # The last check runs on the installed path itself, after the move, so no installer step follows it.
  if ! matches "$h/no-ai-slop"; then
    rm -rf "$h/no-ai-slop"
    [ ! -e "$prev" ] || mv "$prev" "$h/no-ai-slop"
    refuse "the copy installed in $h changed before its final check; the previous copy is restored"
  fi
  rm -rf "$prev"
done
echo "installed no-ai-slop"
