#!/usr/bin/env node

import fs from "node:fs";
import { pathToFileURL } from "node:url";

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

const isoTime = (value) => (nonEmpty(value) && /^\d{4}-\d{2}-\d{2}T/.test(value) ? Date.parse(value) : NaN);

// 2026-09-25, meu-psi: interactive walks signed in as e2e.professional and
// e2e.patient, the deployed CI suite's own identities on the same preview DB.
// The suite's setup deleted and recreated their data mid-walk, the walks
// changed the data under the suite, and a deployed gate went 36/38 on a build
// that was 38/38 twelve minutes earlier. Both sides' evidence was
// contaminated. A walk names its identity (a label, never a credential) and
// whether an automated suite owns it; an owned identity is allowed only when
// no unowned one exists, no automated run overlapped the whole walk window
// (checked after the walk, not only at its start), and the evidence says so.
// A walk may sign in as several personas (meu-psi walks e2e.professional AND
// e2e.patient). `identities` holds one block per persona; the single
// `identity` is kept for older packets. Both are read, so a block in either
// place is checked: with one field only, a second persona went unchecked.
export function declaredIdentities(authentication) {
  const out = [];
  if (authentication?.identity !== undefined) out.push(["authentication.identity", authentication.identity]);
  const list = authentication?.identities;
  if (Array.isArray(list)) list.forEach((block, i) => out.push([`authentication.identities[${i}]`, block]));
  else if (list !== undefined) out.push(["authentication.identities", list]);
  return out;
}

// Identity labels (review r1 D4): `E2E.patient`, `e2e.patient `,
// `e2e.patient@meupsi.test` and `e2е.patient` (Cyrillic е) all name the CI
// suite's e2e.patient. Labels are compared after NFKC, casefold, strip and
// dropping an @domain suffix, and a label that mixes scripts, carries
// invisible characters, or matches a listed label only by look-alike letters
// is refused. Twin of label_key()/label_problem() in ship-gate.py; its
// selftest runs the same labels through both.
const LABEL_SCRIPTS = [
  ["latin", [[0x41, 0x24f], [0x250, 0x2af], [0x1e00, 0x1eff], [0x2c60, 0x2c7f], [0xa720, 0xa7ff], [0xab30, 0xab6f]]],
  ["greek", [[0x370, 0x3ff], [0x1f00, 0x1fff]]],
  ["cyrillic", [[0x400, 0x52f], [0x1c80, 0x1c8f], [0x2de0, 0x2dff], [0xa640, 0xa69f]]],
];
const LABEL_CONFUSABLES = {
  "а": "a", "е": "e", "і": "i", "ј": "j", "к": "k", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
  "ѕ": "s", "ԁ": "d", "һ": "h", "ԛ": "q", "ԝ": "w", "ӏ": "l", "ѵ": "v", "ү": "y",
  "α": "a", "γ": "y", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u",
  "χ": "x", "ω": "w", "ı": "i", "ɑ": "a", "ɩ": "i", "0": "o", "1": "l",
};

// Python's str.casefold() beyond toLowerCase(), for the letters it changes.
const casefold = (s) => s.toLowerCase().replace(/ß/g, "ss").replace(/ς/g, "σ").replace(/ſ/g, "s");

export function labelKey(label) {
  let s = casefold(String(label).normalize("NFKC")).trim();
  const at = s.lastIndexOf("@");
  if (at > 0) s = s.slice(0, at).trim();
  return s;
}

// NFD without combining marks, then look-alike letters: `E2E.PATİENT` casefolds
// to `e2e.pati̇ent` (i + U+0307), which reads as e2e.patient.
const labelSkeleton = (label) => [...labelKey(label).normalize("NFD")]
  .filter((c) => !/\p{Mn}/u.test(c)).map((c) => LABEL_CONFUSABLES[c] ?? c).join("");

function labelScript(ch) {
  const cp = ch.codePointAt(0);
  for (const [name, ranges] of LABEL_SCRIPTS) {
    if (ranges.some(([a, b]) => cp >= a && cp <= b)) return name;
  }
  return `block-${(cp >> 8).toString(16)}`;
}

export function labelProblem(label) {
  const s = String(label).normalize("NFKC");
  if (/[\p{Cf}\p{Cc}]/u.test(s)) return "carries invisible or control characters";
  const scripts = [...new Set([...s].filter((c) => /\p{L}/u.test(c)).map(labelScript))].sort();
  return scripts.length > 1 ? `mixes scripts (${scripts.join(", ")})` : null;
}

export function listedIdentity(label, owned) {
  const key = labelKey(label);
  const skel = labelSkeleton(label);
  const names = (owned || []).filter((o) => typeof o === "string");
  const same = names.find((o) => labelKey(o) === key);
  if (same !== undefined) return [same, "same"];
  const look = names.find((o) => labelSkeleton(o) === skel);
  return look !== undefined ? [look, "confusable"] : null;
}

function checkIdentities(authentication, failures, owned) {
  const blocks = declaredIdentities(authentication);
  if (blocks.length === 0) {
    failures.push(failure("IDENTITY_MISSING", "authentication.identity",
      "name each identity the walk used (authentication.identities, one block per persona) and whether an automated suite owns it"));
    return;
  }
  for (const [base, block] of blocks) checkIdentityIsolation(block, base, failures, owned);
}

// [problems, valid] for identity.walker; valid only for a well-formed
// owner_run by the identity's own owner.
export function ownerRunProblems(identity, owned) {
  const walker = identity.walker;
  if (walker === undefined) return { problems: [], valid: false };
  const problems = [];
  if (!walker || typeof walker !== "object" || Array.isArray(walker) || walker.kind !== "owner_run") {
    problems.push(["WALKER_INVALID", "walker.kind", "walker.kind must be \"owner_run\" (the automation's own CI run walking its identity)"]);
    return { problems, valid: false };
  }
  if (identity.owned_by_automation !== true) {
    problems.push(["OWNER_RUN_NOT_OWNED", "walker", "an owner_run walks an identity an automated suite owns (owned_by_automation: true)"]);
  }
  if (!nonEmpty(walker.owner) || !nonEmpty(identity.owner) || walker.owner.trim() !== identity.owner.trim()) {
    problems.push(["OWNER_RUN_OWNER_MISMATCH", "walker.owner", "walker.owner must be the identity block's owner"]);
  }
  const runId = walker.run_id;
  if (!(nonEmpty(runId) || (typeof runId === "number" && Number.isFinite(runId)))) {
    problems.push(["OWNER_RUN_ID_MISSING", "walker.run_id", "an owner_run names the CI run id it records"]);
  }
  const listed = (owned || []).filter((o) => typeof o === "string");
  if (listed.length > 0 && listedIdentity(identity.label ?? "", listed)?.[1] !== "same") {
    problems.push(["OWNER_RUN_UNLISTED", "walker", "an owner_run walks an identity listed in .qa/config.json automation_identities"]);
  }
  return { problems, valid: problems.length === 0 };
}

function checkIdentityIsolation(identity, base, failures, owned) {
  if (!identity || typeof identity !== "object" || Array.isArray(identity)) {
    failures.push(failure("IDENTITY_MISSING", base, "name the identity the walk used and whether an automated suite owns it"));
    return;
  }
  if (!nonEmpty(identity.label)) {
    failures.push(failure("IDENTITY_LABEL_MISSING", `${base}.label`, "identity label (account name or role, never a credential) is required"));
  } else {
    const problem = labelProblem(identity.label);
    const hit = listedIdentity(identity.label, owned);
    if (hit?.[1] === "confusable") {
      failures.push(failure("IDENTITY_LABEL_CONFUSABLE", `${base}.label`,
        `label looks like ${JSON.stringify(hit[0])} in automation_identities but is spelled differently${problem ? ` (it ${problem})` : ""}`));
    } else if (problem) {
      failures.push(failure("IDENTITY_LABEL_CONFUSABLE", `${base}.label`, `label ${problem}: name the identity in one script`));
    }
    if (hit?.[1] === "same" && identity.owned_by_automation !== true) {
      failures.push(failure("IDENTITY_LISTED_AS_AUTOMATION", `${base}.owned_by_automation`,
        `label is ${JSON.stringify(hit[0])}, listed in automation_identities, but owned_by_automation is not true`));
    }
  }
  if (identity.ownership_checked !== true || !nonEmpty(identity.ownership_evidence)) {
    failures.push(failure("IDENTITY_OWNERSHIP_UNCHECKED", `${base}.ownership_checked`,
      "check CI workflows and e2e setup/fixtures/teardown for the identity, with evidence, before walking with it"));
  }
  if (typeof identity.owned_by_automation !== "boolean") {
    failures.push(failure("IDENTITY_OWNERSHIP_UNKNOWN", `${base}.owned_by_automation`, "owned_by_automation must be true or false"));
    return;
  }
  // The owner running its own suite is not borrowing the identity (meu-psi
  // 2026-09-25: CI run 36193694659 can only sign in as the e2e pair it owns,
  // and with qa.* provisioned every PR was denied). walker.kind "owner_run"
  // lifts the unowned-identity rule for that block only; the walk window, the
  // overlap check and the disclosure stay required, since another writer
  // during the owner's run is exactly the contamination this guards.
  const ownerRun = ownerRunProblems(identity, owned);
  for (const [code, path, message] of ownerRun.problems) failures.push(failure(code, `${base}.${path}`, message));
  if (!identity.owned_by_automation) return;
  if (!nonEmpty(identity.owner)) {
    failures.push(failure("IDENTITY_OWNER_MISSING", `${base}.owner`, "name the automated suite or workflow that owns the identity"));
  }
  if (!ownerRun.valid && (identity.unowned_identity_available !== false || !nonEmpty(identity.unowned_identity_evidence))) {
    failures.push(failure("IDENTITY_OWNED_BY_AUTOMATION", `${base}.unowned_identity_available`,
      "an interactive walk uses an identity no automated suite owns; an owned one only when the repository has none, with evidence"));
  }
  const start = isoTime(identity.walk_window?.start);
  const end = isoTime(identity.walk_window?.end);
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) {
    failures.push(failure("WALK_WINDOW_MISSING", `${base}.walk_window`, "walk_window.start and .end (ISO 8601, end not before start) are required"));
  }
  const overlap = identity.overlap_check;
  const checkedAt = isoTime(overlap?.checked_at);
  if (!overlap || typeof overlap !== "object" || !nonEmpty(overlap.evidence)
      || Number.isNaN(checkedAt) || (!Number.isNaN(end) && checkedAt < end)) {
    failures.push(failure("OVERLAP_UNCHECKED", `${base}.overlap_check`,
      "after the walk, check for automated runs on the same data whose run interval intersects the walk window (checked_at at or after walk_window.end, with evidence)"));
  } else if (overlap.overlapping_runs !== 0) {
    failures.push(failure("CONCURRENT_AUTOMATION_RUN", `${base}.overlap_check.overlapping_runs`,
      "an automated run mutated the same data during the walk: record an environment_contamination defect naming the writer and walk again without overlap"));
  }
  if (!nonEmpty(identity.disclosure)) {
    failures.push(failure("IDENTITY_SHARING_UNDISCLOSED", `${base}.disclosure`,
      "evidence must state that the walk used an automation-owned identity on shared data and that no run overlapped it"));
  }
}

// options.automationIdentities: the repository's automation_identities
// (.qa/config.json), passed by ship-gate.py or --automation-identities.
export function evaluateEvidence(packet, options = {}) {
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

    if (packet.authentication?.required === true) {
      checkIdentities(packet.authentication, failures, options.automationIdentities);
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

function unownedIdentity() {
  return {
    label: "qa.vendor",
    ownership_checked: true,
    ownership_evidence: "CI workflows and e2e setup searched; no suite uses qa.vendor",
    owned_by_automation: false,
  };
}

function ownedIdentity(overlappingRuns = 0) {
  return {
    label: "e2e.professional",
    ownership_checked: true,
    ownership_evidence: "e2e global setup recreates its appointment",
    owned_by_automation: true,
    owner: "deployed e2e gate",
    unowned_identity_available: false,
    unowned_identity_evidence: "seed defines no other professional account",
    walk_window: { start: "2026-09-25T15:10:00Z", end: "2026-09-25T15:40:00Z" },
    overlap_check: { checked_at: "2026-09-25T15:41:00Z", evidence: "CI run list for the walk window", overlapping_runs: overlappingRuns },
    disclosure: "walked as an automation-owned identity on shared data; no run overlapped",
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
      identity: unownedIdentity(),
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
      identity: unownedIdentity(),
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

    // meu-psi 2026-09-25: a walk on the CI suite's identity while its run mutated the data.
    const owned = validFixture("claim_e2e_complete");
    owned.reasoning_effort = effort;
    owned.authentication.identity = ownedIdentity(0);
    if (!evaluateEvidence(owned).ok) throw new Error(`owned identity without overlap failed at ${effort}`);
    owned.authentication.identity = ownedIdentity(1);
    if (!evaluateEvidence(owned).failures.some(({ code }) => code === "CONCURRENT_AUTOMATION_RUN")) {
      throw new Error(`walk overlapping an automated run passed at ${effort}`);
    }
    delete owned.authentication.identity;
    if (!evaluateEvidence(owned).failures.some(({ code }) => code === "IDENTITY_MISSING")) {
      throw new Error(`walk without a named identity passed at ${effort}`);
    }
    // Two personas: an owned, undisclosed second one is not hidden by a clean first one.
    const patient = { ...ownedIdentity(0), label: "e2e.patient" };
    delete patient.disclosure;
    owned.authentication.identities = [unownedIdentity(), patient];
    if (!evaluateEvidence(owned).failures.some(({ code, path }) => code === "IDENTITY_SHARING_UNDISCLOSED" && path === "authentication.identities[1].disclosure")) {
      throw new Error(`owned undisclosed second persona passed at ${effort}`);
    }
    owned.authentication.identities = [unownedIdentity(), { ...unownedIdentity(), label: "qa.patient" }];
    if (!evaluateEvidence(owned).ok) throw new Error(`two unowned personas failed at ${effort}`);
    // review r1 D4: a listed CI identity is found however it is spelled.
    const list = { automationIdentities: ["e2e.patient"] };
    for (const label of ["e2e.patient", "E2E.patient", "e2e.patient ", "e2e.patient@meupsi.test", "e2е.patient", "е2е.раtіеnt", "e2e.pat​ient"]) {
      owned.authentication.identities = [{ ...unownedIdentity(), label }];
      if (evaluateEvidence(owned, list).ok) throw new Error(`label ${JSON.stringify(label)} passed as unowned at ${effort}`);
    }
    owned.authentication.identities = [{ ...unownedIdentity(), label: "qa.patient" }];
    if (!evaluateEvidence(owned, list).ok) throw new Error(`an unlisted one-script label failed at ${effort}`);
    owned.authentication.identities = [{ ...ownedIdentity(0), label: "E2E.Patient" }];
    if (!evaluateEvidence(owned, list).ok) throw new Error(`a listed label declared owned failed at ${effort}`);
    // meu-psi PR #36: the suite's own CI run recorded as the walk.
    const codes = (block, opts = list) => {
      owned.authentication.identities = [block];
      return evaluateEvidence(owned, opts).failures.map(({ code }) => code);
    };
    const ownerRun = () => ({
      ...ownedIdentity(0), label: "e2e.patient", unowned_identity_available: true, unowned_identity_evidence: "qa.* provisioned 21:47Z",
      walker: { kind: "owner_run", owner: ownedIdentity(0).owner, run_id: 36193694659, run_url: "https://github.com/o/r/actions/runs/36193694659" },
    });
    const expectCodes = (got, want, what) => {
      const ok = want === null ? got.length === 0 : got.includes(want);
      if (!ok) throw new Error(`${what} at ${effort}: ${JSON.stringify(got)}`);
    };
    expectCodes(codes(ownerRun()), null, "owner_run with an unowned identity available is refused");
    expectCodes(codes(ownerRun(), {}), null, "owner_run without a configured list is refused");
    const noWalker = ownerRun(); delete noWalker.walker;
    expectCodes(codes(noWalker), "IDENTITY_OWNED_BY_AUTOMATION", "the same walk without walker passes");
    const mismatch = ownerRun(); mismatch.walker.owner = "some other workflow";
    expectCodes(codes(mismatch), "OWNER_RUN_OWNER_MISMATCH", "owner_run by another owner passes");
    expectCodes(codes(mismatch), "IDENTITY_OWNED_BY_AUTOMATION", "owner_run by another owner lifts the unowned rule");
    const noRun = ownerRun(); delete noRun.walker.run_id;
    expectCodes(codes(noRun), "OWNER_RUN_ID_MISSING", "owner_run without run_id passes");
    const noOverlap = ownerRun(); delete noOverlap.overlap_check;
    expectCodes(codes(noOverlap), "OVERLAP_UNCHECKED", "owner_run without overlap_check passes");
    const busy = ownerRun(); busy.overlap_check = { ...busy.overlap_check, overlapping_runs: 1 };
    expectCodes(codes(busy), "CONCURRENT_AUTOMATION_RUN", "owner_run overlapping another writer passes");
    const quiet = ownerRun(); delete quiet.disclosure;
    expectCodes(codes(quiet), "IDENTITY_SHARING_UNDISCLOSED", "owner_run without disclosure passes");
    expectCodes(codes({ ...ownerRun(), label: "e2e.other" }), "OWNER_RUN_UNLISTED", "owner_run for an unlisted label passes");
    expectCodes(codes({ ...ownerRun(), walker: { kind: "borrowed" } }), "WALKER_INVALID", "an unknown walker kind passes");
    const early = ownerRun(); early.overlap_check = { ...early.overlap_check, checked_at: "2026-09-25T15:20:00Z" };
    expectCodes(codes(early), "OVERLAP_UNCHECKED", "owner_run overlap checked before the walk ended passes");
    // a mixed-script label that resembles no listed one is refused on its own
    expectCodes(codes({ ...unownedIdentity(), label: "qa.vеndor" }), "IDENTITY_LABEL_CONFUSABLE", "a mixed-script label passes");
    expectCodes(codes({ ...unownedIdentity(), label: "qa.vеndor" }, {}), "IDENTITY_LABEL_CONFUSABLE", "a mixed-script label passes without a list");





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
  const [command, file, ...rest] = process.argv.slice(2);
  if (command === "selftest") return selftest();
  const usage = "usage: qa-e2e-gate.mjs check <evidence.json> [--automation-identities <json array>] | selftest\n";
  if (command !== "check" || !file) {
    process.stderr.write(usage);
    process.exit(2);
  }
  let automationIdentities;
  const at = rest.indexOf("--automation-identities");
  if (at >= 0) {
    try {
      automationIdentities = JSON.parse(rest[at + 1]);
      if (!Array.isArray(automationIdentities)) throw new Error("not an array");
    } catch (error) {
      process.stderr.write(`--automation-identities: ${error.message}\n${usage}`);
      process.exit(2);
    }
  }
  let packet;
  try {
    packet = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    process.stderr.write(JSON.stringify({ ok: false, failures: [{ code: "READ_ERROR", path: file, message: error.message }] }) + "\n");
    process.exit(2);
  }
  const result = evaluateEvidence(packet, { automationIdentities });
  process.stdout.write(JSON.stringify(result, null, 2) + "\n");
  process.exit(result.ok ? 0 : 1);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
