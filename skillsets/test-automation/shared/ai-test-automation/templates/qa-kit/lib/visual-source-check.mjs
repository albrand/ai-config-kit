import { tokenize } from './lang-tokenize.mjs';

const VISIBILITY_ONLY_MATCHERS = new Set(['toBeVisible', 'toBeHidden', 'toBeInTheDocument', 'toBeAttached', 'toBeDetached']);
const TEXT_LOCATOR = /getBy(?:Text|LabelText|PlaceholderText)\s*\(/g;

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

function assertionMatcherRightAfter(closeParenIndex, code) {
  const after = code.slice(closeParenIndex + 1);
  const neg = after.match(/^\s*\.not\s*\.([a-zA-Z][\w$]*)\s*\(/);
  if (neg) return neg[1];
  const head = after.match(/^\s*\.([a-zA-Z][\w$]*)\s*\(/);
  return head ? head[1] : null;
}

/** Covered runners: Playwright/Test Library locators; xUnit/pytest string asserts are case-sensitive by default. */
export const VISUAL_CHECK_RUNNERS = 'Playwright, Testing Library (getByText), xUnit Assert.Equal, Node assert.strictEqual, pytest assert';

function regexArgHasInsensitiveFlag(srcTail) {
  if (!srcTail.startsWith('/')) return false;
  const close = srcTail.indexOf('/', 1);
  if (close < 0) return false;
  const flags = srcTail.slice(close + 1).match(/^[gimsuy]*/)?.[0] ?? '';
  return flags.includes('i');
}

function caseInsensitiveInExecutableCalls(source, code) {
  const locatorHead = /getBy(?:Text|LabelText|PlaceholderText)\s*\(/g;
  let m;
  while ((m = locatorHead.exec(code))) {
    const srcTail = source.slice(m.index + m[0].length).trimStart();
    if (regexArgHasInsensitiveFlag(srcTail)) return true;
  }
  const matcherHead = /\.to(?:Match|HaveText|ContainText)\s*\(/g;
  while ((m = matcherHead.exec(code))) {
    const srcTail = source.slice(m.index + m[0].length).trimStart();
    if (regexArgHasInsensitiveFlag(srcTail)) return true;
  }
  return false;
}

export function hasCaseInsensitiveTextMatcher(source) {
  const code = tokenize(source);
  if (caseInsensitiveInExecutableCalls(source, code)) return true;
  if (/new\s+RegExp\s*\([^)]*,\s*['"][^'"]*i[^'"]*['"]/.test(code)) return true;
  return false;
}

export function textLocatorMissingExactOption(source, code) {
  let m;
  TEXT_LOCATOR.lastIndex = 0;
  while ((m = TEXT_LOCATOR.exec(code))) {
    const openParen = m.index + m[0].length - 1;
    const close = findCloseParen(code, openParen);
    if (close < 0) continue;
    const argSource = source.slice(openParen + 1, close);
    if (!/['"]/.test(argSource)) continue;
    if (/exact\s*:\s*true/.test(argSource)) continue;
    return true;
  }
  return false;
}

export function isVisibilityOnlyExpect(code, openParenIndex) {
  const closeArg = findCloseParen(code, openParenIndex);
  if (closeArg < 0) return false;
  const name = assertionMatcherRightAfter(closeArg, code);
  return name !== null && VISIBILITY_ONLY_MATCHERS.has(name);
}

export function visualSourceViolations(source) {
  const code = tokenize(source);
  const out = [];
  if (hasCaseInsensitiveTextMatcher(source)) {
    out.push({ reason: 'case-insensitive text matcher in automation source' });
  }
  if (textLocatorMissingExactOption(source, code)) {
    out.push({ reason: 'text locator without exact match option (Playwright/Testing Library: { exact: true })' });
  }
  return out;
}

export function scenarioLineIdPrefix(scenario) {
  return scenario?.id ? `${scenario.id}: ` : '';
}
