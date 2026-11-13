import { spawnSync } from 'node:child_process';
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

/** Identities come only from CI variables the config declares; personal and admin accounts are refused. */
export function resolveCredentials(envConfig, env, { allowLocalCredentials = false } = {}) {
  const fail = reason => ({ ok: false, code: 'CREDENTIALS_NOT_FROM_CI', reason: `CREDENTIALS_NOT_FROM_CI: ${reason}` });
  const declared = envConfig?.credentials?.identities;
  if (!Array.isArray(declared) || !declared.length) return fail('no credentials declared for this environment');
  if (!(env.CI === 'true' || env.CI === '1') && !allowLocalCredentials) return fail('CI is not set; pass --allow-local-credentials to use local variables');
  const deny = envConfig.credentials.deny ?? [];
  const names = [];
  for (const [index, identity] of declared.entries()) {
    for (const key of ['userEnv', 'passwordEnv']) {
      const name = identity?.[key];
      if (typeof name !== 'string' || !name) return fail(`identity ${index} does not declare ${key}`);
      if (!env[name]) return fail(`variable ${name} is not set`);
      names.push(name);
    }
    const hit = deny.findIndex(pattern => wildcardMatch(pattern, env[identity.userEnv]));
    if (hit >= 0) return fail(`identity ${index} matches deny pattern ${hit}`);
  }
  return { ok: true, names };
}

const runArgv = (argv, env) => {
  const [exe, ...rest] = argv;
  const r = spawnSync(exe, rest, { encoding: 'utf8', env, shell: false });
  return { status: r.error ? 1 : (r.status ?? 1), stdout: r.stdout ?? '' };
};

/** Run each needed argv check once. A failed or undefined check yields BLOCKED, never PASS or a misleading FAIL. */
export function runPreflights(names, checks, env) {
  const results = names.map(name => {
    const argv = checks?.[name];
    if (!Array.isArray(argv) || !argv.length) return { name, ok: false, reason: 'check is not defined in config.checks' };
    const r = runArgv(argv, env);
    return r.status === 0 ? { name, ok: true } : { name, ok: false, reason: `exit ${r.status}` };
  });
  const blocked = results.some(r => !r.ok);
  return { ok: !blocked, code: blocked ? 'PREFLIGHT_BLOCKED' : undefined, results };
}

/** Every record the run created (JSON lines `{kind,id}`) must be reported gone by the cleanup check, or the run fails. */
export function verifyCleanup(ledgerPath, cleanupCheck, env) {
  const fail = reason => ({ ok: false, code: 'CLEANUP_UNVERIFIED', reason: `CLEANUP_UNVERIFIED: ${reason}` });
  // `qa test` creates the ledger before the tests start, so a missing one was removed.
  if (!existsSync(ledgerPath)) return fail('ownership ledger is missing');
  let owned;
  try { owned = readFileSync(ledgerPath, 'utf8').split('\n').filter(Boolean).map(line => JSON.parse(line)); }
  catch { return fail('ownership ledger is unreadable'); }
  if (owned.some(r => typeof r?.kind !== 'string' || typeof r?.id !== 'string')) return fail('ownership ledger has a malformed row');
  const r = runArgv(cleanupCheck, { ...env, QA_OWNS_FILE: ledgerPath });
  if (r.status !== 0) return fail(`cleanup check exited ${r.status}`);
  let reported;
  try { reported = JSON.parse(r.stdout); } catch { return fail('cleanup check wrote no JSON result'); }
  const gone = new Set((Array.isArray(reported?.gone) ? reported.gone : []).map(String));
  const missing = owned.filter(rec => !gone.has(`${rec.kind}:${rec.id}`));
  if (missing.length) return fail(`${missing.length} owned record(s) not proven gone: ${missing.map(m => `${m.kind}:${m.id}`).join(', ')}`);
  return { ok: true, owned: owned.length };
}
