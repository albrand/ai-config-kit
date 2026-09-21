#!/usr/bin/env node
// Publish the library into every agent's skill directory.
//
// Skill directories differ by machine AND by agent, and there are more of them
// than the obvious ones — opencode reads ~/.codex/skills and ~/.agents/skills
// per its own config, Claude Code reads ~/.claude/skills, bb reads ~/.bb/skills,
// and a remote machine has its own copy of each. A lesson that only lands where
// Claude looks is invisible to the agent actually doing the work, which is the
// situation this exists to end.
//
// The target list lives in targets.json, not here. Adding a provider must be a
// data change, and the list is deliberately not limited to providers that are
// installed today: a directory that does not exist is created, so an agent
// installed tomorrow finds the library waiting.
//
// Usage:
//   node publish.mjs              publish locally, report what changed
//   node publish.mjs --check      report differences without writing
//   node publish.mjs --remote vps also publish to a machine over ssh
//   node publish.mjs --force      also replace copies edited in place (backed up first)
//
// Publishing is idempotent and one-directional: the repo is the source of
// truth. A target holding an earlier library version is updated; a target
// edited in place (matches no version in git history) is refused and reported,
// exit 3, until it is back-ported or --force backs it up and replaces it.

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { collectLessons } from "./lib/lessons.mjs";
import { loadOverlay, OVERLAY_PATH, substitute } from "./lib/substitute.mjs";

const SCRIPTS = path.dirname(new URL(import.meta.url).pathname);
const ROOT = path.dirname(SCRIPTS);

const CONFIG = JSON.parse(fs.readFileSync(path.join(SCRIPTS, "targets.json"), "utf8"));

/** `~/x` → `/home/me/x`, for local writes only; remote paths stay literal. */
const expand = (p) => p.replace(/^~(?=\/|$)/, os.homedir());

const LOCAL_TARGETS = CONFIG.local.map((t) => ({
  agent: t.agent,
  dir: expand(t.path),
  label: `${t.agent}:${t.path}`,
}));

const REMOTE_TARGETS = CONFIG.remote ?? {};

const OVERLAY = loadOverlay();

const args = new Set(process.argv.slice(2));
const check = args.has("--check");
const force = args.has("--force");

const md5 = (buf) => createHash("md5").update(buf).digest("hex");

/**
 * Every version of a resource the library has ever published, as rendered hashes.
 *
 * "Differs from the library" used to mean "overwrite", which cannot tell an
 * older published copy (safe to replace) from an edit someone made in place
 * (destroyed with nobody told). On 2026-09-21 an in-place orchestrator-lessons
 * edit was one publish away from being erased in all four homes. A copy whose
 * hash matches a version in git history is stale; anything else is an edit.
 */
const knownCache = new Map();
function knownVersions(resource) {
  if (knownCache.has(resource.absolute)) return knownCache.get(resource.absolute);
  const known = new Set([md5(renderedResource(resource))]);
  const rel = path.relative(ROOT, resource.absolute);
  try {
    const shas = execFileSync("git", ["-C", ROOT, "log", "--format=%H", "--", rel], {
      encoding: "utf8",
    }).split("\n").filter(Boolean);
    for (const sha of shas) {
      let body;
      try {
        body = execFileSync("git", ["-C", ROOT, "show", `${sha}:${rel}`]);
      } catch {
        continue;
      }
      known.add(md5(body));
      if (TEXT_RESOURCE_EXTENSIONS.has(path.extname(rel))) {
        known.add(md5(Buffer.from(substitute(body.toString("utf8"), OVERLAY).text, "utf8")));
      }
    }
  } catch {
    // No git history available: only the current version is known, so every
    // differing copy is treated as an edit. Refusing is the safe direction.
  }
  knownCache.set(resource.absolute, known);
  return known;
}

/**
 * The same question when hashes cannot answer it: a copy rendered under an
 * older overlay value (a placeholder whose path moved) matches no current
 * rendering, yet it is still a library version. Match it against every
 * historical source with each {{PLACEHOLDER}} as a one-line wildcard.
 */
const templateCache = new Map();
function historicTemplates(resource) {
  if (templateCache.has(resource.absolute)) return templateCache.get(resource.absolute);
  const rel = path.relative(ROOT, resource.absolute);
  const texts = [fs.readFileSync(resource.absolute, "utf8")];
  try {
    const shas = execFileSync("git", ["-C", ROOT, "log", "--format=%H", "--", rel], {
      encoding: "utf8",
    }).split("\n").filter(Boolean);
    for (const sha of shas) {
      try {
        texts.push(execFileSync("git", ["-C", ROOT, "show", `${sha}:${rel}`], { encoding: "utf8" }));
      } catch {
        // file absent at that commit
      }
    }
  } catch {
    // no history: current source only
  }
  const patterns = texts
    .filter((t) => /\{\{[A-Z0-9_]+\}\}/.test(t))
    .map((t) => new RegExp(
      "^" + t.split(/\{\{[A-Z0-9_]+\}\}/).map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("[^\\n]*?") + "$",
    ));
  templateCache.set(resource.absolute, patterns);
  return patterns;
}

function isKnownVersion(resource, hash, fetchBody) {
  if (knownVersions(resource).has(hash)) return true;
  if (!TEXT_RESOURCE_EXTENSIONS.has(path.extname(resource.relative))) return false;
  const patterns = historicTemplates(resource);
  if (patterns.length === 0) return false;
  const body = fetchBody().toString("utf8");
  return patterns.some((re) => re.test(body));
}

const STAMP = new Date().toISOString().replace(/[:.]/g, "-");
const edited = [];

const lessons = () => collectLessons(ROOT);

const TEXT_RESOURCE_EXTENSIONS = new Set([
  ".cjs", ".js", ".json", ".md", ".mjs", ".py", ".sh", ".toml", ".txt",
  ".yaml", ".yml",
]);

function lessonFiles(lesson) {
  const files = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === ".DS_Store" || entry.name === "__pycache__") continue;
      const absolute = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(absolute);
      else if (entry.isFile()) {
        const relative = path.relative(lesson.dir, absolute);
        if (relative.startsWith("..") || path.isAbsolute(relative)) {
          throw new Error(`${lesson.name}: resource escapes skill directory: ${absolute}`);
        }
        files.push({ absolute, relative });
      }
    }
  };
  walk(lesson.dir);
  return files.sort((a, b) => a.relative.localeCompare(b.relative));
}

function renderedResource(file) {
  const bytes = fs.readFileSync(file.absolute);
  if (!TEXT_RESOURCE_EXTENSIONS.has(path.extname(file.relative))) return bytes;
  return Buffer.from(substitute(bytes.toString("utf8"), OVERLAY).text, "utf8");
}

/**
 * A lesson without a description never fires — skills load by description match.
 * A lesson without `verify` cannot be rechecked and will quietly rot. Both are
 * refusals rather than warnings, because a rotten library is worse than none.
 */
function validate(list) {
  const problems = [];
  for (const lesson of list) {
    const text = fs.readFileSync(lesson.file, "utf8");
    const front = text.match(/^---\n([\s\S]*?)\n---/);
    if (!front) {
      problems.push(`${lesson.name}: no frontmatter`);
      continue;
    }
    for (const key of ["name", "description", "verify", "verified"]) {
      if (!new RegExp(`^${key}:`, "m").test(front[1])) {
        problems.push(`${lesson.name}: missing "${key}"`);
      }
    }
    // An unquoted scalar containing ": " breaks the YAML, and the loader then
    // falls back to the H1 as the description — so the skill still installs and
    // simply never matches anything. Silent, and exactly the class of failure
    // this library exists to stop.
    for (const line of front[1].split("\n")) {
      const kv = line.match(/^([a-zA-Z_]+):\s+(.*)$/);
      if (!kv) continue;
      const value = kv[2];
      const quoted = /^["'].*["']$/.test(value) || value === ">" || value === "|";
      if (!quoted && /:\s/.test(value)) {
        problems.push(
          `${lesson.name}: "${kv[1]}" contains ": " unquoted — wrap the value in quotes or the frontmatter will not parse`,
        );
      }
    }
    // Cheap secret screen. The library is shared across machines, so anything
    // that looks like a credential must never reach it.
    const secret = text.match(
      /\b(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b/,
    );
    if (secret) problems.push(`${lesson.name}: looks like a secret (${secret[1].slice(0, 8)}…)`);
    for (const resource of lessonFiles(lesson)) {
      if (!TEXT_RESOURCE_EXTENSIONS.has(path.extname(resource.relative))) continue;
      const body = fs.readFileSync(resource.absolute, "utf8");
      const resourceSecret = body.match(
        /\b(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b/,
      );
      if (resourceSecret) {
        problems.push(
          `${lesson.name}/${resource.relative}: looks like a secret (${resourceSecret[1].slice(0, 8)}…)`,
        );
      }
    }
  }
  return problems;
}

function publishLocal(list) {
  const changes = [];
  for (const target of LOCAL_TARGETS) {
    for (const lesson of list) {
      const destDir = path.join(target.dir, lesson.name);
      const existed = fs.existsSync(path.join(destDir, "SKILL.md"));
      let lessonChanged = false;
      for (const resource of lessonFiles(lesson)) {
        const dest = path.join(destDir, resource.relative);
        const next = renderedResource(resource);
        const current = fs.existsSync(dest) ? fs.readFileSync(dest) : null;
        if (current?.equals(next)) continue;
        if (current && !isKnownVersion(resource, md5(current), () => current)) {
          edited.push(`${target.label}/${lesson.name}/${resource.relative}`);
          if (!force) continue;
          if (!check) {
            const backup = path.join(os.homedir(), ".cache", "agent-library", "pre-publish", STAMP,
              target.agent, lesson.name, resource.relative);
            fs.mkdirSync(path.dirname(backup), { recursive: true });
            fs.writeFileSync(backup, current);
          }
        }
        lessonChanged = true;
        if (check) continue;
        fs.mkdirSync(path.dirname(dest), { recursive: true });
        fs.writeFileSync(dest, next);
        if ((fs.statSync(resource.absolute).mode & 0o111) !== 0) {
          fs.chmodSync(dest, 0o755);
        }
      }
      if (lessonChanged) {
        changes.push(`${existed ? "update" : "add"} ${target.label}/${lesson.name}`);
      }
    }
  }
  return changes;
}

/**
 * Push to a remote machine over ssh.
 *
 * Deliberately ssh and not a daemon: "spread to the tailnet" must ride transport
 * that already exists. A sync listener on the VPS would be a new inbound
 * service, which is exactly what the operating rules forbid.
 *
 * Reads before it writes. The repo is the source of truth, but enforcing that by
 * blind overwrite means an edit made on the remote machine — a plausible thing
 * for an agent working there to do — is destroyed with nobody told. So we hash
 * what is there first, write only what differs, and report drift loudly.
 *
 * The hashing is one ssh round trip for the whole machine, not one per file.
 */
function remoteHashes(host, targets) {
  // `md5 -q` on macOS, `md5sum` on Linux; emit "<path> <hash>" or nothing.
  const script = targets
    .map(
      (t) =>
        `if [ -f ${t} ]; then printf '%s %s\n' '${t}' "$(md5sum ${t} 2>/dev/null | cut -d' ' -f1 || md5 -q ${t})"; fi`,
    )
    .join("\n");
  const out = execFileSync("ssh", [host, script], { encoding: "utf8" });
  const map = new Map();
  for (const line of out.split("\n")) {
    const [file, hash] = line.trim().split(/\s+/);
    if (file && hash) map.set(file, hash);
  }
  return map;
}

function publishRemote(list, host) {
  const entries = REMOTE_TARGETS[host];
  if (!entries) {
    throw new Error(
      `No targets configured for "${host}". Add it under "remote" in targets.json.`,
    );
  }
  const dirs = entries.map((e) => e.path);

  const targets = dirs.flatMap((dir) =>
    list.flatMap((lesson) =>
      lessonFiles(lesson).map((resource) => `${dir}/${lesson.name}/${resource.relative}`),
    ),
  );
  const existing = remoteHashes(host, targets);

  const changes = [];
  const drifted = [];
  for (const dir of dirs) {
    for (const lesson of list) {
      let lessonChanged = false;
      let lessonExisted = true;
      for (const resource of lessonFiles(lesson)) {
        const body = renderedResource(resource);
        const want = createHash("md5").update(body).digest("hex");
        const target = `${dir}/${lesson.name}/${resource.relative}`;
        const have = existing.get(target);

        if (have === want) continue;
        let backup = "";
        if (have && !isKnownVersion(resource, have,
          () => execFileSync("ssh", [host, `cat ${target}`]))) {
          edited.push(`${host}:${target}`);
          if (!force) continue;
          const saved = `~/.cache/agent-library/pre-publish/${STAMP}/${target.replace(/^~\//, "")}`;
          backup = `mkdir -p ${path.posix.dirname(saved)} && cp ${target} ${saved} && `;
        }
        lessonChanged = true;
        if (!have) lessonExisted = false;
        else drifted.push(`${host}:${target}`);
        if (check) continue;

        const mode = (fs.statSync(resource.absolute).mode & 0o111) !== 0 ? "755" : "644";
        const script = `${backup}mkdir -p ${path.posix.dirname(target)} && base64 -d > ${target} && chmod ${mode} ${target}`;
        execFileSync("ssh", [host, script], {
          input: body.toString("base64"),
          stdio: ["pipe", "ignore", "inherit"],
        });
      }
      if (lessonChanged) {
        changes.push(`${lessonExisted ? "overwrite" : "add"} ${host}:${dir}/${lesson.name}`);
      }
    }
  }

  if (drifted.length > 0) {
    console.log(
      `\n${drifted.length} remote copy(ies) held an earlier library version and ${check ? "would be" : "were"} updated.`,
    );
  }
  return changes;
}

const list = lessons();
if (list.length === 0) {
  console.error("No lessons found.");
  process.exit(1);
}

const problems = validate(list);
if (problems.length > 0) {
  console.error("Refusing to publish:");
  for (const p of problems) console.error(`  · ${p}`);
  process.exit(1);
}

// An unresolved placeholder publishes as-is — the rest of the lesson is still
// useful — but it must be visible, because a `verify` command containing one
// cannot run and the lesson will report as unverifiable.
const unresolved = new Map();
for (const lesson of list) {
  const missing = new Set();
  for (const resource of lessonFiles(lesson)) {
    if (!TEXT_RESOURCE_EXTENSIONS.has(path.extname(resource.relative))) continue;
    const result = substitute(fs.readFileSync(resource.absolute, "utf8"), OVERLAY);
    for (const key of result.missing) missing.add(key);
  }
  if (missing.size > 0) unresolved.set(lesson.name, [...missing]);
}
if (unresolved.size > 0) {
  console.warn(`Unresolved placeholders (add them to ${OVERLAY_PATH}):`);
  for (const [name, keys] of unresolved) console.warn(`  · ${name}: ${keys.join(", ")}`);
  console.warn("");
}

const changes = [...publishLocal(list)];

const remoteFlag = process.argv.indexOf("--remote");
if (remoteFlag !== -1) {
  const host = process.argv[remoteFlag + 1];
  changes.push(...publishRemote(list, host));
}

if (edited.length > 0) {
  console.warn(
    force
      ? `\nEdited in place — backed up to ~/.cache/agent-library/pre-publish/${STAMP}/ on each machine, then overwritten:`
      : "\nEdited in place — matches no version in the library's history, so NOT overwritten:",
  );
  for (const e of edited) console.warn(`  · ${e}`);
  if (!force) {
    console.warn("Back-port the edit into the repo, or rerun with --force to back it up and replace it.\n");
  }
}

console.log(`${list.length} lesson(s) validated.`);
if (changes.length === 0) {
  console.log("Everything already up to date.");
} else {
  console.log(check ? "Would change:" : "Published:");
  for (const c of changes) console.log(`  ${c}`);
}

if (edited.length > 0 && !force) process.exit(3);
