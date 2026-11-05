import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { buildAssociatedScenarioScope, resolveBoardAssociations } from '../lib/associations.mjs';
import { publishFromEvidence } from '../lib/publish-payload.mjs';
import { jira } from '../lib/boards/jira.mjs';
import { azureBoards } from '../lib/boards/azure-boards.mjs';
import { linear } from '../lib/boards/linear.mjs';
import { github } from '../lib/boards/github.mjs';

const kit = resolve(import.meta.dirname, '..');

test('trusted planner never promotes PR free-text ticket hints without board association', () => {
  const source = readFileSync(resolve(kit, 'bin/qa.mjs'), 'utf8');
  assert.match(source, /linkedItemsForChange\(/, 'planner must obtain work items through the board association API');
  assert.doesNotMatch(source, /searchable\.match\(pattern\)/, 'title/body/branch regex matches are hints only');
});

test('adversarial PR ticket hint is excluded from plan and receives no comment while the linked ticket is planned', async () => {
  const resolved = resolveBoardAssociations(['WI-123', 'WI-999'], [{ id: 'WI-123', title: 'Legitimate linked work' }]);
  assert.deepEqual(resolved.linked.map(item => item.id), ['WI-123']);
  assert.deepEqual(resolved.namedNotLinked, ['WI-999']);

  const scenarioId = 'QAS-WI-123-01';
  const scope = buildAssociatedScenarioScope(resolved.linked, [{ id: scenarioId, workItemId: 'WI-123' }, { id: 'QAS-WI-999-01', workItemId: 'WI-999' }], []);
  assert.deepEqual(scope.items.map(item => item.id), ['WI-123']);
  assert.deepEqual(scope.scenarioIds, [scenarioId]);
  const commit = 'a'.repeat(40);
  const plan = { kind: 'plan', schemaVersion: 1, baseSha: 'b'.repeat(40), headSha: commit, ...scope };
  const planHash = `sha256:${createHash('sha256').update(JSON.stringify(plan)).digest('hex')}`;
  const metadata = { kind: 'qa-publish-artifact', schemaVersion: 1, commit, runId: 'association-test' };
  const scenarios = [{ id: scenarioId, workItemId: 'WI-123', kind: 'automated', surface: 'api' }];
  const run = { kind: 'run', schemaVersion: 1, planHash, commitSha: commit, compiled: true, discoveredIds: [scenarioId], results: [{ scenarioId, status: 'passed', executed: true }] };
  const markerHash = 'f'.repeat(64);
  const maliciousVerdict = { kind: 'verdict', schemaVersion: 1, planHash, runHash: `sha256:${markerHash}`, overall: 'PASS', rows: [{ scenarioId: 'QAS-WI-999-01', workItem: 'WI-999', scope: 'linked', surface: 'api', verdict: 'VERIFIED', reason: 'forged', blocking: false }] };
  const posted = [];
  const adapter = { comment: async (item, body) => { posted.push({ item, body }); return { status: 201 }; } };

  await assert.rejects(() => publishFromEvidence(adapter, { metadata, plan, scenarios, run, candidateVerdict: maliciousVerdict, artifactUrl: 'https://ci.example/run/1' }), /outside trusted plan/);
  assert.deepEqual(posted, [], 'unassociated ticket must not receive a board comment');

  const legitimate = await publishFromEvidence(adapter, { metadata, plan, scenarios, run, artifactUrl: 'https://ci.example/run/1' });
  assert.deepEqual(legitimate.receipts.map(receipt => receipt.workItem), ['WI-123']);
  assert.deepEqual(posted.map(comment => comment.item), ['WI-123']);
});

const response = payload => ({ ok: true, status: 200, headers: new Headers(), text: async () => JSON.stringify(payload) });
const fakeFetch = payload => {
  const calls = [];
  return { calls, fetchImpl: async (url, init) => { calls.push({ url: String(url), ...init }); return response(payload); } };
};

test('GitHub association reads only issues linked by the PR in GraphQL', async () => {
  const fake = fakeFetch({ data: { repository: { pullRequest: { closingIssuesReferences: { nodes: [{ number: 123, title: 'Linked', url: 'https://github.com/acme/api/issues/123' }] } } } } });
  const adapter = github({ baseUrl: 'https://api.github.com', repo: 'acme/api', token: 'test', dryRun: false, fetchImpl: fake.fetchImpl });
  assert.deepEqual(await adapter.linkedItemsForChange({ number: 8 }), [{ id: '123', title: 'Linked', url: 'https://github.com/acme/api/issues/123' }]);
  assert.equal(fake.calls[0].method, 'POST');
  assert.equal(new URL(fake.calls[0].url).pathname, '/graphql');
  assert.match(fake.calls[0].body, /closingIssuesReferences/);
});

test('Azure association reads the PR linked work items endpoint', async () => {
  const fake = fakeFetch({ value: [{ id: 123, url: 'https://dev.azure.com/acme/project/_apis/wit/workItems/123' }] });
  const adapter = azureBoards({ baseUrl: 'https://dev.azure.com/acme/project/', token: 'test', dryRun: false, fetchImpl: fake.fetchImpl });
  assert.deepEqual(await adapter.linkedItemsForChange({ organizationUrl: 'https://dev.azure.com/acme/', project: 'project', repositoryId: 'repo-id', pullRequestId: '8' }), [{ id: '123' }]);
  assert.equal(fake.calls[0].method, 'GET');
  assert.equal(new URL(fake.calls[0].url).pathname, '/acme/project/_apis/git/repositories/repo-id/pullRequests/8/workitems');
});

test('Jira association requires a remote link whose URL matches the canonical PR URL', async () => {
  const calls = [];
  const fake = { calls, fetchImpl: async (url, init) => {
    calls.push({ url: String(url), ...init });
    const linked = String(url).includes('WI-123');
    return response([{ object: { url: linked ? 'https://github.com/acme/api/pull/8' : 'https://github.com/acme/api/pull/77' } }]);
  } };
  const adapter = jira({ baseUrl: 'https://acme.atlassian.net', token: 'test', dryRun: false, fetchImpl: fake.fetchImpl });
  assert.deepEqual(await adapter.linkedItemsForChange({ url: 'https://github.com/acme/api/pull/8', hints: ['WI-123', 'WI-999'] }), [{ id: 'WI-123' }]);
  assert.equal(fake.calls.length, 2);
  assert.ok(fake.calls.every(call => call.method === 'GET' && call.url.includes('/remotelink')));
});

test('Linear association reads issues attached to the exact PR URL', async () => {
  const fake = fakeFetch({ data: { attachmentsForURL: { nodes: [{ issue: { id: 'uuid', identifier: 'WI-123' } }] } } });
  const adapter = linear({ baseUrl: 'https://api.linear.app', token: 'test', dryRun: false, fetchImpl: fake.fetchImpl });
  assert.deepEqual(await adapter.linkedItemsForChange({ url: 'https://github.com/acme/api/pull/8' }), [{ id: 'WI-123' }]);
  assert.equal(new URL(fake.calls[0].url).pathname, '/graphql');
  assert.match(fake.calls[0].body, /attachmentsForURL/);
});
