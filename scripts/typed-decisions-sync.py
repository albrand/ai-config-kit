#!/usr/bin/env python3
"""Keep the typed-decisions contract present everywhere an agent reads it.

Three things, all checked:
  1. the always-on block in every global instruction file (identical text);
  2. a skill-specific "Typed decisions here" block in every copy of each skill
     that owns a decision point -- kit sources AND installed copies, which have
     diverged on purpose (installed ones carry machine-local text) and so
     cannot be synced wholesale;
  3. the typed-decisions skill itself in every agent skill home.

A rule written into one file and missing from the next is installed but
inert: the agent reading the other file never sees it. --check exits 1 on
any gap; --falsify proves the check goes red when a block is removed.

Usage:
  typed-decisions-sync.py            write missing or stale blocks
  typed-decisions-sync.py --check    report only; exit 1 on any gap
  typed-decisions-sync.py --falsify  --check, plus proof the check can fail
"""
import os, re, shutil, sys, tempfile

H = os.path.expanduser
KIT = H("~/projects/agent-config-kit")
FOOT = "Contract: the `typed-decisions` skill."

SECTIONS = {
"meaningful-tests": """The per-goal verdict is pick-one, `PASS | FAIL | BLOCKED | NOT RUN`, and
nothing else. "Partially", "mostly works" and "works with a caveat" are
outside that space, and count as FAIL. PASS needs a check: the persona
completed the goal, read at target state. BLOCKED needs the named blocker.
Judge each goal separately; one goal passing never lifts another. The overall
claim is computed, not felt: any FAIL means not done, and any NOT RUN means
you may not write "tested".

Jev (`typed-decisions` section 10) may answer the semantic sub-questions (does this evidence show the
persona reaching the goal? does this report name a blocker?) as one more
isolated judge. It never produces PASS on its own: PASS still needs the check.""",

"finish-the-job": """"Am I done?" is a decision, so type it. Answer each yes/no with a check
behind it, not a feeling:

- In-scope work left? (re-read the original request)
- A found defect still unfixed?
- Siblings of the fixed bug searched?
- Every copy of a touched shared file identical? (`shasum` each home)
- Capability checked before saying blocked? (`bb-capability-check`)

Stopping is allowed only when every answer comes out clean. "Blocked" is
allowed only with the named blocker. Feeling done is a self-report, not a
check.

Batch the semantic questions (in-scope work left, given the request and a
summary of what changed?) into one Jev call (`typed-decisions` section 10). The mechanical ones stay
checks.""",

"scope-advisor": """Don't judge scope as a whole. For each requirement in the scope record, answer
three separate yes/no questions against the record (not the conversation):
`covered?`, `added-unrequested?`, `rests on an assumption only the user can
settle?`. The verdict is then computed:

- any `covered = no` or `added-unrequested = yes` → `revise`
- else any material user-only assumption → `clarification`
- else → `aligned`

Any other verdict is outside the declared space and counts as a failed
check: re-run it.

Run the three questions for every requirement in one Jev call (`typed-decisions` section 10):
`--yn covered`, `--yn added_unrequested`, `--yn user_only_assumption`, with the
scope record and a result summary as state. Answer them yourself too.
Agreement is `agreement(N=2)`; a disagreement means re-read that requirement.""",

"reviewing-with-an-agent": """Ask the reviewer for typed output, and say so in the brief:

- verdict: pick-one `accept | revise | reject`;
- per finding: a separate yes/no, "reproduces on the changed path?", with
  the evidence (command, file:line, observed output).

"Looks mostly fine" is outside that space: re-ask in the same conversation,
don't interpret it. Several reviewers who each reached the same answer on
their own is a confidence source. A reviewer saying it is "confident" is not.

Jev (`typed-decisions` section 10) is a cheap extra reviewer for the per-finding yes/no: same
packet, isolated, calibrated. Count it toward agreement. Never let it replace
a reviewer on a release or security verdict.""",

"delegating-to-glm": """When the delegated job is a decision (classify, triage, pass/fail, does this
reproduce), put the declared answer space in the brief and require
`{question, answer, evidence, confidence_source}` back. An answer outside the
space, or a confidence resting only on the delegate's own opinion, is a
failed delegate. Re-ask or escalate.

For pure classification, Jev (`typed-decisions` section 10) is faster and cheaper than a GLM
delegate and returns the typed answer natively. Prefer it unless the decision
needs reasoning or tools.""",

"pr-review": """Judge each candidate finding separately, against the diff and ticket, with
two typed questions:

1. Finding class (pick-one): `compile-or-runtime-break | wrong-changed-path-behavior
   | broken-contract (auth/data/security/API/env) | missing-required-validation
   | scoped-instruction-violation | none`. `none` is dropped. That is the
   high-signal filter, applied as a fixed list rather than a mood.
2. "Reproduces on the changed path?" (yes/no), backed by evidence. No
   evidence → not reported.

The review verdict is computed: any confirmed finding → `REQUEST_CHANGES`;
none → `APPROVE` (or `COMMENT` when only non-blocking notes remain). Don't
grade it as a whole.

Run question 1 (`--pick`) and question 2 (`--yn`) for every candidate in one
batched Jev call (`typed-decisions` section 10), as an isolated judge. It confirms nothing without
evidence, but a Jev `no` on reproduction sends that finding back for a check
before you report it. Keep code and ticket excerpts minimal, never secret.""",

"security-sweep": """The refute pass is one separate yes/no per candidate, judged without seeing
the other candidates: "exploitable on the target path after existing
mitigations?" A candidate is `confirmed` only when a check shows it (a
reproduced path or proof of concept), or when separate refuters each fail
to refute it. If you're unsure it's reachable, it's `not confirmed`.
Severity is a level from the contract's scale (critical/high/medium/low/info),
and each finding names the residual-exposure fact that places it there.

Add Jev (`typed-decisions` section 10) as one more blind refuter per candidate, and use `--level`
with the contract's anchors for severity. Jev alone never confirms a finding:
that stays a check or independent refuters.""",

"plan-arbiter": """The lane is pick-one from the declared candidates, never a lane invented
mid-decision. Score each candidate on separate yes/no questions: capability
verified? within budget? disjoint write ownership? a verification path that
doesn't rely on the lane's own report? Selection is computed from those
answers. A tie or an unknown escalates to the coordinator or the user; it
never falls to a default lane.

Put each yes/no, and the final pick (`--pick` over the declared lanes with
one-line descriptions), to Jev (`typed-decisions` section 10) as an isolated second judge. A
disagreement with your own selection escalates.""",

"hermes-assisted": """Ask Hermes for a verdict from `accept | revise | reject`, with per-finding
evidence. Any other shape counts as no verdict, recorded as advisor
unavailable/unusable. Under this skill's failure rules, that never blocks a
verdict you have evidenced yourself. Agreement between Hermes and your own
separate judgment is a confidence source. Hermes saying it is sure is not.

Jev (`typed-decisions` section 10) can pre-screen each finding's yes/no before the Hermes pass.
Jev and your own judgment agreeing is `agreement(N=2)`, whether or not
Hermes is available.""",

"harness-routing": """The model or lane is pick-one from the declared tiers. Decide it from
separate yes/no questions (reversible? mechanically verifiable? touches
security/auth/data/release? unexplained failure?), not a holistic "this feels
simple". Any risk trigger = yes removes the minimum-effort tiers. Low
confidence escalates up a tier, never down.

Put the risk-trigger yes/nos to Jev in one call (`typed-decisions` section 10), with the task summary
as state. Treat any trigger at p >= 0.25 as yes (conservative); that removes
the minimum-effort tiers.""",
}

HOMES = ["~/.agents/skills", "~/.bb/skills", "~/.claude/skills", "~/.codex/skills"]

def homes(skill):
    return [f"{h}/{skill}/SKILL.md" for h in HOMES if os.path.exists(H(f"{h}/{skill}/SKILL.md"))]

TARGETS = {
    "meaningful-tests": homes("meaningful-tests"),
    "finish-the-job": homes("finish-the-job"),
    "scope-advisor": [f"{KIT}/skillsets/scope-advisory/codex/scope-advisor/SKILL.md"] + homes("scope-advisor"),
    # shared kit skills reach every home through scripts/publish.mjs
    "reviewing-with-an-agent": [f"{KIT}/skillsets/agent-runtime/shared/reviewing-with-an-agent/SKILL.md"]
                               + homes("reviewing-with-an-agent"),
    "delegating-to-glm": [f"{KIT}/skillsets/agent-runtime/shared/delegating-to-glm/SKILL.md"]
                         + homes("delegating-to-glm"),
    "pr-review": [f"{KIT}/skillsets/pr-review/codex/high-signal-pr-review/SKILL.md",
                  f"{KIT}/skillsets/pr-review/claude/commands/code-review.md",
                  "~/.claude/commands/code-review.md"] + homes("high-signal-pr-review"),
    "security-sweep": [f"{KIT}/skillsets/security-review/codex/adversarial-security-sweep/SKILL.md",
                       f"{KIT}/skillsets/security-review/claude/commands/adversarial-security-sweep.md",
                       "~/.claude/commands/adversarial-security-sweep.md"
                       ] + homes("adversarial-security-sweep"),
    "plan-arbiter": [f"{KIT}/skillsets/cmux-hermes-orchestration/codex/plan-arbiter/SKILL.md",
                     f"{KIT}/skillsets/cmux-hermes-orchestration/claude/commands/plan-arbiter.md",
                     "~/.claude/commands/plan-arbiter.md"] + homes("plan-arbiter"),
    "hermes-assisted": homes("hermes-assisted-pr-review"),
    "harness-routing": homes("harness-routing"),
}

GLOBAL_BLOCK = """<!-- typed-decisions:begin -->
**Typed decisions (always-on)** — most agent steps are decisions (route, triage,
in scope, risky, severity, pass/fail, done, escalate), not writing. For each:
declare the answer space before asking (yes/no, pick-one, or a level whose
levels are written out); an answer outside it is a failed decision, never one to
interpret. Ask one atomic question at a time, judge each in isolation against
the same state, and compose the verdict with explicit logic. Gate action on
confidence — high acts, medium verifies, low escalates — and take confidence
only from agreement across isolated judgments, a measurable check, or a recorded
outcome history, never from a model's self-report. Typed is not correct: high
confidence still gets the checks irreversible, security and release work
require. Record each gated decision in the decision ledger with a findable
`--ref`, and resolve it (held or overturned) when the truth arrives, even when
the decision was another agent's. Run semantic atomic judgments on Jev,
the System One decision model (`typed-decisions` section 10, `jev.py`):
batched, isolated, recorded as `system-one`. Never in a blocking hook, never
with secrets or personal data, and alone never enough for an irreversible
or security call. Full detail: the `typed-decisions` skill.
<!-- typed-decisions:end -->"""

# Every global instruction file an agent on this machine loads at start.
GLOBALS = ["~/.claude/CLAUDE.md", "~/.bb/AGENTS.md", "~/.codex/AGENTS.md",
           "~/.config/opencode/AGENTS.md", f"{KIT}/GLOBAL_AGENTS.md"]

PAT = re.compile(r"<!-- typed-decisions:begin -->.*?<!-- typed-decisions:end -->", re.S)
ANCHOR = "<!-- token-efficient-orchestration:end -->"


# Ledger point each skill records to; see the typed-decisions skill, section 9.
RECORD = {
    "meaningful-tests": "`--point test-verdict`, one record per goal",
    "finish-the-job": "`--point done` with the computed answer",
    "scope-advisor": "`--point scope-verdict`",
    "reviewing-with-an-agent": "`--point review-finding` per finding",
    "delegating-to-glm": "the delegate's decision under its own point",
    "pr-review": "`--point review-finding` per finding and `--point pr-verdict`",
    "security-sweep": "`--point security-finding` per candidate",
    "plan-arbiter": "`--point route`",
    "hermes-assisted": "nothing by hand: Hermes verdicts are imported daily",
    "harness-routing": "`--point route`",
}


def skill_block(key):
    record = (f"\n\nRecord it in the decision ledger ({RECORD[key]}), with a `--ref` a later agent "
              "can find, and resolve it when the truth arrives.")
    return ("<!-- typed-decisions:begin -->\n## Typed decisions here\n\n"
            + SECTIONS[key] + " " + FOOT + record + "\n<!-- typed-decisions:end -->")


def upsert(text, want, is_global):
    if PAT.search(text):
        return PAT.sub(lambda m: want, text)
    if is_global and ANCHOR in text:
        return text.replace(ANCHOR, ANCHOR + "\n\n" + want, 1)
    return text.rstrip("\n") + "\n\n" + want + "\n"


def jobs():
    for p in GLOBALS:
        yield "global", p, GLOBAL_BLOCK
    for key, paths in TARGETS.items():
        if not paths:
            yield key, None, None
        for p in paths:
            yield key, p, skill_block(key)


def run(check, resolve=H, say=print):
    bad = 0
    for key, p, want in jobs():
        if p is None:
            say(f"MISSING-TARGETS {key}"); bad += 1; continue
        path = resolve(p)
        if not os.path.exists(path):
            say(f"NO-FILE {key} {p}"); bad += 1; continue
        text = open(path).read()
        new = upsert(text, want, key == "global")
        if new == text:
            continue
        if check:
            say(f"STALE   {key:24} {p}"); bad += 1
        else:
            open(path, "w").write(new); say(f"written {key:24} {p}")
    for h in HOMES:
        if not os.path.exists(resolve(f"{h}/typed-decisions/SKILL.md")):
            say(f"NO-SKILL {h}/typed-decisions"); bad += 1
    return bad


def quiet(_msg):
    """Sandbox runs report through the case verdicts, not raw lines."""


def falsify():
    """Mirror every target into a sandbox, damage one of each kind, expect red."""
    tmp = tempfile.mkdtemp()
    try:
        def resolve(p):
            return os.path.join(tmp, H(p).lstrip("/"))
        for _, p, _ in jobs():
            if p and os.path.exists(H(p)):
                os.makedirs(os.path.dirname(resolve(p)), exist_ok=True)
                shutil.copy(H(p), resolve(p))
        for h in HOMES:
            src = H(f"{h}/typed-decisions/SKILL.md")
            if os.path.exists(src):
                os.makedirs(os.path.dirname(resolve(f"{h}/typed-decisions/SKILL.md")), exist_ok=True)
                shutil.copy(src, resolve(f"{h}/typed-decisions/SKILL.md"))
        failures = []
        base = run(True, resolve, quiet)
        print(f"falsify: sandbox mirror of live tree -> {base} gap(s) (want 0)")
        if base != 0:
            failures.append("sandbox mirror of the live tree is not green")
        cases = [("global block removed from one file", GLOBALS[3]),
                 ("global block reworded in one file", GLOBALS[0]),
                 ("skill block removed from one copy", TARGETS["meaningful-tests"][0])]
        for label, p in cases:
            f = resolve(p)
            orig = open(f).read()
            damaged = (orig.replace("never from a model's self-report", "from the model")
                       if "reworded" in label else PAT.sub("", orig))
            assert damaged != orig, f"falsify case did not apply: {label}"
            open(f, "w").write(damaged)
            got = run(True, resolve, quiet)
            print(f"falsify: {label} -> {got} gap(s) (want >0)")
            if got == 0:
                failures.append(f"{label}: check stayed green")
            open(f, "w").write(orig)
        os.remove(resolve(f"{HOMES[0]}/typed-decisions/SKILL.md"))
        got = run(True, resolve, quiet)
        print(f"falsify: skill missing from one home -> {got} gap(s) (want >0)")
        if got == 0:
            failures.append("skill missing from one home: check stayed green")
        for msg in failures:
            print("FALSIFY-FAIL " + msg)
        print("falsify: " + ("ok" if not failures else "FAILED"))
        return len(failures)
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    if "--falsify" in sys.argv:
        live = run(True)
        print(f"live: {live} gap(s)" + (" -- in place everywhere" if not live else ""))
        sys.exit(1 if (falsify() or live) else 0)
    bad = run("--check" in sys.argv)
    if not bad:
        print("typed-decisions: in place everywhere")
    sys.exit(1 if bad else 0)
