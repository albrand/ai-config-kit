import { readFileSync } from 'node:fs';
import { expectedLines, mockEncodesAnswer } from './behavior-rules.mjs';
import { tokenize } from './scenario-check.mjs';

const VACUOUS = /\b(?:expect\s*\(\s*true\s*\)|toBeTruthy\s*\(|assert\.ok\s*\(\s*true\s*\)|expect\.[\w$]+\s*\)\s*\.toBeTruthy|\.toBeDefined\s*\(\s*\))/;

const ASSERTION_MATCHERS = new Set([
  'toHaveText', 'toContainText', 'toContain', 'toEqual', 'toMatch', 'toBeVisible', 'toBeHidden',
  'toBe', 'toHaveCount', 'toBeDefined', 'toBeEnabled', 'toBeDisabled', 'toBeChecked', 'toBeInTheDocument',
]);

const LOCATOR_IN_EXPR = /getBy(?:Text|LabelText|Role|PlaceholderText|AltText|Title)\s*\(\s*['"]([^'"]+)['"]/g;
const LOCATOR_VAR_DECL = /(?:const|let|var)\s+(\w+)\s*=\s*([^;]+);/g;

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

function locatorLiteralsInExpr(expr, locatorVars) {
  const found = [];
  LOCATOR_IN_EXPR.lastIndex = 0;
  let m;
  while ((m = LOCATOR_IN_EXPR.exec(expr))) found.push(m[1]);
  const trimmed = expr.trim();
  if (/^\w+$/.test(trimmed) && locatorVars.has(trimmed)) found.push(...locatorVars.get(trimmed));
  return found;
}

/** Locator variables: name -> literal strings from getBy* on the RHS. */
function buildLocatorVarMap(source) {
  const map = new Map();
  let m;
  LOCATOR_VAR_DECL.lastIndex = 0;
  while ((m = LOCATOR_VAR_DECL.exec(source))) {
    const lits = locatorLiteralsInExpr(m[2], new Map());
    if (lits.length) map.set(m[1], lits);
  }
  return map;
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
function assertionLiterals(source) {
  const code = tokenize(source);
  const locatorVars = buildLocatorVarMap(source);
  const literals = [];

  const expectRe = /(?:await\s+)?expect\s*\(/g;
  let m;
  while ((m = expectRe.exec(code))) {
    const openParen = m.index + m[0].length - 1;
    if (!isExecutableExpect(code, openParen)) continue;
    const closeArg = findCloseParen(code, openParen);
    const arg = source.slice(openParen + 1, closeArg);
    literals.push(...locatorLiteralsInExpr(arg, locatorVars));

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

  const assertPatterns = [
    /Assert\.(?:Equal|Contains|That|True|AreEqual)\s*\(\s*['"]([^'"]+)['"]/g,
    /Assert\.(?:Equal|Contains|That|True|AreEqual)\s*\([^,]+,\s*['"]([^'"]+)['"]/g,
    /assert\.(?:strictEqual|equal|match)\s*\([^,]+,\s*['"]([^'"]+)['"]/g,
  ];
  for (const pattern of assertPatterns) {
    for (const match of source.matchAll(pattern)) literals.push(match[1]);
  }

  const assertPy = /^\s*assert\s+.+$/gm;
  for (const line of source.match(assertPy) ?? []) {
    literals.push(...locatorLiteralsInExpr(line, locatorVars));
    literals.push(...stringLiteralsInExpr(line));
  }

  return literals.join('\n');
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
  const locatorVars = buildLocatorVarMap(source);
  const used = collectVarsUsedInExpectMatchers(code, locatorVars);
  for (const name of locatorVars.keys()) {
    if (!used.has(name)) return true;
  }
  return false;
}

export function validateSourceAssertions(source, scenario) {
  if (!scenario || scenario.kind !== 'automated') return { ok: true, reason: 'n/a' };
  const code = tokenize(source);
  if (VACUOUS.test(code)) return { ok: false, reason: 'automation uses vacuous assertion (truthy/true/defined-only)' };
  if (mockEncodesAnswer(source)) return { ok: false, reason: 'automation mock encodes the answer instead of letting app logic decide' };
  if (expectWithoutMatcher(source)) {
    return { ok: false, reason: 'expect() without an assertion matcher does not bind expected lines' };
  }
  if (unassertedLocatorAssignments(source)) {
    return { ok: false, reason: 'locator stored in a variable must be passed to expect() with a matcher' };
  }
  const haystack = assertionLiterals(source);
  for (const line of expectedLines(scenario.expected)) {
    const needle = line.length > 48 ? line.slice(0, 48) : line;
    if (source.includes(needle) && !haystack.includes(needle)) {
      return { ok: false, reason: 'expected text appears in source but not in an executable assertion' };
    }
  }
  const missing = expectedLines(scenario.expected).filter(line => {
    const needle = line.length > 48 ? line.slice(0, 48) : line;
    return !haystack.includes(needle);
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
