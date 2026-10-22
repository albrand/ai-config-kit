// A vendored lesson publishes only as pinned; every other lesson still needs verify/verified.
//
// Runs publish.mjs for real, from a copy of scripts/ and one skillset in a
// throwaway root, with HOME pointed at a throwaway directory, so no real home
// is read or written.
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { vendoredPins, vendoredProblems } from './lib/lessons.mjs';

const SCRIPTS = path.dirname(new URL(import.meta.url).pathname);
const ROOT = path.dirname(SCRIPTS);
const WRITING = path.join(ROOT, 'skillsets', 'writing');
const sha = (file) => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const pins = JSON.parse(fs.readFileSync(path.join(WRITING, 'vendored.json'), 'utf8'))['no-ai-slop'].files;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vendored-lessons-'));
process.on('exit', () => fs.rmSync(tmp, { recursive: true, force: true }));

// 1. The pins in vendored.json, install.sh and README.md agree, and match the copy.
const install = fs.readFileSync(path.join(WRITING, 'install.sh'), 'utf8');
const readme = fs.readFileSync(path.join(WRITING, 'README.md'), 'utf8');
for (const [file, digest] of Object.entries(pins)) {
  assert.match(install, new RegExp(`${file.replace('.', '\\.')}\\) echo ${digest} ;;`), `install.sh pin for ${file}`);
  assert.match(readme, new RegExp(`\`${file.replace('.', '\\.')}\` \\|[^|]*\\| \`${digest}\``), `README pin for ${file}`);
  assert.equal(sha(path.join(WRITING, 'shared', 'no-ai-slop', file)), digest, `vendored ${file} digest`);
}

// 2. vendoredPins / vendoredProblems on throwaway lesson directories.
function lessonCopy(name) {
  const dir = path.join(tmp, name, 'skillsets', 'writing', 'shared', 'no-ai-slop');
  fs.mkdirSync(dir, { recursive: true });
  for (const file of Object.keys(pins)) fs.copyFileSync(path.join(WRITING, 'shared', 'no-ai-slop', file), path.join(dir, file));
  fs.copyFileSync(path.join(WRITING, 'vendored.json'), path.join(tmp, name, 'skillsets', 'writing', 'vendored.json'));
  return { name: 'no-ai-slop', dir, file: path.join(dir, 'SKILL.md'), origin: 'shared:writing' };
}
const clean = lessonCopy('unit-clean');
assert.deepEqual(vendoredProblems(clean, vendoredPins(clean)), []);
assert.equal(vendoredPins({ ...clean, origin: 'local' }), null, 'a local lesson of the same name is not vendored');

const drifted = lessonCopy('unit-drifted');
fs.appendFileSync(drifted.file, '\nverify: true\n');
assert.match(vendoredProblems(drifted, vendoredPins(drifted)).join('\n'), /SKILL\.md does not match its pinned digest/);

const extra = lessonCopy('unit-extra');
fs.writeFileSync(path.join(extra.dir, 'notes.md'), 'x');
assert.match(vendoredProblems(extra, vendoredPins(extra)).join('\n'), /unexpected file notes\.md/);

const missing = lessonCopy('unit-missing');
fs.rmSync(path.join(missing.dir, 'eval.md'));
assert.match(vendoredProblems(missing, vendoredPins(missing)).join('\n'), /pinned file eval\.md is missing/);

const linked = lessonCopy('unit-linked');
fs.rmSync(path.join(linked.dir, 'LICENSE'));
fs.symlinkSync(path.join(WRITING, 'shared', 'no-ai-slop', 'LICENSE'), path.join(linked.dir, 'LICENSE'));
assert.match(vendoredProblems(linked, vendoredPins(linked)).join('\n'), /LICENSE is not a regular file/);

// 3. publish.mjs end to end.
function root(name) {
  const r = path.join(tmp, name);
  fs.cpSync(SCRIPTS, path.join(r, 'scripts'), { recursive: true, filter: (p) => !p.includes('__pycache__') });
  fs.cpSync(WRITING, path.join(r, 'skillsets', 'writing'), { recursive: true });
  const home = path.join(r, 'home');
  fs.mkdirSync(home);
  return { r, home };
}
const publish = ({ r, home }, extraEnv = {}) => spawnSync('node', [path.join(r, 'scripts', 'publish.mjs')], {
  encoding: 'utf8',
  env: { PATH: process.env.PATH, HOME: home, ...extraEnv },
});

const ok = root('e2e-pinned');
let run = publish(ok);
assert.equal(run.status, 0, `pinned copy publishes: ${run.stderr}`);
for (const home of ['.agents', '.claude', '.codex', '.bb']) {
  for (const [file, digest] of Object.entries(pins)) {
    assert.equal(sha(path.join(ok.home, home, 'skills', 'no-ai-slop', file)), digest, `${home} ${file} published as pinned`);
  }
}

const bad = root('e2e-drifted');
fs.appendFileSync(path.join(bad.r, 'skillsets', 'writing', 'shared', 'no-ai-slop', 'SKILL.md'), '\nchanged\n');
run = publish(bad);
assert.equal(run.status, 1);
assert.match(run.stderr, /no-ai-slop: SKILL\.md does not match its pinned digest/);
assert.equal(fs.existsSync(path.join(bad.home, '.claude', 'skills', 'no-ai-slop')), false, 'a drifted copy reaches no home');

const ordinary = root('e2e-ordinary');
const local = path.join(ordinary.r, 'local-lessons', 'plain');
fs.mkdirSync(local, { recursive: true });
fs.writeFileSync(path.join(local, 'SKILL.md'), '---\nname: plain\ndescription: An ordinary lesson.\n---\n\n# Plain\n');
run = publish(ordinary, { AGENT_LIBRARY_LESSONS: path.join(ordinary.r, 'local-lessons') });
assert.equal(run.status, 1);
assert.match(run.stderr, /plain: missing "verify"/);
assert.match(run.stderr, /plain: missing "verified"/);

console.log('PASS: vendored pins agree; a pinned copy publishes byte for byte; drift, extra, missing and linked files refuse; an ordinary lesson still needs verify/verified.');
