import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, existsSync, writeFileSync } from 'node:fs';
import { execSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { installAiPack, checkAiPack, packSourceRoot } from '../lib/ai-pack.mjs';

const kit = resolve(import.meta.dirname, '..');
const cli = join(kit, 'bin/qa.mjs');

test('pack source exposes four task skills', () => {
  const root = packSourceRoot();
  assert.ok(existsSync(join(root, '.agents/skills/scenario-design/SKILL.md')));
  assert.ok(existsSync(join(root, '.agents/skills/bug-hunting-test-automation/SKILL.md')));
  assert.ok(existsSync(join(root, '.agents/skills/run-and-gate/SKILL.md')));
  assert.ok(existsSync(join(root, '.agents/skills/bug-report/SKILL.md')));
});

test('ai-pack --write installs provider entrypoints; --check passes with no drift', () => {
  const target = mkdtempSync(join(tmpdir(), 'ai-pack-adopter-'));
  try {
    const write = spawnSync(process.execPath, [cli, 'ai-pack', '--write', '--target', target], { encoding: 'utf8' });
    assert.equal(write.status, 0, write.stderr || write.stdout);
    for (const rel of [
      '.agents/skills/scenario-design/SKILL.md',
      '.claude/skills/bug-hunting-test-automation/SKILL.md',
      'CLAUDE.md',
      'AGENTS.md',
      '.cursor/rules/qa-core.mdc',
      '.github/copilot-instructions.md',
      '.github/instructions/qa-run-and-gate.instructions.md',
    ]) assert.ok(existsSync(join(target, rel)), rel);
    assert.match(readFileSync(join(target, 'CLAUDE.md'), 'utf8'), /@AGENTS\.md/);
    const check = spawnSync(process.execPath, [cli, 'ai-pack', '--check', '--target', target], { encoding: 'utf8' });
    assert.equal(check.status, 0, check.stderr || check.stdout);
    assert.match(check.stdout, /"drift": \[\]/);
  } finally {
    rmSync(target, { recursive: true, force: true });
  }
});

test('ai-pack --check exits 1 when entrypoints drift', () => {
  const target = mkdtempSync(join(tmpdir(), 'ai-pack-drift-'));
  try {
    installAiPack(target);
    const tampered = join(target, 'AGENTS.md');
    writeTamper(tampered);
    const check = spawnSync(process.execPath, [cli, 'ai-pack', '--check', '--target', target], { encoding: 'utf8' });
    assert.notEqual(check.status, 0);
    assert.ok(checkAiPack(target).length > 0);
  } finally {
    rmSync(target, { recursive: true, force: true });
  }
});

test('old kit without ai-pack command fails CLI smoke', () => {
  const scratch = mkdtempSync(join(tmpdir(), 'ai-pack-old-'));
  try {
    execSync(
      'git archive 4af12cc -- skillsets/test-automation/shared/ai-test-automation/templates/qa-kit/bin/qa.mjs | tar -x -C .',
      { cwd: scratch, stdio: 'pipe' }
    );
    const oldCli = join(scratch, 'skillsets/test-automation/shared/ai-test-automation/templates/qa-kit/bin/qa.mjs');
    const run = spawnSync(process.execPath, [oldCli, 'ai-pack', '--check'], { encoding: 'utf8' });
    assert.notEqual(run.status, 0, 'merge-base CLI must not implement ai-pack yet');
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

function writeTamper(path) {
  writeFileSync(path, `${readFileSync(path, 'utf8')}\n# drift\n`);
}
