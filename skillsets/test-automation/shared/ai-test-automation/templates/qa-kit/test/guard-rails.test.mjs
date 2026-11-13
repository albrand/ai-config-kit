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
const { resolveCredentials, runPreflights, verifyCleanup, wildcardMatch } = await load('deployed-run');
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

test('deployed run: a missing prerequisite reports PREFLIGHT_BLOCKED, never a pass', () => {
  const pass = ['node', '-e', 'process.exit(0)'];
  const fail = ['node', '-e', 'process.exit(3)'];
  assert.equal(runPreflights(['up'], { up: pass }, process.env).ok, true);
  for (const checks of [{ up: fail }, {}, { up: [] }]) {
    const outcome = runPreflights(['up'], checks, process.env);
    assert.equal(outcome.ok, false);
    assert.equal(outcome.code, 'PREFLIGHT_BLOCKED');
  }
  const once = runPreflights(['up', 'db'], { up: pass, db: fail }, process.env);
  assert.deepEqual(once.results.map(r => [r.name, r.ok]), [['up', true], ['db', false]]);
});

test('deployed run: the cleanup ledger fails the run unless every created record is proven gone', () => {
  const root = mkdtempSync(join(tmpdir(), 'qa-owns-'));
  try {
    const ledger = join(root, 'owns.jsonl');
    assert.equal(recordOwned('user', 'u1', ledger), true);
    assert.equal(recordOwned('order', 7, ledger), true);
    assert.equal(recordOwned('user', 'u2', undefined), false);
    const reporting = gone => ['node', '-e', `console.log(JSON.stringify({ gone: ${JSON.stringify(gone)} }))`];
    assert.deepEqual(verifyCleanup(ledger, reporting(['user:u1', 'order:7']), process.env), { ok: true, owned: 2 });
    for (const check of [reporting(['user:u1']), reporting([]), ['node', '-e', 'process.exit(2)'], ['node', '-e', 'console.log("not json")']]) {
      const outcome = verifyCleanup(ledger, check, process.env);
      assert.equal(outcome.ok, false);
      assert.match(outcome.reason, /^CLEANUP_UNVERIFIED/);
    }
    rmSync(ledger);
    assert.match(verifyCleanup(ledger, reporting([]), process.env).reason, /ledger is missing/);
    writeFileSync(ledger, 'not json\n');
    assert.match(verifyCleanup(ledger, reporting([]), process.env).reason, /unreadable/);
    writeFileSync(ledger, '{"kind":1}\n');
    assert.match(verifyCleanup(ledger, reporting([]), process.env).reason, /malformed/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

const SECRET_USER = 'svc-secret-user@corp.invalid';
const SECRET_PASSWORD = 'planted-password-9f3a';
const deployed = { staging: { origins: ['https://staging.example.invalid'], credentials: { identities: [{ userEnv: 'QA_U', passwordEnv: 'QA_P' }], deny: ['admin*'] }, readOnly: true } };
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
  const withCleanup = { ...deployed.staging, readOnly: undefined, cleanupCheck: ['node', 'cleanup.mjs'] };
  const tests = `import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs'; appendFileSync(process.env.QA_OWNS_FILE, JSON.stringify({ kind: 'user', id: 'u1' }) + '\\n'); mkdirSync('qa-results', { recursive: true }); writeFileSync('qa-results/junit.xml', '<testsuite><testcase name="${ID}"/></testsuite>');`;
  const cleanup = gone => `console.log(JSON.stringify({ gone: ${JSON.stringify(gone)} }));`;
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
  const withCleanup = { ...deployed.staging, readOnly: undefined, cleanupCheck: ['node', 'cleanup.mjs'] };
  const record = `import { appendFileSync } from 'node:fs'; appendFileSync(process.env.QA_OWNS_FILE, JSON.stringify({ kind: 'user', id: 'u1' }) + '\\n');`;
  const cleanup = gone => `import { writeFileSync } from 'node:fs'; writeFileSync('cleanup-ran.marker', '1'); console.log(JSON.stringify({ gone: ${JSON.stringify(gone)} }));`;
  const overflow = `${record} process.stdout.write('x'.repeat(3 * 1024 * 1024));`;
  const cases = [
    ['maxBuffer overflow', { tests: overflow }, /ENOBUFS/],
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

test('a deployed environment that declares neither cleanupCheck nor readOnly refuses to start', () => {
  const noCleanup = { ...deployed.staging, readOnly: undefined };
  const project = runProject({ environments: { staging: noCleanup } });
  try {
    const r = project.run(deployedArgs, ciEnv);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /CLEANUP_CHECK_MISSING/);
    assert.equal(project.has('compiled.marker'), false, 'no command started');
    assert.equal(project.has('owns.jsonl'), false);
    const both = runProject({ environments: { staging: { ...noCleanup, readOnly: true, cleanupCheck: ['node', 'c.mjs'] } } });
    try {
      const b = both.run(deployedArgs, ciEnv);
      assert.equal(b.status, 1);
      assert.match(b.stderr, /CLEANUP_CHECK_MISSING/);
    } finally { rmSync(both.root, { recursive: true, force: true }); }
  } finally { rmSync(project.root, { recursive: true, force: true }); }
});

test('the example config declares cleanupCheck or readOnly for every environment', () => {
  const example = JSON.parse(readFileSync(resolve(import.meta.dirname, '../qa.config.example.json'), 'utf8'));
  const names = Object.keys(example.environments);
  assert.ok(names.includes('production') && names.includes('staging'));
  for (const name of names) {
    const env = example.environments[name];
    assert.ok(Array.isArray(env.cleanupCheck) || env.readOnly === true, `${name} declares a cleanup check or readOnly`);
  }
});

test("the example config's production environment fails a run that leaves a record, including after a runner spawn error", () => {
  const example = JSON.parse(readFileSync(resolve(import.meta.dirname, '../qa.config.example.json'), 'utf8'));
  const production = example.environments.production;
  const args = ['--base-url', production.origins[0], '--env', 'production'];
  const env = { CI: 'true', QA_PRODUCTION_USER: 'svc-prod@corp.invalid', QA_PRODUCTION_PASSWORD: 'pw-prod-9f' };
  const cleanup = gone => `console.log(JSON.stringify({ gone: ${JSON.stringify(gone)} }));`;
  const make = (tests, gone) => runProject({ environments: { production } }, { tests, other: { 'qa/cleanup-check.mjs': cleanup(gone) } });
  const overflow = `${record} process.stdout.write('x'.repeat(3 * 1024 * 1024));`;
  const cases = [
    ['leftover record', `${record} ${writeJunit}`, /CLEANUP_UNVERIFIED/],
    ['leftover record after a runner spawn error', overflow, /CLEANUP_UNVERIFIED/],
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

test('a read-only deployed environment fails when any record is reported to the ledger', () => {
  const readOnly = { ...deployed.staging, readOnly: true };
  const silent = runProject({ environments: { staging: readOnly } }, { tests: writeJunit });
  const writing = runProject({ environments: { staging: readOnly } }, { tests: `${record} ${writeJunit}` });
  try {
    const ok = silent.run(deployedArgs, ciEnv);
    assert.equal(ok.status, 0, ok.stderr);
    assert.equal(silent.has('run-v1.json'), true);
    const bad = writing.run(deployedArgs, ciEnv);
    assert.equal(bad.status, 1);
    assert.match(bad.stderr, /CLEANUP_UNVERIFIED.*read-only environment/);
    assert.equal(writing.has('run-v1.json'), false);
  } finally { for (const p of [silent, writing]) rmSync(p.root, { recursive: true, force: true }); }
  assert.match(verifyCleanup(join(tmpdir(), 'no-such-ledger-qa'), null, process.env).reason, /ledger is missing/);
});

test('environment checks attach only to deployed targets', () => {
  const full = { ...deployed.staging, readOnly: undefined, preflights: ['ready'], cleanupCheck: ['node', 'cleanup.mjs'] };
  const project = runProject({ environments: { staging: full }, checks: { ready: ['node', 'preflight.mjs'] } }, { other: { 'preflight.mjs': 'process.exit(9);', 'cleanup.mjs': 'process.exit(9);' } });
  try {
    for (const args of [['--env', 'staging'], ['--env', 'staging', '--base-url', 'http://localhost:3000'], []]) {
      const r = project.run(args, { CI: undefined });
      assert.equal(r.status, 0, `${args.join(' ')}: ${r.stderr}`);
      assert.equal(project.has('preflights.json'), false);
      assert.equal(project.has('owns.jsonl'), false);
    }
    // Positive control: the same declarations DO attach on a deployed target (non-loopback base URL).
    const control = runProject({ environments: { staging: full }, checks: { ready: ['node', 'preflight.mjs'] } }, { other: { 'preflight.mjs': 'process.exit(0);', 'cleanup.mjs': 'console.log(JSON.stringify({ gone: [] }));' } });
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
  assert.match(read('SKILL.md'), /runnable test carries its tag/);
  assert.match(read('references/pitfalls.md'), /import alias/);
});

test('CI release templates name the environment and set CI with every deployed qa test', () => {
  for (const file of ['github-actions.yml', 'azure-pipelines.yml']) {
    const lines = readFileSync(join(import.meta.dirname, '../ci', file), 'utf8').split('\n');
    const deployedRuns = lines.map((line, i) => [line, lines[i + 1] ?? '']).filter(([line]) => /qa\.mjs test .*--base-url/.test(line));
    assert.equal(deployedRuns.length, 2, file);
    for (const [line, next] of deployedRuns) {
      assert.match(line, /--env (?:staging|production)\b/, `${file}: ${line.trim()}`);
      assert.match(next, /env: \{ CI: 'true' \}/, file);
    }
  }
});
