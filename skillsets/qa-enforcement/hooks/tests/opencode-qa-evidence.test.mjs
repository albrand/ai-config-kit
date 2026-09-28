import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { policy } from "../lib/qa-evidence-policy.mjs";
import { server } from "../plugin/opencode-qa-evidence.js";

const here = dirname(fileURLToPath(import.meta.url));
const evidenceScript = resolve(here, "../../shared/qa-sweep/scripts/evidence-stop.py");

test("OpenCode policy sees a real final claim as a block", () => {
  const fixture = "Done — the fix is implemented.";
  const adapterVerdict = policy(fixture, evidenceScript);
  const scriptVerdict = JSON.parse(execFileSync("python3", [evidenceScript], {
    input: JSON.stringify({ text: fixture }), encoding: "utf8",
  }));
  assert.equal(scriptVerdict.decision, "block");
  assert.equal(adapterVerdict.decision, "block");
});

test("OpenCode idle status injects one continuation for a final claim", async () => {
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
