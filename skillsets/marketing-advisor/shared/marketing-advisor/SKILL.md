---
name: marketing-advisor
description: >
  Use before marketing copy goes in front of the brand owner or the public,
  for a landing hero or section, ad, post, pricing block or email subject for a
  brand that has a profile, especially Brazilian mental-health marketing aimed
  at psychologists and their patients. Returns a typed accept, verify or revise
  decision with pass/fail per criterion (clarity for a cold reader, one idea,
  benefit first, concreteness, reading ease, truthfulness, CFP/CDC/LGPD
  compliance, audience value, owner principles). It is calibrated against the
  owner's past verdicts, not their live taste. Also use it to log outcomes
  (owner approvals, landing A/B winners, ad CTR) and to re-score the advisor.
verify: 'python3 "$HOME/.agents/skills/marketing-advisor/advisor.py" --selftest && python3 "$HOME/.agents/skills/marketing-advisor/tests/rescore_test.py"'
verified: 2026-09-24
---

# Marketing advisor

This is a judge for one asset at a time. It replaces "ask the owner to rank a
blind sheet" with a rubric scored against evidence: the owner's recorded
accept and reject decisions. Its accuracy is re-measured as real outcomes
arrive. It advises only. It never publishes, sends or posts anything, and the
owner still approves what ships.

## Call it

```bash
python3 ~/.agents/skills/marketing-advisor/advisor.py \
  --text-file hero.txt --type copy --audience patient --surface "landing hero" \
  --brand {{MARKETING_ADVISOR_BRANDS}}/<brand>.json \
  --id <stable-asset-id> --log {{MARKETING_ADVISOR_BRANDS}}/<brand>-outcomes.jsonl
```

- The defaults are the calibrated configuration in `spec.json` → `calibrated`: judge `opus` (Claude Opus via `claude -p`, tools off), `w = 0`, and one model call per asset (about $0.06).
- `--panel` adds the persona panel's reasons, one more call. It carries zero weight; see the calibration below.
- `--judge sonnet|haiku|gpt|gemini` and `--w` exist for experiments. The output then says `"calibrated": false`.
- The exit code is 0 on accept, 3 on verify or revise, and 1 on error.
- A brand profile holds `principles` (the owner's recorded reasons, each with the feedback `events` it came from) and a `facts_file`, the only allowed source of product facts.
- Profiles live outside this repo in `{{MARKETING_ADVISOR_BRANDS}}`, because they hold an owner's verbatim feedback and unpublished copy. `brands/example.json` shows the shape. A profile with no principles runs the generic rubric only, which is uncalibrated.

## What it judges

The rubric is in `spec.json`. Each criterion is typed pass, fail or `na`; `na` is used only where the criterion cannot apply, such as reading level for a one-word name.

| id | criterion | critical |
|---|---|---|
| R1 | cold_clarity: a first-time visitor understands it without knowing the product's internal names | yes |
| R2 | one_idea: one idea per headline, and the body supports it | |
| R3 | benefit_first: feeling or outcome before mechanics or interface gestures | yes |
| R4 | concreteness: concrete nouns, no floating pronouns | |
| R5 | reading_ease: plain, short, scannable, and a length that fits the surface | |
| R6 | truthful: nothing beyond the fact sheet, no promised results, never implies the paid professional fails, no self-contradiction | yes |
| R7 | compliance: CFP Res. 010/2005 art. 20, CFP NT 1/2022, CDC art. 37, LGPD art. 11 | gate |
| R8 | audience_value: for professionals, value a competent clinician couldn't get alone; for patients, a real felt need | |
| F* | the brand's owner principles, each pass or fail | |

**Panel.** Four synthetic Brazilian psychologists, the buyer, each vote `would_click` and `would_sign_up` with a reason:
- P1, early-career, needs patients;
- P2, established psychoanalyst, distrusts platforms;
- P3, supervisor, skeptical of AI, reads for CFP and LGPD issues;
- P4, leaving a commission platform.

## Output (typed; `schema.json`)

`{asset_id, judge, criteria[{id, pass, evidence}], founder_principles[{id, pass}], compliance{pass, violations[{rule, excerpt}]}, panel[{persona, would_click, would_sign_up, reason}], scores{rubric, panel, combined, w, threshold, ranking}, decision, calibrated, decision_preregistered, failed_criteria[]}`

The decision is computed in code, never by the model:

1. `combined = (1 − w)·rubric + w·panel`. Here `rubric` is the passes divided by the applicable criteria plus principles.
2. `revise` if `combined < threshold` (0.571).
3. Otherwise `verify` if R6 or R7 fails or any compliance violation is listed. Verify means: confirm the flagged claims with the owner, or remove them, before publishing.
4. Otherwise `accept`.

**Expect `verify`, not `accept`, until the fact sheet is complete.** In calibration, every copy item that cleared the threshold was flagged on claims the fact sheet did not contain. A flag on an unconfirmed claim is the correct outcome, not noise to suppress. Add a fact to the fact sheet only when the owner confirms it is true.

## Calibration (2026-09-24)

Setup:
- **Labelled set:** 28 past owner verdicts (7 names, 21 pieces of landing copy; 8 accepts). Only 16 have high or medium label confidence, which is fewer than 20.
- **Blinding:** labels were hidden from the judges.
- **Leave-one-out:** owner principles derived from an item's own feedback event were dropped when that item was judged.
- **Judges:** Claude Opus 5.5, Claude Sonnet 5, GPT-5.6 Sol and Gemini 3.7 Flash.
- **Panel weights:** w ∈ {0, 0.3, 0.5, 1}.

Results:
- **Pre-registered rule (hard R6/R7 gate, cut 0.75): no configuration beat chance.**
  - Best κ +0.29 against a best-of-18 permutation null with a 95th percentile of +0.43 (p = 0.29).
  - Cause: the truth and compliance gate failed 5 of the 6 accepted copy items, on facts missing from the fact sheet.
- **Chosen rule (above; Opus, w = 0, threshold learned).** Figures are accuracy / κ, estimated by nested leave-one-out:

| subset | n (accepts) | nested LOO | best-of-16 null κ95 (p) | AUC | retest: same threshold, 2nd run |
|---|---|---|---|---|---|
| copy | 21 (6) | 0.90 / +0.77 | +0.59 (p = 0.006) | 0.89 | 0.86 / +0.63, AUC 0.83 |
| all incl. names | 28 (8) | 0.82 / +0.61 | +0.51 (p = 0.007) | 0.79 | 0.75 / +0.45, AUC 0.72 |

Other findings:
- Always-reject scores 0.71 accuracy (κ 0) on both subsets.
- **Run-to-run stability:** the taste decision agreed 86% between two runs (κ +0.70).
- **Other judges:**
  - Best nested κ on copy, over the four weights: Sonnet +0.53 (w=0.3), Gemini +0.42 (w=0.3), GPT +0.22.
  - The eval-style "would the owner accept this?" prompt: GPT κ +0.42 and Gemini +0.35 on copy, AUC 0.62 and 0.76.
- **The persona panel alone ran at chance** (AUC 0.50–0.62).
  - At w=0.3 it helped the weaker judges (Sonnet +0.22 → +0.53; Gemini +0.35 → +0.42).
  - It lowered Opus (+0.77 → +0.63), so for the chosen judge its weight is 0.
- **Names are not calibrated.** The judge scored the names the owner rejected as high as the one chosen. Use the advisor on names only to catch hard defects, never to pick one.
- **Honest expectation for copy:** κ about 0.6–0.75, roughly 85% accuracy, against 71% for always-reject.
- **Why these numbers are optimistic:**
  - the rule and scope were chosen after the pre-registered design failed (the nulls correct for choosing among 16 configurations, not for that pivot);
  - the rubric was drafted after reading the owner's reasons;
  - 5 of 6 accepted copy labels are implicit;
  - the chosen judge shares a model family with the writer of most items (self-preference risk).
- **Threshold sensitivity:** calibration scored against fewer principles per item than production runs, so production is stricter by up to one criterion. The rubric's two example phrases were made generic after calibration.
- The raw runs, per-configuration table and labelled set are in the brand directory: `{{MARKETING_ADVISOR_BRANDS}}/<brand>-calibration.md`.

## Keep it honest: re-score against real outcomes

The calibration set is small. Every real outcome is a new label, so log them to
the same JSONL ledger `--log` writes to, joined on `asset_id`:

```json
{"kind":"outcome","asset_id":"hero-v3","date":"2026-10-02","source":"owner","value":"accept"}
{"kind":"outcome","asset_id":"hero-v3","date":"2026-10-20","source":"ab","test_id":"lp-hero-oct","winner":true,"significant":true}
{"kind":"outcome","asset_id":"ad-17","date":"2026-10-21","source":"ctr","campaign_id":"meta-oct","impressions":4200,"clicks":61}
```

- **Owner approvals** (the pilot): every accept, reject or "redo" the owner gives on an asset the advisor scored. Record the verdict, and add the owner's reason as a candidate principle, with its event, in the brand profile.
- **Landing A/B:** log each variant with `winner` and `significant` once the test concludes. Log only tests with a significant winner.
- **Ad CTR:** log impressions and clicks per creative, per campaign. Only rows with at least 1,000 impressions count.

Run it weekly, and whenever outcomes land:

```bash
python3 ~/.agents/skills/marketing-advisor/rescore.py {{MARKETING_ADVISOR_BRANDS}}/<brand>-outcomes.jsonl \
  --calibrated-kappa 0.63 --since 2026-09-24
```

It reports:
- owner agreement: accuracy, κ, κ over the last 20, and always-reject accuracy;
- the A/B winner-ranked-first rate;
- CTR pairwise concordance within campaigns.

It prints `RECALIBRATE:` and exits 2 when any trigger fires:
- ≥ 10 owner labels since the calibration date;
- owner κ over the last 20 (with at least 10) falls more than 0.2 below the calibrated κ;
- A/B winner ranked first in ≤ 50% of ≥ 5 tests;
- CTR concordance ≤ 50% over ≥ 20 pairs.

**Recalibrate:**
1. Append the new owner labels to the brand's labelled set, with confidence.
2. Re-run the calibration harness kept with the brand profile, with labels hidden and event-level leave-one-out.
3. Update `spec.json` → `calibrated` (judge, w, threshold, date) and the table above.
4. Republish. If no configuration beats its permutation null, say so here and stop using the advisor as a gate.

## Typed decisions here

The decision space is pick-one: `accept | verify | revise`. The answer comes from code over typed pass/fail criteria, never from the model's own verdict.
- **Confidence** comes only from the measured agreement above and from the outcome ledger, never from the judge's self-report.
- **`calibrated: false`** (a name, another judge or another weight) is medium confidence at most. Treat it as advice for the owner, not a gate.
- **Verify is not approval.** A human confirms the flagged claims.
- **Record the decision** in the decision ledger (`--point marketing-verdict`, `--ref <brand>:<asset_id>`). Resolve it when the owner's verdict or the test result arrives.
