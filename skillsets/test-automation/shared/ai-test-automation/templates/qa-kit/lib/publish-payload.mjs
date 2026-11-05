const hash = value => typeof value === 'string' && /^sha256:[a-f0-9]{64}$/.test(value);
const text = (value, max = 500) => typeof value === 'string' && value.length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value);

/** Validate untrusted workflow artifacts before a trusted publisher uses them. */
export function validatePublishPayload(metadata, verdict) {
  const errors = [];
  if (!metadata || metadata.kind !== 'qa-publish-artifact' || metadata.schemaVersion !== 1) errors.push('unsupported artifact metadata schema');
  if (!metadata || !/^[a-f0-9]{40}$/.test(metadata.commit ?? '') || !text(metadata.runId, 120)) errors.push('invalid artifact identity');
  if (!verdict || verdict.kind !== 'verdict' || verdict.schemaVersion !== 1) errors.push('unsupported verdict schema');
  if (!verdict || !hash(verdict.planHash) || !hash(verdict.runHash)) errors.push('invalid verdict hashes');
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
  const rows = verdict?.rows ?? [];
  const hasFailure = rows.some(row => row.verdict === 'FAILED');
  const hasBlock = rows.some(row => row.verdict === 'BLOCKED');
  const expectedOverall = hasFailure ? 'FAIL' : hasBlock ? 'BLOCKED' : 'PASS';
  if (verdict?.overall !== expectedOverall) errors.push('overall verdict does not match scenario rows');
  return { ok: errors.length === 0, errors };
}
