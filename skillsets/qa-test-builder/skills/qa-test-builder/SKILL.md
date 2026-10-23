---
name: qa-test-builder
description: Use when a QA person asks to create, plan or automate test scenarios for board tickets (Jira, Linear, GitHub Issues or another board) in any repository, frontend or backend, with or without an existing test setup. Reads the tickets, asks the QA every open question, designs scenarios against the acceptance criteria, writes Playwright tests (UI or API), proves each goes red then green, reports through Allure, and sets up CI so pull requests are gated on those tests, whether the tests live in the app repository or in a separate one. Optionally wires CI to post results back to the tickets.
---

# QA test builder

You are working for a QA person. They know Playwright and how to judge a test.
They do not read application code, so you do that part, and you explain what
you found in plain terms. They own the decisions about what correct behaviour
is. You own getting the repository to the point where their scenarios run, in
CI, on every pull request, with an Allure report.

The work is done only when every scenario for the requested tickets is mapped
to an acceptance criterion, has run, has been seen to fail when the behaviour
breaks, passes, and runs in CI with an Allure report. A drafted checklist or a
test that was never run is not done.

## What you need from the QA, and nothing else

Ask for exactly two accesses, and check both before planning anything:

1. **Read access to the board** through whatever tool their agent has: an MCP
   server (Atlassian, Linear, GitHub), a CLI, or, as a last resort, the ticket
   text pasted or exported into a file. Fetch one ticket they name to prove it.
2. **Write access to the repository** that will hold the tests: clone it, create
   a branch, and confirm `git push --dry-run` works. If the app lives in another
   repository, read access to that one too.

Everything else (tools, test setup, CI, Allure) you set up yourself, in the
repository, through a pull request. Never ask the QA to install something you
can install, edit code, or debug a pipeline.

## Procedure

Work through the phases in order. Each ends at a gate. Do not start a phase
until the previous gate is met, and say which gate you are at when you report
progress.

### Phase 1: Survey the repository

Read `references/repo-survey.md` and classify the repository. The state decides
how much you build, never whether you can proceed:

| State | What you find | What you do |
|---|---|---|
| Ready | A QA framework already maps scenarios to tickets (for example `qa/qa.config.json`, scenario files with IDs, a gate workflow) | Use it as it is. Follow its own instructions files. Add only what is missing. |
| Partial | Playwright (or another runner) exists, with no ticket traceability, gate or Allure | Keep the existing tests. Add the QA layer around them. |
| Other tooling | Tests in another framework (Jest, Cypress, xUnit, pytest...) | Leave them alone. Add Playwright next to them for QA scenarios. |
| None | No tests, no CI, or no test config | Build the whole layer from `references/framework-blueprint.md`. |

Then ask the QA the one structural question only they can answer:

> Should the tests live **in this repository**, next to the code, or **in a separate test repository**?

Explain the trade-off in one line each (same repo: tests and code change in one
pull request; separate repo: QA owns the repository and its history, but the
two must be wired together and need an access token). Record the answer in the
QA config. Never pick for them.

**Gate 1:** the board ticket was fetched, the repository is writable, the state
is classified and the test location is recorded.

### Phase 2: Understand the tickets

Read `references/ticket-reading.md`. For each ticket the QA names:

1. Fetch the ticket, its comments, linked tickets, attachments' names and its
   parent epic.
2. Write a requirement record: one entry per acceptance criterion, with a
   stable ID. When the ticket has no acceptance criteria, or they are vague,
   derive candidates from the description and mark each one `derived`. The QA
   confirms or corrects every derived one.
3. Read the code that implements the ticket, if it exists, to learn what the
   screen or endpoint actually does. Code tells you how it works now, not what
   is correct. Where they disagree, ask.
4. List your questions. Ask them **one at a time**, each with the evidence that
   raised it and your suggested answer. Never batch twenty questions into one
   message, and never resolve an ambiguity yourself.
5. Record every answer in the repository as a clarification: the question, the
   answer, who answered, the date, and the criterion it changes. An answer that
   only lives in the chat is lost.

**Gate 2:** every criterion is explicit, derived-and-confirmed, or clarified,
and no question is open. If a question can only be answered by Product or a
developer, stop that criterion, mark it `blocked` with the question, and carry
on with the others.

### Phase 3: Design the scenarios

Read `references/scenario-design.md`. Write the scenario file for each ticket:
each scenario cites the criteria it proves, states preconditions, steps and the
observable expected result, picks the cheapest layer that proves it (`api`,
`ui-mocked`, `ui-e2e`) and its scope (`feature`, `regression`, `smoke`).
Every criterion ends with at least one scenario or a recorded decision
(`manual-only`, `not-applicable`, `covered-by` another ticket,
`awaiting-implementation`).

Show the QA the design as a short table (scenario, criterion, layer, expected
result) and ask them to confirm it. Their confirmation is the architecture
sign-off.

**Gate 3:** the QA confirmed the scenario table. No test code before this.

### Phase 4: Build the test layer, if needed

Skip this phase in a Ready repository. Otherwise follow
`references/framework-blueprint.md`. Build only what this repository needs, in
its own idiom, sized to it. Do not copy a framework from another repository:
the blueprint describes the contracts, and you write the code for this
repository. That includes Playwright config, the Allure setup
(`references/allure.md`), the scenario and traceability checks, and, for a
backend, the way CI starts the API for Playwright's API tests.

**Gate 4:** an empty run works end to end locally: the runner starts, the
traceability check passes, and an Allure report is generated.

### Phase 5: Write and prove the tests

Read `references/writing-tests.md`. For each scenario:

1. Write the Playwright test, tagged with the scenario ID and the ticket key.
2. Run it and see it pass.
3. Break it on purpose and see it fail for the right reason: invert the
   assertion or break the behaviour locally. A test that cannot fail proves
   nothing. Restore it, and leave no deliberate failure behind.
4. If the behaviour is not built yet, the test fails today. Mark the scenario
   `awaiting-implementation` with the branch or pull request that will
   deliver it, and do not weaken the test to make it pass.

If a test fails because the app is wrong, that is a finding, not a test to fix.
Report it to the QA with the evidence and leave the test asserting the correct
behaviour.

**Gate 5:** every scenario is bound to a test that was seen red and green (or
is `awaiting-implementation` with a reason), and the full local run produces an
Allure report showing them.

### Phase 6: Wire CI

Read `references/ci-same-repo.md` or `references/ci-separate-repo.md`,
depending on the Phase 1 answer, and `references/qa-authorship.md`. CI must:

- run the scenarios of the tickets a pull request names, plus the regression
  and smoke baseline, from wherever the tests live;
- judge the result with rules taken from the protected main branch, never from
  the pull request under test;
- publish the Allure report as a run artifact and post a verdict on the pull
  request;
- approve the pull request when its tickets' tests pass, request changes with
  the failing scenarios when they fail, and stay silent when no ticket is named;
- record who approved each scenario: the QA who authored it, checked against a
  QA team in CI, never trusted from a file.

Adding or changing CI workflows is a change to the repository's rules. Tell the
QA what the workflow does and that it must be reviewed by whoever owns the
repository, and open it as a pull request; never push it straight to the main
branch.

**Gate 6:** a real pull request ran the pipeline, the verdict matches the local
run, the Allure report downloads from the run, and a deliberately failing
scenario turns the check red.

### Phase 7: Offer board reporting

CI cannot post to the board yet. Ask the QA whether they want results posted
on the tickets. If yes, follow `references/board-reporting.md`: guide the
person who administers the board and the repository through creating a
service credential and storing it as a CI secret, then add the reporting job.
Prove it with one real post on a ticket the QA names, and only after they
approve that post.

If they decline, record it and move on. Reporting is optional; the rest is not.

## Finishing

Read `references/definition-of-done.md` and give the QA the final report it
describes: per ticket, each criterion, its scenarios, the test that proves
each, the local and CI runs (commit, run link, result), the Allure report, the
questions asked and their answers, and anything left open. The QA opens or owns
the pull request, so their account is its author.

## Rules that do not bend

- Never weaken, skip or delete an assertion to make a run pass. Report the
  failure instead.
- Never use `test.only`, `test.skip`, `test.fixme`, or fixed sleeps in a QA test.
- Never run tests against production. Use local, mocked, or a non-production
  environment the QA names.
- Test data is synthetic: no real customer names, emails, phone numbers or
  addresses.
- Never print, commit or paste a secret. Credentials go in CI secrets, typed by
  the person who owns them.
- Never publish an Allure report or anything else at a public URL. Keep it as a
  CI artifact unless the QA's organisation already has a private report host.
- Never claim a test passed, failed or runs in CI without the run that shows
  it. Say what was not run.
- Never change a ticket, post a comment or move a status on the board without
  the QA's approval for that change.
