#!/usr/bin/env python3
"""Check the installed evidence contract's critical boundaries offline."""
from pathlib import Path
import sys

text = ' '.join((Path(__file__).resolve().parents[1] / 'SKILL.md').read_text().split())
required = ('a verdict per goal', 'full workflow cannot be called complete',
            'never bypass a safety-hook block', 'review-only request',
            'honest partial evidence is useful',
            'only when the actual change processes, attributes, projects, backfills, writes, or requeues stored data',
            'A nominal reader or UI change that triggers a write is data-moving',
            'A pure stored-data reader with no writes, a UI-only change with no writes, and docs/tests-only changes do not require a lane, throughput, drain, count change, deployment takeover, or 30-minute read-back',
            'Use their real outcome, integration, quality, and behavior evidence',
            'relevant document or test evidence for docs/tests-only changes',
            'For data-moving changes, require observed before and 30-minute after counts',
            'deployment takeover',
            'deployment readiness and delivery are separate',
            'trigger processing after deployment and measure its outcome',
            'Tests passed is never evidence of data movement')
forbidden = (
    'Jev (`typed-decisions` section 10) may answer the semantic sub-questions',
    'Record it in the decision ledger (`--point test-verdict`, one record per goal)',
)

def violations(candidate):
    return [clause for clause in forbidden if clause in candidate]

missing = [clause for clause in required if clause not in text]
if missing:
    print('Missing evidence boundary:', ', '.join(missing), file=sys.stderr)
    raise SystemExit(1)
present = violations(text)
if present:
    print('Unrequested local decision obligation:', ', '.join(present), file=sys.stderr)
    raise SystemExit(1)
old_broad = text.replace(
    'requires data-movement evidence only when the actual change',
    'requires data-movement evidence for every stored-data-reader change, even when the actual change',
)
if old_broad == text or not any(clause not in old_broad for clause in required):
    print('Broad reader counterfactual was not rejected.', file=sys.stderr)
    raise SystemExit(1)
old_obligations = text + '\n' + '\n'.join(forbidden)
if not violations(old_obligations):
    print('Old Jev/ledger obligation counterfactual was not rejected.', file=sys.stderr)
    raise SystemExit(1)
print('Per-goal and scoped data-movement text boundaries pass; broad-gate and old Jev/ledger counterfactuals rejected (text only, not agent-behavior evidence).')
