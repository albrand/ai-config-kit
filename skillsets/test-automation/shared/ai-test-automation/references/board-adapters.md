# Board adapters

Implement `read(id, revision?)`, `comment(id, body, idempotencyKey)`, `attach(id, artifact)`, `transition(id, state, revision)`, `linkPr(id, url)`, and `verifyEvent(request)`. Use MCP first for interactive reads when available; REST fallback for automation. All writes dry-run unless `--apply`. Respect scoped auth, ETags/revisions, rate limits and retries; never log tokens. Configure `boardAuthorizationEnv` with a provider-appropriate authorization header when Bearer auth is not supported.

- Jira: REST issue read/update/comment/attachment; use issue version or update precondition and idempotency marker.
- Azure Boards: Work Item Tracking REST with JSON Patch and `rev` test operation; attach file then add relation.
- Linear: GraphQL issue queries and mutations; retain issue ID and use comment marker for dedupe.
- GitHub Issues/Projects: REST/GraphQL issue, comment, label/project fields; use issue node ID and commit marker.

For another board, map the six operations, document auth scopes and throttling, add offline request-construction tests, then test idempotency and stale-revision behavior before enabling writes.
