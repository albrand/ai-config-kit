import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import * as publisher from '../lib/publish-payload.mjs';
import { judge } from '../lib/gate.mjs';

const id = 'QAS-WI-123-01';
const metadata = { kind: 'qa-publish-artifact', schemaVersion: 1, commit: 'a'.repeat(40), runId: 'run-123' };
const plan = { kind: 'plan', schemaVersion: 1, baseSha: 'b'.repeat(40), headSha: metadata.commit, items: [{ id: 'WI-123', relation: 'linked', scenarioIds: [id], linkedItems: [] }], scenarioIds: [id], regressionIds: [] };
const scenarios = [{ id, workItemId: 'WI-123', kind: 'automated', surface: 'api' }];
const planHash = `sha256:${createHash('sha256').update(JSON.stringify(plan)).digest('hex')}`;
const rawRun = { kind: 'run', schemaVersion: 1, planHash, commitSha: metadata.commit, compiled: true, discoveredIds: [id], results: [{ scenarioId: id, status: 'failed', executed: true }] };
const forgedOutside = { kind: 'verdict', schemaVersion: 1, planHash: `sha256:${'e'.repeat(64)}`, runHash: `sha256:${'f'.repeat(64)}`, overall: 'PASS', rows: [{ scenarioId: 'QAS-WI-999-01', workItem: 'WI-999', scope: 'linked', surface: 'api', verdict: 'VERIFIED', reason: 'forged', blocking: false }] };
const forgedInside = { kind: 'verdict', schemaVersion: 1, planHash: `sha256:${'e'.repeat(64)}`, runHash: `sha256:${'f'.repeat(64)}`, overall: 'PASS', rows: [{ scenarioId: id, workItem: 'WI-123', scope: 'linked', surface: 'api', verdict: 'VERIFIED', reason: 'forged pass', blocking: false }] };

function recordingAdapter() {
  const posted = [];
  return { posted, comment: async (item, body, marker) => { posted.push({ item, body, marker }); return { status: 200 }; } };
}

test('publisher rejects an Allure-tampered verdict for an item outside the trusted plan without posting', async () => {
  assert.equal(typeof publisher.publishFromEvidence, 'function', 'publisher needs a trusted evidence recompute path');
  const adapter = recordingAdapter();
  await assert.rejects(() => publisher.publishFromEvidence(adapter, { metadata, plan, scenarios, run: rawRun, candidateVerdict: forgedOutside, artifactUrl: 'https://ci.example/run/1' }), /outside trusted plan/);
  assert.deepEqual(adapter.posted, []);
});

test('trusted recompute overrides a tampered PASS for an in-plan scenario', async () => {
  assert.equal(judge(scenarios, rawRun, [], plan)[0].verdict, 'FAILED');
  assert.equal(typeof publisher.publishFromEvidence, 'function', 'publisher needs a trusted evidence recompute path');
  const adapter = recordingAdapter();
  const result = await publisher.publishFromEvidence(adapter, { metadata, plan, scenarios, run: rawRun, candidateVerdict: forgedInside, artifactUrl: 'https://ci.example/run/1' });
  assert.equal(result.verdict.rows[0].verdict, 'FAILED');
  assert.equal(result.verdict.overall, 'FAIL');
  assert.match(adapter.posted[0].body, /QAS-WI-123-01: FAILED/);
});

test('publisher posts nothing when runner evidence is bound to another plan or commit', async () => {
  const adapter = recordingAdapter();
  await assert.rejects(() => publisher.publishFromEvidence(adapter, { metadata, plan, scenarios, run: { ...rawRun, planHash: `sha256:${'0'.repeat(64)}` }, artifactUrl: 'https://ci.example/run/1' }), /not bound to the trusted plan/);
  assert.deepEqual(adapter.posted, []);
  await assert.rejects(() => publisher.publishFromEvidence(adapter, { metadata, plan, scenarios, run: { ...rawRun, commitSha: 'c'.repeat(40) }, artifactUrl: 'https://ci.example/run/1' }), /commit does not match the trusted plan/);
  assert.deepEqual(adapter.posted, []);
});
