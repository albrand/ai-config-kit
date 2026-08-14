---
name: orchestrator-lessons
description: >
  Use when running a fleet of agents, or when the same class of mistake keeps
  recurring across sessions. Failure patterns that repeat, why each one survives
  review, and the check that catches it. Read before declaring work done.
verify: "test -n \"$HOME\""
verified: 2026-08-14
---

# Lessons an orchestrator keeps having to relearn

Every entry here cost real rounds. They are written as the check to run, not as
advice, because advice does not fire and a check does.

## Verify the thing you did not change

Nearly every regression in a long session comes from a change that worked and
broke its neighbour. Padding a panel broke the thread view. Moving an element
out of a React row fixed a control and dropped the element into the wrong
corner. Splitting a ternary to add a caption made a loading skeleton render on
top of live data.

In each case the new behaviour was verified and the surrounding behaviour was
not.

**Check:** after any change, exercise the adjacent surface — the page you did
not open, the branch you did not take, the filter you did not click. If a change
touches shared layout, open a different screen before calling it done.

## A tool that reports success is not a tool that worked

`resumeSession` returned `{threadId: "thr_..."}` and the thread was in `error`.
`bb plugin reload` reported `running` while serving the previous build, because
the new one had failed to compile. An edit that matched nothing applied cleanly
and silently did nothing.

**Check:** assert on the RESULT, not the response. A spawn is verified by the
thread reaching a non-error state. A build is verified by the rendered output.
An edit is verified by reading the file back, or by a test that fails without it.

## One source per answer

A report that draws from two populations will eventually mix them. Filtering to
one provider returned burn from transcripts and a turn count borrowed from a
different ledger — one row, which made a project's parts sum to one more than
the project itself.

The tempting patch is a fallback: when source A is empty, use source B. That is
not a fallback, it is a substitution, and it produces numbers nobody can
reconcile.

**Check:** for any figure, name the single population it came from. If a filter
cannot be expressed on that source, either express it — the data is usually
recoverable — or say the dimension is unavailable. Never quietly swap corpora.

## Assert on every metric, not the one you looked at

A combination sweep checked `weighted`, found it exact, and the conclusion
became "combinations partition exactly". `turns` was off by one the whole time.

**Check:** when verifying a partition or an invariant, iterate the metrics the
thing actually reports. One passing metric is evidence about one metric.

## Do not style what you do not render

Three regressions in one session came from writing into another component's DOM:
padding its scroll containers, inserting into its rows, and leaving inline
styles behind after a revert that a running client kept applying.

Reading another component's geometry is safe. Writing to it is not.

**Check:** position by measuring, never by inserting. If a plugin needs room in
someone else's layout, that is a request to the host, not something to take.

## Fixtures catch what corpus checks cannot

Four rounds of reconciliation against live data missed an edit that had silently
failed. A twenty-line fixture caught it on the first run, because a fixture
tests a PATH while a corpus check tests a TOTAL — and totals can agree while a
path is dead.

Corpus data also moves under you: a session written during a scan produced a
"failure" that cost a review round to explain.

**Check:** every parser gets fixtures for its edge cases, especially the schema
variants. Reconciliation is for aggregates; fixtures are for behaviour.

## The reviewer's job is to refuse you

A reviewer that keeps rejecting is working. Every rejection in this project
named something real: an under-reporting figure called a "known gap" when it was
a blocker, evidence that was derived rather than raw, a claim contradicted by
the artifact attached to it.

The failure mode is arguing with the verdict or sending more prose. The fix is
sending what it asked for — raw inputs it can recompute — or fixing the thing.

**Check:** before disputing a verdict, ask what evidence would settle it, then
produce that. If the answer is "a test I have not written", write it.

## Members that report nothing are not working

Idle members held "so they can iterate later" consume a worktree and make the
board overstate work in flight. A member that has reported nothing for an hour
is either blocked or done and does not know it.

**Check:** ask every idle member for what it has NOW, even partial. Retire or
redirect anything that answers with nothing twice.

## Shared context goes stale and then lies

A member wrote "card #6 complete, no scheduler semantics changed" into group
memory; both halves were wrong. Anything reading it afterwards was misled, and
nothing in the system knew.

**Check:** context entries carry who wrote them and when. Before acting on one,
confirm it against the artifact rather than the note. Correct entries in place
when they are found wrong — a stale note is worse than an absent one.

## Report the work that was rejected

Two of three finished pieces were rejected on substance and are better for it.
Reporting "0 done" is more useful than counting them, because the board is a
claim about reality and inflating it destroys its only value.

**Check:** Done means accepted. Anything else is In Review, however finished it
feels.
