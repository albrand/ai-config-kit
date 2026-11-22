import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import schema from '../lib/artifact-schema.v1.json' with { type: 'json' };

const kit = resolve(import.meta.dirname, '..');
const schemaFile = resolve(kit, 'lib/artifact-schema.v1.json');
const allowedOpenObjects = new Map();
const supported = new Set(['$schema','$id','oneOf','$ref','$defs','type','additionalProperties','required','properties','const','enum','pattern','format','minLength','minItems','minimum','uniqueItems','items','allOf','if','then','description']);

function validate(schemaNode, value, root = schema) {
  for (const key of Object.keys(schemaNode)) assert.ok(supported.has(key), `unsupported JSON Schema keyword: ${key}`);
  if (schemaNode.$ref) return validate(schemaNode.$ref.split('/').slice(2).reduce((node, key) => node[key], root), value, root);
  const errors = [];
  const type = Array.isArray(value) ? 'array' : value === null ? 'null' : typeof value;
  const types = schemaNode.type ? (Array.isArray(schemaNode.type) ? schemaNode.type : [schemaNode.type]) : [];
  if (types.length && !types.includes(type) && !(types.includes('integer') && typeof value === 'number' && Number.isInteger(value))) errors.push('type');
  if (schemaNode.const !== undefined && value !== schemaNode.const) errors.push('const');
  if (schemaNode.enum && !schemaNode.enum.includes(value)) errors.push('enum');
  if (schemaNode.pattern && (typeof value !== 'string' || !new RegExp(schemaNode.pattern).test(value))) errors.push('pattern');
  if (schemaNode.minLength !== undefined && value.length < schemaNode.minLength) errors.push('minLength');
  if (schemaNode.minItems !== undefined && value.length < schemaNode.minItems) errors.push('minItems');
  if (schemaNode.minimum !== undefined && value < schemaNode.minimum) errors.push('minimum');
  if (schemaNode.uniqueItems && new Set(value.map(item => JSON.stringify(item))).size !== value.length) errors.push('uniqueItems');
  if (schemaNode.format === 'uri' && (typeof value !== 'string' || !/^https?:\/\//.test(value))) errors.push('format:uri');
  if (schemaNode.format === 'date-time' && (typeof value !== 'string' || Number.isNaN(Date.parse(value)))) errors.push('format:date-time');
  if (schemaNode.format === 'date' && (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value))) errors.push('format:date');
  if (type === 'object') {
    for (const key of schemaNode.required ?? []) if (!(key in value)) errors.push(`required:${key}`);
    for (const [key, child] of Object.entries(value)) {
      if (!schemaNode.properties?.[key]) { if (schemaNode.additionalProperties === false) errors.push(`additional:${key}`); }
      else errors.push(...validate(schemaNode.properties[key], child, root));
    }
  }
  if (type === 'array') for (const item of value) errors.push(...validate(schemaNode.items ?? {}, item, root));
  for (const child of schemaNode.allOf ?? []) errors.push(...validate(child, value, root));
  if (schemaNode.if && validate(schemaNode.if, value, root).length === 0 && schemaNode.then) errors.push(...validate(schemaNode.then, value, root));
  if (schemaNode.oneOf && schemaNode.oneOf.filter(choice => validate(choice, value, root).length === 0).length !== 1) errors.push('oneOf');
  return errors;
}

function assertClosed(node, path = '$') {
  for (const [key, child] of Object.entries(node)) {
    const childPath = `${path}/${key}`;
    if (!child || typeof child !== 'object') continue;
    if (child.type === 'object' && child.additionalProperties !== false) {
      assert.ok(allowedOpenObjects.has(childPath), `open object schema at ${childPath} needs an explicit allowlist reason`);
      assert.match(allowedOpenObjects.get(childPath), /\S/);
    }
    assertClosed(child, childPath);
  }
}

test('every object schema is closed unless explicitly allowlisted with a reason', () => assertClosed(schema));

test('CLI run path parses runner output into a schema-valid run artifact and rejects unknown result fields', () => {
  const dir = mkdtempSync(resolve(tmpdir(), 'qa-run-schema-'));
  try {
    const junit = resolve(dir, 'results.xml');
    const output = resolve(dir, 'run.json');
    const config = resolve(dir, 'qa.config.json');
    writeFileSync(junit, '<testsuite><testcase name="QAS-WI-123-01"/></testsuite>');
    writeFileSync(config, JSON.stringify({
      compileCommand: [process.execPath, '-e', 'process.exit(0)'],
      discoverCommand: [process.execPath, '-e', 'console.log("QAS-WI-123-01")'],
      testCommand: [process.execPath, '-e', 'process.exit(0)'],
      resultFormat: 'junit', resultPath: junit, runner: 'junit5', resultsFile: output
    }));
    const run = spawnSync(process.execPath, [resolve(kit, 'bin/qa.mjs'), 'test', '--config', config, '--commit', 'a'.repeat(40), '--plan-hash', `sha256:${'b'.repeat(64)}`], { cwd: dir, encoding: 'utf8', env: { ...process.env, GITHUB_SHA: 'a'.repeat(40) } });
    assert.equal(run.status, 0, run.stderr);
    const artifact = JSON.parse(readFileSync(output, 'utf8'));
    assert.deepEqual(validate(schema.$defs.run, artifact), []);
    const tampered = structuredClone(artifact);
    tampered.results[0].untrusted = true;
    assert.ok(validate(schema.$defs.run, tampered).includes('additional:untrusted'));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
