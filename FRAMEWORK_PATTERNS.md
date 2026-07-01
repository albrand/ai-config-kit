# Framework Patterns

This file lists neutral configuration patterns that teams can compose.

It deliberately avoids organization-specific, repository-specific, and closed-scope domain details.

## Pattern 1: Global Collaboration Baseline

Use globally when every agent should work the same way by default.

Includes:

- Deep analysis before action.
- Plan before implementation.
- Broad context scan before deciding scope.
- Multi-agent delegation when useful and allowed.
- Cross-agent coordination when another AI tool can add independent critique, execution, verification, or summarization.
- Challenge directives, journals, memory, cached conclusions, and prior project
  patterns as evidence rather than authority.
- Evidence-backed debugging.
- Verification before completion.
- Clear reporting of failures, skipped checks, blocked checks, and residual risk.

Keep out:

- Private repository names.
- Non-public URLs.
- Closed-scope domain facts.
- Deployment credentials.
- Domain-specific data models.

## Pattern 2: Repo Source-Of-Truth Order

Use in each repo instruction file.

Generic order:

1. Current user request.
2. Issue or task acceptance criteria.
3. Approved designs, specs, or architecture docs.
4. Runtime contracts: schema, API payloads, auth rules, feature flags, logs, generated artifacts, and existing behavior.
5. Existing code conventions in the affected area.

Rule:

- If these sources conflict, ask a direct question before implementing.

## Pattern 3: Pre-Edit Impact Mapping

Use before substantial code changes.

Map:

- Entry points.
- Callers and callees.
- Routes or handlers.
- Hooks or state surfaces.
- Services or repositories.
- Config and environment dependencies.
- Tests and fixtures.
- Docs and generated artifacts.
- Release implications.
- Adjacent workflows that can regress.

Output:

- Objective.
- Scope and non-goals.
- Affected surface.
- Plan.
- Validation.
- Rollback or fallback.

## Pattern 4: Evidence-Backed Debugging

Use for bugs, test failures, CI failures, deploy failures, environment mismatches, and unexpected runtime behavior.

Sequence:

1. Capture exact symptom.
2. Reproduce when feasible.
3. State expected versus actual behavior.
4. Form one to three evidence-backed hypotheses.
5. Test the cheapest discriminating hypothesis first.
6. Patch only after the root cause is supported.
7. Re-run the reproducer and one nearby regression check.

Guardrail:

- Do not present a guess as a confirmed root cause.

## Pattern 5: Big-Change Planning

Use for architecture, auth, security, schema, migration, release, infrastructure, or cross-cutting refactor work.

Plan shape:

1. Problem statement.
2. Scope and non-goals.
3. Constraints and risks.
4. Options considered.
5. Recommended approach.
6. Incremental slices.
7. Validation plan.
8. Rollback plan.
9. Open questions.

Guardrail:

- Do not start implementation while material assumptions are unresolved.
- For non-trivial planning or architecture, run an independent advisor critique
  when available, include the authorization sentence in the advisor brief, and
  use single-agent self-critique as the fallback.

## Pattern 5a: Cross-Project Pattern Scan

Use when implementation shape is uncertain and the current repo lacks enough
evidence.

Sequence:

1. Search sibling projects under `/Users/alexandrebrandizzi/projects`
   metadata-first.
2. Identify candidate patterns by stack, file names, tests, and docs before
   opening code.
3. Exclude patterns that depend on secrets, private context, incompatible
   stacks, or different product constraints.
4. Adopt only the pattern parts that fit the current repo's source of truth and
   quality gates.

Guardrail:

- A sibling project pattern is candidate evidence, not authority.

## Pattern 6: Architecture And Code Quality

Use for every non-trivial code change.

Check:

- Boundary ownership.
- Responsibility split.
- State flow.
- Data flow.
- Security boundary.
- Complexity.
- Testability.
- Performance.

Output:

- What boundary owns the change.
- What complexity was reduced or accepted.
- What validation proves the architecture still works.

## Pattern 7: Review And PR Readiness

Use for PR review, PR preparation, and post-change self-review.

Check:

- Changed behavior matches request.
- Runtime contracts are preserved.
- Complexity stays understandable.
- Security and permission boundaries remain intact.
- Tests exercise behavior at the right layer.
- Missing evidence is reported explicitly.

PR body should include:

- Problem.
- Approach.
- Validation run.
- Deployment or operational impact.
- Rollback path.
- Residual risk.

## Pattern 8: Repo-Local Delivery Workflow

Use when a repo has a formal issue tracker or delivery board.

Generic rules:

- Identify the existing issue before implementation.
- Create a missing issue when the team requires ticket-first execution.
- Keep status aligned with reality.
- Add validation evidence after implementation.
- Create follow-up issues for discovered work outside current scope.

Keep local:

- Tracker name.
- Board URLs.
- Status names.
- Default owner.
- Team-specific language requirements.

## Pattern 9: Local Journal Workflow

Use when a repo benefits from durable local execution notes.

Rules:

- Create a local journal at the start of repo investigation or implementation work.
- Record factual actions, decisions, issues, and validation results.
- Keep journals local-only unless the team explicitly wants them versioned.
- Do not record secrets, credentials, sensitive private data, or private URLs.

## Pattern 10: Validation Truthfulness

Use everywhere.

Agents must distinguish:

- Passed.
- Failed.
- Blocked.
- Skipped.
- Not run.

Completion reports should not imply that unrun checks passed.

## Pattern 11: Continuous Skill Learning

Use when a behavior repeats.

Promote to:

- Global baseline: behavior every agent should follow everywhere.
- Global skill: reusable workflow across repos.
- Parent instruction file: workspace convention.
- Repo instruction file: repo-specific architecture or process rule.
- Repo-local skill: specialized workflow for one repository or team.
- Automated guard: lint, test, CI, or script when enforceable.

## Pattern 12: Harness Routing

Use when the AI tool can choose among agents, model tiers, cache, or validation executors.

Rules:

- The master agent owns judgment, ambiguity, architecture, escalation, and final review.
- Delegated agents own narrow execution only.
- Route each subtask to the smallest capable model or agent that can complete it with high confidence and validation.
- Pass only the context needed for the subtask.
- Bypass cache when source-of-truth files changed or the user asks for fresh, current, repeated, or from-scratch analysis.

## Pattern 13: Framework Manifest And Readiness

Use when installing, auditing, or changing the framework itself.

Rules:

- Verify the canonical file set before relying on the framework.
- Choose a load profile that matches the task.
- Record actual tool capabilities instead of assuming sub-agents, cross-agent counterpart access, model routing, cache, validation execution, or journals exist.
- Treat unavailable capabilities as routing constraints with explicit fallbacks.
- Run first-session verification after adoption.
- Rebuild the distributable archive when shared files change.

Output:

- Framework readiness level.
- Missing files or stale adapter paths.
- Harness capability summary.
- Required validation commands.
- Journaling decision.
- Remaining gaps.

## Pattern 14: Quality Convergence Loop

Use when development quality must improve through measured iterations.

Rules:

- Define quality dimensions and target before iterating.
- Attach every score to evidence.
- Feed validation failures into the next iteration.
- Set max iterations before starting.
- Stop on target met, blocked validation, plateau, required approval, or scope expansion.
- Use breakpoints for architecture, security, data, release, or destructive decisions.

Output:

- Target and dimensions.
- Iterations run.
- Evidence gathered.
- Current readiness.
- Stop reason.
- Next step.
- Escalate when ambiguity, repeated failures, security, data loss, or multi-system coupling changes the risk profile.

Output:

- Routing decision.
- Assigned role or model tier.
- Inputs passed.
- Validation required.
- Escalation condition.

## Pattern 15: High-Signal PR Review

Use when PR feedback may be posted or relied on for readiness.

Rules:

- Run preflight stop checks before reviewing.
- Identify path-scoped instruction files for changed files.
- Use independent review passes when supported.
- Validate candidate issues before reporting.
- Drop speculative, style-only, linter-only, duplicate, and pre-existing findings.
- Post inline comments only when requested or policy requires it.

Output:

- Findings ordered by severity.
- Validation reviewed.
- Comments posted or withheld.
- Residual risk.

## Pattern 16: Ecosystem Terraform

Use when the user wants to bootstrap or reconcile the project operating system around the codebase.

Read `ECOSYSTEM_TERRAFORM_GUIDE.md` for command selection and prompt samples before using this pattern with an operator.

Modes:

- Roadmap terraform: requirements, docs, designs, boards, phases, tickets, QA matrix.
- Tech terraform: stack, repos, local environments, secrets contract, full quality-gate matrix, CI/CD, PR checks, security scans, runtime checks, AI workstream gates, and cloud/deploy gates.
- Assess then harden: whole-project read, knowledge docs, missing requirements, ticket gaps, hardening plan.

Rules:

- Ask material questions; discover safe answers from sources first.
- Verify MCP, CLI, repo, cloud, tracker, design, and sub-agent capabilities before relying on them.
- Ask for approval before external mutations, sub-agent swarms, broad imports, destructive board edits, cloud changes, or secret handling.
- Prefer updating existing roadmaps, boards, docs, and tickets over duplicates.
- Tie every ticket and QA recommendation to source evidence.

Output:

- Source map.
- Capability gate.
- Created, updated, proposed, and blocked artifacts.
- PR-sized tickets.
- Business-logic QA matrix.
- Technical quality-gate matrix when `/tech-terraform` is used.
- Approval gates and residual risk.
