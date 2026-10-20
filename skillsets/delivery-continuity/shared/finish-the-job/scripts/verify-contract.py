#!/usr/bin/env python3
"""Check the installed delivery contract's critical boundaries offline."""
from pathlib import Path
import sys

text = ' '.join((Path(__file__).resolve().parents[1] / 'SKILL.md').read_text().split())
required = (
    'Reuse authorization already given',
    'continue useful independent authorized work',
    'never bypass it or route around',
    'Already-running sessions may cache old directives',
    'a failed goal stays FAIL',
    'completed `## Data movement` block only when the actual change processes, attributes, projects, backfills, writes, or requeues stored data',
    'A nominal reader or UI change that triggers a write is data-moving',
    'A pure stored-data reader with no writes, a UI-only change with no writes, and docs/tests-only changes do not require a lane, throughput, drain, count change, deployment takeover, or 30-minute read-back',
    'use their real outcome, integration, quality, and behavior evidence',
    'relevant document or test evidence for docs/tests-only changes',
    '30-minute after counts-only read-back',
    'release verdict FAIL',
    'Tests passed is never data-movement evidence',
    'Deployment readiness and delivery are separate',
    'trigger the processing after deployment',
)
missing = [clause for clause in required if clause not in text]
if missing:
    print('Missing delivery boundary:', ', '.join(missing), file=sys.stderr)
    raise SystemExit(1)
old_broad = text.replace(
    'completed `## Data movement` block only when the actual change',
    'completed `## Data movement` block for any stored-data-reader change, even when it',
)
if old_broad == text or not any(clause not in old_broad for clause in required):
    print('Broad reader counterfactual was not rejected.', file=sys.stderr)
    raise SystemExit(1)
print('Delivery boundaries and scoped data-movement evidence pass; broad-gate counterfactual rejected (text only, not agent-behavior evidence).')
