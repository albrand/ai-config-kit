# Definition of done

Done means the QA can see, for each ticket, that every acceptance criterion is
proven by a scenario whose test ran, failed when the behaviour broke, passes,
and runs in CI. Report it in this shape, in plain language.

## Final report

**Setup** (only what changed)

- Repository state found, and what you built (Playwright config, Allure, QA
  command, CI workflows, authorship check, board reporting).
- Where the tests live, and the pull requests that carry the work.
- What the repository owner still has to do (required checks, the QA team, the
  App, secrets), as a checklist.

**Per ticket**

| Criterion | Scenario | Test | Seen failing | Local | CI |
|---|---|---|---|---|---|
| AC-1f3a9c2e "shows the address" | QAS-7K2M9P | `e2e/qa/vendors/vendor-dialog.spec.ts` "vendor dialog shows..." | inverted the address assertion: "expected '500 Pine St' not found" | passed | passed, run 123, commit `abc1234` |

Followed by the decisions (criteria with no automated scenario and why), the
questions asked with their answers and who answered, and anything blocked or
awaiting implementation with what unblocks it.

**Evidence**

- Local run: the command, the commit, the counts (passed, failed, flaky), and
  where the Allure report is.
- CI: the pull request, the gate run link and result, the Allure artifact, the
  bot's review, and the deliberate-failure run that turned it red.
- Board reporting: the ticket and comment link, or "declined" or "not set up".

## Verdicts

Give one per goal: **PASS** (shown with a run), **FAIL** (it ran and did not
work), **BLOCKED** (could not be attempted, and why), **NOT RUN** (no
evidence). A goal without a run is NOT RUN, not PASS. One goal's PASS does not
cover another.

Required goals:

1. Every criterion of every requested ticket has a scenario or a decision.
2. Every scenario's test was seen failing, then passing (or is awaiting
   implementation, with the reason).
3. The local run produces an Allure report with every scenario linked to its
   ticket.
4. CI runs the scenarios on a pull request from wherever the tests live, and
   the result matches the local run.
5. A deliberate failure turns the CI check red and the bot requests changes
   with the failing scenario named.
6. The QA authorship check names the approver of each scenario.
7. Board reporting: works with one approved post, or declined.

The work is complete only when 1 to 6 are PASS and 7 is PASS or declined.
