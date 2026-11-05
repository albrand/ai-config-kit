import test from 'node:test';
import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const kit = resolve(import.meta.dirname, '..');
const skill = resolve(kit, '../../SKILL.md');
const configTemplate = resolve(kit, 'qa.config.example.json');
const oldCase = { id: 'QAS-WI-123-01', workItemId: 'WI-123', criterionIds: ['AC-create'], kind: 'automated', surface: 'api', mandatory: true, title: 'Creates a record', steps: ['Submit valid input'], expected: 'One record is returned' };
const changedCase = { ...oldCase, title: 'Creates exactly one record' };
const newCase = { ...oldCase, id: 'QAS-WI-123-02', criterionIds: ['AC-read'], title: 'Reads a record', steps: ['Request the record'], expected: 'The record is returned' };

function evidence(results) {
  const rows = results.map(({ scenarioId, status = 'passed', executed = true }) => ({ scenarioId, status, executed }));
  return { kind: 'run', schemaVersion: 1, planHash: `sha256:${'0'.repeat(64)}`, commitSha: 'a'.repeat(40), runner: 'junit', compiled: true, discoveredIds: rows.filter(row => row.executed).map(row => row.scenarioId), results: rows };
}

test('quick-start commands match the example config and enforce changed-scenario evidence and judge verdicts', () => {
  const doc = readFileSync(skill, 'utf8');
  const quickStart = doc.split('## Quick start (30 minutes)')[1].split('\n## 0. Decide')[0];
  const commands = [...quickStart.matchAll(/`(node [^`]+)`/g)].map(match => match[1]);
  assert.equal(commands.length, 3, 'quick start command list should be exercised in full');
  const root = mkdtempSync(resolve(tmpdir(), 'qa-quick-start-'));
  try {
    const qa = resolve(root, 'qa');
    cpSync(kit, qa, { recursive: true });
    const cfg = JSON.parse(readFileSync(configTemplate, 'utf8'));
    cfg.scenarioFile = 'scenarios.json'; cfg.resultsFile = 'run-v1.json'; cfg.resultPath = 'qa-results/junit.xml'; cfg.base = 'origin/main';
    writeFileSync(resolve(qa, 'qa.config.json'), JSON.stringify(cfg, null, 2));
    writeFileSync(resolve(qa, 'scenarios.json'), JSON.stringify([oldCase]));
    writeFileSync(resolve(qa, 'base-scenarios.json'), JSON.stringify([oldCase]));
    mkdirSync(resolve(qa, 'qa-results'), { recursive: true });
    writeFileSync(resolve(qa, 'qa-results/junit.xml'), '<testsuite><testcase name="QAS-WI-123-01"/></testsuite>');
    const git = args => { const result = spawnSync('git', args, { cwd: root, encoding: 'utf8' }); assert.equal(result.status, 0, result.stderr); };
    git(['init', '-q', '-b', 'main']); git(['config', 'user.name', 'QA test']); git(['config', 'user.email', 'qa@example.invalid']);
    git(['add', 'qa/scenarios.json']); git(['commit', '-qm', 'base scenarios']); git(['branch', 'origin/main']);
    writeFileSync(resolve(qa, 'scenarios.json'), JSON.stringify([changedCase, newCase]));
    const runFile = resolve(qa, 'run-v1.json');
    const parsedCommands = commands.map(command => command.match(/(?:"[^"]*"|'[^']*'|\S+)/g).map(token => token.replace(/^['"]|['"]$/g, '')));
    const invoke = args => spawnSync(process.execPath, args.slice(1), { cwd: qa, encoding: 'utf8', env: { ...process.env, QA_BOARD_READ_TOKEN: '', QA_BOARD_WRITE_TOKEN: '', GITHUB_SHA: 'a'.repeat(40) } });

    const read = invoke(parsedCommands[0]);
    assert.equal(read.status, 0, read.stderr); assert.match(read.stdout, /"mode": "dry-run"/);

    const checkArgs = parsedCommands[1];
    writeFileSync(runFile, JSON.stringify(evidence([{ scenarioId: changedCase.id }, { scenarioId: newCase.id }])));
    const check = invoke(checkArgs); assert.equal(check.status, 0, check.stderr);
    const rows = JSON.parse(check.stdout);
    assert.deepEqual(rows.map(row => [row.id, row.ok]), [[changedCase.id, true], [newCase.id, true]]);
    for (const bad of [
      evidence([{ scenarioId: changedCase.id }]),
      evidence([{ scenarioId: changedCase.id, status: 'skipped', executed: false }, { scenarioId: newCase.id }])
    ]) {
      writeFileSync(runFile, JSON.stringify(bad));
      assert.notEqual(invoke(checkArgs).status, 0, 'missing or skipped evidence must block scenario storage');
    }
    writeFileSync(runFile, JSON.stringify(evidence([{ scenarioId: changedCase.id, status: 'failed' }, { scenarioId: newCase.id }])));
    const executedFailure = invoke(checkArgs);
    assert.equal(executedFailure.status, 0, executedFailure.stderr);
    assert.deepEqual(JSON.parse(executedFailure.stdout).map(row => [row.id, row.ok]), [[changedCase.id, true], [newCase.id, true]], 'failed but executed tests may be stored as scenarios');

    const judgeArgs = [...parsedCommands[2], '--base-scenarios', 'base-scenarios.json'];
    writeFileSync(runFile, JSON.stringify(evidence([{ scenarioId: changedCase.id }, { scenarioId: newCase.id }])));
    const pass = invoke(judgeArgs); assert.equal(pass.status, 0, pass.stderr);
    assert.ok(JSON.parse(pass.stdout).rows.every(row => row.verdict === 'VERIFIED'));
    for (const bad of [
      evidence([{ scenarioId: changedCase.id }]),
      evidence([{ scenarioId: changedCase.id, status: 'skipped', executed: false }, { scenarioId: newCase.id }]),
      evidence([{ scenarioId: changedCase.id, status: 'failed' }, { scenarioId: newCase.id }])
    ]) {
      writeFileSync(runFile, JSON.stringify(bad));
      const judged = invoke(judgeArgs); assert.notEqual(judged.status, 0, 'judge must reject incomplete, skipped, or failed run evidence');
      assert.ok(JSON.parse(judged.stdout).rows.some(row => ['BLOCKED', 'FAILED'].includes(row.verdict)));
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});
