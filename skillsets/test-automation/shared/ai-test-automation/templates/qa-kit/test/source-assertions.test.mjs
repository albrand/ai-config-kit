import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { validateSourceAssertions, validateSourcesForScenarios } from '../lib/source-assertions.mjs';

const scenario = {
  id: 'QAS-WI-1-01',
  kind: 'automated',
  expected: 'The pending table shows exactly two rows\nThe empty icon is visible',
};

test('rejects vacuous assertions and mocks that pre-filter in test source', () => {
  const vacuous = `test('QAS-WI-1-01', () => { expect(true).toBeTruthy(); });`;
  assert.match(validateSourceAssertions(vacuous, scenario).reason, /vacuous/);
  const biased = `test('QAS-WI-1-01', () => {
    mockHttp({ body: { rows: [{ status: 'pending' }, { status: 'pending' }] } });
    expect(screen.getByText('The pending table shows exactly two rows')).toBeTruthy();
  });`;
  assert.match(validateSourceAssertions(biased, scenario).reason, /unasserted|vacuous/);
});

test('requires each expected line string to appear in bound automation', () => {
  const ok = `test('QAS-WI-1-01', () => {
    expect(screen.getByText('The pending table shows exactly two rows')).toBeVisible();
    expect(screen.getByLabelText('empty queue icon')).toBeVisible();
  });`;
  const check = validateSourceAssertions(ok, scenario);
  assert.equal(check.ok, false);
  const fixed = `test('QAS-WI-1-01', () => {
    expect(screen.getByText('The pending table shows exactly two rows')).toBeVisible();
    expect(screen.getByText('The empty icon is visible')).toBeVisible();
  });`;
  assert.equal(validateSourceAssertions(fixed, scenario).ok, true);
});

test('rejects expected text that exists only in comments or unused literals', () => {
  const commented = `// The pending table shows exactly two rows
    test('QAS-WI-1-01', () => { expect(screen.getByRole('table')).toBeVisible(); });`;
  assert.match(validateSourceAssertions(commented, scenario).reason, /executable assertion/);
});

test('rejects bare getByText, getByLabelText, or getByRole without expect matchers', () => {
  const bare = `test('QAS-WI-1-01', () => {
    page.getByText('The pending table shows exactly two rows');
    page.getByLabelText('The empty icon is visible');
    page.getByRole('img', { name: 'The empty icon is visible' });
  });`;
  assert.equal(validateSourceAssertions(bare, scenario).ok, false);
  assert.match(validateSourceAssertions(bare, scenario).reason, /unasserted|executable assertion/);
});

test('rejects locator variables that are never passed to expect with a matcher', () => {
  const assigned = `test('QAS-WI-1-01', () => {
    const row = page.getByText('The pending table shows exactly two rows');
    const icon = page.getByText('The empty icon is visible');
  });`;
  assert.equal(validateSourceAssertions(assigned, scenario).ok, false);
  assert.match(validateSourceAssertions(assigned, scenario).reason, /locator stored|unasserted|executable assertion/);
});

test('accepts expect(locator).matcher and variable locators asserted later', () => {
  const direct = `test('QAS-WI-1-01', async () => {
    await expect(page.getByText('The pending table shows exactly two rows')).toBeVisible();
    await expect(page.getByText('The empty icon is visible')).toBeVisible();
  });`;
  assert.equal(validateSourceAssertions(direct, scenario).ok, true);
  const viaVar = `test('QAS-WI-1-01', async () => {
    const row = page.getByText('The pending table shows exactly two rows');
    const icon = page.getByText('The empty icon is visible');
    await expect(row).toBeVisible();
    await expect(icon).not.toBeVisible();
  });`;
  assert.equal(validateSourceAssertions(viaVar, scenario).ok, true);
});

test('rejects expect() with no matcher chain', () => {
  const naked = `test('QAS-WI-1-01', () => {
    expect(page.getByText('The pending table shows exactly two rows'));
    expect(page.getByText('The empty icon is visible')).toBeVisible();
  });`;
  assert.equal(validateSourceAssertions(naked, scenario).ok, false);
  assert.match(validateSourceAssertions(naked, scenario).reason, /without an assertion matcher/);
});

test('rejects Python docstring with escaped triple-quote spoof', () => {
  const pySpoof = `def test_qas():
    """\\""" assert "The pending table shows exactly two rows" in page
    assert "The empty icon is visible" in page
    """`;
  assert.equal(validateSourceAssertions(pySpoof, scenario).ok, false);
});

test('rejects assertion text in comments across JS, C#, and Python', () => {
  const jsBlock = `test('QAS-WI-1-01', () => {
    /* expect(page.getByText('The pending table shows exactly two rows')).toBeVisible();
       expect(page.getByText('The empty icon is visible')).toBeVisible(); */
    expect(screen.getByRole('table')).toBeVisible();
  });`;
  assert.equal(validateSourceAssertions(jsBlock, scenario).ok, false);

  const csharpComment = `// Assert.Equal("The pending table shows exactly two rows", actual);
    // Assert.Equal("The empty icon is visible", actual);
    test('QAS-WI-1-01', () => {
      expect(screen.getByRole('table')).toBeVisible();
    });`;
  assert.equal(validateSourceAssertions(csharpComment, scenario).ok, false);

  const pythonComment = `# assert "The pending table shows exactly two rows" in page
    # assert "The empty icon is visible" in page
    def test_qas():
      pass`;
  assert.equal(validateSourceAssertions(pythonComment, scenario).ok, false);
});

test('rejects expected lines that appear only inside string literals', () => {
  const spoof = `test('QAS-WI-1-01', () => {
    const plan = 'expect(page.getByText("The pending table shows exactly two rows")).toBeVisible()';
    const more = "The empty icon is visible";
    expect(screen.getByRole('table')).toBeVisible();
  });`;
  assert.equal(validateSourceAssertions(spoof, scenario).ok, false);
  assert.match(validateSourceAssertions(spoof, scenario).reason, /executable assertion|unasserted|locator stored/);
});

test('accepts real Assert.Equal, Python assert, and JS expect bindings', () => {
  const csharp = `[Fact]
    public void QAS_WI_1_01() {
      Assert.Equal("The pending table shows exactly two rows", actual);
      Assert.Equal("The empty icon is visible", actual);
    }`;
  assert.equal(validateSourceAssertions(csharp, scenario).ok, true);

  const python = `def test_qas_wi_1_01():
    assert "The pending table shows exactly two rows" in page.text
    assert "The empty icon is visible" in page.text`;
  assert.equal(validateSourceAssertions(python, scenario).ok, true);

  const js = `test('QAS-WI-1-01', () => {
    expect(page.getByText('The pending table shows exactly two rows')).toBeVisible();
    expect(page.getByText('The empty icon is visible')).toBeVisible();
  });`;
  assert.equal(validateSourceAssertions(js, scenario).ok, true);
});

test('check-scenarios source pass flags changed id missing bindings', () => {
  const dir = mkdtempSync(join(tmpdir(), 'src-assert-'));
  try {
    const path = join(dir, 'case.test.mjs');
    writeFileSync(path, `test('QAS-WI-1-02', () => expect(true).toBeTruthy());`);
    const rows = validateSourcesForScenarios(
      [path],
      new Map([[ 'QAS-WI-1-02', { ...scenario, id: 'QAS-WI-1-02' } ]]),
      new Set(['QAS-WI-1-02']),
    );
    assert.equal(rows.length, 1);
    assert.equal(rows[0].ok, false);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
