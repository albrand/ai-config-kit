import { tokenize } from './lang-tokenize.mjs';

const VISIBILITY_ONLY_MATCHERS = new Set(['toBeVisible', 'toBeHidden', 'toBeInTheDocument', 'toBeAttached', 'toBeDetached']);
const TEXT_LOCATOR = /getBy(?:Text|LabelText|PlaceholderText)\s*\(/g;
const PARTIAL_TEXT_MATCHERS = new Set([
  'toContain', 'toContainText', 'toMatch', 'matches', 'Contains', 'Matches',
]);
const STYLE_MATCHERS = /toHaveCSS\s*\(|toHaveStyle\s*\(|getComputedStyle|\.(?:backgroundColor|color|fontFamily|fontSize|fontWeight|textTransform)\b|Assert\.Equal\s*\([^)]*(?:Color|color)/;

/** Covered runners: Playwright/Testing Library, xUnit, Node assert, pytest (equality-only text). */
export const VISUAL_CHECK_RUNNERS = 'Playwright, Testing Library (getByText), xUnit Assert.Equal, Node assert.strictEqual, pytest assert ==';

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
  if (/\.toLowerCase\s*\(/.test(code)) return true;
  if (/\.toUpperCase\s*\(/.test(code)) return true;
  if (/\.casefold\s*\(/.test(code)) return true;
  if (/StringComparison\.\w*IgnoreCase/.test(code)) return true;
  if (/OrdinalIgnoreCase/.test(code)) return true;
  if (/\.ToLower(?:Invariant)?\s*\(/.test(code)) return true;
  if (/\.ToUpper(?:Invariant)?\s*\(/.test(code)) return true;
  if (/ignoreCase\s*:\s*true/.test(code)) return true;
  if (/RegexOptions\.IgnoreCase/.test(code)) return true;
  if (/\bre\.(?:I|IGNORECASE)\b/.test(code)) return true;
  if (/flags\s*=\s*re\.I\b/.test(code)) return true;
  return false;
}

/** Every text locator in the file must use `{ exact: true }` when the argument is a string literal (including RHS of assignments). */
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

export function hasPartialTextMatch(source) {
  const code = tokenize(source);
  if (/Assert\.Contains\b/.test(code)) return true;
  if (/Assert\.Matches\b/.test(code)) return true;
  if (/\.Contains\s*\(/.test(code)) return true;
  if (/\.StartsWith\s*\(/.test(code)) return true;
  if (/\.EndsWith\s*\(/.test(code)) return true;
  if (/\.toContainText\s*\(/.test(code)) return true;
  if (/\.toContain\s*\(/.test(code)) return true;
  if (/\.includes\s*\(/.test(code)) return true;
  if (/\.toMatch\s*\(/.test(code)) return true;
  const codeLines = code.split('\n');
  const srcLines = source.split('\n');
  for (let i = 0; i < codeLines.length; i++) {
    if (!/^\s*assert\b/.test(codeLines[i])) continue;
    const srcLine = srcLines[i] ?? '';
  if (/\bin\b/.test(codeLines[i]) && /['"]/.test(srcLine)) return true;
    if (/\.find\s*\(/.test(codeLines[i])) return true;
    if (/re\.search/.test(codeLines[i])) return true;
  }
  return false;
}

export function isVisualPropertyLine(line) {
  if (/\b(?:colour|color)\b/i.test(line) && (/#(?:[0-9a-fA-F]{3,8})\b|\brgb\s*\(/i.test(line) || /\bcolour is\b/i.test(line))) {
    return 'colour';
  }
  if (/\bfont family\b/i.test(line)) return 'font-family';
  if (/\bfont size\b/i.test(line) && /\d+\s*(?:px|pt|rem|em|%)\b/i.test(line)) return 'font-size';
  if (/\bfont weight\b/i.test(line)) return 'font-weight';
  if (/\b(?:uppercase|lowercase|title case|letter case|text-transform)\b/i.test(line)) return 'letter-case';
  return null;
}

function visualValueNeedle(line, kind) {
  const hex = line.match(/#(?:[0-9a-fA-F]{3,8})\b/)?.[0];
  if (hex) return hex;
  const px = line.match(/\d+\s*(?:px|pt|rem|em)\b/i)?.[0];
  if (px && kind === 'font-size') return px.replace(/\s+/g, '');
  const family = line.match(/font family is\s+["']?([^"'\n]+)/i)?.[1]?.trim();
  if (family) return family.length > 32 ? family.slice(0, 32) : family;
  if (kind === 'letter-case' && /uppercase/i.test(line)) return 'uppercase';
  if (kind === 'letter-case' && /lowercase/i.test(line)) return 'lowercase';
  return line.length > 48 ? line.slice(0, 48) : line;
}

function styleAssertionCoversValue(source, code, value) {
  if (!value) return false;
  const v = value.toLowerCase();
  if (!STYLE_MATCHERS.test(code)) return false;
  for (const m of source.matchAll(/toHaveCSS\s*\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]/g)) {
    const joined = `${m[1]} ${m[2]}`.toLowerCase();
    if (joined.includes(v) || v.includes(m[2].toLowerCase())) return true;
  }
  for (const m of source.matchAll(/toHaveStyle\s*\(\s*\{([^}]+)\}/g)) {
    if (m[1].toLowerCase().includes(v)) return true;
  }
  if (/getComputedStyle/.test(code) && source.toLowerCase().includes(v)) return true;
  return source.toLowerCase().includes(v) && /toHaveCSS|toHaveStyle|getComputedStyle|textTransform|fontFamily|fontSize|fontWeight/.test(code);
}

function letterCaseAssertionOk(source, code, line) {
  if (/text-transform/i.test(line) && /uppercase/i.test(line)) {
    return /toHaveCSS\s*\(\s*['"]text-transform['"]\s*,\s*['"]uppercase['"]/.test(source)
      || /textTransform['"]\s*:\s*['"]uppercase/.test(source);
  }
  if (/uppercase/i.test(line)) {
    return /toHaveCSS\s*\(\s*['"]text-transform['"]/.test(source) || /\.textTransform/.test(code);
  }
  return false;
}

export function visualLineIsBound(source, line) {
  const code = tokenize(source);
  if (!isVisualPropertyLine(line)) return false;
  return !visualLineBindingFails(source, code, line);
}

function visualLineBindingFails(source, code, line) {
  const kind = isVisualPropertyLine(line);
  if (!kind) return false;
  const needle = visualValueNeedle(line, kind);
  if (kind === 'letter-case') {
    return !letterCaseAssertionOk(source, code, line);
  }
  if (kind === 'colour' || kind === 'font-family' || kind === 'font-size' || kind === 'font-weight') {
    return !styleAssertionCoversValue(source, code, needle);
  }
  return true;
}

export function visualLineViolations(source, scenario) {
  const code = tokenize(source);
  const lines = (scenario?.expected ?? '').split(/\n+/).map(l => l.trim()).filter(Boolean);
  for (const line of lines) {
    if (!isVisualPropertyLine(line)) continue;
    if (visualLineBindingFails(source, code, line)) {
      return {
        reason: `visual expected line needs style/transform assertion (${line})`,
      };
    }
    const needle = visualValueNeedle(line, isVisualPropertyLine(line));
    if (/toHaveClass\s*\(/.test(code) && !STYLE_MATCHERS.test(code) && source.includes(needle)) {
      return { reason: `class-name check cannot satisfy visual expected line (${line})` };
    }
  }
  return null;
}

export function isVisibilityOnlyExpect(code, openParenIndex) {
  const closeArg = findCloseParen(code, openParenIndex);
  if (closeArg < 0) return false;
  const name = assertionMatcherRightAfter(closeArg, code);
  return name !== null && VISIBILITY_ONLY_MATCHERS.has(name);
}

export function visualSourceViolations(source, scenario) {
  const code = tokenize(source);
  const out = [];
  if (hasCaseInsensitiveTextMatcher(source)) {
    out.push({ reason: 'case-insensitive text matcher in automation source' });
  }
  if (hasPartialTextMatch(source)) {
    out.push({ reason: 'partial or substring text matcher is not allowed for quoted expected lines' });
  }
  if (textLocatorMissingExactOption(source, code)) {
    out.push({
      reason: 'text locator without exact match option (Playwright/Testing Library: { exact: true } on every getByText in the file)',
    });
  }
  const visual = scenario ? visualLineViolations(source, scenario) : null;
  if (visual) out.push(visual);
  return out;
}

export function scenarioLineIdPrefix(scenario) {
  return scenario?.id ? `${scenario.id}: ` : '';
}
