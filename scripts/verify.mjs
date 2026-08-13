#!/usr/bin/env node
// Recheck every lesson's falsifiable claim.
//
// A library that only grows is a liability. The failure this guards against is
// real and already happened here: a memory indexed as "VPS enrollment is blocked
// on the tailnet ACL" survived long after the VPS was enrolled and working, and
// would have sent the next agent down a dead path with full confidence.
//
// So every lesson carries a `verify:` command that proves it still describes the
// world. This runs them and reports what can no longer be confirmed. It does not
// delete anything — a failing check means "a human or a reviewer should look",
// not "this is false"; the command itself may have rotted.
//
// Usage:
//   node verify.mjs           run every check
//   node verify.mjs --stale 90  also flag lessons not verified in N days

import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { collectLessons } from "./lib/lessons.mjs";
import { loadOverlay, substitute } from "./lib/substitute.mjs";

const SCRIPTS = path.dirname(new URL(import.meta.url).pathname);
const ROOT = path.dirname(SCRIPTS);

const staleFlag = process.argv.indexOf("--stale");
const staleDays = staleFlag === -1 ? null : Number(process.argv[staleFlag + 1] ?? 90);

function frontmatter(text) {
  const match = text.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return {};
  const out = {};
  // Values may be block scalars (`description: >`); we only need the scalar
  // one-liners, so take the first line of each top-level key.
  for (const line of match[1].split("\n")) {
    const kv = line.match(/^([a-zA-Z_]+):\s*(.*)$/);
    // Strip surrounding quotes. Keeping them made bash treat the whole command
    // as one word, so a lesson that was perfectly true reported FAIL — the check
    // rotting rather than the claim.
    if (kv) out[kv[1]] = kv[2].trim().replace(/^(['"])([\s\S]*)\1$/, "$2");
  }
  return out;
}

const OVERLAY = loadOverlay();

const results = [];
for (const lesson of collectLessons(ROOT)) {
  const file = lesson.file;
  const entry = { name: lesson.name };

  const meta = frontmatter(fs.readFileSync(file, "utf8"));
  const result = { name: entry.name, verified: meta.verified ?? null, origin: lesson.origin };

  const { text: check, missing } = substitute(meta.verify ?? "", OVERLAY);

  if (!meta.verify) {
    result.status = "no-check";
  } else if (missing.length > 0) {
    // The check could not be resolved on this machine — that says nothing about
    // whether the claim is true. Reporting it as a failure is how the anti-rot
    // mechanism starts crying wolf and gets ignored.
    result.status = "not-here";
    result.detail = `needs ${missing.join(", ")} in the local overlay`;
  } else {
    try {
      execSync(check, {
        stdio: ["ignore", "pipe", "pipe"],
        timeout: 60_000,
        shell: "/bin/bash",
      });
      result.status = "holds";
    } catch (error) {
      result.status = "failed";
      result.detail = String(error.stderr ?? error.message ?? "").trim().slice(0, 120);
    }
  }

  if (staleDays && meta.verified) {
    const age = (Date.now() - new Date(meta.verified).getTime()) / 86_400_000;
    if (age > staleDays) {
      result.stale = Math.round(age);
    }
  }
  results.push(result);
}

const failed = results.filter((r) => r.status === "failed");
const stale = results.filter((r) => r.stale);

for (const r of results) {
  const mark =
    r.status === "holds" ? "ok  " : r.status === "failed" ? "FAIL" : r.status === "not-here" ? "n/a " : "??  ";
  const age = r.stale ? `  (unverified ${r.stale}d)` : "";
  console.log(`${mark} ${r.name}${age}`);
  if (r.detail) console.log(`     ${r.detail}`);
}

console.log(
  `\n${results.length} lesson(s): ${results.filter((r) => r.status === "holds").length} hold, ${failed.length} failed, ${results.filter((r) => r.status === "not-here").length} n/a here, ${stale.length} stale`,
);

// A failed check is a signal, not a verdict — exit non-zero so a scheduled run
// surfaces it, but never rewrite the library automatically.
process.exit(failed.length > 0 ? 1 : 0);
