#!/usr/bin/env node
import { readFileSync, writeFileSync, cpSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, resolve, isAbsolute, relative, sep } from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { readdirSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { parseAllureResults, parseJunitXml, parsePlaywrightJson, parseTrx } from '../lib/results/parsers.mjs';
import { boardAdapter } from '../lib/boards/index.mjs';
import { scenarioCheck, sourceFilePrecheck } from '../lib/scenario-check.mjs';
import { judge, parseArgs } from '../lib/gate.mjs';
import { html, markdown, reportBlocks, reportMarker, reportRows } from '../lib/report.mjs';
import { validatePublishPayload } from '../lib/publish-payload.mjs';

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
    let linked = args.item ?? [];
    if (!linked.length) {
      if (process.env.SYSTEM_PULLREQUEST_PULLREQUESTID && process.env.SYSTEM_ACCESSTOKEN) {
        const collection = process.env.SYSTEM_COLLECTIONURI;
        const project = encodeURIComponent(process.env.SYSTEM_TEAMPROJECT ?? '');
        const repo = encodeURIComponent(process.env.BUILD_REPOSITORY_ID ?? '');
        const endpoint = `${collection}${project}/_apis/git/repositories/${repo}/pullRequests/${process.env.SYSTEM_PULLREQUEST_PULLREQUESTID}/workitems?api-version=7.1`;
        const response = await fetch(endpoint, { headers: { authorization: `Bearer ${process.env.SYSTEM_ACCESSTOKEN}`, accept: 'application/json' } });
        if (!response.ok) throw new Error(`Azure PR work-item lookup failed: HTTP ${response.status}`);
        const data = await response.json();
        linked = (data.value ?? []).map(item => String(item.id));
      }
    }
    if (!linked.length) {
      const sourceText = last('linked-text') ? readFileSync(last('linked-text'), 'utf8') : (process.env.GITHUB_EVENT_PATH && existsSync(process.env.GITHUB_EVENT_PATH) ? readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8') : '');
      let searchable = sourceText;
      try { const event = JSON.parse(sourceText); searchable = `${event.pull_request?.title ?? ''}\n${event.pull_request?.body ?? ''}\n${event.inputs?.work_items ?? ''}`; } catch { /* caller supplied plain text */ }
      const pattern = new RegExp(cfg.workItemPattern ?? '\\b[A-Z][A-Z0-9]+-\\d+\\b', 'g');
      linked = [...new Set(searchable.match(pattern) ?? [])];
    }
    if (!linked.length) throw new Error('plan found no linked work-item IDs; pass --item repeatedly or provide a PR event body');
    const scenarioPath = last('file', config().scenarioFile ?? 'qa/scenarios.json');
    const current = scenariosFrom(last('scenarios', scenarioPath));
    const oldDocument = last('base-scenarios') ? json(last('base-scenarios')) : JSON.parse(execFileSync('git', ['show', `${base}:${scenarioPath}`], { encoding: 'utf8' }));
    const old = unwrap(oldDocument).map(scenario => ({ ...scenario, ...(scenario.workItemId || !oldDocument.workItemId ? {} : { workItemId: oldDocument.workItemId }) }));
    const oldIds = new Set(old.map(s => s.id));
    const scenarioIds = [...new Set([...current.map(s => s.id), ...old.map(s => s.id)])];
    const related = [...(args.related ?? []), ...(args.delivered ?? [])];
    const token = cfg.boardReadTokenEnv ? process.env[cfg.boardReadTokenEnv] : (cfg.boardTokenEnv ? process.env[cfg.boardTokenEnv] : undefined);
    const authorization = cfg.boardAuthorizationEnv ? process.env[cfg.boardAuthorizationEnv] : undefined;
    if (!token && !authorization) throw new Error(`plan requires read-only board credentials via ${cfg.boardTokenEnv ?? cfg.boardAuthorizationEnv ?? 'board auth config'}`);
    const adapter = boardAdapter(cfg.board, { baseUrl: cfg.boardUrl, repo: cfg.repo, token, authorization, dryRun: false });
    const workItems = [];
    for (const [id, relation] of [...linked.map(id => [id, 'linked']), ...related.map(id => [id, 'related'])]) {
      const response = await adapter.read(id);
      const data = response.data;
      const revision = data?.rev ?? data?.fields?.updated ?? data?.updatedAt ?? data?.updated_at ?? data?.data?.issue?.updatedAt ?? args.revision?.at(-1) ?? 'unknown';
      workItems.push({ id, revision, relation });
    }
    const plan = { kind: 'plan', schemaVersion: 1, baseSha, headSha, items: workItems.map(item => ({ ...item, scenarioIds: current.filter(s => s.workItemId === item.id || s.id.startsWith(`QAS-${item.id}-`)).map(s => s.id), linkedItems: linked.filter(id => id !== item.id) })), scenarioIds, createdAt: new Date().toISOString() };
    plan.items.push(...old.map(s => ({ id: s.workItemId ?? s.id.split('-').slice(1, -1).join('-'), revision: 'base', relation: 'regression', scenarioIds: [s.id] })));
    plan.regressionIds = [...oldIds];
    if (last('output')) writeJson(last('output'), plan);
    console.log(JSON.stringify(plan, null, 2));
  } else if (command === 'validate-publish-payload') {
    const metadata = json(last('metadata', 'metadata.json'));
    const verdict = json(last('verdict', 'verdict.json'));
    const result = validatePublishPayload(metadata, verdict);
    const expectedCommit = last('expected-commit');
    if (expectedCommit && metadata.commit !== expectedCommit) result.errors.push('artifact commit does not match trusted workflow metadata');
    result.ok = result.errors.length === 0;
    console.log(JSON.stringify(result, null, 2));
    if (!result.ok) process.exitCode = 1;
  } else if (command === 'judge') {
    const scenarios = scenariosFrom(last('scenarios', config().scenarioFile ?? 'qa/scenarios.json'));
    const results = readResults(last('results', 'results.json'));
    const baseScenarios = last('base-scenarios') ? unwrap(json(last('base-scenarios'))) : [];
    const plan = last('plan') ? json(last('plan')) : {};
    const baseIds = [...new Set([...(last('base-ids') ? json(last('base-ids')) : baseScenarios.map(s => s.id)), ...(plan.regressionIds ?? [])])];
    const rows = judge(scenarios, results, baseIds, plan);
    const runDoc = Array.isArray(results) ? { results } : results;
    const output = { kind: 'verdict', schemaVersion: 1, planHash: plan.planHash ?? digest(plan), runHash: digest(runDoc), overall: rows.some(r => r.verdict === 'FAILED') ? 'FAIL' : rows.some(r => r.verdict === 'BLOCKED') ? 'BLOCKED' : 'PASS', rows: rows.map(({ id, ...row }) => ({ scenarioId: id, ...row })), createdAt: new Date().toISOString() };
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
      const verdict = json(last('verdict'));
      const valid = validatePublishPayload({ kind: 'qa-publish-artifact', schemaVersion: 1, commit: last('commit', process.env.GITHUB_SHA ?? ''), runId: last('run-id', process.env.GITHUB_RUN_ID ?? 'local') }, verdict);
      if (!valid.ok) throw new Error(`refusing to publish invalid verdict: ${valid.errors.join('; ')}`);
      const artifact = last('artifact');
      if (!artifact) throw new Error('board report requires --artifact URL confirmed by the artifact publisher');
      const grouped = new Map();
      for (const row of verdict.rows ?? []) if (row.workItem) grouped.set(row.workItem, [...(grouped.get(row.workItem) ?? []), row]);
      if (!grouped.size) throw new Error('verdict has no work-item IDs to report');
      const receipts = [];
      for (const [item, rows] of grouped) {
        const body = `QA verdict ${verdict.overall} for ${last('commit', process.env.GITHUB_SHA ?? 'local')}\nArtifact: ${artifact}\n\n${rows.map(row => `${row.scenarioId}: ${row.verdict} — ${row.reason}`).join('\n')}`;
        const marker = reportMarker(item, last('commit', process.env.GITHUB_SHA ?? 'local'), body);
        const result = await adapter.comment(item, body, marker);
        receipts.push({ workItem: item, marker, confirmed: Boolean(apply && (result.duplicate || (result.status >= 200 && result.status < 300))), status: result.status, duplicate: Boolean(result.duplicate), request: redactedRequest(result) });
      }
      console.log(JSON.stringify({ mode: apply ? 'apply' : 'dry-run', receipts }, null, 2));
      if (last('receipt-output')) writeJson(last('receipt-output'), { schemaVersion: 1, kind: 'board-post-receipt', receipts });
      if (apply && receipts.some(receipt => !receipt.confirmed)) process.exitCode = 1;
    } else {
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
    }
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
  } else if (command === 'check-scenarios') {
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
    for (const path of unsafe) result.push({ id: path, ok: false, reason: 'source pre-check found disabled/skipped test pattern' });
    console.log(JSON.stringify(result, null, 2));
    if (result.some(row => !row.ok)) process.exitCode = 1;
  } else if (command === 'test') {
    const cfg = config();
    for (const field of ['compileCommand', 'discoverCommand', 'testCommand']) if (!Array.isArray(cfg[field]) || !cfg[field].length) throw new Error(`qa.config.json must define ${field} as [executable, ...args]`);
    const execute = command => {
      const [exe, ...argv] = command;
      const result = spawnSync(exe, argv, { encoding: 'utf8', env: { PATH: process.env.PATH, CI: 'true' }, shell: false });
      if (result.error) throw result.error;
      return { status: result.status ?? 1, stdout: result.stdout ?? '', stderr: result.stderr ?? '' };
    };
    const compiled = execute(cfg.compileCommand);
    if (compiled.status !== 0) throw new Error(`compile command failed with exit ${compiled.status}`);
    const discovery = execute(cfg.discoverCommand);
    if (discovery.status !== 0) throw new Error(`discovery command failed with exit ${discovery.status}`);
    const discoveredIds = [...new Set(discovery.stdout.match(/QAS-[\w-]+/g) ?? [])];
    if (!discoveredIds.length) throw new Error('discovery command returned no stable QAS IDs');
    const execution = execute(cfg.testCommand);
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
    const run = { kind: 'run', schemaVersion: 1, planHash: last('plan-hash', planPath && existsSync(planPath) ? digest(json(planPath)) : `sha256:${'0'.repeat(64)}`), commitSha: process.env.GITHUB_SHA ?? process.env.BUILD_SOURCEVERSION ?? git('rev-parse', 'HEAD'), runner: cfg.runner ?? format, compiled: true, discoveredIds, results: results.map(row => ({ ...row, scenarioId: row.scenario_id ?? row.scenarioId, scenario_id: undefined })), processExitCode: execution.status, sourceArtifacts: [resultPath] };
    const output = last('output', cfg.resultsFile ?? 'run-v1.json');
    writeJson(output, run);
    console.log(JSON.stringify({ run: output, compiled: true, discoveredIds: discoveredIds.length, results: results.length, testExitCode: execution.status }, null, 2));
    if (execution.status !== 0) process.exitCode = execution.status;
  } else {
    console.error('usage: qa.mjs plan|judge|report|board|install-authoritative|check-scenarios|test');
    process.exitCode = 2;
  }
} catch (error) {
  console.error(`qa: ${error.message}`);
  process.exitCode = 1;
}
