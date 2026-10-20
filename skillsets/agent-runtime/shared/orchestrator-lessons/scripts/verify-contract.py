#!/usr/bin/env python3
"""Check the orchestrator's scoped data-movement text contract offline."""
from pathlib import Path
import sys

text = ' '.join((Path(__file__).resolve().parents[1] / 'SKILL.md').read_text().split())
required = (
    'Gate data movement at plan and integration',
    'A change is data-moving when it processes, attributes, projects, backfills, writes, or requeues stored data',
    'A nominal reader or UI change that triggers such a write is data-moving',
    'A pure stored-data reader with no writes, a UI-only change with no writes, and docs/tests-only changes do not move stored data',
    'do not require them to invent a lane, throughput, drain, count change, takeover, or 30-minute read-back',
    'Use the real outcome, integration, quality, and behavior evidence',
    'UI changes use a screen read when that is the changed outcome',
    'docs/tests-only changes use their relevant document or test evidence',
    'Only for a change whose actual behavior moves stored data',
    '## Data movement',
    'Kind: data-moving | reader-only | UI-only | docs/tests-only; classify by actual writes/requeues, not the label',
    'Existing records affected (production, counts only)',
    'Lane and cadence:',
    'Per-run throughput:',
    'Time-budget check:',
    'Predicted drain:',
    'Counts-only read-back query:',
    'Expected after-value:',
    'Deployment-takeover check:',
    'COORDINATOR TO MEASURE',
    'For data-moving cards, complete every field above',
    'report the observed before and 30-minute after counts',
    'Tests passed is never evidence of data movement',
    '30 minutes after deployment is Ready',
    'release verdict stays FAIL',
    'Deployment readiness and delivery are separate',
    'trigger the processing after deployment',
    "## A data-moving release is done when the user's data moved, not merely when the release is Ready",
    'for releases whose actual behavior processes, writes, or requeues stored data, trigger the processing the change depends on',
    'measure the user-facing outcome (per customer or per entity, the same table as the baseline) within 30 minutes',
    'A job that has not reported completion is a FAIL to act on now, not "pending"',
    'Until that table moves, the data-moving release is deployed, not delivered',
    'Pure readers and UI changes with no writes, and docs/tests-only releases, do not require processing or a 30-minute baseline read-back',
    'use their actual outcome evidence',
)
missing = [clause for clause in required if clause not in text]
if missing:
    print('Missing data-movement gate clause:', ', '.join(missing), file=sys.stderr)
    raise SystemExit(1)

old_broad = text.replace(
    'Only for a change whose actual behavior moves stored data, require this',
    'For every stored-data reader and UI change, require this',
)
if old_broad == text or not any(clause not in old_broad for clause in required):
    print('Broad reader/UI counterfactual was not rejected.', file=sys.stderr)
    raise SystemExit(1)

old_incident = text.replace(
    "## A data-moving release is done when the user's data moved, not merely when the release is Ready",
    "## Done means the user's data moved, not that the release is Ready",
).replace(
    'for releases whose actual behavior processes, writes, or requeues stored data, trigger the processing the change depends on, then measure the user-facing outcome',
    'after every release, trigger the processing it depends on, then measure the user-facing outcome',
)
incident_scope = (
    "## A data-moving release is done when the user's data moved, not merely when the release is Ready",
    'for releases whose actual behavior processes, writes, or requeues stored data, trigger the processing the change depends on',
    'Pure readers and UI changes with no writes, and docs/tests-only releases, do not require processing or a 30-minute baseline read-back',
)
if old_incident == text or not any(clause not in old_incident for clause in incident_scope):
    print('Old broad incident counterfactual was not rejected.', file=sys.stderr)
    raise SystemExit(1)
print('Scoped reader/docs/UI, data-moving, and incident text contracts pass; both broad-gate counterfactuals rejected (text only, not agent-behavior evidence).')
