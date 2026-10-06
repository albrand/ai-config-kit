# Mutation testing

Coverage says a line ran; mutation testing says a test would notice if it were wrong. The tool
changes the code (flips a condition, drops a call) and reruns the tests; a surviving mutant is a
bug your tests would let through.

It is slow, so it runs on a schedule and only on files that changed since the base branch:
`verify.py mutation-targets . --base origin/main` prints them. Schedule it with cron or a bb
automation: `verify.py run . --stages mutation --strict`. The tool's own break threshold enforces
the score; keep it equal to `min_score` in `.verify/config.json`.

## JavaScript / TypeScript: StrykerJS

```sh
npm i -D @stryker-mutator/core   # plus the runner you use: @stryker-mutator/vitest-runner or jest-runner
```

`stryker.config.json`:

```json
{
  "testRunner": "vitest",
  "incremental": true,
  "thresholds": { "high": 80, "low": 60, "break": 60 },
  "reporters": ["clear-text", "html"]
}
```

Stage: `"run": "files=$(python3 ~/.agents/skills/verify/scripts/verify.py mutation-targets . | paste -sd, -); [ -z \"$files\" ] || npx stryker run --mutate \"$files\""`

## Python: mutmut

```toml
# pyproject.toml
[tool.mutmut]
paths_to_mutate = ["src/"]
```

Stage: `"run": "mutmut run && mutmut results"`. mutmut has no break threshold of its own, so fail
the stage from its results when killed / total is below `min_score`.

## .NET: Stryker.NET

`stryker-config.json`:

```json
{
  "stryker-config": {
    "since": { "enabled": true, "target": "main" },
    "thresholds": { "high": 80, "low": 60, "break": 60 }
  }
}
```

Stage: `"run": "dotnet stryker"`.

When a mutant survives, add the test that kills it. Do not lower the threshold to make it pass.
