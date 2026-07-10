#!/usr/bin/env node

import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const scripts = path.dirname(new URL(import.meta.url).pathname);
const run = (file, args = [], options = {}) => spawnSync(process.execPath, [path.join(scripts, file), ...args], { encoding: 'utf8', ...options });

const classify = run('classify-call.mjs', [], { input: JSON.stringify({ objective: 'x', scope: ['a'], inputs: 'b', output: 'c', escalation: 'd' }) });
assert.equal(classify.status, 0);
assert.equal(JSON.parse(classify.stdout).classification, 'execute');

const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'opencode-context-test-'));
const stale = path.join(temp, 'stale.json');
fs.writeFileSync(stale, '{}');
fs.utimesSync(stale, new Date(0), new Date(0));
const dry = run('context-gc.mjs', ['--context-dir', temp, '--max-age-hours', '1']);
assert.equal(dry.status, 0);
assert.equal(fs.existsSync(stale), true);
const apply = run('context-gc.mjs', ['--context-dir', temp, '--max-age-hours', '1', '--apply']);
assert.equal(apply.status, 0);
assert.equal(fs.existsSync(stale), false);
const refused = run('context-gc.mjs', ['--context-dir', process.cwd()]);
assert.notEqual(refused.status, 0);

const bin = path.join(temp, 'bin');
fs.mkdirSync(bin);
const deleteLog = path.join(temp, 'deleted');
const testDb = path.join(temp, 'opencode.db');
const dbSetup = spawnSync('sqlite3', [testDb, "create table session(id text primary key,parent_id text); insert into session values('ses_test123',null);"], { encoding: 'utf8' });
assert.equal(dbSetup.status, 0);
const fake = path.join(bin, 'opencode');
fs.writeFileSync(fake, `#!/bin/sh\nif [ "$1" = session ] && [ "$2" = list ]; then echo '[]'; exit 0; fi\nif [ "$1" = run ]; then echo '{"type":"text","sessionID":"ses_test123","part":{"text":"status: done; plan_progress: complete; changes: []; artifacts: []; validation: []; gates_preserved: yes; residual_risk: none; next_step: null"}}'; exit 0; fi\nif [ "$1" = session ] && [ "$2" = delete ]; then echo "$3" > "${deleteLog}"; exit 0; fi\nexit 1\n`);
fs.chmodSync(fake, 0o700);
const managed = run('run-managed.mjs', ['--timeout-ms', '5000', '--', 'opencode', 'run', 'test', '--format', 'json'], { env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, OPENCODE_DB_PATH: testDb } });
assert.equal(managed.status, 0);
assert.equal(fs.existsSync(deleteLog), true, managed.stderr);
assert.equal(fs.readFileSync(deleteLog, 'utf8').trim(), 'ses_test123');
assert.equal(JSON.parse(managed.stderr).context_gc.deleted, true);

fs.rmSync(temp, { recursive: true, force: true });
process.stdout.write('context tools: pass\n');
