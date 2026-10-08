#!/bin/sh
# The kit's static stage for verify.py: every tracked Python, shell and Node file parses, and the kit
# source and rendered homes keep every standing rule. Reads nothing outside the checkout.
cd "$(dirname "$0")/.." || exit 1
fail=0
tmp=$(mktemp -d "${TMPDIR:-/tmp}/verify-static.XXXXXX") || exit 1
trap 'rm -rf "$tmp"' EXIT
git ls-files -z '*.py' | xargs -0 python3 -I -c '
import ast, sys
bad = 0
for f in sys.argv[1:]:
    try:
        ast.parse(open(f, "rb").read(), f)
    except SyntaxError as e:
        print("FAIL python syntax:", f, e); bad = 1
sys.exit(bad)' || fail=1
for f in $(git ls-files '*.sh'); do
  case "$(head -1 "$f")" in *bash*) bash -n "$f" ;; *) sh -n "$f" ;; esac || { echo "FAIL shell syntax: $f"; fail=1; }
done
for f in $(git ls-files '*.mjs' '*.js' '*.cjs'); do
  node --check "$f" 2>"$tmp/err" || { echo "FAIL node syntax: $f"; cat "$tmp/err"; fail=1; }
done
python3 -I scripts/check-standing-rules.py --files GLOBAL_AGENTS.md proposals/card21/rendered-homes/*.md || fail=1
[ "$fail" = 0 ] && echo "static: ok"
exit $fail
