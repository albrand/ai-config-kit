import { readFileSync } from 'node:fs';
import { expectedLines, mockEncodesAnswer } from './behavior-rules.mjs';
import { tokenize } from './scenario-check.mjs';
import {
  isVisibilityOnlyExpect,
  scenarioLineIdPrefix,
  visualSourceViolations,
} from './visual-source-check.mjs';

const VACUOUS = /\b(?:expect\s*\(\s*true\s*\)|toBeTruthy\s*\(|assert\.ok\s*\(\s*true\s*\)|expect\.[\w$]+\s*\)\s*\.toBeTruthy|\.toBeDefined\s*\(\s*\))/;

const ASSERTION_MATCHERS = new Set([
  'toHaveText', 'toContainText', 'toContain', 'toEqual', 'toMatch', 'toBeVisible', 'toBeHidden',
  'toBe', 'toHaveCount', 'toBeDefined', 'toBeEnabled', 'toBeDisabled', 'toBeChecked', 'toBeInTheDocument',
  'toHaveCSS', 'toHaveStyle', 'toHaveAttribute', 'toHaveClass',
]);

const LOCATOR_HEAD = /getBy(?:Text|LabelText|Role|PlaceholderText|AltText|Title)\s*\(/g;
const LOCATOR_VAR_DECL = /(?:const|let|var)\s+(\w+)\s*=\s*([^;]+);/g;

function locatorLiteralsAligned(codeExpr, sourceExpr, locatorVars) {
  const found = [];
  let m;
  LOCATOR_HEAD.lastIndex = 0;
  while ((m = LOCATOR_HEAD.exec(codeExpr))) {
    const openParen = m.index + m[0].length - 1;
    const close = findCloseParen(codeExpr, openParen);
    if (close < 0) continue;
    found.push(...stringLiteralsInExpr(sourceExpr.slice(openParen + 1, close)));
  }
  const trimmed = codeExpr.trim();
  if (/^\w+$/.test(trimmed) && locatorVars.has(trimmed)) found.push(...locatorVars.get(trimmed));
  return found;
}

function findCloseParen(code, openIndex) {
  if (code[openIndex] !== '(') return -1;
  let depth = 0;
  for (let i = openIndex; i < code.length; i++) {
    const c = code[i];
    if (c === '(') depth++;
    else if (c === ')') {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}

function stringLiteralsInExpr(expr) {
  const out = [];
  const re = /['"]([^'"]+)['"]/g;
  let m;
  while ((m = re.exec(expr))) out.push(m[1]);
  return out;
}

function locatorLiteralsInExpr(codeExpr, sourceExpr, locatorVars) {
  return locatorLiteralsAligned(codeExpr, sourceExpr ?? codeExpr, locatorVars);
}

/** Locator variables: name -> literal strings from getBy* on the RHS (detected on tokenized code only). */
function buildLocatorVarMap(source, code) {
  const map = new Map();
  let m;
  LOCATOR_VAR_DECL.lastIndex = 0;
  while ((m = LOCATOR_VAR_DECL.exec(code))) {
    const semi = m.index + m[0].length - 1;
    const eq = code.indexOf('=', m.index);
    if (eq < 0 || eq > semi) continue;
    const rhsCode = code.slice(eq + 1, semi);
    const rhsSource = source.slice(eq + 1, semi);
    const lits = locatorLiteralsAligned(rhsCode, rhsSource, new Map());
    if (lits.length) map.set(m[1], lits);
  }
  return map;
}

const XUNIT_CALL = /Assert\.(?:Equal|Contains|That|True|AreEqual)\s*\(/g;
const NODE_ASSERT_CALL = /assert\.(?:strictEqual|equal|match)\s*\(/g;

function literalsFromCallOnCode(code, source, openRe) {
  const literals = [];
  let m;
  openRe.lastIndex = 0;
  while ((m = openRe.exec(code))) {
    const openParen = m.index + m[0].length - 1;
    if (code[openParen] !== '(') continue;
    const close = findCloseParen(code, openParen);
    if (close < 0) continue;
    const argSlice = source.slice(openParen + 1, close);
    literals.push(...stringLiteralsInExpr(argSlice));
    const argCode = code.slice(openParen + 1, close);
    literals.push(...locatorLiteralsAligned(argCode, argSlice, new Map()));
  }
  return literals;
}

function literalsFromPythonAsserts(code, source, locatorVars) {
  const literals = [];
  const codeLines = code.split('\n');
  const sourceLines = source.split('\n');
  for (let i = 0; i < codeLines.length; i++) {
    if (!/^\s*assert\b/.test(codeLines[i])) continue;
    const line = sourceLines[i] ?? '';
    literals.push(...stringLiteralsInExpr(line));
    literals.push(...locatorLiteralsAligned(codeLines[i], line, locatorVars));
  }
  return literals;
}

function collectVarsUsedInExpectMatchers(code, locatorVars) {
  const used = new Set();
  const expectRe = /(?:await\s+)?expect\s*\(/g;
  let m;
  while ((m = expectRe.exec(code))) {
    const openParen = m.index + m[0].length - 1;
    const closeArg = findCloseParen(code, openParen);
    if (closeArg < 0) continue;
    const arg = code.slice(openParen + 1, closeArg).trim();
    const after = code.slice(closeArg + 1);
    if (!/^\s*(?:\.not\s*)?\.[a-zA-Z][\w$]*\s*\(/.test(after)) continue;
    if (/^\w+$/.test(arg) && locatorVars.has(arg)) used.add(arg);
  }
  return used;
}

function assertionMatcherRightAfter(closeParenIndex, code) {
  const after = code.slice(closeParenIndex + 1);
  const neg = after.match(/^\s*\.not\s*\.([a-zA-Z][\w$]*)\s*\(/);
  if (neg) return neg[1];
  const head = after.match(/^\s*\.([a-zA-Z][\w$]*)\s*\(/);
  return head ? head[1] : null;
}

function isExecutableExpect(code, openParenIndex) {
  const closeArg = findCloseParen(code, openParenIndex);
  if (closeArg < 0) return false;
  const name = assertionMatcherRightAfter(closeArg, code);
  return name !== null && ASSERTION_MATCHERS.has(name);
}

/**
 * Literals bound only through executable assertions (expect + matcher, Assert.*, etc.).
 * Bare getBy* calls never contribute.
 */
function collectExpectLiterals(source, { countVisibilityBinding = true } = {}) {
  const code = tokenize(source);
  const locatorVars = buildLocatorVarMap(source, code);
  const literals = [];

  const expectRe = /(?:await\s+)?expect\s*\(/g;
  let m;
  while ((m = expectRe.exec(code))) {
    const openParen = m.index + m[0].length - 1;
    if (!isExecutableExpect(code, openParen)) continue;
    const visibilityOnly = isVisibilityOnlyExpect(code, openParen);
    if (visibilityOnly && !countVisibilityBinding) continue;
    const closeArg = findCloseParen(code, openParen);
    const argCode = code.slice(openParen + 1, closeArg);
    const arg = source.slice(openParen + 1, closeArg);
    literals.push(...locatorLiteralsAligned(argCode, arg, locatorVars));

    const after = code.slice(closeArg + 1);
    const head = after.match(/^\s*(?:\.not\s*)?\.[a-zA-Z][\w$]*\s*\(/);
    if (!head) continue;
    const matcherOpen = closeArg + 1 + head[0].length - 1;
    const matcherClose = findCloseParen(code, matcherOpen);
    if (matcherClose > matcherOpen) {
      const matcherArg = source.slice(matcherOpen + 1, matcherClose);
      literals.push(...stringLiteralsInExpr(matcherArg));
    }
  }

  literals.push(...literalsFromCallOnCode(code, source, XUNIT_CALL));
  literals.push(...literalsFromCallOnCode(code, source, NODE_ASSERT_CALL));
  literals.push(...literalsFromPythonAsserts(code, source, locatorVars));

  return literals.join('\n');
}

function assertionLiterals(source) {
  return collectExpectLiterals(source, { countVisibilityBinding: false });
}

function expectWithoutMatcher(source) {
  const code = tokenize(source);
  const expectRe = /(?:await\s+)?expect\s*\(/g;
  let m;
  while ((m = expectRe.exec(code))) {
    const openParen = m.index + m[0].length - 1;
    const closeArg = findCloseParen(code, openParen);
    if (closeArg < 0) continue;
    if (!isExecutableExpect(code, openParen)) {
      return true;
    }
  }
  return false;
}

function unassertedLocatorAssignments(source) {
  const code = tokenize(source);
  const locatorVars = buildLocatorVarMap(source, code);
  const used = collectVarsUsedInExpectMatchers(code, locatorVars);
  for (const name of locatorVars.keys()) {
    if (!used.has(name)) return true;
  }
  return false;
}

export function validateSourceAssertions(source, scenario) {
  if (!scenario || scenario.kind !== 'automated') return { ok: true, reason: 'n/a' };
  const prefix = scenarioLineIdPrefix(scenario);
  const code = tokenize(source);
  if (VACUOUS.test(code)) return { ok: false, reason: `${prefix}automation uses vacuous assertion (truthy/true/defined-only)` };
  if (mockEncodesAnswer(source)) {
    return { ok: false, reason: `${prefix}automation mock encodes the answer instead of letting app logic decide` };
  }
  for (const row of visualSourceViolations(source)) {
    return { ok: false, reason: `${prefix}${row.reason}` };
  }
  if (expectWithoutMatcher(source)) {
    return { ok: false, reason: `${prefix}expect() without an assertion matcher does not bind expected lines` };
  }
  if (unassertedLocatorAssignments(source)) {
    return { ok: false, reason: `${prefix}locator stored in a variable must be passed to expect() with a matcher` };
  }
  const haystack = assertionLiterals(source);
  const visibilityHaystack = collectExpectLiterals(source, { countVisibilityBinding: true });
  for (const line of expectedLines(scenario.expected)) {
    const needle = line.length > 48 ? line.slice(0, 48) : line;
    if (source.includes(needle) && !haystack.includes(needle)) {
      if (visibilityHaystack.includes(needle)) {
        return {
          ok: false,
          reason: `${prefix}expected line bound only by visibility matcher (${line}) — require text/style/icon assertion`,
        };
      }
      return { ok: false, reason: `${prefix}expected text appears in source but not in an executable assertion` };
    }
  }
  const missing = expectedLines(scenario.expected).filter(line => {
    const needle = line.length > 48 ? line.slice(0, 48) : line;
    return !haystack.includes(needle);
  });
  if (missing.length) return { ok: false, reason: `${prefix}unasserted expected line(s): ${missing.join(' | ')}` };
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
