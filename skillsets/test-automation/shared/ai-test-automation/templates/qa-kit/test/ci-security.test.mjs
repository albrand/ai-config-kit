import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

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
    if (/\$\{\{\s*secrets\.|\b(?:QA_BOARD_\w*TOKEN|QA_READ_TOKEN|SYSTEM_ACCESSTOKEN)\b/.test(job.source)) {
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

test('trusted publishers consume validated data without checking out or installing PR code', () => {
  assert.match(githubYaml, /pull_request_target:/, 'the privileged planner workflow definition must come from the base branch');
  assert.match(githubPublisher, /workflow_run:/);
  assert.match(githubPublisher, /issues:\s*write/);
  assert.match(githubPublisher, /pull-requests:\s*write/);
  assert.match(githubPublisher, /validate-publish-payload/);
  assert.doesNotMatch(githubPublisher, /github\.event\.pull_request\.head\.sha|npm\s+(?:ci|install)/);
  assert.match(azurePublisher, /resources:\s*\n\s*pipelines:/);
  assert.match(azurePublisher, /validate-publish-payload/);
  assert.match(azurePublisher, /QA_BOARD_WRITE_TOKEN/);
  assert.doesNotMatch(azurePublisher, /checkout:\s*self[\s\S]{0,100}?pullRequest|npm\s+(?:ci|install)/i);
});
