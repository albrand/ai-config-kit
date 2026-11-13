import { tokenize } from './lang-tokenize.mjs';

// A scenario counts as bound to a test file only when a RUNNABLE test carries its tag the way a runner sees it:
// the title of a test/it/describe/specify call, or a `scenario_id` label call. Comments, unrelated string
// literals and skipped tests never bind. Matching is by whole ID, so QAS-WI-1-01 never binds QAS-WI-1-010.
const ID = /QAS-[\w-]*?-\d{2,}(?![\w-])/g;
const idsIn = text => new Set(text.match(ID) ?? []);

// Only runnable callee shapes: a skip/fixme/todo/fail/only/slow modifier does not match, so those calls never bind.
const TITLE_CALL = /(?<![\w$.])(?:test|it|describe|specify)(?:\s*\.\s*(?:describe|serial|parallel))*\s*\(/g;
// `scenario_id` label calls: Allure JS/Python/.NET runtime APIs and the JUnit annotation.
const LABEL_CALL = /(?<![\w$])(?:(?:allure|Allure|AllureApi)\s*\.\s*)?(?:label|AddLabel|LabelAnnotation)\s*\(/g;
// Attribute-style display names (xUnit/NUnit/JUnit) carry the tag in DisplayName / @DisplayName.
const DISPLAY_NAME = /(?:\bDisplayName\s*=|@\s*DisplayName\s*\()/g;

function closeParen(code, open) {
  let depth = 0;
  for (let i = open; i < code.length; i++) {
    if (code[i] === '(') depth++;
    else if (code[i] === ')' && --depth === 0) return i;
  }
  return -1;
}

function firstLiteral(source, from) {
  const m = /^\s*(["'`])((?:\\.|(?!\1)[^\\])*)\1/.exec(source.slice(from));
  return m ? m[2] : '';
}

export function scenarioIdsInBoundTestFile(source) {
  const code = tokenize(source);
  const bound = new Set();
  for (const m of code.matchAll(TITLE_CALL)) {
    for (const id of idsIn(firstLiteral(source, m.index + m[0].length))) bound.add(id);
  }
  for (const m of code.matchAll(LABEL_CALL)) {
    const open = m.index + m[0].length - 1;
    const close = closeParen(code, open);
    if (close < 0) continue;
    const args = source.slice(open + 1, close);
    if (!/["'`]scenario_id["'`]/.test(args) && !/\bname\s*=\s*["']scenario_id["']/.test(args)) continue;
    for (const id of idsIn(args)) bound.add(id);
  }
  for (const m of code.matchAll(DISPLAY_NAME)) {
    const literal = firstLiteral(source, m.index + m[0].length);
    // A Skip/Ignore/Disabled marker on this line or the line above disables the case.
    const lineStart = code.lastIndexOf('\n', m.index) + 1;
    const prevStart = code.lastIndexOf('\n', lineStart - 2) + 1;
    const lineEnd = code.indexOf('\n', m.index) < 0 ? code.length : code.indexOf('\n', m.index);
    if (/\b(?:Skip|Ignore|Disabled)\b/.test(code.slice(prevStart, lineEnd))) continue;
    for (const id of idsIn(literal)) bound.add(id);
  }
  return bound;
}

/** Changed automated scenarios no source file binds through a runnable test. */
export function unboundScenarios(sources, scenarios) {
  const bound = new Set();
  for (const source of sources) for (const id of scenarioIdsInBoundTestFile(source)) bound.add(id);
  return scenarios.filter(s => s.kind === 'automated' && !bound.has(s.id)).map(s => s.id);
}
