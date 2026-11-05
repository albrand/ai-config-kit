# Board adapters: contract and provider recipes

## Safe integration order

1. Use the configured MCP connector first for interactive, human-led discovery and read-only ticket context. Keep source snapshots versioned and cite the board URL and revision. CI must use a deterministic API identity; MCP availability is not a CI dependency.
2. Start every adapter invocation in dry-run. Inspect the printed URL, method, headers with secrets redacted, and body. Tests inject a fake `fetch` and must assert request shape and zero network calls.
3. Enable `--apply` only in a protected CI job with a scoped secret. Read the item again immediately before a write; compare its revision/ETag when the provider supports it. On conflict, stop and re-plan rather than replaying a stale mutation.
4. Use bounded retries only for reads and explicitly idempotent writes: at most 3 attempts, exponential delays 250 ms, 1 s, 4 s plus jitter, honor `Retry-After`, and retry 429/502/503/504. Do not retry 400/401/403/404/409 or a timed-out non-idempotent write without reading back to reconcile. Respect each provider's published quotas and `Retry-After` / rate-limit reset headers.
5. A comment marker must be `<!-- qa-report:<work-item-id>:<commit-sha>:<sha256-of-normalized-content> -->`. Search existing comments for the full marker before posting. A commit alone is not an idempotency key because one commit can produce revised report content.
6. Upload an artifact first, confirm a durable URL/ID in the provider response, then attach/link it. A missing token, failed upload, missing URL, or unconfirmed follow-up means BLOCKED; never report success from a planned request.

## Adapter interface

The starter modules are in `templates/qa-kit/lib/boards/`. Keep this interface asynchronous and return `{dryRun, request}` or a response receipt. `revision` is an opaque ETag/revision captured by `read`.

```js
read(workItemId, { revision? })
comment(workItemId, markdown, marker) // marker includes item + commit + content hash
attach(workItemId, { filename, contentType, contentBase64 } | { url, title })
transition(workItemId, stateOrColumnId, revision)
linkPr(workItemId, { url, title, commitSha })
verifyEvent({ rawBody: Buffer, signature, secret, headers }) // boolean; constant-time compare
```

`attach` may be a board comment containing an already uploaded artifact URL when the board has no upload API. Return `confirmed: true` only after the API confirms the association. `transition` must compare revision where supported. Avoid logging auth headers or full binary bodies.

## Jira Cloud (REST v3)

- Auth: OAuth 2.0 (3LO) bearer token for integrations, or basic auth from account email + API token for a controlled bot. Example secrets: `JIRA_EMAIL`, `JIRA_API_TOKEN`; construct `Authorization: Basic base64(email:token)` in the caller. Grant least scopes for issue read/write, comments, attachments, and transitions. Never put tokens in JSON.
- Read + revision: `GET https://{site}.atlassian.net/rest/api/3/issue/{issueIdOrKey}?fields=summary,status,issuetype,updated,project,issuelinks`; record response `fields.updated` and optionally `GET .../transitions` for available transitions. Jira issue reads do not expose a universal numeric revision; fetch immediately before writing and do not assume `If-Match` is honored.
- Comment: `POST /rest/api/3/issue/{issueIdOrKey}/comment`, JSON body `{ "body": { "type":"doc", "version":1, "content":[{"type":"paragraph","content":[{"type":"text","text":"report text + full marker"}]}] } }` (ADF).
- Attach: `POST /rest/api/3/issue/{issueIdOrKey}/attachments`, multipart field `file`; header `X-Atlassian-Token: no-check`. Capture returned attachment id and filename.
- Transition: `GET /rest/api/3/issue/{id}/transitions`, then `POST` to the same path with `{ "transition": { "id":"<available-transition-id>" } }`. Do not send a state name where an ID is required.
- Link PR/artifact: `POST /rest/api/3/issue/{id}/remotelink` body `{ "object": { "url":"https://…", "title":"QA report" } }`; include PR URL and candidate SHA in the title/summary.
- Webhook: Jira Cloud delivery does not provide a universal built-in shared-secret signature on every webhook configuration. Put a trusted gateway in front that verifies an HMAC-SHA256 header such as `X-QA-Signature: sha256=<hex>` over the exact raw body; reject missing/invalid signatures before queueing. Use constant-time comparison.
- Rate/retry: honor `Retry-After` on 429 and Jira rate-limit headers; retry safe reads only, and reconcile write timeouts by reading comments/remote links for the complete marker.

## Azure Boards (REST 7.1)

- Auth: Microsoft Entra OAuth bearer token with `vso.work` / `vso.work_write` as needed, or a narrowly scoped PAT stored as `AZURE_DEVOPS_EXT_PAT`/`AZURE_BOARDS_TOKEN` in CI. Send `Authorization: Bearer …` for OAuth. PAT Basic is `Basic base64(:PAT)`; never print it.
- Read + revision: `GET https://dev.azure.com/{organization}/{project}/_apis/wit/workitems/{id}?$expand=relations&api-version=7.1`; response `rev` is the revision. For updates, `PATCH .../workitems/{id}?api-version=7.1`, `Content-Type: application/json-patch+json`, include `{ "op":"test", "path":"/rev", "value":<rev> }` first.
- Comment: `POST .../_apis/wit/workitems/{id}/comments?format=markdown&api-version=7.1-preview.4`, JSON `{ "text":"report\n\n<!-- qa-report:id:sha:hash -->" }`. The preview endpoint version is explicitly preview; pin and re-check provider API version before adoption. Alternative compatibility path is PATCH work item with JSON Patch add `/fields/System.History` and the marker.
- Attach: upload bytes with `POST .../_apis/wit/attachments?fileName={encoded-name}&api-version=7.1` and binary content type; use returned `url`. Then PATCH the work item with `[{"op":"test","path":"/rev","value":N},{"op":"add","path":"/relations/-","value":{"rel":"AttachedFile","url":"<upload-url>","attributes":{"comment":"QA evidence"}}}]`. Both upload and relation must confirm.
- Transition/move: PATCH work item with revision test plus `add /fields/System.State` and configured state. Board-column placement can also depend on `System.BoardColumn` and `System.BoardLane`; only write those fields if the process supports them and policy permits it.
- Link PR: PATCH work item with revision test plus `add /relations/-` value `{ "rel":"Hyperlink", "url":"<PR URL>", "attributes":{"comment":"PR <sha>"} }`. Azure Repos linking can use an ArtifactLink only when you provide the correct artifact URI; use Hyperlink for portable external PR URLs.
- Webhook: Service Hooks are authenticated by configured basic/shared secret or secured ingress depending on service; where the delivery does not sign the body, terminate it at an ingress that enforces a shared HMAC-SHA256 signature header over raw bytes. Verify before enqueueing and deduplicate delivery IDs.
- Rate/retry: honor 429 and `Retry-After`; Azure may also return 503 during throttling. Retry only reads/idempotent updates; after an uncertain PATCH, read the revision and verify the marker/field before retrying.

## Linear (GraphQL)

- Auth: personal API key for a dedicated automation user, or OAuth access token. Store as `LINEAR_API_KEY`; send `Authorization: <key>` (Linear's API accepts the key directly; `Bearer` is also used in OAuth flows). Scope access to the required team/workspace.
- Read + revision: `POST https://api.linear.app/graphql`, query `{ issue(id: $id) { id identifier title updatedAt state { id name } team { id key } } }`. Use `updatedAt` as a change detector. Linear mutations do not expose a general compare-and-swap revision argument; reread before write and stop if `updatedAt` changed.
- Comment: GraphQL `commentCreate(input:{issueId:$id, body:$body})`; body includes the complete marker. Before mutation, query comments for the marker to avoid duplicates.
- Attach: `attachmentLinkURL(input:{issueId:$id,url:$url,title:$title})`; upload artifact to CI storage first and require `success:true` plus returned attachment URL/ID.
- Transition/move: `issueUpdate(id:$id,input:{stateId:$stateId})`; obtain valid workflow state IDs from `workflowStates` for the issue's team. Linear has issue workflow states rather than a generic project column mutation.
- Link PR: use the same `attachmentLinkURL` mutation with PR URL and title containing commit SHA.
- Webhook: configure the Linear webhook signing secret; validate the provider HMAC-SHA256 signature header over the exact raw payload with constant-time comparison and reject invalid requests.
- Rate/retry: inspect GraphQL errors and HTTP 429; honor `Retry-After`. A 200 response can contain GraphQL errors, so require `errors` absent and mutation `success:true`. Do not retry mutation timeouts until querying for the marker/attachment.

## GitHub Issues and Projects v2

- Auth: GitHub App installation token preferred; classic/fine-grained PAT only for local/manual use. `GITHUB_TOKEN` in Actions needs minimum `issues: read/write`, `pull-requests: read`, `contents: read`, and project scopes if updating Projects v2. Use `GH_TOKEN`/`GITHUB_TOKEN` secrets, never persist them in config.
- Read + revision: REST `GET /repos/{owner}/{repo}/issues/{issue_number}`; record `updated_at` and response `ETag`. Send `If-Match: <etag>` where endpoint supports conditional requests; on 412 reread and re-plan. To read project fields, GraphQL `node(id)` / `projectV2` queries are required.
- Comment: `POST /repos/{owner}/{repo}/issues/{issue_number}/comments`, JSON `{ "body":"report\n\n<!-- qa-report:item:commit:hash -->" }`.
- Attach: GitHub Issues has no general binary-attachment upload endpoint. Upload report/screenshots as an Actions artifact or approved object store, verify its URL, then `POST` an issue comment with a Markdown link. Do not use undocumented browser upload endpoints.
- Transition: `PATCH /repos/{owner}/{repo}/issues/{issue_number}`, JSON `{ "state":"open"|"closed", "state_reason":"completed"|"not_planned" }`. For project column move, GraphQL mutation `updateProjectV2ItemFieldValue(input:{projectId,itemId,fieldId,value:{singleSelectOptionId}})`; resolve all IDs through GraphQL first.
- Link PR: if issue and PR share a repository, include `Fixes #N` in PR body for native linkage; otherwise post a comment with the PR URL and SHA, or use Projects v2 relationship fields where configured.
- Webhook: verify `X-Hub-Signature-256` as `sha256=<hex>` = HMAC-SHA256(secret, exact raw body) using constant-time comparison. Also deduplicate `X-GitHub-Delivery` and validate the event type/repository.
- Rate/retry: inspect `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`, and secondary-limit responses; pause until reset. Retry safe GET only. For write timeout, search for full content marker before retry.

## Adding another board

1. Create `lib/boards/<name>.mjs` exporting `<name>(config)` with all six methods above; also add `moveProjectItem` only if the board has a distinct column model.
2. Map each field to the board's immutable ID and revision model. Record exact HTTP method, URL, request headers, body, response receipt, auth scopes and rate limits in a reference page.
3. Dry-run returns a sanitized `{ dryRun:true, request:{ method,url,headers,body } }` and performs zero fetches. Apply mode uses injected `fetchImpl` so tests can capture requests without network.
4. Sign and verify webhooks from raw bytes; use constant-time signature checks, delivery deduplication and event allowlists.
5. Define comment marker as work-item + commit + normalized-content SHA-256. Search before create; never use commit-only dedupe.
6. Handle pagination and `Retry-After`; retry no more than three times and never blindly retry uncertain mutations.
7. Add offline tests for every request method/body, auth header redaction, dry-run no-send, --apply fetch, stale revision, rate-limit, duplicate marker, failed upload and invalid webhook signature.
8. Register the adapter in `lib/boards/index.mjs`, add config validation and document its environment variables. Keep dry-run the default until an operator reviews captured requests.
