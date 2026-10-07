#!/usr/bin/env python3
"""Guard the PR-review skill sources against directives that contradict their owners."""

from __future__ import annotations

import hashlib
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLSETS = ROOT / "skillsets"
CODEX_SKILL = SKILLSETS / "pr-review/shared/high-signal-pr-review/SKILL.md"
CODEX_CONTRACT = SKILLSETS / "pr-review/shared/high-signal-pr-review/references/pr-review-output-contract.md"
SHARED_CONTRACT = SKILLSETS / "pr-review/references/pr-review-output-contract.md"
GLOBAL_AGENTS = ROOT / "GLOBAL_AGENTS.md"

# Hermes help is mandatory to attempt and never a publish blocker (high-signal-pr-review,
# "Hermes advisor pass"). Calling it a completion/publish gate once suppressed real findings.
HERMES_AS_GATE = re.compile(
    r"(?is)(?:hermes[^.]{0,200}?(?:completion gate|publish(?:ing)? gate|must succeed before (?:posting|publishing))"
    r"|not complete (?:when|if|until|without)[^.]{0,80}?hermes (?:result|answer|pass|review|verdict)"
    r"[^.]{0,40}?(?:is |was )?(?:missing|absent|unavailable|not returned|arrives)"
    r"|(?:complete|done|finished|post(?:ed|ing)?|publish(?:ed|ing)?|approv(?:e|ed|al)|merg(?:e|ed|ing))"
    r"[^.]{0,20}? only (?:after|when|once|if)[^.]{0,60}?hermes"
    r"|(?:do not|don't|never|must not|cannot) (?:post|publish|approve|merge|complete|finish)[^.]{0,60}?"
    r"(?:until|before|without)[^.]{0,40}?hermes (?:returns|answers|responds|replies|approves|accepts|verdict|result)"
    r"|wait for hermes[^.]{0,40}?before (?:posting|publishing|approving|merging)"
    # holding the review back for Hermes, in any order (Hermes 2026-10-07, kit-review-skill-merge r4)
    r"|(?:hold|defer|delay|pause|postpone|withhold)[^.]{0,40}?(?:post|publish|the review|verdict|approv)[^.]{0,60}?"
    r"(?:until|before|while|unless)[^.]{0,60}?hermes"
    r"|(?:review|verdict)[^.]{0,30}?(?:unposted|unpublished|on hold)[^.]{0,60}?(?:until|before|while|unless)[^.]{0,60}?hermes"
    r"|(?:retry|re-?send|re-?run|try) hermes[^.]{0,60}?before (?:posting|publishing|approving|merging))"
)
HERMES_SECTION_SHA256 = "1735148db18dd464b86f4460df3f7b977226b20532be925e59a7463350b6a1d3"
# The whole other-PR block, verbatim (whitespace collapsed): an added instruction that keeps every asserted phrase,
# such as holding the post after a Hermes timeout, still changes this text (Hermes 2026-10-07, kit-review-skill-merge r4).
OTHER_PR_BLOCK = " - ".join((
    "Hermes is an advisor, mandatory to attempt and never a publish blocker.",
    "If it does not answer (transport fault, capacity, timeout), post your independently evidenced verdict unchanged. "
    "Do not downgrade `REQUEST_CHANGES` to `COMMENT` or soften a finding.",
    "Record `Hermes gate: BLOCKED` in the operator close-out only, and say there that the verdict is unadvised.",
    "Do not claim the pass happened, and do not silently replace Hermes with another model.",
    "Acknowledge queued automation work normally once the review is confirmed posted. "
    "Hermes being down is not a reason to leave an item unacknowledged; only failing to post is.",
    "Skipping the attempt while Hermes is reachable leaves the review incomplete.",
    "An earlier rule that made the advisor's answer a condition for posting suppressed real findings: "
    "a reviewer held back two located defects because two advisor calls timed out.",
))
# Each thing the review skill asks Hermes to challenge or name (Hermes 2026-10-06, kit-review-skill-merge r2:
# assert every item, not the start of the sentence).
CHALLENGE_ITEMS = (
    "Ask Hermes to challenge business-rule coverage", "changed-path correctness", "auth, security, data and API contracts",
    "regression risk", "validation sufficiency", "and each candidate finding",
    "Ask it to name false positives, missing evidence and overlooked defects",
)
# The retired hermes-assisted-pr-review's other rules that still apply, each as its own phrase.
RETAINED_RULES = (
    "a verdict from `accept | revise | reject` with per-finding evidence", "any other shape counts as no verdict",
    "Agreement between Hermes and your own separate judgment is a confidence source",
    "Hermes saying it is sure is not",
    "Acknowledge queued automation work normally once the review is confirmed posted",
    "Skipping the attempt while Hermes is reachable leaves the review incomplete",
    "Re-fetch the live head and review state just before you post, acknowledge, or merge",
    "discard the advice as stale and run a fresh same-topic review of the delta",
    "Never let advice about an older head support a post or a merge",
    "the queue acknowledgement status, when the review came from a queue",
)
# Extra agent-loaded files to scan (e.g. installed skills with no kit source), os.pathsep-separated.
CHAIN_ENV = "REVIEW_CHAIN_PATHS"


def sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))


def plain(text: str) -> str:
    """Drop Markdown emphasis, code marks, and link syntax so formatting cannot hide a sentence."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return re.sub(r"[*_`~]+", "", text)


# No exemptions of any kind: context can reinstate quoted or "historical" wording, so explain withdrawn
# rules without restating them. This pins known gate phrasings; it cannot prove every paraphrase absent.
def gate_sentences(text: str) -> list[str]:
    return [s for s in sentences(plain(text)) if HERMES_AS_GATE.search(s)]


class ReviewSkillSourceTests(unittest.TestCase):
    def test_gate_predicate_controls(self) -> None:
        flagged = [
            "Its bounded Hermes advisor pass is a mandatory internal completion gate.",
            "The review is not complete when the Hermes result is missing, stale, or unverified.",
            "A review is not complete until the Hermes verdict arrives.",
            "Hermes must succeed before posting.",
            "A review is complete only after Hermes returns a verdict.",
            "Post the review only once Hermes has answered.",
            "Do not publish the review until Hermes returns.",
            "Never approve without the Hermes verdict.",
            "Wait for Hermes to answer before posting.",
            "This used to read differently; do not publish the review until Hermes returns.",
            'This used to read "Hermes is optional", and now the review is complete only after Hermes returns.',
            'This previously said "Do not publish the review until Hermes returns"; this requirement remains binding.',
            'This used to read "Hermes help is a completion gate", and that wording is still in force.',
            "If Hermes times out, hold the review until Hermes answers.",
            "Defer posting the verdict until a Hermes retry succeeds.",
            "Keep the review unposted while Hermes is unreachable.",
            "Retry Hermes once more before posting.",
        ]
        formatted = [
            "A review is complete **only after** Hermes returns a verdict.",
            "Its bounded `Hermes` advisor pass is a *completion gate*.",
            "The review is __not complete__ when the [Hermes](SKILL.md) result is missing.",
        ]
        allowed = [
            "Its bounded Hermes advisor pass is mandatory to attempt, best-effort to obtain, and never a publish blocker.",
            "An earlier version of this section made the advisor result a condition for finishing the review, "
            "and that suppressed real findings.",
            "The review is not complete when the Hermes attempt was skipped while Hermes was reachable.",
            "This skill is an authorization and completion gate.",
            "Do not silently replace Hermes with another model and do not claim the advisor pass happened.",
            "Post anyway, on your own evidence, if Hermes does not answer.",
            "Record Hermes gate: BLOCKED in the operator-facing close-out only.",
            "Keep the review on its own evidence when Hermes does not answer.",
            "If Hermes times out, post the review anyway.",
            "When Hermes cannot be reached, fix the transport and resend rather than merging unreviewed.",
        ]
        for sentence in flagged:
            self.assertEqual(gate_sentences(sentence), [sentence], sentence)
        for sentence in formatted:
            self.assertEqual(len(gate_sentences(sentence)), 1, sentence)
        allowed.append("It is **never** a *publish blocker*; `Hermes` help is best-effort.")
        for sentence in allowed:
            self.assertEqual(gate_sentences(sentence), [], sentence)
        # Quoting the withdrawn wording is never exempt, alone or with a sentence that reinstates it.
        quoted = 'This used to read "Hermes help is a completion gate", and that wording suppressed real findings.'
        self.assertEqual(gate_sentences(quoted), [quoted])
        self.assertEqual(len(gate_sentences(quoted + " Continue enforcing the quoted completion requirement.")), 1)

    def test_hermes_is_never_described_as_a_completion_gate(self) -> None:
        offenders = []
        for path in sorted(SKILLSETS.rglob("*.md")):
            for sentence in gate_sentences(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(ROOT)}: {sentence[:160]}")
        self.assertEqual(offenders, [])

    @unittest.skipUnless(os.environ.get(CHAIN_ENV), f"set {CHAIN_ENV} to scan installed files")
    def test_installed_review_chain_has_no_hermes_gate(self) -> None:
        offenders = []
        for raw in os.environ[CHAIN_ENV].split(os.pathsep):
            path = Path(raw).expanduser()
            for sentence in gate_sentences(path.read_text(encoding="utf-8")):
                offenders.append(f"{path}: {sentence[:160]}")
        self.assertEqual(offenders, [])

    def test_review_skill_carries_the_hermes_pass_for_both_acts(self) -> None:
        text = re.sub(r"\s+", " ", CODEX_SKILL.read_text(encoding="utf-8"))
        # Each rule must sit where it applies, not merely somewhere in the file (Hermes 2026-10-06,
        # kit-review-skill-merge r3): the section, and within it the block for each act.
        self.assertEqual(text.count("## Hermes advisor pass"), 1)
        section = text.split("## Hermes advisor pass", 1)[1].split(" ## ", 1)[0]
        self.assertEqual(section.count("**Reviewing someone else's PR:**"), 1)
        self.assertEqual(section.count("**Merging our own PR:**"), 1)
        others = section.split("**Reviewing someone else's PR:**", 1)[1].split("**Merging our own PR:**", 1)[0]
        own = section.split("**Merging our own PR:**", 1)[1].split("**Fresh head.**", 1)[0]
        self.assertIn("bb fleet validate", section)
        for rule in (
            "Hermes is an advisor, mandatory to attempt and never a publish blocker",
            "If it does not answer (transport fault, capacity, timeout), post your independently evidenced verdict unchanged",
            "Do not downgrade `REQUEST_CHANGES` to `COMMENT` or soften a finding",
            "Record `Hermes gate: BLOCKED` in the operator close-out only",
            "Hermes being down is not a reason to leave an item unacknowledged",
        ):
            with self.subTest(act="someone else's PR", rule=rule):
                self.assertIn(rule, others)
        for rule in (
            "Hermes reviews every one of our PRs before merge",
            "A defect it names blocks the merge until it is fixed and Hermes, on the same topic, no longer names it",
            "An objection about evidence or method that names no defect does not block",
            "fix the transport and resend rather than merging unreviewed",
        ):
            with self.subTest(act="our own PR", rule=rule):
                self.assertIn(rule, own)
        # The section is pinned by digest (whitespace collapsed): an instruction added anywhere in it, in any wording,
        # fails here. To change the section, review the new text against both acts and update the digest.
        self.assertEqual(hashlib.sha256(section.encode()).hexdigest(), HERMES_SECTION_SHA256,
                         "the Hermes advisor pass section changed: review it against both acts, then update the digest")
        # Posting a review of someone else's PR never waits on Hermes: the block is pinned verbatim, so nothing can
        # be added to it, and it has no blocking or gate wording.
        self.assertEqual(others.strip().rstrip(" -"), OTHER_PR_BLOCK)
        self.assertNotIn("blocks", others)
        self.assertEqual(gate_sentences(others), [])
        # The retired skill's rules that still apply, the stale-head rule among them (Hermes 2026-10-06,
        # kit-review-skill-merge r1 and r2): one assertion per phrase, inside the section.
        for item in CHALLENGE_ITEMS + RETAINED_RULES:
            with self.subTest(rule=item):
                self.assertIn(item, section)
        # The folded-in skill is retired; nothing may send an agent to it.
        self.assertNotIn("hermes-assisted-pr-review", text)

    def test_codex_contract_carries_the_pre_review_packet_rule(self) -> None:
        text = CODEX_CONTRACT.read_text(encoding="utf-8")
        self.assertIn("attach both JSON and Markdown packets", text)

    def test_board_requirements_are_proportional_and_keep_required_evidence(self) -> None:
        global_text = re.sub(r"\s+", " ", GLOBAL_AGENTS.read_text(encoding="utf-8"))
        self.assertIn("configured or linked authoritative ticket board", global_text)
        self.assertIn("continue independent authorized work", global_text)
        for path in (CODEX_SKILL, CODEX_CONTRACT, SHARED_CONTRACT):
            text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
            self.assertNotIn("the kit's `GLOBAL_AGENTS.md` board regression rule does", text)
            self.assertIn("board", text.lower())


if __name__ == "__main__":
    unittest.main()
