#!/bin/sh
# Exercise journey.fixture.ts in a real browser against a throwaway local server.
# Usage: run.sh <a repo whose node_modules has @playwright/test and its browsers>
here=$(cd "$(dirname "$0")" && pwd)
src=$(dirname "$here") nm=${1:?repo with node_modules}/node_modules
work=$(mktemp -d "${TMPDIR:-/tmp}/journeys-selftest.XXXXXX")  # macOS mktemp ignores TMPDIR without a template
cp "$src/journey.fixture.ts" "$here/cases.selftest.ts" "$work/"
cat > "$work/playwright.config.ts" <<'EOF'
import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: '.', testMatch: /cases\.selftest\.ts/, retries: 0, workers: 2,
  reporter: [['json', { outputFile: 'results.json' }]], use: { baseURL: 'http://127.0.0.1:4317' } });
EOF
node "$here/server.mjs" 4317 &
srv=$!
sleep 1
(cd "$work" && NODE_PATH="$nm" "$nm/.bin/playwright" test -c playwright.config.ts >/dev/null 2>&1)
kill "$srv"
python3 - "$work/results.json" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
def walk(s):
    for sp in s.get("specs", []):
        for t in sp["tests"]:
            res = t["results"][-1]
            err = (res.get("errors") or [{}])[0].get("message", "")[:160].replace("\n", " ")
            yield sp["title"], res["status"], err
    for c in s.get("suites", []):
        yield from walk(c)
bad = 0
for title, status, err in (x for s in r["suites"] for x in walk(s)):
    want = "failed" if "must fail" in title else "passed"
    ok = status == want
    bad += not ok
    print(("ok  " if ok else "BAD ") + f"{title}: {status}" + (f" [{err}]" if err else ""))
sys.exit(1 if bad else 0)
EOF
rc=$?
rm -rf "$work"
exit $rc
