#!/usr/bin/env node
//
// Keep the remote bb host agent on the same version as this bb.
//
// Why this exists: updating the desktop app bumps the server's daemon protocol,
// and a remote machine still on the previous release is refused outright —
// "Can't connect — its bb agent is out of date · daemon protocol 104 · server
// protocol 123". The panel says "Usually it updates itself", and on this host it
// never can: `bb-app` is installed globally at /usr/lib/node_modules/bb-app,
// owned by root, while the daemon runs as a systemd *user* service. bb's own
// updater shells out to `npm install -g` as that user and hits EACCES every
// time. Retry cannot fix a permission it does not have.
//
// So the update is done from here, over ssh, with sudo — the one thing the
// in-app path structurally cannot do.
//
// Read-only unless the versions actually differ, and it reports the mismatch it
// found rather than a bare "ok", because a sync that silently does nothing is
// indistinguishable from a sync that is broken.

import { execFileSync } from "node:child_process";

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

/** The ssh alias in ~/.ssh/config, not a bare IP: the host is Tailscale-only. */
const HOST = process.env.BB_AGENT_SYNC_HOST || "vps";
/** Machine-specific: the systemd unit name differs per host, so it has no default. */
const SERVICE = requireEnv("BB_AGENT_SYNC_SERVICE");
const DRY_RUN = process.env.BB_AGENT_SYNC_DRY_RUN === "1";

function run(command, args, options = {}) {
  return execFileSync(command, args, {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    timeout: 300_000,
    ...options,
  }).trim();
}

/** Over ssh, with a short connect timeout so a sleeping host fails fast. */
function remote(script) {
  return run("ssh", ["-o", "ConnectTimeout=10", "-o", "BatchMode=yes", HOST, script]);
}

function main() {
  if (process.argv.includes("--self-test")) {
    // The only branch worth a fixture is the comparison, which is where a
    // wrong answer would either skip a needed update or reinstall forever.
    const cases = [
      ["0.38.0", "0.37.0", true],
      ["0.38.0", "0.38.0", false],
      // A newer remote is not downgraded: that would be this script fighting a
      // manual fix someone applied on purpose.
      ["0.37.0", "0.38.0", false],
      ["0.38.0", "", true],
    ];
    for (const [local, remoteVersion, expected] of cases) {
      const actual = needsUpdate(local, remoteVersion);
      if (actual !== expected) {
        throw new Error(`self-test: ${local} vs ${remoteVersion} → ${actual}, expected ${expected}`);
      }
    }
    process.stdout.write("self-test: ok\n");
    return;
  }

  const local = run("bb", ["--version"]).trim();
  if (!/^\d+\.\d+\.\d+/.test(local)) {
    process.stdout.write(`Could not read the local bb version (got "${local}").\n`);
    process.exitCode = 1;
    return;
  }

  let remoteVersion = "";
  try {
    remoteVersion = remote("bb --version 2>/dev/null | head -1").trim();
  } catch (error) {
    // Unreachable is not out-of-date. Say which it is: one needs a version
    // bump and the other needs the machine to come back.
    process.stdout.write(
      `${HOST} is unreachable, so its version is unknown: ${String(error?.stderr || error?.message || error).slice(0, 160)}\n`,
    );
    process.exitCode = 1;
    return;
  }

  if (!needsUpdate(local, remoteVersion)) {
    process.stdout.write(`${JSON.stringify({ wakeAgent: false })}\n`);
    return;
  }

  if (DRY_RUN) {
    process.stdout.write(`Would update ${HOST}: bb ${remoteVersion || "unknown"} → ${local}.\n`);
    return;
  }

  // sudo, because the package is root-owned. This is the whole reason the
  // in-app updater cannot do it.
  remote(`sudo npm install -g bb-app@${local}`);
  const after = remote("bb --version 2>/dev/null | head -1").trim();
  if (after !== local) {
    process.stdout.write(
      `Update ran but ${HOST} still reports ${after || "nothing"}, not ${local}. Not restarting the daemon.\n`,
    );
    process.exitCode = 1;
    return;
  }

  // Only after the version is CONFIRMED. Restarting on the strength of the
  // install command exiting 0 would bounce a working daemon for nothing.
  remote(`systemctl --user restart ${SERVICE}`);
  const active = remote(`systemctl --user is-active ${SERVICE} || true`).trim();

  process.stdout.write(
    [
      `Updated ${HOST}: bb ${remoteVersion || "unknown"} → ${after}.`,
      `Daemon ${SERVICE} is ${active}.`,
      active === "active"
        ? "It should reconnect within a minute."
        : "It did not come back active — check `journalctl --user -u` on that host.",
    ].join("\n") + "\n",
  );
  if (active !== "active") process.exitCode = 1;
}

/** Update only when the remote differs AND is behind. */
export function needsUpdate(local, remoteVersion) {
  if (!remoteVersion) return true;
  if (local === remoteVersion) return false;
  const parse = (v) => v.split(".").map((n) => Number.parseInt(n, 10) || 0);
  const [la, lb, lc] = parse(local);
  const [ra, rb, rc] = parse(remoteVersion);
  if (la !== ra) return la > ra;
  if (lb !== rb) return lb > rb;
  return lc > rc;
}

main();
