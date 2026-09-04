#!/usr/bin/env node
//
// Keep Hermes pointed at a provider that can actually answer.
//
// Why this exists: Hermes has a fallback chain — Opus 4.8, then GLM — and it
// does not fire when it matters most. Verified three times: with the primary
// quota-exhausted, Hermes retried the PRIMARY three times and surfaced the
// error without ever consulting the chain.
//
// The reason is the shape of the error. The chain triggers on "rate-limit,
// overload, or connection errors", and an exhausted Codex subscription does not
// arrive as any of those — it arrives as:
//
//     HTTP 404: no route found for model "gpt-5.6-sol" for user "<account>"
//
// A 404 reads as "that model does not exist", which is not a retryable
// condition, so the chain is correctly declining to fire on what looks like a
// configuration error. The chain is fine for 5xx and connection failures. It is
// no protection against running out of quota, which is the failure that actually
// happens.
//
// So this moves the PRIMARY instead, which is the setting Hermes always honours.
// It only ever switches to a provider whose credential Hermes itself reports as
// usable, and if nothing is usable it changes nothing and says so — moving the
// primary to a second dead provider would just relabel the outage.

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

const SSH = ["-o", "ConnectTimeout=20", "vps"];
const H = "/opt/hermes/agent/venv/bin/hermes";
const run = (cmd, timeout = 180_000) =>
  execFileSync("ssh", [...SSH, cmd], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    timeout,
  }).trim();

/**
 * Preference order, and the first entry is a choice that was made, not a ranking.
 *
 * Sol is first because it is what was ASKED for — "hermes can be left using
 * sol". A guard that quietly promoted a model it considered better would be
 * overriding that decision every time the other account happened to be free,
 * and the user would find Hermes running something they did not pick. So this
 * only ever deviates when the chosen provider cannot answer, and returns to it
 * the moment it can.
 *
 * Opus is the first fallback: it is the strongest reviewer available, and an
 * independent second opinion is the entire point of Hermes. GLM is last, being
 * a shared proxy on a weekly ceiling.
 */
const CANDIDATES = [
  { provider: "openai-codex", model: "gpt-5.6-sol", pooled: true },
  { provider: "anthropic", model: "claude-opus-4-8", pooled: true },
  {
    // Machine-specific: the self-hosted provider id and its probe URL name a
    // particular host, so they come from the environment and have no default.
    provider: requireEnv("HERMES_SELFHOSTED_PROVIDER"),
    model: "glm-5.2",
    pooled: false,
    probe: requireEnv("HERMES_SELFHOSTED_PROBE_URL"),
  },
];

/**
 * Which pooled providers Hermes considers usable right now.
 *
 * Read from `hermes auth list` rather than inferred from a failed call: Hermes
 * already tracks exhaustion per credential with a reset countdown, so asking it
 * costs nothing and avoids burning a request to discover a wall we are already
 * standing at.
 */
function pooledStatus() {
  const out = run(`sudo -u hermes ${H} auth list 2>/dev/null`);
  const usable = new Map();
  let current = null;
  for (const line of out.split("\n")) {
    const header = line.match(/^(\S+)\s+\(\d+ credential/);
    if (header) {
      current = header[1];
      usable.set(current, false);
      continue;
    }
    if (current && /^\s+#\d/.test(line)) {
      // A credential is usable unless Hermes has marked it spent. Both markers
      // matter: `exhausted` for subscription windows, `usage_limit_reached` for
      // the 429 form.
      const spent = /exhausted|usage_limit_reached|rate-limited/i.test(line);
      if (!spent) usable.set(current, true);
    }
  }
  return usable;
}

/**
 * A provider with no pooled credential is only knowable by asking it — and the
 * question has to be "will you answer", not "are you up".
 *
 * The first version fetched /v1/models and accepted 200. That endpoint is a
 * registry: it listed glm-5.2 happily while every actual completion came back
 * `429 Weekly/Monthly Limit Exhausted`, so the guard switched the primary ONTO a
 * provider that could not answer a single request. Same shape as a health check
 * that pings a cached artifact — it proves the service is reachable and nothing
 * about whether it can do the work.
 *
 * So this sends the smallest real completion it can: one token, no reasoning.
 * A quota wall answers 429 to that and 200 to the model list, which is the whole
 * difference.
 */
function probeOk(url) {
  const body = JSON.stringify({
    model: "glm-5.2",
    messages: [{ role: "user", content: "ping" }],
    max_tokens: 1,
    stream: false,
  });
  try {
    const code = run(
      `curl -s -o /dev/null -w '%{http_code}' --max-time 40 -X POST ` +
        `-H 'Content-Type: application/json' -d ${JSON.stringify(body)} ` +
        `${url.replace("/v1/models", "/v1/chat/completions")}`,
      90_000,
    );
    return code === "200";
  } catch {
    return false;
  }
}

const cfg = run(`sudo -u hermes ${H} config show 2>/dev/null | grep -i "^  Model:" | head -1`);
const currentModel = (cfg.match(/'default':\s*'([^']+)'/) ?? [])[1] ?? "?";
const currentProvider = (cfg.match(/'provider':\s*'([^']+)'/) ?? [])[1] ?? "?";

const pooled = pooledStatus();
let chosen = null;
const why = [];

for (const candidate of CANDIDATES) {
  const ok = candidate.pooled
    ? pooled.get(candidate.provider) === true
    : probeOk(candidate.probe);
  why.push(`${candidate.provider}: ${ok ? "usable" : "unavailable"}`);
  if (ok && !chosen) chosen = candidate;
}

console.log(`  current: ${currentModel} via ${currentProvider}`);
console.log(why.map((w) => `  ${w}`).join("\n"));

if (!chosen) {
  // Deliberately not an alarm. Every provider being spent is a quota fact about
  // the account, not a fault in the machine, and paging about it every 30
  // minutes would train the alarm to be ignored before it ever means something.
  console.log("\nno provider is usable right now — leaving the primary as it is");
  process.exit(0);
}

if (chosen.provider === currentProvider && chosen.model === currentModel) {
  console.log(`\nprimary already on the best usable provider (${chosen.model})`);
  process.exit(0);
}

run(`sudo -u hermes ${H} config set model.provider "${chosen.provider}" >/dev/null 2>&1`);
run(`sudo -u hermes ${H} config set model.default "${chosen.model}" >/dev/null 2>&1`);

// Re-read rather than trust the set. Two commands wrote; this checks what the
// file now says, because a half-applied switch is worse than none.
const after = run(`sudo -u hermes ${H} config show 2>/dev/null | grep -i "^  Model:" | head -1`);
const nowModel = (after.match(/'default':\s*'([^']+)'/) ?? [])[1] ?? "?";
const nowProvider = (after.match(/'provider':\s*'([^']+)'/) ?? [])[1] ?? "?";

if (nowModel === chosen.model && nowProvider === chosen.provider) {
  console.log(`\nswitched primary: ${currentModel} → ${nowModel} (via ${nowProvider})`);
} else {
  console.error(
    `\nFAILED to switch primary: wanted ${chosen.model} via ${chosen.provider}, ` +
      `config now says ${nowModel} via ${nowProvider}`,
  );
  process.exitCode = 1;
}
