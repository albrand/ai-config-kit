import { readFileSync } from 'node:fs';
import { expectedLines, mockEncodesAnswer } from './behavior-rules.mjs';
import { tokenize } from './scenario-check.mjs';

const VACUOUS = /\b(?:expect\s*\(\s*true\s*\)|toBeTruthy\s*\(|assert\.ok\s*\(\s*true\s*\)|expect\.[\w$]+\s*\)\s*\.toBeTruthy|\.toBeDefined\s*\(\s*\))/;

export function validateSourceAssertions(source, scenario) {
  if (!scenario || scenario.kind !== 'automated') return { ok: true, reason: 'n/a' };
  const code = tokenize(source);
  if (VACUOUS.test(code)) return { ok: false, reason: 'automation uses vacuous assertion (truthy/true/defined-only)' };
  if (mockEncodesAnswer(source)) return { ok: false, reason: 'automation mock encodes the answer instead of letting app logic decide' };
  const missing = expectedLines(scenario.expected).filter(line => {
    const needle = line.length > 48 ? line.slice(0, 48) : line;
    return !source.includes(needle);
  });
  if (missing.length) return { ok: false, reason: `unasserted expected line(s): ${missing.join(' | ')}` };
  return { ok: true, reason: 'assertions bound to expected lines' };
}

export function validateSourcesForScenarios(sources, scenariosById, changedIds) {
  const rows = [];
  for (const path of sources) {
    const source = readFileSync(path, 'utf8');
    const ids = [...new Set(source.match(/QAS-[\w-]+-\d{2,}/g) ?? [])];
    for (const id of ids) {
      if (!changedIds.has(id)) continue;
      const scenario = scenariosById.get(id);
      if (!scenario) continue;
      const check = validateSourceAssertions(source, scenario);
      if (!check.ok) rows.push({ id, path, ok: false, reason: check.reason });
    }
  }
  return rows;
}
