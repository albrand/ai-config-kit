#!/usr/bin/env node
//
// Snapshot bb's database, and shout when it loses things.
//
// Why this exists: five projects vanished from `bb.db` — the rows were absent
// from the table entirely, not soft-deleted — with no backup anywhere on the
// machine and no log entry naming what removed them. The cause was never
// established. This cannot prevent that; nothing a plugin or script can do
// prevents an unexplained delete. What it can do is make the next one
// RECOVERABLE and NOTICED, which is the difference between an inconvenience
// and losing a day.
//
// Two jobs, deliberately in one script so a snapshot and its census can never
// disagree about what was true at that moment.

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const BB = join(homedir(), ".bb");
const DB = join(BB, "bb.db");
const OUT = process.env.BB_SNAPSHOT_DIR || join(homedir(), ".bb-backups");
const KEEP = Number(process.env.BB_SNAPSHOT_KEEP || 24);
const CENSUS = join(OUT, "census.json");

function sqlite(db, sql) {
  return execFileSync("sqlite3", [db, sql], { encoding: "utf8", timeout: 120_000 }).trim();
}

/** Counts worth alarming on. Anything that only ever grows in normal use. */
function census(db) {
  const n = (t, where = "") => Number(sqlite(db, `select count(*) from ${t} ${where};`) || 0);
  return {
    projects: n("projects"),
    threads: n("threads"),
    // Archived threads are fine and expected; DELETED ones are the loss.
    liveThreads: n("threads", "where deleted_at is null"),
  };
}

function main() {
  if (!existsSync(DB)) {
    process.stdout.write(`bb.db not found at ${DB}\n`);
    process.exitCode = 1;
    return;
  }
  mkdirSync(OUT, { recursive: true });

  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const target = join(OUT, `bb-${stamp}.db`);

  // `.backup` and NOT a file copy. bb runs in WAL mode, so copying bb.db alone
  // captures a database missing every uncommitted page in the -wal file — a
  // "backup" that restores to an older state than the one you were looking at,
  // which is the worst possible kind. `.backup` checkpoints properly and is
  // safe against a live writer.
  sqlite(DB, `.backup '${target}'`);
  const size = statSync(target).size;
  if (size < 1_000_000) {
    process.stdout.write(`Snapshot looks truncated (${size} bytes) — keeping it, but check.\n`);
    process.exitCode = 1;
    return;
  }

  const now = census(target);
  let previous = null;
  try {
    previous = JSON.parse(readFileSync(CENSUS, "utf8"));
  } catch {
    /* first run */
  }
  writeFileSync(CENSUS, `${JSON.stringify({ at: Date.now(), ...now }, null, 2)}\n`);

  // Rotate. Oldest first, and never below one — a rotation that deletes the
  // only copy is worse than no rotation.
  const snaps = readdirSync(OUT).filter((f) => f.startsWith("bb-") && f.endsWith(".db")).sort();
  for (const old of snaps.slice(0, Math.max(0, snaps.length - KEEP))) {
    unlinkSync(join(OUT, old));
  }

  // The alarm. Projects and live threads do not decrease on their own; a drop
  // is either a deliberate deletion or the unexplained kind that already
  // happened once.
  const lost = [];
  if (previous) {
    if (now.projects < previous.projects) {
      lost.push(`projects ${previous.projects} -> ${now.projects}`);
    }
    if (now.liveThreads < previous.liveThreads) {
      lost.push(`live threads ${previous.liveThreads} -> ${now.liveThreads}`);
    }
  }

  if (lost.length > 0) {
    // Loud, and exit non-zero so the run goes red in the automations list.
    process.stdout.write(
      [
        `DATA LOSS DETECTED: ${lost.join("; ")}.`,
        `A snapshot from BEFORE this was taken is in ${OUT}.`,
        "Quit bb before attempting any recovery, and work on a copy.",
      ].join("\n") + "\n",
    );
    try {
      execFileSync(`${process.env.HOME}/.local/bin/bb-notify`, [
        "bb data loss detected",
        "Projects or threads disappeared from bb.db. A pre-loss snapshot exists.",
        "bb-db-snapshot",
      ]);
    } catch {
      /* the stdout line is the record that matters */
    }
    process.exitCode = 1;
    return;
  }

  process.stdout.write(
    `${JSON.stringify({ wakeAgent: false, projects: now.projects, liveThreads: now.liveThreads, snapshots: Math.min(snaps.length, KEEP) })}\n`,
  );
}

main();
