# Marketing advisor

A typed accept/revise judge for marketing copy and product names, calibrated
against the brand owner's past verdicts instead of a live taste test. It is
built for Brazilian mental-health marketing, aimed at psychologists and their
patients: the compliance gate applies the CFP, CDC and LGPD rules. The rubric
and the panel mechanics are brand-neutral.

- `shared/marketing-advisor/`: the skill, published to every agent home by
  `scripts/publish.mjs`. It contains:
  - `SKILL.md`: method, output schema, calibration numbers and the re-scoring loop;
  - `spec.json`: the rubric and the persona panel;
  - `advisor.py`: two model calls per asset, with the decision computed in code;
  - `rescore.py`: accuracy against real outcomes;
  - `tests/`.
- Brand profiles (owner principles with provenance, fact sheet, calibration
  set, outcomes ledger) stay **outside this repo**, in
  `{{MARKETING_ADVISOR_BRANDS}}`. They hold an owner's verbatim feedback and
  unpublished copy, which is closed-scope. `brands/example.json` shows the shape.
