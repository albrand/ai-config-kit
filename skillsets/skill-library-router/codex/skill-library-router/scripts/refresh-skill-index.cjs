const fs = require('fs');
const os = require('os');
const path = require('path');

const checkOnly = process.argv.includes('--check');
const codexHome = process.env.CODEX_HOME || path.join(os.homedir(), '.codex');
const skillRoot = path.join(codexHome, 'skills');
const systemSkillRoot = path.join(skillRoot, '.system');
const pluginCacheRoot = path.join(codexHome, 'plugins', 'cache');
const routerRoot = path.join(skillRoot, 'skill-library-router');
const referencesDir = path.join(routerRoot, 'references');
const indexJsonPath = path.join(referencesDir, 'skill-index.json');
const indexMdPath = path.join(referencesDir, 'skill-index.md');
const policySummaryPath = path.join(referencesDir, 'applied-policy-summary.json');

// External agent skills root (e.g. ~/.agents/skills), surfaced read-only with
// source 'agent'. These skills remain vendor policy-controlled: the router
// indexes them but NEVER writes a policy file into them and NEVER passes them
// to ensurePolicyFalse. Overrides via AGENT_SKILLS_HOME; default ~/.agents/skills.
const agentSkillsHome = process.env.AGENT_SKILLS_HOME || path.join(os.homedir(), '.agents', 'skills');

const explicitOnlyUserSkillNames = new Set([
  // Specialized / heavy workflows — router-accessible on demand.
  'adaptive-model-orchestrator',
  'ai-config-kit-core',
  'assess-then-harden',
  'figma',
  'plan-module-delivery',
  'roadmap-terraform',
  'tech-terraform',
  'ux-design-agent',
  // Behavioral framework skills: their always-on behavior is already encoded in
  // the root directive (AGENTS.md / GLOBAL_AGENTS.md, loaded every prompt), so
  // preloading their metadata is redundant. Keep them router-accessible as
  // detailed expansions. Names not present in a given install are harmless.
  'always-deep-plan-delegate',
  'harness-routing',
  'mcp-routing',
  'token-efficiency',
  'big-change-planning',
  'quality-convergence',
  'verification-before-completion',
  'systematic-debugging',
  'cross-agent-coordination',
  'high-signal-pr-review',
  'preparing-prs',
  'repo-agents-discovery',
  'repo-session-journal',
]);

const explicitOnlySystemSkillNames = new Set(['plugin-creator', 'skill-installer']);
const pluginImplicitExceptions = new Set(['knowledge-update']);
// 'upstream' skips the bundled upstream SKILL.md copies some plugins ship
// (e.g. Vercel) which otherwise create duplicate-named, ambiguous router entries.
const skippedDirectoryNames = new Set(['.git', 'node_modules', 'upstream']);
const pluginManifestDirectoryNames = new Set(['.claude-plugin', '.codex-plugin', '.cursor-plugin']);

// Backup directory patterns produced by installers/tools (e.g.
// `native-agent-surface.bak.20240101T000000Z`, `skill.bak`). Excluded from
// recursive scans. Matched on whole-segment names only so legitimate skill names
// that merely contain the substring "bak" (e.g. `feedback-loop`, `bakery`) are
// never excluded.
function isBackupDirectoryName(name) {
  if (typeof name !== 'string' || name.length === 0) return false;
  if (name === '.bak') return true;
  // Whole-segment backup names only: ends with ".bak", contains ".bak."
  // (timestamped siblings like native-agent-surface.bak.20240101T000000Z),
  // or ".bak_<ts>". Legitimate skill names that merely contain the substring
  // "bak" (e.g. feedback-loop, bakery) are never excluded.
  if (/(^|\.)bak$/i.test(name)) return true;
  if (/\.bak\./i.test(name)) return true;
  if (/\.bak_/i.test(name)) return true;
  return false;
}
const routingStopWords = new Set([
  'a',
  'about',
  'after',
  'all',
  'an',
  'and',
  'any',
  'are',
  'as',
  'at',
  'be',
  'by',
  'can',
  'code',
  'codex',
  'for',
  'from',
  'has',
  'have',
  'in',
  'into',
  'is',
  'it',
  'its',
  'of',
  'on',
  'or',
  'that',
  'the',
  'this',
  'to',
  'use',
  'when',
  'with',
  'work',
  'working',
]);
const routingSynonyms = new Map([
  ['audit', ['review', 'inspect']],
  ['build', ['create', 'generate', 'make']],
  ['create', ['build', 'generate', 'make']],
  ['debug', ['diagnose', 'fix', 'troubleshoot']],
  ['deck', ['presentation', 'slide', 'slides']],
  ['deploy', ['deployment', 'release']],
  ['diagnose', ['debug', 'fix', 'troubleshoot']],
  ['fix', ['debug', 'diagnose', 'troubleshoot']],
  ['generate', ['build', 'create', 'make']],
  ['make', ['build', 'create', 'generate']],
  ['powerpoint', ['deck', 'presentation', 'slide', 'slides']],
  ['pptx', ['deck', 'presentation', 'slide', 'slides']],
  ['presentation', ['deck', 'slide', 'slides']],
  ['review', ['audit', 'inspect']],
  ['slide', ['deck', 'presentation']],
  ['slides', ['deck', 'presentation']],
  ['troubleshoot', ['debug', 'diagnose', 'fix']],
]);

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function writeFile(file, content) {
  ensureDir(path.dirname(file));
  fs.writeFileSync(file, content, 'utf8');
}

function isInside(file, dir) {
  const relative = path.relative(dir, file);
  return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative);
}

function walkForSkillFiles(dir, out) {
  if (!fs.existsSync(dir)) return;

  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (skippedDirectoryNames.has(entry.name)) continue;
    if (entry.isDirectory() && isBackupDirectoryName(entry.name)) continue;

    const fullPath = path.join(dir, entry.name);

    if (entry.isDirectory()) {
      walkForSkillFiles(fullPath, out);
      continue;
    }

    if (entry.isFile() && entry.name === 'SKILL.md') out.push(fullPath);
  }
}

function walkForPluginManifests(dir, out) {
  if (!fs.existsSync(dir)) return;

  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (skippedDirectoryNames.has(entry.name)) continue;
    if (entry.isDirectory() && isBackupDirectoryName(entry.name)) continue;

    const fullPath = path.join(dir, entry.name);

    if (entry.isDirectory()) {
      walkForPluginManifests(fullPath, out);
      continue;
    }

    const manifestDir = path.basename(path.dirname(fullPath));

    if (entry.isFile() && entry.name === 'plugin.json' && pluginManifestDirectoryNames.has(manifestDir)) {
      out.push(fullPath);
    }
  }
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function pluginSkillRoots() {
  const manifests = [];
  walkForPluginManifests(pluginCacheRoot, manifests);

  const roots = [];

  for (const manifestPath of manifests) {
    try {
      const manifest = readJson(manifestPath);

      if (!manifest.skills) continue;

      const pluginRoot = path.dirname(path.dirname(manifestPath));
      roots.push(path.resolve(pluginRoot, manifest.skills));
    } catch (_error) {
      continue;
    }
  }

  return roots;
}

function scanSkillFiles() {
  const files = [];
  walkForSkillFiles(skillRoot, files);

  for (const root of pluginSkillRoots()) {
    walkForSkillFiles(root, files);
  }

  // External agent skills root: indexed read-only with source 'agent'. The
  // agent root is disjoint from the codex skillRoot by default; if an operator
  // configures an agent root that nests inside skillRoot/plugin cache, the
  // path-based source resolver below still prefers the more specific codex
  // roots so ownership stays unambiguous.
  if (agentSkillsHome && fs.existsSync(agentSkillsHome)) {
    walkForSkillFiles(agentSkillsHome, files);
  }

  return Array.from(new Set(files)).sort();
}

function parseFrontmatter(text) {
  const match = text.match(/^---\n([\s\S]*?)\n---/);
  return match ? match[1] : '';
}

function readYamlScalar(frontmatter, key) {
  const lines = frontmatter.split(/\n/);
  const index = lines.findIndex((line) => line.startsWith(`${key}:`));

  if (index === -1) return '';

  const raw = lines[index].slice(key.length + 1).trim();

  if (raw === '|' || raw === '>-' || raw === '>') {
    const body = [];

    for (let i = index + 1; i < lines.length; i += 1) {
      if (/^[A-Za-z0-9_-]+:/.test(lines[i])) break;
      body.push(lines[i].replace(/^\s+/, ''));
    }

    return body.join(' ').trim();
  }

  return raw.replace(/^['"]|['"]$/g, '').trim();
}

function unique(values) {
  const seen = new Set();
  const out = [];

  for (const value of values) {
    const normalized = String(value || '').trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    out.push(normalized);
  }

  return out;
}

function expandWordForms(words) {
  const out = [];

  for (const word of words) {
    out.push(word);

    if (!/^[a-z0-9-]+$/.test(word) || word.length <= 3) continue;

    if (word.endsWith('ies') && word.length > 4) {
      out.push(`${word.slice(0, -3)}y`);
    } else if (word.endsWith('s') && !/(ss|is|us)$/.test(word)) {
      out.push(word.slice(0, -1));
    } else {
      out.push(`${word}s`);
    }

    if (word.endsWith('ing') && word.length > 5) {
      out.push(word.slice(0, -3));
    }

    out.push(...(routingSynonyms.get(word) || []));
  }

  return unique(out);
}

function wordsFrom(value) {
  return expandWordForms(unique(
    String(value || '')
      .toLowerCase()
      .replace(/[`'"()[\]{}<>]/g, ' ')
      .split(/[^a-z0-9@$_:.+#-]+/)
      .map((word) => word.trim().replace(/^[._:+#/-]+|[._:+#/-]+$/g, ''))
      .filter((word) => word.length > 1)
      .filter((word) => !routingStopWords.has(word))
      .filter((word) => !/^v?\d+(\.\d+){0,4}$/.test(word)),
  ));
}

function handlesFrom(value) {
  const handles = [];
  const matcher = /(^|[\s`'"(])([$@/][A-Za-z0-9][A-Za-z0-9_.:/-]*)/g;
  let match;

  while ((match = matcher.exec(String(value || ''))) !== null) {
    handles.push(match[2]);
  }

  return unique(handles);
}

function sourceFor(file) {
  return rootDescriptorFor(file).source;
}

function rootDescriptors() {
  // Most-specific roots come first so nested system/plugin roots cannot be
  // mistaken for the general user root. Writable is an ownership boundary,
  // not merely a policy preference.
  return [
    { root: systemSkillRoot, source: 'system', writable: true },
    { root: pluginCacheRoot, source: 'plugin', writable: true },
    { root: skillRoot, source: 'user', writable: true },
    { root: agentSkillsHome, source: 'agent', writable: false },
  ].filter((descriptor) => descriptor.root);
}

function rootDescriptorFor(file) {
  return rootDescriptors().find((descriptor) => isInside(file, descriptor.root))
    || { root: null, source: 'unknown', writable: false };
}

function pluginFor(file) {
  if (!isInside(file, pluginCacheRoot)) return null;

  const parts = path.relative(pluginCacheRoot, file).split(path.sep);

  if (parts.length < 3) return parts[0] || null;

  return `${parts[0]}/${parts[1]}/${parts[2]}`;
}

function pluginShortName(plugin) {
  if (!plugin) return null;

  const parts = plugin.split('/').filter(Boolean);

  return parts.length > 1 ? parts[1] : parts[0] || null;
}

function aliasesFor(name, file, plugin) {
  const baseNames = unique([name, path.basename(path.dirname(file))]);
  const pluginName = pluginShortName(plugin);
  const aliases = [];

  for (const baseName of baseNames) {
    aliases.push(baseName, `$${baseName}`, `@${baseName}`, `/${baseName}`);

    if (pluginName) {
      aliases.push(
        `${pluginName}:${baseName}`,
        `@${pluginName}:${baseName}`,
        `${pluginName}/${baseName}`,
        `@${pluginName}/${baseName}`,
      );
    }
  }

  if (pluginName) aliases.push(pluginName, `@${pluginName}`);

  return unique(aliases);
}

function routingTermsFor({ aliases, description, file, name, plugin, relativePath, source }) {
  return unique([
    ...aliases,
    ...handlesFrom(description),
    ...wordsFrom(name),
    ...wordsFrom(description),
    ...wordsFrom(source),
    ...wordsFrom(plugin),
    ...wordsFrom(relativePath),
    ...wordsFrom(path.dirname(file).split(path.sep).slice(-3).join(' ')),
  ]).slice(0, 120);
}

function searchTextFor({ aliases, description, name, plugin, relativePath, routingTerms, source }) {
  return unique([
    ...routingTerms,
    ...aliases,
    ...wordsFrom(name),
    ...wordsFrom(description),
    ...wordsFrom(plugin),
    ...wordsFrom(relativePath),
    source,
  ]).join(' ');
}

function readPolicy(skillFile) {
  const policyFile = path.join(path.dirname(skillFile), 'agents', 'openai.yaml');

  if (!fs.existsSync(policyFile)) return { implicit: true, policyFile };

  const text = fs.readFileSync(policyFile, 'utf8');
  const match = text.match(/allow_implicit_invocation:\s*(true|false)/);

  return { implicit: match ? match[1] === 'true' : true, policyFile };
}

function skillRecord(file) {
  const text = fs.readFileSync(file, 'utf8');
  const frontmatter = parseFrontmatter(text);
  const name = readYamlScalar(frontmatter, 'name') || path.basename(path.dirname(file));
  const description = readYamlScalar(frontmatter, 'description');
  const policy = readPolicy(file);
  const rootDescriptor = rootDescriptorFor(file);
  const source = rootDescriptor.source;
  const plugin = pluginFor(file);
  const relativePath = path.relative(codexHome, file);
  const aliases = aliasesFor(name, file, plugin);
  const routingTerms = routingTermsFor({
    aliases,
    description,
    file,
    name,
    plugin,
    relativePath,
    source,
  });

  return {
    name,
    description,
    path: file,
    relativePath,
    source,
    writable: rootDescriptor.writable,
    plugin,
    aliases,
    routingTerms,
    searchText: searchTextFor({
      aliases,
      description,
      name,
      plugin,
      relativePath,
      routingTerms,
      source,
    }),
    implicit: policy.implicit,
    policyPath: policy.policyFile,
    bodyLines: text.split(/\n/).length,
    descriptionChars: description.length,
  };
}

function shouldBeExplicit(skill) {
  if (skill.name === 'skill-library-router') return false;
  // Read-only roots remain vendor policy-controlled. Their current policy is
  // indexed as-is, but they are never candidates for mutation.
  if (!skill.writable) return false;
  if (skill.source === 'plugin') return !pluginImplicitExceptions.has(skill.name);
  if (skill.source === 'system') return explicitOnlySystemSkillNames.has(skill.name);
  if (skill.source === 'user') return explicitOnlyUserSkillNames.has(skill.name);
  return false;
}

function ensurePolicyFalse(skill) {
  if (!skill || skill.writable !== true) {
    throw new Error('refusing policy write outside a writable skill root');
  }
  const agentPath = path.join(path.dirname(skill.path), 'agents', 'openai.yaml');
  ensureDir(path.dirname(agentPath));

  if (!fs.existsSync(agentPath)) {
    writeFile(agentPath, 'policy:\n  allow_implicit_invocation: false\n');
    return 'created';
  }

  const text = fs.readFileSync(agentPath, 'utf8');

  if (/allow_implicit_invocation:\s*false/.test(text)) return 'unchanged';

  if (/allow_implicit_invocation:\s*true/.test(text)) {
    fs.writeFileSync(
      agentPath,
      text.replace(/allow_implicit_invocation:\s*true/, 'allow_implicit_invocation: false'),
      'utf8',
    );

    return 'updated';
  }

  const separator = text.endsWith('\n') ? '\n' : '\n\n';
  fs.writeFileSync(agentPath, `${text}${separator}policy:\n  allow_implicit_invocation: false\n`, 'utf8');

  return 'updated';
}

function sortSkills(files) {
  return files
    .map(skillRecord)
    .sort((a, b) => a.name.localeCompare(b.name) || a.relativePath.localeCompare(b.relativePath));
}

function escapeTableCell(value) {
  return String(value || '').replace(/\|/g, '/');
}

function skillIndexMarkdown(skills) {
  const lines = [
    '# Skill Library Index',
    '',
    'Generated by skill-library-router/scripts/refresh-skill-index.cjs.',
    '',
    '| Skill | Source | Mode | Plugin | Path | Description |',
    '| --- | --- | --- | --- | --- | --- |',
  ];

  for (const skill of skills) {
    const mode = skill.implicit ? 'implicit' : 'explicit';
    lines.push(
      `| ${escapeTableCell(skill.name)} | ${skill.source} | ${mode} | ${escapeTableCell(skill.plugin)} | ${escapeTableCell(skill.path)} | ${escapeTableCell(skill.description)} |`,
    );
  }

  lines.push('');

  return lines.join('\n');
}

function policySummary(skills, policyChanges) {
  return {
    generatedAt: new Date().toISOString(),
    explicitOnlyUserSkillNames: Array.from(explicitOnlyUserSkillNames).sort(),
    explicitOnlySystemSkillNames: Array.from(explicitOnlySystemSkillNames).sort(),
    pluginImplicitExceptions: Array.from(pluginImplicitExceptions).sort(),
    explicitPluginSkillsExceptExceptions: true,
    implicitSkills: skills.filter((skill) => skill.implicit).map((skill) => skill.name).sort(),
    explicitSkills: skills.filter((skill) => !skill.implicit).map((skill) => skill.name).sort(),
    policyChanges,
  };
}

function indexPayload(skills) {
  return {
    generatedAt: new Date().toISOString(),
    count: skills.length,
    skills,
  };
}

function compareSkills(leftSkills, rightSkills) {
  return JSON.stringify(leftSkills) === JSON.stringify(rightSkills);
}

function checkIndex(skills) {
  const missingFiles = [indexJsonPath, indexMdPath, policySummaryPath].filter((file) => !fs.existsSync(file));
  const explicitPolicyIssues = skills.filter((skill) => shouldBeExplicit(skill) && skill.implicit);
  const existing = fs.existsSync(indexJsonPath) ? readJson(indexJsonPath) : { skills: [] };
  const staleIndex = !compareSkills(existing.skills || [], skills);

  const status = {
    ok: missingFiles.length === 0 && explicitPolicyIssues.length === 0 && !staleIndex,
    totalSkills: skills.length,
    implicitCount: skills.filter((skill) => skill.implicit).length,
    explicitCount: skills.filter((skill) => !skill.implicit).length,
    missingFiles,
    explicitPolicyIssues: explicitPolicyIssues.map((skill) => ({
      name: skill.name,
      source: skill.source,
      plugin: skill.plugin,
      path: skill.path,
      policyPath: skill.policyPath,
    })),
    staleIndex,
  };

  console.log(JSON.stringify(status, null, 2));

  if (!status.ok) process.exitCode = 1;
}

function refreshIndex() {
  const initialSkills = sortSkills(scanSkillFiles());
  const policyChanges = [];

  for (const skill of initialSkills) {
    if (!shouldBeExplicit(skill)) continue;

    const result = ensurePolicyFalse(skill);
    policyChanges.push({
      name: skill.name,
      source: skill.source,
      plugin: skill.plugin,
      path: skill.path,
      result,
    });
  }

  const skills = sortSkills(scanSkillFiles());
  const payload = indexPayload(skills);
  const summary = policySummary(skills, policyChanges);

  writeFile(indexJsonPath, `${JSON.stringify(payload, null, 2)}\n`);
  writeFile(indexMdPath, skillIndexMarkdown(skills));
  writeFile(policySummaryPath, `${JSON.stringify(summary, null, 2)}\n`);

  console.log(JSON.stringify({
    totalSkills: skills.length,
    implicitCount: skills.filter((skill) => skill.implicit).length,
    explicitCount: skills.filter((skill) => !skill.implicit).length,
    policyChanges: policyChanges.length,
    indexPath: indexJsonPath,
  }, null, 2));
}

function run() {
  if (checkOnly) {
    checkIndex(sortSkills(scanSkillFiles()));
  } else {
    refreshIndex();
  }
}

// Exported for offline testing (temp-home fixtures). Path constants are computed
// from CODEX_HOME / AGENT_SKILLS_HOME at require time, so tests set those env
// vars before requiring this module fresh.
module.exports = {
  run,
  scanSkillFiles,
  sortSkills,
  skillRecord,
  sourceFor,
  rootDescriptors,
  rootDescriptorFor,
  shouldBeExplicit,
  ensurePolicyFalse,
  isBackupDirectoryName,
  refreshIndex,
  checkIndex,
  paths: {
    codexHome,
    skillRoot,
    systemSkillRoot,
    pluginCacheRoot,
    agentSkillsHome,
    routerRoot,
    referencesDir,
    indexJsonPath,
    indexMdPath,
    policySummaryPath,
  },
};

if (require.main === module) {
  run();
}
