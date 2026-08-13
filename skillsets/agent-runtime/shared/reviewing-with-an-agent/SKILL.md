---
name: reviewing-with-an-agent
description: >
  Use when sending work to another agent for review, critique or validation, or
  when following up on a review that already happened. Covers why a re-review
  must continue the original conversation, and what a reviewer needs in order to
  answer instead of flailing.
verify: "test -n \"$HOME\""
verified: 2026-08-13
---

# Reviewing with another agent

## A re-review continues the thread — it does not start one

The failure is easy to walk into: round one spawns a reviewer, it answers, you
fix things, and round two spawns a *fresh* reviewer to ask "did the fixes land?"

That reviewer has never seen the original. So you re-send the whole context to
give it a chance, and now:

- it judges a **summary you wrote** rather than the work it previously examined,
  which is precisely the material a biased summary can hide;
- it cannot notice that a point it made was quietly dropped;
- you pay the full context cost again, every round — and re-read context is
  usually the dominant cost, not output.

Key the conversation by a stable **topic** and send follow-ups into the same
thread. Under bb, `fleet_review` takes a `topic` for exactly this; consultations
sharing a topic share a thread. Standing reviews (a weekly audit, say) should use
one long-lived conversation so the reviewer sees what it said last time and what
changed since.

The corollary: **do not archive a review thread on completion.** Archiving makes
continuation impossible and forces the respawn that caused the problem.

## Tell a reviewer whether it may use tools

A reviewer handed a design description with no filesystem to inspect will try to
inspect one anyway, hit a tool-call guardrail, and return an apology about the
guardrail instead of a review. Say which mode you want:

- **Document review** — "Do not call any tool. Everything you need is in this
  message. Reason from the text." Use when the artifact is described, not
  checked out.
- **Repository review** — give it the paths and let it read.

## Ask for a verdict it can lose

State the questions numerically and demand a shape: `RESOLVED / PARTIAL / NOT
RESOLVED` per point, with the specific claim being judged. A reviewer told to
"check this over" agrees; one told "say which of these three is inadequate and
why" finds the inadequate one.

Give it permission to be blunt and an explicit word budget. Long reviews drift
toward restating the work back to you — say "do not restate the work" outright.

## Give the reviewer something it can inspect

A reviewer that cannot read your artifacts can only judge your prose about them,
and a careful one will keep saying "revise" no matter how detailed the prose
gets. That is not stubbornness — it is correct. Three rounds were spent this way
before the actual blocker became visible: the reviewer ran on a different machine
with no read access to the files under review.

Put the artifacts where the reviewer already is. A diff, the before and after
files, the framework files a claim depends on, raw command output — copied to a
path on its own filesystem — turned three `revise` verdicts into an `accept` in
one round, because it checked the claims itself instead of weighing an assertion.

Two things follow. Say explicitly which tools it should use and where to look, or
a reviewer told "do not use tools" in an earlier round will keep obeying that.
And name what you still cannot make inspectable — source on another machine, a
browser it has no access to — so the accept is scoped rather than assumed to
cover everything.

## Take the loss

The point of the round is the finding you did not want. If a reviewer says a fix
is `PARTIAL` and you can see why, fix it rather than arguing the label — and if
you disagree on evidence, say so in the same thread, where the disagreement is
on the record and the reviewer can answer it.
