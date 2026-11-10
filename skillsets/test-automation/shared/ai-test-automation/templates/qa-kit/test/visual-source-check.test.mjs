import test from 'node:test';
import assert from 'node:assert/strict';
import { validateSourceAssertions } from '../lib/source-assertions.mjs';
import { hasCaseInsensitiveTextMatcher, hasPartialTextMatch, textLocatorMissingExactOption } from '../lib/visual-source-check.mjs';
import { tokenize } from '../lib/lang-tokenize.mjs';

const LINE_TEXT = 'Submit Order';
const LINE_COLOUR = 'Primary button colour is #0A5CFF';
const LINE_FONT = 'Body font family is Inter';
const LINE_SIZE = 'Heading font size is 24px';
const LINE_CASE = 'Submit label is shown in uppercase';

const scenarioFull = {
  id: 'QAS-VIS-01',
  kind: 'automated',
  expected: [LINE_TEXT, LINE_COLOUR, LINE_FONT, LINE_SIZE, LINE_CASE].join('\n'),
};

const scenarioTextColour = {
  id: 'QAS-VIS-01',
  kind: 'automated',
  expected: `${LINE_TEXT}\n${LINE_COLOUR}`,
};

const JS_BIND = `await expect(page.getByText('${LINE_TEXT}', { exact: true })).toHaveText('${LINE_TEXT}');
    await expect(page.locator('[data-testid=primary-cta]')).toHaveCSS('background-color', '#0A5CFF');
    await expect(page.locator('.body')).toHaveCSS('font-family', 'Inter');
    await expect(page.locator('h1')).toHaveCSS('font-size', '24px');
    await expect(page.locator('[data-testid=submit]')).toHaveCSS('text-transform', 'uppercase');`;

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
  { lang: 'js', form: 'colour-by-text', body: `test('QAS-VIS-01', async () => {
      ${JS_BIND.split('\n').slice(0, 1).join('\n')}; });`, match: /visual expected line|unasserted/ },
  { lang: 'js', form: 'colour-by-class', body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText('${LINE_TEXT}', { exact: true })).toHaveText('${LINE_TEXT}');
      await expect(page.locator('[data-testid=primary-cta]')).toHaveClass('btn-primary'); });`, match: /visual expected line|class-name/ },
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
];

const ACCEPTS = [
  {
    lang: 'js',
    body: `test('QAS-VIS-01', async () => { ${JS_BIND} });`,
    scenario: scenarioFull,
  },
  {
    lang: 'js',
    body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText('${LINE_TEXT}', { exact: true })).toHaveText('${LINE_TEXT}');
      await expect(page.locator('[data-testid=primary-cta]')).toHaveCSS('background-color', '#0A5CFF');
    });`,
    scenario: scenarioTextColour,
  },
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

for (const row of REJECTS) {
  test(`visual reject: ${row.lang} ${row.form}`, () => {
    const scen = row.form.startsWith('colour') ? scenarioTextColour : { ...scenarioFull, expected: LINE_TEXT };
    const check = validateSourceAssertions(row.body, scen);
    assert.equal(check.ok, false);
    assert.match(check.reason, row.match);
    assert.match(check.reason, /QAS-VIS-01:/);
  });
}

for (const row of ACCEPTS) {
  test(`visual accept: ${row.lang} ${row.scenario.expected.slice(0, 12)}`, () => {
    assert.equal(validateSourceAssertions(row.body, row.scenario).ok, true);
  });
}

test('lexer unit: partial and case-insensitive patterns not in comment spoof', () => {
  const src = `/* assert "x" in y; Assert.Contains("x"); .toLowerCase() */`;
  assert.equal(hasPartialTextMatch(src), false);
  assert.equal(hasCaseInsensitiveTextMatcher(src), false);
  assert.equal(textLocatorMissingExactOption(src, tokenize(src)), false);
});
