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
 * Astra is first because it is what was ASKED for (2026-09-07, superseding the
 * earlier "hermes can be left using sol"). A guard that quietly promoted a
 * model it considered better would be overriding that decision every time the
 * other account happened to be free, and the user would find Hermes running
 * something they did not pick. So this only ever deviates when the chosen
 * provider cannot answer, and returns to it the moment it can.
 *
 * Opus is the first fallback: it is the strongest reviewer available, and an
 * independent second opinion is the entire point of Hermes. GLM is last, being
 * a shared proxy on a weekly ceiling.
 */
const CANDIDATES = [
  { provider: "openai-codex", model: "gpt-6-astra", pooled: true, plan: "chatgpt" },
  { provider: "anthropic", model: "claude-opus-5-5", pooled: true, plan: "claude" },
  {
    provider: "custom:aperture-glm",
    model: "glm-5.2",
    pooled: false,
    plan: "zai",
    probe: "http://claramente-aperture.tail6118ef.ts.net/v1/models",
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
        // aperture serves completions at the ROOT (/chat/completions), which is
        // also what Hermes calls with its base_url; /v1/chat/completions is a
        // 404 there, so the old probe marked GLM unavailable even with quota
        // left (found 2026-09-11).
        `${url.replace("/v1/models", "/chat/completions")}`,
      90_000,
    );
    return code === "200";
  } catch {
    return false;
  }
}

/**
 * Tokens already spent per PLAN, so the primary can go to the least-used one.
 *
 * This guard used to take the first usable candidate. That is a failover
 * ladder, not a balancer: it pinned the primary to one plan and held it there
 * until the credential was fully spent, then moved to the next and drained that
 * too. Measured 2026-09-08 over 30 days: gpt-5.6-sol had burned 229,748,212 of
 * 230,842,404 total tokens — 99.5% on ONE plan — while the other two paid plans
 * sat effectively unused, and then all three hit their limit together. That is
 * the exact outcome the balancing policy exists to prevent.
 *
 * Balancing is done per PLAN, not per model, because astra and sol both bill the
 * same ChatGPT subscription — rotating between them spreads nothing.
 *
 * Returns null when the ledger cannot be read, and the caller then falls back to
 * the old first-usable order. Degrading to today's behaviour is acceptable;
 * guessing at usage is not.
 */
function planUsage() {
  // 48h, not the 30-day default. The window is the whole design decision:
  // cumulative history says chatgpt=230,406,518 vs claude=23,324, which would
  // exile a live, working plan for weeks over a drain that already happened and
  // has since reset. Measured 2026-09-08 — 30d: chatgpt 230.4M / zai 428k /
  // claude 23k; 7d: 30.2M / 202k / 23k; 48h: 479k / 158k / 23k. Only the short
  // window reflects CURRENT pressure, so the primary rotates on a timescale of
  // hours instead of days. Quota cycles are weekly, but the goal here is "who
  // should take the next turn", not "who used most this billing period".
  const out = run(`sudo -u hermes ${H} insights --days 2 2>/dev/null`);
  if (!out || !/Models Used/.test(out)) return null;
  const tokens = { chatgpt: 0, claude: 0, zai: 0 };
  let seen = false;
  for (const line of out.split("\n")) {
    const m = line.match(/^\s+(\S+)\s+\d+\s+([\d,]+)\s*$/);
    if (!m) continue;
    const model = m[1];
    const n = Number(m[2].replace(/,/g, ""));
    if (!Number.isFinite(n)) continue;
    const plan = /^gpt-/.test(model) ? "chatgpt"
      : /^claude/.test(model) ? "claude"
      : /^glm/.test(model) ? "zai" : null;
    if (!plan) continue;
    tokens[plan] += n;
    seen = true;
  }
  return seen ? tokens : null;
}

/**
 * Subscription plans first, always; a capped plan only when none is usable.
 *
 * This used to hand the primary to the plan with the fewest raw 48h tokens. The
 * capped plan (GLM behind Aperture's $1/day + $10/month brake) always looked
 * least used, precisely BECAUSE it is capped, so whenever its bucket refilled a
 * few cents the guard promoted it, the bucket drained within minutes, and every
 * review on it died with `429 Aperture quota exceeded: hermes-daily` after
 * 3 x 600 s retries. Measured 2026-09-24: 14 promotions onto GLM in one day
 * while astra was usable in 1,082 of 1,082 runs, and 64+ review threads dead
 * over 09-21..24. Raw tokens are the wrong unit: a subscription window and a
 * dollar brake are not comparable by token count.
 *
 * So: usable subscription (pooled) plans in operator order (astra first, as
 * asked on 2026-09-07); a capped plan only when no subscription plan is usable,
 * with the reason logged. Spend is still printed, for the record only.
 */
export function orderCandidates(usable, candidates = CANDIDATES) {
  const rank = new Map(candidates.map((c, i) => [c.model, i]));
  const byRank = (a, b) => rank.get(a.model) - rank.get(b.model);
  const subscription = usable.filter((c) => c.pooled).sort(byRank);
  if (subscription.length) {
    return { ordered: subscription, reason: "subscription plan usable — capped plans not considered" };
  }
  const capped = usable.filter((c) => !c.pooled).sort(byRank);
  const down = candidates.filter((c) => c.pooled).map((c) => c.provider).join(", ");
  return {
    ordered: capped,
    reason: capped.length
      ? `FALLBACK to capped plan: no subscription plan usable (${down} all unavailable)`
      : `no subscription plan usable (${down}) and no capped plan answered`,
  };
}

function main() {
const cfg = run(`sudo -u hermes ${H} config show 2>/dev/null | grep -i "^  Model:" | head -1`);
const currentModel = (cfg.match(/'default':\s*'([^']+)'/) ?? [])[1] ?? "?";
const currentProvider = (cfg.match(/'provider':\s*'([^']+)'/) ?? [])[1] ?? "?";

const pooled = pooledStatus();
let chosen = null;
const why = [];

const usable = [];
for (const candidate of CANDIDATES.filter((c) => c.pooled)) {
  const ok = pooled.get(candidate.provider) === true;
  why.push(`${candidate.provider}: ${ok ? "usable" : "unavailable"}`);
  if (ok) usable.push(candidate);
}
// Probing a capped plan spends from its brake, so it is only probed when it
// could actually be chosen.
for (const candidate of CANDIDATES.filter((c) => !c.pooled)) {
  if (usable.length) {
    why.push(`${candidate.provider}: not probed (subscription plan usable)`);
    continue;
  }
  const ok = probeOk(candidate.probe);
  why.push(`${candidate.provider}: ${ok ? "usable" : "unavailable"}`);
  if (ok) usable.push(candidate);
}

const spend = planUsage();
if (spend) {
  why.push(
    `plan spend (48h, informational): ` +
      Object.entries(spend)
        .map(([k, v]) => `${k}=${v.toLocaleString()}`)
        .join("  "),
  );
}

const { ordered, reason } = orderCandidates(usable);
why.push(`policy: ${reason}`);
if (ordered.length) why.push(`order: ${ordered.map((c) => c.model).join(" -> ")}`);
chosen = ordered[0] ?? null;

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

/**
 * Prove the provider ANSWERS before leaving the primary on it.
 *
 * `hermes auth list` reports a marker, not a working credential. On 2026-09-08
 * the anthropic entry read as a usable pooled credential while every call died
 * with "No Anthropic credentials found" — it had never worked, which is why that
 * plan showed 0 tokens in 30 days. A guard that trusts the marker parks the
 * primary on a dead provider and Hermes stays down with a healthy-looking config.
 *
 * One short completion per SWITCH (not per run), and the previous primary is
 * restored if it fails.
 */
function switchTo(candidate) {
  run(`sudo -u hermes ${H} config set model.provider "${candidate.provider}" >/dev/null 2>&1`);
  run(`sudo -u hermes ${H} config set model.default "${candidate.model}" >/dev/null 2>&1`);
  // The cd must happen INSIDE the sudo. /var/lib/hermes is drwx------ hermes, so
  // changing into it as the automation's own user fails with "Permission denied"
  // and takes the whole guard down — which is exactly what run
  // arun_pzpefbyfkte did on 2026-09-08, and only on runs that actually switch.
  const probe = run(
    `sudo -u hermes bash -lc 'cd /var/lib/hermes && timeout 120 ${H} -z "reply OK"' 2>&1 | tail -2`,
  );
  const failed = /agent failed|No .* credentials found|error/i.test(probe);
  return { ok: !failed, detail: probe.trim().slice(0, 160) };
}

let verified = null;
for (const candidate of ordered) {
  const attempt = switchTo(candidate);
  if (attempt.ok) {
    verified = candidate;
    break;
  }
  console.log(`  ${candidate.provider} accepted the config but did not answer: ${attempt.detail}`);
}

if (!verified) {
  // Put the primary back rather than leaving it on the last thing tried.
  run(`sudo -u hermes ${H} config set model.provider "${currentProvider}" >/dev/null 2>&1`);
  run(`sudo -u hermes ${H} config set model.default "${currentModel}" >/dev/null 2>&1`);
  console.log("\nno provider actually answered — primary restored, nothing switched");
  process.exit(0);
}
chosen = verified;

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
}

// The replay test imports orderCandidates without touching the VPS.
if (process.env.HERMES_GUARD_IMPORT_ONLY !== "1") main();
