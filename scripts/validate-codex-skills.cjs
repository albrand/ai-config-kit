#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const skillsets = path.join(root, 'skillsets');
const errors = [];
const warnings = [];

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === '__pycache__') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (entry.isFile() && entry.name === 'SKILL.md' && full.includes(`${path.sep}codex${path.sep}`)) out.push(full);
  }
  return out;
}

function parseFrontmatter(text, file) {
  const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
  if (!match) {
    errors.push(`${file}: missing YAML frontmatter`);
    return {};
  }

  const result = {};
  const lines = match[1].split(/\r?\n/);
  for (let i = 0; i < lines.length; i += 1) {
    const keyMatch = lines[i].match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (!keyMatch) continue;
    const [, key, raw] = keyMatch;
    if (['>', '>-', '|', '|-'].includes(raw)) {
      const body = [];
      while (i + 1 < lines.length && /^\s+/.test(lines[i + 1])) {
        i += 1;
        body.push(lines[i].trim());
      }
      result[key] = body.join(raw.startsWith('>') ? ' ' : '\n').trim();
    } else {
      result[key] = raw.replace(/^['"]|['"]$/g, '').trim();
    }
  }
  return result;
}

function validateManifest(skillDir, file) {
  const manifestPath = path.join(skillDir, 'package-manifest.json');
  if (!fs.existsSync(manifestPath)) return;
  let manifest;
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  } catch (error) {
    errors.push(`${manifestPath}: invalid JSON (${error.message})`);
    return;
  }
  if (!Array.isArray(manifest.required) || !Array.isArray(manifest.executable)) {
    errors.push(`${manifestPath}: required and executable must be arrays`);
    return;
  }
  for (const rel of manifest.required) {
    const target = path.resolve(skillDir, rel);
    if (!target.startsWith(`${path.resolve(skillDir)}${path.sep}`)) errors.push(`${manifestPath}: path escapes package root ${rel}`);
    else if (!fs.existsSync(target)) errors.push(`${manifestPath}: missing required file ${rel}`);
  }
  for (const rel of manifest.executable) {
    const target = path.join(skillDir, rel);
    if (fs.existsSync(target) && (fs.statSync(target).mode & 0o111) === 0) errors.push(`${manifestPath}: not executable ${rel}`);
  }
  if (manifest.name && manifest.name !== file.name) errors.push(`${manifestPath}: name does not match SKILL.md (${file.name})`);

  const packaged = [];
  function collect(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === '__pycache__') continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        collect(full);
      } else if (entry.isFile() && full !== manifestPath
                 && !entry.name.endsWith('.pyc') && !entry.name.endsWith('.pyo')) {
        packaged.push(path.relative(skillDir, full));
      }
    }
  }
  collect(skillDir);
  for (const rel of packaged) {
    if (!manifest.required.includes(rel)) errors.push(`${manifestPath}: unlisted package file ${rel}`);
  }
}

function validateOpenAiMetadata(skillDir, file) {
  const metadataPath = path.join(skillDir, 'agents', 'openai.yaml');
  if (!fs.existsSync(metadataPath)) return;
  const text = fs.readFileSync(metadataPath, 'utf8');
  const required = [
    /^interface:\s*$/m,
    /^\s+display_name:\s*.+$/m,
    /^\s+short_description:\s*.+$/m,
    /^\s+default_prompt:\s*.+$/m,
  ];
  if (required.some((pattern) => !pattern.test(text))) errors.push(`${metadataPath}: missing or malformed required OpenAI metadata`);
  if (/^policy:\s*$/m.test(text) && !/^\s+allow_implicit_invocation:\s*(true|false)\s*$/m.test(text)) {
    errors.push(`${metadataPath}: malformed implicit-invocation policy`);
  }
  if (['adaptive-model-orchestrator', 'ai-config-kit-core',
       'cmux-hermes-orchestrator', 'native-agent-surface',
       'plan-arbiter'].includes(file.name)
      && !/^\s+allow_implicit_invocation:\s*false\s*$/m.test(text)) {
    errors.push(`${metadataPath}: behavioral framework skills must be explicit-only`);
  }
}

const files = walk(skillsets).sort();
for (const absolute of files) {
  const relative = path.relative(root, absolute);
  const text = fs.readFileSync(absolute, 'utf8');
  const meta = parseFrontmatter(text, relative);

  if (!meta.name || !/^[a-z0-9-]+$/.test(meta.name) || meta.name.length > 64) errors.push(`${relative}: invalid or missing name`);
  if (!meta.description) errors.push(`${relative}: missing description`);
  else if (meta.description.length > 1024) errors.push(`${relative}: description is ${meta.description.length} characters; maximum is 1024`);
  for (const key of Object.keys(meta)) {
    if (!['name', 'description'].includes(key)) errors.push(`${relative}: unsupported frontmatter key ${key}`);
  }

  const skillDir = path.dirname(absolute);
  const localRefs = [...text.matchAll(/`(references\/[^`\s]+)`/g)].map((match) => match[1].replace(/[.,;:]$/, ''));
  for (const rel of new Set(localRefs)) {
    if (rel.startsWith('references/skill-index.')) continue; // generated by the router
    if (!fs.existsSync(path.join(skillDir, rel))) errors.push(`${relative}: missing bundled reference ${rel}`);
  }
  validateManifest(skillDir, { name: meta.name });
  validateOpenAiMetadata(skillDir, { name: meta.name });
}

if (warnings.length) warnings.forEach((warning) => process.stderr.write(`warning: ${warning}\n`));
if (errors.length) {
  errors.forEach((error) => process.stderr.write(`error: ${error}\n`));
  process.stderr.write(`Codex skill validation failed: ${errors.length} error(s) across ${files.length} skill(s).\n`);
  process.exit(1);
}

process.stdout.write(`Codex skill validation passed: ${files.length} skill(s).\n`);
