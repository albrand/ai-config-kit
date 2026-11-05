import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { buildAssociatedScenarioScope, resolveBoardAssociations } from '../lib/associations.mjs';
import { publishFromEvidence } from '../lib/publish-payload.mjs';
import { judge } from '../lib/gate.mjs';
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
  const decoyScenarioId = 'QAS-WI-999-01';
  const scenarios = [
    { id: scenarioId, workItemId: 'WI-123', kind: 'automated', surface: 'api' },
    { id: decoyScenarioId, workItemId: 'WI-999', kind: 'automated', surface: 'api' }
  ];
  const scope = buildAssociatedScenarioScope(resolved.linked, scenarios, []);
  assert.deepEqual(scope.items.map(item => item.id), ['WI-123']);
  assert.ok(scope.scenarioIds.includes(decoyScenarioId), 'the complete suite remains in gate scope');
  const commit = 'a'.repeat(40);
  const plan = { kind: 'plan', schemaVersion: 1, baseSha: 'b'.repeat(40), headSha: commit, ...scope };
  const planHash = `sha256:${createHash('sha256').update(JSON.stringify(plan)).digest('hex')}`;
  const metadata = { kind: 'qa-publish-artifact', schemaVersion: 1, commit, runId: 'association-test' };
  const run = { kind: 'run', schemaVersion: 1, planHash, commitSha: commit, compiled: true, discoveredIds: [scenarioId, decoyScenarioId], results: [
    { scenarioId, status: 'passed', executed: true },
    { scenarioId: decoyScenarioId, status: 'passed', executed: true }
  ] };
  const markerHash = 'f'.repeat(64);
  const maliciousVerdict = { kind: 'verdict', schemaVersion: 1, planHash, runHash: `sha256:${markerHash}`, overall: 'PASS', rows: [{ scenarioId: 'QAS-WI-888-01', workItem: 'WI-888', scope: 'linked', surface: 'api', verdict: 'VERIFIED', reason: 'forged', blocking: false }] };
  const posted = [];
  const adapter = { comment: async (item, body) => { posted.push({ item, body }); return { status: 201 }; } };

  await assert.rejects(() => publishFromEvidence(adapter, { metadata, plan, scenarios, run, candidateVerdict: maliciousVerdict, artifactUrl: 'https://ci.example/run/1' }), /outside trusted plan/);
  assert.deepEqual(posted, [], 'unassociated ticket must not receive a board comment');

  const legitimate = await publishFromEvidence(adapter, { metadata, plan, scenarios, run, artifactUrl: 'https://ci.example/run/1' });
  assert.deepEqual(legitimate.verdict.rows.map(row => row.scenarioId), [scenarioId, decoyScenarioId]);
  assert.deepEqual(legitimate.receipts.map(receipt => receipt.workItem), ['WI-123']);
  assert.deepEqual(posted.map(comment => comment.item), ['WI-123']);
});

test('unrelated base regressions remain in the gate without becoming board write targets', async () => {
  const linked = [{ id: 'WI-123' }];
  const current = [{ id: 'QAS-WI-123-01', workItemId: 'WI-123', kind: 'automated', surface: 'api' }];
  const base = [{ id: 'QAS-WI-999-01', workItemId: 'WI-999', kind: 'automated', surface: 'api' }];
  const scope = buildAssociatedScenarioScope(linked, current, base);
  const plan = { ...scope, kind: 'plan', schemaVersion: 1 };
  assert.deepEqual(scope.items.map(item => item.id), ['WI-123'], 'only associated items are board write targets');
  assert.ok(scope.scenarioIds.includes('QAS-WI-999-01'), 'unrelated base scenario remains in gate scope');
  assert.ok(scope.regressionIds.includes('QAS-WI-999-01'), 'all base scenarios remain regressions');
  const rows = judge([...current, ...base], [
    { scenarioId: 'QAS-WI-123-01', status: 'passed', executed: true },
    { scenarioId: 'QAS-WI-999-01', status: 'passed', executed: true }
  ], scope.regressionIds, plan);
  assert.equal(rows.find(row => row.id === 'QAS-WI-999-01')?.verdict, 'VERIFIED', 'unrelated regression is judged');
  assert.equal(rows.find(row => row.id === 'QAS-WI-999-01')?.scope, 'regression');

  const commit = 'c'.repeat(40);
  const trustedPlan = { ...plan, headSha: commit };
  const planHash = `sha256:${createHash('sha256').update(JSON.stringify(trustedPlan)).digest('hex')}`;
  const adapter = { posted: [], comment: async function(item, body) { this.posted.push({ item, body }); return { status: 201 }; } };
  const publication = await publishFromEvidence(adapter, {
    metadata: { kind: 'qa-publish-artifact', schemaVersion: 1, commit, runId: 'regression-scope' },
    plan: trustedPlan,
    scenarios: [...current, ...base],
    run: { kind: 'run', schemaVersion: 1, planHash, commitSha: commit, compiled: true, discoveredIds: [current[0].id, base[0].id], results: [
      { scenarioId: current[0].id, status: 'passed', executed: true },
      { scenarioId: base[0].id, status: 'passed', executed: true }
    ] },
    artifactUrl: 'https://ci.example/regression'
  });
  assert.ok(publication.verdict.rows.some(row => row.scenarioId === base[0].id && row.scope === 'regression'));
  assert.deepEqual(adapter.posted.map(comment => comment.item), ['WI-123'], 'regression evaluation cannot create an unassociated ticket write target');
});

test('no board links still plan and judge base regressions without any board writes', async () => {
  const planner = readFileSync(resolve(kit, 'bin/qa.mjs'), 'utf8');
  assert.doesNotMatch(planner, /if\s*\(!linked\.length\)\s*throw/, 'empty associations must not abort planning before regressions are included');

  const baseOnly = [{ id: 'QAS-WI-999-01', workItemId: 'WI-999', kind: 'automated', surface: 'api' }];
  for (const association of [
    { linked: [], crossRepo: [{ id: 'otherrepo/service#12' }] },
    { linked: [], crossRepo: [] }
  ]) {
    const scope = buildAssociatedScenarioScope(association.linked, [], baseOnly);
    const plan = { kind: 'plan', schemaVersion: 1, headSha: 'd'.repeat(40), ...scope, crossRepo: association.crossRepo, policyReasons: ['no linked work item'] };
    assert.deepEqual(plan.items, [], 'no associated items means no board write targets');
    assert.deepEqual(plan.scenarioIds, ['QAS-WI-999-01']);
    assert.deepEqual(plan.regressionIds, ['QAS-WI-999-01']);

    const rows = judge(baseOnly, [{ scenarioId: baseOnly[0].id, status: 'passed', executed: true }], plan.regressionIds, plan);
    assert.equal(rows.find(row => row.id === baseOnly[0].id)?.verdict, 'VERIFIED', 'base-only regression is judged');
    assert.equal(rows.find(row => row.id === baseOnly[0].id)?.scope, 'regression');

    const posted = [];
    const adapter = { comment: async (item, body) => { posted.push({ item, body }); return { status: 201 }; } };
    const commit = 'e'.repeat(40);
    const boundPlan = { ...plan, headSha: commit };
    const planHash = `sha256:${createHash('sha256').update(JSON.stringify(boundPlan)).digest('hex')}`;
    const publication = await publishFromEvidence(adapter, {
      metadata: { kind: 'qa-publish-artifact', schemaVersion: 1, commit, runId: 'no-links' },
      plan: boundPlan,
      scenarios: baseOnly,
      run: { kind: 'run', schemaVersion: 1, planHash, commitSha: commit, compiled: true, discoveredIds: [baseOnly[0].id], results: [{ scenarioId: baseOnly[0].id, status: 'passed', executed: true }] },
      artifactUrl: 'https://ci.example/no-links'
    });
    assert.deepEqual(publication.verdict.gateReasons, ['no linked work item']);
    assert.equal(publication.verdict.overall, 'BLOCKED', 'no-link policy remains a gate blocker while regressions are judged');
    assert.ok(publication.verdict.rows.some(row => row.scenarioId === baseOnly[0].id && row.scope === 'regression'));
    assert.deepEqual(posted, [], 'empty write targets never produce a board request');
  }
});

const response = payload => ({ ok: true, status: 200, headers: new Headers(), text: async () => JSON.stringify(payload) });
const fakeFetch = payload => {
  const calls = [];
  return { calls, fetchImpl: async (url, init) => { calls.push({ url: String(url), ...init }); return response(payload); } };
};

test('GitHub association reads only issues linked by the PR in GraphQL', async () => {
  const fake = fakeFetch({ data: { repository: { pullRequest: { closingIssuesReferences: { nodes: [{ number: 123, title: 'Linked', url: 'https://github.com/acme/api/issues/123' }] } } } } });
  const adapter = github({ baseUrl: 'https://api.github.com', repo: 'acme/api', token: 'test', dryRun: false, fetchImpl: fake.fetchImpl });
  assert.deepEqual(await adapter.linkedItemsForChange({ number: 8 }), [{ id: '123', number: '123', repository: 'acme/api', title: 'Linked', url: 'https://github.com/acme/api/issues/123' }]);
  assert.equal(fake.calls[0].method, 'POST');
  assert.equal(new URL(fake.calls[0].url).pathname, '/graphql');
  assert.match(fake.calls[0].body, /closingIssuesReferences/);
});

test('cross-repository closing reference cannot comment on the same-number issue in the configured repository', async () => {
  const calls = [];
  const linkedIssue = { number: 12, title: 'Other repository ticket', url: 'https://github.com/otherrepo/service/issues/12' };
  const fake = { calls, fetchImpl: async (url, init) => {
    const parsed = new URL(url);
    calls.push({ url: String(url), ...init });
    if (parsed.pathname === '/graphql') return response({ data: { repository: { pullRequest: { closingIssuesReferences: { nodes: [linkedIssue] } } } } });
    if (init.method === 'GET') return response([]);
    return response({ id: 1 });
  } };
  const adapter = github({ baseUrl: 'https://api.github.com', repo: 'acme/api', token: 'test', dryRun: false, fetchImpl: fake.fetchImpl });
  const associated = await adapter.linkedItemsForChange({ number: 8, owner: 'acme', repositoryName: 'api' });
  const resolution = resolveBoardAssociations([], associated);
  for (const item of resolution.linked) await adapter.comment(item.id, 'QA report', 'marker');
  const issueComments = calls.filter(call => call.method === 'POST' && /\/issues\/12\/comments$/.test(new URL(call.url).pathname));
  assert.deepEqual(issueComments, [], 'an otherrepo#12 association must not write to acme/api#12');
  assert.deepEqual(resolution.linked, [], 'cross-repository references are not writable plan targets');
  assert.deepEqual(resolution.crossRepo.map(item => item.id), ['otherrepo/service#12']);
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
