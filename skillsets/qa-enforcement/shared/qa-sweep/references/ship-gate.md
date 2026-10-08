# P6 protected ship-gate procedure

## P6 Ship

Only what SHIPS is gated (v2 + v4): **pushes whose destination is protected** — the repo's default branch plus
`protected_branches` in `.qa/config.json` (resolved from the refspec, `HEAD:dev`,
`+dev` and bare `HEAD` forms, the current branch's upstream when there is no
refspec; `--all`/`--mirror` count as protected) — **tag pushes** (`git push origin
v1.2`, `refs/tags/…`, `tag v1.2`, `--tags`/`--follow-tags`) — and **production
deploys**: `vercel --prod` / `vercel deploy --prod` / `--target production`,
`vercel promote`, `vercel redeploy`,
`netlify deploy --prod`, `fly deploy`, **releases** (`gh release create`, and
`gh release edit` with `--draft=false` or `--tag`), **any
workflow dispatch** (`gh workflow run`: deploy workflows are dispatched exactly
this way, and a name→file→jobs mapping is not decidable locally in a hook — a
false positive only asks for a completed pipeline, a false negative ships), and
a **deployments-API POST that targets production** (`vercel api …/vN/deployments`
or curl, with `target: production` in the arguments, in a readable body file
such as `--input body.json` / `-d @body.json`, or anywhere in the command text),
plus a POST to the promote API. Env prefixes and runners (`FOO=1 …`, `env`,
`npx`, `bunx`, `pnpm dlx`, …) and multi-line commands classify like the bare
command.

Free on purpose: **every PR command** (`gh pr merge` with any flags, admin included,
`gh pr ready`, and the REST/GraphQL merge calls; owner decision 2026-10-06: production
fixes keep shipping), **feature-branch pushes** (that is how previews and CI get
built), **`gh pr create`** (that is how the preview and the PR are produced),
**`bb fleet validate`** (review should see the work before the merge, not
after), **preview deploys** (`vercel deploy` without a production target, and
a `vercel api`/curl POST to `/vN/deployments` whose target is a preview — the
a pilot repo heals seat-blocked previews through exactly that call, and
blocking it would deadlock the pilot again), and **`vercel rollback`**
(incident recovery restores an already-shipped deployment). A deployments POST
whose body cannot be seen at hook time (built by a script or piped on stdin)
and carries no production marker anywhere in the command is allowed: the hook
gates on evidence of production. The deadlock v1 had — the re-walk must be at
the shipped SHA but the preview for that SHA only exists after the push — is
resolved: walk against the preview of your feature-branch push, then ship.

Walk freshness is checked at **every commit the command ships** (v4): for a
protected push, the pushed source commit (or one `.qa/`-only commit on top of it) (`feat:main` checks `feat`); for a tag push or
release, the tagged commit (else `--target`, else the remote default branch);
for a workflow dispatch, its `--ref` (else the default branch) as origin knows
it; for other deploys, the local HEAD — each with the same `.qa`-only
allowance. A walked HEAD cannot clear an unwalked tag, and a walked tag cannot
hide an unwalked branch pushed next to it.

**Deployments ship their own commit (v5).** `vercel promote <deployment>`,
`vercel redeploy <deployment>`, `vercel alias [set] <deployment> <domain>`,
`vercel rolling-release start --dpl <deployment>`, the promote and alias APIs,
and a production deployments POST naming `deploymentId` ship a deployment that
already exists, so the gate resolves the commit Vercel built it from (one
read-only `vercel api /v13/deployments/<id|url>` through the CLI's own login,
scoped by `--scope`, the URL's `teamId`, or `.vercel/project.json`) and needs a
fresh run for THAT tree (tree equivalence; the run's records may sit in HEAD's
committed tree). It denies when the deployment is unknown, the CLI is missing,
logged out or offline, the lookup overruns its 3.2 s budget, the deployment
has no git metadata or was built dirty, or
its commit is not in the clone (`git fetch`). A production deployments-API
create whose body names a `gitSource` is checked at that commit, not HEAD. An
upload deploy (`vercel --prod`, `netlify deploy --prod`, `fly deploy`) ships the
working tree, so uncommitted changes outside `.qa/` deny it. GitHub API writes
that ship (`gh api` or curl to api.github.com: `merges`, release
create/publish, ref create/update, contents commits, workflow/repository
dispatch, deployments, and the GraphQL branch-merge/ref/commit mutations) deny
outright: use the gated CLI form (`gh release create|edit`, `git push`,
`gh workflow run`) so the shipped commit is checked. PR merge calls
(`pulls/N/merge`, `mergePullRequest`), reads and deletes stay free.

**Deadline.** A PreToolUse hook the host times out does not block: the command
runs (Claude Code 2.1.282, probed live; Codex 0.157.0, `pre_tool_use.rs`). So
the gate must decide before the host kills it. `coordinator-hook-pretool.sh`
exports `HOOK_T0` when the chain starts, and every gate counts from it:
a soft budget at 9 s, a hard deadline at 10 s (`HOOK_HARD_S`), under the host

timeout of 15 s (`HOOK_HOST_TIMEOUT_S`) on the chain's entry in
`~/.claude/settings.json` and `~/.codex/hooks.json`. A gate reached with the
time already spent decides at once. At the deadline a ship-shaped command in
an opted-in repo (or one whose opt-in was not yet read) denies; anything else
passes. `HOOK_T0` in the future or unreadable counts as 0 s spent: it can only
shorten a budget. `hooks/hook-timeouts.py check` fails when a host timeout is
below the gates' constant; both installers run `apply` (backup first).
`hooks/test-hook-chain.sh` runs the chain with a slow ship stage under the
configured timeout.


**Releases after a merge (tree equivalence).** A release tag normally points at
the squash or merge commit on the default branch, which is never the walked PR
head. For a **tag push, `gh release create`, or a `gh workflow run` on the
default branch** (no `--ref`, or `--ref <default>`), and only for those, the
walk also covers a commit whose root tree outside `.qa/` is **identical by tree
hash** to the tree of the walked commit (the committed run's `rewalk.json`
sha, which must be present in the clone). Squash-merging an up-to-date branch
therefore ships without a second walk. If any path outside `.qa/` differs
(the base moved, or a merge brought in other changes), the combined code was
never walked. Walk the merged commit, commit the evidence as one `.qa/`-only
commit on top, and tag or dispatch that. Protected-branch pushes,
non-default dispatches and other deploys keep the strict rule (walked sha or
one `.qa`-only commit on top). A commit that one command ships both as a tag
and to a protected branch is checked strictly.

The local gate (PreToolUse hook, git pre-push template) checks consistency; the
CI job reports the result on the commit. Whether it is a required check is the
owner's decision per repo. Where it is required, keep admin bypass on
(enforcement for non-admins only) so an admin can always merge a prod fix, and
keep what it checks to people walking the real app: a persona's journey through
frontend and backend, not mocks. The hooks never restrict a PR merge (owner
decision 2026-10-06). The CI
template handles merge queues (`merge_group` trigger; a queue run checks the
queued PR's head, taken from the PR number in the
`gh-readonly-queue/<base>/pr-<N>-<base-sha>` ref, never the group commit). In
husky repos the pre-push gate block goes at the **top** of `.husky/pre-push`
(see the template header): it saves the pushed refs, gates on them, and hands
them back to the husky script after it; appended after a script that reads
stdin it would see no refs and let every push through. If a ship is denied,
complete the pipeline; never delete `.qa/config.json` to dodge the gate.
