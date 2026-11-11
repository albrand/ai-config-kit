import test from 'node:test';
import assert from 'node:assert/strict';
import { citesImplementation, criteriaCoverageErrors, validateScenarioDesign } from '../lib/behavior-rules.mjs';
import { scenarioCheck } from '../lib/scenario-check.mjs';
import { judge } from '../lib/gate.mjs';

const baseScenario = {
  id: 'QAS-WI-1-01',
  criterionIds: ['AC-alpha'],
  kind: 'automated',
  surface: 'api',
  layer: 'api',
  polarity: 'positive',
  regressionCase: false,
  mandatory: true,
  title: 'Happy path',
  steps: ['Call the public API with valid input'],
  expected: 'The service returns the created record',
};

function triplet(workItem, criterion) {
  const root = `QAS-${workItem}`;
  return [
    { ...baseScenario, id: `${root}-01`, criterionIds: [criterion], polarity: 'positive', regressionCase: false },
    { ...baseScenario, id: `${root}-02`, criterionIds: [criterion], polarity: 'negative', regressionCase: false, title: 'Invalid input rejected', expected: 'The user sees a clear rejection without a second record' },
    { ...baseScenario, id: `${root}-03`, criterionIds: [criterion], polarity: 'positive', regressionCase: true, title: 'Regression guard', expected: 'Previously shipped behaviour still holds' },
  ];
}

const runEvidence = ids => ({
  compiled: true,
  discoveredIds: ids,
  results: ids.map(scenarioId => ({ scenarioId, status: 'passed', executed: true })),
});

test('rejects steps or expected that cite implementation instead of user behaviour', () => {
  const bad = { ...baseScenario, steps: ['Open src/pages/Home.tsx and check the hook'] };
  assert.equal(validateScenarioDesign(bad).ok, false);
  assert.match(validateScenarioDesign(bad).reason, /implementation/i);
  assert.equal(citesImplementation('query param foo'), true);
});

test('rejects a criterion with only one polarity', () => {
  const head = [baseScenario];
  const rows = scenarioCheck(head, [], runEvidence([baseScenario.id]));
  assert.ok(rows.some(row => !row.ok && /negative scenario/.test(row.reason)));
});

test('rejects a criterion without a regression-scoped case', () => {
  const head = [
    baseScenario,
    { ...baseScenario, id: 'QAS-WI-1-02', polarity: 'negative', regressionCase: false },
  ];
  const rows = scenarioCheck(head, [], runEvidence(['QAS-WI-1-01', 'QAS-WI-1-02']));
  assert.ok(rows.some(row => !row.ok && /regression-scoped/.test(row.reason)));
});

test('rejects loose expected lines and mocks that encode the answer', () => {
  const loose = { ...baseScenario, expected: 'An icon or any svg is visible' };
  assert.match(validateScenarioDesign(loose).reason, /specific observable/i);
  const biasedMock = {
    ...baseScenario,
    layer: 'component',
    surface: 'browser',
    steps: ['Mount list with MSW returning only filtered rows'],
    expected: 'The pending table shows exactly two rows',
    mockPolicy: 'mixed-source',
  };
  assert.match(validateScenarioDesign(biasedMock).reason, /encode the answer/i);
  const fairMock = {
    ...biasedMock,
    steps: ['Mount list with MSW returning mixed approved and pending rows'],
  };
  assert.equal(validateScenarioDesign(fairMock).ok, true);
});

test('blocks a new scenario that passed on the merge base', () => {
  const id = 'QAS-WI-9-99';
  const scenario = { ...baseScenario, id, criterionIds: ['AC-new'] };
  const head = [...triplet('WI-9', 'AC-new'), scenario];
  const plan = { items: [{ id: 'WI-9', scenarioIds: head.map(s => s.id) }] };
  const rows = judge(head, runEvidence(head.map(s => s.id)), [], plan, {
    baseScenarios: [],
    baseResults: { results: [{ scenarioId: id, status: 'passed', executed: true }] },
  });
  const row = rows.find(r => r.id === id);
  assert.equal(row.verdict, 'BLOCKED');
  assert.equal(row.reason, 'passes without the change');
});

test('bug status stays red and blocks only its own ticket PR', () => {
  const id = 'QAS-WI-7-10';
  const scenario = {
    ...baseScenario,
    id,
    workItemId: 'WI-7',
    status: 'bug',
    bugKey: 'WI-701',
    layer: 'e2e',
    surface: 'browser',
  };
  const results = [{ scenarioId: id, status: 'failed', executed: true, screenshot: 'shot.png' }];
  const linked = judge([scenario], results, [], { items: [{ id: 'WI-7', scenarioIds: [id] }] });
  const unrelated = judge([scenario], results, [], { items: [{ id: 'WI-8', scenarioIds: ['QAS-WI-8-01'] }] });
  assert.equal(linked[0].verdict, 'BUG');
  assert.equal(linked[0].blocking, true);
  assert.equal(unrelated[0].verdict, 'BUG');
  assert.equal(unrelated[0].blocking, false);
});

test('criteriaCoverageErrors lists every missing polarity or regression bucket', () => {
  const errors = criteriaCoverageErrors([baseScenario], new Set(['AC-alpha']));
  assert.deepEqual(errors.map(e => e.reason), [
    'criterion AC-alpha lacks a negative scenario',
    'criterion AC-alpha lacks a regression-scoped scenario',
  ]);
});
