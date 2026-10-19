#!/usr/bin/env python3
"""Check the orchestrator's data-movement release gate offline."""
from pathlib import Path
import sys

text = ' '.join((Path(__file__).resolve().parents[1] / 'SKILL.md').read_text().split())
required = (
    'Gate every data movement change at plan and integration',
    '## Data movement',
    'Kind: data-moving | reader-only | UI-only | docs/tests-only',
    'Existing records affected (production, counts only)',
    'Lane and cadence:',
    'Per-run throughput:',
    'Time-budget check:',
    'Predicted drain:',
    'Counts-only read-back query:',
    'Expected after-value:',
    'Deployment-takeover check:',
    'COORDINATOR TO MEASURE',
    'screen read that proves the change is visible',
    'report the observed before and 30-minute after counts',
    'Tests passed is never evidence of data movement',
    '30 minutes after deployment is Ready',
    'release verdict stays FAIL',
)
missing = [clause for clause in required if clause not in text]
if missing:
    print('Missing data-movement gate clause:', ', '.join(missing), file=sys.stderr)
    raise SystemExit(1)
print('Orchestration data-movement release gate present.')
