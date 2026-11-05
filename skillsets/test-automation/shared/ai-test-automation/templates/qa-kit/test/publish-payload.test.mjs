import test from 'node:test';
import assert from 'node:assert/strict';
import { validatePublishPayload } from '../lib/publish-payload.mjs';

const metadata = { kind: 'qa-publish-artifact', schemaVersion: 1, commit: 'a'.repeat(40), runId: 'run-123' };
const verdict = { kind: 'verdict', schemaVersion: 1, planHash: `sha256:${'b'.repeat(64)}`, runHash: `sha256:${'c'.repeat(64)}`, overall: 'PASS', rows: [{ scenarioId: 'QAS-WI-123-01', verdict: 'VERIFIED', reason: 'executed and passed', blocking: false, workItem: 'WI-123', scope: 'linked', surface: 'api', linkedItems: [], screenshot: '' }] };

test('publisher accepts a bounded versioned data artifact', () => assert.deepEqual(validatePublishPayload(metadata, verdict), { ok: true, errors: [] }));
test('publisher rejects unknown schema versions and malformed identifiers', () => {
  const result = validatePublishPayload({ ...metadata, schemaVersion: 9 }, { ...verdict, rows: [{ ...verdict.rows[0], scenarioId: '../../script.mjs' }] });
  assert.equal(result.ok, false);
  assert.match(result.errors.join(' '), /unsupported artifact metadata schema/);
  assert.match(result.errors.join(' '), /invalid scenario id/);
});
test('publisher rejects control characters and unbounded rows', () => {
  const result = validatePublishPayload(metadata, { ...verdict, rows: [{ ...verdict.rows[0], reason: 'bad\u0000text' }, ...Array(10000).fill(verdict.rows[0])] });
  assert.equal(result.ok, false);
  assert.match(result.errors.join(' '), /invalid reason or blocking flag|invalid verdict rows/);
});
test('publisher rejects a PASS summary that hides a failed scenario', () => {
  const result = validatePublishPayload(metadata, { ...verdict, rows: [{ ...verdict.rows[0], verdict: 'FAILED', blocking: true }] });
  assert.equal(result.ok, false);
  assert.match(result.errors.join(' '), /overall verdict does not match scenario rows/);
});
