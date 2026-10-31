#!/usr/bin/env python3
"""Check known wording contracts offline, not arbitrary paraphrases or behavior."""
from pathlib import Path
import sys

text = ' '.join((Path(__file__).resolve().parents[1] / 'SKILL.md').read_text().split())
delegation = ' '.join((Path(__file__).resolve().parents[2] / 'codex-delegation' / 'SKILL.md').read_text().split())
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
boundary_required = (
    'Carry hard boundaries into delegated execution',
    "parent's exact hard refusal and permission boundaries into both the generated brief and launcher configuration",
    'requested disposable writes fit the existing authority and allowed tools',
    'Preserve the original outcome: report an unattempted requested output as BLOCKED/NOT RUN and an attempted failed output as FAIL, as applicable; continue independent authorized work and never silently substitute reduced output as success',
    'Never widen authority or add a routine approval step',
    'Actual hard safety/authorization refusals—a safety-hook, sandbox, guardian, DLP, access-policy, or provider-policy refusal—are final',
    'do not retry, rephrase, switch tools/routes, delegate around them, or widen authority',
    'Ordinary command usage/format, transport/runtime, and wrong execution-context errors may be diagnosed and corrected within already established authority',
    'An external access/ACL refusal is not such an error',
    'A GitHub collaborator error under one account does not authorize evading repository ACLs or selecting credentials; use an already authenticated owner context only when actual owner rules authorize it',
    'continue only independently authorized work',
    'Keep safety/process FAIL distinct from successful output observations or task API results',
    'does not prove agent behavior or enforce safety',
)
missing_boundary = [clause for clause in boundary_required if clause not in text]
handoff_required = (
    "Carry the parent's exact hard refusal and permission boundaries into the generated brief and launcher configuration",
    'verify requested writes fit the existing authority before launch',
    'Actual hard safety/authorization refusals are final',
    'never retry, rephrase, switch tools/routes, delegate around them, or widen authority',
    'Ordinary command usage/format, transport/runtime, and wrong execution-context errors may be diagnosed and corrected within already established authority',
    'An access/ACL refusal is not such an error: do not evade ACLs or select credentials',
    'Use an already authenticated owner context only when actual owner rules authorize it',
    'Preserve the requested outcome: an unattempted output is BLOCKED/NOT RUN, and an attempted failed output is FAIL; never report reduced output as success',
    'Continue only independently authorized work',
)
owner_pause_required = (
    'architecture, data model, access-widening security',
    'destructive or hard-to-reverse action',
    'validation that contradicts the plan',
)
missing_owner_pause = [clause for clause in owner_pause_required if clause not in delegation]
if missing_owner_pause:
    print('Missing delegate NEEDS-OWNER owner-decision contract: ' + '; '.join(missing_owner_pause), file=sys.stderr)
    raise SystemExit(1)
narrow_needs_owner = 'NEEDS-OWNER: <one question: a login, code or hard-prohibition approval not yet given>'
if narrow_needs_owner in delegation:
    print('Delegate NEEDS-OWNER contract is too narrow.', file=sys.stderr)
    raise SystemExit(1)
missing_handoff = [clause for clause in handoff_required if clause not in delegation]
if missing_boundary or missing_handoff:
    missing = [f'lesson: {clause}' for clause in missing_boundary]
    missing.extend(f'delegation handoff: {clause}' for clause in missing_handoff)
    print('Missing delegated-boundary text contract: ' + '; '.join(missing), file=sys.stderr)
    raise SystemExit(1)

# Counterfactual: restore the original generic step 3 with no boundary clause.
needle = "Carry the parent's exact hard refusal and permission boundaries into the generated brief and launcher configuration"
start_boundary = delegation.find(needle)
end_boundary = delegation.find('4. Keep one writer', start_boundary)
if start_boundary < 0 or end_boundary < 0:
    print('Delegated-boundary omission counterfactual could not isolate the handoff clause.', file=sys.stderr)
    raise SystemExit(1)
omitted_handoff = delegation[:start_boundary] + delegation[end_boundary:]
if any(clause in omitted_handoff for clause in handoff_required):
    print('Original delegated-boundary omission counterfactual was not rejected.', file=sys.stderr)
    raise SystemExit(1)

# This intentionally narrow lexical check catches the known exception form;
# it is not a semantic parser and cannot catch arbitrary paraphrases.
bypass_exception = 'Exception: retry a denied action through another route and widen authority.'
known_bypass = 'retry a denied action through another route and widen authority'

def has_known_bypass(source: str) -> bool:
    return known_bypass in source.lower()

for source_name, source in (('lesson', text), ('handoff', delegation)):
    if has_known_bypass(source):
        print(f'Contradictory delegated-boundary exception text detected in {source_name}.', file=sys.stderr)
        raise SystemExit(1)
    # Same required clauses remain in place; appending the known exception
    # must still be rejected in either relevant source.
    if not has_known_bypass(source + ' ' + bypass_exception):
        print(f'Known bypass counterfactual was not rejected in {source_name}.', file=sys.stderr)
        raise SystemExit(1)

# Reject the former blanket rule even if all other required clauses remain.
unqualified_finality = 'a denial is final'

def has_unqualified_finality(source: str) -> bool:
    return unqualified_finality in source.lower()

for source_name, source in (('lesson', text), ('handoff', delegation)):
    if has_unqualified_finality(source):
        print(f'Unqualified denial-finality wording detected in {source_name}.', file=sys.stderr)
        raise SystemExit(1)
    if not has_unqualified_finality(source + ' A denial is final: never retry or switch tools.'):
        print(f'Unqualified-finality regression counterfactual was not rejected in {source_name}.', file=sys.stderr)
        raise SystemExit(1)

print('Scoped contracts pass; known boundary mutations rejected. Checks are lexical: arbitrary paraphrases and agent behavior are not verified or enforced.')
