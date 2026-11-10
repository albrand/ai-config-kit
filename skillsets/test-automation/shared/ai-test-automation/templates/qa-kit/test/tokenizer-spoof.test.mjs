import test from 'node:test';
import assert from 'node:assert/strict';
import { tokenize } from '../lib/lang-tokenize.mjs';
import { validateSourceAssertions } from '../lib/source-assertions.mjs';

const LINE_A = 'The pending table shows exactly two rows';
const LINE_B = 'The empty icon is visible';
const scenario = { kind: 'automated', expected: `${LINE_A}\n${LINE_B}` };

const SPOOFS = [
  { lang: 'js', form: 'line-comment', body: `// expect(page.getByText('${LINE_A}')).toBeVisible();` },
  { lang: 'js', form: 'line-comment-no-space', body: `//expect(page.getByText('${LINE_A}')).toBeVisible();` },
  { lang: 'js', form: 'line-suffix-comment', body: `const x = 1;//expect(page.getByText('${LINE_A}')).toBeVisible();` },
  { lang: 'js', form: 'block-comment', body: `/* expect(page.getByText('${LINE_A}')).toBeVisible(); */` },
  { lang: 'js', form: 'block-comment-no-space', body: `/*expect(page.getByText('${LINE_A}')).toBeVisible();*/` },
  { lang: 'js', form: 'single-quoted', body: `'expect(page.getByText("${LINE_A}")).toBeVisible()';` },
  { lang: 'js', form: 'double-quoted', body: `"expect(page.getByText('${LINE_A}')).toBeVisible()";` },
  { lang: 'js', form: 'double-escaped-quote', body: `"expect(page.getByText(\\"${LINE_A}\\")).toBeVisible()";` },
  {
    lang: 'js',
    form: 'template-literal',
    body: `\`plan: expect(page.getByText('\${'${LINE_A}'}')).toBeVisible()\`;`,
  },
  {
    lang: 'js',
    form: 'template-nesting',
    body: `\`outer \${'inner expect ${LINE_A}'} \`;`,
  },
  {
    lang: 'js',
    form: 'regex-literal',
    body: `const re = /expect\\(page\\.getByText\\('${LINE_A}'\\)\\)\\.toBeVisible\\(\\)/;`,
  },
  { lang: 'csharp', form: 'line-comment', body: `// Assert.Equal("${LINE_A}", actual);` },
  { lang: 'csharp', form: 'line-comment-no-space', body: `//Assert.Equal("${LINE_A}", actual);` },
  { lang: 'csharp', form: 'block-comment', body: `/* Assert.Equal("${LINE_A}", actual); */` },
  { lang: 'csharp', form: 'block-comment-no-space', body: `/*Assert.Equal("${LINE_A}", actual);*/` },
  { lang: 'csharp', form: 'verbatim', body: `@"Assert.Equal(""${LINE_A}"", actual)";` },
  {
    lang: 'csharp',
    form: 'verbatim-escape',
    body: `@"lead """" Assert.Equal(""${LINE_A}"", actual) tail";`,
  },
  {
    lang: 'csharp',
    form: 'interpolated',
    body: `$"note Assert.Equal(\\"{LINE_A}\\", actual)";`,
  },
  {
    lang: 'csharp',
    form: 'raw-triple',
    body: `"""spoof Assert.Equal("${LINE_A}", actual)""" ;`,
  },
  { lang: 'python', form: 'hash-comment', body: `# assert "${LINE_A}" in page` },
  { lang: 'python', form: 'hash-comment-no-space', body: `#expect(page.getByText('${LINE_A}')).toBeVisible()` },
  { lang: 'python', form: 'hash-suffix-comment', body: `x = 1 #assert "${LINE_A}" in page` },
  { lang: 'python', form: 'single-quoted', body: `'assert "${LINE_A}" in page'` },
  { lang: 'python', form: 'double-quoted', body: `"assert '${LINE_A}' in page"` },
  { lang: 'python', form: 'double-escaped', body: `"assert \\"${LINE_A}\\" in page"` },
  {
    lang: 'python',
    form: 'triple-single',
    body: `'''assert "${LINE_A}" in page'''`,
  },
  {
    lang: 'python',
    form: 'triple-double',
    body: `"""assert "${LINE_A}" in page"""`,
  },
  {
    lang: 'python',
    form: 'triple-escaped-delimiter',
    body: `"""\\""" assert "${LINE_A}" in page \\""" """`,
  },
  {
    lang: 'python',
    form: 'raw-triple-double',
    body: `r"""\""" maybe ${LINE_A} \""" """`,
  },
  { lang: 'python', form: 'raw-single', body: `r'assert "\\'${LINE_A}\\'" in page'` },
];

const REAL = [
  {
    lang: 'js',
    body: `test('QAS-WI-1-01', () => {
      expect(page.getByText('${LINE_A}')).toBeVisible();
      expect(page.getByText('${LINE_B}')).toBeVisible();
    });`,
  },
  {
    lang: 'csharp',
    body: `[Fact]
    public void QAS_WI_1_01() {
      Assert.Equal("${LINE_A}", actual);
      Assert.Equal("${LINE_B}", actual);
    }`,
  },
  {
    lang: 'python',
    body: `def test_qas_wi_1_01():
    assert "${LINE_A}" in page.text
    assert "${LINE_B}" in page.text`,
  },
];

for (const row of SPOOFS) {
  test(`spoof rejected: ${row.lang} ${row.form}`, () => {
    const source = `def stub():\n  pass\n${row.body}`;
    const code = tokenize(source);
    assert.equal(/assert\b|expect\s*\(|Assert\./.test(code), false, 'assertion keyword survives tokenize');
    const tail = `expect(page.getByText('${LINE_B}')).toBeVisible();`;
    const check = validateSourceAssertions(`${row.body}\n${tail}`, scenario);
    assert.equal(check.ok, false);
  });
}

for (const row of REAL) {
  test(`real assertion accepted: ${row.lang}`, () => {
    assert.equal(validateSourceAssertions(row.body, scenario).ok, true);
  });
}
