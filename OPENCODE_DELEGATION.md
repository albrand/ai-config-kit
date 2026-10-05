# Legacy OpenCode Execution Boundary

OpenCode is retired from the framework's default routing policy. Bounded and
bulk execution goes through the verified Codex route; architecture, security,
authentication, data-loss, release, and final-review work stays on Claude. Hermes
PR reviews run on Codex through `bb fleet validate`. No task may use GLM or a
GLM-backed Hermes route.

This reference preserves safety rules for an operator who explicitly requests
an existing non-GLM OpenCode setup. It does not authorize provider membership,
authentication, model choice, or private-context sharing. Without explicit
request and live verification, keep execution on the default Codex and Claude
routes. See `skillsets/agent-runtime/shared/codex-delegation/SKILL.md` for the
default bounded-work handoff.

## Legacy OpenCode Gate

Before any explicitly requested OpenCode call:

1. Verify the executable version, configured provider, model, agent, and effort
   with a small no-tool probe. Never select GLM.
2. Keep package checks offline. Runtime authentication belongs to an explicit
   operator-run doctor; do not inspect or handle credentials.
3. Confirm repository-context authorization, minimize the evidence packet, and
   remove secrets.
4. Record workdir, allowed tools, mutation boundary, output cap, stop
   conditions, and a local Codex fallback.
5. For execution, use a dedicated isolated worktree and any configured explicit
   write gate. Prompt-level path restrictions are not an enforcement boundary.
6. Keep sharing disabled. Never publish an OpenCode session unless the user
   explicitly requests publication of that session.
7. Keep coordinator ownership of architecture, security, integration, and final
   validation. Sidecar output is evidence, never release truth.

Direction must remain acyclic: coordinator -> OpenCode -> result -> coordinator.
OpenCode must not call the coordinator, another orchestrator, or another
sidecar. If any gate fails, report the exact blocker and continue locally only
when the Codex route is authorized.

## Hermes Review Boundary

Hermes is an independent reviewer, not an executor. Request PR reviews through
`bb fleet validate` with a bounded topic and evidence packet. The review route
uses Codex. Never pass a `--model` override to `acp-hermes-agent`. Never place
or retain a project source on Hermes; provide only bounded review context via
the approved broker. Transport details remain in
`CMUX_HERMES_ORCHESTRATION.md`.

## Handoff Packet

For any explicitly approved legacy sidecar call, include only:

- the relevant request and accepted scope;
- the bounded responsibility and exact `do_not_touch` paths;
- source evidence, acceptance criteria, and exact local checks;
- security, data, dependency, and release invariants;
- allowed tools, mutation boundary, output cap, stop conditions, and fallback.

The complete request must remain accessible to the recipient. If this exceeds
the authorized context, keep the work local or rescope it.

## Executor Output

Require a structured result with status (`done`, `partial`, or `blocked`),
changes, artifacts, validation results (`pass`, `fail`, `blocked`, `skipped`,
or `not_run`), gates preserved, residual risk, and next step. Re-read changed
files and rerun important checks locally before acting on the result.
