// Where lessons come from — two sources, deliberately.
//
// SHARED: `skillsets/<topic>/shared/<name>/SKILL.md` in this repo. Portable by
// construction: no hostnames, no home directories, no machine names. Anything
// machine-specific is a `{{PLACEHOLDER}}` resolved from the local overlay.
//
// The `shared/` level is new. The existing layout is
// `skillsets/<topic>/<provider>/<name>/SKILL.md`, which forces a copy per
// provider — the repo already carries near-duplicate `claude/` and `codex/`
// trees. A lesson that is true of every agent should be written once, so it
// lives under `shared/` and the publisher fans it out to each agent's directory.
//
// LOCAL: `~/.config/agent-library/lessons/<name>/SKILL.md`, outside any repo.
// For lessons whose content *is* closed-scope — this setup's own measurements,
// for instance. The framework's own rule is "remove closed-scope details", and
// for some lessons that would remove the lesson. Those stay here rather than
// being scrubbed into a platitude or leaked upstream.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const LOCAL_LESSONS_DIR =
  process.env.AGENT_LIBRARY_LESSONS ??
  path.join(os.homedir(), ".config", "agent-library", "lessons");

function readLessonDirs(root, origin) {
  if (!fs.existsSync(root)) return [];
  return fs
    .readdirSync(root, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => ({
      name: e.name,
      dir: path.join(root, e.name),
      file: path.join(root, e.name, "SKILL.md"),
      origin,
    }))
    .filter((l) => fs.existsSync(l.file));
}

/**
 * Every lesson this machine should publish, shared first.
 *
 * A local lesson with the same name as a shared one wins: the overlay is how a
 * machine corrects or extends the shared library without forking it.
 */
export function collectLessons(repoRoot) {
  const found = new Map();

  const skillsets = path.join(repoRoot, "skillsets");
  if (fs.existsSync(skillsets)) {
    for (const topic of fs.readdirSync(skillsets, { withFileTypes: true })) {
      if (!topic.isDirectory()) continue;
      for (const lesson of readLessonDirs(
        path.join(skillsets, topic.name, "shared"),
        `shared:${topic.name}`,
      )) {
        found.set(lesson.name, lesson);
      }
    }
  }

  for (const lesson of readLessonDirs(LOCAL_LESSONS_DIR, "local")) {
    found.set(lesson.name, lesson);
  }

  return [...found.values()].sort((a, b) => a.name.localeCompare(b.name));
}
