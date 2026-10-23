# QA authorship: who approved each scenario

The QA who writes a scenario and its test is the person approving that it is
the right check for the ticket. CI works out who that is from GitHub, never
from a field in a file, so a developer's test does not count as QA-approved by
accident.

## The QA team

The repository owner creates a GitHub team for QA (for example `owner/qa`) and
adds the QA people. Guide them: Organization → Teams → New team, then add
members. Its slug goes in `qa.config.json` as `qaTeam`. Membership changes need
no code change. Personal-account repositories have no teams; there, ask the
owner to move the repository into an organization or keep a list of QA logins
in `policy.json` on the main branch, and say which one you used.

Reading team membership needs a token with the organization's members: read
permission, which the built-in CI token does not have. Use the GitHub App that
approves pull requests (`ci-same-repo.md`), with that permission added.

## The rule

A pull request that adds, changes or removes a scenario file or a test in the
QA tests folder is QA-approved only when one of these holds at its current
head commit:

1. its author is a member of the QA team; or
2. a member of the QA team other than the author has an approving review on
   the current head commit.

The approver is the author in case 1 and the reviewer in case 2. CI computes
it every time from the pull request; nothing is written into the scenario
files, so a new commit never invalidates the record and nothing in the pull
request can claim an approver.

## Where it runs

The check needs the App's secret, so it must never run in a job that checks out
or executes the pull request's code. Run it inside the `qa-approval` workflow
(`ci-same-repo.md`), which is triggered by `workflow_run` and runs from the
default branch:

- Add a tiny workflow, `qa-review-trigger`, on `pull_request_review` (submitted,
  dismissed). It has no permissions, checks out nothing and only finishes. Add
  it to `qa-approval`'s `workflow_run` list, so a QA review re-runs the
  decision.
- `qa-approval` lists the pull request's changed files through the API, finds
  QA files, reads the author and the reviews on the head commit, checks team
  membership, and publishes a check run named `qa-authorship` on the head
  commit with the approver per changed scenario:

  > QAS-7K2M9P (added): approved by @qa-person, author, member of owner/qa

- When no QA file changed, the check passes with "no QA scenarios or tests
  changed".
- When neither case holds, the check fails with: "Changes to QA scenarios or
  tests need a QA team member as author or approving reviewer: <files>".

Make `qa-authorship` a required check on the main branch, and in the branch
rule set its expected source to the App, so a status posted by any other
workflow cannot satisfy it. Then everything on main under the QA folders was
authored or approved by QA.

## How approval uses it

`qa-approval` approves a pull request only when the gate passed with tickets
named and `qa-authorship` passed. A feature scenario changed in the pull
request without QA authorship means no approval, with the reason.

The record of who approved each scenario is the `qa-authorship` check run on
the merged pull request, plus the pull request's author and reviews. The final
report lists it per scenario.

## Edge cases

- A QA who opens a pull request that also changes app code is still the author;
  the scenarios count as approved. Code review of the app change is a separate,
  human matter.
- A bot (dependency updates) that touches QA files needs a QA review.
- If the team does not exist yet, do not weaken the rule. Report the check as
  blocked on the team, and tell the owner exactly what to create.
