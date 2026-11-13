import { spawn } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';

// Deployed-run safeguards. Each applies only to a deployed target (see target-allowlist.mjs). Messages carry
// variable names and deny-pattern indexes, never a value.

/** Case-insensitive wildcard match (`*` only). No regular expression is built from config. */
export function wildcardMatch(pattern, value) {
  const parts = String(pattern).toLowerCase().split('*');
  const text = String(value).toLowerCase();
  if (parts.length === 1) return parts[0] === text;
  if (!text.startsWith(parts[0])) return false;
  let pos = parts[0].length;
  for (const part of parts.slice(1, -1)) { const i = text.indexOf(part, pos); if (i < 0) return false; pos = i + part.length; }
  const last = parts.at(-1);
  return text.length - last.length >= pos && text.endsWith(last);
}

const ENV_NAME = /^[A-Z_][A-Z0-9_]{0,127}$/;

/**
 * Identities come only from CI variables the config declares; personal and admin accounts are refused. The config is validated before any
 * variable is read: at least one identity, valid and distinct variable names, and a non-empty `deny` list of non-blank patterns.
 * A variable that is blank after trimming is not set; the user value and each pattern are trimmed before matching.
 */
export function resolveCredentials(envConfig, env, { allowLocalCredentials = false } = {}) {
  const fail = reason => ({ ok: false, code: 'CREDENTIALS_NOT_FROM_CI', reason: `CREDENTIALS_NOT_FROM_CI: ${reason}` });
  const declared = envConfig?.credentials?.identities;
  if (!Array.isArray(declared) || !declared.length) return fail('no credentials declared for this environment');
  const deny = envConfig.credentials.deny;
  if (!Array.isArray(deny) || !deny.length) return fail('credentials.deny must list at least one pattern for personal and admin accounts');
  for (const [index, pattern] of deny.entries()) {
    if (typeof pattern !== 'string' || !pattern.trim() || pattern.length > 256) return fail(`deny pattern ${index} must be a non-blank string of at most 256 characters`);
  }
  for (const [index, identity] of declared.entries()) {
    for (const key of ['userEnv', 'passwordEnv']) {
      const name = identity?.[key];
      if (typeof name !== 'string' || !name) return fail(`identity ${index} does not declare ${key}`);
      if (!ENV_NAME.test(name)) return fail(`identity ${index} ${key} is not a valid variable name`);
    }
    if (identity.userEnv === identity.passwordEnv) return fail(`identity ${index} must use different variables for user and password`);
  }
  if (!(env.CI === 'true' || env.CI === '1') && !allowLocalCredentials) return fail('CI is not set; pass --allow-local-credentials to use local variables');
  const names = [];
  for (const [index, identity] of declared.entries()) {
    for (const key of ['userEnv', 'passwordEnv']) {
      const name = identity[key];
      if (!String(env[name] ?? '').trim()) return fail(`variable ${name} is not set`);
      names.push(name);
    }
    const user = String(env[identity.userEnv]).trim();
    const hit = deny.findIndex(pattern => wildcardMatch(pattern.trim(), user));
    if (hit >= 0) return fail(`identity ${index} matches deny pattern ${hit}`);
  }
  return { ok: true, names };
}

/** Defaults: the test run gets 45 minutes (as upstream), each preflight or cleanup check 5 minutes; both can be overridden per environment. */
export const DEFAULT_TEST_TIMEOUT_SECONDS = 45 * 60;
export const DEFAULT_CHECK_TIMEOUT_SECONDS = 5 * 60;
export const MAX_TIMEOUT_SECONDS = 6 * 60 * 60;

/** `testTimeoutSeconds` and `checkTimeoutSeconds` are optional per-environment overrides: positive integers up to six hours. */
export function resolveTimeouts(envConfig) {
  const read = (key, fallback) => {
    const value = envConfig?.[key];
    if (value === undefined) return { ms: fallback * 1000 };
    if (!Number.isInteger(value) || value < 1 || value > MAX_TIMEOUT_SECONDS) return { error: `${key} must be an integer from 1 to ${MAX_TIMEOUT_SECONDS} seconds` };
    return { ms: value * 1000 };
  };
  const test = read('testTimeoutSeconds', DEFAULT_TEST_TIMEOUT_SECONDS);
  const check = read('checkTimeoutSeconds', DEFAULT_CHECK_TIMEOUT_SECONDS);
  const error = test.error ?? check.error;
  if (error) return { ok: false, code: 'TIMEOUT_CONFIG_INVALID', reason: `TIMEOUT_CONFIG_INVALID: ${error}; no test was run` };
  return { ok: true, testMs: test.ms, checkMs: check.ms };
}

const sleep = ms => new Promise(done => setTimeout(done, ms));
const alive = pid => { try { process.kill(-pid, 0); return true; } catch (error) { return error.code === 'EPERM'; } };

/** Kill the whole process group and wait until no member is left. Returns false when the group will not die. */
async function terminateGroup(pid, waitMs = 10000) {
  try { process.kill(-pid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') return false; }
  const deadline = Date.now() + waitMs;
  while (alive(pid)) {
    if (Date.now() > deadline) return false;
    await sleep(25);
  }
  return true;
}

/** Process groups are the only way to stop a command's descendants here; Windows has no equivalent that can be confirmed. */
export const TREE_KILL_SUPPORTED = process.platform !== 'win32';

/**
 * Run an argv in its own process group with a hard time limit. When the command ends for any reason (exit, non-zero, timeout, spawn
 * error) the whole group is killed and awaited, so no worker it left behind can write to the target afterwards. `treeGone: false` means
 * the group would not die; the caller must fail the run. A process that leaves the group on purpose (setsid, a double fork) is out of reach.
 */
export async function runBounded(argv, env, timeoutMs) {
  const [exe, ...rest] = argv;
  if (!TREE_KILL_SUPPORTED) return { status: 1, stdout: '', stderr: '', timedOut: false, treeGone: false, error: new Error('TREE_KILL_UNSUPPORTED: process-tree termination cannot be confirmed on this platform') };
  const child = spawn(exe, rest, { env, shell: false, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = '';
  let stderr = '';
  let truncated = false;
  const CAP = 10 * 1024 * 1024; // keep at most 10 MB of each stream; a longer one is flagged, never silently cut
  const collect = (stream, append) => {
    stream.setEncoding('utf8').on('data', chunk => { if (append.length() + chunk.length <= CAP) append.add(chunk); else truncated = true; });
    return new Promise(done => { stream.once('end', done); stream.once('close', done); stream.once('error', done); });
  };
  const drained = Promise.all([
    collect(child.stdout, { length: () => stdout.length, add: chunk => { stdout += chunk; } }),
    collect(child.stderr, { length: () => stderr.length, add: chunk => { stderr += chunk; } }),
  ]);
  let timedOut = false;
  const outcome = await new Promise(done => {
    const timer = setTimeout(() => { timedOut = true; try { process.kill(-child.pid, 'SIGKILL'); } catch { /* already gone */ } }, timeoutMs);
    child.once('error', error => { clearTimeout(timer); done({ status: 1, error }); });
    child.once('exit', (code, signal) => { clearTimeout(timer); done({ status: code ?? (signal ? 1 : 1) }); });
  });
  const treeGone = child.pid ? await terminateGroup(child.pid) : true;
  // 'exit' can fire before the pipes are drained. With the group dead nobody holds them open, so this returns at once; the bound only
  // matters for a pipe somebody outside the group still holds, and then the streams are destroyed.
  await Promise.race([drained, sleep(2000)]);
  child.stdout.destroy();
  child.stderr.destroy();
  return { status: outcome.status, stdout, stderr, timedOut, treeGone, truncated, error: outcome.error };
}

const runArgv = (argv, env, timeoutMs = DEFAULT_CHECK_TIMEOUT_SECONDS * 1000) => runBounded(argv, env, timeoutMs);

/** Run each needed argv check once. A failed or undefined check yields BLOCKED, never PASS or a misleading FAIL. */
export async function runPreflights(names, checks, env, timeoutMs = DEFAULT_CHECK_TIMEOUT_SECONDS * 1000) {
  const results = [];
  for (const name of names) {
    const argv = checks?.[name];
    if (!Array.isArray(argv) || !argv.length) { results.push({ name, ok: false, reason: 'check is not defined in config.checks' }); continue; }
    const r = await runArgv(argv, env, timeoutMs);
    if (r.error && !r.treeGone) results.push({ name, ok: false, reason: String(r.error.message).split('\n')[0] });
    else if (!r.treeGone) results.push({ name, ok: false, reason: 'its process tree would not exit' });
    else if (r.timedOut) results.push({ name, ok: false, reason: `timed out after ${timeoutMs / 1000}s` });
    else results.push(r.status === 0 ? { name, ok: true } : { name, ok: false, reason: `exit ${r.status}` });
  }
  const blocked = results.some(r => !r.ok);
  return { ok: !blocked, code: blocked ? 'PREFLIGHT_BLOCKED' : undefined, results };
}

/** A deployed environment must declare a cleanupCheck: the adopter's command that looks for residue on the target. */
export function checkCleanupDeclared(envConfig) {
  const check = envConfig?.cleanupCheck;
  if (Array.isArray(check) && check.length > 0 && check.every(part => typeof part === 'string')) return { ok: true };
  return { ok: false, code: 'CLEANUP_CHECK_MISSING', reason: 'CLEANUP_CHECK_MISSING: a deployed environment must declare cleanupCheck as an argv array; no test was run' };
}

/**
 * The cleanup check always runs, even when the ledger is empty, so it can search the target for residue (for example records tagged
 * with QA_RUN_ID) that the tests never recorded. It prints `{"gone":["kind:id"], "residue":["..."]}`: every ledger row must be in `gone`
 * and `residue` must be empty, or the run fails.
 */
export async function verifyCleanup(ledgerPath, cleanupCheck, env, runId = env.QA_RUN_ID, timeoutMs = DEFAULT_CHECK_TIMEOUT_SECONDS * 1000) {
  const fail = reason => ({ ok: false, code: 'CLEANUP_UNVERIFIED', reason: `CLEANUP_UNVERIFIED: ${reason}` });
  const invalid = reason => ({ ok: false, code: 'CLEANUP_CHECK_INVALID', reason: `CLEANUP_CHECK_INVALID: ${reason}` });
  // `qa test` creates the ledger before the tests start, so a missing one was removed.
  if (!existsSync(ledgerPath)) return fail('ownership ledger is missing');
  let owned;
  try { owned = readFileSync(ledgerPath, 'utf8').split('\n').filter(Boolean).map(line => JSON.parse(line)); }
  catch { return fail('ownership ledger is unreadable'); }
  if (owned.some(r => typeof r?.kind !== 'string' || typeof r?.id !== 'string')) return fail('ownership ledger has a malformed row');
  const r = await runArgv(cleanupCheck, { ...env, QA_OWNS_FILE: ledgerPath, ...(runId ? { QA_RUN_ID: runId } : {}) }, timeoutMs);
  if (!r.treeGone) return fail('a process the cleanup check started would not exit, so the target is not proven clean');
  if (r.timedOut) return invalid(`the cleanup check timed out after ${timeoutMs / 1000}s, so the target is not proven clean`);
  if (r.status !== 0) return invalid(`the cleanup check exited ${r.status}`);
  let reported;
  try { reported = JSON.parse(r.stdout); } catch { return invalid('the cleanup check did not print JSON'); }
  // Strict result: an object whose `gone` and `residue` are both arrays of strings. A missing or wrongly typed field is never read as empty.
  const stringArray = value => Array.isArray(value) && value.every(item => typeof item === 'string');
  if (!reported || typeof reported !== 'object' || Array.isArray(reported) || !stringArray(reported.gone) || !stringArray(reported.residue)) return invalid('the result must be a JSON object with `gone` and `residue`, both arrays of strings');
  const gone = new Set(reported.gone);
  const residue = reported.residue;
  if (residue.length) return fail(`the cleanup check found ${residue.length} residual record(s) on the target: ${residue.slice(0, 20).join(', ')}`);
  const missing = owned.filter(rec => !gone.has(`${rec.kind}:${rec.id}`));
  if (missing.length) return fail(`${missing.length} owned record(s) not proven gone: ${missing.map(m => `${m.kind}:${m.id}`).join(', ')}`);
  return { ok: true, owned: owned.length };
}
