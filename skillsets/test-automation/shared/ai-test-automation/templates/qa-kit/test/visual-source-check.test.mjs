import test from 'node:test';
import assert from 'node:assert/strict';
import { validateSourceAssertions } from '../lib/source-assertions.mjs';
import { hasCaseInsensitiveTextMatcher, hasPartialTextMatch, textLocatorMissingExactOption } from '../lib/visual-source-check.mjs';
import { tokenize } from '../lib/lang-tokenize.mjs';

const LINE_TEXT = 'Submit Order';

const VISUAL_PROPS = [
  {
    kind: 'colour',
    line: 'Primary label text colour is #111827',
    js: `await expect(page.locator('.label')).toHaveCSS('color', '#111827');`,
    csharp: `await Expect(Page.Locator(".label")).ToHaveCSSAsync("color", "#111827");`,
    python: `expect(page.locator(".label")).to_have_css("color", "#111827")`,
  },
  {
    kind: 'background-colour',
    line: 'Primary button background colour is #0A5CFF',
    js: `await expect(page.locator('[data-testid=primary-cta]')).toHaveCSS('background-color', '#0A5CFF');`,
    csharp: `await Expect(Page.Locator("[data-testid=primary-cta]")).ToHaveCSSAsync("background-color", "#0A5CFF");`,
    python: `expect(page.locator("[data-testid=primary-cta]")).to_have_css("background-color", "#0A5CFF")`,
  },
  {
    kind: 'font-family',
    line: 'Body font family is Inter',
    js: `await expect(page.locator('.body')).toHaveCSS('font-family', 'Inter');`,
    csharp: `await Expect(Page.Locator(".body")).ToHaveCSSAsync("font-family", "Inter");`,
    python: `expect(page.locator(".body")).to_have_css("font-family", "Inter")`,
  },
  {
    kind: 'font-size',
    line: 'Heading font size is 24px',
    js: `await expect(page.locator('h1')).toHaveCSS('font-size', '24px');`,
    csharp: `await Expect(Page.Locator("h1")).ToHaveCSSAsync("font-size", "24px");`,
    python: `expect(page.locator("h1")).to_have_css("font-size", "24px")`,
  },
  {
    kind: 'font-weight',
    line: 'Section title font weight is 700',
    js: `await expect(page.locator('h2.section')).toHaveCSS('font-weight', '700');`,
    csharp: `await Expect(Page.Locator("h2.section")).ToHaveCSSAsync("font-weight", "700");`,
    python: `expect(page.locator("h2.section")).to_have_css("font-weight", "700")`,
  },
  {
    kind: 'letter-case',
    line: 'Submit label is shown in uppercase',
    js: `await expect(page.locator('[data-testid=submit]')).toHaveCSS('text-transform', 'uppercase');`,
    csharp: `await Expect(Page.Locator("[data-testid=submit]")).ToHaveCSSAsync("text-transform", "uppercase");`,
    python: `expect(page.locator("[data-testid=submit]")).to_have_css("text-transform", "uppercase")`,
  },
  {
    kind: 'icon',
    line: 'Cart icon shows shopping-bag glyph',
    js: `await expect(page.getByRole('img', { name: 'shopping-bag glyph' })).toBeVisible();`,
    csharp: `await Expect(Page.GetByRole(AriaRole.Img, new() { Name = "shopping-bag glyph" })).ToBeVisibleAsync();`,
    python: `expect(page.get_by_role("img", name="shopping-bag glyph")).to_be_visible()`,
  },
];

const scenarioAllVisual = {
  id: 'QAS-VIS-01',
  kind: 'automated',
  expected: [LINE_TEXT, ...VISUAL_PROPS.map(p => p.line)].join('\n'),
};

const scenarioTextBg = {
  id: 'QAS-VIS-01',
  kind: 'automated',
  expected: `${LINE_TEXT}\n${VISUAL_PROPS.find(p => p.kind === 'background-colour').line}`,
};

const scenarioLetterCase = {
  id: 'QAS-VIS-01',
  kind: 'automated',
  expected: `${LINE_TEXT}\n${VISUAL_PROPS.find(p => p.kind === 'letter-case').line}`,
};

const ICON_LINE = VISUAL_PROPS.find(p => p.kind === 'icon').line;

const scenarioIcon = {
  id: 'QAS-VIS-01',
  kind: 'automated',
  expected: `${LINE_TEXT}\n${ICON_LINE}`,
};


const scenarioIconDesignated = {
  id: 'QAS-VIS-01',
  kind: 'automated',
  expected: `${LINE_TEXT}\nCart icon (\`cart-glyph\`) shows shopping-bag glyph`,
};

const scenarioIconShort = {
  id: 'QAS-VIS-01',
  kind: 'automated',
  expected: `${LINE_TEXT}\nCart icon shows bag`,
};

function bindsForLang(lang, omitKind) {
  return VISUAL_PROPS.filter(p => p.kind !== omitKind).map(p => p[lang]);
}

function jsBody(omitKind, extraLines = []) {
  const lines = [
    `await expect(page.getByText('${LINE_TEXT}', { exact: true })).toHaveText('${LINE_TEXT}');`,
    ...bindsForLang('js', omitKind),
    ...extraLines,
  ];
  return `test('QAS-VIS-01', async () => {\n    ${lines.join('\n    ')}\n  });`;
}

function csharpBody(omitKind, extraLines = []) {
  const lines = [
    'Assert.Equal("Submit Order", await Page.Locator("h1").InnerTextAsync());',
    ...bindsForLang('csharp', omitKind),
    ...extraLines,
  ];
  return `[Fact]
public async Task QAS_VIS_01() {
  ${lines.join('\n  ')}
}`;
}

function pythonBody(omitKind, extraLines = []) {
  const lines = [
    `assert page.inner_text("h1") == "${LINE_TEXT}"`,
    ...bindsForLang('python', omitKind),
    ...extraLines,
  ];
  return `def test_qas_vis_01():\n    ${lines.join('\n    ')}`;
}

function bodyFor(lang, omitKind, extra = []) {
  if (lang === 'js') return jsBody(omitKind, extra);
  if (lang === 'csharp') return csharpBody(omitKind, extra);
  return pythonBody(omitKind, extra);
}

const PROP_LANGS = ['js', 'csharp', 'python'];

const REJECTS = [
  { lang: 'js', form: 'visibility-only', body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText('${LINE_TEXT}', { exact: true })).toBeVisible(); });`, match: /visibility matcher/ },
  { lang: 'js', form: 'getByText-without-exact', body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText('${LINE_TEXT}')).toHaveText('${LINE_TEXT}'); });`, match: /exact match/ },
  { lang: 'js', form: 'var-without-exact', body: `test('QAS-VIS-01', async () => {
      const cta = page.getByText('${LINE_TEXT}');
      await expect(cta).toHaveText('${LINE_TEXT}'); });`, match: /exact match/ },
  { lang: 'js', form: 'toContainText', body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText('${LINE_TEXT}', { exact: true })).toContainText('${LINE_TEXT}'); });`, match: /partial|substring/ },
  { lang: 'js', form: 'includes', body: `test('QAS-VIS-01', async () => {
      expect(page.innerText().includes('${LINE_TEXT}')).toBe(true); });`, match: /partial|substring/ },
  { lang: 'js', form: 'tolower', body: `test('QAS-VIS-01', async () => {
      expect(page.innerText().toLowerCase()).toBe('${LINE_TEXT}'.toLowerCase()); });`, match: /case-insensitive/ },
  { lang: 'js', form: 'regexp-i', body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText(/submit order/i)).toHaveText('${LINE_TEXT}'); });`, match: /case-insensitive/ },
  { lang: 'js', form: 'colour-by-text', body: jsBody('background-colour', []), scenario: scenarioAllVisual, match: /missing background-colour/ },
  { lang: 'js', form: 'colour-by-class', body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText('${LINE_TEXT}', { exact: true })).toHaveText('${LINE_TEXT}');
      await expect(page.locator('[data-testid=primary-cta]')).toHaveClass('btn-primary'); });`,
    scenario: scenarioTextBg, match: /missing background-colour|class-name/ },
  { lang: 'csharp', form: 'Assert.Contains', body: `[Fact]
    public void QAS_VIS_01() { Assert.Contains("${LINE_TEXT}", Page.Locator("h1").InnerText); }`, match: /partial|substring/ },
  { lang: 'csharp', form: 'OrdinalIgnoreCase', body: `[Fact]
    public void QAS_VIS_01() { Assert.Equal("${LINE_TEXT}", actual, StringComparison.OrdinalIgnoreCase); }`, match: /case-insensitive/ },
  { lang: 'csharp', form: 'comment-spoof-contains', body: `// Assert.Contains("${LINE_TEXT}", actual);
      [Fact] public void QAS_VIS_01() { Assert.Equal("other", actual); }`, match: /unasserted|executable assertion/ },
  { lang: 'csharp', form: 'string-spoof-contains', body: `var p = "Assert.Contains(\\"${LINE_TEXT}\\")";
      [Fact] public void QAS_VIS_01() { Assert.Equal("other", actual); }`, match: /unasserted|executable assertion/ },
  { lang: 'python', form: 'assert-in', body: `def test_vis():
      assert "${LINE_TEXT}" in page.inner_text("h1")`, match: /partial|substring/ },
  { lang: 'python', form: 're-search', body: `def test_vis():
      import re
      assert re.search("submit order", page.inner_text("h1"), re.I)`, match: /case-insensitive|partial/ },
  { lang: 'python', form: 'comment-spoof-in', body: `# assert "${LINE_TEXT}" in page
      def test_vis(): assert "unrelated" == page.inner_text("h1")`, match: /unasserted|executable assertion/ },
  { lang: 'python', form: 'hash-spoof-in', body: `#assert "${LINE_TEXT}" in page
      def test_vis(): assert "wrong" == page.inner_text("h1")`, match: /unasserted|executable assertion/ },
  { lang: 'csharp', form: 'EndsWith', body: `[Fact]
    public void QAS_VIS_01() { Assert.EndsWith("${LINE_TEXT}", actual); }`, match: /partial|substring/ },
  { lang: 'csharp', form: 'ToLower', body: `[Fact]
    public void QAS_VIS_01() { Assert.Equal(actual.ToLower(), "${LINE_TEXT}".ToLower()); }`, match: /case-insensitive/ },
  { lang: 'csharp', form: 'block-comment-partial', body: `/* Assert.Contains("${LINE_TEXT}", actual); */
      [Fact] public void QAS_VIS_01() { Assert.Equal("x", actual); }`, match: /unasserted|executable/ },
  { lang: 'python', form: 'find', body: `def test_vis():
      assert page.inner_text("h1").find("${LINE_TEXT}") >= 0`, match: /partial|substring/ },
  { lang: 'python', form: 'casefold', body: `def test_vis():
      assert page.inner_text("h1").casefold() == "${LINE_TEXT}".casefold()`, match: /case-insensitive/ },
  { lang: 'python', form: 'string-spoof-in', body: `plan = '''assert "${LINE_TEXT}" in page'''
      def test_vis(): assert "x" == page.inner_text("h1")`, match: /unasserted|executable/ },
  { lang: 'js', form: 'block-comment-partial', body: `/* expect(el).toContainText('${LINE_TEXT}') */
      test('QAS-VIS-01', async () => { await expect(page.getByRole('table')).toBeVisible(); });`, match: /unasserted|executable/ },
  { lang: 'js', form: 'comment-spoof-exact', body: `// getByText('${LINE_TEXT}', { exact: true })
      test('QAS-VIS-01', async () => { await expect(page.getByRole('table')).toBeVisible(); });`, match: /unasserted|visibility|executable/ },
  { lang: 'js', form: 'string-spoof-exact', body: `const plan = "getByText('${LINE_TEXT}', { exact: true })";
      test('QAS-VIS-01', async () => { await expect(page.getByRole('table')).toBeVisible(); });`, match: /unasserted|executable/ },
  { lang: 'js', form: 'font-size-value-in-comment', scenario: scenarioAllVisual,
    body: jsBody('font-size', ['// heading font-size 24px']),
    match: /missing font-size assertion/ },
  { lang: 'js', form: 'font-size-wrong-property', scenario: scenarioAllVisual,
    body: jsBody('font-size', [`await expect(page.locator('h1')).toHaveCSS('color', '#111827');`]),
    match: /missing font-size assertion/ },
  { lang: 'js', form: 'font-size-wrong-value', scenario: scenarioAllVisual,
    body: jsBody('font-size', [`await expect(page.locator('h1')).toHaveCSS('font-size', '16px');`]),
    match: /missing font-size assertion/ },
  { lang: 'js', form: 'letter-case-dom-toHaveText', scenario: scenarioLetterCase,
    body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText('${LINE_TEXT}', { exact: true })).toHaveText('${LINE_TEXT}');
      await expect(page.locator('[data-testid=submit]')).toHaveText('SUBMIT ORDER');
    });`,
    match: /missing letter-case assertion/ },
  { lang: 'js', form: 'letter-case-getByText-exact-chain', scenario: scenarioLetterCase,
    body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText('${LINE_TEXT}', { exact: true })).toHaveText('${LINE_TEXT}');
      await expect(page.getByText('SUBMIT ORDER', { exact: true })).toHaveText('SUBMIT ORDER');
    });`,
    match: /missing letter-case assertion/ },
  { lang: 'js', form: 'icon-locator-unasserted', scenario: scenarioIcon,
    body: jsBody('icon', [`page.getByRole('img', { name: 'shopping-bag glyph' });`]),
    match: /missing icon assertion/ },
  { lang: 'js', form: 'icon-name-in-comment', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.getByRole('img', { name: 'checkout glyph' })).toBeVisible(); // shopping-bag glyph`]),
    match: /missing icon assertion/ },
  { lang: 'js', form: 'icon-name-next-statement', scenario: scenarioIcon,
    body: jsBody('icon', [
      `await expect(page.getByRole('img', { name: 'checkout glyph' })).toBeVisible();`,
      `const _note = 'shopping-bag glyph';`,
    ]),
    match: /missing icon assertion/ },
  { lang: 'js', form: 'icon-substring-assert', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.getByRole('img', { name: 'shopping-bag-off' })).toBeVisible();`]),
    match: /missing icon assertion/ },
  { lang: 'js', form: 'icon-substring-needle', scenario: scenarioIconShort,
    body: jsBody('icon', [`await expect(page.getByRole('img', { name: 'shopping-bag-off' })).toBeVisible();`]),
    match: /missing icon assertion/ },
  { lang: 'csharp', form: 'icon-locator-unasserted', scenario: scenarioIcon,
    body: csharpBody('icon', [`Page.GetByRole(AriaRole.Img, new() { Name = "shopping-bag glyph" });`]),
    match: /missing icon assertion/ },
  { lang: 'csharp', form: 'icon-substring-assert', scenario: scenarioIcon,
    body: csharpBody('icon', [`await Expect(Page.GetByRole(AriaRole.Img, new() { Name = "shopping-bag-off" })).ToBeVisibleAsync();`]),
    match: /missing icon assertion/ },
  { lang: 'python', form: 'icon-locator-unasserted', scenario: scenarioIcon,
    body: pythonBody('icon', [`page.get_by_role("img", name="shopping-bag glyph")`]),
    match: /missing icon assertion/ },
  { lang: 'python', form: 'icon-substring-assert', scenario: scenarioIcon,
    body: pythonBody('icon', [`expect(page.get_by_role("img", name="shopping-bag-off")).to_be_visible()`]),
    match: /missing icon assertion/ },

  { lang: 'js', form: 'icon-toBeHidden', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.getByRole('img', { name: 'shopping-bag glyph' })).toBeHidden();`]),
    match: /missing icon assertion/ },
  { lang: 'js', form: 'icon-not-toBeVisible', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.getByRole('img', { name: 'shopping-bag glyph' })).not.toBeVisible();`]),
    match: /missing icon assertion/ },
  { lang: 'js', form: 'icon-not-toHaveAttribute', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.getByRole('img', { name: 'shopping-bag glyph' })).not.toHaveAttribute('aria-label', 'shopping-bag glyph');`]),
    match: /missing icon assertion/ },
  { lang: 'js', form: 'icon-toHaveCount-0', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.getByRole('img', { name: 'shopping-bag glyph' })).toHaveCount(0);`]),
    match: /missing icon assertion/ },
  { lang: 'js', form: 'icon-testid-label', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.getByTestId('label')).toHaveAttribute('aria-label', 'shopping-bag glyph');`]),
    match: /designated icon locator/ },
  { lang: 'js', form: 'icon-testid-header', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.getByTestId('header')).toHaveAttribute('aria-label', 'shopping-bag glyph');`]),
    match: /designated icon locator/ },
  { lang: 'js', form: 'icon-attr-bare-svg', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.locator('svg')).toHaveAttribute('aria-label', 'shopping-bag glyph');`]),
    match: /designated icon locator/ },
  { lang: 'js', form: 'icon-attr-class-header', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.locator('.header')).toHaveAttribute('aria-label', 'shopping-bag glyph');`]),
    match: /designated icon locator/ },
  { lang: 'js', form: 'icon-attr-on-label', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.locator('.label')).toHaveAttribute('aria-label', 'shopping-bag glyph');`]),
    match: /designated icon locator/ },
  { lang: 'csharp', form: 'icon-attr-on-label', scenario: scenarioIcon,
    body: csharpBody('icon', [`await Expect(Page.Locator(".label")).ToHaveAttributeAsync("aria-label", "shopping-bag glyph");`]),
    match: /designated icon locator/ },
  { lang: 'python', form: 'icon-attr-on-label', scenario: scenarioIcon,
    body: pythonBody('icon', [`expect(page.locator(".label")).to_have_attribute("aria-label", "shopping-bag glyph")`]),
    match: /designated icon locator/ },
  { lang: 'js', form: 'icon-attr-on-div', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.locator('div')).toHaveAttribute('aria-label', 'shopping-bag glyph');`]),
    match: /designated icon locator/ },
  { lang: 'js', form: 'icon-attr-on-getByText', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.getByText('${LINE_TEXT}', { exact: true })).toHaveAttribute('aria-label', 'shopping-bag glyph');`]),
    match: /designated icon locator/ },
    { lang: 'js', form: 'icon-data-state-attr', scenario: scenarioIcon,
    body: jsBody('icon', [`await expect(page.locator('.cart-icon')).toHaveAttribute('data-state', 'shopping-bag glyph');`]),
    match: /missing icon assertion/ },
  { lang: 'js', form: 'colour-not-toHaveCSS', scenario: scenarioAllVisual,
    body: jsBody('colour', [`await expect(page.locator('.label')).not.toHaveCSS('color', '#111827');`]),
    match: /missing colour assertion/ },
  { lang: 'js', form: 'font-size-not-toHaveCSS', scenario: scenarioAllVisual,
    body: jsBody('font-size', [`await expect(page.locator('h1')).not.toHaveCSS('font-size', '24px');`]),
    match: /missing font-size assertion/ },
  { lang: 'js', form: 'letter-case-not-toHaveCSS', scenario: scenarioLetterCase,
    body: jsBody('letter-case', [`await expect(page.locator('[data-testid=submit]')).not.toHaveCSS('text-transform', 'uppercase');`]),
    match: /missing letter-case assertion/ },
  { lang: 'js', form: 'letter-case-innerText-next-comment', scenario: scenarioLetterCase,
    body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText('${LINE_TEXT}', { exact: true })).toHaveText('${LINE_TEXT}');
      const text = await page.locator('[data-testid=submit]').innerText();
      // SUBMIT ORDER
      expect(text).toBe('Submit Order');
    });`,
    match: /missing letter-case assertion/ },
  { lang: 'csharp', form: 'icon-Not-ToBeVisibleAsync', scenario: scenarioIcon,
    body: csharpBody('icon', [`await Expect(Page.GetByRole(AriaRole.Img, new() { Name = "shopping-bag glyph" })).Not.ToBeVisibleAsync();`]),
    match: /missing icon assertion/ },
  { lang: 'csharp', form: 'icon-ToHaveCountAsync-0', scenario: scenarioIcon,
    body: csharpBody('icon', [`await Expect(Page.GetByRole(AriaRole.Img, new() { Name = "shopping-bag glyph" })).ToHaveCountAsync(0);`]),
    match: /missing icon assertion/ },
  { lang: 'python', form: 'icon-not-to-be-visible', scenario: scenarioIcon,
    body: pythonBody('icon', [`expect(page.get_by_role("img", name="shopping-bag glyph")).not_to_be_visible()`]),
    match: /missing icon assertion/ },
  { lang: 'python', form: 'letter-case-not-to-have-css', scenario: scenarioLetterCase,
    body: pythonBody('letter-case', [`expect(page.locator("[data-testid=submit]")).not_to_have_css("text-transform", "uppercase")`]),
    match: /missing letter-case assertion/ },
  { lang: 'js', form: 'font-family-substring', scenario: scenarioAllVisual,
    body: jsBody('font-family', [`await expect(page.locator('.body')).toHaveCSS('font-family', 'Inter Tight');`]),
    match: /missing font-family assertion/ },
];

for (const prop of VISUAL_PROPS) {
  for (const lang of PROP_LANGS) {
    REJECTS.push({
      lang,
      form: `missing-${prop.kind}`,
      scenario: scenarioAllVisual,
      body: bodyFor(lang, prop.kind),
      match: new RegExp(`missing ${prop.kind.replace(/-/g, '[- ]')} assertion`),
    });
  }
}

const ACCEPTS = [
  {
    lang: 'csharp',
    body: `[Fact]
    public void QAS_VIS_01() {
      Assert.Equal("${LINE_TEXT}", Page.Locator("h1").InnerText);
    }`,
    scenario: { id: 'QAS-VIS-01', kind: 'automated', expected: LINE_TEXT },
  },
  {
    lang: 'python',
    body: `def test_qas_vis_01():
    assert page.inner_text("h1") == "${LINE_TEXT}"`,
    scenario: { id: 'QAS-VIS-01', kind: 'automated', expected: LINE_TEXT },
  },
];

for (const prop of VISUAL_PROPS) {
  for (const lang of PROP_LANGS) {
    ACCEPTS.push({
      lang,
      form: `bind-${prop.kind}`,
      scenario: scenarioAllVisual,
      body: bodyFor(lang, null),
    });
  }
}

ACCEPTS.push({
  lang: 'js',
  form: 'icon-testid-scenario-designated',
  scenario: scenarioIconDesignated,
  body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText('${LINE_TEXT}', { exact: true })).toHaveText('${LINE_TEXT}');
      await expect(page.getByTestId('cart-glyph')).toHaveAttribute('aria-label', 'shopping-bag glyph');
    });`,
});

ACCEPTS.push({
  lang: 'js',
  form: 'icon-attr-role-img',
  scenario: scenarioIcon,
  body: jsBody('icon', [`await expect(page.getByRole('img', { name: 'shopping-bag glyph' })).toHaveAttribute('aria-label', 'shopping-bag glyph');`]),
});
ACCEPTS.push({
  lang: 'js',
  form: 'icon-attr-test-id',
  scenario: scenarioIcon,
  body: jsBody('icon', [`await expect(page.getByTestId('cart-icon')).toHaveAttribute('aria-label', 'shopping-bag glyph');`]),
});
ACCEPTS.push({
  lang: 'js',
  form: 'icon-attr-svg-data-icon',
  scenario: scenarioIcon,
  body: jsBody('icon', [`await expect(page.locator('svg[data-icon="shopping-bag"]')).toHaveAttribute('aria-label', 'shopping-bag glyph');`]),
});

ACCEPTS.push({
  lang: 'js',
  form: 'bind-letter-case-useInnerText',
  scenario: scenarioLetterCase,
  body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText('${LINE_TEXT}', { exact: true })).toHaveText('${LINE_TEXT}');
      await expect(page.locator('[data-testid=submit]')).toHaveText('SUBMIT ORDER', { useInnerText: true });
    });`,
});

function scenarioForRow(row) {
  if (row.scenario) return row.scenario;
  if (row.form?.startsWith('colour')) return scenarioTextBg;
  return { ...scenarioAllVisual, expected: LINE_TEXT };
}

for (const row of REJECTS) {
  test(`visual reject: ${row.lang} ${row.form}`, () => {
    const scen = scenarioForRow(row);
    const check = validateSourceAssertions(row.body, scen);
    assert.equal(check.ok, false);
    assert.match(check.reason, row.match);
    assert.match(check.reason, /QAS-VIS-01:/);
  });
}

for (const row of ACCEPTS) {
  test(`visual accept: ${row.lang} ${row.form ?? row.scenario.expected.slice(0, 12)}`, () => {
    assert.equal(validateSourceAssertions(row.body, row.scenario).ok, true);
  });
}

test('lexer unit: partial and case-insensitive patterns not in comment spoof', () => {
  const src = `/* assert "x" in y; Assert.Contains("x"); .toLowerCase() */`;
  assert.equal(hasPartialTextMatch(src), false);
  assert.equal(hasCaseInsensitiveTextMatcher(src), false);
  assert.equal(textLocatorMissingExactOption(src, tokenize(src)), false);
});

test('lexer unit: visual value in comment does not bind font-size', () => {
  const body = jsBody('font-size', ['// 24px in comment only']);
  const check = validateSourceAssertions(body, scenarioAllVisual);
  assert.equal(check.ok, false);
  assert.match(check.reason, /missing font-size assertion/);
});
