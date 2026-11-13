#!/usr/bin/env node
import { readFileSync, writeFileSync, cpSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, resolve, isAbsolute, relative, sep } from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { readdirSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { parseAllureResults, parseJunitXml, parsePlaywrightJson, parseTrx } from '../lib/results/parsers.mjs';
import { boardAdapter } from '../lib/boards/index.mjs';
import { scenarioCheck, sourceFilePrecheck } from '../lib/scenario-check.mjs';
import { validateSourcesForScenarios } from '../lib/source-assertions.mjs';
import { judge, parseArgs } from '../lib/gate.mjs';
import { html, markdown, reportBlocks, reportMarker, reportRows } from '../lib/report.mjs';
import { publishFromEvidence, recomputeTrustedVerdict, validatePublishPayload } from '../lib/publish-payload.mjs';
import { buildPlan, extractWorkItemHints, resolveBoardAssociations } from '../lib/associations.mjs';
import { checkAiPack, installAiPack } from '../lib/ai-pack.mjs';
import { assertCanaries, runCanaries } from '../lib/canaries.mjs';
import { unboundScenarios } from '../lib/bound-tests.mjs';
import { checkTarget } from '../lib/target-allowlist.mjs';
import { checkCleanupDeclared, resolveCredentials, runPreflights, verifyCleanup } from '../lib/deployed-run.mjs';

const [command, ...rest] = process.argv.slice(2);
const args = parseArgs(rest);
const last = (key, fallback) => args[key]?.at(-1) ?? fallback;
const json = path => JSON.parse(readFileSync(path, 'utf8'));
const digest = value => `sha256:${createHash('sha256').update(JSON.stringify(value)).digest('hex')}`;
const readResults = path => {
  if (!statSync(path).isDirectory()) return json(path);
  const candidate = readdirSync(path, { withFileTypes: true }).find(entry => entry.isFile() && /^run-v1\.json$/.test(entry.name));
  if (!candidate) throw new Error(`results directory has no run-v1.json: ${path}`);
  return json(resolve(path, candidate.name));
};
const writeJson = (path, value) => { mkdirSync(dirname(resolve(path)), { recursive: true }); writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`); };
const unwrap = value => Array.isArray(value) ? value : value.scenarios ?? value;
const scenariosFrom = path => {
  const document = json(path);
  const owner = document.workItemId ?? document.id;
  return unwrap(document).map(scenario => ({ ...scenario, ...(scenario.workItemId || !owner ? {} : { workItemId: owner }) }));
};
const config = () => json(last('config', existsSync('qa/qa.config.json') ? 'qa/qa.config.json' : 'qa.config.json'));
const safeRelative = path => { if (isAbsolute(path) || path.split(/[\\/]/).includes('..')) throw new Error(`unsafe relative path: ${path}`); return path; };
const redactedRequest = result => {
  if (!result?.request) return undefined;
  const request = structuredClone(result.request);
  if (request.headers?.authorization) request.headers.authorization = '[redacted]';
  return request;
};
const git = (...argv) => execFileSync('git', argv, { encoding: 'utf8' }).trim();

try {
  if (command === 'plan') {
    const cfg = config();
    const base = last('base', 'origin/main');
    const head = last('head', process.env.GITHUB_SHA ?? git('rev-parse', 'HEAD'));
    const baseSha = /^[a-f0-9]{40}$/i.test(base) ? base : git('rev-parse', `${base}^{commit}`);
    const headSha = /^[a-f0-9]{40}$/i.test(head) ? head : git('rev-parse', `${head}^{commit}`);
    const eventPath = process.env.GITHUB_EVENT_PATH && existsSync(process.env.GITHUB_EVENT_PATH) ? process.env.GITHUB_EVENT_PATH : null;
    const event = eventPath ? json(eventPath) : {};
    const pullRequest = event.pull_request ?? {};
    const linkedText = last('linked-text') ? readFileSync(last('linked-text'), 'utf8') : '';
    let freeText = linkedText;
    if (last('linked-text')) {
      try { const parsed = JSON.parse(linkedText); freeText = `${parsed.title ?? ''}\n${parsed.body ?? ''}\n${parsed.branch ?? ''}`; } catch { /* plain text is also a hint source */ }
    }
    const hints = [...new Set([
      ...(args.item ?? []), ...(args.related ?? []), ...(args.delivered ?? []),
      ...extractWorkItemHints([pullRequest.title, pullRequest.body, pullRequest.head?.ref, event.inputs?.work_items, freeText, process.env.SYSTEM_PULLREQUEST_SOURCEBRANCH], cfg.workItemPattern)
    ])];
    const change = {
      id: String(last('pull-request') || pullRequest.number || process.env.SYSTEM_PULLREQUEST_PULLREQUESTID || ''),
      number: last('pull-request') || pullRequest.number,
      pullRequestId: last('pull-request') || process.env.SYSTEM_PULLREQUEST_PULLREQUESTID,
      url: last('change-url') || pullRequest.html_url || pullRequest.url || process.env.SYSTEM_PULLREQUEST_PULLREQUESTURI,
      owner: last('change-owner') || event.repository?.owner?.login,
      repositoryName: last('change-repository') || event.repository?.name,
      project: last('change-project') || process.env.SYSTEM_TEAMPROJECT,
      repositoryId: last('change-repository-id') || process.env.BUILD_REPOSITORY_ID,
      organizationUrl: last('organization-url') || process.env.SYSTEM_COLLECTIONURI,
      branch: pullRequest.head?.ref ?? process.env.SYSTEM_PULLREQUEST_SOURCEBRANCH,
      title: pullRequest.title,
      hints
    };
    const scenarioPath = last('file', config().scenarioFile ?? 'qa/scenarios.json');
    const current = scenariosFrom(last('scenarios', scenarioPath));
    const oldDocument = last('base-scenarios') ? json(last('base-scenarios')) : JSON.parse(execFileSync('git', ['show', `${base}:${scenarioPath}`], { encoding: 'utf8' }));
    const old = unwrap(oldDocument).map(scenario => ({ ...scenario, ...(scenario.workItemId || !oldDocument.workItemId ? {} : { workItemId: oldDocument.workItemId }) }));
    const token = cfg.boardReadTokenEnv ? process.env[cfg.boardReadTokenEnv] : (cfg.boardTokenEnv ? process.env[cfg.boardTokenEnv] : undefined);
    const authorization = cfg.boardAuthorizationEnv ? process.env[cfg.boardAuthorizationEnv] : undefined;
    if (!token && !authorization) throw new Error(`plan requires read-only board credentials via ${cfg.boardTokenEnv ?? cfg.boardAuthorizationEnv ?? 'board auth config'}`);
    const adapter = boardAdapter(cfg.board, { baseUrl: cfg.boardUrl, repo: cfg.repo, token, authorization, dryRun: false });
    if (typeof adapter.linkedItemsForChange !== 'function') throw new Error(`board adapter ${cfg.board} does not implement linkedItemsForChange(change)`);
    const association = resolveBoardAssociations(hints, await adapter.linkedItemsForChange(change));
    const plan = await buildPlan({ association, currentScenarios: current, baseScenarios: old, baseSha, headSha, readWorkItem: async id => {
      const response = await adapter.read(id);
      return { ...response.data, revision: args.revision?.at(-1) };
    } });
    if (last('output')) writeJson(last('output'), plan);
    console.log(JSON.stringify(plan, null, 2));
  } else if (command === 'validate-publish-payload') {
    const metadata = json(last('metadata', 'metadata.json'));
    const verdict = json(last('verdict', 'verdict.json'));
    const plan = json(last('plan', 'plan.json'));
    const result = validatePublishPayload(metadata, verdict, plan);
    const expectedCommit = last('expected-commit');
    if (expectedCommit && metadata.commit !== expectedCommit) result.errors.push('artifact commit does not match trusted workflow metadata');
    result.ok = result.errors.length === 0;
    console.log(JSON.stringify(result, null, 2));
    if (!result.ok) process.exitCode = 1;
  } else if (command === 'canary') {
    const outcome = runCanaries();
    console.log(JSON.stringify(outcome, null, 2));
    if (!outcome.ok) process.exitCode = 1;
  } else if (command === 'judge') {
    assertCanaries();
    const scenarios = scenariosFrom(last('scenarios', config().scenarioFile ?? 'qa/scenarios.json'));
    const results = readResults(last('results', 'results.json'));
    const baseScenarios = last('base-scenarios') ? unwrap(json(last('base-scenarios'))) : [];
    const plan = last('plan') ? json(last('plan')) : {};
    const baseIds = [...new Set([...(last('base-ids') ? json(last('base-ids')) : baseScenarios.map(s => s.id)), ...(plan.regressionIds ?? [])])];
    const baseResultsPath = last('base-results');
    const baseResults = baseResultsPath && existsSync(baseResultsPath) ? readResults(baseResultsPath) : null;
    const rows = judge(scenarios, results, baseIds, plan, { baseResults, baseScenarios });
    const runDoc = Array.isArray(results) ? { results } : results;
    const output = last('plan')
      ? recomputeTrustedVerdict(plan, scenarios, results)
      : { kind: 'verdict', schemaVersion: 1, planHash: plan.planHash ?? digest(plan), runHash: digest(runDoc), overall: rows.some(r => r.verdict === 'FAILED' || (r.verdict === 'BUG' && r.blocking)) ? 'FAIL' : rows.some(r => r.verdict === 'BLOCKED') ? 'BLOCKED' : 'PASS', rows: rows.map(({ id, ...row }) => ({ scenarioId: id, ...row })) };
    console.log(JSON.stringify(output, null, 2));
    if (last('output')) writeJson(last('output'), output);
    if (output.overall !== 'PASS') process.exitCode = 1;
  } else if (command === 'report') {
    const verdictDoc = last('verdict') ? json(last('verdict')) : null;
    const scenarios = verdictDoc ? (last('scenarios') ? scenariosFrom(last('scenarios')) : verdictDoc.rows.map(r => ({ id: r.scenarioId ?? r.id, workItemId: r.workItem, scope: r.scope, surface: r.surface }))) : scenariosFrom(last('scenarios', config().scenarioFile ?? 'qa/scenarios.json'));
    const verdicts = verdictDoc?.rows?.map(row => ({ ...row, id: row.scenarioId ?? row.id, verdict: row.verdict, reason: row.reason })) ?? judge(scenarios, json(last('results', 'results.json')));
    const receiptPath = last('post-receipt');
    const receipt = receiptPath ? json(receiptPath) : null;
    const expectedItems = [...new Set(verdicts.map(row => row.workItem).filter(Boolean))];
    const confirmedItems = new Set((receipt?.receipts ?? []).filter(item => item.confirmed === true && /^<!-- qa-report:[^:]+:[^:]+:[a-f0-9]{16} -->$/.test(item.marker ?? '')).map(item => String(item.workItem)));
    const posted = expectedItems.length > 0 && expectedItems.every(item => confirmedItems.has(String(item)));
    const rows = reportRows(scenarios, verdicts, { posted });
    const output = last('output', 'qa-report');
    mkdirSync(output, { recursive: true });
    writeFileSync(`${output}/report.md`, `${markdown(rows)}\n`);
    writeFileSync(`${output}/report.html`, html(rows));
    writeJson(`${output}/report.json`, { rows, marker: reportMarker(last('work-item', 'multiple'), last('commit', process.env.GITHUB_SHA ?? 'local'), markdown(rows)), posted });
    console.log(JSON.stringify({ output, rows: rows.length, blocked: reportBlocks(rows), posted }, null, 2));
    if (reportBlocks(rows) && !args['allow-pending']) process.exitCode = 1;
  } else if (command === 'board') {
    const cfg = config();
    const apply = args.apply === true;
    const tokenName = cfg.boardTokenEnv ?? 'QA_BOARD_TOKEN';
    const token = process.env[tokenName];
    const authorization = cfg.boardAuthorizationEnv ? process.env[cfg.boardAuthorizationEnv] : undefined;
    if (apply && !token && !authorization) throw new Error(`board token missing from ${tokenName}`);
    const adapter = boardAdapter(cfg.board, { baseUrl: cfg.boardUrl, repo: cfg.repo, token, authorization, dryRun: !apply });
    const [action, id, ...values] = args._;
    if (!action) throw new Error('board requires operation and work-item id');
    if (action === 'report') {
      throw new Error('board report no longer accepts verdict artifacts; use publish-evidence with trusted plan and raw runner results');
    }
    if (!id) throw new Error('board requires operation and work-item id');
    const body = values.join(' ');
    const marker = reportMarker(id, last('commit', process.env.GITHUB_SHA ?? 'local'), body);
    const methods = {
        read: () => adapter.read(id),
        comment: () => adapter.comment(id, body, marker),
        attach: () => adapter.attach(id, body.startsWith('{') ? JSON.parse(body) : body),
        transition: () => adapter.transition(id, values[0], last('revision')),
        linkPr: () => adapter.linkPr(id, values[0], `PR ${last('commit', process.env.GITHUB_SHA ?? 'local')}`)
      };
    if (!methods[action]) throw new Error(`unsupported board operation: ${action}`);
    const result = await methods[action]();
    const safe = structuredClone(result);
    if (safe.request?.headers?.authorization) safe.request.headers.authorization = '[redacted]';
    console.log(JSON.stringify({ mode: apply ? 'apply' : 'dry-run', result: safe }, null, 2));
  } else if (command === 'publish-evidence') {
    assertCanaries();
    const cfg = config();
    const apply = args.apply === true;
    const tokenName = cfg.boardTokenEnv ?? 'QA_BOARD_TOKEN';
    const token = process.env[tokenName];
    const authorization = cfg.boardAuthorizationEnv ? process.env[cfg.boardAuthorizationEnv] : undefined;
    if (apply && !token && !authorization) throw new Error(`board token missing from ${tokenName}`);
    const metadata = json(last('metadata', 'metadata.json'));
    const plan = json(last('plan', 'plan.json'));
    const scenarios = scenariosFrom(last('scenarios', cfg.scenarioFile ?? 'qa/scenarios.json'));
    const run = readResults(last('results', 'run-v1.json'));
    const adapter = boardAdapter(cfg.board, { baseUrl: cfg.boardUrl, repo: cfg.repo, token, authorization, dryRun: !apply });
    const result = await publishFromEvidence(adapter, {
      metadata, plan, scenarios, run, artifactUrl: last('artifact'),
      expectedCommit: last('expected-commit'), expectedRunId: last('expected-run-id')
    });
    console.log(JSON.stringify({ mode: apply ? 'apply' : 'dry-run', ...result }, null, 2));
    if (last('receipt-output')) writeJson(last('receipt-output'), { schemaVersion: 1, kind: 'board-post-receipt', receipts: result.receipts });
    if (apply && result.receipts.some(receipt => !receipt.confirmed)) process.exitCode = 1;
  } else if (command === 'install-authoritative') {
    const source = last('source'); const target = last('target', '.');
    if (!source) throw new Error('install-authoritative requires --source');
    const sourceConfig = json(last('config', `${source}/qa.config.json`));
    const paths = sourceConfig.authoritativePaths ?? ['scenarios.json', 'tests'];
    const installed = [];
    for (const raw of paths) {
      const rel = safeRelative(raw); const from = resolve(source, rel); const to = resolve(target, rel);
      if (existsSync(from)) { cpSync(from, to, { recursive: true, force: true }); installed.push(rel); }
    }
    console.log(JSON.stringify({ installed, ignoredBranchCopies: paths }, null, 2));
  } else if (command === 'merge-base') {
    // Resolve the real common ancestor of head and target (never the target tip) and optionally verify a recorded SHA.
    const repo = resolve(last('repo', '.'));
    const head = last('head');
    const target = last('target');
    if (!head || !target) throw new Error('merge-base requires --head and --target');
    let resolved;
    try { resolved = execFileSync('git', ['-C', repo, 'merge-base', head, target], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim(); }
    catch { throw new Error(`NOT RUN: cannot resolve the merge base of ${head} and ${target}; fetch full history (fetch-depth 0)`); }
    const expected = last('expect');
    if (expected !== undefined && expected !== resolved) {
      throw new Error(`NOT RUN: the base run was recorded at ${expected || '(missing baseSha)'} but the merge base of head and target is ${resolved}; the red-on-base proof is for the wrong commit`);
    }
    const output = last('output');
    if (output) writeJson(output, { kind: 'base-meta', baseSha: resolved, head, target });
    console.log(resolved);
  } else if (command === 'ai-pack') {
    const target = resolve(last('target', '.'));
    if (args.check) {
      const drift = checkAiPack(target);
      console.log(JSON.stringify({ ok: drift.length === 0, drift }, null, 2));
      if (drift.length) process.exitCode = 1;
    } else if (args.write) {
      const written = installAiPack(target);
      console.log(JSON.stringify({ ok: true, target, written }, null, 2));
    } else throw new Error('ai-pack requires --write or --check');
  } else if (command === 'check-scenarios') {
    assertCanaries();
    const scenarioPath = last('file', config().scenarioFile ?? 'qa/scenarios.json');
    const head = unwrap(json(last('head', scenarioPath)));
    const baseRef = last('base');
    if (!baseRef) throw new Error('check-scenarios requires --base <git-ref>');
    const resultsFile = last('results'); if (!resultsFile) throw new Error('check-scenarios requires --results <run-v1.json>');
    const file = safeRelative(scenarioPath);
    const base = unwrap(JSON.parse(execFileSync('git', ['show', `${baseRef}:${file}`], { encoding: 'utf8' })));
    const run = json(resultsFile);
    const sources = args.source ?? [];
    const unsafe = sources.filter(path => !sourceFilePrecheck(path));
    const result = scenarioCheck(head, base, run);
    const headById = new Map(head.map(s => [s.id, s]));
    const changedIds = new Set(result.filter(r => r.changed && r.id.startsWith('QAS-')).map(r => r.id));
    for (const row of validateSourcesForScenarios(sources, headById, changedIds)) result.push({ id: row.id, ok: row.ok, changed: true, reason: row.reason });
    // A changed automated scenario counts as bound only when a runnable test in a --source file carries its tag.
    if (sources.length) {
      const sourceTexts = sources.map(path => readFileSync(path, 'utf8'));
      const changedAutomated = head.filter(s => changedIds.has(s.id) && s.kind === 'automated');
      for (const id of unboundScenarios(sourceTexts, changedAutomated)) result.push({ id, ok: false, changed: true, reason: 'no runnable test in the --source files carries the scenario tag' });
    }
    for (const path of unsafe) result.push({ id: path, ok: false, reason: 'source pre-check found disabled/skipped test pattern' });
    console.log(JSON.stringify(result, null, 2));
    if (result.some(row => !row.ok)) process.exitCode = 1;
  } else if (command === 'test') {
    const cfg = config();
    for (const field of ['compileCommand', 'discoverCommand', 'testCommand']) if (!Array.isArray(cfg[field]) || !cfg[field].length) throw new Error(`qa.config.json must define ${field} as [executable, ...args]`);
    // Target allowlist first: a non-loopback base URL must belong to an environment that declares its origins.
    const baseUrl = last('base-url', cfg.baseUrl);
    const environment = last('env', cfg.environment ?? 'local');
    const target = checkTarget({ baseUrl, environment, config: cfg });
    if (!target.ok) throw new Error(target.reason);
    const testEnv = { PATH: process.env.PATH, CI: 'true', ...(baseUrl ? { QA_BASE_URL: baseUrl } : {}) };
    const envConfig = cfg.environments?.[environment] ?? {};
    const ownsFile = resolve(last('owns-output', 'owns.jsonl'));
    // Environment safeguards apply only to a deployed target; local, loopback and no-base-URL runs are unchanged.
    if (target.deployed) {
      const credentials = resolveCredentials(envConfig, process.env, { allowLocalCredentials: args['allow-local-credentials'] === true });
      if (!credentials.ok) throw new Error(credentials.reason);
      for (const name of credentials.names) testEnv[name] = process.env[name];
      // A deployed run must say how created data is cleaned up (cleanupCheck) or declare itself read-only; refuse before any test.
      const declared = checkCleanupDeclared(envConfig);
      if (!declared.ok) throw new Error(declared.reason);
      const preflight = runPreflights(envConfig.preflights ?? [], cfg.checks, testEnv);
      if (envConfig.preflights?.length) writeJson(last('preflights-output', 'preflights.json'), preflight);
      if (!preflight.ok) {
        console.error(`qa: PREFLIGHT_BLOCKED: ${preflight.results.filter(r => !r.ok).map(r => `${r.name} (${r.reason})`).join(', ')}; no test was run`);
        process.exitCode = 2;
        process.exit();
      }
      writeFileSync(ownsFile, '');
      testEnv.QA_OWNS_FILE = ownsFile;
    }
    const execute = command => {
      const [exe, ...argv] = command;
      const result = spawnSync(exe, argv, { encoding: 'utf8', env: testEnv, shell: false });
      if (result.error) throw result.error;
      return { status: result.status ?? 1, stdout: result.stdout ?? '', stderr: result.stderr ?? '' };
    };
    let discoveredIds;
    let execution;
    let runnerError = null;
    try {
      const compiled = execute(cfg.compileCommand);
      if (compiled.status !== 0) throw new Error(`compile command failed with exit ${compiled.status}`);
      const discovery = execute(cfg.discoverCommand);
      if (discovery.status !== 0) throw new Error(`discovery command failed with exit ${discovery.status}`);
      discoveredIds = [...new Set(discovery.stdout.match(/QAS-[\w-]+/g) ?? [])];
      if (!discoveredIds.length) throw new Error('discovery command returned no stable QAS IDs');
      execution = execute(cfg.testCommand);
    } catch (error) { runnerError = error; }
    // Every record the run created must be proven gone on every exit path, including a runner spawn error.
    if (target.deployed) {
      const cleanup = verifyCleanup(ownsFile, envConfig.readOnly === true ? null : envConfig.cleanupCheck, testEnv);
      if (!cleanup.ok) {
        if (runnerError) console.error(`qa: ${runnerError.message}`);
        console.error(`qa: ${cleanup.reason}; no run evidence was written`);
        process.exit(1);
      }
    }
    if (runnerError) throw runnerError;
    const format = cfg.resultFormat;
    const resultPath = cfg.resultPath;
    if (!format || !resultPath) throw new Error('qa.config.json must define resultFormat and resultPath');
    let results;
    if (format === 'junit') results = parseJunitXml(readFileSync(resultPath, 'utf8'));
    else if (format === 'trx') results = parseTrx(readFileSync(resultPath, 'utf8'));
    else if (format === 'playwright') results = parsePlaywrightJson(json(resultPath));
    else if (format === 'allure') results = parseAllureResults(readdirSync(resultPath).filter(name => name.endsWith('-result.json')).map(name => json(resolve(resultPath, name))));
    else throw new Error(`unsupported resultFormat: ${format}`);
    const planPath = last('plan');
    const run = { kind: 'run', schemaVersion: 1, planHash: last('plan-hash', planPath && existsSync(planPath) ? digest(json(planPath)) : `sha256:${'0'.repeat(64)}`), commitSha: last('commit', process.env.GITHUB_HEAD_SHA ?? process.env.GITHUB_SHA ?? process.env.BUILD_SOURCEVERSION ?? git('rev-parse', 'HEAD')), runner: cfg.runner ?? format, compiled: true, discoveredIds, results: results.map(row => ({ ...row, scenarioId: row.scenario_id ?? row.scenarioId, scenario_id: undefined })), processExitCode: execution.status, sourceArtifacts: [resultPath] };
    const output = last('output', cfg.resultsFile ?? 'run-v1.json');
    writeJson(output, run);
    console.log(JSON.stringify({ run: output, compiled: true, discoveredIds: discoveredIds.length, results: results.length, testExitCode: execution.status }, null, 2));
    if (execution.status !== 0) process.exitCode = execution.status;
  } else {
    console.error('usage: qa.mjs plan|judge|report|board|publish-evidence|install-authoritative|check-scenarios|test|merge-base|ai-pack|canary');
    process.exitCode = 2;
  }
} catch (error) {
  console.error(`qa: ${error.message}`);
  process.exitCode = 1;
}
