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
