import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Credential variables a deployed environment declares. A release job that names a protected `environment:` may map exactly these from secrets.
const exampleConfig = JSON.parse(readFileSync(new URL('../qa.config.example.json', import.meta.url), 'utf8'));
const credentialNames = new Set(Object.values(exampleConfig.environments).flatMap(env => (env.credentials?.identities ?? []).flatMap(i => [i.userEnv, i.passwordEnv])));

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

function auditGithub(source) {
  const top = source.slice(0, source.indexOf('\njobs:\n'));
  const globalWrite = /\b(?:contents|issues|pull-requests|actions):\s*write\b|permissions:\s*write-all/.test(top);
  const violations = [];
  for (const job of githubJobs(source)) {
    const prCheckout = githubCheckoutSteps(job.source).some(step => /github\.event\.pull_request\.head\.sha/.test(step));
    const runsPrCode = prCheckout || /\bnpm\s+(?:ci|install)\b/.test(job.source)
      || /qa(?:-authority)?\/qa\/bin\/qa\.mjs\s+test\b/.test(job.source)
      || (job.name === 'qa-repository-pr' && /github\.event_name\s*==\s*'pull_request'/.test(job.source));
    if (!runsPrCode) continue;
    if (globalWrite || /\b(?:contents|issues|pull-requests|actions):\s*write\b|permissions:\s*write-all/.test(job.source)) {
      violations.push(`github:${job.name}: write permission`);
    }
    for (const step of githubCheckoutSteps(job.source)) {
      if (!/persist-credentials:\s*false/.test(step)) violations.push(`github:${job.name}: checkout credentials not disabled`);
    }
    const allowed = /^    environment:\s*\S+/m.test(job.source)
      ? job.source.replace(/\$\{\{\s*secrets\.(\w+)\s*\}\}/g, (match, name) => (credentialNames.has(name) ? '' : match))
      : job.source;
    if (/\$\{\{\s*secrets\.|\b(?:QA_BOARD_\w*TOKEN|QA_READ_TOKEN|SYSTEM_ACCESSTOKEN)\b/.test(allowed)) {
      violations.push(`github:${job.name}: secret or board token reaches PR-code job`);
    }
  }
  return violations;
}

function auditAzure(source) {
  const violations = [];
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
  assert.match(auditGithub(unprotected).join(';'), /github:staging: secret/);
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
