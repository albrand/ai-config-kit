# P0 workflow-scope procedure

## P0 Scope: `.qa/workflow.json`

Before the first LLM review submission, attach both JSON and Markdown packets
from `python3 ~/.agents/skills/pr-review/scripts/pre-review.py` to `bb fleet validate --evidence` and any
advisor round; keep LLM review focused on semantic gaps left by deterministic
checks. Each defect fix must add the cheapest deterministic detector that
would catch it (regex, Semgrep, lint, test, fixture, or probe), or say in one
line when only semantic review can catch it. Put generic rules in the kit starter
pack and project-specific rules in `.review-rules/`.

Name the persona, the entry point, the user-visible outcome, every step
between them, and the target (URL plus the SHA being tested). A repo-level
`.qa/config.json` (committed) lists the repo's personas and workflows and is
what turns the gate on; `workflow.json` names one of those workflows.

**The walk identity.** Walk as an identity that no automated suite owns. An
identity is owned when a CI workflow, or e2e setup, fixtures or teardown,
signs in as it or creates, resets or deletes its data. List the owned ones in
`.qa/config.json` `automation_identities`. If the repo has no unowned identity
for the persona, walk with the owned one only when no automated run on the
same data overlaps the walk. Check running CI before you start, and again
after you finish for any run whose interval intersected the walk window. Say
in the evidence that the identity is shared. The evidence packet records all
of it in `authentication.identities`, one block per persona walked
(verified-qa-e2e evidence contract), and
the gate refuses a packet that declares any listed identity unowned. Labels
match after NFKC, smart quotes and dashes to ASCII, lowercase, strip and dropping an `@domain` suffix; a
mixed-script, look-alike or non-Latin label, or one containing a listed label, is refused. **CI's own run as the
walk** is the `owner_run` case: the suite that owns the identity, recording its
own run, adds `walker: {kind: "owner_run", owner: <the block's owner>, run_id,
run_url}` and is not held to the unowned-identity rule; the walk window, the
after-walk overlap check and the disclosure still apply. It needs the label
in `automation_identities` and a `run_url` of this repository's `origin`
naming `run_id` (with `/attempts/<n>` for a re-run), and the gate checks that
attempt with `gh api`: it must have completed with success, on the walked
commit, and its own start and last update must enclose the walk window, whose
times carry an offset (verified-qa-e2e evidence contract). Why: on



2026-09-25 two interactive walks on one repo signed in as the deployed CI
suite's own e2e identities on the shared preview DB. The suite's setup
recreated their data mid-walk, the walks changed data under the suite, and a
deployed gate went 36/38 on a build that was 38/38 twelve minutes earlier.

```json
{"workflow": "invite-and-accept", "persona": "member", "entry": "/invite link from email",
 "outcome": "lands in workspace with member rights", "steps": ["open invite", "accept", "first login"],
 "target": {"url": "https://app.example.test", "sha": "<full sha>"}}
```
