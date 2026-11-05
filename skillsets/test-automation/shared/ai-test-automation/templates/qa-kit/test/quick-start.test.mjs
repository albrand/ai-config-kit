import test from 'node:test';
import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const kit = resolve(import.meta.dirname, '..');
const skill = resolve(kit, '../../SKILL.md');
const configTemplate = resolve(kit, 'qa.config.example.json');

test('every Node command in the quick start runs with the example config in a fresh git repo', () => {
  const doc = readFileSync(skill, 'utf8');
  const quickStart = doc.split('## Quick start (30 minutes)')[1].split('\n## 0. Decide')[0];
  const commands = [...quickStart.matchAll(/`(node [^`]+)`/g)].map(match => match[1]);
  assert.equal(commands.length, 3, 'quick start command list should be exercised in full');

  const root = mkdtempSync(resolve(tmpdir(), 'qa-quick-start-'));
  try {
    const qa = resolve(root, 'qa');
    cpSync(kit, qa, { recursive: true });
    const cfg = JSON.parse(readFileSync(configTemplate, 'utf8'));
    cfg.compileCommand = [process.execPath, '-e', 'process.exit(0)'];
    cfg.discoverCommand = [process.execPath, '-e', 'console.log("QAS-WI-123-01")'];
    cfg.testCommand = [process.execPath, '-e', 'process.exit(0)'];
    cfg.scenarioFile = 'scenarios.json';
    cfg.resultsFile = 'run-v1.json';
    cfg.resultPath = 'qa-results/junit.xml';
    cfg.base = 'origin/main';
    writeFileSync(resolve(qa, 'qa.config.json'), JSON.stringify(cfg, null, 2));
    const scenarios = [{ id: 'QAS-WI-123-01', workItemId: 'WI-123', kind: 'automated', surface: 'api', mandatory: true, title: 'Example', steps: ['Run request'], expected: 'Returns success' }];
    writeFileSync(resolve(qa, 'scenarios.json'), JSON.stringify(scenarios));
    writeFileSync(resolve(qa, 'base-scenarios.json'), JSON.stringify(scenarios));
    writeFileSync(resolve(qa, 'run-v1.json'), JSON.stringify({ kind: 'run', schemaVersion: 1, planHash: `sha256:${'0'.repeat(64)}`, commitSha: 'a'.repeat(40), runner: 'junit', compiled: true, discoveredIds: ['QAS-WI-123-01'], results: [{ scenarioId: 'QAS-WI-123-01', status: 'passed', executed: true }] }));
    mkdirSync(resolve(qa, 'qa-results'), { recursive: true });
    writeFileSync(resolve(qa, 'qa-results/junit.xml'), '<testsuite><testcase name="QAS-WI-123-01"/></testsuite>');
    const git = (args) => {
      const result = spawnSync('git', args, { cwd: root, encoding: 'utf8' });
      assert.equal(result.status, 0, result.stderr);
    };
    git(['init', '-q', '-b', 'main']);
    git(['config', 'user.name', 'QA test']); git(['config', 'user.email', 'qa@example.invalid']);
    git(['add', 'qa/scenarios.json', 'qa/base-scenarios.json']); git(['commit', '-qm', 'base scenarios']);
    git(['branch', 'origin/main']);

    for (const command of commands) {
      const args = command.match(/(?:"[^"]*"|'[^']*'|\S+)/g).map(token => token.replace(/^['"]|['"]$/g, ''));
      const result = spawnSync(process.execPath, args.slice(1), { cwd: qa, encoding: 'utf8', env: { ...process.env, QA_BOARD_READ_TOKEN: '', QA_BOARD_WRITE_TOKEN: '' } });
      assert.equal(result.status, 0, `${command}\nstdout: ${result.stdout}\nstderr: ${result.stderr}`);
      if (command.includes('board read')) assert.match(result.stdout, /"mode": "dry-run"/);
    }
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
