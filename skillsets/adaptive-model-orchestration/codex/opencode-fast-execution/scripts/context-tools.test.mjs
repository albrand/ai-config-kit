#!/usr/bin/env node

import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scripts = path.dirname(fileURLToPath(import.meta.url));

function run(file, args = [], options = {}) {
  return spawnSync(process.execPath, [path.join(scripts, file), ...args], {
    encoding: 'utf8',
    ...options,
  });
}

const call = run('classify-call.mjs', [], {
  input: JSON.stringify({
    objective: 'x',
    scope: ['a'],
    inputs: 'b',
    output: 'c',
    escalation: 'd',
  }),
});
assert.equal(call.status, 0);
assert.equal(JSON.parse(call.stdout).classification, 'execute');

const liveLargeRun = run('classify-run-progress.mjs', [], {
  input: JSON.stringify({
    process_state: 'running',
    elapsed_ms: 300_000,
    outer_silence_ms: 180_000,
    pre_edit_tools: 99,
    validation_calls: 12,
  }),
});
assert.equal(liveLargeRun.status, 0);
assert.equal(JSON.parse(liveLargeRun.stdout).decision, 'continue');

const scopeViolation = run('classify-run-progress.mjs', [], {
  input: JSON.stringify({ process_state: 'running', verified_scope_violation: true }),
});
assert.equal(JSON.parse(scopeViolation.stdout).decision, 'stop');

const unknownState = run('classify-run-progress.mjs', [], {
  input: JSON.stringify({ pre_edit_tools: 99, repair_attempts: 0 }),
});
assert.equal(JSON.parse(unknownState.stdout).decision, 'continue');

const firstInsufficient = run('classify-run-progress.mjs', [], {
  input: JSON.stringify({
    process_state: 'exited',
    process_quiescent: true,
    result_status: 'partial',
  }),
});
assert.equal(JSON.parse(firstInsufficient.stdout).decision, 'repair');

const nonQuiescent = run('classify-run-progress.mjs', [], {
  input: JSON.stringify({
    process_state: 'completed',
    process_quiescent: false,
    result_status: 'partial',
  }),
});
assert.equal(JSON.parse(nonQuiescent.stdout).decision, 'continue');

const missingQuiescence = run('classify-run-progress.mjs', [], {
  input: JSON.stringify({ process_state: 'stopped', result_status: 'partial' }),
});
assert.equal(JSON.parse(missingQuiescence.stdout).decision, 'continue');

const repairedInsufficient = run('classify-run-progress.mjs', [], {
  input: JSON.stringify({
    process_state: 'exited',
    process_quiescent: true,
    result_status: 'partial',
    repair_attempts: 1,
  }),
});
assert.equal(JSON.parse(repairedInsufficient.stdout).decision, 'escalate');

const complete = run('classify-run-progress.mjs', [], {
  input: JSON.stringify({
    process_state: 'exited',
    process_quiescent: true,
    result_status: 'done',
    acceptance_criteria_met: true,
    close_out_complete: true,
  }),
});
assert.equal(JSON.parse(complete.stdout).decision, 'complete');

const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'opencode-context-test-'));
const stale = path.join(temp, 'stale.json');

fs.writeFileSync(stale, '{}');
fs.utimesSync(stale, new Date(0), new Date(0));

const dryRun = run('context-gc.mjs', ['--context-dir', temp, '--max-age-hours', '1']);
assert.equal(dryRun.status, 0);
assert.equal(fs.existsSync(stale), true);

const applied = run('context-gc.mjs', [
  '--context-dir',
  temp,
  '--max-age-hours',
  '1',
  '--apply',
]);
assert.equal(applied.status, 0);
assert.equal(fs.existsSync(stale), false);

const refused = run('context-gc.mjs', ['--context-dir', process.cwd()]);
assert.notEqual(refused.status, 0);

fs.rmSync(temp, { recursive: true, force: true });
process.stdout.write('OpenCode context tools: pass\n');
