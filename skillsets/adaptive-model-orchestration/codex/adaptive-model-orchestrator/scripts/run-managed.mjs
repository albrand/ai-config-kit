#!/usr/bin/env node

import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const rawArgs = process.argv.slice(2);
const separator = rawArgs.indexOf('--');

if (separator < 0 || separator === rawArgs.length - 1) {
  throw new Error(
    'Usage: run-managed.mjs [--retain-session] [--deadline-ms N] [--success-contract structured|process] -- <opencode-bin> run ... --format json',
  );
}

const runnerArgs = rawArgs.slice(0, separator);
const command = rawArgs[separator + 1];
const commandArgs = rawArgs.slice(separator + 2);
const retainSession = runnerArgs.includes('--retain-session');

function readOption(name) {
  const index = runnerArgs.indexOf(name);

  return index >= 0 ? runnerArgs[index + 1] : null;
}

const maximumTimerDelayMs = 2_147_483_647;

function readPositiveNumber(name, fallback = null) {
  const value = readOption(name);

  if (value === null) return fallback;

  const parsed = Number(value);

  if (!Number.isFinite(parsed) || parsed < 1 || parsed > maximumTimerDelayMs) {
    throw new Error(`Invalid ${name}`);
  }

  return parsed;
}

const deadlineMs = readPositiveNumber('--deadline-ms');
const terminationGraceMs = readPositiveNumber('--termination-grace-ms', 5_000);
const quiescenceWaitMs = readPositiveNumber('--quiescence-wait-ms', 10_000);
const successContract = readOption('--success-contract') ?? 'structured';
const continuationFlags = ['--session', '-s', '--continue', '-c', '--fork'];
let lastSignalError = null;

if (!['structured', 'process'].includes(successContract)) {
  throw new Error('Invalid --success-contract');
}

if (!command || commandArgs[0] !== 'run') {
  throw new Error('Managed runner only accepts an OpenCode executable followed by `run`');
}

const formatIndex = commandArgs.indexOf('--format');

if (formatIndex < 0 || commandArgs[formatIndex + 1] !== 'json') {
  throw new Error('Managed runner requires `--format json`');
}

if (!retainSession && commandArgs.some((arg) => continuationFlags.includes(arg))) {
  throw new Error('Continuation and fork flags require --retain-session');
}

function listSessions() {
  const result = spawnSync(command, ['session', 'list', '--format', 'json', '-n', '1000'], {
    encoding: 'utf8',
    maxBuffer: 4_194_304,
  });

  if (result.status !== 0) {
    const detail = result.error?.message ?? result.stderr ?? result.stdout ?? 'unknown error';

    throw new Error(`Cannot establish session ownership: ${detail.trim()}`);
  }

  const sessions = JSON.parse(result.stdout);

  if (!Array.isArray(sessions)) {
    throw new Error('OpenCode session list did not return an array');
  }

  return sessions;
}

function isRootSession(id) {
  if (!id) return false;

  const databasePath =
    process.env.OPENCODE_DB_PATH ?? path.join(os.homedir(), '.local/share/opencode/opencode.db');

  if (!fs.existsSync(databasePath)) return false;

  const query = spawnSync(
    'sqlite3',
    ['-readonly', databasePath, `select parent_id is null from session where id='${id}';`],
    { encoding: 'utf8', maxBuffer: 1_048_576 },
  );

  return query.status === 0 && query.stdout.trim() === '1';
}

function signalProcessGroup(pid, signal) {
  try {
    process.kill(-pid, signal);

    return true;
  } catch (error) {
    if (error?.code === 'ESRCH') return false;
    if (error?.code === 'EPERM') {
      lastSignalError = `${signal}:${error.code}`;

      return false;
    }

    throw error;
  }
}

function isProcessGroupAlive(pid) {
  try {
    process.kill(-pid, 0);

    return true;
  } catch (error) {
    if (error?.code === 'ESRCH') return false;
    if (error?.code === 'EPERM') {
      lastSignalError = `probe:${error.code}`;

      return true;
    }

    throw error;
  }
}

function wait(delayMs) {
  return new Promise((resolve) => setTimeout(resolve, delayMs));
}

async function waitForQuiescence(pid, waitMs) {
  const expiresAt = Date.now() + waitMs;

  while (Date.now() < expiresAt) {
    if (!isProcessGroupAlive(pid)) return true;

    await wait(100);
  }

  return !isProcessGroupAlive(pid);
}

const existingSessions = listSessions();
const existingIds = new Set(existingSessions.map((session) => session.id));
const runId = crypto.randomUUID();
const contextRoot = path.resolve(
  process.env.OPENCODE_CONTEXT_DIR ?? path.join(os.tmpdir(), 'opencode-context'),
);
const leaseDir = path.join(contextRoot, 'leases');
const leasePath = path.join(leaseDir, `${runId}.json`);
const startedAtMs = Date.now();
const startedAt = new Date(startedAtMs).toISOString();

fs.mkdirSync(leaseDir, { recursive: true, mode: 0o700 });
fs.chmodSync(leaseDir, 0o700);

function writeLease(value) {
  fs.writeFileSync(leasePath, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  fs.chmodSync(leasePath, 0o600);
}

let sessionId = null;
let parseError = null;
let providerError = null;
let pending = '';
let toolCalls = 0;
let tokenTotals = { input: 0, output: 0, reasoning: 0, total: 0 };
let stopReason = null;
let callerSignal = null;
let deadlineTimer = null;
let escalationTimer = null;
let terminationEscalated = false;
let finishing = false;
const messageTexts = new Map();
let lastMessageId = null;

const child = spawn(command, commandArgs, {
  stdio: ['inherit', 'pipe', 'inherit'],
  detached: true,
});

writeLease({
  run_id: runId,
  caller_pid: process.pid,
  child_pid: child.pid,
  session_id: null,
  started_at: startedAt,
  retention: retainSession ? 'same-step' : 'delete-on-validated-success',
  state: 'running',
  deadline_ms: deadlineMs,
});

function requestStop(reason, signal = 'SIGTERM') {
  if (stopReason) return;

  stopReason = reason;
  signalProcessGroup(child.pid, signal);
  escalationTimer = setTimeout(() => {
    terminationEscalated = true;
    signalProcessGroup(child.pid, 'SIGKILL');
  }, terminationGraceMs);
  escalationTimer.unref();
}

const signalExitCodes = { SIGHUP: 129, SIGINT: 130, SIGTERM: 143 };
const signalHandlers = new Map();

for (const signal of Object.keys(signalExitCodes)) {
  const handler = () => {
    callerSignal = signal;
    requestStop(`caller_signal:${signal}`, signal);
  };

  signalHandlers.set(signal, handler);
  process.on(signal, handler);
}

if (deadlineMs !== null) {
  deadlineTimer = setTimeout(() => {
    requestStop('explicit_deadline');
  }, deadlineMs);
  deadlineTimer.unref();
}

function addTokens(tokens) {
  if (!tokens || typeof tokens !== 'object') return;

  for (const key of Object.keys(tokenTotals)) {
    const value = Number(tokens[key] ?? 0);

    if (Number.isFinite(value)) tokenTotals[key] += value;
  }
}

function consumeLine(line) {
  if (!line.trim()) return;

  let event;

  try {
    event = JSON.parse(line);
  } catch {
    parseError = 'non-JSON stdout from --format json run';
    requestStop('protocol_error');

    return;
  }

  const id = event?.sessionID;

  if (id && !/^ses_[A-Za-z0-9]+$/.test(id)) {
    parseError = 'invalid session ID in JSON event';
    requestStop('protocol_error');
  } else if (id && sessionId && id !== sessionId) {
    parseError = 'multiple session IDs in one managed run';
    requestStop('protocol_error');
  } else if (id) {
    sessionId = id;
  }

  if (event?.type === 'tool_use') toolCalls += 1;
  if (event?.type === 'step_finish') addTokens(event?.part?.tokens);

  if (event?.type === 'error') {
    providerError = event?.error?.data?.message ?? event?.error?.message ?? 'unknown provider error';
    requestStop('provider_error');
  }

  if (event?.type === 'text' && typeof event?.part?.text === 'string') {
    const messageId = event.part.messageID ?? event.messageID ?? '__unidentified_message__';
    const previous = messageTexts.get(messageId) ?? '';

    messageTexts.set(messageId, `${previous}${event.part.text}`);
    lastMessageId = messageId;
  }
}

child.stdout.on('data', (chunk) => {
  const text = chunk.toString();

  process.stdout.write(text);
  pending += text;

  const lines = pending.split('\n');

  pending = lines.pop() ?? '';

  for (const line of lines) consumeLine(line);
});

function hasPassingValidationBlock(text) {
  const block = text.match(/^validation:\s*\n([\s\S]*?)^gates_preserved:/im)?.[1] ?? '';
  const firstEntry = block.search(/^\s*-\s+check:/m);

  if (firstEntry < 0 || block.slice(0, firstEntry).trim()) return false;

  const entries = block
    .slice(firstEntry)
    .split(/(?=^\s*-\s+check:)/m)
    .filter((entry) => entry.trim());

  return (
    entries.length > 0 &&
    entries.every((entry) => {
      const check = entry.match(/^\s*-\s+check:\s*(.+)$/m)?.[1]?.trim() ?? '';
      const result = entry.match(/^\s+result:\s*(\S+)\s*$/m)?.[1] ?? '';

      return Boolean(check) && result === 'pass';
    })
  );
}

function hasStructuredCloseOut(text) {
  const required = [
    'status:',
    'plan_progress:',
    'changes:',
    'artifacts:',
    'validation:',
    'gates_preserved:',
    'residual_risk:',
    'next_step:',
  ];

  if (!text || !/(^|\n)status:\s*done\b/.test(text)) return false;
  if (!required.every((field) => text.includes(field))) return false;

  const gates = text.match(/^gates_preserved:\s*(.+)$/im)?.[1]?.trim() ?? '';
  const affirmativeGates = /^(yes|true|preserved|all preserved)$/i.test(gates);

  return hasPassingValidationBlock(text) && affirmativeGates;
}

async function finalize(code, childSignal) {
  if (finishing) return;

  finishing = true;

  if (deadlineTimer) clearTimeout(deadlineTimer);
  if (escalationTimer) clearTimeout(escalationTimer);
  if (pending.trim()) consumeLine(pending);

  let processQuiescent = await waitForQuiescence(child.pid, quiescenceWaitMs);
  let quiescenceEscalated = false;

  if (!processQuiescent) {
    quiescenceEscalated = signalProcessGroup(child.pid, 'SIGKILL');
    processQuiescent = await waitForQuiescence(child.pid, terminationGraceMs);
  }

  const newlyOwned = Boolean(sessionId && !existingIds.has(sessionId));
  const rootSession = isRootSession(sessionId);
  const lastAssistantText = lastMessageId ? messageTexts.get(lastMessageId) : null;
  const processSuccess = Boolean(lastAssistantText && code === 0 && !providerError && !parseError);
  const validatedDone =
    successContract === 'process' ? processSuccess : processSuccess && hasStructuredCloseOut(lastAssistantText);

  if (!stopReason) {
    if (providerError) stopReason = 'provider_error';
    else if (parseError) stopReason = 'protocol_error';
    else if (code === 0) stopReason = 'completed';
    else if (childSignal) stopReason = `child_signal:${childSignal}`;
    else stopReason = `child_exit:${code ?? 'unknown'}`;
  }

  const eligibleForDeletion = Boolean(
    stopReason === 'completed' &&
      validatedDone &&
      newlyOwned &&
      rootSession &&
      processQuiescent &&
      !retainSession,
  );
  let deleted = false;
  let deleteError = null;

  if (eligibleForDeletion) {
    const result = spawnSync(command, ['session', 'delete', sessionId], {
      encoding: 'utf8',
      maxBuffer: 1_048_576,
    });

    deleted = result.status === 0;
    if (!deleted) deleteError = (result.stderr || result.stdout || 'session delete failed').trim();
  }

  const endedAt = new Date().toISOString();
  const telemetry = {
    context_gc: {
      run_id: runId,
      session_id: sessionId,
      deleted,
      retained: !deleted,
      validated_done: validatedDone,
      success_contract: successContract,
      newly_owned: newlyOwned,
      root_session: rootSession,
      stop_reason: stopReason,
      provider_error: providerError,
      caller_signal: callerSignal,
      explicit_deadline_ms: deadlineMs,
      exit_code: code,
      signal: childSignal,
      parse_error: parseError,
      process_quiescent: processQuiescent,
      termination_escalated: terminationEscalated,
      quiescence_escalated: quiescenceEscalated,
      signal_error: lastSignalError,
      delete_error: deleteError,
      elapsed_ms: Date.now() - startedAtMs,
      tool_calls: toolCalls,
      tokens: tokenTotals,
      lease: leasePath,
    },
  };

  writeLease({
    run_id: runId,
    caller_pid: process.pid,
    child_pid: child.pid,
    session_id: sessionId,
    started_at: startedAt,
    ended_at: endedAt,
    retention: retainSession ? 'same-step' : 'delete-on-validated-success',
    state: deleted ? 'deleted' : 'retained',
    ...telemetry.context_gc,
  });
  process.stderr.write(`${JSON.stringify(telemetry)}\n`);

  for (const [signal, handler] of signalHandlers) process.off(signal, handler);

  if (callerSignal) process.exitCode = signalExitCodes[callerSignal] ?? 1;
  else if (stopReason === 'explicit_deadline') process.exitCode = 124;
  else if (providerError) process.exitCode = 1;
  else if (code === 0 && !validatedDone) process.exitCode = 65;
  else process.exitCode = code ?? 1;
}

child.on('error', (error) => {
  parseError = `failed to launch OpenCode: ${error.message}`;
});

child.on('close', (code, signal) => {
  void finalize(code, signal).catch((error) => {
    for (const [registeredSignal, handler] of signalHandlers) {
      process.off(registeredSignal, handler);
    }

    process.stderr.write(
      `${JSON.stringify({
        context_gc: {
          run_id: runId,
          session_id: sessionId,
          deleted: false,
          retained: true,
          stop_reason: stopReason ?? 'managed_runner_error',
          process_quiescent: false,
          managed_runner_error: error.message,
          lease: leasePath,
        },
      })}\n`,
    );
    process.exitCode = 1;
  });
});
