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
//
// Publishing is idempotent and one-directional: the repo is the source of
// truth, and a target that has drifted is overwritten. Edit lessons here.

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
        lessonChanged = true;
        if (!have) lessonExisted = false;
        else drifted.push(`${host}:${target}`);
        if (check) continue;

        const mode = (fs.statSync(resource.absolute).mode & 0o111) !== 0 ? "755" : "644";
        const script = `mkdir -p ${path.posix.dirname(target)} && base64 -d > ${target} && chmod ${mode} ${target}`;
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
    console.warn(
      `\nDrift: ${drifted.length} remote copy(ies) differed from the library and ${check ? "would be" : "were"} replaced:`,
    );
    for (const d of drifted) console.warn(`  · ${d}`);
    console.warn("If any of that was a real edit, recover it from the machine before the next run.\n");
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

console.log(`${list.length} lesson(s) validated.`);
if (changes.length === 0) {
  console.log("Everything already up to date.");
} else {
  console.log(check ? "Would change:" : "Published:");
  for (const c of changes) console.log(`  ${c}`);
}
