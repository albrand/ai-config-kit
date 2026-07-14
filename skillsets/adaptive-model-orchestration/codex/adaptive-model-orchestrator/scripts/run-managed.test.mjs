#!/usr/bin/env node

import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scripts = path.dirname(fileURLToPath(import.meta.url));
const runner = path.join(scripts, 'run-managed.mjs');
const wrapper = path.join(scripts, 'run-opencode-sidecar.sh');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'opencode-managed-test-'));
const binDir = path.join(temp, 'bin');
const fake = path.join(binDir, 'opencode');
const customFake = path.join(binDir, 'opencode-custom-wrapper');
const statePath = path.join(temp, 'sessions.json');
const deleteLog = path.join(temp, 'deleted.log');
const descendantPidPath = path.join(temp, 'descendant.pid');
const databasePath = path.join(temp, 'opencode.db');
const configDir = path.join(temp, 'config');
const worktree = path.join(temp, 'worktree');

fs.mkdirSync(binDir);
fs.mkdirSync(configDir);
fs.mkdirSync(worktree);
fs.writeFileSync(path.join(configDir, 'opencode.json'), '{}');
fs.writeFileSync(path.join(worktree, '.ai-config-kit-sidecar-write-scope'), 'test only\n');
fs.writeFileSync(
  fake,
  `#!/usr/bin/env node
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const statePath = process.env.FAKE_STATE_PATH;
const deleteLog = process.env.FAKE_DELETE_LOG;
const args = process.argv.slice(2);
const sessions = () => fs.existsSync(statePath) ? JSON.parse(fs.readFileSync(statePath, 'utf8')) : [];
if (args[0] === 'session' && args[1] === 'list') {
  process.stdout.write(JSON.stringify(sessions()));
  process.exit(0);
}
if (args[0] === 'session' && args[1] === 'delete') {
  fs.appendFileSync(deleteLog, args[2] + '\\n');
  process.exit(0);
}
if (args[0] !== 'run') process.exit(2);
const id = process.env.FAKE_SESSION_ID || 'ses_test123';
fs.writeFileSync(statePath, JSON.stringify([{ id, parentID: null }]));
const emit = (event) => process.stdout.write(JSON.stringify({ sessionID: id, ...event }) + '\\n');
const closeOut = 'status: done\\nplan_progress: complete\\nchanges: []\\nartifacts: []\\nvalidation:\\n  - check: focused test\\n    result: pass\\ngates_preserved: yes\\nresidual_risk: none\\nnext_step: null';
if (process.env.FAKE_MODE?.startsWith('provider-error')) {
  emit({ type: 'error', error: { data: { message: 'The operation timed out.' } } });
  if (process.env.FAKE_MODE === 'provider-error-zero') process.exit(0);
  if (process.env.FAKE_MODE === 'provider-error-hang') setInterval(() => {}, 1000);
  else process.exit(1);
}
if (process.env.FAKE_MODE === 'hang') {
  const descendant = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' });
  fs.writeFileSync(process.env.FAKE_DESCENDANT_PID_PATH, String(descendant.pid));
  emit({ type: 'step_start', part: {} });
  setInterval(() => {}, 1000);
} else if (process.env.FAKE_MODE === 'stubborn') {
  process.on('SIGTERM', () => {});
  emit({ type: 'step_start', part: {} });
  setInterval(() => {}, 1000);
} else {
  const delay = process.env.FAKE_MODE === 'slow-success' ? 100 : 0;
  let result = closeOut;
  if (process.env.FAKE_MODE === 'failed-validation') {
    result = closeOut.replace('result: pass', 'result: fail');
  }
  if (process.env.FAKE_MODE === 'failed-gates') {
    result = closeOut.replace('gates_preserved: yes', 'gates_preserved: no');
  }
  if (process.env.FAKE_MODE === 'empty-validation') {
    result = closeOut.replace('validation:\\n  - check: focused test\\n    result: pass', 'validation: []');
  }
  if (process.env.FAKE_MODE === 'ambiguous-gates') {
    result = closeOut.replace('gates_preserved: yes', 'gates_preserved: uncertain');
  }
  if (process.env.FAKE_MODE === 'missing-check') {
    result = closeOut.replace('  - check: focused test\\n    result: pass', '  - result: pass');
  }
  if (process.env.FAKE_MODE === 'out-of-section-pass') {
    result = closeOut
      .replace('validation:\\n  - check: focused test\\n    result: pass', 'validation: []')
      .replace('residual_risk: none', 'residual_risk: none\\n  result: pass');
  }
  setTimeout(() => emit({ type: 'text', part: { messageID: 'msg_final', text: result } }), delay);
}
`,
);
fs.chmodSync(fake, 0o700);
fs.copyFileSync(fake, customFake);
fs.chmodSync(customFake, 0o700);
const database = spawnSync('sqlite3', [
  databasePath,
  "create table session(id text primary key,parent_id text); insert into session values('ses_test123',null); insert into session values('ses_existing123',null); insert into session values('ses_parent123',null); insert into session values('ses_child123','ses_parent123');",
]);
assert.equal(database.status, 0, database.stderr?.toString());

function runManaged(extraArgs = [], env = {}, executable = fake) {
  return spawnSync(
    process.execPath,
    [runner, ...extraArgs, '--', executable, 'run', 'test', '--format', 'json'],
    {
      encoding: 'utf8',
      timeout: 10_000,
      env: {
        ...process.env,
        OPENCODE_CONTEXT_DIR: path.join(temp, 'context'),
        OPENCODE_DB_PATH: databasePath,
        FAKE_STATE_PATH: statePath,
        FAKE_DELETE_LOG: deleteLog,
        FAKE_DESCENDANT_PID_PATH: descendantPidPath,
        ...env,
      },
    },
  );
}

function readTelemetry(result) {
  const lines = result.stderr.trim().split('\n').reverse();

  for (const line of lines) {
    try {
      const parsed = JSON.parse(line);

      if (parsed.context_gc) return parsed.context_gc;
    } catch {}
  }

  throw new Error(`No managed-runner telemetry found:\n${result.stderr}`);
}

function runWrapper(env = {}) {
  return spawnSync(wrapper, ['execute-high', worktree, 'test'], {
    encoding: 'utf8',
    timeout: 10_000,
    env: {
      ...process.env,
      OPENCODE_ALLOW_WRITES: '1',
      OPENCODE_BIN: fake,
      OPENCODE_CONTEXT_DIR: path.join(temp, 'context'),
      OPENCODE_DB_PATH: databasePath,
      OPENCODE_SIDECAR_CONFIG_DIR: configDir,
      FAKE_STATE_PATH: statePath,
      FAKE_DELETE_LOG: deleteLog,
      FAKE_DESCENDANT_PID_PATH: descendantPidPath,
      ...env,
    },
  });
}

function runAndCancel() {
  return new Promise((resolve, reject) => {
    const child = spawn(
      process.execPath,
      [runner, '--', fake, 'run', 'test', '--format', 'json'],
      {
        env: {
          ...process.env,
          OPENCODE_CONTEXT_DIR: path.join(temp, 'context'),
          OPENCODE_DB_PATH: databasePath,
          FAKE_STATE_PATH: statePath,
          FAKE_DELETE_LOG: deleteLog,
          FAKE_DESCENDANT_PID_PATH: descendantPidPath,
          FAKE_MODE: 'hang',
        },
      },
    );
    let stdout = '';
    let stderr = '';
    let cancellationSent = false;
    const guard = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error('caller-signal test timed out'));
    }, 5_000);

    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();

      if (!cancellationSent) {
        cancellationSent = true;
        child.kill('SIGTERM');
      }
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    child.on('close', (code, signal) => {
      clearTimeout(guard);
      resolve({ status: code, signal, stdout, stderr });
    });
  });
}

try {
  const noDefaultDeadline = runManaged([], { FAKE_MODE: 'slow-success' });
  assert.equal(noDefaultDeadline.status, 0, noDefaultDeadline.stderr);
  assert.equal(readTelemetry(noDefaultDeadline).stop_reason, 'completed');
  assert.equal(readTelemetry(noDefaultDeadline).explicit_deadline_ms, null);
  assert.equal(readTelemetry(noDefaultDeadline).deleted, true);

  fs.rmSync(statePath, { force: true });
  const deadline = runManaged(['--deadline-ms', '50', '--termination-grace-ms', '100'], {
    FAKE_MODE: 'hang',
  });
  assert.equal(deadline.status, 124, deadline.stderr);
  assert.equal(readTelemetry(deadline).stop_reason, 'explicit_deadline');
  assert.equal(readTelemetry(deadline).deleted, false);
  assert.equal(readTelemetry(deadline).process_quiescent, true);

  fs.rmSync(statePath, { force: true });
  const stubborn = runManaged(
    ['--deadline-ms', '200', '--termination-grace-ms', '50'],
    { FAKE_MODE: 'stubborn' },
  );
  assert.equal(stubborn.status, 124, stubborn.stderr);
  assert.equal(readTelemetry(stubborn).termination_escalated, true);
  assert.equal(readTelemetry(stubborn).process_quiescent, true);

  fs.rmSync(statePath, { force: true });
  const providerError = runManaged([], { FAKE_MODE: 'provider-error' });
  assert.notEqual(providerError.status, 0);
  assert.equal(readTelemetry(providerError).stop_reason, 'provider_error');
  assert.equal(readTelemetry(providerError).provider_error, 'The operation timed out.');
  assert.equal(readTelemetry(providerError).deleted, false);

  fs.rmSync(statePath, { force: true });
  const cancelled = await runAndCancel();
  assert.equal(cancelled.status, 143, cancelled.stderr);
  assert.equal(readTelemetry(cancelled).stop_reason, 'caller_signal:SIGTERM');
  assert.equal(readTelemetry(cancelled).process_quiescent, true);
  assert.equal(readTelemetry(cancelled).deleted, false);
  const descendantPid = Number(fs.readFileSync(descendantPidPath, 'utf8'));
  assert.throws(() => process.kill(descendantPid, 0), { code: 'ESRCH' });

  fs.rmSync(statePath, { force: true });
  const providerErrorZero = runManaged([], { FAKE_MODE: 'provider-error-zero' });
  assert.notEqual(providerErrorZero.status, 0);
  assert.equal(readTelemetry(providerErrorZero).stop_reason, 'provider_error');
  assert.equal(readTelemetry(providerErrorZero).deleted, false);

  fs.rmSync(statePath, { force: true });
  const providerErrorHang = runManaged([], { FAKE_MODE: 'provider-error-hang' });
  assert.notEqual(providerErrorHang.status, 0);
  assert.equal(readTelemetry(providerErrorHang).stop_reason, 'provider_error');
  assert.equal(readTelemetry(providerErrorHang).process_quiescent, true);

  fs.rmSync(statePath, { force: true });
  const failedValidation = runManaged([], { FAKE_MODE: 'failed-validation' });
  assert.notEqual(failedValidation.status, 0);
  assert.equal(readTelemetry(failedValidation).validated_done, false);
  assert.equal(readTelemetry(failedValidation).deleted, false);

  fs.rmSync(statePath, { force: true });
  const failedGates = runManaged([], { FAKE_MODE: 'failed-gates' });
  assert.notEqual(failedGates.status, 0);
  assert.equal(readTelemetry(failedGates).validated_done, false);
  assert.equal(readTelemetry(failedGates).deleted, false);

  fs.rmSync(statePath, { force: true });
  const emptyValidation = runManaged([], { FAKE_MODE: 'empty-validation' });
  assert.notEqual(emptyValidation.status, 0);
  assert.equal(readTelemetry(emptyValidation).validated_done, false);
  assert.equal(readTelemetry(emptyValidation).deleted, false);

  fs.rmSync(statePath, { force: true });
  const ambiguousGates = runManaged([], { FAKE_MODE: 'ambiguous-gates' });
  assert.notEqual(ambiguousGates.status, 0);
  assert.equal(readTelemetry(ambiguousGates).validated_done, false);
  assert.equal(readTelemetry(ambiguousGates).deleted, false);

  fs.rmSync(statePath, { force: true });
  const missingCheck = runManaged([], { FAKE_MODE: 'missing-check' });
  assert.notEqual(missingCheck.status, 0);
  assert.equal(readTelemetry(missingCheck).validated_done, false);
  assert.equal(readTelemetry(missingCheck).deleted, false);

  fs.rmSync(statePath, { force: true });
  const outOfSectionPass = runManaged([], { FAKE_MODE: 'out-of-section-pass' });
  assert.notEqual(outOfSectionPass.status, 0);
  assert.equal(readTelemetry(outOfSectionPass).validated_done, false);
  assert.equal(readTelemetry(outOfSectionPass).deleted, false);

  fs.rmSync(statePath, { force: true });
  const customExecutable = runManaged([], {}, customFake);
  assert.equal(customExecutable.status, 0, customExecutable.stderr);
  assert.equal(readTelemetry(customExecutable).deleted, true);

  fs.rmSync(statePath, { force: true });
  const childSession = runManaged([], { FAKE_SESSION_ID: 'ses_child123' });
  assert.equal(childSession.status, 0, childSession.stderr);
  assert.equal(readTelemetry(childSession).root_session, false);
  assert.equal(readTelemetry(childSession).deleted, false);

  const oversizedDeadline = runManaged(['--deadline-ms', '2147483648']);
  assert.notEqual(oversizedDeadline.status, 0);
  assert.match(oversizedDeadline.stderr, /Invalid --deadline-ms/);

  fs.writeFileSync(statePath, JSON.stringify([{ id: 'ses_existing123', parentID: null }]));
  const continued = runManaged(
    ['--retain-session'],
    { FAKE_SESSION_ID: 'ses_existing123' },
  );
  assert.equal(continued.status, 0, continued.stderr);
  assert.equal(readTelemetry(continued).newly_owned, false);
  assert.equal(readTelemetry(continued).deleted, false);

  fs.rmSync(statePath, { force: true });
  const wrapped = runWrapper();
  assert.equal(wrapped.status, 0, wrapped.stderr);
  assert.equal(readTelemetry(wrapped).success_contract, 'structured');
  assert.equal(readTelemetry(wrapped).deleted, true);

  fs.writeFileSync(statePath, JSON.stringify([{ id: 'ses_existing123', parentID: null }]));
  const resumed = runWrapper({
    OPENCODE_RETAIN_SESSION: '1',
    OPENCODE_SESSION_ID: 'ses_existing123',
    FAKE_SESSION_ID: 'ses_existing123',
  });
  assert.equal(resumed.status, 0, resumed.stderr);
  assert.equal(readTelemetry(resumed).newly_owned, false);
  assert.equal(readTelemetry(resumed).deleted, false);

  const invalidResume = runWrapper({ OPENCODE_SESSION_ID: 'ses_existing123' });
  assert.equal(invalidResume.status, 64);
  assert.match(invalidResume.stderr, /OPENCODE_RETAIN_SESSION=1/);

  process.stdout.write('managed runner: pass\n');
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
