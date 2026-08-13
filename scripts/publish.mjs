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
  }
  return problems;
}

function publishLocal(list) {
  const changes = [];
  for (const target of LOCAL_TARGETS) {
    for (const lesson of list) {
      const destDir = path.join(target.dir, lesson.name);
      const dest = path.join(destDir, "SKILL.md");
      const next = substitute(fs.readFileSync(lesson.file, "utf8"), OVERLAY).text;
      const current = fs.existsSync(dest) ? fs.readFileSync(dest, "utf8") : null;
      if (current === next) continue;
      changes.push(`${current === null ? "add" : "update"} ${target.label}/${lesson.name}`);
      if (check) continue;
      fs.mkdirSync(destDir, { recursive: true });
      fs.writeFileSync(dest, next);
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
function remoteHashes(host, dirs, names) {
  const targets = dirs.flatMap((dir) => names.map((n) => `${dir}/${n}/SKILL.md`));
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

  const existing = remoteHashes(
    host,
    dirs,
    list.map((l) => l.name),
  );

  const changes = [];
  const drifted = [];
  for (const dir of dirs) {
    for (const lesson of list) {
      const body = substitute(fs.readFileSync(lesson.file, "utf8"), OVERLAY).text;
      const want = createHash("md5").update(body).digest("hex");
      const target = `${dir}/${lesson.name}/SKILL.md`;
      const have = existing.get(target);

      if (have === want) continue;
      if (have) drifted.push(`${host}:${target}`);
      changes.push(`${have ? "overwrite" : "add"} ${host}:${dir}/${lesson.name}`);
      if (check) continue;

      // Heredoc with a quoted marker: no expansion, no escaping games.
      // Trim the trailing newline: the heredoc supplies the one before the
      // marker, so passing body verbatim wrote an extra blank line and made
      // every remote copy differ from source on every run.
      const script = `mkdir -p ${dir}/${lesson.name} && cat > ${target} <<'BB_LESSON_EOF'\n${body.replace(/\n$/, "")}\nBB_LESSON_EOF`;
      execFileSync("ssh", [host, script], { stdio: ["ignore", "ignore", "inherit"] });
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
  const { missing } = substitute(fs.readFileSync(lesson.file, "utf8"), OVERLAY);
  if (missing.length > 0) unresolved.set(lesson.name, missing);
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
