#!/usr/bin/env node
'use strict';

/*
 * Offline selftest for refresh-skill-index.cjs.
 *
 * Proves, with temp fixtures (no real home touched):
 *   1. External agent skills (AGENT_SKILLS_HOME) are indexed with source 'agent'.
 *   2. An external skill's agents/openai.yaml is byte-identical after refresh
 *      (the router never writes into external agent skill directories).
 *   3. The router never creates a policy file inside an external agent skill.
 *   4. Backup directory trees (native-agent-surface.bak.<TIMESTAMP>, *.bak)
 *      are excluded from the scan.
 *   5. Legitimate skill names that merely contain "bak" (e.g. feedback-loop)
 *      are still indexed.
 *
 * Run: node skillsets/skill-library-router/scripts/refresh_skill_index_test.cjs
 */

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SCRIPT_DIR = __dirname;
const REFRESH_PATH = path.join(
  SCRIPT_DIR,
  '..',
  'codex',
  'skill-library-router',
  'scripts',
  'refresh-skill-index.cjs',
);

let failures = 0;
function check(name, cond) {
  if (cond) {
    process.stdout.write(`[ok] ${name}\n`);
  } else {
    failures += 1;
    process.stdout.write(`[FAIL] ${name}\n`);
  }
}

function mkdirp(p) {
  fs.mkdirSync(p, { recursive: true });
}
function writeFile(file, content) {
  mkdirp(path.dirname(file));
  fs.writeFileSync(file, content, 'utf8');
}

function skillFrontmatter(name, description) {
  return `---\nname: ${name}\ndescription: ${description}\n---\n\n# ${name}\n\nBody.\n`;
}

function main() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-router-test-'));
  const codexHome = path.join(tmp, 'codex');
  const agentHome = path.join(tmp, 'agents', 'skills');
  const userSkillRoot = path.join(codexHome, 'skills');

  process.env.CODEX_HOME = codexHome;
  process.env.AGENT_SKILLS_HOME = agentHome;
  // Ensure the ~/.agents default is never consulted.
  process.env.HOME = tmp;

  // --- Seed fixtures --------------------------------------------------------
  // 1. A normal user skill (source 'user').
  writeFile(
    path.join(userSkillRoot, 'my-user-skill', 'SKILL.md'),
    skillFrontmatter('my-user-skill', 'A normal user skill for router tests.'),
  );

  // 2. An external agent skill with an existing openai.yaml (must stay intact).
  const externalSkillDir = path.join(agentHome, 'agent-demo-skill');
  const externalYaml = path.join(externalSkillDir, 'agents', 'openai.yaml');
  const externalYamlBody = [
    'interface:',
    '  display_name: "Agent Demo"',
    '  short_description: "vendor-controlled"',
    '  default_prompt: "run $agent-demo-skill"',
    'policy:',
    '  allow_implicit_invocation: true',
  ].join('\n') + '\n';
  writeFile(path.join(externalSkillDir, 'SKILL.md'),
    skillFrontmatter('agent-demo-skill', 'An external agent skill that must remain vendor-controlled.'));
  writeFile(externalYaml, externalYamlBody);

  // 3. An external agent skill WITHOUT any policy file (must stay absent).
  const noPolicyDir = path.join(agentHome, 'agent-no-policy');
  writeFile(path.join(noPolicyDir, 'SKILL.md'),
    skillFrontmatter('agent-no-policy', 'External agent skill with no policy file.'));

  // 4. A backup tree that mirrors the installer's timestamped sibling backups.
  const backupTs = path.join(agentHome, 'native-agent-surface.bak.20240101T000000Z');
  writeFile(path.join(backupTs, 'SKILL.md'),
    skillFrontmatter('stale-backup-skill', 'Should never be indexed.'));
  // A plain .bak sibling too.
  const backupPlain = path.join(agentHome, 'some-skill.bak');
  writeFile(path.join(backupPlain, 'SKILL.md'),
    skillFrontmatter('stale-plain-bak', 'Should never be indexed.'));

  // 5. A legitimate skill whose name merely contains the substring "bak".
  const legitDir = path.join(agentHome, 'feedback-loop');
  writeFile(path.join(legitDir, 'SKILL.md'),
    skillFrontmatter('feedback-loop', 'Legit skill name containing bak substring.'));

  // --- Require fresh (env is now pointed at temp tree) ----------------------
  delete require.cache[require.resolve(REFRESH_PATH)];
  const refresh = require(REFRESH_PATH);

  // Confirm path wiring before running.
  check('agentSkillsHome points at temp agent root',
    refresh.paths.agentSkillsHome === agentHome);
  check('skillRoot points at temp codex skills',
    refresh.paths.skillRoot === userSkillRoot);

  // Run the refresh (writes the index into the temp router references dir).
  refresh.refreshIndex();

  const index = JSON.parse(fs.readFileSync(refresh.paths.indexJsonPath, 'utf8'));
  const byName = new Map(index.skills.map((s) => [s.name, s]));

  // 1. External skill indexed with source 'agent'.
  const demo = byName.get('agent-demo-skill');
  check('external agent skill is indexed', !!demo);
  check('external agent skill has source=agent', demo && demo.source === 'agent');
  check('external agent skill is hard-marked non-writable',
    demo && demo.writable === false);
  check('external agent skill policy preserved as implicit (vendor-controlled)',
    demo && demo.implicit === true);

  // 2. External openai.yaml byte-identical after refresh.
  const afterYaml = fs.readFileSync(externalYaml, 'utf8');
  check('external agents/openai.yaml byte-identical after refresh',
    afterYaml === externalYamlBody);

  // 3. No policy file created inside the policy-less external skill.
  const noPolicyYaml = path.join(noPolicyDir, 'agents', 'openai.yaml');
  check('router did not create a policy file in external agent skill dir',
    !fs.existsSync(noPolicyYaml));

  // 4. Backup trees excluded.
  check('timestamped backup tree excluded', !byName.has('stale-backup-skill'));
  check('plain .bak backup tree excluded', !byName.has('stale-plain-bak'));

  // 5. Legit "bak"-substring name still indexed.
  const feedback = byName.get('feedback-loop');
  check('legit feedback-loop skill indexed despite bak substring', !!feedback);
  check('feedback-loop indexed as source=agent', feedback && feedback.source === 'agent');

  // 6. Normal user skill still indexed as 'user' (existing behavior unchanged).
  const userSkill = byName.get('my-user-skill');
  check('normal user skill still indexed', !!userSkill);
  check('normal user skill has source=user', userSkill && userSkill.source === 'user');
  check('normal user skill is writable', userSkill && userSkill.writable === true);

  // 7. The write helper itself fails closed even if called directly, so the
  // read-only boundary does not depend only on shouldBeExplicit().
  let rejectedExternalWrite = false;
  try {
    refresh.ensurePolicyFalse(demo);
  } catch (error) {
    rejectedExternalWrite = /refusing policy write/.test(String(error.message));
  }
  check('policy writer rejects external non-writable skill directly',
    rejectedExternalWrite);

  // 8. Backup-name classifier unit checks (boundary cases).
  check('classifier: native-agent-surface.bak.TIMESTAMP is backup',
    refresh.isBackupDirectoryName('native-agent-surface.bak.20240101T000000Z'));
  check('classifier: skill.bak is backup', refresh.isBackupDirectoryName('skill.bak'));
  check('classifier: .bak is backup', refresh.isBackupDirectoryName('.bak'));
  check('classifier: feedback-loop is NOT backup',
    !refresh.isBackupDirectoryName('feedback-loop'));
  check('classifier: bakery is NOT backup',
    !refresh.isBackupDirectoryName('bakery'));
  check('classifier: feedback is NOT backup',
    !refresh.isBackupDirectoryName('feedback'));

  // --- --check passes after a fresh refresh ---------------------------------
  delete require.cache[require.resolve(REFRESH_PATH)];
  // Re-check requires with same env; checkOnly is derived from argv, so call
  // checkIndex directly against a fresh sortSkills to mirror `--check`.
  const recheck = require(REFRESH_PATH);
  let checkOk = true;
  try {
    const origExit = process.exit;
    process.exitCode = undefined;
    // checkIndex sets process.exitCode on failure without throwing.
    recheck.checkIndex(recheck.sortSkills(recheck.scanSkillFiles()));
    checkOk = process.exitCode !== 1;
    process.exitCode = undefined;
    process.exit = origExit;
  } catch (e) {
    checkOk = false;
  }
  check('checkIndex reports ok after refresh', checkOk);

  // No writes leaked into the real home (normalize macOS /var -> /private/var).
  const resolvedTmp = fs.realpathSync(tmp);
  check('temp tree is the only thing written (no real home touched)',
    fs.realpathSync(refresh.paths.indexJsonPath).startsWith(resolvedTmp));

  process.stdout.write(`\n${index.skills.length} skills indexed\n`);
  fs.rmSync(tmp, { recursive: true, force: true });

  if (failures) {
    process.stderr.write(`refresh-skill-index selftest FAILED: ${failures} check(s)\n`);
    process.exit(1);
  }
  process.stdout.write('refresh-skill-index selftest passed\n');
  process.exit(0);
}

main();
