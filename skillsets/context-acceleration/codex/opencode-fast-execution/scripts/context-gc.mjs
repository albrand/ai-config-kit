#!/usr/bin/env node

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const args = process.argv.slice(2);
const valueAfter = (flag) => { const index = args.indexOf(flag); return index >= 0 ? args[index + 1] : null; };
const root = path.resolve(valueAfter('--context-dir') || process.env.OPENCODE_CONTEXT_DIR || path.join(os.tmpdir(), 'opencode-context'));
const apply = args.includes('--apply');
const maxAgeHours = Number(valueAfter('--max-age-hours') || 24);
if (!Number.isFinite(maxAgeHours) || maxAgeHours < 1) throw new Error('Invalid --max-age-hours');
if (!root.startsWith(path.resolve(os.tmpdir()) + path.sep) && root !== path.resolve(os.tmpdir())) throw new Error('Context GC only accepts a directory under the OS temp directory');

const now = Date.now();
const removable = [];
if (fs.existsSync(root)) for (const name of fs.readdirSync(root)) {
  const filePath = path.join(root, name); const stat = fs.lstatSync(filePath);
  if (stat.isFile() && now - stat.mtimeMs > maxAgeHours * 3_600_000 && /\.(json|jsonl|md|log)$/.test(name)) removable.push(filePath);
}
for (const filePath of removable) if (apply) fs.rmSync(filePath);

const dbPath = path.join(os.homedir(), '.local/share/opencode/opencode.db');
let database = null;
if (fs.existsSync(dbPath)) {
  const sql = "select (select count(*) from session) sessions,(select count(*) from session where time_archived is null) unarchived,round((select sum(pgsize) from dbstat where name='event')/1048576.0,2) event_mb,round((select sum(pgsize) from dbstat where name in ('message','part'))/1048576.0,2) message_part_mb";
  const query = spawnSync('sqlite3', ['-readonly', '-json', dbPath, sql], { encoding: 'utf8', maxBuffer: 1_048_576 });
  database = { path: dbPath, bytes: fs.statSync(dbPath).size, metrics: query.status === 0 ? JSON.parse(query.stdout)[0] : null, query_error: query.status === 0 ? null : query.stderr.trim() };
}

const processes = spawnSync('ps', ['-axo', 'rss=,command='], { encoding: 'utf8' });
const live = processes.stdout.split('\n').filter((line) => /\b(opencode run|codex(?: resume)?)(?:\s|$)/.test(line));
const rssKb = live.reduce((sum, line) => sum + Number(line.trim().split(/\s+/, 1)[0] || 0), 0);

process.stdout.write(`${JSON.stringify({ temp: { root, apply, max_age_hours: maxAgeHours, candidates: removable, removed: apply ? removable : [] }, opencode_database: database, live_agent_processes: { count: live.length, rss_kb: rssKb }, recommendations: ['Use compaction.prune=true', 'Use run-managed.mjs so successful orchestrator-owned sessions are deleted after close-out', 'Never delete active or user-owned sessions automatically', 'Vacuum the database only during a maintenance window with no opencode processes'] }, null, 2)}\n`);
