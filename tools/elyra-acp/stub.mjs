#!/usr/bin/env node
// Probe ACP agent: records what bb sends (method names, params shape, env var
// names only) so the real Elyra bridge is designed from observed behaviour.
import fs from "node:fs";
import os from "node:os";
import readline from "node:readline";

const logDir = os.homedir() + "/.local/state/elyra-acp";
fs.mkdirSync(logDir, { recursive: true, mode: 0o700 });
const logPath = logDir + "/stub.log";
const log = (o) => fs.appendFileSync(logPath, JSON.stringify({ t: new Date().toISOString(), pid: process.pid, ...o }) + "\n", { mode: 0o600 });

const SECRETISH = /TOKEN|SECRET|KEY|PASSWORD|AUTH|COOKIE/i;
log({
  event: "start",
  argv: process.argv.slice(2),
  cwd: process.cwd(),
  envNames: Object.keys(process.env).sort(),
  // Non-secret bb identifiers are safe to record; everything else is names only.
  bbIds: Object.fromEntries(Object.entries(process.env).filter(([k]) => /^BB_/.test(k) && !SECRETISH.test(k))),
});

const send = (msg) => {
  log({ dir: "out", msg });
  process.stdout.write(JSON.stringify({ jsonrpc: "2.0", ...msg }) + "\n");
};

let sessionCounter = 0;
const rl = readline.createInterface({ input: process.stdin });
rl.on("line", (line) => {
  let msg;
  try { msg = JSON.parse(line); } catch { log({ dir: "in", unparsed: line.slice(0, 500) }); return; }
  log({ dir: "in", msg });
  const { id, method, params } = msg;
  if (id === undefined) return; // notification
  if (method === "initialize") {
    send({ id, result: { protocolVersion: 1, agentCapabilities: { loadSession: true, promptCapabilities: { image: false } }, authMethods: [] } });
  } else if (method === "session/new") {
    const sessionId = `stub-${Date.now()}-${++sessionCounter}`;
    send({ id, result: { sessionId, models: { currentModelId: "stub", availableModels: [{ modelId: "stub", name: "Stub" }] } } });
  } else if (method === "session/load") {
    send({ id, result: {} });
  } else if (method === "session/prompt") {
    const sessionId = params.sessionId;
    send({ method: "session/update", params: { sessionId, update: { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "stub: in-turn reply" } } } });
    send({ id, result: { stopReason: "end_turn" } });
    // Out-of-turn update: does bb accept it when no prompt is in flight?
    setTimeout(() => send({ method: "session/update", params: { sessionId, update: { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "stub: OUT-OF-TURN update 3s after end_turn" } } } }), 3000);
  } else if (method === "session/set_model") {
    send({ id, result: {} });
  } else {
    send({ id, error: { code: -32601, message: `stub: ${method} not implemented` } });
  }
});
rl.on("close", () => log({ event: "stdin-closed" }));
