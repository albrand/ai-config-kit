import { createHash } from 'node:crypto';

const esc = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
const cell = value => String(value ?? '').replaceAll('|', '\\|').replaceAll('\n', '<br>');

/** Merge planned scope with verdicts; absence of a verdict is represented as BLOCKED, never omitted. */
export function reportRows(scope, verdicts, { posted = false } = {}) {
  const byId = new Map(verdicts.map(row => [row.id ?? row.scenario_id, row]));
  return scope.map(item => {
    const result = byId.get(item.id) ?? {};
    const reason = result.reason ?? 'no verdict/evidence row produced';
    const screenshot = result.screenshot ?? result.screenshotUrl ?? item.screenshot ?? '';
    let verdict = result.verdict ?? 'BLOCKED';
    let finalReason = reason;
    if (item.surface === 'browser' && result.executed && !screenshot) { verdict = 'BLOCKED'; finalReason = 'required browser screenshot missing'; }
    if (result.attachmentFailed || result.uploadConfirmed === false || result.missingToken) { verdict = 'BLOCKED'; finalReason = result.missingToken ? 'attachment token missing' : result.uploadConfirmed === false ? 'attachment upload not confirmed' : 'attachment failed'; }
    if (!posted && !['FAILED', 'BLOCKED'].includes(verdict)) { verdict = 'BLOCKED'; finalReason = 'report posting not confirmed'; }
    return { id: item.id, workItem: item.workItem ?? item.workItemId ?? '', scope: item.scope ?? (item.regression ? 'regression' : item.linked ? 'linked' : 'related'), linkedItems: item.linkedItems ?? [], verdict, reason: finalReason, screenshot: screenshot || '', executed: Boolean(result.executed) };
  });
}

export function reportMarker(workItem, commit, content) {
  const hash = createHash('sha256').update(String(content).replace(/\r\n/g, '\n').trim()).digest('hex').slice(0, 16);
  return `<!-- qa-report:${workItem}:${commit}:${hash} -->`;
}

export function markdown(rows) {
  return ['| Work item | Scope | Scenario | Verdict | Reason | Screenshot |', '|---|---|---|---|---|---|', ...rows.map(row => `| ${cell(row.workItem)} | ${cell(row.scope)} | ${cell(row.id)} | ${cell(row.verdict)} | ${cell(row.reason)} | ${cell(row.screenshot)} |`)].join('\n');
}

export function html(rows) {
  return `<!doctype html><meta charset="utf-8"><title>QA scenario report</title><table><thead><tr><th>Work item</th><th>Scope</th><th>Scenario</th><th>Verdict</th><th>Reason</th><th>Screenshot</th></tr></thead><tbody>${rows.map(row => { const url = /^https:\/\//i.test(row.screenshot ?? '') ? `<a href="${esc(row.screenshot)}">evidence</a>` : esc(row.screenshot || '—'); return `<tr><td>${esc(row.workItem)}</td><td>${esc(row.scope)}</td><td>${esc(row.id)}</td><td>${esc(row.verdict)}</td><td>${esc(row.reason)}</td><td>${url}</td></tr>`; }).join('')}</tbody></table>`;
}

export function reportBlocks(rows) { return rows.some(row => ['FAILED', 'BLOCKED'].includes(row.verdict)); }
