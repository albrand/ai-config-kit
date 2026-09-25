#!/usr/bin/env node

import fs from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";

const OPERATIONS = new Set([
  "publish_qa_instructions",
  "claim_e2e_complete",
  "claim_e2e_blocked",
  "request_manual_browser_login",
]);
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
        "operation must be publish_qa_instructions, claim_e2e_complete, claim_e2e_blocked, or request_manual_browser_login",
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

  const isRequest = packet.operation === "request_manual_browser_login";
  const isBlocked = packet.operation === "claim_e2e_blocked";

  if (isRequest && packet.authentication?.required !== true) {
    failures.push(
      failure(
        "AUTH_REQUIRED_FOR_MANUAL_LOGIN",
        "authentication.required",
        "a manual browser login request is valid only when authentication is required",
      ),
    );
  }
  if (isRequest && packet.authentication?.initial_state !== "logged_out") {
    failures.push(
      failure(
        "INITIAL_AUTH_NOT_LOGGED_OUT",
        "authentication.initial_state",
        "a manual browser login request requires an initial logged_out state",
      ),
    );
  }

  if (packet.authentication?.required === true) {
    if (isRequest) {
      if (packet.authentication?.state !== "logged_out") {
        failures.push(
          failure(
            "AUTH_NOT_LOGGED_OUT",
            "authentication.state",
            "a manual login request requires the current authentication state to be logged_out",
          ),
        );
      }
    } else if (isBlocked) {
      if (!INITIAL_AUTH_STATES.has(packet.authentication?.state)) {
        failures.push(failure("AUTH_STATE_UNKNOWN", "authentication.state", "a blocked claim needs the observed authenticated or logged_out state"));
      }
    } else if (packet.authentication?.state !== "authenticated") {
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
        requireText(
          packet.authentication?.test_identity_discovery?.attempt_evidence,
          "TEST_IDENTITY_ATTEMPT_EVIDENCE_MISSING",
          "authentication.test_identity_discovery.attempt_evidence",
          "evidence of the discovered test-identity attempt is required",
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

  const manual = packet.manual_login;
  if (isRequest || manual !== undefined) {
    if (!manual || typeof manual !== "object" || Array.isArray(manual)) {
      failures.push(
        failure(
          "MANUAL_LOGIN_MISSING",
          "manual_login",
          isRequest
            ? "a manual login request requires a manual_login evidence block"
            : "a packet that reports manual_login must include the manual_login evidence block",
        ),
      );
    } else {
      requireText(manual.instance_id, "INSTANCE_NOT_BOUND", "manual_login.instance_id", "manual login must be bound to a concrete browser instance id");
      requireTrue(manual.thread_owned, "INSTANCE_NOT_OWNED", "manual_login.thread_owned", "the browser instance must be owned by the current thread");
      const before = manual.owned_instances_before;
      const created = manual.instances_created;
      if (!Number.isInteger(before) || before < 0 || before > 1
          || !Number.isInteger(created) || created < 0 || created > 1) {
        failures.push(
          failure(
            "INSTANCE_COUNT_UNVERIFIED",
            "manual_login",
            "owned_instances_before and instances_created must be integers from 0 to 1",
          ),
        );
      } else if (before === 0 && (created !== 1 || manual.reused !== false)) {
        failures.push(
          failure(
            "INSTANCE_CREATION_INVALID",
            "manual_login",
            "when no owned instance exists, create exactly one and record reused as false",
          ),
        );
      } else if (before === 1 && (created !== 0 || manual.reused !== true)) {
        failures.push(
          failure(
            "INSTANCE_NOT_REUSED",
            "manual_login",
            "when one owned instance exists, reuse it and create no additional instance",
          ),
        );
      }
      if (!Number.isInteger(manual.instances_exposed_count) || manual.instances_exposed_count < 1) {
        failures.push(
          failure(
            "EXPOSED_COUNT_INVALID",
            "manual_login.instances_exposed_count",
            "instances_exposed_count must be an integer of at least 1; a shared window always exposes at least the target tab",
          ),
        );
      }
      requireText(manual.necessity_evidence, "MANUAL_INTERACTION_NECESSITY_MISSING", "manual_login.necessity_evidence", "evidence that manual interaction was necessary is required before requesting a handoff");

      const pre = manual.pre_snapshot;
      const preIsObject = pre && typeof pre === "object" && !Array.isArray(pre);
      const preBound = preIsObject && nonEmpty(manual.instance_id) && pre.instance_id === manual.instance_id;
      if (!preBound || !nonEmpty(pre?.url) || !nonEmpty(pre?.title) || !nonEmpty(pre?.login_control) || !nonEmpty(pre?.evidence)) {
        failures.push(
          failure(
            "PRE_LOGIN_UNVERIFIED",
            "manual_login.pre_snapshot",
            "a pre-login snapshot bound to the same instance with url, title, login_control, and evidence is required",
          ),
        );
      }
      if (preIsObject && nonEmpty(manual.instance_id) && nonEmpty(pre.instance_id) && pre.instance_id !== manual.instance_id) {
        failures.push(
          failure(
            "INSTANCE_ID_MISMATCH",
            "manual_login.pre_snapshot.instance_id",
            `pre_snapshot instance ${JSON.stringify(pre.instance_id)} does not match manual_login instance ${JSON.stringify(manual.instance_id)}`,
          ),
        );
      }

      const takeover = manual.takeover;
      const takeoverIsObject = takeover && typeof takeover === "object" && !Array.isArray(takeover);
      if (!takeoverIsObject || takeover.authorized !== true || !nonEmpty(takeover?.evidence)) {
        failures.push(
          failure(
            "TAKEOVER_UNAUTHORIZED",
            "manual_login.takeover",
            "takeover of the shared window must be authorized with evidence",
          ),
        );
      }
      if (!takeoverIsObject || takeover.shared_window_disclosed !== true) {
        failures.push(
          failure(
            "TAKEOVER_EXPOSURE_UNDISCLOSED",
            "manual_login.takeover.shared_window_disclosed",
            "the shared-window exposure must be disclosed before takeover",
          ),
        );
      }

      if (!isRequest) {
        const post = manual.post_snapshot;
        const postIsObject = post && typeof post === "object" && !Array.isArray(post);
        const postBound = postIsObject && nonEmpty(manual.instance_id) && post.instance_id === manual.instance_id;
        if (!postBound || post.authenticated_state_observed !== true || !nonEmpty(post?.evidence)) {
          failures.push(
            failure(
              "POST_LOGIN_UNVERIFIED",
              "manual_login.post_snapshot",
              "publication or completion after a manual login requires a post-login snapshot bound to the same instance with authenticated_state_observed and evidence",
            ),
          );
        }
        if (postIsObject && nonEmpty(manual.instance_id) && nonEmpty(post.instance_id) && post.instance_id !== manual.instance_id) {
          failures.push(
            failure(
              "INSTANCE_ID_MISMATCH",
              "manual_login.post_snapshot.instance_id",
              `post_snapshot instance ${JSON.stringify(post.instance_id)} does not match manual_login instance ${JSON.stringify(manual.instance_id)}`,
            ),
          );
        }
        if (manual.released !== true) {
          failures.push(
            failure(
              "NOT_RELEASED",
              "manual_login.released",
              "the browser instance must be released after manual sign-in before publication or completion",
            ),
          );
        }
      }
    }
  }

  if (isBlocked) {
    const blocker = packet.blocker;
    requireText(blocker?.goal, "BLOCKER_GOAL_MISSING", "blocker.goal", "name the user outcome that could not be attempted");
    requireText(blocker?.point, "BLOCKER_POINT_MISSING", "blocker.point", "name the visible screen and control where progress stopped");
    requireText(blocker?.evidence, "BLOCKER_EVIDENCE_MISSING", "blocker.evidence", "cite a current observation on the intended surface");
    const route = blocker?.visible_route;
    if (route === "attempted") {
      requireText(blocker?.attempt_evidence, "VISIBLE_ROUTE_NOT_PROVEN", "blocker.attempt_evidence", "cite the UI action and observed result, not code inspection");
      requireText(blocker?.stop_reason, "STOP_REASON_MISSING", "blocker.stop_reason", "name what prevented the user from continuing");
    } else if (route === "none") {
      requireText(blocker?.route_inspection_evidence, "VISIBLE_ROUTE_NOT_INSPECTED", "blocker.route_inspection_evidence", "cite inspection of the relevant user-facing controls");
      requireText(blocker?.setup_discovery_evidence, "SETUP_NOT_CHECKED", "blocker.setup_discovery_evidence", "cite authorized setup or test-data discovery");
      requireText(blocker?.stop_reason, "STOP_REASON_MISSING", "blocker.stop_reason", "name why no authorized user route exists");
    } else if (route === "denied") {
      requireText(blocker?.denial_evidence, "PERMISSION_DENIAL_NOT_PROVEN", "blocker.denial_evidence", "cite the explicit refusal or permission denial");
    } else {
      failures.push(failure("VISIBLE_ROUTE_UNRESOLVED", "blocker.visible_route", "visible_route must be attempted, none, or denied; a pending user action is not a blocked verdict"));
    }
    if (packet.terminal?.status !== "blocked") {
      failures.push(failure("TERMINAL_NOT_BLOCKED", "terminal.status", "a blocked claim requires terminal status blocked"));
    }
    requireText(packet.terminal?.evidence, "TERMINAL_EVIDENCE_MISSING", "terminal.evidence", "terminal-state evidence is required");
  } else if (!isRequest) {
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
  }

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
      test_identity_discovery: {
        checked: true,
        found: true,
        attempted: true,
        evidence: "seed-doc-reference",
        attempt_evidence: "seeded identity attempt result",
      },
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

function manualLoginFixture(operation = "request_manual_browser_login") {
  const packet = {
    schema_version: 1,
    operation,
    reasoning_effort: "medium",
    actor: { verified: true, persona: "vendor", surface: "Vendor Portal", environment: "development" },
    entrypoint: { verified: true, route: "visible portal link", evidence: "snapshot-entry" },
    authentication: {
      required: true,
      initial_state: "logged_out",
      state: operation === "request_manual_browser_login" ? "logged_out" : "authenticated",
      evidence: "snapshot-login",
      test_identity_discovery: {
        checked: true,
        found: true,
        attempted: true,
        evidence: "seed-doc-reference",
        attempt_evidence: "seeded identity attempt result",
      },
    },
    manual_login: {
      instance_id: "page-7f3a",
      thread_owned: true,
      reused: true,
      owned_instances_before: 1,
      instances_created: 0,
      instances_exposed_count: 4,
      necessity_evidence: "discovered identity rejected; interactive SSO is the only remaining authorized route",
      pre_snapshot: {
        instance_id: "page-7f3a",
        url: "https://portal.example.test/login",
        title: "Sign in",
        login_control: "Continue with SSO",
        evidence: "snapshot-pre-login",
      },
      takeover: { authorized: true, evidence: "current user approval in thread", shared_window_disclosed: true },
      released: true,
      post_snapshot: {
        instance_id: "page-7f3a",
        authenticated_state_observed: true,
        evidence: "snapshot-authenticated",
      },
    },
  };
  if (operation !== "request_manual_browser_login") {
    packet.prerequisites = {
      verified: true,
      evidence: "snapshot-prerequisites",
      items: [{ name: "portal link", available: true, obtained_by: "visible product control", evidence: "snapshot-link" }],
    };
    packet.journey = {
      walked: true,
      same_actor: true,
      same_surface: true,
      evidence: "trace-journey",
      steps: [{ page: "Work", control: "Accept Dispatch", surface: "Vendor Portal", observed: true, evidence: "snapshot-work" }],
    };
    packet.terminal = { status: "passed", evidence: "snapshot-finished" };
    if (operation === "publish_qa_instructions") {
      packet.external = { authorized: true, authorization_evidence: "current user request", target: "TICKET-1", previewed: true };
    }
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

    const requestOk = manualLoginFixture();
    requestOk.reasoning_effort = effort;
    delete requestOk.manual_login.released;
    delete requestOk.manual_login.post_snapshot;
    if (!evaluateEvidence(requestOk).ok) throw new Error(`manual request fixture failed at ${effort}`);

    const requestBad = manualLoginFixture();
    requestBad.reasoning_effort = effort;
    requestBad.manual_login.instance_id = "";
    requestBad.manual_login.pre_snapshot.instance_id = "";
    if (evaluateEvidence(requestBad).ok) throw new Error(`unbound manual request passed at ${effort}`);

    const publishManualOk = manualLoginFixture("publish_qa_instructions");
    publishManualOk.reasoning_effort = effort;
    if (!evaluateEvidence(publishManualOk).ok) throw new Error(`manual publish fixture failed at ${effort}`);

    const publishManualBad = manualLoginFixture("publish_qa_instructions");
    publishManualBad.reasoning_effort = effort;
    publishManualBad.manual_login.released = false;
    publishManualBad.manual_login.post_snapshot.instance_id = "page-other";
    const badResult = evaluateEvidence(publishManualBad);
    if (badResult.ok) throw new Error(`unreleased manual publish passed at ${effort}`);
    const badCodes = badResult.failures.map((item) => item.code);
    if (!badCodes.includes("NOT_RELEASED") || !badCodes.includes("INSTANCE_ID_MISMATCH") || !badCodes.includes("POST_LOGIN_UNVERIFIED")) {
      throw new Error(`manual publish failure codes missing at ${effort}`);
    }

    const blocked = validFixture("claim_e2e_blocked");
    blocked.blocker = {
      goal: "finish onboarding with connected data",
      point: "Connect data screen, Connect Google control",
      evidence: "snapshot-connect-data",
      visible_route: "attempted",
      attempt_evidence: "click and provider rejection snapshot",
      stop_reason: "authorized test account rejected",
    };
    blocked.terminal = { status: "blocked", evidence: "provider rejection snapshot" };
    if (!evaluateEvidence(blocked).ok) throw new Error(`valid blocked fixture failed at ${effort}`);
    delete blocked.blocker.attempt_evidence;
    if (!evaluateEvidence(blocked).failures.some(({ code }) => code === "VISIBLE_ROUTE_NOT_PROVEN")) {
      throw new Error(`source-only blocker passed at ${effort}`);
    }
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

// Node resolves import.meta.url to the realpath while argv[1] keeps the spelling
// it was invoked with, so a symlinked install (/var -> /private/var on macOS)
// never matched a literal comparison and exited 0 having evaluated nothing.
function isEntryModule() {
  if (!process.argv[1]) return false;
  try {
    return fs.realpathSync(process.argv[1]) === fs.realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return import.meta.url === pathToFileURL(process.argv[1]).href;
  }
}

if (isEntryModule()) main();
