import { judge as realJudge } from './gate.mjs';
import { sourcePrecheck as realSourcePrecheck } from './scenario-check.mjs';
import { scenarioIdsInBoundTestFile as realBoundIds } from './bound-tests.mjs';

// Gate canaries: known-bad inputs the gate must still reject, plus positive controls it must still accept.
// `judge` and `check-scenarios` run them first, so a refactor that silently stops a check from firing makes the
// gate refuse to run (SANITY_CANARY_FAILED) instead of passing bad runs. Gate functions are injectable so a
// test can prove the canaries notice a broken gate.
const ID = 'QAS-CANARY-01';
const scenario = (extra = {}) => ({ id: ID, kind: 'automated', surface: 'api', ...extra });
const result = (extra = {}) => ({ scenario_id: ID, status: 'passed', executed: true, ...extra });
const hidden = (...parts) => parts.join('');

export function runCanaries({ judge = realJudge, sourcePrecheck = realSourcePrecheck, scenarioIdsInBoundTestFile = realBoundIds } = {}) {
  const verdict = (scenarios, results, base = [], plan = {}, options = {}) => judge(scenarios, results, base, plan, options)[0]?.verdict;
  const checks = [
    ['positive control: executed pass is VERIFIED', () => verdict([scenario()], [result()]) === 'VERIFIED'],
    ['skipped result is not VERIFIED', () => verdict([scenario()], [result({ status: 'skipped', executed: false })]) === 'BLOCKED'],
    ['failed result is FAILED', () => verdict([scenario()], [result({ status: 'failed' })]) === 'FAILED'],
    ['missing result is BLOCKED', () => verdict([scenario()], []) === 'BLOCKED'],
    ['browser pass without screenshot is BLOCKED', () => verdict([scenario({ surface: 'browser' })], [result()]) === 'BLOCKED'],
    ['base scenario removed from head is BLOCKED', () => verdict([], [], [ID]) === 'BLOCKED'],
    ['new scenario that passed on base is BLOCKED', () => verdict([scenario()], [result()], [], {}, { baseResults: [result()], baseScenarios: [] }) === 'BLOCKED'],
    ['positive control: comments and strings are not hidden-red', () => sourcePrecheck(`// ${hidden('test', '.', 'skip')}\nconst note = "Skip = true";\ntest('${ID}', () => {});`) === true],
    ['skipped test source is rejected', () => sourcePrecheck(`${hidden('test', '.', 'skip')}('${ID}', () => {});`) === false],
    ['positive control: a runnable test title binds its tag', () => scenarioIdsInBoundTestFile(`test('${ID} works', () => {});`).has(ID)],
    ['a tag in a comment does not bind', () => !scenarioIdsInBoundTestFile(`// test('${ID}', () => {});`).has(ID)],
    ['a tag in a skipped test does not bind', () => !scenarioIdsInBoundTestFile(`${hidden('test', '.', 'skip')}('${ID}', () => {});`).has(ID)],
  ];
  const failures = [];
  for (const [name, check] of checks) {
    let ok = false;
    try { ok = check() === true; } catch { ok = false; }
    if (!ok) failures.push(name);
  }
  return { ok: failures.length === 0, failures, total: checks.length };
}

/** Throws SANITY_CANARY_FAILED when any canary no longer behaves; callers abort before judging real input. */
export function assertCanaries(options) {
  const outcome = runCanaries(options);
  if (!outcome.ok) throw new Error(`SANITY_CANARY_FAILED: the gate no longer rejects known-bad input (${outcome.failures.join('; ')})`);
  return outcome;
}
