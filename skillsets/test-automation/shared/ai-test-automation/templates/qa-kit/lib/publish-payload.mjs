import { createHash } from 'node:crypto';
import { judge } from './gate.mjs';
import { reportMarker } from './report.mjs';

const hash = value => typeof value === 'string' && /^sha256:[a-f0-9]{64}$/.test(value);
const text = (value, max = 500) => typeof value === 'string' && value.length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value);
const digest = value => `sha256:${createHash('sha256').update(JSON.stringify(value)).digest('hex')}`;
const planPairs = plan => {
  const pairs = new Set();
  for (const item of plan?.items ?? []) {
    if (!text(String(item.id ?? ''), 160)) continue;
    for (const id of item.scenarioIds ?? []) pairs.add(`${id}\u0000${item.id}`);
  }
  return pairs;
};

function scopeErrors(verdict, plan) {
  const pairs = planPairs(plan);
  const errors = [];
  for (const [index, row] of (verdict?.rows ?? []).entries()) {
    if (!pairs.has(`${row.scenarioId}\u0000${row.workItem}`)) errors.push(`row ${index} is outside trusted plan`);
  }
  return errors;
}

/** Recompute a verdict in trusted code from a trusted plan and untrusted runner data. */
export function recomputeTrustedVerdict(plan, scenarios, run) {
  if (!plan || plan.kind !== 'plan' || plan.schemaVersion !== 1 || !/^[a-f0-9]{40}$/.test(plan.headSha ?? '')) throw new Error('trusted plan schema or head commit is invalid');
  if (!run || run.kind !== 'run' || run.schemaVersion !== 1) throw new Error('runner evidence schema is invalid');
  const planHash = digest(plan);
  if (run.planHash !== planHash) throw new Error('runner evidence is not bound to the trusted plan');
  if (run.commitSha !== plan.headSha) throw new Error('runner evidence commit does not match the trusted plan');
  const pairs = planPairs(plan);
  const allowedById = new Set([...pairs].map(pair => pair.split('\u0000')[0]));
  const scoped = (scenarios ?? []).filter(scenario => allowedById.has(scenario.id));
  const rows = judge(scoped, run, plan.regressionIds ?? [], plan).map(({ id, ...row }) => ({ scenarioId: id, ...row }));
  const overall = rows.some(row => row.verdict === 'FAILED') ? 'FAIL' : rows.some(row => row.verdict === 'BLOCKED') ? 'BLOCKED' : 'PASS';
  return { kind: 'verdict', schemaVersion: 1, planHash, runHash: digest(run), commitSha: plan.headSha, overall, rows };
}

/** Validate a publisher payload against trusted plan membership and trusted run identity. */
export function validatePublishPayload(metadata, verdict, plan, expected = {}) {
  const errors = [];
  if (!metadata || metadata.kind !== 'qa-publish-artifact' || metadata.schemaVersion !== 1) errors.push('unsupported artifact metadata schema');
  if (!metadata || !/^[a-f0-9]{40}$/.test(metadata.commit ?? '') || !text(metadata.runId, 120)) errors.push('invalid artifact identity');
  if (expected.commit && metadata?.commit !== expected.commit) errors.push('artifact commit does not match trusted workflow metadata');
  if (expected.runId && metadata?.runId !== String(expected.runId)) errors.push('artifact run id does not match trusted workflow metadata');
  if (!plan || plan.kind !== 'plan' || plan.schemaVersion !== 1) errors.push('unsupported trusted plan schema');
  if (metadata?.commit !== plan?.headSha) errors.push('artifact commit does not match trusted plan head');
  if (!verdict || verdict.kind !== 'verdict' || verdict.schemaVersion !== 1) errors.push('unsupported verdict schema');
  if (!verdict || !hash(verdict.planHash) || !plan || verdict.planHash !== digest(plan)) errors.push('verdict plan hash does not match trusted plan');
  if (!verdict || !hash(verdict.runHash) || verdict.commitSha !== plan?.headSha) errors.push('verdict run identity does not match trusted plan');
  if (!verdict || !['PASS', 'FAIL', 'BLOCKED'].includes(verdict.overall)) errors.push('invalid overall verdict');
  if (!verdict || !Array.isArray(verdict.rows) || verdict.rows.length === 0 || verdict.rows.length > 10000) errors.push('invalid verdict rows');
  for (const [index, row] of (verdict?.rows ?? []).entries()) {
    if (!text(row.scenarioId, 160) || !/^QAS-[A-Za-z0-9_-]+$/.test(row.scenarioId ?? '')) errors.push(`row ${index}: invalid scenario id`);
    if (!['VERIFIED', 'FAILED', 'BLOCKED', 'NOT_APPLICABLE'].includes(row.verdict)) errors.push(`row ${index}: invalid verdict`);
    if (!text(row.reason, 1000) || typeof row.blocking !== 'boolean') errors.push(`row ${index}: invalid reason or blocking flag`);
    if (!text(row.workItem ?? '', 160) || !text(row.scope ?? '', 40) || !text(row.surface ?? '', 20)) errors.push(`row ${index}: invalid scope fields`);
    if (row.screenshot && !text(row.screenshot, 2000)) errors.push(`row ${index}: invalid screenshot reference`);
    if (Array.isArray(row.linkedItems) && (row.linkedItems.length > 100 || row.linkedItems.some(item => !text(item, 160)))) errors.push(`row ${index}: invalid linked items`);
  }
  errors.push(...scopeErrors(verdict, plan));
  const rows = verdict?.rows ?? [];
  const hasFailure = rows.some(row => row.verdict === 'FAILED');
  const hasBlock = rows.some(row => row.verdict === 'BLOCKED');
  const expectedOverall = hasFailure ? 'FAIL' : hasBlock ? 'BLOCKED' : 'PASS';
  if (verdict?.overall !== expectedOverall) errors.push('overall verdict does not match scenario rows');
  return { ok: errors.length === 0, errors };
}

/** The publisher ignores an in-plan candidate verdict and posts its trusted recomputation. */
export async function publishFromEvidence(adapter, { metadata, plan, scenarios, run, candidateVerdict, artifactUrl, expectedCommit, expectedRunId }) {
  const verdict = recomputeTrustedVerdict(plan, scenarios, run);
  const valid = validatePublishPayload(metadata, verdict, plan, { commit: expectedCommit, runId: expectedRunId });
  if (!valid.ok) throw new Error(`refusing to publish evidence: ${valid.errors.join('; ')}`);
  if (candidateVerdict) {
    const outside = scopeErrors(candidateVerdict, plan);
    if (outside.length) throw new Error(`refusing verdict candidate outside trusted plan: ${outside.join('; ')}`);
  }
  if (!text(artifactUrl, 2000) || !/^https:\/\//.test(artifactUrl)) throw new Error('publisher requires a trusted HTTPS artifact URL');
  const grouped = new Map();
  for (const row of verdict.rows) grouped.set(row.workItem, [...(grouped.get(row.workItem) ?? []), row]);
  if (!grouped.size) throw new Error('trusted verdict has no planned work items to report');
  const receipts = [];
  for (const [item, rows] of grouped) {
    const body = `QA verdict ${verdict.overall} for ${metadata.commit}\nArtifact: ${artifactUrl}\n\n${rows.map(row => `${row.scenarioId}: ${row.verdict} — ${row.reason}`).join('\n')}`;
    const marker = reportMarker(item, metadata.commit, body);
    const result = await adapter.comment(item, body, marker);
    receipts.push({ workItem: item, marker, status: result.status, duplicate: Boolean(result.duplicate), confirmed: Boolean(result.duplicate || (result.status >= 200 && result.status < 300)) });
  }
  return { verdict, receipts };
}
