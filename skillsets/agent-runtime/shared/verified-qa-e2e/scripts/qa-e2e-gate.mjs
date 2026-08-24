#!/usr/bin/env node

import fs from "node:fs";
import { pathToFileURL } from "node:url";

const OPERATIONS = new Set(["publish_qa_instructions", "claim_e2e_complete"]);
const INITIAL_AUTH_STATES = new Set(["authenticated", "logged_out"]);

const nonEmpty = (value) => typeof value === "string" && value.trim().length > 0;

function failure(code, path, message) {
  return { code, path, message };
}

export function evaluateEvidence(packet) {
  const failures = [];
  const requireTrue = (value, code, path, message) => {
    if (value !== true) failures.push(failure(code, path, message));
  };
  const requireText = (value, code, path, message) => {
    if (!nonEmpty(value)) failures.push(failure(code, path, message));
  };

  if (!packet || typeof packet !== "object" || Array.isArray(packet)) {
    return {
      ok: false,
      operation: null,
      reasoning_invariant: true,
      failures: [failure("INVALID_PACKET", "$", "evidence must be a JSON object")],
    };
  }

  if (packet.schema_version !== 1) {
    failures.push(failure("SCHEMA_VERSION", "schema_version", "schema_version must be 1"));
  }
  if (!OPERATIONS.has(packet.operation)) {
    failures.push(
      failure(
        "OPERATION",
        "operation",
        "operation must be publish_qa_instructions or claim_e2e_complete",
      ),
    );
  }

  requireTrue(packet.actor?.verified, "ACTOR_UNVERIFIED", "actor.verified", "tester actor must be verified");
  requireText(packet.actor?.persona, "PERSONA_MISSING", "actor.persona", "tester persona is required");
  requireText(packet.actor?.surface, "SURFACE_MISSING", "actor.surface", "target product surface is required");
  requireText(packet.actor?.environment, "ENVIRONMENT_MISSING", "actor.environment", "target environment is required");

  requireTrue(packet.entrypoint?.verified, "ENTRYPOINT_UNVERIFIED", "entrypoint.verified", "starting entry point must be reached and verified");
  requireText(packet.entrypoint?.route, "ENTRYPOINT_ROUTE_MISSING", "entrypoint.route", "verified visible route is required");
  requireText(packet.entrypoint?.evidence, "ENTRYPOINT_EVIDENCE_MISSING", "entrypoint.evidence", "entry-point evidence is required");

  if (packet.authentication?.required === true) {
    if (packet.authentication?.state !== "authenticated") {
      failures.push(
        failure(
          "AUTH_UNRESOLVED",
          "authentication.state",
          "authenticated UI state is required; logged_out or blocked is not completion",
        ),
      );
    }
    if (!INITIAL_AUTH_STATES.has(packet.authentication?.initial_state)) {
      failures.push(
        failure(
          "INITIAL_AUTH_STATE_UNKNOWN",
          "authentication.initial_state",
          "initial auth state must be authenticated or logged_out",
        ),
      );
    }
    if (packet.authentication?.initial_state === "logged_out") {
      requireTrue(
        packet.authentication?.test_identity_discovery?.checked,
        "TEST_IDENTITY_NOT_CHECKED",
        "authentication.test_identity_discovery.checked",
        "repository-owned test identity discovery must run after a logged-out start",
      );
      requireText(
        packet.authentication?.test_identity_discovery?.evidence,
        "TEST_IDENTITY_EVIDENCE_MISSING",
        "authentication.test_identity_discovery.evidence",
        "test-identity discovery evidence is required after a logged-out start",
      );
      if (packet.authentication?.test_identity_discovery?.found === true) {
        requireTrue(
          packet.authentication?.test_identity_discovery?.attempted,
          "TEST_IDENTITY_NOT_ATTEMPTED",
          "authentication.test_identity_discovery.attempted",
          "an applicable discovered test identity must be attempted",
        );
      }
    }
  } else if (packet.authentication?.required === false) {
    if (packet.authentication?.state !== "not_required") {
      failures.push(
        failure(
          "AUTH_STATE_MISMATCH",
          "authentication.state",
          "authentication state must be not_required when authentication is not required",
        ),
      );
    }
  } else {
    failures.push(
      failure(
        "AUTH_REQUIREMENT_UNKNOWN",
        "authentication.required",
        "state whether authentication is required",
      ),
    );
  }
  requireText(packet.authentication?.evidence, "AUTH_EVIDENCE_MISSING", "authentication.evidence", "authentication evidence is required");

  requireTrue(packet.prerequisites?.verified, "PREREQUISITES_UNVERIFIED", "prerequisites.verified", "all tester prerequisites must be verified");
  requireText(packet.prerequisites?.evidence, "PREREQUISITE_EVIDENCE_MISSING", "prerequisites.evidence", "prerequisite evidence is required");
  if (!Array.isArray(packet.prerequisites?.items)) {
    failures.push(failure("PREREQUISITES_INVALID", "prerequisites.items", "prerequisites.items must be an array"));
  } else {
    for (const [index, item] of packet.prerequisites.items.entries()) {
      const base = `prerequisites.items[${index}]`;
      requireText(item?.name, "PREREQUISITE_NAME_MISSING", `${base}.name`, "prerequisite name is required");
      requireTrue(item?.available, "PREREQUISITE_UNAVAILABLE", `${base}.available`, "every prerequisite must be available before publication or completion");
      requireText(item?.obtained_by, "PREREQUISITE_ROUTE_MISSING", `${base}.obtained_by`, "how the tester obtains the prerequisite is required");
      requireText(item?.evidence, "PREREQUISITE_ITEM_EVIDENCE_MISSING", `${base}.evidence`, "prerequisite item evidence is required");
    }
  }

  requireTrue(packet.journey?.walked, "JOURNEY_NOT_WALKED", "journey.walked", "the requested UI journey must be walked");
  requireTrue(packet.journey?.same_actor, "ACTOR_DRIFT", "journey.same_actor", "journey evidence must use the intended tester persona");
  requireTrue(packet.journey?.same_surface, "SURFACE_DRIFT", "journey.same_surface", "journey evidence must stay on the intended product surface");
  requireText(packet.journey?.evidence, "JOURNEY_EVIDENCE_MISSING", "journey.evidence", "journey evidence is required");
  if (!Array.isArray(packet.journey?.steps) || packet.journey.steps.length === 0) {
    failures.push(failure("JOURNEY_STEPS_MISSING", "journey.steps", "at least one observed UI step is required"));
  } else {
    for (const [index, step] of packet.journey.steps.entries()) {
      const base = `journey.steps[${index}]`;
      requireText(step?.page, "PAGE_MISSING", `${base}.page`, "observed page title is required");
      requireText(step?.control, "CONTROL_MISSING", `${base}.control`, "observed control label is required");
      requireText(step?.surface, "STEP_SURFACE_MISSING", `${base}.surface`, "step surface is required");
      requireTrue(step?.observed, "CONTROL_NOT_OBSERVED", `${base}.observed`, "every referenced control must be observed");
      requireText(step?.evidence, "STEP_EVIDENCE_MISSING", `${base}.evidence`, "step evidence is required");
      if (nonEmpty(packet.actor?.surface) && nonEmpty(step?.surface)
          && packet.actor.surface !== step.surface) {
        failures.push(
          failure(
            "STEP_SURFACE_MISMATCH",
            `${base}.surface`,
            `step surface ${JSON.stringify(step.surface)} does not match actor surface ${JSON.stringify(packet.actor.surface)}`,
          ),
        );
      }
    }
  }

  if (packet.operation === "publish_qa_instructions") {
    requireTrue(packet.external?.authorized, "EXTERNAL_WRITE_UNAUTHORIZED", "external.authorized", "external tracker mutation must be authorized");
    requireText(packet.external?.authorization_evidence, "EXTERNAL_AUTHORIZATION_EVIDENCE_MISSING", "external.authorization_evidence", "current authorization evidence is required");
    requireText(packet.external?.target, "EXTERNAL_TARGET_MISSING", "external.target", "external target is required");
    requireTrue(packet.external?.previewed, "DRAFT_NOT_PREVIEWED", "external.previewed", "QA draft must be previewed before publication");
  }

  if (packet.terminal?.status !== "passed") {
    failures.push(failure("TERMINAL_NOT_PASSED", "terminal.status", "publication or completion requires terminal status passed"));
  }
  requireText(packet.terminal?.evidence, "TERMINAL_EVIDENCE_MISSING", "terminal.evidence", "terminal-state evidence is required");

  return {
    ok: failures.length === 0,
    operation: OPERATIONS.has(packet.operation) ? packet.operation : null,
    reasoning_effort_observed: nonEmpty(packet.reasoning_effort) ? packet.reasoning_effort : null,
    reasoning_invariant: true,
    failures,
  };
}

function validFixture(operation = "publish_qa_instructions") {
  const packet = {
    schema_version: 1,
    operation,
    reasoning_effort: "medium",
    actor: { verified: true, persona: "vendor", surface: "Vendor Portal", environment: "development" },
    entrypoint: { verified: true, route: "visible portal link", evidence: "snapshot-entry" },
    authentication: {
      required: true,
      initial_state: "logged_out",
      state: "authenticated",
      evidence: "snapshot-authenticated",
      test_identity_discovery: { checked: true, found: true, attempted: true, evidence: "seed-doc-reference" },
    },
    prerequisites: {
      verified: true,
      evidence: "snapshot-prerequisites",
      items: [{ name: "portal link", available: true, obtained_by: "visible product control", evidence: "snapshot-link" }],
    },
    journey: {
      walked: true,
      same_actor: true,
      same_surface: true,
      evidence: "trace-journey",
      steps: [{ page: "Work", control: "Accept Dispatch", surface: "Vendor Portal", observed: true, evidence: "snapshot-work" }],
    },
    terminal: { status: "passed", evidence: "snapshot-finished" },
  };
  if (operation === "publish_qa_instructions") {
    packet.external = { authorized: true, authorization_evidence: "current user request", target: "TICKET-1", previewed: true };
  }
  return packet;
}

function selftest() {
  const efforts = ["low", "medium", "high", "xhigh", "max"];
  for (const effort of efforts) {
    const good = validFixture();
    good.reasoning_effort = effort;
    if (!evaluateEvidence(good).ok) throw new Error(`valid fixture failed at ${effort}`);

    const bad = validFixture();
    bad.reasoning_effort = effort;
    bad.journey.same_surface = false;
    if (evaluateEvidence(bad).ok) throw new Error(`invalid fixture passed at ${effort}`);
  }
  process.stdout.write(JSON.stringify({ ok: true, reasoning_invariant: true, efforts }) + "\n");
}

function main() {
  const [command, file] = process.argv.slice(2);
  if (command === "selftest") return selftest();
  if (command !== "check" || !file) {
    process.stderr.write("usage: qa-e2e-gate.mjs check <evidence.json> | selftest\n");
    process.exit(2);
  }
  let packet;
  try {
    packet = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    process.stderr.write(JSON.stringify({ ok: false, failures: [{ code: "READ_ERROR", path: file, message: error.message }] }) + "\n");
    process.exit(2);
  }
  const result = evaluateEvidence(packet);
  process.stdout.write(JSON.stringify(result, null, 2) + "\n");
  process.exit(result.ok ? 0 : 1);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
