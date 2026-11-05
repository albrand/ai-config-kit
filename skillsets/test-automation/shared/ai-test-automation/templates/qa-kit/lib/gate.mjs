import { validateScenario } from './scenario-check.mjs';

export function judge(scenarios, results, baseIds = [], plan = {}) {
  const run = Array.isArray(results) ? null : results;
  results = Array.isArray(results) ? results : (results.results ?? []);
  const byId = new Map(scenarios.map(s => [s.id, s]));
  const scope = new Map();
  for (const item of plan.items ?? []) {
    const relation = item.relation ?? 'linked';
    for (const scenarioId of item.scenarioIds ?? []) scope.set(scenarioId, { workItem: item.id, scope: relation, linkedItems: item.linkedItems ?? [] });
  }
  for (const id of plan.scenarioIds ?? []) if (!scope.has(id)) scope.set(id, { scope: baseIds.includes(id) ? 'regression' : 'linked' });
  for (const id of baseIds) if (!scope.has(id)) scope.set(id, { scope: 'regression' });
  for (const id of scope.keys()) if (!byId.has(id)) byId.set(id, { id, kind: 'automated', surface: 'api', deleted: baseIds.includes(id) });
  for (const id of baseIds) if (!byId.has(id)) byId.set(id, { id, kind: 'automated', surface: 'api', deleted: true });

  return [...byId.values()].map(s => {
    const r = results.find(x => (x.scenario_id ?? x.scenarioId) === s.id);
    const scopeInfo = scope.get(s.id) ?? { scope: baseIds.includes(s.id) ? 'regression' : 'linked' };
    let verdict = 'BLOCKED', reason = 'no executed evidence';
    if (s.deleted) { verdict = 'BLOCKED'; reason = 'base scenario removed from head'; }
    else if (s.kind === 'manual' || s.kind === 'awaiting') { const check = validateScenario(s); verdict = check.ok ? 'NOT_APPLICABLE' : 'BLOCKED'; reason = check.reason; }
    else if (run && (run.compiled !== true || !run.discoveredIds?.includes(s.id))) { verdict = 'BLOCKED'; reason = run.compiled !== true ? 'runner compile evidence missing' : 'scenario was not discovered'; }
    else if (r?.status === 'passed' && r.executed === true) { verdict = 'VERIFIED'; reason = 'executed and passed'; }
    else if (r?.status === 'failed' && r.executed === true) { verdict = 'FAILED'; reason = 'test failed'; }
    else if (r?.status === 'skipped' || r?.executed === false) { verdict = 'BLOCKED'; reason = 'skipped/not-executed result is not evidence'; }
    if (s.surface === 'browser' && r?.executed === true && !r.screenshot && !r.screenshotUrl) { verdict = 'BLOCKED'; reason = 'missing screenshot'; }
    if (r?.attachmentFailed) { verdict = 'BLOCKED'; reason = 'evidence attachment failed'; }
    if (r?.missingToken || r?.uploadConfirmed === false) { verdict = 'BLOCKED'; reason = r.missingToken ? 'attachment token missing' : 'upload not confirmed'; }
    return { id: s.id, workItem: s.workItemId ?? scopeInfo.workItem ?? '', scope: scopeInfo.scope, linkedItems: scopeInfo.linkedItems ?? [], surface: s.surface, executed: Boolean(r?.executed), screenshot: r?.screenshotUrl ?? r?.screenshot ?? '', verdict, reason, blocking: ['FAILED', 'BLOCKED'].includes(verdict) };
  });
}

/** Repeated options accumulate; scalar consumers explicitly select the last value. */
export function parseArgs(args) {
  const out = { _: [] };
  const booleans = new Set(['apply', 'dry-run', 'allow-pending', 'no-network-writes']);
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg.startsWith('--')) {
      const key = arg.slice(2);
      if (booleans.has(key)) { out[key] = true; continue; }
      if (!args[i + 1] || args[i + 1].startsWith('--')) throw new Error(`missing value for --${key}`);
      (out[key] ??= []).push(args[++i]);
    } else out._.push(arg);
  }
  return out;
}
