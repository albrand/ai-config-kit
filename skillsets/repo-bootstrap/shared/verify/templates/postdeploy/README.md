# Postdeploy

A deploy is done when the deployed app works, not when the platform says it built. After each
deploy, check the health endpoint and run the `@smoke` journeys against the deployed URL.

Copy `postdeploy.sh` to `scripts/` and add a health endpoint that touches what the app needs
(database reachable, required config present) and returns 200.

verify config:

```json
"postdeploy": {
  "run": "sh scripts/postdeploy.sh",
  "base_url": "vercel ls --prod 2>/dev/null | grep -m1 -o 'https://[^ ]*'",
  "env": ["JOURNEY_MEMBER_EMAIL", "JOURNEY_MEMBER_PASSWORD"],
  "timeout": 900
}
```

`base_url` is a command that prints the deployed URL; replace it with whatever your platform
offers (a Vercel deployment for the commit, a fixed staging URL, `fly status`). Run it after a
deploy with `verify.py run . --stages postdeploy --strict`. The verify hook reminds the agent
after a deploy command.

When it fails, the script prints how to roll back and exits non-zero. Rolling back is a decision
for whoever owns the release. The script does not roll back on its own.
