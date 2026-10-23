# QA authorship: who approved each scenario

The QA who writes a scenario and its test is the person approving that it is
the right check for the ticket. CI records that, and checks it against GitHub
rather than trusting a field in a file, so a developer's test does not count as
QA-approved by accident.

## The QA team

The repository owner creates a GitHub team for QA (for example `owner/qa`) and
adds the QA people. Guide them: Organization → Teams → New team, then add
members. Its slug goes in `qa.config.json` as `qaTeam`. Membership changes need
no code change.

Reading team membership needs a token with the organization's members: read
permission, which the built-in CI token does not have. Use the GitHub App from
`ci-same-repo.md`, with that permission added.

## The rule

A pull request that adds or changes a scenario file, or a test in the QA tests
folder, passes the `qa-authorship` check only when one of these holds at its
head commit:

1. Its author is a member of the QA team; or
2. A member of the QA team, other than the author, has an approving review on
   the current head commit.

And for every scenario the pull request adds or changes, `approvedBy` in the
scenario file names that person (the author in case 1, the reviewer in case 2).
The check reports, per scenario, who approved it and how.

If neither holds, the check fails with: "Changes to QA scenarios or tests need a
QA team member as author or approving reviewer: <files>". The developer asks a
QA to review; their approval re-runs the check (trigger on
`pull_request_review` too).

Make `qa-authorship` a required check on the main branch. Then everything on
main under the QA folders was authored or approved by QA, and the gate can
treat `approvedBy` on main as verified.

## How the gate uses it

- On the main branch, a scenario with `approvedBy` set and `binding.status`
  `draft` or `ready` counts as QA-approved.
- In a pull request, a scenario it adds or changes counts as QA-approved only if
  that pull request's `qa-authorship` check passes. The gate reads that result
  from the same run (same workflow), not from the file.
- A feature scenario that is not QA-approved makes the verdict `UNAPPROVED`
  instead of `VERIFIED`, so the approval bot does not approve.

## Edge cases

- A QA who opens a pull request that also changes app code is still the author;
  the scenarios count as approved. Code review of the app change is a separate,
  human matter.
- A bot (dependency updates) that touches QA files fails the check and needs a
  QA review.
- Removing a scenario counts as a change: it needs QA authorship or review too.
- If the team does not exist yet, do not weaken the rule. Report that the check
  is blocked on the team and leave it failing until the owner creates it.
