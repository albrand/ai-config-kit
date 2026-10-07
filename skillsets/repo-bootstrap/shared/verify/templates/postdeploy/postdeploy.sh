#!/bin/sh
# After a deploy: is the deployed app up, and can people still do the things that matter most?
# Needs BASE_URL (verify sets it from the stage's base_url command). HEALTH_PATH defaults to /api/health.
# Exits non-zero when the deploy is broken, and says how to roll back. It never rolls back by itself.
set -u
: "${BASE_URL:?BASE_URL must be the deployed URL}"
health="${BASE_URL%/}${HEALTH_PATH:-/api/health}"

echo "postdeploy: health $health"
if ! curl -fsS --max-time 15 --retry 10 --retry-delay 6 --retry-all-errors "$health" >/dev/null; then
  echo "postdeploy: FAIL - $health is not healthy" >&2
  failed=health
else
  echo "postdeploy: @smoke journeys against $BASE_URL"
  if npx playwright test -c "${JOURNEYS_CONFIG:-playwright.journeys.config.ts}" --grep @smoke; then
    echo "postdeploy: pass"
    exit 0
  fi
  failed=smoke
fi

echo "postdeploy: the deploy at $BASE_URL is broken ($failed)." >&2
echo "postdeploy: to restore the previous deployment: ${ROLLBACK_HINT:-vercel rollback (or your platform's equivalent)}" >&2
exit 1
