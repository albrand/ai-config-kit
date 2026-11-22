import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { test } from "node:test";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";
import { policy } from "../lib/qa-evidence-policy.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const evidenceScript = resolve(here, "../../shared/qa-sweep/scripts/evidence-stop.py");

test("OpenCode policy sees a real final claim as a block", () => {
  const fixture = "Done — the fix is implemented.";
  const directory = mkdtempSync(join(tmpdir(), "qa-evidence-policy-test-"));
  const eventPath = join(directory, "events.jsonl");
  const previousEventPath = process.env.QA_GATE_EVENTS_FILE;
  process.env.QA_GATE_EVENTS_FILE = eventPath;
  try {
    const metadata = { runtime: "opencode", cwd: process.cwd() };
    const adapterVerdict = policy(fixture, evidenceScript, metadata);
    const scriptVerdict = JSON.parse(execFileSync("python3", [evidenceScript], {
      input: JSON.stringify({ text: fixture, ...metadata }), encoding: "utf8",
    }));
    assert.equal(scriptVerdict.decision, "block");
    assert.equal(adapterVerdict.decision, "block");
    const events = readFileSync(eventPath, "utf8").trim().split("\n").map(JSON.parse);
    assert.equal(events.length, 2);
    assert.equal(events[0].runtime, "opencode");
    assert.equal(events[0].cwd, process.cwd());
    assert.equal(events[0].decision, "block");
  } finally {
    if (previousEventPath === undefined) delete process.env.QA_GATE_EVENTS_FILE;
    else process.env.QA_GATE_EVENTS_FILE = previousEventPath;
    rmSync(directory, { recursive: true, force: true });
  }
});

test("OpenCode idle status injects one continuation for a final claim", async () => {
  // The plugin reads the policy installed under HOME; give it this checkout's copy, not the host's.
  const home = mkdtempSync(join(tmpdir(), "qa-evidence-home-"));
  const installed = join(home, ".agents", "skills", "qa-sweep", "scripts");
  mkdirSync(installed, { recursive: true });
  copyFileSync(evidenceScript, join(installed, "evidence-stop.py"));
  const previousHome = process.env.HOME;
  process.env.HOME = home;
  let server;
  try {
    ({ server } = await import(`../plugin/opencode-qa-evidence.js?home=${encodeURIComponent(home)}`));
  } finally {
    process.env.HOME = previousHome;
  }
  const calls = [];
  const client = { session: {
    messages: async () => ({ data: [
      { info: { role: "user", time: { created: 1 } }, parts: [{ type: "text", text: "probe" }] },
      { info: { role: "assistant", time: { created: 2 } }, parts: [{ type: "text", text: "Done, the fix is implemented." }] },
    ] }),
    promptAsync: async (args) => { calls.push(args); },
  } };
  const hooks = await server({ client });
  await Promise.all([
    hooks.event({ event: { type: "session.status", properties: { sessionID: "fixture-session", status: { type: "idle" } } } }),
    hooks.event({ event: { type: "session.idle", properties: { sessionID: "fixture-session" } } }),
  ]);
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "fixture-session" } } });
  assert.equal(calls.length, 1);
  assert.match(calls[0].body.parts[0].text, /\[qa-evidence-gate-nudge\]/u);
});
