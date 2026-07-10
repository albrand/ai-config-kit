#!/usr/bin/env node

import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const args = process.argv.slice(2); const separator = args.indexOf('--');
if (separator < 0 || separator === args.length - 1) throw new Error('Usage: run-managed.mjs [--retain-session] [--timeout-ms N] -- opencode run ... --format json');
const retainSession = args.includes('--retain-session'); const timeoutIndex = args.indexOf('--timeout-ms');
const timeoutMs = timeoutIndex >= 0 ? Number(args[timeoutIndex + 1]) : 600_000;
if (!Number.isFinite(timeoutMs) || timeoutMs < 1_000) throw new Error('Invalid --timeout-ms');
const command = args[separator + 1]; const commandArgs = args.slice(separator + 2);
if (command !== 'opencode' || commandArgs[0] !== 'run') throw new Error('Managed runner only accepts `opencode run`');
const formatIndex = commandArgs.indexOf('--format');
if (formatIndex < 0 || commandArgs[formatIndex + 1] !== 'json') throw new Error('Managed runner requires `--format json`');
if (!retainSession && commandArgs.some((arg) => ['--session', '-s', '--continue', '-c', '--fork'].includes(arg))) throw new Error('Continuation/fork flags require --retain-session');

const existingResult = spawnSync('opencode', ['session', 'list', '--format', 'json', '-n', '1000'], { encoding: 'utf8', maxBuffer: 4_194_304 });
if (existingResult.status !== 0) throw new Error(`Cannot establish session ownership: ${existingResult.stderr.trim()}`);
const existingIds = new Set(JSON.parse(existingResult.stdout).map((session) => session.id));
const runId = crypto.randomUUID(); const leaseDir = path.join(os.tmpdir(), 'opencode-context', 'leases');
fs.mkdirSync(leaseDir, { recursive: true, mode: 0o700 }); fs.chmodSync(leaseDir, 0o700);
const leasePath = path.join(leaseDir, `${runId}.json`); const startedAt = new Date().toISOString();
const writeLease = (value) => { fs.writeFileSync(leasePath, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 }); fs.chmodSync(leasePath, 0o600); };

let sessionId = null; let parseError = null; let timedOut = false; let killTimer = null; let pending = ''; let lastAssistantText = null;
const child = spawn(command, commandArgs, { stdio: ['inherit', 'pipe', 'inherit'], detached: true });
writeLease({ run_id: runId, caller_pid: process.pid, child_pid: child.pid, session_id: null, started_at: startedAt, retention: retainSession ? 'same-step' : 'delete-on-validated-success', state: 'running' });
const timer = setTimeout(() => { timedOut = true; try { process.kill(-child.pid, 'SIGTERM'); } catch {} killTimer = setTimeout(() => { try { process.kill(-child.pid, 'SIGKILL'); } catch {} }, 5_000); }, timeoutMs);

child.stdout.on('data', (chunk) => {
  const text = chunk.toString(); process.stdout.write(text); pending += text;
  const lines = pending.split('\n'); pending = lines.pop() ?? '';
  for (const line of lines) {
    if (!line.trim()) continue;
    try {
      const event = JSON.parse(line); const id = event?.sessionID;
      if (id && !/^ses_[A-Za-z0-9]+$/.test(id)) parseError = 'invalid session ID in JSON event';
      else if (id && sessionId && id !== sessionId) parseError = 'multiple session IDs in one managed run';
      else if (id) sessionId = id;
      if (event?.type === 'text' && typeof event?.part?.text === 'string') lastAssistantText = event.part.text;
    } catch { parseError = 'non-JSON stdout from --format json run'; }
  }
});

child.on('close', (code, signal) => {
  clearTimeout(timer); if (killTimer) clearTimeout(killTimer);
  const newlyOwned = Boolean(sessionId && !existingIds.has(sessionId));
  let rootSession = false;
  if (sessionId) {
    const db = process.env.OPENCODE_DB_PATH || path.join(os.homedir(), '.local/share/opencode/opencode.db');
    const sql = `select parent_id is null from session where id='${sessionId}';`;
    const result = spawnSync('sqlite3', ['-readonly', db, sql], { encoding: 'utf8', maxBuffer: 2_097_152 });
    if (result.status === 0) rootSession = result.stdout.trim() === '1';
  }
  const required = ['status:', 'plan_progress:', 'changes:', 'artifacts:', 'validation:', 'gates_preserved:', 'residual_risk:', 'next_step:'];
  const validDone = Boolean(lastAssistantText && /(^|\n)status:\s*done\b/.test(lastAssistantText) && required.every((field) => lastAssistantText.includes(field)));
  const eligible = code === 0 && !timedOut && !parseError && newlyOwned && rootSession && validDone && !retainSession;
  let deleted = false; let deleteError = null;
  if (eligible) { const result = spawnSync('opencode', ['session', 'delete', sessionId], { encoding: 'utf8' }); deleted = result.status === 0; if (!deleted) deleteError = (result.stderr || result.stdout || 'session delete failed').trim(); }
  const state = deleted ? 'deleted' : 'retained';
  writeLease({ run_id: runId, caller_pid: process.pid, child_pid: child.pid, session_id: sessionId, started_at: startedAt, ended_at: new Date().toISOString(), retention: retainSession ? 'same-step' : 'delete-on-validated-success', state, validated_done: validDone, newly_owned: newlyOwned, root_session: rootSession, timed_out: timedOut, exit_code: code, signal, parse_error: parseError, delete_error: deleteError });
  process.stderr.write(`${JSON.stringify({ context_gc: { run_id: runId, session_id: sessionId, deleted, retained: !deleted, validated_done: validDone, newly_owned: newlyOwned, root_session: rootSession, timed_out: timedOut, exit_code: code, signal, parse_error: parseError, delete_error: deleteError, lease: leasePath } })}\n`);
  process.exitCode = code ?? 1;
});
