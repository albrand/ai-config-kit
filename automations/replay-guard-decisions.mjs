#!/usr/bin/env node
// Replay recorded guard runs through the current orderCandidates() policy.
// Usage: node replay-guard-decisions.mjs [hours=48]
// Reads automation_runs for auto_g-jueaas2ga from the automations data.db
// (read-only), reconstructs each run's usable set from its logged lines, and
// counts GLM promotions: recorded (old policy) vs replayed (new policy).
// Exit 1 if the new policy would promote GLM while openai-codex was usable.
process.env.HERMES_GUARD_IMPORT_ONLY = "1";
import { execFileSync } from "node:child_process";
import { homedir } from "node:os";

const { orderCandidates } = await import("./hermes-primary-guard.mjs");
const CANDIDATES = [
  { provider: "openai-codex", model: "gpt-6-astra", pooled: true },
  { provider: "anthropic", model: "claude-opus-5-5", pooled: true },
  { provider: "custom:aperture-glm", model: "glm-5.2", pooled: false },
];

const hours = Number(process.argv[2] ?? 48);
const db = `${homedir()}/.bb/plugins/automations/data.db`;
const since = Date.now() - hours * 3600_000;
const rows = JSON.parse(
  execFileSync("sqlite3", ["-readonly", "-json", db,
    `select started_at, output from automation_runs where automation_id='auto_g-jueaas2ga' ` +
    `and started_at >= ${since} and output is not null order by started_at`], { encoding: "utf8" }) || "[]",
);

const byDay = {};
let runs = 0, astraUsable = 0, oldGlm = 0, oldGlmAstraUsable = 0, newGlmAstraUsable = 0, newGlm = 0;
for (const { started_at, output } of rows) {
  const state = {};
  for (const m of output.matchAll(/^\s+(openai-codex|anthropic|custom:aperture-glm): (usable|unavailable)/gm)) state[m[1]] = m[2] === "usable";
  if (!("openai-codex" in state)) continue;
  runs++;
  const day = new Date(started_at).toISOString().slice(0, 10);
  byDay[day] ??= { runs: 0, oldGlm: 0, newGlm: 0 };
  byDay[day].runs++;
  const astra = state["openai-codex"];
  if (astra) astraUsable++;
  const recordedGlm = /switched primary: .* → glm-/.test(output);
  if (recordedGlm) { oldGlm++; byDay[day].oldGlm++; if (astra) oldGlmAstraUsable++; }
  const usable = CANDIDATES.filter((c) => state[c.provider]);
  const { ordered } = orderCandidates(usable, CANDIDATES);
  const picksGlm = ordered[0]?.provider === "custom:aperture-glm";
  if (picksGlm) { newGlm++; byDay[day].newGlm++; if (astra) newGlmAstraUsable++; }
}

console.log(JSON.stringify({ windowHours: hours, runs, astraUsable,
  recorded: { glmPromotions: oldGlm, glmPromotionsWhileAstraUsable: oldGlmAstraUsable },
  replayed: { glmChosen: newGlm, glmChosenWhileAstraUsable: newGlmAstraUsable }, byDay }, null, 2));
process.exit(newGlmAstraUsable === 0 ? 0 : 1);
