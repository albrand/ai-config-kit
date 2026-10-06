#!/bin/sh
# Install the vendored no-ai-slop skill. Run from the kit checkout:
#   sh skillsets/writing/install.sh
# Installs exactly the three pinned files. Refuses, before touching any home, if the source holds any other
# file or if a file differs from the digest recorded in README.md (the pinned upstream copy).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SRC="$HERE/shared/no-ai-slop"
refuse() { echo "no-ai-slop: $1; not installing" >&2; exit 1; }

[ -d "$SRC" ] && [ ! -L "$SRC" ] || refuse "the vendored directory is missing or a link"
extra=$(cd "$SRC" && find . -mindepth 1 ! -path ./SKILL.md ! -path ./eval.md ! -path ./LICENSE -print | head -1)
[ -z "$extra" ] || refuse "unexpected entry ${extra#./} in the vendored copy"
for pair in \
  "SKILL.md 992b365f51a2f62cf4c1c5ed22049a9ee551dfea677550c1a72b371c0ceadd62" \
  "eval.md 8ad8d83ed1abe7fc054ad74966bfca64fc182bc71f59d701b24b962c39d11ad7" \
  "LICENSE b7a7fe370cc4c9e974528c7cea7841cf8ac886bc9ed947edb11b289441fba4a8"; do
  f=${pair% *} want=${pair#* }
  [ -f "$SRC/$f" ] && [ ! -L "$SRC/$f" ] || refuse "$f is missing or not a regular file"
  got=$(shasum -a 256 "$SRC/$f" | cut -d' ' -f1)
  [ "$got" = "$want" ] || refuse "$f does not match the pinned digest"
done

for h in "$HOME/.agents/skills" "$HOME/.bb/skills" "$HOME/.claude/skills" "$HOME/.codex/skills"; do
  [ -d "$h" ] || continue
  tmp=$(mktemp -d "$h/.no-ai-slop.XXXXXX")
  chmod 755 "$tmp"
  for f in SKILL.md eval.md LICENSE; do cp "$SRC/$f" "$tmp/$f"; done
  rm -rf "$h/no-ai-slop"
  mv "$tmp" "$h/no-ai-slop"
done
echo "installed no-ai-slop"
