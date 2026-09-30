#!/usr/bin/env python3
"""Guard the PR-review skill sources against directives that contradict their owners."""

from __future__ import annotations

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
    r"(?is)hermes[^.]{0,200}?(?:completion gate|publish(?:ing)? gate|must succeed before (?:posting|publishing))"
)


def sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))


class ReviewSkillSourceTests(unittest.TestCase):
    def test_hermes_is_never_described_as_a_completion_gate(self) -> None:
        offenders = []
        for path in sorted(SKILLSETS.rglob("*.md")):
            for sentence in sentences(path.read_text(encoding="utf-8")):
                if HERMES_AS_GATE.search(sentence) and "used to read" not in sentence.lower():
                    offenders.append(f"{path.relative_to(ROOT)}: {sentence[:160]}")
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
