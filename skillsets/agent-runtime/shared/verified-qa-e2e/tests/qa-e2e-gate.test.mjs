#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { evaluateEvidence } from "../scripts/qa-e2e-gate.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(fs.readFileSync(path.join(here, "fixtures.json"), "utf8"));
const efforts = ["low", "medium", "high", "xhigh", "max"];

for (const fixture of fixtures) {
  let baselineCodes = null;
  for (const effort of efforts) {
    const packet = structuredClone(fixture.packet);
    packet.reasoning_effort = effort;
    const result = evaluateEvidence(packet);
    assert.equal(result.ok, fixture.expected, `${fixture.id} at ${effort}`);
    assert.equal(result.reasoning_invariant, true, `${fixture.id} reasoning invariant marker`);
    const codes = result.failures.map((item) => item.code).sort();
    if (baselineCodes === null) baselineCodes = codes;
    else assert.deepEqual(codes, baselineCodes, `${fixture.id} changed outcome at ${effort}`);
    for (const code of fixture.required_codes ?? []) {
      assert.ok(codes.includes(code), `${fixture.id} missing ${code} at ${effort}`);
    }
    assert.equal(result.operation, fixture.packet.operation, `${fixture.id} operation echo at ${effort}`);
  }
}

const manualIncident = fixtures.find((fixture) => fixture.id === "manual-login-incident-replay");
assert.ok(manualIncident, "incident replay fixture present");
const manualRequest = fixtures.find((fixture) => fixture.id === "manual-login-request-valid");
assert.ok(manualRequest, "valid manual request fixture present");
for (const effort of efforts) {
  const packet = structuredClone(manualIncident.packet);
  packet.reasoning_effort = effort;
  const result = evaluateEvidence(packet);
  assert.equal(result.ok, false, `incident replay must fail at ${effort}`);
  assert.equal(result.reasoning_invariant, true, `incident replay invariant at ${effort}`);
  const codes = result.failures.map((item) => item.code);
  for (const code of ["INSTANCE_NOT_BOUND", "INSTANCE_NOT_OWNED", "INSTANCE_NOT_REUSED", "TAKEOVER_EXPOSURE_UNDISCLOSED", "PRE_LOGIN_UNVERIFIED", "POST_LOGIN_UNVERIFIED", "NOT_RELEASED"]) {
    assert.ok(codes.includes(code), `incident replay missing ${code} at ${effort}`);
  }

  const wrongAuth = structuredClone(manualRequest.packet);
  wrongAuth.reasoning_effort = effort;
  wrongAuth.authentication.required = false;
  wrongAuth.authentication.initial_state = "authenticated";
  wrongAuth.authentication.state = "not_required";
  const wrongAuthCodes = evaluateEvidence(wrongAuth).failures.map((item) => item.code);
  assert.ok(wrongAuthCodes.includes("AUTH_REQUIRED_FOR_MANUAL_LOGIN"), `manual request accepted without required auth at ${effort}`);
  assert.ok(wrongAuthCodes.includes("INITIAL_AUTH_NOT_LOGGED_OUT"), `manual request accepted without logged-out start at ${effort}`);

  const missingAttempt = structuredClone(manualRequest.packet);
  missingAttempt.reasoning_effort = effort;
  delete missingAttempt.authentication.test_identity_discovery.attempt_evidence;
  const missingAttemptCodes = evaluateEvidence(missingAttempt).failures.map((item) => item.code);
  assert.ok(missingAttemptCodes.includes("TEST_IDENTITY_ATTEMPT_EVIDENCE_MISSING"), `manual request accepted without identity-attempt evidence at ${effort}`);
}

const blockedBase = structuredClone(fixtures.find((fixture) => fixture.id === "valid-vendor-portal").packet);
blockedBase.operation = "claim_e2e_blocked";
blockedBase.blocker = {
  goal: "finish onboarding with connected data",
  point: "Connect data screen, Connect Google control",
  evidence: "current screen snapshot",
  visible_route: "attempted",
  attempt_evidence: "browser click and provider rejection snapshot",
  stop_reason: "authorized test account rejected by provider",
};
blockedBase.terminal = { status: "blocked", evidence: "provider rejection snapshot" };
delete blockedBase.external;
delete blockedBase.prerequisites;
delete blockedBase.journey;
assert.equal(evaluateEvidence(blockedBase).ok, true, "a reached and attempted prerequisite can be blocked");

const codeOnlyBlock = structuredClone(blockedBase);
delete codeOnlyBlock.blocker.attempt_evidence;
assert.ok(evaluateEvidence(codeOnlyBlock).failures.some(({ code }) => code === "VISIBLE_ROUTE_NOT_PROVEN"),
  "a source-only Connect data investigation cannot claim the E2E walk blocked");

const pendingConsent = structuredClone(blockedBase);
pendingConsent.blocker.visible_route = "pending_consent";
assert.ok(evaluateEvidence(pendingConsent).failures.some(({ code }) => code === "VISIBLE_ROUTE_UNRESOLVED"),
  "pending consent is an interim handoff, not a blocked verdict");

const deniedConsent = structuredClone(blockedBase);
deniedConsent.blocker.visible_route = "denied";
delete deniedConsent.blocker.attempt_evidence;
deniedConsent.blocker.denial_evidence = "user explicitly declined this connection";
assert.equal(evaluateEvidence(deniedConsent).ok, true, "explicit consent denial can block the journey");

// Installed copies are reached through symlinks (bb's per-session bridge lives
// under /var/folders, which resolves to /private/var). The CLI must still run
// when argv[1] and import.meta.url spell the path differently; an entry guard
// that compares them literally exits 0 with no output and evaluates nothing.
const gateScript = path.join(here, "..", "scripts", "qa-e2e-gate.mjs");
const linkRoot = fs.mkdtempSync(path.join(os.tmpdir(), "qa-e2e-gate-link-"));
try {
  const fileLink = path.join(linkRoot, "gate.mjs");
  fs.symlinkSync(gateScript, fileLink);
  const dirLink = path.join(linkRoot, "scripts");
  fs.symlinkSync(path.dirname(gateScript), dirLink, "dir");
  const packetFor = (id) => {
    const file = path.join(linkRoot, `${id}.json`);
    fs.writeFileSync(file, JSON.stringify(fixtures.find((fixture) => fixture.id === id).packet));
    return file;
  };
  const failing = packetFor("seeded-account-not-checked");
  const passing = packetFor("valid-vendor-portal");
  for (const entry of [fileLink, path.join(dirLink, "qa-e2e-gate.mjs")]) {
    const bad = spawnSync(process.execPath, [entry, "check", failing], { encoding: "utf8" });
    assert.equal(bad.status, 1, `failing packet via ${entry} must exit 1 (got ${bad.status}, stdout ${bad.stdout.length} bytes)`);
    assert.ok(bad.stdout.length > 0, `failing packet via ${entry} produced no output`);
    assert.equal(JSON.parse(bad.stdout).ok, false, `failing packet via ${entry} verdict`);
    const good = spawnSync(process.execPath, [entry, "check", passing], { encoding: "utf8" });
    assert.equal(good.status, 0, `passing packet via ${entry} must exit 0 (got ${good.status})`);
    assert.equal(JSON.parse(good.stdout).ok, true, `passing packet via ${entry} verdict`);
  }
} finally {
  fs.rmSync(linkRoot, { recursive: true, force: true });
}

process.stdout.write(
  JSON.stringify({ ok: true, fixtures: fixtures.length, efforts, evaluations: fixtures.length * efforts.length }) + "\n",
);
