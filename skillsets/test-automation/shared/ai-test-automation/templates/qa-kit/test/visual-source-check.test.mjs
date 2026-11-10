import test from 'node:test';
import assert from 'node:assert/strict';
import { validateSourceAssertions } from '../lib/source-assertions.mjs';
import { hasCaseInsensitiveTextMatcher, textLocatorMissingExactOption } from '../lib/visual-source-check.mjs';
import { tokenize } from '../lib/lang-tokenize.mjs';

const LINE_A = 'Submit Order';
const scenario = {
  id: 'QAS-VIS-01',
  kind: 'automated',
  expected: `${LINE_A}\nPrimary button colour is #0A5CFF`,
};

const BIND = `await expect(page.getByText('${LINE_A}', { exact: true })).toHaveText('${LINE_A}');`;

const REJECTS = [
  {
    lang: 'js',
    form: 'visibility-only',
    body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText('${LINE_A}', { exact: true })).toBeVisible();
    });`,
    match: /visibility matcher/,
  },
  {
    lang: 'js',
    form: 'getByText-without-exact',
    body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText('${LINE_A}')).toHaveText('${LINE_A}');
    });`,
    match: /exact match/,
  },
  {
    lang: 'js',
    form: 'case-insensitive-regex',
    body: `test('QAS-VIS-01', async () => {
      await expect(page.getByText(/submit order/i)).toHaveText('${LINE_A}');
    });`,
    match: /case-insensitive/,
  },
  {
    lang: 'js',
    form: 'tomatch-insensitive',
    body: `test('QAS-VIS-01', async () => {
      await expect(page.locator('h1')).toHaveText(/submit order/i);
    });`,
    match: /case-insensitive/,
  },
  {
    lang: 'js',
    form: 'comment-spoof-exact',
    body: `// getByText('${LINE_A}', { exact: true })
      test('QAS-VIS-01', async () => { await expect(page.getByRole('table')).toBeVisible(); });`,
    match: /unasserted|visibility|executable/,
  },
  {
    lang: 'js',
    form: 'string-spoof-exact',
    body: `const plan = "getByText('${LINE_A}', { exact: true })";
      test('QAS-VIS-01', async () => { await expect(page.getByRole('table')).toBeVisible(); });`,
    match: /unasserted|executable/,
  },
  {
    lang: 'python',
    form: 'hash-comment-no-space-exact',
    body: `#getByText('${LINE_A}')
      def test_vis(): assert True`,
    match: /unasserted|executable/,
  },
];

const ACCEPTS = [
  {
    lang: 'js',
    body: `test('QAS-VIS-01', async () => {
      ${BIND}
    });`,
  },
  {
    lang: 'csharp',
    body: `[Fact]
    public void QAS_VIS_01() {
      Assert.Equal("${LINE_A}", Page.Locator("[data-testid=cta]").InnerText);
    }`,
  },
  {
    lang: 'python',
    body: `def test_qas_vis_01():
    assert "${LINE_A}" in page.inner_text("h1")`,
  },
];

for (const row of REJECTS) {
  test(`visual reject: ${row.lang} ${row.form}`, () => {
    const check = validateSourceAssertions(row.body, scenario);
    assert.equal(check.ok, false);
    assert.match(check.reason, row.match);
    assert.match(check.reason, /QAS-VIS-01:/);
  });
}

for (const row of ACCEPTS) {
  test(`visual accept: ${row.lang}`, () => {
    if (row.lang === 'js') {
      assert.equal(validateSourceAssertions(row.body, { ...scenario, expected: LINE_A }).ok, true);
      return;
    }
    const oneLine = { ...scenario, expected: LINE_A };
    assert.equal(validateSourceAssertions(row.body, oneLine).ok, true);
  });
}

test('lexer unit: case-insensitive regex not in tokenized comment spoof', () => {
  const src = `/* getByText(/foo/i) */`;
  assert.equal(hasCaseInsensitiveTextMatcher(src), false);
  assert.equal(textLocatorMissingExactOption(src, tokenize(src)), false);
});
