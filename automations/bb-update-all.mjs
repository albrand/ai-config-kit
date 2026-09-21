#!/usr/bin/env node
//
// Update every bb component and agent CLI, on demand, and prove each one landed.
//
// Why this exists: bb's own updater kept reporting things it had not done. On
// one machine `codex update` exited 1 on every release; on the same machine the
// Claude Code install script exited 0 having installed nothing, so bb said
// "done" and the box had no `claude` binary. Neither is recoverable by pressing
// Retry, because Retry runs the same command that just failed.
//
// The reason both failed is that bb asks a CLI to update ITSELF, and whether
// that works depends on how the CLI was installed — which differs per machine:
//
//   Mac  · claude → ~/.local/bin        native installer   self-update works
//   Mac  · codex  → /opt/homebrew/bin   homebrew cask      needs brew
//   VPS  · claude → /usr/lib/node_mod   npm global (root)  self-update works
//   VPS  · codex  → /usr/lib/node_mod   npm global (root)  self-update FAILS:
//         `codex update` shells out to `npm install -g` with no sudo, against a
//         root-owned prefix, and dies with EACCES / exit 243.
//
// So this resolves the install method per binary per machine and uses the
// mechanism that actually works for it, rather than one command that is right
// somewhere and wrong everywhere else.
//
// Nothing here reports success from an exit code. Every target is re-read after
// the attempt and compared, because "the command returned" is exactly what was
// wrong with what it replaces.

import { execFileSync } from "node:child_process";

const ONLY = process.argv.slice(2).find((a) => !a.startsWith("-"));
const DRY = process.argv.includes("--dry-run");

/** A machine we can run commands on. `ssh` is null for this one. */
const TARGETS = [
  { name: "Mac Studio", ssh: null },
  { name: "srv1677963", ssh: "vps" },
];

const results = [];
const problems = [];

function sh(target, command, timeout = 600_000) {
  const opts = { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout };
  return target.ssh
    ? execFileSync("ssh", ["-o", "ConnectTimeout=20", target.ssh, command], opts).trim()
    : execFileSync("bash", ["-lc", command], opts).trim();
}

const trySh = (target, command, timeout) => {
  try {
    return { ok: true, out: sh(target, command, timeout) };
  } catch (error) {
    return { ok: false, out: String(error.stderr || error.stdout || error.message || error).slice(0, 500) };
  }
};

/**
 * Where a binary lives decides how to update it.
 *
 * Resolved by asking the machine, never assumed: the same tool is a homebrew
 * cask on one box and a root-owned npm global on the other, and guessing wrong
 * means running a command that cannot possibly work.
 */
function installMethod(target, binary) {
  const which = trySh(target, `command -v ${binary} 2>/dev/null || true`, 60_000);
  const path = which.ok ? which.out.trim() : "";
  if (!path) return { kind: "absent", path: "" };
  if (path.includes("/homebrew/")) return { kind: "brew", path };
  if (path.includes("/.local/bin/")) return { kind: "native", path };
  // An npm global under a root-owned prefix needs sudo; one under the user's
  // own prefix does not. The distinction is the whole codex failure.
  const real = trySh(target, `readlink -f ${path} 2>/dev/null || echo ${path}`, 60_000).out;
  if (real.includes("node_modules")) {
    const writable = trySh(target, `test -w "$(dirname ${path})" && echo yes || echo no`, 60_000).out;
    return { kind: writable.trim() === "yes" ? "npm" : "npm-root", path };
  }
  return { kind: "unknown", path };
}

const version = (target, binary) => {
  const r = trySh(target, `${binary} --version 2>/dev/null | head -1`, 120_000);
  return r.ok ? r.out.trim() : "";
};

/** The tools this updates, and the npm package each corresponds to. */
const TOOLS = [
  { binary: "claude", npm: "@anthropic-ai/claude-code", selfUpdate: "claude update", brew: null },
  { binary: "codex", npm: "@openai/codex", selfUpdate: "codex update", brew: "codex" },
  // bb's own agent. Only meaningful on a remote machine; the Mac runs the app.
  { binary: "bb", npm: "bb-app", selfUpdate: null, brew: null, remoteOnly: true },
];

function updateCommand(tool, method) {
  switch (method.kind) {
    // A native installer manages its own tree and its self-update is the only
    // supported path.
    case "native":
      return tool.selfUpdate;
    case "brew":
      // Casks and formulae both answer `upgrade`; `--cask` is added when the
      // plain form reports it is a cask.
      return tool.brew ? `brew upgrade --cask ${tool.brew} 2>/dev/null || brew upgrade ${tool.brew}` : null;
    case "npm":
      return `npm install -g ${tool.npm}`;
    case "npm-root":
      // The case bb cannot handle. sudo is required because the prefix is
      // root-owned, and the CLI's own updater does not use it.
      return `sudo npm install -g ${tool.npm}`;
    default:
      return null;
  }
}

for (const target of TARGETS) {
  if (ONLY && !target.name.toLowerCase().includes(ONLY.toLowerCase())) continue;

  const reachable = trySh(target, "echo ok", 60_000);
  if (!reachable.ok) {
    problems.push(`${target.name}: unreachable — ${reachable.out.slice(0, 160)}`);
    continue;
  }

  for (const tool of TOOLS) {
    if (tool.remoteOnly && !target.ssh) continue;

    const method = installMethod(target, tool.binary);
    if (method.kind === "absent") {
      // Install it, rather than skipping. A missing agent CLI on a machine bb
      // routes work to is why a host silently stops being useful.
      const cmd = `sudo npm install -g ${tool.npm}`;
      if (DRY) {
        results.push(`${target.name} · ${tool.binary}: ABSENT → would run: ${cmd}`);
        continue;
      }
      const r = trySh(target, cmd);
      const now = version(target, tool.binary);
      if (now) results.push(`${target.name} · ${tool.binary}: installed → ${now}`);
      else problems.push(`${target.name} · ${tool.binary}: install failed — ${r.out.slice(0, 200)}`);
      continue;
    }

    const before = version(target, tool.binary);
    const cmd = updateCommand(tool, method);
    if (!cmd) {
      problems.push(
        `${target.name} · ${tool.binary}: installed via "${method.kind}" at ${method.path}, ` +
          `which has no known update path here — update it by hand and teach this script how.`,
      );
      continue;
    }

    if (DRY) {
      results.push(`${target.name} · ${tool.binary} (${method.kind}) ${before}: would run: ${cmd}`);
      continue;
    }

    const run = trySh(target, cmd);
    // The version AFTER, always. A command that returned is not a version that
    // changed, and that gap is the entire reason this file exists.
    const after = version(target, tool.binary);

    if (!after) {
      problems.push(`${target.name} · ${tool.binary}: gone after update — ${run.out.slice(0, 200)}`);
    } else if (!run.ok && after === before) {
      problems.push(
        `${target.name} · ${tool.binary} (${method.kind}): update FAILED and it is still ${before}\n` +
          `      ${run.out.split("\n").slice(-3).join(" ").slice(0, 240)}`,
      );
    } else if (after === before) {
      results.push(`${target.name} · ${tool.binary} (${method.kind}): ${after} — already current`);
    } else {
      results.push(`${target.name} · ${tool.binary} (${method.kind}): ${before} → ${after}`);
    }
  }
}

console.log(results.map((r) => `  ${r}`).join("\n") || "  (nothing to report)");

if (problems.length > 0) {
  console.error(`\nUPDATE PROBLEMS\n${problems.map((p) => `  - ${p}`).join("\n")}`);
  try {
    execFileSync(`${process.env.HOME}/.local/bin/bb-notify`, [
      "bb update failed",
      "One or more agent CLIs could not be updated. See the run output.",
      "bb-update-all",
    ]);
  } catch {
    /* the exit code carries it */
  }
  process.exitCode = 1;
} else {
  console.log("\nall targets current");
}
