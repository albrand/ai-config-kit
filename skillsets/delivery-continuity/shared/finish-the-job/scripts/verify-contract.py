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
    'After shipping a release whose actual behavior processes, writes, or requeues stored data, trigger that processing, then re-measure the same per-entity table used for the baseline',
    'A job that has not reported completion is a failure to act on now',
    'For these data-moving releases, report deployed and delivered separately until the table moves',
    'Pure readers with no writes, UI changes with no writes, and docs/tests-only changes do not require a processing trigger or baseline read-back',
    'verify their actual outcome as described below',
)
forbidden = (
    'Batch the semantic questions (in-scope work left, given the request and a summary of what changed?) into one Jev call',
    'Record it in the decision ledger (`--point done` with the computed answer)',
)

def violations(candidate):
    return [clause for clause in forbidden if clause in candidate]

missing = [clause for clause in required if clause not in text]
if missing:
    print('Missing delivery boundary:', ', '.join(missing), file=sys.stderr)
    raise SystemExit(1)
present = violations(text)
if present:
    print('Unrequested local decision obligation:', ', '.join(present), file=sys.stderr)
    raise SystemExit(1)
old_broad = text.replace(
    'completed `## Data movement` block only when the actual change',
    'completed `## Data movement` block for any stored-data-reader change, even when it',
)
if old_broad == text or not any(clause not in old_broad for clause in required):
    print('Broad reader counterfactual was not rejected.', file=sys.stderr)
    raise SystemExit(1)

old_intro = text.replace(
    'After shipping a release whose actual behavior processes, writes, or requeues stored data, trigger that processing',
    'After shipping anything that feeds processing, trigger that processing',
)
intro_scope = (
    'After shipping a release whose actual behavior processes, writes, or requeues stored data, trigger that processing',
    'Pure readers with no writes, UI changes with no writes, and docs/tests-only changes do not require a processing trigger or baseline read-back',
)
if old_intro == text or not any(clause not in old_intro for clause in intro_scope):
    print('Old broad introductory counterfactual was not rejected.', file=sys.stderr)
    raise SystemExit(1)
old_obligations = text + '\n' + '\n'.join(forbidden)
if not violations(old_obligations):
    print('Old Jev/ledger obligation counterfactual was not rejected.', file=sys.stderr)
    raise SystemExit(1)
print('Delivery and scoped data-movement text boundaries pass; broad exemption, introductory, and old Jev/ledger counterfactuals rejected (text only, not agent-behavior evidence).')
