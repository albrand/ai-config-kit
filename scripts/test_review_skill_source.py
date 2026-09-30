#!/usr/bin/env python3
"""Guard the PR-review skill sources against directives that contradict their owners."""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLSETS = ROOT / "skillsets"
CODEX_SKILL = SKILLSETS / "pr-review/codex/high-signal-pr-review/SKILL.md"
CODEX_CONTRACT = SKILLSETS / "pr-review/codex/high-signal-pr-review/references/pr-review-output-contract.md"
SHARED_CONTRACT = SKILLSETS / "pr-review/references/pr-review-output-contract.md"
GLOBAL_AGENTS = ROOT / "GLOBAL_AGENTS.md"

# Hermes help is mandatory to attempt and never a publish blocker (hermes-assisted-pr-review,
# "Failure behavior"). Calling it a completion/publish gate once suppressed real findings.
HERMES_AS_GATE = re.compile(
    r"(?is)(?:hermes[^.]{0,200}?(?:completion gate|publish(?:ing)? gate|must succeed before (?:posting|publishing))"
    r"|not complete (?:when|if|until|without)[^.]{0,80}?hermes (?:result|answer|pass|review|verdict)"
    r"[^.]{0,40}?(?:is |was )?(?:missing|absent|unavailable|not returned|arrives))"
)
# Extra agent-loaded files to scan (e.g. installed skills with no kit source), os.pathsep-separated.
CHAIN_ENV = "REVIEW_CHAIN_PATHS"


def sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))


def gate_sentences(text: str) -> list[str]:
    return [s for s in sentences(text) if HERMES_AS_GATE.search(s) and "used to read" not in s.lower()]


class ReviewSkillSourceTests(unittest.TestCase):
    def test_gate_predicate_controls(self) -> None:
        flagged = [
            "Its bounded Hermes advisor pass is a mandatory internal completion gate.",
            "The review is not complete when the Hermes result is missing, stale, or unverified.",
            "A review is not complete until the Hermes verdict arrives.",
            "Hermes must succeed before posting.",
        ]
        allowed = [
            "Its bounded Hermes advisor pass is mandatory to attempt, best-effort to obtain, and never a publish blocker.",
            'This used to read "Hermes help is a completion gate", and that wording suppressed real findings.',
            "The review is not complete when the Hermes attempt was skipped while Hermes was reachable.",
            "This skill is an authorization and completion gate.",
        ]
        for sentence in flagged:
            self.assertEqual(gate_sentences(sentence), [sentence], sentence)
        for sentence in allowed:
            self.assertEqual(gate_sentences(sentence), [], sentence)

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

    def test_codex_skill_points_to_hermes_skill_with_attempt_semantics(self) -> None:
        text = re.sub(r"\s+", " ", CODEX_SKILL.read_text(encoding="utf-8"))
        self.assertIn("`hermes-assisted-pr-review`", text)
        self.assertIn("mandatory to attempt", text)
        self.assertIn("never a publish blocker", text)
        self.assertNotIn("/.bb/skills/hermes-assisted-pr-review", text)

    def test_codex_contract_carries_the_pre_review_packet_rule(self) -> None:
        text = CODEX_CONTRACT.read_text(encoding="utf-8")
        self.assertIn("attach both JSON and Markdown packets", text)

    def test_board_precedence_matches_global_agents(self) -> None:
        global_text = re.sub(r"\s+", " ", GLOBAL_AGENTS.read_text(encoding="utf-8"))
        self.assertIn("unavailable access means `board regression gate blocked`", global_text)
        for path in (CODEX_SKILL, CODEX_CONTRACT, SHARED_CONTRACT):
            text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
            # A cross-reference to a proportional rule in GLOBAL_AGENTS.md is false while that
            # file carries the strict board rule.
            self.assertNotRegex(text, r"proportional board rule in `GLOBAL_AGENTS\.md`", str(path))
        for path in (CODEX_SKILL, CODEX_CONTRACT):
            text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
            if "proportional" in text.lower():
                self.assertRegex(text, r"(?i)(?:outrank|wins over|yields to)", str(path))


if __name__ == "__main__":
    unittest.main()
