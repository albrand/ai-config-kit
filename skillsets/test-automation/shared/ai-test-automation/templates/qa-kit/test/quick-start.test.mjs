import test from 'node:test';
import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const kit = resolve(import.meta.dirname, '..');
const skill = resolve(kit, '../../SKILL.md');
const configTemplate = resolve(kit, 'qa.config.example.json');
const scenarioFields = { kind: 'automated', surface: 'api', layer: 'api', mandatory: true, workItemId: 'WI-123', regressionCase: false };
const oldCase = { ...scenarioFields, id: 'QAS-WI-123-01', criterionIds: ['AC-create'], polarity: 'positive', title: 'Creates a record', steps: ['Submit valid input'], expected: 'One record is returned' };
const createNegative = { ...scenarioFields, id: 'QAS-WI-123-03', criterionIds: ['AC-create'], polarity: 'negative', title: 'Rejects invalid input', steps: ['Submit invalid input'], expected: 'No record is created and the user sees a clear error' };
const createRegression = { ...scenarioFields, id: 'QAS-WI-123-04', criterionIds: ['AC-create'], polarity: 'positive', regressionCase: true, title: 'Regression create', steps: ['Submit valid input'], expected: 'Creation still works on the prior release behaviour' };
const changedCase = { ...oldCase, title: 'Creates exactly one record' };
const newCase = { ...scenarioFields, id: 'QAS-WI-123-02', criterionIds: ['AC-read'], polarity: 'positive', title: 'Reads a record', steps: ['Request the record'], expected: 'The record is returned' };
const readNegative = { ...scenarioFields, id: 'QAS-WI-123-05', criterionIds: ['AC-read'], polarity: 'negative', title: 'Missing record rejected', steps: ['Request a missing record'], expected: 'The user sees not found without leaking internal data' };
const readRegression = { ...scenarioFields, id: 'QAS-WI-123-06', criterionIds: ['AC-read'], polarity: 'positive', regressionCase: true, title: 'Regression read', steps: ['Request the record'], expected: 'Read behaviour matches the last release' };
const baseScenarios = [oldCase, createNegative, createRegression];
const headScenarios = [changedCase, createNegative, createRegression, newCase, readNegative, readRegression];

function evidence(results) {
  const rows = results.map(({ scenarioId, status = 'passed', executed = true }) => ({ scenarioId, status, executed }));
  return { kind: 'run', schemaVersion: 1, planHash: `sha256:${'0'.repeat(64)}`, commitSha: 'a'.repeat(40), runner: 'junit', compiled: true, discoveredIds: rows.filter(row => row.executed).map(row => row.scenarioId), results: rows };
}

test('quick-start commands match the example config and enforce changed-scenario evidence and judge verdicts', () => {
  const doc = readFileSync(skill, 'utf8');
  const quickStart = doc.split('## Quick start (30 minutes)')[1].split('\n## 0. Decide')[0];
  const commands = [...quickStart.matchAll(/`(node [^`]+)`/g)].map(match => match[1]).filter(cmd => !cmd.includes('ai-pack'));
  assert.equal(commands.length, 3, 'quick start board/check/judge commands should be exercised in full');
  const root = mkdtempSync(resolve(tmpdir(), 'qa-quick-start-'));
  try {
    const qa = resolve(root, 'qa');
    cpSync(kit, qa, { recursive: true });
    const cfg = JSON.parse(readFileSync(configTemplate, 'utf8'));
    cfg.scenarioFile = 'scenarios.json'; cfg.resultsFile = 'run-v1.json'; cfg.resultPath = 'qa-results/junit.xml'; cfg.base = 'origin/main';
    writeFileSync(resolve(qa, 'qa.config.json'), JSON.stringify(cfg, null, 2));
    writeFileSync(resolve(qa, 'scenarios.json'), JSON.stringify(baseScenarios));
    writeFileSync(resolve(qa, 'base-scenarios.json'), JSON.stringify(baseScenarios));
    mkdirSync(resolve(qa, 'qa-results'), { recursive: true });
    writeFileSync(resolve(qa, 'qa-results/junit.xml'), '<testsuite><testcase name="QAS-WI-123-01"/></testsuite>');
    const git = args => { const result = spawnSync('git', args, { cwd: root, encoding: 'utf8' }); assert.equal(result.status, 0, result.stderr); };
    git(['init', '-q', '-b', 'main']); git(['config', 'user.name', 'QA test']); git(['config', 'user.email', 'qa@example.invalid']);
    git(['add', 'qa/scenarios.json']); git(['commit', '-qm', 'base scenarios']); git(['branch', 'origin/main']);
    writeFileSync(resolve(qa, 'scenarios.json'), JSON.stringify(headScenarios));
    const runFile = resolve(qa, 'run-v1.json');
    const parsedCommands = commands.map(command => command.match(/(?:"[^"]*"|'[^']*'|\S+)/g).map(token => token.replace(/^['"]|['"]$/g, '')));
    const invoke = args => spawnSync(process.execPath, args.slice(1), { cwd: qa, encoding: 'utf8', env: { ...process.env, QA_BOARD_READ_TOKEN: '', QA_BOARD_WRITE_TOKEN: '', GITHUB_SHA: 'a'.repeat(40) } });

    const read = invoke(parsedCommands[0]);
    assert.equal(read.status, 0, read.stderr); assert.match(read.stdout, /"mode": "dry-run"/);

    const checkArgs = parsedCommands[1];
    writeFileSync(runFile, JSON.stringify(evidence(headScenarios.map(s => ({ scenarioId: s.id })))));
    const check = invoke(checkArgs); assert.equal(check.status, 0, check.stderr);
    const rows = JSON.parse(check.stdout);
    const scenarioRows = rows.filter(row => row.id.startsWith('QAS-'));
    assert.ok(scenarioRows.every(row => row.ok), JSON.stringify(scenarioRows, null, 2));
    for (const bad of [
      evidence([{ scenarioId: changedCase.id }]),
      evidence([{ scenarioId: changedCase.id, status: 'skipped', executed: false }, { scenarioId: newCase.id }])
    ]) {
      writeFileSync(runFile, JSON.stringify(bad));
      assert.notEqual(invoke(checkArgs).status, 0, 'missing or skipped evidence must block scenario storage');
    }
    writeFileSync(runFile, JSON.stringify(evidence(headScenarios.map(s => ({
      scenarioId: s.id,
      status: s.id === changedCase.id ? 'failed' : 'passed',
    })))));
    const executedFailure = invoke(checkArgs);
    assert.equal(executedFailure.status, 0, executedFailure.stderr);
    assert.ok(JSON.parse(executedFailure.stdout).filter(row => row.id.startsWith('QAS-')).every(row => row.ok), 'failed but executed tests may be stored as scenarios');

    const judgeArgs = [...parsedCommands[2], '--base-scenarios', 'base-scenarios.json'];
    writeFileSync(runFile, JSON.stringify(evidence(headScenarios.map(s => ({ scenarioId: s.id })))));
    const pass = invoke(judgeArgs); assert.equal(pass.status, 0, pass.stderr);
    assert.ok(JSON.parse(pass.stdout).rows.every(row => row.verdict === 'VERIFIED'));
    const focusIds = [changedCase.id, newCase.id];
    const verdictSlice = rows => rows
      .filter(row => focusIds.includes(row.scenarioId))
      .map(row => [row.scenarioId, row.verdict, row.blocking]);
    for (const { run, expected } of [
      { run: evidence([{ scenarioId: changedCase.id }]), expected: [[changedCase.id, 'VERIFIED', false], [newCase.id, 'BLOCKED', true]] },
      { run: evidence([{ scenarioId: changedCase.id, status: 'skipped', executed: false }, { scenarioId: newCase.id }]), expected: [[changedCase.id, 'BLOCKED', true], [newCase.id, 'VERIFIED', false]] },
      { run: evidence([{ scenarioId: changedCase.id, status: 'failed' }, { scenarioId: newCase.id }]), expected: [[changedCase.id, 'FAILED', true], [newCase.id, 'VERIFIED', false]] }
    ]) {
      writeFileSync(runFile, JSON.stringify(run));
      const judged = invoke(judgeArgs); assert.notEqual(judged.status, 0, 'judge must reject incomplete, skipped, or failed run evidence');
      const verdictRows = JSON.parse(judged.stdout).rows;
      assert.deepEqual(verdictSlice(verdictRows), expected);
      const changed = verdictRows.find(row => row.scenarioId === changedCase.id);
      if (run.results.find(row => row.scenarioId === changedCase.id)?.status === 'failed') {
        assert.equal(changed.verdict, 'FAILED');
        assert.equal(changed.blocking, true);
      }
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});
