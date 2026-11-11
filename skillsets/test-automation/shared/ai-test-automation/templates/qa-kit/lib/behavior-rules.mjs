const IMPLEMENTATION_CITATION = /(?:\bsrc\/|\bhooks?\b|\bprops\b|\bquery param|\brenders?\b|\.tsx?\b|\.cs\b)/i;
const LOOSE_ASSERTION = /\b(any\s+(?:svg|img|icon|element|image)|to\s*be\s*truthy|toBeTruthy|count\s*>\s*0|is\s+defined|exists?\s*$|something\s+like|or\s+similar|may\s+appear)/i;
const MOCK_ENCODES_ANSWER = /\b(?:pre-?filtered|already\s+filtered|(?:mock|msw)\s+returns?\s+(?:only|just|empty|zero)|returning\s+only\s+filtered|fixture\s+(?:returns?|with)\s+(?:only|no\s+)|returns?\s+the\s+correct(?:ly)?\s+filtered|only\s+matching\s+rows?\s+in\s+(?:the\s+)?mock)/i;
const USES_MOCK = /\b(mock|fixture|stub|msw|intercept|fake\s+api)\b/i;

export function citesImplementation(parts) {
  const text = (Array.isArray(parts) ? parts : [parts]).flat().join('\n');
  return IMPLEMENTATION_CITATION.test(text);
}

export function looseExpectation(expected) {
  if (typeof expected !== 'string' || !expected.trim()) return true;
  const lines = expected.split(/\n+/).map(line => line.trim()).filter(Boolean);
  if (!lines.length) return true;
  return lines.some(line => LOOSE_ASSERTION.test(line));
}

export function mockEncodesAnswer(parts) {
  const text = (Array.isArray(parts) ? parts : [parts]).flat().join('\n');
  return MOCK_ENCODES_ANSWER.test(text);
}

export function expectedLines(expected) {
  return (typeof expected === 'string' ? expected : '')
    .split(/\n+/)
    .map(line => line.trim())
    .filter(Boolean);
}

export function validateScenarioDesign(scenario) {
  if (!scenario || typeof scenario !== 'object') return { ok: false, reason: 'scenario object required' };
  const layers = ['e2e', 'api', 'unit', 'component'];
  if (!layers.includes(scenario.layer)) return { ok: false, reason: 'scenario requires layer e2e|api|unit|component' };
  if (!['positive', 'negative'].includes(scenario.polarity)) return { ok: false, reason: 'scenario requires polarity positive|negative' };
  if (typeof scenario.regressionCase !== 'boolean') return { ok: false, reason: 'scenario requires regressionCase boolean' };
  if (scenario.surface === 'browser' && !['e2e', 'component'].includes(scenario.layer)) {
    return { ok: false, reason: 'browser surface requires layer e2e or component' };
  }
  if (scenario.layer === 'e2e' && scenario.surface !== 'browser') return { ok: false, reason: 'layer e2e requires browser surface' };
  if (scenario.layer === 'api' && scenario.surface !== 'api') return { ok: false, reason: 'layer api requires api surface' };
  if (scenario.layer === 'unit' && scenario.surface !== 'api') return { ok: false, reason: 'layer unit requires api surface' };
  if (scenario.layer === 'component' && !['api', 'browser'].includes(scenario.surface)) {
    return { ok: false, reason: 'layer component requires api or browser surface' };
  }
  const userText = [scenario.title, scenario.expected, ...(scenario.steps ?? [])];
  if (citesImplementation(userText)) return { ok: false, reason: 'steps or expected cite implementation, not user behaviour' };
  if (looseExpectation(scenario.expected)) {
    return { ok: false, reason: 'expected must state specific observable outcomes, not loose assertions (any icon, truthy, count > 0)' };
  }
  if (expectedLines(scenario.expected).length === 0) {
    return { ok: false, reason: 'expected must list every outcome line the automation will assert' };
  }
  const stepText = [...(scenario.steps ?? []), scenario.expected].join('\n');
  if (USES_MOCK.test(stepText)) {
    if (mockEncodesAnswer(stepText)) {
      return { ok: false, reason: 'mock or fixture must not encode the answer; return mixed input and let the app under test produce the outcome' };
    }
    if (scenario.mockPolicy !== 'mixed-source') {
      return { ok: false, reason: 'scenarios that use mocks require mockPolicy mixed-source in the scenario record' };
    }
  }
  if (scenario.status === 'bug') {
    if (typeof scenario.bugKey !== 'string' || !scenario.bugKey.trim()) return { ok: false, reason: 'bug status requires bugKey' };
  }
  return { ok: true, reason: 'valid' };
}

export function criteriaCoverageErrors(scenarios, criterionIds) {
  const byCriterion = new Map();
  for (const scenario of scenarios) {
    for (const criterionId of scenario.criterionIds ?? []) {
      if (!criterionIds.has(criterionId)) continue;
      const bucket = byCriterion.get(criterionId) ?? { positive: false, negative: false, regression: false };
      if (scenario.regressionCase === true) bucket.regression = true;
      else if (scenario.polarity === 'positive') bucket.positive = true;
      else if (scenario.polarity === 'negative') bucket.negative = true;
      byCriterion.set(criterionId, bucket);
    }
  }
  const errors = [];
  for (const criterionId of criterionIds) {
    const bucket = byCriterion.get(criterionId) ?? { positive: false, negative: false, regression: false };
    if (!bucket.positive) errors.push({ criterionId, reason: `criterion ${criterionId} lacks a positive scenario` });
    if (!bucket.negative) errors.push({ criterionId, reason: `criterion ${criterionId} lacks a negative scenario` });
    if (!bucket.regression) errors.push({ criterionId, reason: `criterion ${criterionId} lacks a regression-scoped scenario` });
  }
  return errors;
}

export function newScenarioIds(head, base) {
  const baseIds = new Set(base.map(s => s.id));
  return head.filter(s => !baseIds.has(s.id)).map(s => s.id);
}
