#!/bin/sh
# The kit's unit stage for verify.py: every self-contained test suite in the repo.
# Each suite runs from the checkout and reads nothing outside it, so it also runs in the
# verify runner's sandbox. Exits non-zero if any suite fails, after running them all.
cd "$(dirname "$0")/.." || exit 1
fail=0
run() {
  name=$1; shift
  echo "== $name"
  if "$@"; then echo "ok   $name"; else echo "FAIL $name"; fail=1; fi
}
run "scripts"            python3 -m unittest discover -s scripts -p "test_*.py"
run "context hygiene"    python3 -m unittest discover -s skillsets/agent-runtime/hooks -p "test_*.py"
run "qa-enforcement"     python3 -m unittest discover -s skillsets/qa-enforcement/hooks/tests -p "test_*.py"
run "ship-gate selftest" python3 skillsets/qa-enforcement/shared/qa-sweep/scripts/ship-gate.py selftest
run "ship matrix"        python3 skillsets/qa-enforcement/hooks/test-ship-matrix.py
run "verify"             python3 -m unittest discover -s skillsets/repo-bootstrap/shared/verify/scripts/tests -p "test_*.py"
run "ui-ux-pro-max"      python3 -m unittest discover -s skillsets/ux-design-intelligence/shared/ui-ux-pro-max/scripts/tests -p "test_*.py"
run "node tests"         node --test \
  skillsets/adaptive-model-orchestration/codex/adaptive-model-orchestrator/scripts/run-managed.test.mjs \
  skillsets/agent-runtime/shared/verified-qa-e2e/tests/qa-e2e-gate.test.mjs \
  skillsets/qa-enforcement/hooks/tests/opencode-qa-evidence.test.mjs
exit $fail
