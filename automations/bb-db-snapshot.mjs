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
import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, statSync, statfsSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

// node:sqlite is still flagged experimental in Node 24 and prints a warning on
// stderr at import. Silence it so a healthy run stays a silent tick.
process.removeAllListeners("warning");
const { DatabaseSync, backup } = await import("node:sqlite");

const BB = join(homedir(), ".bb");
const DB = join(BB, "bb.db");
const OUT = process.env.BB_SNAPSHOT_DIR || join(homedir(), ".bb-backups");
// Each snapshot is a full copy of bb.db (3.1 GB on 2026-09-11) on a disk that
// had 13-23 GiB free. 3 kept + 1 in flight = ~12.4 GB peak.
const KEEP = Number(process.env.BB_SNAPSHOT_KEEP || 3);
const CENSUS = join(OUT, "census.json");
// Must finish inside the automation's own timeout (600000 ms) so a slow run
// exits with a diagnostic instead of being killed mid-write.
const DEADLINE_MS = 540_000;
// Never fill the disk: need room for one more full copy plus this reserve.
const RESERVE_BYTES = 2 * 1024 ** 3;
const SIDECARS = ["-journal", "-wal", "-shm"];
const SNAPSHOT = /^bb-\d{4}-\d{2}-\d{2}T[\d-]+Z\.db(\.zst)?$/;
// Older snapshots are kept zstd-compressed (~6x: 5.4 GB -> 0.9 GB on
// 2026-09-21). Three raw copies held 16 GB and pushed free disk under the
// 20 GB floor that every agent on this host stops at.
const ZSTD = ["/opt/homebrew/bin/zstd", "/usr/local/bin/zstd"].find((p) => existsSync(p));

function removeWithSidecars(path) {
  for (const p of [path, ...SIDECARS.map((s) => path + s)]) {
    if (existsSync(p)) unlinkSync(p);
  }
}

/** Counts worth alarming on. Anything that only ever grows in normal use. */
function census(db) {
  const n = (t, where = "") => Number(db.prepare(`select count(*) as c from ${t} ${where}`).get().c || 0);
  return {
    projects: n("projects"),
    threads: n("threads"),
    // Archived threads are fine and expected; DELETED ones are the loss.
    liveThreads: n("threads", "where deleted_at is null"),
  };
}

function fail(message) {
  process.stdout.write(`${message}\n`);
  process.exitCode = 1;
}

async function main() {
  if (!existsSync(DB)) return fail(`bb.db not found at ${DB}`);
  mkdirSync(OUT, { recursive: true });

  // Leftovers from a run that was killed mid-copy. A `.partial` is never a
  // snapshot, and sidecars whose snapshot is gone belong to nothing.
  const present = new Set(readdirSync(OUT));
  for (const f of present) {
    const base = SIDECARS.reduce((b, s) => (b.endsWith(s) ? b.slice(0, -s.length) : b), f);
    if (f.includes(".partial") || (base !== f && base.startsWith("bb-") && !present.has(base))) {
      unlinkSync(join(OUT, f));
    }
  }

  const wal = existsSync(`${DB}-wal`) ? statSync(`${DB}-wal`).size : 0;
  const needed = statSync(DB).size + wal + RESERVE_BYTES;
  const fs = statfsSync(OUT);
  const free = fs.bavail * fs.bsize;
  if (free < needed) {
    return fail(`Not enough disk for a snapshot: ${(free / 1024 ** 3).toFixed(1)} GiB free, need ${(needed / 1024 ** 3).toFixed(1)} GiB. Existing snapshots kept.`);
  }

  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const target = join(OUT, `bb-${stamp}.db`);
  const partial = `${target}.partial`;

  // SQLite online backup, copying every page in ONE step (rate -1). The
  // previous `sqlite3 .backup` copied 100 pages per step; the backup API
  // restarts from page 1 whenever another connection writes the source
  // between steps, and bb writes constantly, so on a 3 GB database it never
  // finished (537 MB after 420 s in a probe). A single step holds one WAL read
  // transaction for the whole copy (~50 s measured): bb keeps writing, the
  // snapshot is consistent, nothing is locked. Written under `.partial` and
  // renamed only once verified, so a `bb-*.db` name always means complete.
  const src = new DatabaseSync(DB, { readOnly: true });
  // The backup runs off the main thread and cannot be cancelled, so on
  // overrun drop the partial file and exit rather than wait for it.
  const timer = setTimeout(() => {
    removeWithSidecars(partial);
    process.stdout.write(`Snapshot failed, nothing kept from this run: backup exceeded ${DEADLINE_MS} ms\n`);
    process.exit(1);
  }, DEADLINE_MS);
  let now;
  try {
    const expected = src.prepare("pragma page_count").get().page_count;
    await backup(src, partial, { rate: -1 });
    const snap = new DatabaseSync(partial);
    try {
      // The copy inherits WAL mode; switch it off so reading it later does
      // not leave -wal/-shm files behind.
      snap.exec("pragma journal_mode = delete");
      const copied = snap.prepare("pragma page_count").get().page_count;
      // Pages written between reading `expected` and the backup's snapshot
      // can grow the copy; a copy SMALLER than the source means truncation.
      if (copied < expected) throw new Error(`snapshot has ${copied} pages, source had ${expected}`);
      now = census(snap);
    } finally {
      snap.close();
    }
  } catch (err) {
    removeWithSidecars(partial);
    return fail(`Snapshot failed, nothing kept from this run: ${err.message}`);
  } finally {
    clearTimeout(timer);
    src.close();
  }
  for (const s of SIDECARS) if (existsSync(partial + s)) unlinkSync(partial + s);
  renameSync(partial, target);

  let previous = null;
  try {
    previous = JSON.parse(readFileSync(CENSUS, "utf8"));
  } catch {
    /* first run */
  }
  writeFileSync(CENSUS, `${JSON.stringify({ at: Date.now(), ...now }, null, 2)}\n`);

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
    // No rotation on this run: every pre-loss snapshot stays on disk.
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

  // Compress every raw snapshot except the one just taken. zstd -t checks the
  // output against the content checksum taken while reading the input, so the
  // raw copy goes only after a verified round trip. Any failure keeps the raw.
  const raws = readdirSync(OUT).filter((f) => SNAPSHOT.test(f) && f.endsWith(".db") && join(OUT, f) !== target);
  for (const f of ZSTD ? raws : []) {
    const src = join(OUT, f);
    const tmp = `${src}.zst.partial`;
    try {
      execFileSync(ZSTD, ["-q", "-f", "-T0", "-3", src, "-o", tmp], { timeout: 180_000 });
      execFileSync(ZSTD, ["-q", "-t", tmp], { timeout: 120_000 });
      renameSync(tmp, `${src}.zst`);
      removeWithSidecars(src);
    } catch (err) {
      if (existsSync(tmp)) unlinkSync(tmp);
      process.stdout.write(`Compressing ${f} failed, raw copy kept: ${err.message}\n`);
    }
  }

  // Rotate. Oldest first, and never below one — a rotation that deletes the
  // only copy is worse than no rotation. Sidecars go with their snapshot.
  // The timestamp prefix sorts .db and .db.zst together.
  const snaps = readdirSync(OUT).filter((f) => SNAPSHOT.test(f)).sort();
  for (const old of snaps.slice(0, Math.max(0, snaps.length - Math.max(1, KEEP)))) {
    removeWithSidecars(join(OUT, old));
  }

  process.stdout.write(
    `${JSON.stringify({ wakeAgent: false, projects: now.projects, liveThreads: now.liveThreads, snapshots: Math.min(snaps.length, Math.max(1, KEEP)) })}\n`,
  );
}

await main();
