#!/usr/bin/env node
//
// Keep the remote agent's self-update working, and shout the day it stops.
//
// Why this exists: the VPS agent showed "Can't connect — its bb agent is out of
// date. Usually it updates itself." It had tried to update itself seven times
// and backed off. The daemon's log said only "Daemon self-update failed"; the
// reason was three hops away, on the OTHER machine.
//
// The chain, end to end:
//
//   1. Node v24.13.0 had npm 6.14.18 in its bin — npm 6 had been installed OVER
//      the npm 11 that ships with Node 24.
//   2. `--pack-destination` arrived in npm 7. npm 6 does not reject the unknown
//      flag, it IGNORES it and reads the path as a positional package spec.
//   3. So `npm pack --pack-destination ~/.bb/install-cache` tried to pack the
//      cache DIRECTORY, which has no package.json: ENOLOCAL.
//   4. The bb server builds /install/bb-app.tgz with that command, so the
//      endpoint returned 500.
//   5. Every remote daemon downloads its update from that endpoint. So every
//      self-update failed, on every release, until someone updated by hand.
//
// Nothing in that chain is visible from the failing machine, and the user's
// only symptom is a host that will not connect after an update.
//
// What this checks, and why it is not just a health ping:
//
// The server CACHES the tarball per version — bb-app-0.39.0-protocol-135.tgz.
// Once one has been built, the endpoint answers 200 from cache no matter how
// broken packing is. A probe that only curls the endpoint would have been green
// all through the outage above and green again the day before the next release.
// So the real check is the CAPABILITY: can this npm still build a tarball at
// all. That is the thing that broke, and it is checkable before it matters.

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/**
 * Machine-specific configuration comes from the environment, never a default.
 *
 * A hardcoded hostname or service name is one machine's answer wearing the
 * costume of a general one: it makes this script look portable while silently
 * pointing every other host at somebody else's box. Failing loudly on an unset
 * variable is the honest behaviour.
 */
function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    console.error(`${name} is not set. It names a host-specific resource, so there is no safe default.`);
    process.exit(2);
  }
  return value;
}

/**
 * The npm the bb server will spawn is the one on PATH, and this script has to
 * test THAT one — a green check against a different npm is the last way this
 * can pass while the server still cannot pack. Resolved and reported every run.
 */
const NPM_PATH = (() => {
  try {
    return execFileSync("which", ["npm"], { encoding: "utf8" }).trim();
  } catch {
    return "(npm not on PATH)";
  }
})();

/**
 * Restore the npm that Node ships with.
 *
 * The cause of the downgrade was never found: no nvm default-packages entry, no
 * shell rc line, no npm log naming it, and every OTHER node in nvm has a
 * correct npm — so something wrote npm 6.14.18 into the default node alone.
 * Without a cause there is no way to prevent a recurrence, and an alarm that
 * fires every time it recurs is still the user's update breaking every time.
 *
 * So this repairs it. The action is narrow and reversible: install the npm
 * major that Node 24 ships with, then RE-TEST. It never reports success on the
 * strength of having run the fix — only on the capability check passing
 * afterwards, and it notifies either way so a self-heal is never silent.
 */
function repairNpm() {
  execFileSync("npm", ["install", "-g", "npm@11"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    timeout: 300_000,
  });
}

/** Machine-specific: no default, so this can never probe someone else's server. */
const SERVER_URL = requireEnv("BB_SERVER_URL");
const problems = [];
const notes = [];

const run = (cmd, args, opts = {}) =>
  execFileSync(cmd, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], ...opts }).trim();

// --- 1. can npm still pack? --------------------------------------------------
//
// Proved by DOING it, not by reading `npm --version` or grepping help text. A
// version comparison encodes an assumption about which npm releases are broken;
// packing a real package answers the only question that matters. `--dry-run`
// keeps it cheap — it exercises argument parsing, which is exactly where npm 6
// failed, without writing 34MB.
function canPack() {
  let scratch;
  try {
    scratch = mkdtempSync(join(tmpdir(), "bb-pack-check-"));
    // Two directories, and the separation is the entire test.
    //
    // The destination must NOT be a package. npm 6 does not reject the unknown
    // `--pack-destination` flag — it ignores it and reads the following path as
    // a positional package spec. So it fails ONLY when that path has no
    // package.json, which is exactly bb's case: it packs into
    // ~/.bb/install-cache, an output directory.
    //
    // The first version of this check used ONE directory for both, so the
    // destination was the package it had just created with `npm init`. npm 6
    // happily packed it and the check reported healthy against a genuinely
    // broken npm — verified by downgrading and watching it pass. The same
    // mistake as picking a convenient fixture value: the probe has to have the
    // shape of the real call, not merely its arguments.
    const pkg = join(scratch, "pkg");
    const dest = join(scratch, "dest");
    mkdirSync(pkg);
    mkdirSync(dest);
    run("npm", ["init", "-y"], { cwd: pkg });
    run("npm", ["pack", "--dry-run", "--pack-destination", dest], { cwd: pkg });
    return { ok: true, detail: "" };
  } catch (error) {
    return { ok: false, detail: String(error.stderr || error.message || error).slice(0, 400) };
  } finally {
    if (scratch && existsSync(scratch)) rmSync(scratch, { recursive: true, force: true });
  }
}

{
  const first = canPack();
  if (first.ok) {
    notes.push(`npm can pack (${NPM_PATH})`);
  } else {
    // Repair, then prove it. Never trust the repair itself.
    let repairError = "";
    try {
      repairNpm();
    } catch (error) {
      repairError = String(error.stderr || error.message || error).slice(0, 300);
    }
    const second = canPack();
    if (second.ok) {
      // Not a silent self-heal: this is still reported and still notifies, so a
      // recurring downgrade shows up as a pattern instead of being papered over.
      problems.push(
        `npm at ${NPM_PATH} could not pack with --pack-destination — the bb server builds ` +
          `/install/bb-app.tgz this way, so every remote self-update would have failed on the ` +
          `next release. REPAIRED by reinstalling npm@11, and re-tested green.\n    ${first.detail}`,
      );
    } else {
      problems.push(
        `npm at ${NPM_PATH} cannot pack with --pack-destination, and the repair did not fix it. ` +
          `Remote agents will not be able to self-update.\n    ${first.detail}` +
          (repairError ? `\n    repair failed: ${repairError}` : ""),
      );
    }
  }
}

// Recorded rather than asserted on. npm 6 was the cause once, but the check
// above is what decides; this only makes the report diagnosable at a glance.
try {
  const version = run("npm", ["--version"]);
  notes.push(`npm ${version} (node ${process.version})`);
  if (Number(version.split(".")[0]) < 7) {
    problems.push(`npm ${version} predates --pack-destination (added in npm 7)`);
  }
} catch {
  problems.push("npm is not runnable at all");
}

// --- 2. does the install endpoint answer? ------------------------------------
//
// Weaker than the check above, because of the cache, and kept anyway: it is the
// only check that covers the network path the remote actually uses — TLS, the
// tunnel, the route — none of which the local pack test can see.
try {
  const code = run("curl", [
    "-s", "-o", "/dev/null", "-w", "%{http_code}",
    "--max-time", "180",
    `${SERVER_URL}/install/bb-app.tgz`,
  ]);
  if (code !== "200") {
    problems.push(`${SERVER_URL}/install/bb-app.tgz returned ${code} — remote agents cannot update`);
  } else {
    notes.push("install endpoint 200");
  }
} catch (error) {
  problems.push(`could not reach ${SERVER_URL}/install/bb-app.tgz: ${String(error).slice(0, 200)}`);
}

// --- 3. are the provider CLIs on remote machines current? -------------------
//
// Reported here, repaired by `bb-update-all.mjs`. The repair lived in this file
// first and then the updater grew the same logic, which is two owners for one
// job and the shorter road to them disagreeing. This one watches; that one acts.
//
// Worth watching at all because bb asks each CLI to update ITSELF, and whether
// that works depends on how it was installed. On the VPS `codex update` shells
// out to `npm install -g` with no sudo against a root-owned prefix and dies with
// EACCES on every release, so drift here is expected rather than surprising.
try {
  const status = run("bb", ["updates", "status"]);
  const stale = status
    .split("\n")
    .filter((line) => /srv|remote/i.test(line) && /update available|not installed/i.test(line))
    .map((line) => line.trim());
  if (stale.length === 0) {
    notes.push("remote provider CLIs up to date");
  } else {
    problems.push(
      `remote provider CLIs are behind — run the "Update bb and agent CLIs" automation ` +
        `(or \`node bb-update-all.mjs\`):\n      ${stale.join("\n      ")}`,
    );
  }
} catch (error) {
  notes.push(`could not read update status: ${String(error).slice(0, 120)}`);
}

// --- 4. is anything stranded right now? --------------------------------------
//
// The symptom the user actually sees. A machine can be disconnected for
// ordinary reasons — powered off, off the tailnet — so this is reported, never
// treated as proof of the fault above.
try {
  const listing = run("bb", ["machine", "list"]);
  const offline = listing
    .split("\n")
    .filter((line) => /disconnected/i.test(line))
    .map((line) => line.trim().split(/\s{2,}/)[0])
    .filter(Boolean);
  if (offline.length > 0) notes.push(`disconnected: ${offline.join(", ")}`);
  else notes.push("all machines connected");
} catch (error) {
  notes.push(`could not list machines: ${String(error).slice(0, 120)}`);
}

// --- report ------------------------------------------------------------------
console.log(notes.map((n) => `  ${n}`).join("\n"));

if (problems.length === 0) {
  console.log("remote update path: healthy");
} else {
  console.error(`\nREMOTE UPDATE PATH BROKEN\n${problems.map((p) => `  - ${p}`).join("\n")}`);
  try {
    execFileSync(`${process.env.HOME}/.local/bin/bb-notify`, [
      "bb update path broken",
      "Remote agents will not be able to self-update. See the automation run.",
      "bb-remote-update-health",
    ]);
  } catch {
    // A missing notification must not mask the failure; the exit code carries it.
  }
  process.exitCode = 1;
}
