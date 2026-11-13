import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { sourcePrecheck } from '../lib/scenario-check.mjs';

// The rule modules load dynamically so a missing module fails each test on its own instead of the whole file.
const load = name => import(`../lib/${name}.mjs`).catch(() => ({}));
const { scenarioIdsInBoundTestFile, unboundScenarios } = await load('bound-tests');
const { assertCanaries, runCanaries } = await load('canaries');
const { checkTarget, isDeployedTarget } = await load('target-allowlist');
const { DEFAULT_CHECK_TIMEOUT_SECONDS, DEFAULT_TEST_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS, resolveCredentials, resolveTimeouts, runPreflights, verifyCleanup, wildcardMatch } = await load('deployed-run');
const { recordOwned } = await load('qa-owns');

const cli = resolve(import.meta.dirname, '../bin/qa.mjs');
const hidden = (...parts) => parts.join('');
const ID = 'QAS-WI-1-01';

// --- Rule 1: a bound test counts only when a runnable test carries the scenario tag ---------------------------

test('bound-test: a runnable test title binds its scenario tag', () => {
  assert.deepEqual([...scenarioIdsInBoundTestFile(`test('${ID} shows two rows', async () => {});`)], [ID]);
  assert.deepEqual([...scenarioIdsInBoundTestFile(`describe.serial("${ID}", () => {});`)], [ID]);
});

test('bound-test: a tag in a comment, an unrelated string or a test body does not bind', () => {
  assert.equal(scenarioIdsInBoundTestFile(`// test('${ID}', () => {});`).size, 0);
  assert.equal(scenarioIdsInBoundTestFile(`/* it('${ID}', () => {}); */`).size, 0);
  assert.equal(scenarioIdsInBoundTestFile(`const note = '${ID}';\ntest('other case', () => {});`).size, 0);
  assert.equal(scenarioIdsInBoundTestFile(`test('other case', () => { expect(x).toBe('${ID}'); });`).size, 0);
});

test('bound-test: skipped and fixme tests do not bind', () => {
  for (const modifier of ['skip', 'fixme', 'todo', 'only']) {
    assert.equal(scenarioIdsInBoundTestFile(`${hidden('test', '.', modifier)}('${ID}', () => {});`).size, 0, modifier);
  }
  assert.equal(scenarioIdsInBoundTestFile(`${hidden('x', 'it')}('${ID}', () => {});`).size, 0);
  assert.equal(scenarioIdsInBoundTestFile(`[Fact(DisplayName = "${ID}", ${hidden('Sk', 'ip')} = "later")]`).size, 0);
});

test('bound-test: an ID matches whole, so a longer ID never binds a shorter one', () => {
  const bound = scenarioIdsInBoundTestFile(`test('QAS-WI-1-010 other', () => {});`);
  assert.equal(bound.has(ID), false);
  assert.equal(bound.has('QAS-WI-1-010'), true);
});

test('bound-test: scenario_id label calls and DisplayName attributes bind', () => {
  assert.equal(scenarioIdsInBoundTestFile(`await allure.label('scenario_id', '${ID}');`).has(ID), true);
  assert.equal(scenarioIdsInBoundTestFile(`@allure.label("scenario_id", "${ID}")\ndef test_x(): pass`).has(ID), true);
  assert.equal(scenarioIdsInBoundTestFile(`[Fact(DisplayName = "${ID}")] void X() {}`).has(ID), true);
  assert.equal(scenarioIdsInBoundTestFile(`// await allure.label('scenario_id', '${ID}');`).has(ID), false);
  assert.equal(scenarioIdsInBoundTestFile(`allure.label('severity', '${ID}');`).has(ID), false);
  assert.deepEqual(unboundScenarios([`test('${ID}', () => {});`], [{ id: ID, kind: 'automated' }, { id: 'QAS-WI-1-02', kind: 'automated' }, { id: 'QAS-WI-1-03', kind: 'manual' }]), ['QAS-WI-1-02']);
});

function gitProject() {
  const root = mkdtempSync(join(tmpdir(), 'qa-guard-'));
  const git = (...argv) => execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@example.invalid', ...argv], { cwd: root, stdio: 'pipe' });
  git('init', '-q', '-b', 'main');
  writeFileSync(join(root, 'scenarios.json'), '[]');
  writeFileSync(join(root, 'qa.config.json'), '{}');
  git('add', '.');
  git('commit', '-q', '-m', 'base');
  return root;
}

test('check-scenarios --source fails a changed automated scenario that no runnable test carries', () => {
  const root = gitProject();
  try {
    const scenario = { id: ID, kind: 'automated', surface: 'api', layer: 'api', polarity: 'positive', regressionCase: false, mandatory: true, criterionIds: ['AC-a'], title: 'Rows', steps: ['load the page'], expected: 'two rows are listed' };
    const negative = { ...scenario, id: 'QAS-WI-1-02', polarity: 'negative' };
    const regression = { ...scenario, id: 'QAS-WI-1-03', regressionCase: true };
    writeFileSync(join(root, 'scenarios.json'), JSON.stringify([scenario, negative, regression]));
    const run = { compiled: true, discoveredIds: [ID, negative.id, regression.id], results: [ID, negative.id, regression.id].map(scenarioId => ({ scenarioId, status: 'passed', executed: true })) };
    writeFileSync(join(root, 'run-v1.json'), JSON.stringify(run));
    const body = id => `test('${id} case', () => { expect(page.getByText('two rows are listed', { exact: true })).toHaveText('two rows are listed'); });\n`;
    writeFileSync(join(root, 'bound.spec.js'), body(ID) + body(negative.id) + body(regression.id));
    writeFileSync(join(root, 'unbound.spec.js'), `// ${body(ID)}\nconst tag = '${ID}'; test('other', () => { expect(page.getByText('two rows are listed', { exact: true })).toHaveText('two rows are listed'); });\n`);
    const args = ['check-scenarios', '--head', 'scenarios.json', '--base', 'main', '--file', 'scenarios.json', '--results', 'run-v1.json'];
    const rowsFor = files => JSON.parse(spawnSync(process.execPath, [cli, ...args, ...files.flatMap(f => ['--source', f])], { cwd: root, encoding: 'utf8' }).stdout);
    const good = rowsFor(['bound.spec.js']);
    assert.deepEqual(good.filter(r => !r.ok), []);
    const bad = spawnSync(process.execPath, [cli, ...args, '--source', 'unbound.spec.js'], { cwd: root, encoding: 'utf8' });
    assert.notEqual(bad.status, 0);
    assert.match(bad.stdout, /no runnable test in the --source files carries the scenario tag/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

// --- Rule 2: gate canaries ------------------------------------------------------------------------------------

test('canaries: the shipped gate passes every canary and positive control', () => {
  const outcome = runCanaries();
  assert.deepEqual(outcome.failures, []);
  assert.equal(outcome.ok, true);
  assert.ok(outcome.total >= 10);
  const cliRun = spawnSync(process.execPath, [cli, 'canary'], { encoding: 'utf8' });
  assert.equal(cliRun.status, 0, cliRun.stderr);
});

test('canaries: a judge that passes bad input is caught', () => {
  const rubberStamp = scenarios => scenarios.map(s => ({ id: s.id, verdict: 'VERIFIED', reason: 'ok', blocking: false }));
  const outcome = runCanaries({ judge: rubberStamp });
  assert.equal(outcome.ok, false);
  assert.ok(outcome.failures.some(name => /skipped result/.test(name)));
  assert.ok(outcome.failures.some(name => /failed result/.test(name)));
  assert.throws(() => assertCanaries({ judge: rubberStamp }), /SANITY_CANARY_FAILED/);
});

test('canaries: a source precheck or tag scan that stops rejecting is caught', () => {
  assert.equal(runCanaries({ sourcePrecheck: () => true }).ok, false);
  assert.equal(runCanaries({ scenarioIdsInBoundTestFile: source => new Set(source.match(/QAS-[\w-]+-\d{2,}/g) ?? []) }).ok, false);
  assert.equal(runCanaries({ judge: () => [] }).ok, false);
});

// --- Rule 3: deployment target allowlist ----------------------------------------------------------------------

const allowCfg = { environments: { staging: { origins: ['https://staging.example.invalid'] }, empty: {} } };

test('target allowlist: loopback and no base URL are never deployed', () => {
  for (const baseUrl of [undefined, 'http://localhost:3000', 'http://127.0.0.1:8080', 'http://[::1]:3000']) {
    assert.deepEqual(checkTarget({ baseUrl, config: allowCfg }), { ok: true, deployed: false });
    assert.equal(isDeployedTarget(baseUrl), false);
  }
});

test('target allowlist: a URL outside the declared origins is refused with TARGET_NOT_ALLOWED', () => {
  const refused = [
    { baseUrl: 'https://prod.example.invalid', environment: 'staging' },
    { baseUrl: 'https://staging.example.invalid.evil.invalid', environment: 'staging' },
    { baseUrl: 'https://staging.example.invalid', environment: 'empty' },
    { baseUrl: 'https://staging.example.invalid', environment: 'unknown' },
    { baseUrl: 'https://staging.example.invalid' },
    { baseUrl: 'https://staging.example.invalid', environment: 'local' },
    { baseUrl: 'not a url', environment: 'staging' },
    { baseUrl: 'ftp://staging.example.invalid', environment: 'staging' },
  ];
  for (const input of refused) {
    const outcome = checkTarget({ ...input, config: allowCfg });
    assert.equal(outcome.ok, false, JSON.stringify(input));
    assert.match(outcome.reason, /^TARGET_NOT_ALLOWED/);
  }
  assert.deepEqual(checkTarget({ baseUrl: 'https://staging.example.invalid/app?x=1', environment: 'staging', config: allowCfg }), { ok: true, deployed: true });
});

// A throwaway project whose commands record what ran, so a refused run is proven to start nothing.
function runProject(config, files = {}) {
  const root = mkdtempSync(join(tmpdir(), 'qa-run-'));
  const script = (name, body) => { mkdirSync(dirname(join(root, name)), { recursive: true }); writeFileSync(join(root, name), body); };
  script('compile.mjs', `import { writeFileSync } from 'node:fs'; writeFileSync('compiled.marker', '1');`);
  script('discover.mjs', `console.log('${ID}');`);
  script('tests.mjs', files.tests ?? `import { mkdirSync, writeFileSync } from 'node:fs'; mkdirSync('qa-results', { recursive: true }); writeFileSync('qa-results/junit.xml', '<testsuite><testcase name="${ID}"/></testsuite>');`);
  script('cleanup.mjs', `console.log(JSON.stringify({ gone: [], residue: [] }));`);
  for (const [name, body] of Object.entries(files.other ?? {})) script(name, body);
  const base = { compileCommand: ['node', 'compile.mjs'], discoverCommand: ['node', 'discover.mjs'], testCommand: ['node', 'tests.mjs'], resultFormat: 'junit', resultPath: 'qa-results/junit.xml', runner: 'stub' };
  writeFileSync(join(root, 'qa.config.json'), JSON.stringify({ ...base, ...config }));
  const run = (args = [], env = {}) => spawnSync(process.execPath, [cli, 'test', ...args], { cwd: root, encoding: 'utf8', env: { PATH: process.env.PATH, GITHUB_HEAD_SHA: 'a'.repeat(40), ...env } });
  return { root, run, has: name => existsSync(join(root, name)), read: name => readFileSync(join(root, name), 'utf8') };
}

test('qa test refuses a target outside the allowlist before compiling anything', () => {
  const project = runProject({ environments: { staging: { origins: ['https://staging.example.invalid'] } } });
  try {
    for (const args of [['--base-url', 'https://prod.example.invalid', '--env', 'staging'], ['--base-url', 'https://staging.example.invalid'], ['--base-url', 'https://staging.example.invalid', '--env', 'local']]) {
      const r = project.run(args);
      assert.equal(r.status, 1, args.join(' '));
      assert.match(r.stderr, /TARGET_NOT_ALLOWED/);
      assert.equal(project.has('compiled.marker'), false, 'a refused target starts no command');
    }
    const loopback = project.run(['--base-url', 'http://localhost:3000']);
    assert.equal(loopback.status, 0, loopback.stderr);
    assert.equal(project.has('compiled.marker'), true);
  } finally { rmSync(project.root, { recursive: true, force: true }); }
});

// --- Rule 4: deployed-run safeguards --------------------------------------------------------------------------

test('deployed run: wildcard deny patterns are case-insensitive and never build a regular expression', () => {
  assert.equal(wildcardMatch('admin*', 'ADMIN@corp.invalid'), true);
  assert.equal(wildcardMatch('*@personal.invalid', 'Me@Personal.INVALID'), true);
  assert.equal(wildcardMatch('qa-*-bot', 'qa-7-bot'), true);
  assert.equal(wildcardMatch('qa-*-bot', 'qa-7-user'), false);
  assert.equal(wildcardMatch('(a+)+$', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaa!'), false);
  assert.equal(wildcardMatch('a.c', 'abc'), false);
});

const envCfg = { credentials: { identities: [{ userEnv: 'QA_U', passwordEnv: 'QA_P' }], deny: ['admin*', '*@personal.invalid'] } };

test('deployed run: identities come only from declared CI variables and exclude personal or admin accounts', () => {
  const ok = { CI: 'true', QA_U: 'svc-qa@corp.invalid', QA_P: 'pw-value' };
  assert.deepEqual(resolveCredentials(envCfg, ok), { ok: true, names: ['QA_U', 'QA_P'] });
  const refusals = [
    [{}, ok],
    [{ credentials: {} }, ok],
    [envCfg, { ...ok, QA_P: '' }],
    [envCfg, { ...ok, CI: undefined }],
    [envCfg, { ...ok, CI: 'false' }],
    [envCfg, { ...ok, QA_U: 'ADMIN-root@corp.invalid' }],
    [envCfg, { ...ok, QA_U: 'alex@personal.invalid' }],
  ];
  for (const [cfg, env] of refusals) {
    const outcome = resolveCredentials(cfg, env);
    assert.equal(outcome.ok, false);
    assert.match(outcome.reason, /^CREDENTIALS_NOT_FROM_CI/);
    assert.doesNotMatch(outcome.reason, /pw-value|svc-qa|alex@|ADMIN-root/);
  }
  assert.equal(resolveCredentials(envCfg, { ...ok, CI: undefined }, { allowLocalCredentials: true }).ok, true);
});

test('deployed run: the credentials config is validated before any variable is read', () => {
  const ok = { CI: 'true', QA_U: 'svc-qa@corp.invalid', QA_P: 'pw-value' };
  const withCreds = credentials => ({ credentials: { identities: [{ userEnv: 'QA_U', passwordEnv: 'QA_P' }], ...credentials } });
  const refused = {
    'deny missing': withCreds({}),
    'deny empty': withCreds({ deny: [] }),
    'deny not an array': withCreds({ deny: 'admin*' }),
    'deny holds an empty string': withCreds({ deny: [''] }),
    'deny holds a blank string': withCreds({ deny: ['   '] }),
    'deny holds a non-string': withCreds({ deny: [42] }),
    'deny pattern over 256 characters': withCreds({ deny: ['a'.repeat(257)] }),
    'user and password share a variable': { credentials: { identities: [{ userEnv: 'QA_U', passwordEnv: 'QA_U' }], deny: ['admin*'] } },
    'lower-case variable name': { credentials: { identities: [{ userEnv: 'qa_u', passwordEnv: 'QA_P' }], deny: ['admin*'] } },
    'variable name with a dash': { credentials: { identities: [{ userEnv: 'QA-U', passwordEnv: 'QA_P' }], deny: ['admin*'] } },
    'variable name over 128 characters': { credentials: { identities: [{ userEnv: 'A'.repeat(129), passwordEnv: 'QA_P' }], deny: ['admin*'] } },
    'no identities': { credentials: { identities: [], deny: ['admin*'] } },
  };
  for (const [name, cfg] of Object.entries(refused)) {
    const outcome = resolveCredentials(cfg, ok);
    assert.equal(outcome.ok, false, name);
    assert.match(outcome.reason, /^CREDENTIALS_NOT_FROM_CI/, name);
  }
  assert.equal(resolveCredentials(withCreds({ deny: ['admin*'] }), ok).ok, true);
});

test('deployed run: admin and personal accounts are refused case-insensitively; a dedicated test account passes', () => {
  const run = user => resolveCredentials(envCfg, { CI: 'true', QA_U: user, QA_P: 'pw-value' });
  assert.equal(run('Admin@corp.invalid').ok, false);
  assert.equal(run('ADMIN').ok, false);
  assert.equal(run('Alex@PERSONAL.invalid').ok, false);
  assert.equal(run('svc-qa-staging@corp.invalid').ok, true);
});

test('deployed run: blank values count as unset and whitespace cannot dodge the deny list', () => {
  const base = { CI: 'true', QA_U: 'svc-qa@corp.invalid', QA_P: 'pw-value' };
  assert.equal(resolveCredentials(envCfg, { ...base, QA_P: '   ' }).ok, false);
  assert.equal(resolveCredentials(envCfg, { ...base, QA_U: '\t ' }).ok, false);
  assert.equal(resolveCredentials(envCfg, { ...base, QA_U: ' admin@corp.invalid' }).ok, false);
  assert.equal(resolveCredentials(envCfg, { ...base, QA_U: 'admin@corp.invalid ' }).ok, false);
  assert.equal(resolveCredentials({ credentials: { ...envCfg.credentials, deny: [' admin* '] } }, { ...base, QA_U: 'admin@corp.invalid' }).ok, false);
  assert.equal(resolveCredentials(envCfg, { ...base, QA_U: ' svc-qa@corp.invalid ' }).ok, true);
});

test('the example config gives every deployed environment a non-empty deny list that its own credentials pass', () => {
  const cfg = JSON.parse(readFileSync(new URL('../qa.config.example.json', import.meta.url), 'utf8'));
  for (const [name, env] of Object.entries(cfg.environments)) {
    assert.ok(Array.isArray(env.credentials.deny) && env.credentials.deny.length > 0, name);
    const vars = Object.fromEntries(env.credentials.identities.flatMap(i => [[i.userEnv, 'svc-qa-account'], [i.passwordEnv, 'pw-value']]));
    assert.equal(resolveCredentials(env, { CI: 'true', ...vars }).ok, true, name);
  }
});

test('deployed run: a missing prerequisite reports PREFLIGHT_BLOCKED, never a pass', async () => {
  const pass = ['node', '-e', 'process.exit(0)'];
  const fail = ['node', '-e', 'process.exit(3)'];
  assert.equal((await runPreflights(['up'], { up: pass }, process.env)).ok, true);
  for (const checks of [{ up: fail }, {}, { up: [] }]) {
    const outcome = (await runPreflights(['up'], checks, process.env));
    assert.equal(outcome.ok, false);
    assert.equal(outcome.code, 'PREFLIGHT_BLOCKED');
  }
  const once = (await runPreflights(['up', 'db'], { up: pass, db: fail }, process.env));
  assert.deepEqual(once.results.map(r => [r.name, r.ok]), [['up', true], ['db', false]]);
});

test('deployed run: the cleanup ledger fails the run unless every created record is proven gone', async () => {
  const root = mkdtempSync(join(tmpdir(), 'qa-owns-'));
  try {
    const ledger = join(root, 'owns.jsonl');
    assert.equal(recordOwned('user', 'u1', ledger), true);
    assert.equal(recordOwned('order', 7, ledger), true);
    assert.equal(recordOwned('user', 'u2', undefined), false);
    const reporting = gone => ['node', '-e', `console.log(JSON.stringify({ gone: ${JSON.stringify(gone)}, residue: [] }))`];
    assert.deepEqual((await verifyCleanup(ledger, reporting(['user:u1', 'order:7']), process.env)), { ok: true, owned: 2 });
    for (const check of [reporting(['user:u1']), reporting([])]) {
      const outcome = (await verifyCleanup(ledger, check, process.env));
      assert.equal(outcome.ok, false);
      assert.match(outcome.reason, /^CLEANUP_UNVERIFIED/);
    }
    for (const check of [['node', '-e', 'process.exit(2)'], ['node', '-e', 'console.log("not json")']]) {
      assert.match((await verifyCleanup(ledger, check, process.env)).reason, /^CLEANUP_CHECK_INVALID/);
    }
    rmSync(ledger);
    assert.match((await verifyCleanup(ledger, reporting([]), process.env)).reason, /ledger is missing/);
    writeFileSync(ledger, 'not json\n');
    assert.match((await verifyCleanup(ledger, reporting([]), process.env)).reason, /unreadable/);
    writeFileSync(ledger, '{"kind":1}\n');
    assert.match((await verifyCleanup(ledger, reporting([]), process.env)).reason, /malformed/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

const SECRET_USER = 'svc-secret-user@corp.invalid';
const SECRET_PASSWORD = 'planted-password-9f3a';
const deployed = { staging: { origins: ['https://staging.example.invalid'], credentials: { identities: [{ userEnv: 'QA_U', passwordEnv: 'QA_P' }], deny: ['admin*'] }, cleanupCheck: ['node', 'cleanup.mjs'] } };
const ciEnv = { CI: 'true', QA_U: SECRET_USER, QA_P: SECRET_PASSWORD };
const deployedArgs = ['--base-url', 'https://staging.example.invalid', '--env', 'staging'];

function everything(root) {
  const out = [];
  const walk = dir => { for (const entry of readdirSync(dir, { withFileTypes: true })) { const path = join(dir, entry.name); if (entry.isDirectory()) walk(path); else out.push(readFileSync(path, 'utf8')); } };
  walk(root);
  return out.join('\n');
}

test('qa test on a deployed target refuses undeclared or non-CI identities and never prints a secret', () => {
  const undeclared = runProject({ environments: { staging: { origins: deployed.staging.origins } } });
  const declared = runProject({ environments: deployed });
  try {
    for (const [project, env] of [[undeclared, ciEnv], [declared, { ...ciEnv, CI: undefined }], [declared, { CI: 'true', QA_U: SECRET_USER }], [declared, { ...ciEnv, QA_U: 'ADMIN@corp.invalid' }]]) {
      const r = project.run(deployedArgs, env);
      assert.equal(r.status, 1);
      assert.match(r.stderr, /CREDENTIALS_NOT_FROM_CI/);
      assert.equal(project.has('compiled.marker'), false, 'a refused run starts no command');
      assert.doesNotMatch(r.stdout + r.stderr + everything(project.root), new RegExp(`${SECRET_PASSWORD}|${SECRET_USER}`));
    }
    const ok = declared.run(deployedArgs, ciEnv);
    assert.equal(ok.status, 0, ok.stderr);
    assert.doesNotMatch(ok.stdout + ok.stderr + everything(declared.root), new RegExp(`${SECRET_PASSWORD}|${SECRET_USER}`));
  } finally { for (const p of [undeclared, declared]) rmSync(p.root, { recursive: true, force: true }); }
});

test('qa test on a deployed target blocks (exit 2) when a preflight fails and starts no test', () => {
  const failing = { ...deployed.staging, preflights: ['ready'] };
  const project = runProject({ environments: { staging: failing }, checks: { ready: ['node', 'preflight.mjs'] } }, { other: { 'preflight.mjs': 'process.exit(4);' } });
  try {
    const r = project.run(deployedArgs, ciEnv);
    assert.equal(r.status, 2);
    assert.match(r.stderr, /PREFLIGHT_BLOCKED/);
    assert.equal(project.has('compiled.marker'), false);
    assert.equal(project.has('run-v1.json'), false);
    assert.equal(JSON.parse(project.read('preflights.json')).results[0].ok, false);
    const fixed = runProject({ environments: { staging: failing }, checks: { ready: ['node', 'preflight.mjs'] } }, { other: { 'preflight.mjs': 'process.exit(0);' } });
    try { assert.equal(fixed.run(deployedArgs, ciEnv).status, 0); } finally { rmSync(fixed.root, { recursive: true, force: true }); }
  } finally { rmSync(project.root, { recursive: true, force: true }); }
});

test('qa test on a deployed target fails when a created record is not proven gone', () => {
  const withCleanup = { ...deployed.staging, cleanupCheck: ['node', 'cleanup.mjs'] };
  const tests = `import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs'; appendFileSync(process.env.QA_OWNS_FILE, JSON.stringify({ kind: 'user', id: 'u1' }) + '\\n'); mkdirSync('qa-results', { recursive: true }); writeFileSync('qa-results/junit.xml', '<testsuite><testcase name="${ID}"/></testsuite>');`;
  const cleanup = gone => `console.log(JSON.stringify({ gone: ${JSON.stringify(gone)}, residue: [] }));`;
  const leaking = runProject({ environments: { staging: withCleanup } }, { tests, other: { 'cleanup.mjs': cleanup([]) } });
  const clean = runProject({ environments: { staging: withCleanup } }, { tests, other: { 'cleanup.mjs': cleanup(['user:u1']) } });
  try {
    const bad = leaking.run(deployedArgs, ciEnv);
    assert.equal(bad.status, 1);
    assert.match(bad.stderr, /CLEANUP_UNVERIFIED/);
    assert.equal(leaking.has('run-v1.json'), false, 'a leaking run leaves no run evidence for the gate to judge');
    assert.equal(clean.run(deployedArgs, ciEnv).status, 0);
    assert.equal(clean.has('run-v1.json'), true);
  } finally { for (const p of [leaking, clean]) rmSync(p.root, { recursive: true, force: true }); }
});

test('qa test on a deployed target verifies cleanup after a runner spawn error and still reports the runner error', () => {
  const withCleanup = { ...deployed.staging, cleanupCheck: ['node', 'cleanup.mjs'] };
  const record = `import { appendFileSync } from 'node:fs'; appendFileSync(process.env.QA_OWNS_FILE, JSON.stringify({ kind: 'user', id: 'u1' }) + '\\n');`;
  const cleanup = gone => `import { writeFileSync } from 'node:fs'; writeFileSync('cleanup-ran.marker', '1'); console.log(JSON.stringify({ gone: ${JSON.stringify(gone)}, residue: [] }));`;
  const cases = [
    ['missing test binary', { other: { 'compile.mjs': record } }, /ENOENT/],
  ];
  for (const [name, files, runnerError] of cases) {
    const patched = name === 'missing test binary' ? { other: { ...files.other, 'cleanup.mjs': cleanup(['user:u1']) } } : { ...files, other: { 'cleanup.mjs': cleanup(['user:u1']) } };
    const project = runProject({ environments: { staging: withCleanup }, ...(name === 'missing test binary' ? { testCommand: ['./no-such-runner'] } : {}) }, patched);
    const leaking = runProject({ environments: { staging: withCleanup }, ...(name === 'missing test binary' ? { testCommand: ['./no-such-runner'] } : {}) }, { ...patched, other: { ...patched.other, 'cleanup.mjs': cleanup([]) } });
    try {
      const r = project.run(deployedArgs, ciEnv);
      assert.notEqual(r.status, 0, name);
      assert.match(r.stderr, runnerError, `${name}: the original runner error is reported`);
      assert.equal(project.has('cleanup-ran.marker'), true, `${name}: the cleanup check was invoked`);
      assert.equal(project.has('run-v1.json'), false, name);
      const bad = leaking.run(deployedArgs, ciEnv);
      assert.equal(bad.status, 1, name);
      assert.match(bad.stderr, runnerError, `${name}: runner error kept beside the cleanup failure`);
      assert.match(bad.stderr, /CLEANUP_UNVERIFIED/, name);
    } finally { for (const p of [project, leaking]) rmSync(p.root, { recursive: true, force: true }); }
  }
});

const record = `import { appendFileSync } from 'node:fs'; appendFileSync(process.env.QA_OWNS_FILE, JSON.stringify({ kind: 'user', id: 'u1' }) + '\\n');`;
const writeJunit = `import { mkdirSync, writeFileSync } from 'node:fs'; mkdirSync('qa-results', { recursive: true }); writeFileSync('qa-results/junit.xml', '<testsuite><testcase name="${ID}"/></testsuite>');`;

test('a deployed environment without a cleanupCheck refuses to start, and readOnly is not an exemption', () => {
  for (const extra of [{}, { readOnly: true }, { cleanupCheck: [] }, { cleanupCheck: 'node cleanup.mjs' }]) {
    const project = runProject({ environments: { staging: { ...deployed.staging, cleanupCheck: undefined, ...extra } } });
    try {
      const r = project.run(deployedArgs, ciEnv);
      assert.equal(r.status, 1, JSON.stringify(extra));
      assert.match(r.stderr, /CLEANUP_CHECK_MISSING/);
      assert.equal(project.has('compiled.marker'), false, 'no command started');
      assert.equal(project.has('owns.jsonl'), false);
    } finally { rmSync(project.root, { recursive: true, force: true }); }
  }
});

test('the example config declares a cleanupCheck for every environment and no readOnly option', () => {
  const example = JSON.parse(readFileSync(resolve(import.meta.dirname, '../qa.config.example.json'), 'utf8'));
  const names = Object.keys(example.environments);
  assert.ok(names.includes('production') && names.includes('staging'));
  for (const name of names) {
    const env = example.environments[name];
    assert.ok(Array.isArray(env.cleanupCheck) && env.cleanupCheck.length > 0, `${name} declares a cleanupCheck`);
    assert.equal('readOnly' in env, false, `${name} has no readOnly option`);
  }
});

test("the example config's production environment fails a run that leaves a record, including after a runner spawn error", () => {
  const example = JSON.parse(readFileSync(resolve(import.meta.dirname, '../qa.config.example.json'), 'utf8'));
  const production = example.environments.production;
  const args = ['--base-url', production.origins[0], '--env', 'production'];
  const env = { CI: 'true', QA_PRODUCTION_USER: 'svc-prod@corp.invalid', QA_PRODUCTION_PASSWORD: 'pw-prod-9f' };
  const cleanup = gone => `console.log(JSON.stringify({ gone: ${JSON.stringify(gone)}, residue: [] }));`;
  const make = (tests, gone) => runProject({ environments: { production } }, { tests, other: { 'qa/cleanup-check.mjs': cleanup(gone) } });
  const overflow = `${record} process.stdout.write('x'.repeat(3 * 1024 * 1024));`;
  const cases = [
    ['leftover record', `${record} ${writeJunit}`, /CLEANUP_UNVERIFIED/],
    ['leftover record after a run that wrote no results', overflow, /CLEANUP_UNVERIFIED/],
  ];
  for (const [name, tests, expected] of cases) {
    const leaking = make(tests, []);
    try {
      const r = leaking.run(args, env);
      assert.equal(r.status, 1, name);
      assert.match(r.stderr, expected, name);
      assert.equal(leaking.has('run-v1.json'), false, name);
    } finally { rmSync(leaking.root, { recursive: true, force: true }); }
  }
  const clean = make(`${record} ${writeJunit}`, ['user:u1']);
  try { assert.equal(clean.run(args, env).status, 0); } finally { rmSync(clean.root, { recursive: true, force: true }); }
});

// A test that hangs after creating a record must still reach the cleanup check; timeouts of a second keep these fast.
const hang = `setInterval(() => {}, 1000);`;
const timed = extra => ({ ...deployed.staging, testTimeoutSeconds: 1, checkTimeoutSeconds: 1, ...extra });

test('a deployed test that hangs after creating a record is killed, the cleanup check still runs, and the run fails', () => {
  const pidFile = `import { writeFileSync } from 'node:fs'; writeFileSync('child.pid', String(process.pid));`;
  const recorded = `${pidFile} import { appendFileSync } from 'node:fs'; appendFileSync(process.env.QA_OWNS_FILE, JSON.stringify({ kind: 'user', id: 'u1' }) + '\\n'); ${hang}`;
  const unrecorded = `${pidFile} import { appendFileSync } from 'node:fs'; appendFileSync('target-state.txt', process.env.QA_RUN_ID + ':order-9\\n'); ${hang}`;
  const check = `import { existsSync, readFileSync, writeFileSync } from 'node:fs'; writeFileSync('cleanup-ran.marker', '1');
    const state = existsSync('target-state.txt') ? readFileSync('target-state.txt', 'utf8').split('\\n').filter(Boolean) : [];
    console.log(JSON.stringify({ gone: process.env.GONE ? ['user:u1'] : [], residue: state.filter(l => l.startsWith(process.env.QA_RUN_ID + ':')) }));`;
  const cases = [
    ['recorded record still on the target', recorded, /CLEANUP_UNVERIFIED/, {}],
    ['unrecorded tagged record on the target', unrecorded, /CLEANUP_UNVERIFIED.*residual record|run-.*order-9/s, {}],
    ['record cleaned up, the timeout alone fails the run', recorded, /TEST_TIMEOUT/, { GONE: '1' }],
  ];
  for (const [name, tests, expected, extraEnv] of cases) {
    const project = runProject({ environments: { staging: timed() } }, { tests, other: { 'cleanup.mjs': check } });
    try {
      const started = Date.now();
      const outcome = project.run([...deployedArgs, '--run-id', 'run-hang'], { ...ciEnv, ...extraEnv });
      assert.ok(Date.now() - started < 20000, `${name}: bounded wall time`);
      assert.equal(outcome.status, 1, `${name}: ${outcome.stderr}`);
      assert.match(outcome.stderr, expected, name);
      assert.equal(project.has('cleanup-ran.marker'), true, `${name}: cleanup check ran after the hang`);
      assert.equal(project.has('run-v1.json'), false, `${name}: no run evidence`);
      const pid = Number(project.read('child.pid'));
      assert.throws(() => process.kill(pid, 0), `${name}: the hung child was killed`);
      assert.doesNotMatch(outcome.stdout + outcome.stderr, new RegExp(`${SECRET_USER}|${SECRET_PASSWORD}`));
    } finally { rmSync(project.root, { recursive: true, force: true }); }
  }
  // A clean cleanup does not turn the timeout into a pass: TEST_TIMEOUT is reported and the exit is non-zero (third case above).
});

// A worker the command leaves behind (same process group) must be killed with it, or it can write to the target after the cleanup check.
const worker = `import { spawn } from 'node:child_process'; import { writeFileSync as saveWorkerPid } from 'node:fs';
  const w = spawn(process.execPath, ['-e', "setTimeout(() => require('node:fs').writeFileSync('late.marker', 'wrote after cleanup'), 1500)"], { stdio: 'ignore' });
  w.unref(); saveWorkerPid('worker.pid', String(w.pid));`;
const gone = pid => { try { process.kill(pid, 0); return false; } catch { return true; } };
const pause = ms => new Promise(done => setTimeout(done, ms));

test('a worker that outlives a timed-out test is killed with it and never writes after cleanup', async () => {
  const project = runProject({ environments: { staging: timed() } }, { tests: `${worker} ${hang}` });
  try {
    const outcome = project.run(deployedArgs, ciEnv);
    assert.equal(outcome.status, 1, outcome.stderr);
    assert.match(outcome.stderr, /TEST_TIMEOUT/);
    await pause(2500);
    assert.equal(project.has('late.marker'), false, 'the worker never wrote its marker');
    assert.equal(gone(Number(project.read('worker.pid'))), true, 'the worker process is gone');
  } finally { rmSync(project.root, { recursive: true, force: true }); }
});

test('a worker left behind by a test that exits normally is killed before the run is judged', async () => {
  const project = runProject({ environments: { staging: timed() } }, { tests: `${worker} ${writeJunit}` });
  try {
    const outcome = project.run(deployedArgs, ciEnv);
    assert.equal(outcome.status, 0, outcome.stderr);
    await pause(2500);
    assert.equal(project.has('late.marker'), false, 'the worker never wrote its marker');
    assert.equal(gone(Number(project.read('worker.pid'))), true, 'the worker process is gone');
  } finally { rmSync(project.root, { recursive: true, force: true }); }
});

test('a worker left behind by the cleanup check is killed too', async () => {
  const check = `${worker} console.log(JSON.stringify({ gone: [], residue: [] }));`;
  const project = runProject({ environments: { staging: timed() } }, { tests: writeJunit, other: { 'cleanup.mjs': check } });
  try {
    const outcome = project.run(deployedArgs, ciEnv);
    assert.equal(outcome.status, 0, outcome.stderr);
    await pause(2500);
    assert.equal(project.has('late.marker'), false, 'the worker never wrote its marker');
    assert.equal(gone(Number(project.read('worker.pid'))), true, 'the worker process is gone');
  } finally { rmSync(project.root, { recursive: true, force: true }); }
});

test('a discovery command that prints thousands of IDs and exits at once loses none of them', () => {
  const many = `for (let i = 0; i < 5000; i += 1) console.log('QAS-' + String(i).padStart(5, '0'));`;
  const project = runProject({ environments: { staging: timed() } }, { other: { 'discover.mjs': many } });
  try {
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const outcome = project.run(deployedArgs, ciEnv);
      assert.equal(outcome.status, 0, `attempt ${attempt}: ${outcome.stderr}`);
      assert.equal(JSON.parse(outcome.stdout).discoveredIds, 5000, `attempt ${attempt}: every ID was read`);
    }
  } finally { rmSync(project.root, { recursive: true, force: true }); }
});

test('a discovery output over the 10 MB cap fails clearly instead of judging on partial IDs', () => {
  const flood = `console.log('QAS-00001'); process.stdout.write('x'.repeat(11 * 1024 * 1024));`;
  const project = runProject({ environments: { staging: timed() } }, { other: { 'discover.mjs': flood } });
  try {
    const outcome = project.run(deployedArgs, ciEnv);
    assert.equal(outcome.status, 1, outcome.stderr);
    assert.match(outcome.stderr, /discovery output exceeded 10 MB/);
    assert.equal(project.has('run-v1.json'), false);
  } finally { rmSync(project.root, { recursive: true, force: true }); }
});

test('a hung cleanup check or preflight fails the run and is never a pass', () => {
  const hangingCheck = project => project.run([...deployedArgs], ciEnv);
  const cleanupHangs = runProject({ environments: { staging: timed() } }, { tests: writeJunit, other: { 'cleanup.mjs': hang } });
  const preflightHangs = runProject({ environments: { staging: timed({ preflights: ['up'] }) }, checks: { up: ['node', 'up.mjs'] } }, { other: { 'up.mjs': hang } });
  try {
    const bad = hangingCheck(cleanupHangs);
    assert.equal(bad.status, 1, bad.stderr);
    assert.match(bad.stderr, /CLEANUP_CHECK_INVALID.*timed out/);
    assert.equal(cleanupHangs.has('run-v1.json'), false);
    const blocked = hangingCheck(preflightHangs);
    assert.equal(blocked.status, 2, blocked.stderr);
    assert.match(blocked.stderr, /PREFLIGHT_BLOCKED.*timed out/);
    assert.equal(preflightHangs.has('compiled.marker'), false, 'no test command ran');
  } finally { for (const p of [cleanupHangs, preflightHangs]) rmSync(p.root, { recursive: true, force: true }); }
});

test('timeout overrides are validated before any test and the defaults are documented values', () => {
  assert.equal(DEFAULT_TEST_TIMEOUT_SECONDS, 45 * 60);
  assert.equal(DEFAULT_CHECK_TIMEOUT_SECONDS, 5 * 60);
  assert.deepEqual(resolveTimeouts({}), { ok: true, testMs: 45 * 60 * 1000, checkMs: 5 * 60 * 1000 });
  assert.deepEqual(resolveTimeouts({ testTimeoutSeconds: 90, checkTimeoutSeconds: 30 }), { ok: true, testMs: 90000, checkMs: 30000 });
  for (const bad of [0, -5, 1.5, '60', null, MAX_TIMEOUT_SECONDS + 1, Infinity, NaN]) {
    for (const key of ['testTimeoutSeconds', 'checkTimeoutSeconds']) {
      const outcome = resolveTimeouts({ [key]: bad });
      assert.equal(outcome.ok, false, `${key}=${String(bad)}`);
      assert.match(outcome.reason, /^TIMEOUT_CONFIG_INVALID/);
    }
  }
  const project = runProject({ environments: { staging: { ...deployed.staging, testTimeoutSeconds: 0 } } });
  try {
    const outcome = project.run(deployedArgs, ciEnv);
    assert.equal(outcome.status, 1);
    assert.match(outcome.stderr, /TIMEOUT_CONFIG_INVALID/);
    assert.equal(project.has('compiled.marker'), false);
  } finally { rmSync(project.root, { recursive: true, force: true }); }
});

test('an empty ledger still runs cleanupCheck, with the run ID and ledger path, and the run fails when the check reports residue', async () => {
  // The tests write to the "target" (a file) without calling recordOwned, tagged with the run ID; only the adopter's check can see it.
  const writeUnrecorded = `import { appendFileSync } from 'node:fs'; appendFileSync('target-state.txt', process.env.QA_RUN_ID + ':order-7\\n'); ${writeJunit}`;
  const check = `import { appendFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
    writeFileSync('check-env.json', JSON.stringify({ runId: process.env.QA_RUN_ID, ledger: process.env.QA_OWNS_FILE, ledgerBytes: readFileSync(process.env.QA_OWNS_FILE, 'utf8').length }));
    const state = existsSync('target-state.txt') ? readFileSync('target-state.txt', 'utf8').split('\\n').filter(Boolean) : [];
    console.log(JSON.stringify({ gone: [], residue: state.filter(line => line.startsWith(process.env.QA_RUN_ID + ':')) }));`;
  const leaking = runProject({ environments: { staging: deployed.staging } }, { tests: writeUnrecorded, other: { 'cleanup.mjs': check } });
  const clean = runProject({ environments: { staging: deployed.staging } }, { tests: writeJunit, other: { 'cleanup.mjs': check } });
  try {
    const bad = leaking.run([...deployedArgs, '--run-id', 'run-abc'], ciEnv);
    assert.equal(bad.status, 1);
    assert.match(bad.stderr, /CLEANUP_UNVERIFIED.*residual record/);
    assert.match(bad.stderr, /run-abc:order-7/);
    assert.equal(leaking.has('run-v1.json'), false);
    const seen = JSON.parse(leaking.read('check-env.json'));
    assert.equal(seen.runId, 'run-abc', 'the check receives the run ID');
    assert.equal(seen.ledgerBytes, 0, 'the ledger was empty, yet the check ran');
    assert.match(seen.ledger, /owns\.jsonl$/, 'the check receives the ledger path');
    const ok = clean.run(deployedArgs, ciEnv);
    assert.equal(ok.status, 0, ok.stderr);
    assert.match(JSON.parse(clean.read('check-env.json')).runId, /^[0-9a-f-]{36}$/, 'a run ID is generated when none is passed');
  } finally { for (const p of [leaking, clean]) rmSync(p.root, { recursive: true, force: true }); }
  assert.match((await verifyCleanup(join(tmpdir(), 'no-such-ledger-qa'), ['node', '-e', ''], process.env)).reason, /ledger is missing/);
});

test('a cleanup check result that is not a strict {gone, residue} object fails the run, even with an empty ledger', async () => {
  const root = mkdtempSync(join(tmpdir(), 'qa-strict-'));
  try {
    const ledger = join(root, 'owns.jsonl');
    writeFileSync(ledger, '');
    const printing = text => ['node', '-e', `console.log(${JSON.stringify(text)})`];
    const rejected = {
      'empty object': printing('{}'),
      'only gone': printing('{"gone":[]}'),
      'only residue': printing('{"residue":[]}'),
      'residue is a string': printing('{"gone":[],"residue":"x"}'),
      'gone is an object': printing('{"gone":{},"residue":[]}'),
      'non-string entries': printing('{"gone":[],"residue":[1]}'),
      'array result': printing('[]'),
      'null result': printing('null'),
      'non-JSON': printing('all clean'),
      'empty output': ['node', '-e', ''],
      'non-zero exit with valid JSON': ['node', '-e', 'console.log(JSON.stringify({ gone: [], residue: [] })); process.exit(3)'],
    };
    for (const [name, check] of Object.entries(rejected)) {
      const outcome = (await verifyCleanup(ledger, check, process.env));
      assert.equal(outcome.ok, false, name);
      assert.equal(outcome.code, 'CLEANUP_CHECK_INVALID', name);
      assert.match(outcome.reason, /^CLEANUP_CHECK_INVALID/, name);
    }
    assert.deepEqual((await verifyCleanup(ledger, printing('{"gone":[],"residue":[]}'), process.env)), { ok: true, owned: 0 });
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('qa test fails a deployed run whose cleanup check prints an invalid result, with an empty ledger', () => {
  for (const [name, body] of [['empty object', 'console.log("{}");'], ['wrong type', 'console.log(\'{"gone":[],"residue":"x"}\');'], ['non-JSON', 'console.log("ok");'], ['non-zero exit', 'process.exit(5);']]) {
    const project = runProject({ environments: { staging: deployed.staging } }, { other: { 'cleanup.mjs': body } });
    try {
      const r = project.run(deployedArgs, ciEnv);
      assert.equal(r.status, 1, name);
      assert.match(r.stderr, /CLEANUP_CHECK_INVALID/, name);
      assert.equal(project.has('run-v1.json'), false, name);
    } finally { rmSync(project.root, { recursive: true, force: true }); }
  }
});

test('a failed preflight exits before compile, discovery and the test command start, so nothing can be left behind', () => {
  const full = { ...deployed.staging, preflights: ['ready'] };
  const tests = `import { writeFileSync } from 'node:fs'; writeFileSync('tests-ran.marker', '1');`;
  const project = runProject({ environments: { staging: full }, checks: { ready: ['node', 'preflight.mjs'] } }, { tests, other: { 'preflight.mjs': 'process.exit(4);', 'cleanup.mjs': `import { writeFileSync } from 'node:fs'; writeFileSync('cleanup-ran.marker', '1'); console.log(JSON.stringify({ gone: [], residue: [] }));` } });
  try {
    const r = project.run(deployedArgs, ciEnv);
    assert.equal(r.status, 2);
    assert.match(r.stderr, /PREFLIGHT_BLOCKED/);
    for (const marker of ['compiled.marker', 'tests-ran.marker', 'run-v1.json']) assert.equal(project.has(marker), false, marker);
    assert.equal(readFileSync(join(import.meta.dirname, '../bin/qa.mjs'), 'utf8').indexOf('runPreflights('), readFileSync(join(import.meta.dirname, '../bin/qa.mjs'), 'utf8').lastIndexOf('runPreflights(') , 'one preflight call site');
    const source = readFileSync(join(import.meta.dirname, '../bin/qa.mjs'), 'utf8');
    assert.ok(source.indexOf('runPreflights(') < source.indexOf('execute(cfg.compileCommand)'), 'preflights run before the first runner command');
  } finally { rmSync(project.root, { recursive: true, force: true }); }
});

test('environment checks attach only to deployed targets', () => {
  const full = { ...deployed.staging, preflights: ['ready'], cleanupCheck: ['node', 'cleanup.mjs'] };
  const project = runProject({ environments: { staging: full }, checks: { ready: ['node', 'preflight.mjs'] } }, { other: { 'preflight.mjs': 'process.exit(9);', 'cleanup.mjs': 'process.exit(9);' } });
  try {
    for (const args of [['--env', 'staging'], ['--env', 'staging', '--base-url', 'http://localhost:3000'], []]) {
      const r = project.run(args, { CI: undefined });
      assert.equal(r.status, 0, `${args.join(' ')}: ${r.stderr}`);
      assert.equal(project.has('preflights.json'), false);
      assert.equal(project.has('owns.jsonl'), false);
    }
    // Positive control: the same declarations DO attach on a deployed target (non-loopback base URL).
    const control = runProject({ environments: { staging: full }, checks: { ready: ['node', 'preflight.mjs'] } }, { other: { 'preflight.mjs': 'process.exit(0);', 'cleanup.mjs': 'console.log(JSON.stringify({ gone: [], residue: [] }));' } });
    try {
      const r = control.run(deployedArgs, ciEnv);
      assert.equal(r.status, 0, r.stderr);
      assert.equal(control.has('preflights.json'), true);
      assert.equal(control.has('owns.jsonl'), true);
    } finally { rmSync(control.root, { recursive: true, force: true }); }
  } finally { rmSync(project.root, { recursive: true, force: true }); }
});

// --- Issue #148 items 1 and 2: skip calls reached through an import alias --------------------------------------

test('source precheck rejects pytest and unittest skip helpers reached through an import alias', () => {
  const rejected = {
    'from pytest import skip': 'from pytest import skip\nskip("later")\n',
    'from pytest import xfail': 'from pytest import xfail\nxfail("later")\n',
    'from pytest import importorskip': 'from pytest import importorskip\nimportorskip("module")\n',
    'import pytest as pt (pt.skip)': 'import pytest as pt\npt.skip("later")\n',
    'import pytest as pt (pt.mark.skipif)': 'import pytest as pt\n@pt.mark.skipif(True, reason="x")\ndef test_a(): pass\n',
    'from pytest import mark as m': 'from pytest import mark as m\n@m.skip\ndef test_a(): pass\n',
    'from unittest import skip as later': 'from unittest import skip as later\n@later("x")\nclass T: pass\n',
    'from unittest import (parenthesised)': 'from unittest import (skipIf,\n    expectedFailure)\n@expectedFailure\ndef test_a(): pass\n',
    'import unittest as ut': 'import unittest as ut\n@ut.skipUnless(False, "x")\nclass T: pass\n',
  };
  for (const [name, source] of Object.entries(rejected)) assert.equal(sourcePrecheck(source), false, name);
});

test('source precheck accepts helpers, assignments and plain references that only share a skip name', () => {
  const accepted = {
    'local helper': 'def skip(reason): return reason\nskip("not a runner skip")\n',
    'other module': 'from mylib import skip\nskip("x")\n',
    'plain reference after import': 'from pytest import skip\nreference = skip\n',
    'alias reference': 'from unittest import skip as later\nreference = later\n',
    'unrelated pytest alias member': 'import pytest as pt\nvalue = pt.fixture\n',
    'string and comment': 'from pytest import fixture\n# skip("x")\nnote = "xfail(1)"\n',
  };
  for (const [name, source] of Object.entries(accepted)) assert.equal(sourcePrecheck(source), true, name);
});

// --- Issue #148 items 3 and 4: destructured, assigned and wrapped skips ---------------------------------------

test('source precheck rejects a JS/TS skip reached by destructuring or by assigning the test object', () => {
  const rejected = {
    'const { skip } = test': "const { skip } = test;\nskip('later');\n",
    'const { skip: later } = test': "const { skip: later } = test;\nlater('x');\n",
    'const { fixme } = test': "const { fixme } = test;\nfixme();\n",
    'const { skip } = it': "const { skip } = it;\nskip();\n",
    'const { skip } = describe': "const { skip } = describe;\nskip('x', () => {});\n",
    'let { only } = test': "let { only } = test;\nonly('a', () => {});\n",
    'const t = test; t.skip': "const t = test;\nt.skip('x');\n",
    'const d = describe; d.skip': "const d = describe;\nd.skip('x', () => {});\n",
    'alias of an alias': "const t = test;\nconst u = t;\nu.fixme();\n",
    'a copy of a destructured skip': "const { skip } = test;\nconst later = skip;\nlater();\n",
    'let t; t = test': "let t;\nt = test;\nt.skip('x');\n",
    'var t; t = it': "var t;\nt = it;\nt.fixme();\n",
    't = describe after a declaration': "let t;\nt = describe;\nt.skip('x', () => {});\n",
    'a reassigned destructure target': "let s;\n({ skip: s } = test);\ns();\n",
    'an assignment followed by a comma and a test call': "let t;\nt = test, test('c', () => { t.skip(); });\n",
    'a parenthesised assignment': "let t;\n(t = test);\nt.skip();\n",
    'a sequence of assignments': "let t, u;\nt = test, u = it;\nu.skip();\n",
    'a default parameter (kept conservative)': "function f(t = test) { t.skip('x'); }\n",
    'a reassigned alias of an alias': "let t, u;\nt = test;\nu = t;\nu.skip();\n",
    'a reassigned copy of a skip callable': "const { skip } = test;\nlet later;\nlater = skip;\nlater();\n",
    'reassigned to another object afterwards (kept conservative)': "let t;\nt = test;\nt = other;\nt.skip('x');\n",
  };
  for (const [name, source] of Object.entries(rejected)) assert.equal(sourcePrecheck(source), false, name);
});

test('source precheck rejects a skip wrapped in a helper defined in the same file', () => {
  const rejected = {
    'function helper with test.skip': "function later() { test.skip(); }\ntest('a', () => { later(); });\n",
    'arrow helper with pytest.skip': "const later = () => pytest.skip('x')\n",
    'python def helper calling pytest.skip': "import pytest\ndef later():\n    pytest.skip()\ndef test_a():\n    later()\n",
    'python helper through an import alias': "from pytest import skip as s\ndef later():\n    s()\ndef test_a():\n    later()\n",
    'JS helper through a destructured skip': "const { skip } = test;\nfunction later() { skip(); }\ntest('a', () => { later(); });\n",
    'python copy of an imported skip': "from pytest import skip\nlater = skip\nlater('x')\n",
  };
  for (const [name, source] of Object.entries(rejected)) assert.equal(sourcePrecheck(source), false, name);
});

test('source precheck accepts same-name helpers, destructures from other objects and plain references', () => {
  const accepted = {
    'a helper named skip that only logs': "function skip(reason) { console.log(reason); }\nskip('not a runner skip');\n",
    'destructure from options': "const { skip } = options;\nskip('x');\n",
    'destructure of another property from test': "const { expect } = test;\nexpect(1).toBe(1);\n",
    'a plain reference after destructuring': "const { skip } = test;\nconst list = [skip];\n",
    'an alias of a non-test object': "const t = options;\nt.skip('x');\n",
    'a reassignment from options': "let t;\nt = options;\nt.skip('x');\n",
    'a reassignment from a call': "let t;\nt = makeThing();\nt.skip('x');\n",
    'a reassigned destructure from options': "let s;\n({ skip: s } = options);\ns();\n",
    'a property assignment named like the object': "holder.t = test;\nholder.t.step('a');\n",
    'a reassignment from options followed by a comma': "let t;\nt = options, test('c', () => { t.skip(); });\n",
    'a call argument assignment to a non-test value': "let t;\nf(t = 1, test);\nlog(t);\n",
    'a strict comparison followed by a comma': "const ok = (t === test, 1);\n",
    'an arrow function body': "const f = t => test;\nf(1);\n",
    'a comparison': "if (t == test) { log(t); }\n",
    'an alias of test used for something else': "const t = test;\nt.step('a', () => {});\n",
    'a string mentioning skip': "const note = 'const { skip } = test; skip()';\n",
    'a comment mentioning skip': "// const { skip } = test; skip();\nconst a = 1;\n",
    'a python helper that only logs': "def later():\n    print('x')\ndef test_a():\n    later()\n",
    'a python copy of a non-skip name': "from pytest import fixture\nlater = fixture\nlater('x')\n",
  };
  for (const [name, source] of Object.entries(accepted)) assert.equal(sourcePrecheck(source), true, name);
});

test('source precheck leaves the forms that need a parser unresolved, as documented', () => {
  const unresolved = {
    'a helper imported from another file': "import { later } from './helpers';\ntest('a', () => { later(); });\n",
    'computed property access': "test['sk' + 'ip']('x');\n",
    'computed destructuring': "const name = 'skip';\nconst { [name]: later } = test;\nlater();\n",
    'a skip passed as a value and called elsewhere': "const { skip } = test;\n[skip].forEach(fn => fn('x'));\n",
  };
  for (const [name, source] of Object.entries(unresolved)) assert.equal(sourcePrecheck(source), true, `${name} is a documented limit`);
  const gateRules = readFileSync(join(resolve(import.meta.dirname, '../../..'), 'references/gate-rules.md'), 'utf8');
  assert.match(gateRules, /imported from another file/);
  assert.match(gateRules, /computed property/);
});

// --- Documentation carries every rule -------------------------------------------------------------------------

test('skill and references state each ported rule and its reason code', () => {
  const skillset = resolve(import.meta.dirname, '../../..');
  const read = path => readFileSync(join(skillset, path), 'utf8');
  const gateRules = read('references/gate-rules.md');
  const runAndGate = read('templates/ai-pack/.agents/skills/run-and-gate/SKILL.md');
  for (const code of ['SANITY_CANARY_FAILED', 'TARGET_NOT_ALLOWED', 'CREDENTIALS_NOT_FROM_CI', 'PREFLIGHT_BLOCKED', 'CLEANUP_CHECK_MISSING', 'CLEANUP_UNVERIFIED']) {
    assert.ok(gateRules.includes(code), `gate-rules.md names ${code}`);
    assert.ok(runAndGate.includes(code), `run-and-gate names ${code}`);
  }
  assert.match(gateRules, /Bound tests/);
  assert.match(gateRules, /Limit of the ledger/);
  assert.match(gateRules, /CLEANUP_CHECK_INVALID/);
  assert.match(runAndGate, /CLEANUP_CHECK_INVALID/);
  assert.match(gateRules, /Preflight order/);
  assert.match(gateRules, /always runs, even when the ledger is empty/);
  assert.match(read('references/pitfalls.md'), /QA_RUN_ID/);
  assert.doesNotMatch(gateRules + runAndGate, /readOnly/);
  assert.match(read('SKILL.md'), /runnable test carries its tag/);
  assert.match(read('references/pitfalls.md'), /import alias/);
  assert.match(read('references/pitfalls.md'), /destructur/);
});

// The credential names come from the example config, never from a hard-coded copy.
const exampleConfig = JSON.parse(readFileSync(resolve(import.meta.dirname, '../qa.config.example.json'), 'utf8'));
const deployedEnvironments = Object.entries(exampleConfig.environments).map(([name, env]) => ({ name, names: env.credentials.identities.flatMap(i => [i.userEnv, i.passwordEnv]) }));
const templates = {
  'github-actions.yml': name => `: \${{ secrets.${name} }}`,
  'azure-pipelines.yml': name => `: $(${name})`,
};

/** The step block (the `qa.mjs test ... --env <env>` line and its env mapping) of a rendered release workflow. */
function releaseStep(text, env) {
  const lines = text.split('\n');
  const start = lines.findIndex(line => new RegExp(`qa\\.mjs test .*--env ${env}\\b`).test(line));
  if (start < 0) return '';
  const indent = lines[start].match(/^\s*/)[0].length;
  const end = lines.findIndex((line, i) => i > start && /^\s*- (?:run|script|name):/.test(line) && line.match(/^\s*/)[0].length <= indent);
  return lines.slice(start, end < 0 ? lines.length : end).join('\n');
}

/** Credential names of `env` that the rendered workflow does not map from a secret. */
function unmappedCredentials(file, text, env, names) {
  const step = releaseStep(text, env);
  return names.filter(name => !step.includes(`${name}${templates[file](name)}`));
}

test('every declared credential of every deployed environment is mapped from a secret in each rendered release workflow', () => {
  assert.ok(deployedEnvironments.length >= 2);
  for (const file of Object.keys(templates)) {
    const text = readFileSync(join(import.meta.dirname, '../ci', file), 'utf8');
    for (const { name, names } of deployedEnvironments) {
      assert.ok(releaseStep(text, name), `${file}: a release step for ${name}`);
      assert.deepEqual(unmappedCredentials(file, text, name, names), [], `${file}/${name}`);
      assert.match(releaseStep(text, name), /CI: 'true'/, `${file}/${name} sets CI`);
      assert.doesNotMatch(releaseStep(text, name), /\bset -x\b|\becho\b/, `${file}/${name} never echoes`);
    }
  }
});

test('removing one credential mapping from a release workflow makes the mapping check fail', () => {
  for (const file of Object.keys(templates)) {
    const text = readFileSync(join(import.meta.dirname, '../ci', file), 'utf8');
    for (const { name, names } of deployedEnvironments) {
      for (const missing of names) {
        const broken = text.split('\n').filter(line => !line.includes(`${missing}${templates[file](missing)}`)).join('\n');
        assert.notEqual(broken, text, `${file}: a mapping line for ${missing}`);
        assert.deepEqual(unmappedCredentials(file, broken, name, names), [missing], `${file}/${name}: ${missing}`);
      }
    }
  }
});

test('a deployed run with the declared credentials set passes preflight, reaches the cleanup check, and leaks no credential value', () => {
  const environment = { ...deployed.staging, preflights: ['ready'], cleanupCheck: ['node', 'cleanup.mjs'] };
  const needsCredentials = `process.exit(process.env.QA_U && process.env.QA_P ? 0 : 7);`;
  const tests = `${writeJunit} if (!process.env.QA_U || !process.env.QA_P) process.exit(9); writeFileSync('tests-saw-credentials.marker', '1');`;
  const cleanup = `import { writeFileSync } from 'node:fs'; writeFileSync('cleanup-ran.marker', '1'); console.log(JSON.stringify({ gone: [], residue: [] }));`;
  const files = { tests, other: { 'preflight.mjs': needsCredentials, 'cleanup.mjs': cleanup } };
  const project = runProject({ environments: { staging: environment }, checks: { ready: ['node', 'preflight.mjs'] } }, files);
  const without = runProject({ environments: { staging: environment }, checks: { ready: ['node', 'preflight.mjs'] } }, files);
  try {
    const r = project.run(deployedArgs, ciEnv);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(project.has('tests-saw-credentials.marker'), true, 'the tests received the credentials');
    assert.equal(project.has('cleanup-ran.marker'), true, 'the run reached the cleanup check');
    assert.equal(JSON.parse(project.read('preflights.json')).ok, true);
    const everythingWritten = r.stdout + r.stderr + everything(project.root);
    assert.doesNotMatch(everythingWritten, new RegExp(`${SECRET_PASSWORD}|${SECRET_USER}`), 'no credential value in output, logs, run-v1.json or evidence files');
    assert.equal(project.has('run-v1.json'), true);
    // Without the mapping (the old templates) the same run stops before any test.
    const blocked = without.run(deployedArgs, { CI: 'true' });
    assert.equal(blocked.status, 1);
    assert.match(blocked.stderr, /CREDENTIALS_NOT_FROM_CI/);
    assert.equal(without.has('cleanup-ran.marker'), false);
  } finally { for (const p of [project, without]) rmSync(p.root, { recursive: true, force: true }); }
});
