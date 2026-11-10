import { tokenize } from './lang-tokenize.mjs';

const VISIBILITY_ONLY_MATCHERS = new Set(['toBeVisible', 'toBeHidden', 'toBeInTheDocument', 'toBeAttached', 'toBeDetached']);
const TEXT_LOCATOR = /getBy(?:Text|LabelText|PlaceholderText)\s*\(/g;

/** Covered runners: Playwright/Testing Library, xUnit, Node assert, pytest (equality-only text). */
export const VISUAL_CHECK_RUNNERS = 'Playwright, Testing Library (getByText), xUnit Assert.Equal, Node assert.strictEqual, pytest assert ==';

const KIND_CSS_PROPS = {
  colour: ['color'],
  'background-colour': ['background-color', 'background'],
  'font-family': ['font-family'],
  'font-size': ['font-size'],
  'font-weight': ['font-weight'],
};

const CSS_ASSERTION_RE = [
  /toHaveCSS\s*\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)/g,
  /to_have_css\s*\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)/gi,
  /ToHaveCSSAsync\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)/g,
];

const TO_HAVE_STYLE_RE = /toHaveStyle\s*\(\s*\{([^}]+)\}/g;

const ICON_ASSERTION_MATCHERS = new Set([
  'toBeVisible', 'toBeHidden', 'toHaveAttribute', 'toHaveCount', 'toHaveClass',
  'to_be_visible', 'to_be_hidden', 'to_have_attribute', 'to_have_count', 'to_have_class',
  'ToBeVisibleAsync', 'ToHaveAttributeAsync', 'ToHaveCountAsync',
]);

const ICON_LOCATOR_HEAD = [
  /getByRole\s*\(\s*['"]img['"]/g,
  /get_by_role\s*\(\s*['"]img['"]/gi,
  /GetByRole\s*\(\s*AriaRole\.Img/g,
  /getByTestId\s*\(/g,
  /get_by_test_id\s*\(/gi,
  /GetByTestId\s*\(/g,
];

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
  if (/\bbackground\b/i.test(line) && /\b(?:colour|color)\b/i.test(line)
    && (/#(?:[0-9a-fA-F]{3,8})\b|\brgb\s*\(/i.test(line))) {
    return 'background-colour';
  }
  if (/\b(?:colour|color)\b/i.test(line) && (/#(?:[0-9a-fA-F]{3,8})\b|\brgb\s*\(/i.test(line))) {
    return 'colour';
  }
  if (/\bfont family\b/i.test(line)) return 'font-family';
  if (/\bfont size\b/i.test(line) && /\d+\s*(?:px|pt|rem|em|%)\b/i.test(line)) return 'font-size';
  if (/\bfont weight\b/i.test(line)) return 'font-weight';
  if (/\b(?:uppercase|lowercase|title case|letter case|text-transform)\b/i.test(line)) return 'letter-case';
  if (/\bicon\s+shows\s+/i.test(line)) return 'icon';
  if (/\bicon\s+is\s+(?!visible\b)/i.test(line)) return 'icon';
  return null;
}

function visualValueNeedle(line, kind) {
  const hex = line.match(/#(?:[0-9a-fA-F]{3,8})\b/)?.[0];
  if (hex && (kind === 'colour' || kind === 'background-colour')) return hex;
  const px = line.match(/\d+\s*(?:px|pt|rem|em)\b/i)?.[0];
  if (px && kind === 'font-size') return px.replace(/\s+/g, '');
  const weight = line.match(/font weight is\s+(\d{3})\b/i)?.[1];
  if (weight && kind === 'font-weight') return weight;
  const family = line.match(/font family is\s+["']?([^"'\n]+)/i)?.[1]?.trim();
  if (family) return family.length > 32 ? family.slice(0, 32) : family;
  if (kind === 'letter-case' && /uppercase/i.test(line)) return 'uppercase';
  if (kind === 'letter-case' && /lowercase/i.test(line)) return 'lowercase';
  if (kind === 'icon') {
    const icon = line.match(/\bicon\s+(?:shows|is)\s+(.+)/i)?.[1]?.trim();
    if (icon) return icon.toLowerCase();
  }
  return line.length > 48 ? line.slice(0, 48) : line;
}

function isExecutableSpan(code, start, end) {
  const slice = code.slice(start, end);
  return /\S/.test(slice);
}

function normalizeVisualValue(value, kind) {
  if (!value) return '';
  let v = value.trim().toLowerCase().replace(/\s+/g, '');
  if (kind === 'font-size') v = v.replace(/(\d)(px|pt|rem|em|%)/, '$1$2');
  return v;
}

function fontFamilyTokenMatch(asserted, needle) {
  const n = needle.trim().toLowerCase();
  if (!n) return false;
  const raw = asserted.trim().toLowerCase();
  if (raw === n) return true;
  const tokens = raw.split(',').map(t => t.trim().replace(/^['"]|['"]$/g, ''));
  return tokens.some(t => t === n);
}

function strictIdentityMatch(asserted, expected) {
  if (!expected) return false;
  return asserted.trim().toLowerCase() === expected.trim().toLowerCase();
}

function valuesMatch(asserted, needle, kind) {
  const a = normalizeVisualValue(asserted, kind);
  const n = normalizeVisualValue(needle, kind);
  if (!n) return false;
  if (a === n) return true;
  if (kind === 'font-family') return fontFamilyTokenMatch(asserted, needle);
  return false;
}

function cssPropMatchesKind(prop, kind) {
  const p = prop.toLowerCase();
  const allowed = KIND_CSS_PROPS[kind];
  if (!allowed) return false;
  return allowed.some(a => p === a || (a === 'background' && p === 'background-color'));
}

function parseToHaveStylePairs(source, code, out) {
  for (const m of source.matchAll(TO_HAVE_STYLE_RE)) {
    if (!isExecutableSpan(code, m.index, m.index + m[0].length)) continue;
    const inner = m[1];
    for (const pair of inner.matchAll(/(fontFamily|fontSize|fontWeight|color|backgroundColor|textTransform)\s*:\s*['"]([^'"]+)['"]/g)) {
      const propMap = {
        fontFamily: 'font-family',
        fontSize: 'font-size',
        fontWeight: 'font-weight',
        color: 'color',
        backgroundColor: 'background-color',
        textTransform: 'text-transform',
      };
      out.push({ prop: propMap[pair[1]] ?? pair[1], value: pair[2] });
    }
  }
}

/** CSS property/value pairs from executable assertion calls only. */
export function collectExecutableCssAssertions(source, code) {
  const out = [];
  for (const re of CSS_ASSERTION_RE) {
    re.lastIndex = 0;
    for (const m of source.matchAll(re)) {
      if (!isExecutableSpan(code, m.index, m.index + m[0].length)) continue;
      out.push({ prop: m[1], value: m[2] });
    }
  }
  parseToHaveStylePairs(source, code, out);
  return out;
}

function styleAssertionCoversKind(source, code, kind, needle) {
  const assertions = collectExecutableCssAssertions(source, code);
  return assertions.some(({ prop, value }) => cssPropMatchesKind(prop, kind) && valuesMatch(value, needle, kind));
}

function letterCaseAssertionOk(source, code, line) {
  const needle = visualValueNeedle(line, 'letter-case');
  const assertions = collectExecutableCssAssertions(source, code);
  if (assertions.some(a => a.prop === 'text-transform' && valuesMatch(a.value, needle, 'letter-case'))) {
    return true;
  }
  for (const m of source.matchAll(/to_have_css\s*\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]/gi)) {
    if (!isExecutableSpan(code, m.index, m.index + m[0].length)) continue;
    if (m[1].toLowerCase() === 'text-transform' && valuesMatch(m[2], needle, 'letter-case')) return true;
  }
  if (/ToHaveCSSAsync\s*\([^)]*text-transform/i.test(source)) {
    for (const m of source.matchAll(/ToHaveCSSAsync\s*\(\s*"text-transform"\s*,\s*"([^"]+)"/g)) {
      if (!isExecutableSpan(code, m.index, m.index + m[0].length)) continue;
      if (valuesMatch(m[1], needle, 'letter-case')) return true;
    }
  }
  for (const m of source.matchAll(/toHaveText\s*\([^)]*\)/g)) {
    if (!isExecutableSpan(code, m.index, m.index + m[0].length)) continue;
    const callSrc = source.slice(m.index, m.index + m[0].length);
    if (/useInnerText\s*:\s*true/.test(callSrc)) return true;
  }
  for (const m of source.matchAll(/\.innerText\s*\(\s*\)/g)) {
    if (!isExecutableSpan(code, m.index, m.index + m[0].length)) continue;
    const tail = source.slice(m.index, m.index + 160);
    if (!/(?:\.toBe\s*\(|===|==|assert\.strictEqual)/.test(tail)) continue;
  if (/uppercase/i.test(line) && /['"][A-Z][^'"]{2,}['"]/.test(tail)) return true;
    if (/lowercase/i.test(line) && /['"][a-z][^'"]{2,}['"]/.test(tail)) return true;
  }
  return false;
}

function iconIdentityLiteralsInArg(argSource) {
  const literals = [];
  const patterns = [
    /(?:\bname\b|\bName\b)\s*[:=]\s*['"]([^'"]+)['"]/g,
    /getByTestId\s*\(\s*['"]([^'"]+)['"]/g,
    /get_by_test_id\s*\(\s*['"]([^'"]+)['"]/g,
    /GetByTestId\s*\(\s*"([^"]+)"/g,
    /locator\s*\(\s*['"][^'"]*(?:data-testid|data-icon|aria-label)=([^'"\]]+)/gi,
  ];
  for (const re of patterns) {
    re.lastIndex = 0;
    for (const m of argSource.matchAll(re)) literals.push(m[1]);
  }
  return literals;
}

function iconLocatorsInRange(source, code, rangeStart, rangeEnd) {
  const found = [];
  const slice = source.slice(rangeStart, rangeEnd);
  for (const re of ICON_LOCATOR_HEAD) {
    const local = new RegExp(re.source, re.flags);
    let m;
    while ((m = local.exec(slice))) {
      const abs = rangeStart + m.index;
      const relOpen = m[0].indexOf('(');
      if (relOpen < 0) continue;
      const openParen = abs + relOpen;
      const close = findCloseParen(code, openParen);
      if (close < 0 || close > rangeEnd) continue;
      if (!isExecutableSpan(code, abs, close + 1)) continue;
      found.push(source.slice(openParen + 1, close));
    }
  }
  return found;
}

function matcherCallLiterals(source, code, argClose) {
  const afterCode = code.slice(argClose + 1);
  const afterSrc = source.slice(argClose + 1);
  const head = afterCode.match(/^\s*(?:\.not\s*)?\.([a-zA-Z][\w$]*)\s*\(/);
  if (!head || !ICON_ASSERTION_MATCHERS.has(head[1])) return [];
  const open = argClose + 1 + afterCode.indexOf('(');
  const close = findCloseParen(code, open);
  if (close < 0 || !isExecutableSpan(code, open, close + 1)) return [];
  const matcher = head[1];
  const args = source.slice(open + 1, close);
  if (/Attribute/i.test(matcher)) {
    const m = args.match(/^\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]/);
    if (m && /^(aria-label|src|href|alt|data-testid)$/i.test(m[1])) return [m[2]];
  }
  return [];
}

function collectExecutableIconBindings(source, code) {
  const values = [];
  const expectHeads = [
    /(?:await\s+)?expect\s*\(/g,
    /(?:await\s+)?Expect\s*\(/g,
  ];
  for (const expectRe of expectHeads) {
    expectRe.lastIndex = 0;
    let m;
    while ((m = expectRe.exec(code))) {
      const expectOpen = m.index + m[0].length - 1;
      if (!isExecutableSpan(code, m.index, expectOpen + 1)) continue;
      const argClose = findCloseParen(code, expectOpen);
      if (argClose < 0) continue;
      const matcher = assertionMatcherRightAfter(argClose, code);
      if (!matcher || !ICON_ASSERTION_MATCHERS.has(matcher)) continue;
      for (const arg of iconLocatorsInRange(source, code, expectOpen + 1, argClose)) {
        values.push(...iconIdentityLiteralsInArg(arg));
      }
      values.push(...matcherCallLiterals(source, code, argClose));
    }
  }
  return values;
}

function iconAssertionOk(source, code, line) {
  const needle = visualValueNeedle(line, 'icon');
  if (!needle) return false;
  const bindings = collectExecutableIconBindings(source, code);
  return bindings.some(v => strictIdentityMatch(v, needle));
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
  if (kind === 'letter-case') return !letterCaseAssertionOk(source, code, line);
  if (kind === 'icon') return !iconAssertionOk(source, code, line);
  if (kind in KIND_CSS_PROPS) return !styleAssertionCoversKind(source, code, kind, needle);
  return true;
}

export function visualMissingKindReason(kind, line) {
  return `visual expected line missing ${kind} assertion (${line})`;
}

export function visualLineViolations(source, scenario) {
  const code = tokenize(source);
  const lines = (scenario?.expected ?? '').split(/\n+/).map(l => l.trim()).filter(Boolean);
  for (const line of lines) {
    const kind = isVisualPropertyLine(line);
    if (!kind) continue;
    if (visualLineBindingFails(source, code, line)) {
      return { reason: visualMissingKindReason(kind, line) };
    }
    if (/toHaveClass\s*\(/.test(code) && kind !== 'icon') {
      const needle = visualValueNeedle(line, kind);
      if (needle && source.toLowerCase().includes(needle.toLowerCase().slice(0, 8))) {
        return { reason: `class-name check cannot satisfy visual expected line (${line})` };
      }
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
