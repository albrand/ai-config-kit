import { validateScenario } from './scenario-check.mjs';
export function judge(scenarios, results, baseIds = []) {
  const byId = new Map(scenarios.map(s => [s.id, s]));
  // Scenarios present at the merge base remain in regression scope even when
  // a branch deletes them. A deletion is represented as a blocking row.
  for (const id of baseIds) if (!byId.has(id)) byId.set(id, { id, kind: 'automated', surface: 'api', deleted: true });
  return [...byId.values()].map(s => {
    const r = results.find(x => x.scenario_id === s.id);
    let verdict = 'BLOCKED', reason = 'no executed evidence';
    if (s.deleted) { verdict = 'BLOCKED'; reason = 'base scenario removed from head'; }
    else if (s.kind === 'manual' || s.kind === 'awaiting') { const check=validateScenario(s); verdict=check.ok?'NOT_APPLICABLE':'BLOCKED'; reason=check.reason; }
    else if (r?.status === 'passed' && (!baseIds.includes(s.id) || r.executed)) { verdict = 'VERIFIED'; reason = 'executed'; }
    else if (r?.status === 'failed') { verdict = 'FAILED'; reason = 'test failed'; }
    else if (r?.status === 'skipped') { verdict = 'BLOCKED'; reason = 'skipped is not executed'; }
    if (s.surface === 'browser' && r?.executed && !r.screenshot) { verdict = 'BLOCKED'; reason = 'missing screenshot'; }
    if (r?.attachmentFailed) { verdict = 'BLOCKED'; reason = 'evidence attachment failed'; }
    if (r?.missingToken || r?.uploadConfirmed === false) { verdict = 'BLOCKED'; reason = r.missingToken ? 'attachment token missing' : 'upload not confirmed'; }
    return { id:s.id, verdict, reason };
  });
}
export function parseArgs(args) { const out={_:[]}; const booleans=new Set(['apply','dry-run']); for(let i=0;i<args.length;i++){const a=args[i]; if(a.startsWith('--')){const k=a.slice(2);if(booleans.has(k)){out[k]=true;continue;} (out[k]??=[]).push(args[++i]);} else out._.push(a);} return out; }
