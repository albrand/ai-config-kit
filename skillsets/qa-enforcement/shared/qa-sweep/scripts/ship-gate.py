#!/usr/bin/env python3
"""QA ship gate: fail-closed push/PR/deploy gate for repos that opted in.

A repo opts in by committing `.qa/config.json`. From that moment the gate is
ALWAYS ON for that repo for ship commands (merges, pushes to protected
branches, production deploys, releases, tag pushes, workflow dispatch -- see
segment_ship_kind). It denies unless the whole
discover->cluster->plan->fix->re-walk pipeline is complete at exactly the SHA
being shipped:

  .qa/config.json     repo opt-in: personas, workflows, optional deployed_check,
                      optional automation_identities (CI-owned walk identities)
  <run>/workflow.json   the task's scope: persona, entry, outcome, steps, target
  <run>/inventory.jsonl one row per defect found on the full walk (no fixing yet)
  <run>/clusters.json   row -> cluster, repro command, repro_failed_once: true
  <run>/plan.md         one plan covering every cluster id
  <run>/rewalk.json     verdict per workflow step, at the SHA being shipped
  <run>/evidence.json   qa-e2e-gate.mjs packet (claim_e2e_complete)

A run is `.qa/runs/<branch-slug>/` (per-branch, so concurrent PRs never
collide) or the legacy flat `.qa/`. The gate selects the run whose rewalk.sha
equals the shipped SHA (or its parent under a .qa-only head); no match is a
DENY naming the runs, two matches are an ambiguous DENY. Since v3 the
artifacts are read from the SHIPPED COMMIT's tree (git show sha:path), so
uncommitted working-tree records cannot clear a protected push or merge.

Subcommands:
  hook    PreToolUse adapter (stdin JSON; exit 2 = deny, 0 = allow)
  stop    Stop-hook adapter (blocks while inventory rows are still open)
  check   run the pipeline for a repo (exit 0 pass / 1 fail); --json for JSON
  clusters  cluster + plan subset of check (for the cluster-check entry point)
  record  append an event (inventory-closed | rewalk | escape) to events.jsonl
  selftest  build scratch repos and prove every deny/allow path

Fail-open / fail-closed rules (tested in selftest):
  - not a ship command              -> ALLOW, whatever happens
  - ship command, repo not opted in -> ALLOW, whatever happens
  - ship command, opted-in repo     -> DENY on any missing/incomplete artifact
                                       and on any internal error (fail closed)

Events (no secrets, no user text) append to
~/.local/state/agent-quality/events.jsonl.

Written 2026-09-24 per the qa-speed-quality research report (2026-09-24) S2:
the gate replaces prose, it does not add a rule. Adapted sources and
licenses: see LICENSES.md.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HOME = os.path.expanduser("~")
# QA_GATE_EVENTS_FILE overrides the sink: tests, demos and probes MUST point it
# at a scratch file so the live events file only ever receives real activity
# (the value panel counts these rows; selftest noise drowned it 2026-09-24).
EVENTS = os.environ.get("QA_GATE_EVENTS_FILE") or os.path.join(
    HOME, ".local", "state", "agent-quality", "events.jsonl")
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
# realpath: a symlinked skill dir makes the gate script no-op (its main() guard
# compares import.meta.url to argv[1]), so always run the resolved file.
# Candidates: the flattened skill-home sibling, the kit's agent-runtime copy,
# then the neutral hub home. First that exists wins; else the first (canonical
# flattened) path is kept so the failure message names a concrete location.
_E2E_CANDIDATES = [
    os.path.realpath(os.path.join(SKILL_DIR, "..", "..", "verified-qa-e2e", "scripts", "qa-e2e-gate.mjs")),
    os.path.realpath(os.path.join(SKILL_DIR, "..", "..", "..", "..", "agent-runtime", "shared",
                                  "verified-qa-e2e", "scripts", "qa-e2e-gate.mjs")),
    os.path.realpath(os.path.expanduser("~/.agents/skills/verified-qa-e2e/scripts/qa-e2e-gate.mjs")),
]
E2E_GATE = next((p for p in _E2E_CANDIDATES if os.path.isfile(p)), _E2E_CANDIDATES[0])

# ---- v2 ship classification (2026-09-24, card 3 meu-psi pilot) --------------
# v1 gated every push and every PR command, which deadlocked preview-based
# flows: the re-walk must be at the shipped SHA, but the preview for that SHA
# only exists after the push. v2 gates only what SHIPS: merges (gh pr merge,
# gh pr ready), pushes whose destination ref is protected (default branch plus
# .qa/config.json protected_branches), and production deploys. Feature-branch
# pushes, gh pr create and bb fleet validate are free: that is how previews,
# CI and review get produced. No dead patterns: every class below is exercised
# by selftest against a canonical sample.
# v4 (card 6): "what ships" also covers releases (gh release create), any
# workflow dispatch (gh workflow run -- justification at the classifier), tag
# pushes (--tags/--follow-tags/refs/tags/vX, checked at the tagged commit),
# vercel redeploy, and deployments-API POSTs that target production. Preview
# builds through the deployments API stay free (meu-psi heal).

GIT_VALUE_FLAGS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                   "--super-prefix", "--exec-path", "--config-env"}
PUSH_ALL_FLAGS = {"--all", "--mirror", "--branches"}
# v4: pushing tags ships whatever they point at (seahaven-style deploys are
# release/tag driven: `release: published` vX.Y.Z-staging, tag deploys).
TAG_PUSH_FLAGS = {"--tags", "--follow-tags"}
# v4: Vercel deployments API. Only PRODUCTION targets gate; preview builds
# through this API must stay free -- the meu-psi pilot rebuilds seat-blocked
# previews via exactly `vercel api "/v13/deployments?teamId=.." -X POST
# --input <body.json>`. The body usually sits in a file (the pallium autoheal
# posts PRODUCTION the same way), so readable body files are inspected too.
DEPLOY_CREATE_RE = re.compile(r"/v\d+/deployments(?:[?#]|$)")
PROMOTE_API_RE = re.compile(r"/v\d+/projects/[^/?#\s]+/promote/")
PROD_TARGET_RE = re.compile(r"""["']?\btarget["']?\s*[:=]\s*["']?production\b""")
# per tool: flags whose presence means "request body" (POST unless -X says
# otherwise), and the method flags. `vercel api -d` is --debug, not data.
API_BODY_FLAGS = {
    "curl": {"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii",
             "--json", "-F", "--form", "--form-string"},
    "vercel": {"--input", "-F", "--field", "-f", "--raw-field"},
}
API_METHOD_FLAGS = {"curl": {"-X", "--request"}, "vercel": {"-X", "--method"}}
BODY_FILE_MAX = 256 * 1024
# gh subcommand flags that take a value (so the positional parse skips it)
GH_RELEASE_VALUE_FLAGS = {"-t", "--title", "-n", "--notes", "-F", "--notes-file", "--notes-start-tag",
                          "--target", "--discussion-category", "-R", "--repo", "--tag"}
# pflag's false spellings: `gh release edit --draft=false` publishes a draft
# (`--draft false` does not: a bare bool flag takes no separate value)
PFLAG_FALSE = {"false", "0", "f", "F", "FALSE", "False"}
# ---- v5 (card 11): deployment provenance ------------------------------------
# `vercel promote|redeploy <deployment>` and the promote API ship a deployment
# that already exists; its code is the commit Vercel built it from, not the
# local HEAD. The gate resolves that commit through the vercel CLI's own login
# (read-only GET /v13/deployments/<id|url>; the hook never reads, prints or
# forwards a token) and requires a fresh run for its tree. Unresolvable
# provenance (unknown deployment, CLI missing or offline, no git metadata, a
# dirty build, a commit not in this clone) DENIES. The PreToolUse hook runs
# under the host's hook timeout and a timed-out hook proceeds, so every lookup
# in one command shares the hook budget and an expired budget denies.
VERCEL_VALUE_FLAGS = {"-S", "--scope", "-T", "--team", "-t", "--token", "--cwd", "-A", "--local-config",
                      "-Q", "--global-config", "--timeout", "--target", "-e", "--env", "-b", "--build-env",
                      "-m", "--meta", "--archive", "--dpl"}
PROMOTE_ID_RE = re.compile(r"/v\d+/projects/[^/?#\s]+/promote/([^/?#\s'\"]+)")
# the API forms of `vercel alias set <deployment> <domain>` (a production
# domain pointed at any deployment ships it) and of `vercel redeploy` (a
# deployments POST whose body names the deployment to rebuild)
ALIAS_API_RE = re.compile(r"/v\d+/deployments/([^/?#\s'\"]+)/aliases")
DEPLOYMENT_ID_BODY_RE = re.compile(r"""["']?deploymentId["']?\s*[:=]\s*["']?([A-Za-z0-9_.-]+)""")
DEPLOYMENT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
GIT_SOURCE_RE = re.compile(r"""["']?gitSource["']?\s*:\s*\{([^{}]*)\}""")
# GitHub REST/GraphQL writes that ship without a CLI form the gate can check
# (gh api / curl api.github.com): merging a PR, merging branches, creating or
# publishing a release, creating or moving a ref, committing file contents,
# dispatching a workflow, creating a deployment. The commit they ship is not
# decidable locally, so they DENY outright and name the gated CLI form.
GITHUB_WRITE_RE = re.compile(
    r"(?:^|/)repos/[^/\s]+/[^/\s?#]+/(pulls/\d+/merge|merges|releases(?:/\d+)?|git/refs(?:/[^\s?#]*)?|"
    r"actions/workflows/[^/\s]+/dispatches|dispatches|contents/[^\s?#]*|deployments)(?:[?#]|$)")
GITHUB_GRAPHQL_WRITE_RE = re.compile(
    r"\b(mergePullRequest|enablePullRequestAutoMerge|mergeBranch|createRef|updateRef|updateRefs|"
    r"createCommitOnBranch)\b")
GH_API_VALUE_FLAGS = {"-X", "--method", "-f", "--raw-field", "-F", "--field", "-H", "--header", "--input",
                      "-q", "--jq", "-t", "--template", "--hostname", "--cache", "-p", "--preview"}
LOOKUP_BUDGET_S = 3.2
_LOOKUP_DEADLINE = None
# The whole PreToolUse decision must land before the host's hook timeout: a
# timed-out hook lets the command run (verified 2026-09-25: a live probe on
# Claude Code 2.1.282, and codex-rs/hooks pre_tool_use.rs at rust-v0.157.0,
# where a timeout is a Failed run that never blocks). Lookups and deployed
# checks are clamped to what is left, a commit reached after the soft budget
# denies, and a hard SIGALRM decides on the spot: deny for a ship in an
# opted-in repo, allow otherwise (the same rule as a crash).
# The clock starts when the host starts the hook chain, not when this process
# does: coordinator-hook-pretool.sh exports HOOK_T0, so interpreter start-up
# and the stages before this one count. With a 5 s host timeout and a clock
# that started in hook(), a loaded host decided in 4.9-6.0 s (2026-09-25,
# load 145-190) and the command ran ungated. The installers set the host
# timeout (HOOK_HOST_TIMEOUT_S) on every entry that runs the chain, and
# hooks/check-hook-timeouts.sh refuses a config below it.
HOOK_HOST_TIMEOUT_S = 15.0
# Below the chain supervisor's GATE_DEADLINE (11 s, coordinator-hook-pretool.sh),
# which kills a stage still running then; this gate's own deny usually wins.
HOOK_HARD_S = 10.0
HOOK_BUDGET_S = HOOK_HARD_S - 1.0
_HOOK_DEADLINE = None
# None until _hook() knows whether the command targets an opted-in repo. At
# the hard deadline, unknown counts as opted in: a deadline that fires before
# the opt-in check (a chain that spent its budget before this process
# started) must not let a ship-shaped command through.
_HOOK_OPTED = None


def hook_elapsed(now=None):
    """Seconds since the hook chain started (HOOK_T0, epoch seconds). 0 when
    unset or unreadable, and never negative: a T0 in the future cannot buy
    more time, it can only be ignored."""
    try:
        t0 = float(os.environ.get("HOOK_T0", ""))
    except ValueError:
        return 0.0
    return max(0.0, (time.time() if now is None else now) - t0)


def time_left():
    """Seconds left in this hook invocation (infinite outside hook())."""
    return float("inf") if _HOOK_DEADLINE is None else _HOOK_DEADLINE - time.monotonic()

GH_WORKFLOW_VALUE_FLAGS = {"-r", "--ref", "-f", "--raw-field", "-F", "--field", "-R", "--repo"}
# wrappers that run a command unchanged: stripped before classification so
# `FOO=1 vercel --prod`, `npx vercel@latest --prod` or `env gh pr merge 5`
# classify like the bare command (pre-v4 they were invisible to the hook)
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
PLAIN_WRAPPERS = {"env", "command", "exec", "nohup", "time", "sudo", "npx", "bunx", "pnpx"}
WRAPPER_VALUE_FLAGS = {"env": {"-u", "--unset", "-C", "--chdir"}, "sudo": {"-u", "--user", "-g", "--group"},
                       "npx": {"-p", "--package"}, "pnpm": {"--package"}, "yarn": {"-p", "--package"},
                       "npm": {"-p", "--package"}}
RUNNER_SUBCOMMANDS = {"pnpm": {"exec", "dlx"}, "yarn": {"exec", "dlx"}, "npm": {"exec", "x"},
                      "bun": {"x"}}
SHIP_BINS = {"git", "gh", "vercel", "netlify", "fly", "flyctl", "curl"}

ROW_STATUSES = ("open", "closed", "fail_escalated")
ROW_FIELDS = ("id", "step", "symptom", "evidence", "predates_change", "severity", "status")


def run_git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=5)


def repo_root(start):
    cur = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isdir(os.path.join(cur, ".git")) or os.path.isfile(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def opted_in(root):
    if not root:
        return False
    return os.path.isfile(os.path.join(root, ".qa", "config.json"))


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def read_lines(path):
    with open(path, encoding="utf-8") as fh:
        return [ln for ln in (raw.strip() for raw in fh) if ln]


def derive_provider(payload):
    """Provider from the hook payload itself (measured 2026-09-24):
    Claude PreToolUse carries transcript_path under ~/.claude/projects,
    prompt_id, tool_use_id 'toolu_*'; Codex carries transcript_path under
    ~/.codex/sessions (rollout-*), model and turn_id. Env vars are the
    fallback; empty only when nothing identifies the caller."""
    tp = str(payload.get("transcript_path") or payload.get("transcriptPath") or "")
    if "/.codex/sessions/" in tp or "/rollout-" in tp:
        return "codex"
    if "/.claude/projects/" in tp:
        return "claude-code"
    if payload.get("turn_id") is not None or payload.get("model"):
        return "codex"
    if payload.get("prompt_id") is not None or str(payload.get("tool_use_id", "")).startswith("toolu_"):
        return "claude-code"
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "claude-code"
    for k in os.environ:
        if k.startswith("CODEX_"):
            return "codex"
    return ""


def emit(event, repo, sha="", data=None, provider=""):
    try:
        root = repo_root(repo) if repo else None
        branch = run_git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() if root else ""
        if branch == "HEAD":
            branch = "(detached)"
        rec = {
            "schema_version": 1,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "event": event,
            "repo": os.path.basename(root) if root else "",
            "repo_path": root or "",
            "branch": branch,
            "sha": (sha or (run_git(root, "rev-parse", "HEAD").stdout.strip() if root else ""))[:12],
            "thread_id": os.environ.get("BB_THREAD_ID", ""),
            "provider": provider or os.environ.get("QA_GATE_PROVIDER", os.environ.get("AGENT_PROVIDER", "")),
            "data": data or {},
        }
        os.makedirs(os.path.dirname(EVENTS), exist_ok=True)
        with open(EVENTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def branch_slug(branch):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-") or "detached"


def qa_reader(root, sha=None):
    """Artifact access as (exists(rel), read(rel)) over repo-relative paths.
    With a sha that exists locally, artifacts come from THAT COMMIT'S tree
    (git show sha:rel) -- v3 security fix: uncommitted working-tree records
    can no longer clear a protected push or merge; a shipped commit carries
    its own evidence. Without a sha, the working tree (mid-sweep helpers)."""
    if sha and run_git(root, "cat-file", "-e", sha + "^{commit}").returncode == 0:
        def exists(rel):
            return run_git(root, "cat-file", "-e", "%s:%s" % (sha, rel)).returncode == 0

        def read(rel):
            p = run_git(root, "show", "%s:%s" % (sha, rel))
            if p.returncode != 0:
                raise FileNotFoundError(rel)
            return p.stdout
        return {"exists": exists, "read": read}

    def exists(rel):
        return os.path.isfile(os.path.join(root, rel))

    def read(rel):
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            return fh.read()
    return {"exists": exists, "read": read}


def qa_run_dirs(root, sha=None, rd=None):
    """Candidate run dirs as repo-relative paths: .qa/runs/<name>/ plus the
    legacy flat .qa/ when it holds a run (or when there are no runs at all,
    so legacy messages still name .qa/ paths). At a sha, the listing comes
    from that commit's tree."""
    dirs = []
    if sha:
        p = run_git(root, "ls-tree", "--name-only", sha, "--", ".qa/runs/")
        if p.returncode == 0:
            for line in p.stdout.splitlines():
                name = line.strip().rstrip("/").split("/")[-1]
                if name:
                    dirs.append(".qa/runs/" + name)
        legacy_has = run_git(root, "cat-file", "-e", "%s:.qa/rewalk.json" % sha).returncode == 0
    else:
        runs = os.path.join(root, ".qa", "runs")
        if os.path.isdir(runs):
            dirs = [".qa/runs/" + n for n in sorted(os.listdir(runs))
                    if os.path.isdir(os.path.join(runs, n))]
        legacy_has = os.path.isfile(os.path.join(root, ".qa", "rewalk.json"))
    if legacy_has or not dirs:
        dirs.append(".qa")
    return dirs


def resolve_run(root, sha, rd, equiv=False, listing=None):
    """(dir, None) for the one run re-walked at `sha` (or at its parent under
    a .qa/-only head; with equiv, at a commit whose tree outside .qa/ is
    identical -- used only when no sha/parent match exists); (None, failure)
    when none or several match. A single candidate is returned as is, so the
    legacy flat layout and a lone run behave exactly as before. `listing`
    (v5): the commit whose tree holds the records when it is not `sha`
    itself (a deployment built from a code commit whose run was committed
    later); it is the commit `rd` reads from."""
    cands = qa_run_dirs(root, listing or sha, rd)
    if len(cands) == 1:
        return cands[0], None
    seen, matches, equiv_matches = [], [], []
    for d in cands:
        try:
            walked = str(json.loads(rd["read"](d + "/rewalk.json")).get("sha") or "")
        except Exception:
            walked = ""
        seen.append("%s@%s" % (d, walked[:12] or "-"))
        if walked and (walked == sha or rewalk_parent_ok(root, sha, walked)):
            matches.append(d)
        elif equiv and walk_fresh(root, sha, walked, equiv=True):
            equiv_matches.append(d)
    if not matches:
        matches = equiv_matches
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, "no QA run has a re-walk at %s (runs: %s)" % (str(sha)[:12], ", ".join(seen))
    return None, "ambiguous QA runs for %s: %s (one run per branch)" % (str(sha)[:12], ", ".join(matches))


def default_run(root):
    """Working-tree default for mid-sweep helpers (record, cluster-check):
    .qa/runs/<slug of current branch>/ when present, else the legacy .qa/."""
    branch = run_git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    d = os.path.join(root, ".qa", "runs", branch_slug(branch))
    return d if os.path.isdir(d) else os.path.join(root, ".qa")


def check_config(root, rd, fails):
    rel = ".qa/config.json"
    if not rd["exists"](rel):
        fails.append(".qa/config.json missing (repo opt-in)")
        return None
    try:
        cfg = json.loads(rd["read"](rel))
    except Exception as exc:
        fails.append(f".qa/config.json unparseable: {exc}")
        return None
    if not (isinstance(cfg.get("personas"), list) and cfg["personas"]):
        fails.append(".qa/config.json: personas must be a non-empty list")
    if not (isinstance(cfg.get("workflows"), list) and cfg["workflows"]):
        fails.append(".qa/config.json: workflows must be a non-empty list")
    else:
        for wf in cfg["workflows"]:
            if not (isinstance(wf, dict) and wf.get("name")):
                fails.append(".qa/config.json: every workflow needs a name")
    return cfg


def check_workflow(qa, rd, cfg, fails):
    rel = qa + "/workflow.json"
    if not rd["exists"](rel):
        fails.append(rel + " missing (P0 scope: persona, entry, outcome, steps, target)")
        return None
    try:
        wf = json.loads(rd["read"](rel))
    except Exception as exc:
        fails.append(f"{rel} unparseable: {exc}")
        return None
    if not (wf.get("persona") or wf.get("personas")):
        fails.append(rel + ": persona missing")
    for key in ("entry", "outcome"):
        if not wf.get(key):
            fails.append(rel + f": {key} missing")
    steps = wf.get("steps")
    if not (isinstance(steps, list) and steps and all(isinstance(s, str) and s for s in steps)):
        fails.append(rel + ": steps must be a non-empty list of step names")
    target = wf.get("target")
    if not (isinstance(target, dict) and target.get("url") and target.get("sha")):
        fails.append(rel + ": target needs url and sha")
    if cfg and isinstance(cfg.get("workflows"), list):
        names = {w.get("name") for w in cfg["workflows"] if isinstance(w, dict)}
        if wf.get("workflow") and names and wf["workflow"] not in names:
            fails.append(rel + f": '{wf['workflow']}' is not a workflow named in .qa/config.json")
    return wf


def check_inventory(qa, rd, fails, stats):
    rel = qa + "/inventory.jsonl"
    if not rd["exists"](rel):
        fails.append(rel + " missing (P1 full-walk inventory)")
        return []
    rows = []
    try:
        for i, ln in enumerate([l for l in rd["read"](rel).splitlines() if l.strip()], 1):
            try:
                row = json.loads(ln)
            except Exception as exc:
                fails.append(f"{rel} line {i} unparseable: {exc}")
                continue
            miss = [f for f in ROW_FIELDS if f not in row]
            if miss:
                fails.append(f"inventory row {row.get('id', 'line %d' % i)}: missing field(s) {', '.join(miss)}")
                continue
            if row["status"] not in ROW_STATUSES:
                fails.append(f"inventory row {row['id']}: status '{row['status']}' not in {ROW_STATUSES}")
            if row["status"] == "open":
                fails.append(f"inventory row {row['id']} still OPEN ({row['step']}: {row['symptom']})")
            if row["status"] == "fail_escalated" and not row.get("escalation"):
                fails.append(f"inventory row {row['id']} is fail_escalated without an escalation reference")
            if not isinstance(row["predates_change"], bool):
                fails.append(f"inventory row {row['id']}: predates_change must be true/false")
            # A gate failure caused by another writer mutating the same data
            # (meu-psi 2026-09-25: a CI setup and interactive walks sharing the
            # CI identities) is a defect with a named writer, never a blind re-run.
            if row.get("kind") == "environment_contamination" and not str(row.get("writer") or "").strip():
                fails.append(f"inventory row {row['id']}: environment_contamination must name the writer "
                             f"(CI run id, thread id or job) that mutated the data")
            rows.append(row)
    except Exception as exc:
        fails.append(f"{rel} unreadable: {exc}")
        return []
    stats["rows_total"] = len(rows)
    stats["open_rows"] = sum(1 for r in rows if r["status"] == "open")
    stats["predates_count"] = sum(1 for r in rows if r.get("predates_change") is True)
    return rows


def check_clusters(qa, rd, rows, fails, stats):
    rel = qa + "/clusters.json"
    if not rd["exists"](rel):
        fails.append(rel + " missing (P2 clustering with red repro)")
        return None
    try:
        doc = json.loads(rd["read"](rel))
        clusters = doc.get("clusters", [])
        mapping = doc.get("mapping", {})
    except Exception as exc:
        fails.append(f"{rel} unparseable: {exc}")
        return None
    ids = set()
    for cl in clusters if isinstance(clusters, list) else []:
        if not (isinstance(cl, dict) and cl.get("id")):
            fails.append(rel + ": every cluster needs an id")
            continue
        ids.add(cl["id"])
        if not cl.get("hypothesis"):
            fails.append(f"cluster {cl['id']}: hypothesis missing (root cause, not symptom)")
        if not cl.get("repro_command"):
            fails.append(f"cluster {cl['id']}: repro_command missing")
        if cl.get("repro_failed_once") is not True:
            fails.append(f"cluster {cl['id']}: repro_failed_once must be true (make it fail once before trusting it)")
    if not isinstance(mapping, dict):
        fails.append(rel + ": mapping must be an object of row-id -> cluster-id")
        mapping = {}
    for row in rows:
        cid = mapping.get(row["id"])
        if not cid:
            fails.append(f"inventory row {row['id']} is not mapped to a cluster")
        elif cid not in ids:
            fails.append(f"inventory row {row['id']} maps to unknown cluster '{cid}'")
    stats["clusters"] = len(ids)
    return doc


def check_plan(qa, rd, clusters, fails):
    rel = qa + "/plan.md"
    if not rd["exists"](rel):
        fails.append(rel + " missing (P3 one plan for every cluster)")
        return False
    try:
        text = rd["read"](rel)
    except Exception as exc:
        fails.append(f"{rel} unreadable: {exc}")
        return False
    for cl in (clusters or {}).get("clusters", []) if isinstance(clusters, dict) else []:
        if isinstance(cl, dict) and cl.get("id") and cl["id"] not in text:
            fails.append(rel + f" does not cover cluster {cl['id']}")
    return True


def rewalk_parent_ok(root, head, walked):
    """True when `head` (any sha present in the local repo) is exactly one
    .qa/-only commit on top of `walked`."""
    if not head:
        return False
    if run_git(root, "cat-file", "-e", head + "^{commit}").returncode != 0:
        return False  # shipped head not present locally: cannot verify
    parent = run_git(root, "rev-parse", head + "~1").stdout.strip()
    if not parent or parent != walked:
        return False
    diff = run_git(root, "diff", "--name-only", head + "~1", head).stdout.split()
    return bool(diff) and all(d == ".qa" or d.startswith(".qa/") for d in diff)


def tree_equiv_outside_qa(root, shipped, walked):
    """True when both commits exist locally and their root trees are identical
    outside .qa/: every top-level entry except .qa has the same mode, type and
    object hash. Tree hashes only, no heuristics. v4 (coordinator decision,
    card 6): a squash or merge commit whose code tree IS the walked code tree
    ships code that was walked, so a tag / release / default-branch dispatch
    of it needs no second walk; any non-.qa difference (other changes merged
    in) still does."""
    def entries(c):
        p = run_git(root, "ls-tree", "-z", "%s^{commit}" % c)
        if p.returncode != 0:
            return None
        return sorted(e for e in p.stdout.split("\0") if e and e.split("\t", 1)[-1] != ".qa")
    if not shipped or not walked:
        return False
    a, b = entries(shipped), entries(walked)
    return a is not None and b is not None and a == b


def walk_fresh(root, shipped, walked, equiv=False):
    """The walk at `walked` covers `shipped`: same sha, one .qa-only commit on
    top, or (equiv: tags, releases, default-branch dispatch) an identical
    tree outside .qa/."""
    return bool(walked) and (walked == shipped or rewalk_parent_ok(root, shipped, walked)
                             or (equiv and tree_equiv_outside_qa(root, shipped, walked)))


def check_rewalk(root, qa, rd, wf, sha, fails, stats, equiv=False):
    rel = qa + "/rewalk.json"
    if not rd["exists"](rel):
        fails.append(rel + " missing (P5 re-walk of the whole workflow)")
        return None
    try:
        doc = json.loads(rd["read"](rel))
    except Exception as exc:
        fails.append(f"{rel} unparseable: {exc}")
        return None
    if not doc.get("sha"):
        fails.append(rel + ": sha missing")
    elif sha and doc["sha"] != sha:
        if not walk_fresh(root, sha, str(doc["sha"]), equiv):
            why = (" and its tree outside .qa/ differs (or the walked commit is not in this clone)"
                   if equiv else "")
            fails.append(f"{rel} sha {str(doc['sha'])[:12]} != shipped sha {str(sha)[:12]}{why}: "
                         f"re-walk at the new commit")
    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        fails.append(rel + ": steps must be a non-empty list")
    else:
        for st in steps:
            if not isinstance(st, dict) or not st.get("step"):
                fails.append(rel + ": every step needs a step name")
                continue
            if st.get("verdict") != "PASS":
                fails.append(f"{rel} step '{st['step']}': verdict {st.get('verdict')!r} (only PASS clears the gate)")
            if not st.get("evidence"):
                fails.append(f"{rel} step '{st['step']}': evidence missing")
        if isinstance(wf, dict) and isinstance(wf.get("steps"), list):
            walked = {st.get("step") for st in steps if isinstance(st, dict)}
            for name in wf["steps"]:
                if name not in walked:
                    fails.append(rel + f": workflow step '{name}' has no verdict")
        stats["rewalk_steps"] = len(steps)
        stats["rewalk_failed"] = sum(1 for st in steps if isinstance(st, dict) and st.get("verdict") != "PASS")
    return doc


def declared_identities(auth):
    """Every identity block in an evidence packet: the legacy single
    `identity` plus each entry of `identities` (one per persona). Mirrors
    declaredIdentities() in qa-e2e-gate.mjs, so both gates read the same set."""
    out = []
    if not isinstance(auth, dict):
        return out
    if "identity" in auth:
        out.append(auth["identity"])
    ids = auth.get("identities")
    if isinstance(ids, list):
        out.extend(ids)
    elif ids is not None:
        out.append(ids)
    return out


# Identity labels (review r1 D4). `E2E.patient`, `e2e.patient `,
# `e2e.patient@meupsi.test` and `e2е.patient` (Cyrillic е) all name the CI
# suite's e2e.patient, and an exact-string match let each one through as
# unowned. Both sides are normalised (NFKC, casefold, strip, an @domain suffix
# dropped), and a label that mixes scripts, carries invisible characters, or
# only differs from a listed label by look-alike letters is refused outright.
# label_problem() and label_key() have a twin in qa-e2e-gate.mjs; the selftest
# runs the same labels through both.
_LABEL_SCRIPTS = (
    ("latin", ((0x41, 0x24F), (0x250, 0x2AF), (0x1E00, 0x1EFF), (0x2C60, 0x2C7F), (0xA720, 0xA7FF), (0xAB30, 0xAB6F))),
    ("greek", ((0x370, 0x3FF), (0x1F00, 0x1FFF))),
    ("cyrillic", ((0x400, 0x52F), (0x1C80, 0x1C8F), (0x2DE0, 0x2DFF), (0xA640, 0xA69F))),
)
# Letters that read as a Latin letter (UTS #39 confusables, single letters).
_LABEL_CONFUSABLES = {
    "а": "a", "е": "e", "і": "i", "ј": "j", "к": "k", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "ѕ": "s", "ԁ": "d", "һ": "h", "ԛ": "q", "ԝ": "w", "ӏ": "l", "ѵ": "v", "ү": "y",
    "α": "a", "γ": "y", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u",
    "χ": "x", "ω": "w", "ı": "i", "ɑ": "a", "ɩ": "i", "0": "o", "1": "l",
}


def label_key(label):
    """The comparable form of an identity label: NFKC, casefolded, stripped,
    without an @domain suffix."""
    import unicodedata
    s = unicodedata.normalize("NFKC", str(label)).casefold().strip()
    at = s.rfind("@")
    if at > 0:
        s = s[:at].strip()
    return s


def _label_script(ch):
    cp = ord(ch)
    for name, ranges in _LABEL_SCRIPTS:
        if any(a <= cp <= b for a, b in ranges):
            return name
    return "block-%x" % (cp >> 8)


def label_skeleton(label):
    """NFD without combining marks, then look-alike letters: `E2E.PATİENT`
    casefolds to `e2e.pati̇ent` (i + U+0307), which reads as e2e.patient."""
    import unicodedata
    s = unicodedata.normalize("NFD", label_key(label))
    return "".join(_LABEL_CONFUSABLES.get(c, c) for c in s if unicodedata.category(c) != "Mn")


def label_problem(label):
    """Why a label cannot be trusted as written (mixed scripts, invisible or
    control characters), or None."""
    import unicodedata
    s = unicodedata.normalize("NFKC", str(label))
    if any(unicodedata.category(c) in ("Cf", "Cc") for c in s):
        return "carries invisible or control characters"
    scripts = sorted({_label_script(c) for c in s if c.isalpha()})
    if len(scripts) > 1:
        return "mixes scripts (%s)" % ", ".join(scripts)
    return None


def owner_run_problems(ident, owned):
    """Why an identity block's `walker` is not a valid owner_run (the
    automation's own CI run recorded as the walk), as messages; [] when it is
    one or there is no walker. Twin of ownerRunProblems() in qa-e2e-gate.mjs,
    which also lifts IDENTITY_OWNED_BY_AUTOMATION for a valid one."""
    walker = ident.get("walker")
    if walker is None and "walker" not in ident:
        return []
    if not isinstance(walker, dict) or walker.get("kind") != "owner_run":
        return ["walker.kind must be \"owner_run\""]
    out = []
    if ident.get("owned_by_automation") is not True:
        out.append("an owner_run walks an identity an automated suite owns (owned_by_automation: true)")
    wo, io = walker.get("owner"), ident.get("owner")
    if not (isinstance(wo, str) and wo.strip() and isinstance(io, str) and wo.strip() == io.strip()):
        out.append("walker.owner must be the identity block's owner")
    rid = owner_run_id(walker)
    if rid is None:
        out.append("an owner_run names the CI run id it records (walker.run_id, digits)")
    m = RUN_URL_RE.match(walker["run_url"].strip()) if isinstance(walker.get("run_url"), str) else None
    if not m:
        out.append("an owner_run names its run page: walker.run_url "
                   "https://github.com/<owner>/<repo>/actions/runs/<run_id>")
    elif rid is not None and m.group(3) != rid:
        out.append(f"walker.run_url names run {m.group(3)}, not run_id {rid}")
    if not owned:
        out.append("an owner_run is accepted only against the repository's automation_identities "
                   "(.qa/config.json), and none is configured")
    elif (listed_identity(ident.get("label") or "", owned) or (None, None))[1] != "same":
        out.append("an owner_run walks an identity listed in .qa/config.json automation_identities")
    return out


# A GitHub Actions run page; twin of RUN_URL in qa-e2e-gate.mjs. ASCII digits
# only: Python's \d also matches fullwidth ones, which JavaScript's does not.
RUN_URL_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/actions/runs/(\d+)(?:/attempts/\d+)?$",
                        re.ASCII)
RUN_ATTEMPT_RE = re.compile(r"/attempts/(\d+)$", re.ASCII)


def owner_run_id(walker):
    rid = walker.get("run_id")
    if isinstance(rid, int) and not isinstance(rid, bool) and rid > 0:
        return str(rid)
    if isinstance(rid, str) and re.fullmatch(r"\d+", rid.strip(), re.ASCII):
        return rid.strip()
    return None


def origin_repo(root):
    """'owner/repo' of the origin remote on github.com, lowercased, or None."""
    try:
        url = run_git(root, "remote", "get-url", "origin").stdout.strip()
    except Exception:
        return None
    m = re.match(r"^(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com(?::\d+)?/)"
                 r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}".lower() if m else None


# An ISO 8601 time that carries its offset (Z or +hh:mm). A naive time would be
# read in the hook's local zone here and as UTC by some parsers, so it is not a
# time at all (review r2a-bis). Twin of ZONED_TIME in qa-e2e-gate.mjs.
ZONED_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$", re.ASCII)


def _iso(s):
    if not isinstance(s, str) or not ZONED_TIME_RE.match(s.strip()):
        return None
    try:
        return datetime.datetime.fromisoformat(s.strip().replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _run_attempt(root, repo, rid, attempt, cache=None):
    """(run attempt object, None) from the GitHub API, or (None, reason). The
    named attempt, or the run's latest one when the URL names none. `cache` is
    one check's: #36 names the same run for two identities, and both lookups
    shared one 3.2 s budget (review r2a-bis)."""
    global _LOOKUP_DEADLINE
    key = (repo.lower(), rid, attempt)
    if cache is not None and key in cache:
        return cache[key]
    path = f"repos/{repo}/actions/runs/{rid}" + (f"/attempts/{attempt}" if attempt else "")
    now = time.monotonic()
    if _LOOKUP_DEADLINE is None:
        _LOOKUP_DEADLINE = now + LOOKUP_BUDGET_S
    left = min(_LOOKUP_DEADLINE - now, time_left() - 0.6)
    if left < 0.3:
        return None, f"run {rid}: lookup budget ({LOOKUP_BUDGET_S:.1f} s per command) is spent; retry"
    try:
        p = subprocess.run(["gh", "api", path], cwd=root, capture_output=True, text=True, timeout=left,
                           env=dict(os.environ, GH_PROMPT_DISABLED="1", NO_COLOR="1"))
    except FileNotFoundError:
        return None, f"run {rid}: the gh CLI is not on the hook's PATH, so the run cannot be checked"
    except subprocess.TimeoutExpired:
        return None, f"run {rid}: `gh api {path}` timed out after {left:.1f} s; retry"
    except Exception as exc:
        return None, f"run {rid}: `gh api {path}` could not run: {_redact(str(exc))}"
    if p.returncode != 0:
        lines = (p.stderr or p.stdout or "").strip().splitlines()
        res = None, f"run {rid}: `gh api {path}` failed (rc={p.returncode}: {_redact(lines[-1] if lines else '')})"
    else:
        try:
            run = json.loads(p.stdout)
        except ValueError:
            run = None
        res = (run, None) if isinstance(run, dict) else (None, f"run {rid}: `gh api {path}` returned no run object")
    if cache is not None:
        cache[key] = res
    return res


def owner_run_verify(root, ident, walked_sha, cache=None):
    """What the ship gate checks of a well-formed owner_run beyond the packet
    (review r2a D5, r2a-bis): the run URL's repository is this repository's
    origin, and the run attempt the URL names (or the run's latest attempt)
    exists, completed with success, was built from the walked commit, and
    spans the walk window from its own start to its last update. Every failure
    is a reason, and a reason denies. The lookup shares the v5 provenance
    lookup's budget and deadline."""
    walker = ident["walker"]
    url = walker["run_url"].strip()
    m = RUN_URL_RE.match(url)
    repo, rid = f"{m.group(1)}/{m.group(2)}", m.group(3)
    am = RUN_ATTEMPT_RE.search(url)
    attempt = am.group(1) if am else None
    if not root:
        return ["no repository to check the run against (the ship gate verifies an owner_run from its repo)"]
    origin = origin_repo(root)
    if origin is None:
        return ["the repository's origin remote is not on github.com, so the run cannot be tied to it"]
    if repo.lower() != origin:
        return [f"walker.run_url is a run of {repo}, not of this repository ({origin})"]
    run, why = _run_attempt(root, repo, rid, attempt, cache)
    if why:
        return [why]
    name = f"run {rid} attempt {run.get('run_attempt') or attempt or '?'}"
    out = []
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        out.append(f"{name} is {run.get('status') or '?'}/{run.get('conclusion') or '-'}, "
                   f"not completed/success: an unfinished or failed run is not a walk")
    head = str(run.get("head_sha") or "").lower()
    if not walked_sha:
        out.append(f"{name}: no walked commit (rewalk.json sha) to compare its head_sha with")
    elif head != str(walked_sha).lower():
        out.append(f"{name} ran on {head[:12] or '?'}, not the walked commit {str(walked_sha)[:12]}")
    start, end = _iso(run.get("run_started_at")), _iso(run.get("updated_at"))
    w = ident.get("walk_window") if isinstance(ident.get("walk_window"), dict) else {}
    ws, we = _iso(w.get("start")), _iso(w.get("end"))
    if None in (ws, we):
        out.append(f"walk_window {w.get('start')}..{w.get('end')} is not two ISO 8601 times with an offset (Z or +hh:mm)")
    elif None in (start, end) or not (start <= ws <= we <= end):
        out.append(f"{name} ran {run.get('run_started_at')}..{run.get('updated_at')}; the walk window "
                   f"{w.get('start')}..{w.get('end')} is not inside it")
    return out



def listed_identity(label, owned):
    """(listed label, how) when `label` names an entry of automation_identities
    after normalisation ('same') or only by look-alike letters ('confusable')."""
    key, skel = label_key(label), label_skeleton(label)
    for o in owned:
        if not isinstance(o, str):
            continue
        if label_key(o) == key:
            return o, "same"
    for o in owned:
        if isinstance(o, str) and label_skeleton(o) == skel:
            return o, "confusable"
    return None
def check_e2e(qa, rd, cfg, fails, root=None, walked_sha=None):
    rel = qa + "/evidence.json"
    gate = (cfg or {}).get("e2e_evidence_gate") or E2E_GATE
    if not rd["exists"](rel):
        fails.append(rel + " missing (qa-e2e-gate packet, claim_e2e_complete)")
        return
    if not os.path.isfile(gate):
        fails.append(f"qa-e2e-gate.mjs not found at {gate}")
        return
    try:
        body = rd["read"](rel)
    except Exception as exc:
        fails.append(f"{rel} unreadable: {exc}")
        return
    owned = (cfg or {}).get("automation_identities")
    owned = [o for o in owned if isinstance(o, str)] if isinstance(owned, list) else []
    try:
        auth = json.loads(body).get("authentication") or {}
    except Exception:
        auth = {}
    run_lookups = {}  # one per check_e2e call, which is one per check
    for ident in declared_identities(auth):
        if not isinstance(ident, dict) or not isinstance(ident.get("label"), str):
            continue
        label = ident["label"]
        problem = label_problem(label)
        hit = listed_identity(label, owned)
        if hit and hit[1] == "confusable":
            fails.append(f"{rel}: identity {label!r} looks like '{hit[0]}' in .qa/config.json automation_identities "
                         f"but is spelled differently{' (it ' + problem + ')' if problem else ''}: refused")
        elif problem:
            fails.append(f"{rel}: identity label {label!r} {problem}: refused, name the identity in one script")
        or_problems = owner_run_problems(ident, owned)
        if "walker" in ident and not or_problems:
            or_problems = owner_run_verify(root, ident, walked_sha, run_lookups)
        for problem in or_problems:
            fails.append(f"{rel}: identity {label!r} walker: {problem}: refused")
        if hit and hit[1] == "same" and ident.get("owned_by_automation") is not True:

            fails.append(f"{rel}: identity {label!r} is '{hit[0]}', listed in .qa/config.json automation_identities, "
                         f"but the packet says no automated suite owns it")
    tmppath = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            tf.write(body)
            tmppath = tf.name
        args = ["node", gate, "check", tmppath]
        if owned:
            args += ["--automation-identities", json.dumps(owned)]
        proc = subprocess.run(args, capture_output=True, text=True,

                              timeout=max(0.5, min(20, time_left())))
    except Exception as exc:
        fails.append(f"qa-e2e-gate.mjs could not run: {exc}")
        return
    finally:
        if tmppath:
            try:
                os.unlink(tmppath)
            except Exception:
                pass
    result, detail = None, ""
    try:
        cand = json.loads((proc.stdout or "").strip())
        if isinstance(cand, dict) and "ok" in cand:
            result = cand
    except Exception:
        result = None
    if result is not None and result.get("failures"):
        detail = "; ".join(str(f.get("code", "?")) for f in result["failures"] if isinstance(f, dict))
    if result is None:
        fails.append(f"qa-e2e-gate check produced no verdict (rc={proc.returncode}, stdout empty or unparsed); "
                     f"a silent no-op is a FAIL, not a pass")
    elif proc.returncode != 0 or result.get("ok") is not True:
        fails.append(f"qa-e2e-gate check FAILED{': ' + detail if detail else ''}")


def check_deployed(root, cfg, sha, fails):
    dc = (cfg or {}).get("deployed_check")
    if not dc:
        return
    url = dc.get("url")
    if url:
        import urllib.request
        target = url.replace("{sha}", sha or "")
        try:
            with urllib.request.urlopen(target, timeout=max(0.5, min(3, time_left()))) as resp:
                if resp.status not in (200, 204):
                    fails.append(f"deployed check HTTP {resp.status} for {target}")
        except Exception as exc:
            fails.append(f"deployed check failed for {target}: {exc}")
        return
    cmd = dc.get("command")
    if cmd:
        try:
            proc = subprocess.run([cmd], shell=True, cwd=root, capture_output=True, text=True,
                                  timeout=max(0.5, min(dc.get("timeout_s", 3), time_left())))
            if proc.returncode != 0:
                fails.append(f"deployed check exited {proc.returncode}: {(proc.stdout or proc.stderr).strip()[:200]}")
        except subprocess.TimeoutExpired:
            fails.append("deployed check timed out")
        except Exception as exc:
            fails.append(f"deployed check could not run: {exc}")
    else:
        fails.append(".qa/config.json deployed_check needs a url template or a command")


def check_all(root, sha=None, equiv=False, evidence=None):
    """Return (ok, failures, stats, cfg). Never raises. Artifacts are read
    from the shipped commit's tree when sha is resolvable (v3). equiv (v4):
    the walk may sit on a commit whose tree outside .qa/ equals the shipped
    one -- only for tags, releases, default-branch dispatches and (v5)
    deployments resolved to their source commit. evidence (v5): read the
    records from this commit's tree instead (committed records only, never
    the working tree); freshness is still judged against `sha`."""
    fails, stats = [], {"rows_total": 0, "open_rows": 0, "predates_count": 0, "clusters": 0,
                        "rewalk_steps": 0, "rewalk_failed": 0}
    cfg = None
    try:
        if not sha:
            sha = run_git(root, "rev-parse", "HEAD").stdout.strip() or None
        rd = qa_reader(root, evidence or sha)
        cfg = check_config(root, rd, fails)
        qa, err = resolve_run(root, sha, rd, equiv, evidence)
        if err:
            fails.append(err)
            return (False, fails, stats, cfg)
        wf = check_workflow(qa, rd, cfg, fails)
        rows = check_inventory(qa, rd, fails, stats)
        clusters = check_clusters(qa, rd, rows, fails, stats)
        check_plan(qa, rd, clusters, fails)
        rewalk = check_rewalk(root, qa, rd, wf, sha, fails, stats, equiv)
        check_e2e(qa, rd, cfg, fails, root=root, walked_sha=(rewalk or {}).get("sha") if isinstance(rewalk, dict) else None)

        check_deployed(root, cfg, sha, fails)
    except Exception as exc:  # fail closed on anything unexpected
        fails.append(f"gate internal error: {exc}")
    return (not fails), fails, stats, cfg


def _shell_arg_at(s, i):
    """One shell word starting at/after index i, with POSIX quoting semantics
    for everything statically resolvable: backslash escapes, single quotes,
    double quotes (backslash escapes for quote, backslash, dollar, backtick) and concatenated
    quoted/unquoted segments (Hermes rounds 2-3, topic qa-ship-gate:
    `qa\\ opted\\ repo` and `"/tmp/qa opted "repo` both name the same
    directory as "/tmp/qa opted repo"). Known limit: $VAR and substitutions
    are kept literally, not expanded; such targets stay unresolved
    (documented limitation, fail-closed in every resolvable case)."""
    n = len(s)
    while i < n and s[i] in " \t":
        i += 1
    if i >= n or s[i] in ";&|\n":
        return None, i
    out = []
    while i < n:
        c = s[i]
        if c in " \t;&|\n":  # v4: a newline ends the word (multi-line commands)
            break
        if c == "\\":
            if i + 1 < n:
                if s[i + 1] == "\n":  # line continuation: removed, word continues
                    i += 2
                    continue
                out.append(s[i + 1])
                i += 2
                continue
            break
        if c == "'":
            j = s.find("'", i + 1)
            if j < 0:
                out.append(s[i + 1:])
                i = n
                break
            out.append(s[i + 1:j])
            i = j + 1
            continue
        if c == '"':
            i += 1
            while i < n and s[i] != '"':
                if s[i] == "\\" and i + 1 < n:
                    if s[i + 1] == "\n":  # line continuation inside quotes: removed
                        i += 2
                    elif s[i + 1] in '"\\$`':
                        out.append(s[i + 1])
                        i += 2
                    else:
                        out.append(s[i])
                        i += 1
                else:
                    out.append(s[i])
                    i += 1
            i += 1  # closing quote, or past end
            continue
        out.append(c)
        i += 1
    return ("".join(out) or None), i


def ship_target_roots(command, cwd):
    """Every local repo a ship command can target: the payload cwd's repo plus
    any `git -C path`, `cd path &&`, or --work-tree path inside the command,
    with quoting honoured (paths with spaces included). Hermes review
    2026-09-24, topic qa-ship-gate: two rounds - first only the payload cwd
    was resolved, then whitespace-split regexes truncated quoted paths."""
    roots = []

    def add(p):
        if isinstance(p, str) and p:
            full = p if os.path.isabs(p) else os.path.normpath(os.path.join(cwd, p))
            r = repo_root(full)
            if r and r not in roots:
                roots.append(r)

    add(cwd)
    for pattern in (r"(?<![\w-])-C\s", r"\bcd\s", r"--work-tree[=\s]"):
        pos = 0
        while True:
            m = re.compile(pattern).search(command, pos)
            if not m:
                break
            value, end = _shell_arg_at(command, m.end())
            if value:
                add(value)
                pos = max(end, m.end())
            else:
                pos = m.end()
    return roots


def command_segments(command):
    """Top-level shell segments as token lists, split on ; | && and newlines,
    tokenized with the same POSIX word parser the target resolver uses."""
    segments, cur, i, n = [], [], 0, len(command)
    while i < n:
        c = command[i]
        if c in " \t":
            i += 1
            continue
        if c in ";|&\n":
            j = i
            while j < n and command[j] in ";|&\n":
                j += 1
            if cur:
                segments.append(cur)
                cur = []
            i = j
            continue
        word, endpos = _shell_arg_at(command, i)
        if word is None:
            break
        cur.append(word)
        i = endpos
    if cur:
        segments.append(cur)
    return [s for s in (unwrap_segment(s) for s in segments) if s]


def unwrap_segment(seg):
    """The command a segment actually runs: leading VAR=value assignments,
    plain wrappers (env, command, sudo, npx, bunx, ...) with their flags and
    package runners (`pnpm exec|dlx`, `yarn dlx`, `npm exec`, `bun x`, and
    `pnpm|yarn <ship-bin>`) are dropped, and the head is reduced to its
    basename without an @version (`./node_modules/.bin/vercel`,
    `vercel@latest`). One place, so every consumer (classifier, merge-args,
    sha selection) sees the same words."""
    s = list(seg)
    while s:
        if ASSIGN_RE.match(s[0]):
            s.pop(0)
            continue
        h = os.path.basename(s[0])
        if h in PLAIN_WRAPPERS:
            s.pop(0)
            while s and s[0].startswith("-"):
                f = s.pop(0)
                if f in WRAPPER_VALUE_FLAGS.get(h, ()) and s:
                    s.pop(0)
            continue
        if h in RUNNER_SUBCOMMANDS and len(s) > 1:
            if s[1] in RUNNER_SUBCOMMANDS[h]:
                s = s[2:]
                while s and s[0].startswith("-"):
                    f = s.pop(0)
                    if f in WRAPPER_VALUE_FLAGS.get(h, ()) and s:
                        s.pop(0)
                continue
            if h in ("pnpm", "yarn") and os.path.basename(s[1]).split("@")[0] in SHIP_BINS:
                s = s[1:]
                continue
        break
    if s:
        h = os.path.basename(s[0])
        if not h.startswith("@") and "@" in h:
            h = h.split("@")[0]
        s[0] = h
    return s


def git_subcommand(args):
    """The git subcommand: first non-option word after git, skipping global
    options and their values (-C dir, -c k=v, --git-dir=..., ...). Card 3
    defect (b): a -m message containing the word push must not classify."""
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--":
            return args[i + 1] if i + 1 < len(args) else None
        if a.startswith("-"):
            if a in GIT_VALUE_FLAGS:
                i += 2
                continue
            if a.startswith("-C") and len(a) > 2:  # attached -Cdir
                i += 1
                continue
            i += 1
            continue
        return a
    return None


def push_refspecs(args):
    """(mode, flags, [(src, dst)]) for a git push token list. mode 'all' for
    --all/--mirror/--branches (every branch ships); else the refspec words
    after the remote as (source, destination) pairs (`HEAD:dev`, bare `v1.2`).
    No refspec -> empty list (caller resolves the branch upstream)."""
    try:
        i = args.index("push") + 1
    except ValueError:
        return None, [], []
    flags, words = [], []
    while i < len(args):
        a = args[i]
        if a == "--":
            words += args[i + 1:]
            break
        if a.startswith("-"):
            flags.append(a)
            i += 1
            continue
        words.append(a)
        i += 1
    if any(f in PUSH_ALL_FLAGS or f.split("=")[0] in PUSH_ALL_FLAGS for f in flags):
        return "all", flags, []
    pairs, rest = [], words[1:]  # words[0] is the remote when present
    while rest:
        rs = rest.pop(0)
        if rs == "tag" and rest:  # `git push origin tag v1.2` == refs/tags/v1.2
            t = "refs/tags/" + rest.pop(0)
            pairs.append((t, t))
            continue
        # a leading + only forces the update; `+main` still ships to main
        src, _, dst = rs.lstrip("+").partition(":")
        pairs.append((src or dst, dst or src))
    return None, flags, pairs


def normalize_ref(dst):
    for pre in ("refs/heads/", "refs/"):
        if dst.startswith(pre):
            return dst[len(pre):]
    return dst


def default_branch(root, remote="origin"):
    r = run_git(root, "symbolic-ref", "--short", "refs/remotes/%s/HEAD" % remote).stdout.strip()
    if not r and remote != "origin":
        r = run_git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").stdout.strip()
    if r and "/" in r:
        return r.split("/", 1)[1]
    cfg = run_git(root, "config", "--get", "init.defaultBranch").stdout.strip()
    return cfg or "main"


def upstream_branch(root):
    """Upstream branch from git config. Config, not %(upstream): a configured
    upstream works even before any fetch has created the remote-tracking ref
    (a freshly pushed -u branch, or a config-only setup)."""
    cur = run_git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if not cur or cur == "HEAD":
        return None
    merge = run_git(root, "config", "--get", "branch.%s.merge" % cur).stdout.strip()
    if not merge:
        return None
    return normalize_ref(merge)


def protected_refs(root, cfg):
    prot = {default_branch(root)}
    try:
        extra = cfg.get("protected_branches")
        if isinstance(extra, list):
            prot.update(str(b) for b in extra if b)
    except Exception:
        pass
    return prot


def resolve_commit(root, rev):
    """Full commit sha for a rev, or None. `^{commit}` peels annotated tags,
    so a tag object resolves to the commit it ships."""
    if not rev:
        return None
    p = run_git(root, "rev-parse", "-q", "--verify", "%s^{commit}" % rev)
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def head_commit(root):
    return run_git(root, "rev-parse", "HEAD").stdout.strip()


def current_branch(root):
    b = run_git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return b if b and b != "HEAD" else None


def remote_commit(root, ref):
    """What the remote holds for `ref` as far as this clone knows
    (refs/remotes/origin/<ref>), then the local ref, then a raw sha."""
    return resolve_commit(root, "refs/remotes/origin/%s" % ref) or resolve_commit(root, ref)


def tag_ref(root, src):
    """refs/tags/<name> when a push source names a tag (refs/tags/... or a
    bare word that is a local tag, e.g. `git push origin v1.2`), else None.
    HEAD and explicit refs/heads/ sources are never tags."""
    if src.startswith("refs/tags/"):
        return src
    if src.startswith("refs/") or src in ("HEAD", "@"):
        return None
    return "refs/tags/%s" % src if resolve_commit(root, "refs/tags/%s" % src) else None


def _positionals(toks, value_flags):
    """Positional words of a gh subcommand plus {flag: value} for value flags
    (split `--target main` and attached `--target=main` forms)."""
    pos, vals, i = [], {}, 0
    while i < len(toks):
        t = toks[i]
        if t.startswith("-") and "=" in t:
            k, _, v = t.partition("=")
            vals[k] = v
        elif t in value_flags and i + 1 < len(toks):
            vals[t] = toks[i + 1]
            i += 1
        elif not t.startswith("-"):
            pos.append(t)
        i += 1
    return pos, vals


def release_commit(root, toks):
    """Commit `gh release create` publishes: its tag when the tag exists
    locally; else --target (as the remote knows it); else the remote default
    branch, which is what GitHub tags when neither exists; else HEAD."""
    pos, vals = _positionals(toks, GH_RELEASE_VALUE_FLAGS)
    if pos:
        c = resolve_commit(root, "refs/tags/%s" % pos[0].replace("refs/tags/", "", 1))
        if c:
            return c
    target = vals.get("--target")
    if target:
        return remote_commit(root, target) or head_commit(root)
    return remote_commit(root, default_branch(root)) or head_commit(root)


def release_edit_commit(root, toks):
    """(ships, commit, problem) for `gh release edit <tag>`. It ships when it
    publishes a draft (--draft=false in any pflag spelling) or moves the
    release to another tag (--tag). The commit is the release's tag (--tag
    when given) as this clone has it, else --target as the remote knows it.
    No default-branch fallback: a draft's stored target is not visible
    locally, and guessing it is the "checked the wrong commit" defect."""
    pos, vals = _positionals(toks, GH_RELEASE_VALUE_FLAGS)
    if vals.get("--draft") not in PFLAG_FALSE and "--tag" not in vals:
        return False, None, None
    tag = (vals.get("--tag") or (pos[0] if pos else "")).replace("refs/tags/", "", 1)
    c = resolve_commit(root, "refs/tags/%s" % tag) if tag else None
    if not c and vals.get("--target"):
        c = remote_commit(root, vals["--target"])
    if c:
        return True, c, None
    return True, None, ("gh release edit publishes release %r, but its tag is not in this clone and no "
                        "--target names the commit: `git fetch --tags`, then retry" % (tag or "?"))


def workflow_commit(root, toks):
    """(commit, on_default) for `gh workflow run`: the commit it dispatches
    on (--ref/-r as the remote knows it, else the remote default branch,
    GitHub's default, else HEAD) and whether that ref is the default branch."""
    _, vals = _positionals(toks, GH_WORKFLOW_VALUE_FLAGS)
    ref = (vals.get("--ref") or vals.get("-r") or "").replace("refs/heads/", "", 1)
    default = default_branch(root)
    target = ref or default
    return (remote_commit(root, target) or head_commit(root)), target == default


def _read_body_file(path, cwd):
    """Text of a request-body file named on the command line, or None when it
    is not a readable regular file (stdin `-`, not yet created, too big).
    External input read by a hook: no $VAR expansion, regular files only,
    size-capped."""
    if not path or path == "-" or "$" in path:
        return None
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > BODY_FILE_MAX:
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return None


def api_deploy_post(seg, command, cwd):
    """A deployments-API call that ships PRODUCTION, for `vercel api` and curl:
    a POST (explicit method, or a body flag with no other method) to
    /vN/deployments whose target is production, or a POST to a project's
    /promote/ endpoint (the API form of `vercel promote`).

    Where production is looked for: every argv word (the word parser strips
    shell quotes, so '{"target":"production"}' arrives as
    {"target":"production"} and "{target: production}" as {target:
    production}), every readable body file (--input f, -d @f, -F k=@f), and
    the raw command text (a heredoc or pipe that builds the body). Policy for
    a body that cannot be seen at hook time (written by an earlier command,
    or stdin) with no production marker anywhere in the command: ALLOW. The
    gate matches on evidence of production; a preview heal must never be
    denied for lack of it, and the git-pre-push/CI layers do not depend on
    this classifier."""
    tool = "vercel" if seg[0] == "vercel" else "curl"
    toks = seg[2:] if tool == "vercel" else seg[1:]
    urls = [t for t in toks if DEPLOY_CREATE_RE.search(t) or PROMOTE_API_RE.search(t) or ALIAS_API_RE.search(t)]
    if not urls:
        return False
    body_flags, method_flags = API_BODY_FLAGS[tool], API_METHOD_FLAGS[tool]
    method, has_body, texts, i = None, False, list(toks), 0
    while i < len(toks):
        t = toks[i]
        flag, val = t, None
        if t.startswith("--") and "=" in t:
            flag, _, val = t.partition("=")
        elif len(t) > 2 and t[0] == "-" and t[1] != "-" and t[:2] in method_flags | body_flags:
            flag, val = t[:2], t[2:]  # attached short form: -XPOST, -d@body.json
        if flag in method_flags:
            if val is None and i + 1 < len(toks):
                val = toks[i + 1]
                i += 1
            method = (val or "").upper()
        elif flag in body_flags:
            has_body = True
            if val is None and i + 1 < len(toks):
                val = toks[i + 1]
                i += 1
            val = val or ""
            if flag == "--input":
                path = val
            elif val.startswith("@"):
                path = val[1:]
            elif "=@" in val:  # -F key=@file
                path = val.split("=@", 1)[1]
            else:
                path = None
            body = _read_body_file(path, cwd) if path else None
            if body:
                texts.append(body)
        i += 1
    if not (method == "POST" or (method is None and has_body)):
        return None
    texts.append(command)
    # promote and alias POSTs ship the deployment named in the URL
    ids = [(PROMOTE_ID_RE.search(u) or ALIAS_API_RE.search(u) or [None, ""])[1]
           for u in urls if PROMOTE_API_RE.search(u) or ALIAS_API_RE.search(u)]
    if ids:
        return {"promote": ids, "urls": urls, "texts": texts}
    if any(PROD_TARGET_RE.search(t) for t in texts):
        # a production create naming deploymentId is a redeploy of that one
        redeploys = [m.group(1) for t in texts for m in DEPLOYMENT_ID_BODY_RE.finditer(t)]
        return {"promote": list(dict.fromkeys(redeploys)), "urls": urls, "texts": texts}
    return None


def _redact(text):
    """One line of CLI output, safe to show: long opaque words (tokens,
    hashes) are masked and the line is capped."""
    return re.sub(r"[A-Za-z0-9_\-]{24,}", "<redacted>", " ".join((text or "").split()))[:160]


def vercel_team_query(vals, urls, cwd, root):
    """Scope for the deployment lookup, as a query string: --scope/-S/--team/-T
    on the command, else teamId=/slug= in an API URL, else the orgId of the
    nearest .vercel link (project.json, repo.json) from --cwd/cwd up to the
    repo root. '' = the CLI's current scope (which 404s another team's
    deployment, so a missing scope fails closed rather than open)."""
    for k in ("--scope", "-S", "--team", "-T"):
        v = vals.get(k)
        if v and re.fullmatch(r"[A-Za-z0-9_.-]+", v):
            return ("teamId=" if v.startswith("team_") else "slug=") + v
    for u in urls:
        m = re.search(r"[?&](teamId|slug)=([A-Za-z0-9_.-]+)", u)
        if m:
            return "%s=%s" % (m.group(1), m.group(2))
    start = vals.get("--cwd")
    d = os.path.abspath(os.path.join(cwd, os.path.expanduser(start)) if start else cwd)
    stop = os.path.abspath(root)
    if d != stop and not d.startswith(stop + os.sep):
        d = stop  # `cd <repo> && vercel ...` / `git -C`: the payload cwd is elsewhere
    while True:
        for name in ("project.json", "repo.json"):
            try:
                org = str(load_json(os.path.join(d, ".vercel", name)).get("orgId") or "")
            except Exception:
                org = ""
            if re.fullmatch(r"team_[A-Za-z0-9]+", org):
                return "teamId=" + org
        if d == stop or not d.startswith(stop + os.sep) or os.path.dirname(d) == d:
            return ""
        d = os.path.dirname(d)


def deployment_commit(root, ref, team, cwd):
    """(commit, None) for the local commit a Vercel deployment was built
    from, or (None, reason). One read-only GET /v13/deployments/<id|host>
    through the vercel CLI's own login; the hook never reads, prints or
    forwards a token. Every failure is a reason, and a reason DENIES."""
    global _LOOKUP_DEADLINE
    host = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", ref or "").split("/", 1)[0]
    if not host or not DEPLOYMENT_REF_RE.match(host):
        return None, ("deployment %r: no deployment id or URL to resolve its source commit from"
                      % (ref or ""))
    now = time.monotonic()
    if _LOOKUP_DEADLINE is None:
        _LOOKUP_DEADLINE = now + LOOKUP_BUDGET_S
    left = min(_LOOKUP_DEADLINE - now, time_left() - 0.6)  # leave time to check the commit
    if left < 0.3:
        return None, ("deployment %s: provenance lookup budget (%.1f s per command) is spent; "
                      "ship one deployment per command" % (host, LOOKUP_BUDGET_S))
    path = "/v13/deployments/%s%s" % (host, ("?" + team) if team else "")
    env = dict(os.environ, VERCEL_TELEMETRY_DISABLED="1", NO_COLOR="1")
    try:
        p = subprocess.run(["vercel", "api", path, "--raw", "--non-interactive"],
                           cwd=cwd if os.path.isdir(cwd) else root, capture_output=True, text=True,
                           timeout=left, env=env)
    except FileNotFoundError:
        return None, ("deployment %s: the vercel CLI is not on the hook's PATH, so the commit this "
                      "deployment was built from cannot be resolved" % host)
    except subprocess.TimeoutExpired:
        return None, ("deployment %s: provenance lookup timed out after %.1f s (offline, or the API "
                      "is slow); retry" % (host, left))
    except Exception as exc:
        return None, "deployment %s: provenance lookup could not run: %s" % (host, _redact(str(exc)))
    if p.returncode != 0:
        lines = (p.stderr or p.stdout or "").strip().splitlines()
        return None, ("deployment %s: provenance lookup failed (rc=%d: %s). The hook resolves deployments "
                      "with the vercel CLI's own login (`vercel login`, or VERCEL_TOKEN in the agent's "
                      "environment) and scope (%s); a --token on the command line is not forwarded"
                      % (host, p.returncode, _redact(lines[-1] if lines else ""),
                         team or "the CLI's current scope"))
    try:
        doc = json.loads(p.stdout[p.stdout.index("{"):])
    except Exception:
        return None, "deployment %s: provenance lookup returned no JSON" % host
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    gs = doc.get("gitSource") if isinstance(doc.get("gitSource"), dict) else {}
    if str(meta.get("gitDirty", "")).lower() in ("1", "true"):
        return None, ("deployment %s was built from uncommitted changes (meta.gitDirty): no commit "
                      "describes its code" % host)
    shas = {str(v).lower() for v in [gs.get("sha")] + [meta.get(k) for k in (
        "githubCommitSha", "gitlabCommitSha", "bitbucketCommitSha")] if v}
    if not shas:
        return None, ("deployment %s has no git provenance (no gitSource.sha or meta.*CommitSha): "
                      "deploy it from a commit" % host)
    if len(shas) > 1:
        return None, "deployment %s: conflicting source commits %s" % (
            host, ", ".join(sorted(s[:12] for s in shas)))
    sha = shas.pop()
    c = resolve_commit(root, sha) if re.fullmatch(r"[0-9a-f]{7,40}", sha) else None
    if not c:
        return None, ("deployment %s was built from %s, which is not in this clone: `git fetch`, then "
                      "retry" % (host, sha[:12]))
    return c, None


def deployment_ship(root, refs, team, cwd):
    """Segment result for shipping existing deployments: each one's source
    commit, checked with tree equivalence and with records allowed from HEAD
    (provenance set), or a reason per deployment that could not be resolved."""
    shas, problems = [], []
    for ref in refs or [""]:
        c, why = deployment_commit(root, ref, team, cwd)
        if c and c not in shas:
            shas.append(c)
        elif why:
            problems.append(why)
    return "deploy", shas, set(shas), problems, set(shas)


def api_ship(root, info, cwd):
    """Segment result for a production deployments-API POST (api_deploy_post).
    A promote ships the named deployment's source commit. A create whose body
    names a gitSource ships THAT commit (sha, else the ref as origin knows
    it), not HEAD; a body without one (file upload) keeps the v4 rule: HEAD."""
    if info["promote"]:
        return deployment_ship(root, info["promote"], vercel_team_query({}, info["urls"], cwd, root), cwd)
    shas, problems = [], []
    for t in info["texts"]:
        for m in GIT_SOURCE_RE.finditer(t):
            sm = re.search(r"""["']?sha["']?\s*:\s*["']?([0-9a-fA-F]{7,40})""", m.group(1))
            rm = re.search(r"""["']?ref["']?\s*:\s*["']?([^"',\s}]+)""", m.group(1))
            c = resolve_commit(root, sm.group(1)) if sm else (remote_commit(root, rm.group(1)) if rm else None)
            if c:
                if c not in shas:
                    shas.append(c)
                continue
            why = ("production deployment from gitSource %s: that commit is not in this clone "
                   "(`git fetch`, then retry)" % _redact(" ".join(m.group(1).split()))[:80])
            if why not in problems:
                problems.append(why)
    if shas or problems:
        return "deploy", shas, set(shas), problems, set(shas)
    return "deploy", [head_commit(root)], set(), [], set()


def upload_dirty(root):
    """Problems for an upload deploy (vercel --prod, netlify --prod, fly
    deploy), which ships the WORKING TREE, not HEAD: uncommitted changes
    outside .qa/ (and the .vercel link dir) were never walked."""
    p = run_git(root, "status", "--porcelain", "--untracked-files=normal")
    if p.returncode != 0:
        return ["git status failed, so what this upload deploy ships is unknown"]
    paths = [ln[3:].strip('"') for ln in p.stdout.splitlines() if len(ln) > 3]
    paths = [x for x in paths if not re.match(r"(\.qa|\.vercel)(/|$)", x)]
    if not paths:
        return []
    return ["this deploy uploads the working tree, which has uncommitted changes outside .qa/ (%s%s): "
            "commit them, walk that commit, then deploy" % (", ".join(paths[:5]),
                                                            " ..." if len(paths) > 5 else "")]


def github_api_write(seg, command):
    """Deny reason for a GitHub API write that ships (`gh api`, curl to
    api.github.com), else None. Method: explicit -X/--method/--request, else
    POST when a field or body flag is present, else GET. GET, HEAD and
    DELETE pass: reading and deleting ship no code."""
    gh = seg[0] == "gh"
    toks = seg[2:] if gh else seg[1:]
    if gh:
        pos, vals = _positionals(toks, GH_API_VALUE_FLAGS)
        endpoint = pos[0] if pos else ""
        method = (vals.get("-X") or vals.get("--method") or "").upper()
        has_body = any(k in vals for k in ("-f", "--raw-field", "-F", "--field", "--input"))
    else:
        urls = [t for t in toks if "api.github.com" in t]
        if not urls:
            return None
        endpoint, method, has_body = urls[0], "", False
        for i, t in enumerate(toks):
            if t in ("-X", "--request") and i + 1 < len(toks):
                method = toks[i + 1].upper()
            elif t.startswith("--request="):
                method = t.split("=", 1)[1].upper()
            elif (t.split("=", 1)[0] in API_BODY_FLAGS["curl"]
                  or (len(t) > 2 and t[1] != "-" and t[:2] in API_BODY_FLAGS["curl"])):
                has_body = True
    for t in toks:
        if len(t) > 2 and t.startswith("-X"):
            method = t[2:].upper()  # attached -XPOST (curl and pflag)
    method = method or ("POST" if has_body else "GET")
    if method in ("GET", "HEAD", "DELETE"):
        return None
    path = endpoint.split("api.github.com", 1)[-1]
    if re.search(r"(?:^|/)graphql(?:[?#]|$)", path):
        m = GITHUB_GRAPHQL_WRITE_RE.search(" ".join(toks) + "\n" + command)
        what = "GraphQL %s" % m.group(1) if m else None
    else:
        m = GITHUB_WRITE_RE.search(path)
        what = "%s %s" % (method, _redact(path)[:80]) if m else None
    if not what:
        return None
    return ("GitHub API write (%s) ships code the gate cannot tie to a commit: use the gated CLI form "
            "(gh pr merge, gh release create|edit, git push, gh workflow run) so the shipped commit is "
            "checked" % what)


def _vercel_prod_flag(seg):
    """`--prod`, or `--target production` / `--target=production`."""
    for i, t in enumerate(seg):
        if t == "--prod" or t == "--target=production":
            return True
        if t == "--target" and i + 1 < len(seg) and seg[i + 1] == "production":
            return True
    return False


def segment_ship(seg, root, cfg, command="", cwd=None):
    """(kind, shas, equiv, problems, prov) for one unwrapped shell segment.
    kind: "merge" | "push" | "deploy" | None. shas: the commits this segment
    ships, resolved locally, so a tag pointing at an unwalked commit cannot
    pass on a walked HEAD. equiv: the subset whose walk may sit on a
    tree-identical commit (tree_equiv_outside_qa): tags, releases,
    default-branch dispatches, deployment source commits. problems (v5):
    reasons the shipped commit could not be resolved, each one a DENY.
    prov (v5): deployment source commits, whose records may come from HEAD's
    tree (the run is usually committed after the code it walked). For
    merges the caller resolves the PR head (shas empty here)."""
    r = _segment_ship(seg, root, cfg, command, cwd)
    return r if len(r) == 5 else (r[0], r[1], r[2], [], set())


def _segment_ship(seg, root, cfg, command="", cwd=None):
    if not seg:
        return None, [], set()
    head = seg[0]
    cwd = cwd or root
    if head == "git":
        if git_subcommand(seg) != "push":
            return None, [], set()
        mode, flags, pairs = push_refspecs(seg)
        if mode == "all":
            return "push", [head_commit(root)], set()
        prot = protected_refs(root, cfg)
        kind, shas, equiv, strict = None, [], set(), set()
        if any(f.split("=")[0] in TAG_PUSH_FLAGS for f in flags):
            # --tags/--follow-tags: which tags are new is only known to the
            # remote; the hook checks HEAD, the pre-push layer checks each
            # pushed tag exactly (git lists them on stdin)
            h = head_commit(root)
            kind, shas = "deploy", [h]
            equiv.add(h)
        if not pairs:
            up = upstream_branch(root)
            if up and normalize_ref(up) in prot:
                return "push", shas + [head_commit(root)], set()  # HEAD goes to a protected branch: strict
            return kind, shas, equiv
        for src, dst in pairs:
            dst_branch = current_branch(root) if dst in ("HEAD", "@") else normalize_ref(dst)
            if dst_branch in prot:
                kind = "push"
                c = resolve_commit(root, src) or head_commit(root)
                shas.append(c)
                strict.add(c)
                continue
            t = tag_ref(root, src) or tag_ref(root, dst if dst.startswith("refs/tags/") else "")
            if t:
                kind = kind or "deploy"
                c = resolve_commit(root, t) or head_commit(root)
                shas.append(c)
                equiv.add(c)
        return kind, shas, equiv - strict  # a commit also pushed to a protected branch stays strict
    if head == "gh" and len(seg) > 2:
        if seg[1] == "pr" and seg[2] in ("merge", "ready"):
            return "merge", [], set()
        if seg[1] == "release" and seg[2] == "create":
            c = release_commit(root, seg[3:])
            return "deploy", [c], {c}
        if seg[1] == "api":
            why = github_api_write(seg, command)
            return ("deploy", [], set(), [why], set()) if why else (None, [], set())
        if seg[1] == "release" and seg[2] == "edit":
            ships, c, why = release_edit_commit(root, seg[3:])
            if not ships:
                return None, [], set()
            return "deploy", [c] if c else [], {c} if c else set(), [why] if why else [], set()
        if seg[1] == "workflow" and seg[2] == "run":
            # ANY dispatch is shipping. Deploy workflows run exactly this way
            # (seahaven deploy.yaml is workflow_dispatch dev/staging/prod); a
            # reliable workflow-name -> file -> jobs mapping needs GitHub API
            # round trips inside a hook, and a missed deploy workflow is an
            # ungated production deploy while a false positive only asks for
            # a completed .qa pipeline on a rare manual command.
            c, on_default = workflow_commit(root, seg[3:])
            return "deploy", [c], ({c} if on_default else set())
        return None, [], set()
    if head == "vercel":
        # global flags may precede the subcommand (`vercel --scope t promote x`)
        pos, vals = _positionals(seg[1:], VERCEL_VALUE_FLAGS)
        sub = pos[0] if pos else ""
        if sub == "api":
            info = api_deploy_post(seg, command, cwd)
            return api_ship(root, info, cwd) if info else (None, [], set())
        # v5: promote/redeploy ship an EXISTING deployment, whose code is the
        # commit it was built from -- never the local HEAD. `vercel promote
        # status` only reads. `vercel rollback` stays free: it restores an
        # already-shipped deployment, and gating incident recovery is wrong.
        if sub in ("promote", "redeploy"):
            if sub == "promote" and pos[1:2] == ["status"]:
                return None, [], set()
            return deployment_ship(root, pos[1:2], vercel_team_query(vals, [], cwd, root), cwd)
        # pointing a domain at a deployment ships it (`vercel alias [set] <deployment> <alias>`;
        # the one-argument form picks a deployment the hook cannot see, so it denies);
        # a rolling release starts shipping the deployment given by --dpl
        if sub == "alias":
            rest = pos[1:]
            if rest[:1] == ["set"]:
                rest = rest[1:]
            elif not rest or rest[0] in ("ls", "list", "rm", "remove"):
                return None, [], set()
            return deployment_ship(root, rest[:1] if len(rest) > 1 else [""],
                                   vercel_team_query(vals, [], cwd, root), cwd)
        if sub in ("rolling-release", "rr") and pos[1:2] == ["start"]:
            return deployment_ship(root, [vals.get("--dpl", "")], vercel_team_query(vals, [], cwd, root), cwd)
        if _vercel_prod_flag(seg):
            return "deploy", [head_commit(root)], set(), upload_dirty(root), set()
        return None, [], set()
    if head == "netlify" and "deploy" in seg[1:3] and "--prod" in seg:
        return "deploy", [head_commit(root)], set(), upload_dirty(root), set()
    if head in ("fly", "flyctl") and len(seg) > 1 and seg[1] == "deploy":
        return "deploy", [head_commit(root)], set(), upload_dirty(root), set()
    if head in ("curl", "curl.exe"):
        why = github_api_write(seg, command)
        if why:
            return "deploy", [], set(), [why], set()
        info = api_deploy_post(seg, command, cwd)
        return api_ship(root, info, cwd) if info else (None, [], set())
    return None, [], set()


def segment_ship_kind(seg, root, cfg):
    """"merge" | "push" | "deploy" for one shell segment, else None."""
    return segment_ship(seg, root, cfg)[0]


def ship_plan(command, root, cfg, cwd=None):
    """(kind, shas, equiv, problems, prov): the highest-stakes ship kind
    anywhere in the command, every commit its non-merge segments ship, the
    commits that may be checked with tree equivalence, the reasons a shipped
    commit could not be resolved (each denies), and the deployment source
    commits whose records may come from HEAD. A commit also shipped by a
    strict segment (protected push, prod upload deploy) is checked strictly.
    A `ship_commands` match adds HEAD. Merges get their PR head from the caller."""
    kinds, shas, eq, strict, problems, prov = [], [], set(), set(), [], set()
    for seg in command_segments(command):
        k, s, e, pr, pv = segment_ship(seg, root, cfg, command, cwd)
        if k:
            kinds.append(k)
            shas += [x for x in s if x and x not in shas]
            eq |= {x for x in s if x in e}
            strict |= {x for x in s if x not in e}
            problems += [x for x in pr if x not in problems]
            prov |= set(pv)
    try:
        if cfg and isinstance(cfg.get("ship_commands"), list):
            if any(re.search(str(p), command) for p in cfg["ship_commands"]):
                kinds.append("extra")
                h = head_commit(root)
                if h and h not in shas:
                    shas.append(h)
                strict.add(h)
    except Exception:
        pass
    eq -= strict
    prov -= strict
    if "merge" in kinds:
        return "merge", shas, eq, problems, prov   # needs PR-head freshness, the stricter sha rule
    if "push" in kinds:
        return "push", shas, eq, problems, prov
    return (kinds[0] if kinds else None), shas, eq, problems, prov


def ship_kind(command, root, cfg):
    """Highest-stakes ship kind anywhere in the command, for this root."""
    return ship_plan(command, root, cfg)[0]


def pr_merge_args(command):
    """Token list of the first `gh pr merge`/`gh pr ready` segment, if any."""
    for seg in command_segments(command):
        if len(seg) > 2 and seg[0] == "gh" and seg[1] == "pr" and seg[2] in ("merge", "ready"):
            return seg
    return None


def pr_head_sha(root, args):
    """PR head sha for `gh pr merge [n]`: `gh pr view [n] --json headRefOid`.
    None on any failure (caller falls back to the local HEAD)."""
    if os.environ.get("QA_GATE_NO_GH"):
        return None
    num = next((a for a in (args[3:] if len(args) > 3 else []) if a.isdigit()), None)
    cmd = ["gh", "pr", "view"] + ([num] if num else []) + ["--json", "headRefOid", "-q", ".headRefOid"]
    try:
        p = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=6)
        sha = p.stdout.strip()
        if p.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,40}", sha):
            return sha
    except Exception:
        pass
    return None


def _hard_deadline(signum, frame):
    """SIGALRM at HOOK_HARD_S: decide now, before the host times the hook out."""
    if _HOOK_OPTED is not False and coarse_ship(_LAST_INPUT or ""):
        reason = ("[qa-ship-gate] Ship denied: the gate could not finish within %.1f s of the hook chain "
                  "starting (the host's hook timeout is %.0f s, and a timed-out hook lets the command run); "
                  "retry, or ship one target per command" % (HOOK_HARD_S, HOOK_HOST_TIMEOUT_S))
        sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                            "permissionDecision": "deny",
                                                            "permissionDecisionReason": reason}}) + "\n")
        sys.stdout.flush()
        sys.stderr.write(reason + "\n")
        sys.stderr.flush()
        os._exit(2)
    os._exit(0)


def hook(raw=None):
    """PreToolUse adapter under a hard deadline (see HOOK_HARD_S)."""
    global _HOOK_DEADLINE, _LAST_INPUT
    spent = hook_elapsed()
    if spent >= HOOK_HARD_S:  # the chain spent the budget before this process: decide by shape now
        _LAST_INPUT = raw if raw is not None else (sys.stdin.read() or "{}")
        _hard_deadline(None, None)
    _HOOK_DEADLINE = time.monotonic() + HOOK_BUDGET_S - spent
    import signal
    signal.signal(signal.SIGALRM, _hard_deadline)
    signal.setitimer(signal.ITIMER_REAL, HOOK_HARD_S - spent)

    try:
        return _hook(raw)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def _hook(raw=None):
    """PreToolUse adapter: deny ship commands in opted-in repos with an open pipeline."""
    global _LAST_INPUT, _HOOK_OPTED
    try:
        _LAST_INPUT = raw if raw is not None else (sys.stdin.read() or "{}")
        payload = json.loads(_LAST_INPUT)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    inp = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    if not isinstance(inp, dict):
        inp = {}
    command = inp.get("command") or inp.get("cmd") or ""
    if not isinstance(command, str) or not command:
        return 0
    if payload.get("agent_id") or payload.get("agentId"):
        return 0
    cwd = payload.get("cwd") or payload.get("working_directory") or os.getcwd()
    targets = [r for r in ship_target_roots(command, cwd) if opted_in(r)]
    if not targets:
        _HOOK_OPTED = False
        return 0

    _HOOK_OPTED = True  # from here the hard deadline denies ship-shaped commands
    cfgs = {}
    for root in targets:
        try:
            cfgs[root] = load_json(os.path.join(root, ".qa", "config.json"))
        except Exception:
            cfgs[root] = None  # unparseable config on a ship command: check_all reports it
    plans = {root: ship_plan(command, root, cfgs[root], cwd) for root in targets}
    kinds = {root: plans[root][0] for root in targets}
    if not any(kinds.values()):
        return 0  # feature-branch push, gh pr create, bb fleet validate, preview deploy
    prov = derive_provider(payload)
    merge_args = pr_merge_args(command)
    sections, denied = [], []
    for root in targets:
        kind = kinds[root]
        if not kind:
            continue
        # Walk freshness: a merge needs the walk at the PR head SHA being
        # merged (gh pr view), falling back to the local HEAD; pushes and
        # deploys check the local HEAD (with the .qa-only-parent allowance).
        # v3: with a sha resolved, artifacts are read from that commit's tree.
        # v4: every segment contributes the commits it ships (ship_plan): a
        # tag push or release checks the TAGGED commit, a protected refspec
        # its source, a dispatch its --ref as origin knows it. All of them
        # must pass, so a walked HEAD cannot clear an unwalked tag and a tag
        # cannot hide the branch pushed next to it.
        # v5: a promoted/redeployed deployment checks the commit Vercel built
        # it from (plans[root][4]); its run may be committed in HEAD's tree
        # rather than its own, so HEAD's committed records are tried too,
        # freshness still judged against the deployment's commit. Anything
        # that could not be resolved (plans[root][3]) denies outright.
        shas, problems, prov_shas = list(plans[root][1]), plans[root][3], plans[root][4]
        if kind == "merge" and merge_args is not None:
            shas.insert(0, pr_head_sha(root, merge_args) or head_commit(root))
        if not shas and not problems:
            shas = [head_commit(root)]
        ok, fails, stats = not problems, list(problems), {"rows_total": 0, "clusters": 0, "open_rows": 0}
        many = len(shas) + len(problems) > 1
        for sha in shas:
            if time_left() <= 0:
                ok = False
                fails.append("[%s] gate time budget (%.1f s from the hook chain start, under the host's "
                             "%.0f s hook timeout) was spent before this commit was checked; retry"
                             % ((sha or "HEAD")[:12], HOOK_BUDGET_S, HOOK_HOST_TIMEOUT_S))

                break
            o, f, s, _ = check_all(root, sha or None, equiv=bool(sha) and sha in plans[root][2])
            h = head_commit(root) if sha in prov_shas else ""
            if not o and h and h != sha and time_left() > 0:
                o2, f2, s2, _ = check_all(root, sha, equiv=True, evidence=h)
                if o2:
                    o, f, s = o2, f2, s2
                else:
                    f = (["(records at the deployed commit) " + x for x in f]
                         + ["(records at HEAD %s) %s" % (h[:12], x) for x in f2])
            ok = ok and o
            fails += ["[%s] %s" % ((sha or "HEAD")[:12], x) for x in f] if many else f
            stats = s
        if ok:
            emit("gate_passed", root, data={"rows_total": stats["rows_total"], "clusters": stats["clusters"]},
                 provider=prov)
            continue
        denied.append(root)
        emit("gate_denied", root, data={"reason": (fails[0] if fails else "")[:200], "open_rows": stats["open_rows"],
                                        "kind": kind}, provider=prov)
        sections.append("[%s]\n  - %s" % (os.path.basename(root), "\n  - ".join(fails)))
    if not denied:
        return 0
    reason = "[qa-ship-gate] Ship denied in %s. Complete the .qa pipeline, then ship:\n%s" % (
        ", ".join(os.path.basename(r) for r in denied), "\n".join(sections))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    sys.stderr.write(reason + "\n")
    return 2


def stop():
    """Stop hook: block while a sweep has open inventory rows. Honours stop_hook_active."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("stop_hook_active") or payload.get("stopHookActive"):
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    root = repo_root(cwd)
    if not root or not opted_in(root):
        return 0
    path = os.path.join(default_run(root), "inventory.jsonl")
    if not os.path.isfile(path):
        return 0
    open_rows = []
    try:
        for ln in read_lines(path):
            row = json.loads(ln)
            if row.get("status") == "open":
                open_rows.append(row)
    except Exception:
        return 0
    if not open_rows:
        return 0
    listed = "\n".join("  - %s (%s): %s" % (r.get("id", "?"), r.get("step", "?"), r.get("symptom", "?"))
                       for r in open_rows[:10])
    more = "" if len(open_rows) <= 10 else "\n  ...and %d more" % (len(open_rows) - 10)
    reason = ("[qa-sweep] %d open inventory row(s) remain. Fix and verify each, or FAIL-escalate it with a "
              "reference; then cluster, plan, re-walk, and only then ship:\n%s%s" % (len(open_rows), listed, more))
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.stderr.write(reason + "\n")
    return 0


def cmd_check(args):
    root = repo_root(args.get("repo") or os.getcwd()) or os.path.abspath(args.get("repo") or os.getcwd())
    sha = args.get("sha") if isinstance(args.get("sha"), str) else None
    ok, fails, stats, _ = check_all(root, sha)
    if args.get("json"):
        print(json.dumps({"ok": ok, "failures": fails, "stats": stats}, indent=2))
    else:
        print("%s %s" % ("PASS" if ok else "DENY", root))
        for f in fails:
            print("  -", f)
    if ok:
        emit("gate_passed", root, data={"rows_total": stats["rows_total"], "clusters": stats["clusters"]})
    else:
        emit("gate_denied", root, data={"reason": (fails[0] if fails else "")[:200], "open_rows": stats["open_rows"]})
    return 0 if ok else 1


def cmd_clusters(args):
    root = repo_root(args.get("repo") or os.getcwd()) or os.path.abspath(args.get("repo") or os.getcwd())
    fails, stats = [], {"clusters": 0, "rows_total": 0, "open_rows": 0, "predates_count": 0}
    rd = qa_reader(root, None)
    cfg = check_config(root, rd, fails)
    qa = default_run(root)
    check_workflow(qa, rd, cfg, fails)
    rows = check_inventory(qa, rd, fails, stats)
    clusters = check_clusters(qa, rd, rows, fails, stats)
    check_plan(qa, rd, clusters, fails)
    print("PASS" if not fails else "DENY")
    for f in fails:
        print("  -", f)
    return 0 if not fails else 1


def cmd_record(args):
    kind = args.get("kind")
    root = repo_root(os.getcwd())
    sha = run_git(root, "rev-parse", "HEAD").stdout.strip() if root else ""
    qa = args.get("run") or (default_run(root) if root else os.path.join(os.getcwd(), ".qa"))
    rd = qa_reader(root, None)
    run_rel = os.path.relpath(qa, root) if root else qa
    if kind == "inventory-closed":
        fails, stats = [], {"rows_total": 0, "open_rows": 0, "predates_count": 0}
        check_inventory(qa, rd, fails, stats)
        hard = [f for f in fails if "still OPEN" in f or "missing" in f or "unparseable" in f or "unreadable" in f]
        if hard:
            print("refuse: inventory not closed:\n  - " + "\n  - ".join(hard))
            return 1
        emit("inventory_closed", root, sha, {"rows": stats["rows_total"], "predates_count": stats["predates_count"], "run": run_rel})
        print("recorded inventory_closed rows=%d predates=%d" % (stats["rows_total"], stats["predates_count"]))
        return 0
    if kind == "rewalk":
        fails, stats = [], {"rewalk_steps": 0, "rewalk_failed": 0}
        check_rewalk(root, qa, rd, None, sha, fails, stats)
        if stats["rewalk_steps"] == 0 or any("verdict" in f or "no verdict" in f for f in fails):
            print("refuse: rewalk not green:\n  - " + "\n  - ".join(fails))
            return 1
        emit("rewalk", root, sha, {"steps": stats["rewalk_steps"], "failed": stats["rewalk_failed"], "run": run_rel})
        print("recorded rewalk steps=%d failed=%d" % (stats["rewalk_steps"], stats["rewalk_failed"]))
        return 0
    if kind == "escape":
        if not args.get("source") or not args.get("ref"):
            print("refuse: escape needs --source (user|sentry|reopen) and --ref")
            return 1
        emit("escape", root, sha, {"source": args["source"], "ref": args["ref"]})
        print("recorded escape source=%s ref=%s" % (args["source"], args["ref"]))
        return 0
    print("unknown record kind: %s" % kind)
    return 1


def prepush(remote="origin"):
    """git pre-push layer: reads the ref lines on stdin and denies only pushes
    whose destination is protected (remote default branch + protected_branches)
    or a tag (v4: a tag ships the commit it points at). Feature-branch pushes
    and deletions pass untouched (a PR needs its
    preview built before anyone can walk it). Ported from the meu-psi pilot's
    verified hook; the destination logic is ship-gate's own, so there is one
    parser (v2 template defect: the old template ran the full check on every
    push and re-created the v1 deadlock)."""
    root = repo_root(os.getcwd())
    if not root or not opted_in(root):
        return 0
    try:
        cfg = load_json(os.path.join(root, ".qa", "config.json"))
    except Exception:
        cfg = None
    prot = protected_refs(root, cfg) if cfg else {default_branch(root, remote)}
    prot.add(default_branch(root, remote))
    pushes, failures = [], []
    for ln in sys.stdin.read().splitlines():
        parts = ln.split()
        if len(parts) != 4:
            continue
        lref, lsha, rref, _rsha = parts
        if not any(c != "0" for c in lsha):
            continue  # deletion: passes (branch protection on the server owns deletes)
        if rref.startswith("refs/tags/"):
            # v4: a pushed tag ships the commit it points at. Annotated tags
            # report the tag object sha on stdin; peel it to the commit.
            pushes.append((rref, resolve_commit(root, lsha) or lsha))
            continue
        branch = normalize_ref(rref)
        if branch in prot:
            pushes.append((branch, lsha))
    if not pushes:
        return 0
    denied = False
    for ref, sha in pushes:
        # tags may be checked with tree equivalence; protected branches stay strict
        ok, fails, stats, _ = check_all(root, sha, equiv=ref.startswith("refs/tags/"))
        if ok:
            emit("gate_passed", root, data={"rows_total": stats["rows_total"], "clusters": stats["clusters"],
                                            "kind": "push", "ref": ref}, provider=derive_provider({}))
            continue
        denied = True
        emit("gate_denied", root, data={"reason": (fails[0] if fails else "")[:200], "open_rows": stats["open_rows"],
                                        "kind": "push", "ref": ref}, provider=derive_provider({}))
        failures.append("[%s -> %s]\n  - %s" % (sha[:12], ref, "\n  - ".join(fails)))
    if not denied:
        return 0
    sys.stderr.write("[qa-ship-gate] Push to a protected branch or a tag denied. Complete the .qa pipeline for the "
                     "pushed commit, or push a feature branch:\n" + "\n".join(failures) + "\n")
    return 1


def parse_args(argv):
    args, key = {}, None
    for a in argv:
        if a.startswith("--"):
            key = a[2:]
            args[key] = True
        elif key:
            args[key] = a
            key = None
    return args


def main():
    argv = sys.argv[1:]
    cmd = argv[0] if argv else "check"
    rest = parse_args(argv[1:])
    if cmd == "hook":
        return hook()  # hook() stashes raw input for the crash fail-closed path
    if cmd == "stop":
        return stop()
    if cmd == "check":
        return cmd_check(rest)
    if cmd == "clusters":
        return cmd_clusters(rest)
    if cmd == "record":
        rest["kind"] = argv[1] if len(argv) > 1 else ""
        return cmd_record(rest)
    if cmd == "prepush":
        return prepush(argv[1] if len(argv) > 1 else "origin")
    if cmd == "selftest":
        return selftest(rest.get("gate"), rest.get("templates"))
    print(__doc__)
    return 2


def selftest(v4_gate=None, v4_templates=None):
    """Prove each deny/allow path on scratch repos. A check that cannot go red proves nothing."""
    import shutil
    os.environ.pop("HOOK_T0", None)  # hook calls below start their own clock unless a case sets one
    tmp = tempfile.mkdtemp(prefix="qa-gate-selftest-")
    fails = []
    # isolate the events sink: selftest rows are not real gate activity and
    # must never reach the live file the value panel reads
    global EVENTS
    live_events = EVENTS
    scratch_events = os.path.join(tmp, "events.scratch.jsonl")
    EVENTS = scratch_events
    old_qa_gate_events = os.environ.get("QA_GATE_EVENTS_FILE")
    os.environ["QA_GATE_EVENTS_FILE"] = scratch_events
    # v5: a scratch `vercel` first on PATH for every hook this selftest runs,
    # so no case reaches the real Vercel API. It answers GET
    # /v13/deployments/<ref> from stub-bin/deployments.json (written by the
    # v5 cases) only under teamId=team_fx, like a real scoped lookup.
    stub_bin = os.path.join(tmp, "stub-bin")
    os.makedirs(stub_bin)
    with open(os.path.join(stub_bin, "vercel"), "w") as fh:
        fh.write("#!/usr/bin/env python3\n"
                 "import json, os, sys, time\n"
                 "a = sys.argv[1:]\n"
                 "if a[:1] != ['api'] or len(a) < 2:\n"
                 "    sys.exit(0)\n"
                 "ref, _, q = a[1].split('/v13/deployments/', 1)[-1].partition('?')\n"
                 "try:\n"
                 "    fx = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deployments.json')))\n"
                 "except Exception:\n"
                 "    fx = {}\n"
                 "if ref == 'dpl_slow':\n"
                 "    time.sleep(20)\n"
                 "if ref == 'dpl_offline':\n"
                 "    sys.stderr.write('Error: request to https://api.vercel.com failed, reason: getaddrinfo ENOTFOUND\\n')\n"
                 "    sys.exit(1)\n"
                 "if 'teamId=team_fx' not in q.split('&') or ref not in fx:\n"
                 "    sys.stderr.write('Error: Deployment not found (404)\\n')\n"
                 "    sys.exit(1)\n"
                 "time.sleep(fx[ref].get('_sleep', 0))\n"
                 "print(json.dumps(fx[ref]))\n")
    os.chmod(os.path.join(stub_bin, "vercel"), 0o755)
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = stub_bin + os.pathsep + old_path

    def expect(cond, name):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    def sh(cmd, cwd=None, inp=""):
        return subprocess.run(cmd, shell=True, cwd=cwd, input=inp, capture_output=True, text=True)

    def mkrepo(name, optin=True):
        r = os.path.join(tmp, name)
        os.makedirs(r)
        sh("git init -q -b main && git config user.email t@t && git config user.name t", cwd=r)
        if optin:
            os.makedirs(os.path.join(r, ".qa"))
            with open(os.path.join(r, ".qa", "config.json"), "w") as fh:
                json.dump({"schema_version": 1, "personas": ["admin"], "workflows": [{"name": "w1"}]}, fh)
        return r

    def hookrun(root, command):
        payload = json.dumps({"session_id": "selftest", "tool_name": "Bash",
                              "tool_input": {"command": command}, "cwd": root})
        return sh('python3 "%s" hook' % os.path.abspath(__file__), cwd=root, inp=payload)

    def cfgs_of(root):
        try:
            return load_json(os.path.join(root, ".qa", "config.json"))
        except Exception:
            return None

    def commit_qa(root):
        sh("git add .qa && git commit -qm artifacts -- .qa", cwd=root)
        return sh("git rev-parse HEAD", cwd=root).stdout.strip()

    def stoprun(root, active):
        payload = json.dumps({"cwd": root, "stop_hook_active": active, "session_id": "s"})
        return sh('python3 "%s" stop' % os.path.abspath(__file__), cwd=root, inp=payload)

    GATE = os.path.abspath(__file__)

    r1 = mkrepo("opted")
    sh("git add -A && git commit -qm init", cwd=r1)
    p = hookrun(r1, "git push origin main")
    expect(p.returncode == 2 and "inventory.jsonl missing" in p.stderr, "ship denied when pipeline missing")

    # Hermes repro (2026-09-24, topic qa-ship-gate): the command can target a
    # repo other than the payload cwd's. Run from a foreign non-repo cwd.
    foreign = os.path.join(tmp, "foreign")
    os.makedirs(foreign, exist_ok=True)
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": "git -C %s push origin main" % r1}, "cwd": foreign}))
    expect(p.returncode == 2 and "inventory.jsonl missing" in p.stderr,
           "git -C <opted-repo> push from foreign cwd denied")
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": "cd %s && git push origin main" % r1}, "cwd": foreign}))
    expect(p.returncode == 2 and "inventory.jsonl missing" in p.stderr,
           "cd <opted-repo> && git push from foreign cwd denied")

    # Hermes round 2 (same topic): quoted paths containing spaces
    spaced = os.path.join(tmp, "opted repo")
    os.makedirs(spaced, exist_ok=True)
    sh("git init -q && git config user.email t@t && git config user.name t", cwd=spaced)
    os.makedirs(os.path.join(spaced, ".qa"))
    json.dump({"schema_version": 1, "personas": ["admin"], "workflows": [{"name": "w1"}]},
              open(os.path.join(spaced, ".qa", "config.json"), "w"))
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": 'git -C "%s" push origin main' % spaced}, "cwd": foreign}))
    expect(p.returncode == 2 and "inventory.jsonl missing" in p.stderr,
           'git -C "opted repo" (quoted, space) denied from foreign cwd')
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": 'cd "%s" && git push origin main' % spaced}, "cwd": foreign}))
    expect(p.returncode == 2 and "inventory.jsonl missing" in p.stderr,
           'cd "opted repo" (quoted, space) && push denied from foreign cwd')
    spaced_plain = os.path.join(tmp, "plain repo")
    os.makedirs(spaced_plain, exist_ok=True)
    sh("git init -q && git config user.email t@t && git config user.name t", cwd=spaced_plain)
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": 'git -C "%s" push origin main' % spaced_plain}, "cwd": foreign}))
    expect(p.returncode == 0, 'git -C "plain repo" (quoted, space) allowed')

    # Hermes round 3 (same topic): escaped and concatenated static shell forms
    esc = spaced.replace(" ", "\\ ")
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": "git -C %s push origin main" % esc}, "cwd": foreign}))
    expect(p.returncode == 2 and "inventory.jsonl missing" in p.stderr,
           "git -C with backslash-escaped spaces denied")
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": 'git -C "%s "repo push origin main' % spaced[:-5]}, "cwd": foreign}))
    expect(p.returncode == 2 and "inventory.jsonl missing" in p.stderr,
           "git -C with concatenated quoted segment denied")
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": "cd %s && git push origin main" % esc}, "cwd": foreign}))
    expect(p.returncode == 2 and "inventory.jsonl missing" in p.stderr,
           "cd with backslash-escaped spaces denied")
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": 'git --work-tree="%s" -C "%s" push origin main' % (spaced, spaced)}, "cwd": foreign}))
    expect(p.returncode == 2 and "inventory.jsonl missing" in p.stderr,
           "git --work-tree quoted-space denied")
    esc_plain = spaced_plain.replace(" ", "\\ ")
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": "git -C %s push origin main" % esc_plain}, "cwd": foreign}))
    expect(p.returncode == 0, "escaped-space plain repo allowed")

    # Hermes round 4 (same topic): backslash-newline continuations. Quoted
    # continuation joins into the full spaced path; unquoted continuation
    # joins exactly what /bin/sh joins.
    cont = "\\" + chr(10)  # backslash + newline, inside the tested command string
    qspaced = '"' + spaced.replace("/", "/" + cont, 2) + '"'
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": "git -C %s push origin main" % qspaced}, "cwd": foreign}))
    expect(p.returncode == 2 and "inventory.jsonl missing" in p.stderr,
           "git -C quoted backslash-newline continuation denied")
    ur1 = r1.replace("/opted", "/op" + cont + "ted")
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": "git -C %s push origin main" % ur1}, "cwd": foreign}))
    expect(p.returncode == 2 and "inventory.jsonl missing" in p.stderr,
           "unquoted continuation joins like /bin/sh and denies")
    qplain = '"' + spaced_plain.replace("/", "/" + cont, 2) + '"'
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": "git -C %s push origin main" % qplain}, "cwd": foreign}))
    expect(p.returncode == 0, "quoted-continuation plain repo allowed")
    p = hookrun(r1, "ls -la")
    expect(p.returncode == 0, "non-ship allowed when pipeline missing")

    with open(os.path.join(r1, ".qa", "workflow.json"), "w") as fh:
        fh.write("{not json")
    p = hookrun(r1, "cat .qa/workflow.json")
    expect(p.returncode == 0, "malformed .qa + non-ship allowed")
    p = hookrun(r1, "git push origin main")
    expect(p.returncode == 2, "malformed .qa + ship denied")

    sha1 = sh("git rev-parse HEAD", cwd=r1).stdout.strip()
    qa = os.path.join(r1, ".qa")
    with open(os.path.join(qa, "workflow.json"), "w") as fh:
        json.dump({"workflow": "w1", "persona": "admin", "entry": "/login", "outcome": "sees dashboard",
                   "steps": ["login", "dashboard"], "target": {"url": "http://x.test", "sha": sha1}}, fh)
    with open(os.path.join(qa, "inventory.jsonl"), "w") as fh:
        fh.write(json.dumps({"id": "R1", "step": "login", "symptom": "500 on submit", "evidence": "shot-1",
                             "predates_change": True, "severity": "high", "status": "closed"}) + "\n")
    with open(os.path.join(qa, "clusters.json"), "w") as fh:
        json.dump({"clusters": [{"id": "CL-1", "hypothesis": "missing validation crashes handler",
                                 "repro_command": "make repro-cl1", "repro_failed_once": True}],
                   "mapping": {"R1": "CL-1"}}, fh)
    with open(os.path.join(qa, "plan.md"), "w") as fh:
        fh.write("# Plan\n- CL-1 add validation\n")
    with open(os.path.join(qa, "rewalk.json"), "w") as fh:
        json.dump({"sha": sha1, "steps": [{"step": "login", "verdict": "PASS", "evidence": "shot-2"},
                                          {"step": "dashboard", "verdict": "PASS", "evidence": "shot-3"}]}, fh)
    with open(os.path.join(qa, "evidence.json"), "w") as fh:
        json.dump({"schema_version": 1, "operation": "claim_e2e_complete", "reasoning_effort": "medium",
                   "actor": {"verified": True, "persona": "admin", "surface": "Web", "environment": "test"},
                   "entrypoint": {"verified": True, "route": "opened /", "evidence": "shot"},
                   "authentication": {"required": False, "initial_state": "not_required",
                                      "state": "not_required", "evidence": "shot"},
                   "prerequisites": {"verified": True, "evidence": "shot", "items": []},
                   "journey": {"walked": True, "same_actor": True, "same_surface": True, "evidence": "shot",
                               "steps": [{"page": "Login", "control": "Submit", "surface": "Web",
                                          "observed": True, "evidence": "shot"}]},
                   "terminal": {"status": "passed", "evidence": "shot"}}, fh)
    commit_qa(r1)  # v3: evidence must be committed; head is a .qa-only commit over sha1
    p = hookrun(r1, "git push origin main")
    expect(p.returncode == 0, "ship allowed with complete pipeline at HEAD [%s]" % p.stderr.strip()[:160])

    with open(os.path.join(r1, "note.txt"), "w") as fh:
        fh.write("x")
    sh("git add -A && git commit -qm two", cwd=r1)
    p = hookrun(r1, "git push origin main")
    expect(p.returncode == 2 and "shipped sha" in p.stderr, "ship denied on stale rewalk")

    r2 = mkrepo("plain", optin=False)
    sh("git add -A && git commit -qm init", cwd=r2)
    p = hookrun(r2, "git push origin main")
    expect(p.returncode == 0, "ship allowed in non-opted-in repo")
    p = sh('python3 "%s" hook' % GATE, cwd=foreign, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": "git -C %s push origin main" % r2}, "cwd": foreign}))
    expect(p.returncode == 0, "git -C <plain-repo> push from foreign cwd allowed")

    with open(os.path.join(qa, "inventory.jsonl"), "a") as fh:
        fh.write(json.dumps({"id": "R2", "step": "dashboard", "symptom": "widget empty", "evidence": "shot-4",
                             "predates_change": False, "severity": "med", "status": "open"}) + "\n")
    commit_qa(r1)
    p = hookrun(r1, "git push origin main")
    expect(p.returncode == 2 and "R2 still OPEN" in p.stderr and "not mapped" in p.stderr,
           "open row named in deny")

    p = stoprun(r1, False)
    expect(p.returncode == 0 and '"decision": "block"' in p.stdout and "R2" in p.stdout,
           "stop blocks on open rows")
    p = stoprun(r1, True)
    expect(p.returncode == 0 and "block" not in p.stdout, "stop honours stop_hook_active")
    p = stoprun(r2, False)
    expect(p.returncode == 0 and "block" not in p.stdout, "stop silent in non-opted-in repo")

    p = sh('python3 "%s" record inventory-closed' % GATE, cwd=r1)
    expect(p.returncode == 1, "record inventory-closed refused while rows open")
    lines = [json.loads(l) for l in open(os.path.join(qa, "inventory.jsonl"))]
    lines[1]["status"] = "closed"
    with open(os.path.join(qa, "inventory.jsonl"), "w") as fh:
        fh.write("\n".join(json.dumps(l) for l in lines) + "\n")
    doc = json.load(open(os.path.join(qa, "clusters.json")))
    doc["mapping"]["R2"] = "CL-1"
    json.dump(doc, open(os.path.join(qa, "clusters.json"), "w"))
    commit_qa(r1)
    p = sh('python3 "%s" record inventory-closed' % GATE, cwd=r1)
    expect(p.returncode == 0 and "rows=2" in p.stdout, "record inventory-closed accepted")

    cfgp = os.path.join(qa, "config.json")
    cfg = json.load(open(cfgp))
    cfg["deployed_check"] = {"command": "false"}
    json.dump(cfg, open(cfgp, "w"))
    doc = json.load(open(os.path.join(qa, "rewalk.json")))
    doc["sha"] = sh("git rev-parse HEAD", cwd=r1).stdout.strip()
    json.dump(doc, open(os.path.join(qa, "rewalk.json"), "w"))
    commit_qa(r1)
    p = hookrun(r1, "git push origin main")
    expect(p.returncode == 2 and "deployed check" in p.stderr, "failing deployed check denies ship")
    cfg["deployed_check"] = {"command": "true"}
    json.dump(cfg, open(cfgp, "w"))
    doc["sha"] = sh("git rev-parse HEAD", cwd=r1).stdout.strip()
    json.dump(doc, open(os.path.join(qa, "rewalk.json"), "w"))
    commit_qa(r1)
    sha2 = sh("git rev-parse HEAD", cwd=r1).stdout.strip()
    p = hookrun(r1, "git push origin main")
    expect(p.returncode == 0, "green deployed check allows ship [%s]" % p.stderr.strip()[:160])

    p = sh('python3 "%s" hook' % GATE, cwd=tmp, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": "git -C %s push origin main" % r1}, "cwd": tmp}))
    expect(p.returncode == 0, "git -C push allowed once pipeline complete [%s]" % p.stderr.strip()[:120])
    # v3 security: a NEW code commit makes the committed evidence stale; an
    # uncommitted rewalk claiming the new sha must NOT clear the push
    sh("echo later > later.txt && git add later.txt && git commit -qm later-code", cwd=r1)
    doc = json.load(open(os.path.join(qa, "rewalk.json")))
    doc["sha"] = sh("git rev-parse HEAD", cwd=r1).stdout.strip()
    json.dump(doc, open(os.path.join(qa, "rewalk.json"), "w"))  # written, NOT committed
    p = hookrun(r1, "git push origin main")
    expect(p.returncode == 2 and "shipped sha" in p.stderr,
           "v3: uncommitted rewalk cannot clear a protected push")
    sh("git checkout -q -- .qa", cwd=r1)
    doc = json.load(open(os.path.join(qa, "clusters.json")))
    doc["clusters"].append({"id": "CL-9", "hypothesis": "x", "repro_command": "y", "repro_failed_once": True})
    json.dump(doc, open(os.path.join(qa, "clusters.json"), "w"))
    p = sh('python3 "%s" clusters' % GATE, cwd=r1)
    expect(p.returncode == 1 and "CL-9" in p.stdout, "clusters subcommand flags unplanned cluster")

    # a gate that exits 0 with NO verdict must read as FAIL, never as pass
    noop = os.path.join(tmp, "noop-gate.mjs")
    open(noop, "w").write("process.exit(0)\n")
    cfgp = os.path.join(qa, "config.json")
    cfg = json.load(open(cfgp))
    cfg["e2e_evidence_gate"] = noop
    json.dump(cfg, open(cfgp, "w"))
    commit_qa(r1)
    doc = json.load(open(os.path.join(qa, "rewalk.json")))
    doc["sha"] = sh("git rev-parse HEAD~1", cwd=r1).stdout.strip()
    json.dump(doc, open(os.path.join(qa, "rewalk.json"), "w"))
    p = hookrun(r1, "git push origin main")
    expect(p.returncode == 2 and "no verdict" in p.stderr, "silent no-op e2e gate is a deny")
    del cfg["e2e_evidence_gate"]
    json.dump(cfg, open(cfgp, "w"))
    commit_qa(r1)
    p = hookrun(r1, "git push origin main")
    expect("no verdict" not in p.stderr, "real gate verdict restored after removing the noop override")

    # ---------------- pre-push template: real pushes to a bare remote ----------------
    bare = os.path.join(tmp, "remote.git")
    sh("git init -q --bare -b main %s" % bare)
    r4 = os.path.join(tmp, "pushrepo")
    sh("git init -q -b main && git config user.email t@t && git config user.name t", cwd=None) if False else None
    os.makedirs(r4)
    sh("git init -q -b main && git config user.email t@t && git config user.name t", cwd=r4)
    sh("git remote add origin %s && git remote set-head origin main" % bare, cwd=r4)
    os.makedirs(os.path.join(r4, ".qa", "bin"))
    json.dump({"schema_version": 1, "personas": ["admin"], "workflows": [{"name": "w1"}],
               "protected_branches": ["dev", "main"]},
              open(os.path.join(r4, ".qa", "config.json"), "w"))
    open(os.path.join(r4, "f.txt"), "w").write("x")
    sh("git add -A && git commit -qm init", cwd=r4)
    sh("git push -q origin main", cwd=r4)  # seed remote before the hook is installed
    sh("echo y >> f.txt && git add -A && git commit -qm two", cwd=r4)  # give HEAD:main something to send
    shutil.copy(os.path.normpath(os.path.join(SKILL_DIR, "..", "templates", "pre-push")), os.path.join(r4, ".git", "hooks", "pre-push"))
    os.chmod(os.path.join(r4, ".git", "hooks", "pre-push"), 0o755)
    shutil.copy(os.path.abspath(__file__), os.path.join(r4, ".qa", "bin", "ship-gate.py"))
    sha4 = sh("git rev-parse HEAD", cwd=r4).stdout.strip()
    qa4 = os.path.join(r4, ".qa")
    json.dump({"workflow": "w1", "persona": "admin", "entry": "/", "outcome": "o", "steps": ["s1"],
               "target": {"url": "http://x.test", "sha": sha4}}, open(os.path.join(qa4, "workflow.json"), "w"))
    with open(os.path.join(qa4, "inventory.jsonl"), "w") as fh:  # open inventory
        fh.write(json.dumps({"id": "R1", "step": "s1", "symptom": "open bug", "evidence": "e",
                             "predates_change": False, "severity": "high", "status": "open"}) + "\n")
    sh("git add .qa && git commit -qm open-inv -- .qa", cwd=r4)
    p = sh("git push origin HEAD:refs/heads/feature/qa-walk", cwd=r4)
    ref = sh("git --git-dir=%s rev-parse --verify -q refs/heads/feature/qa-walk" % bare)
    expect(p.returncode == 0 and ref.stdout.strip(),
           "prepush template: feature push with open inventory passes and lands")
    p = sh("git push origin HEAD:dev", cwd=r4)
    ref = sh("git --git-dir=%s rev-parse --verify -q refs/heads/dev" % bare)
    expect(p.returncode != 0 and not ref.stdout.strip() and "R1 still OPEN" in p.stderr,
           "prepush template: push to dev with open inventory denied, nothing landed")
    p = sh("git push origin HEAD:main", cwd=r4)
    expect(p.returncode != 0 and "R1 still OPEN" in p.stderr,
           "prepush template: push to main with open inventory denied")
    # complete the pipeline at HEAD -> dev allowed
    with open(os.path.join(qa4, "inventory.jsonl"), "w") as fh:
        fh.write(json.dumps({"id": "R1", "step": "s1", "symptom": "fixed", "evidence": "e",
                             "predates_change": False, "severity": "high", "status": "closed"}) + "\n")
    json.dump({"clusters": [{"id": "CL-1", "hypothesis": "h", "repro_command": "x", "repro_failed_once": True}],
               "mapping": {"R1": "CL-1"}}, open(os.path.join(qa4, "clusters.json"), "w"))
    open(os.path.join(qa4, "plan.md"), "w").write("# p\n- CL-1\n")
    json.dump({"sha": sha4, "steps": [{"step": "s1", "verdict": "PASS", "evidence": "e"}]},
              open(os.path.join(qa4, "rewalk.json"), "w"))
    ev4 = json.load(open(os.path.join(qa, "evidence.json")))
    json.dump(ev4, open(os.path.join(qa4, "evidence.json"), "w"))
    doc = json.load(open(os.path.join(qa4, "rewalk.json")))
    doc["sha"] = sh("git rev-parse HEAD", cwd=r4).stdout.strip()
    json.dump(doc, open(os.path.join(qa4, "rewalk.json"), "w"))
    sh("git add .qa && git commit -qm walk -- .qa", cwd=r4)
    p = sh("git push origin HEAD:dev", cwd=r4)
    ref = sh("git --git-dir=%s rev-parse --verify -q refs/heads/dev" % bare)
    expect(p.returncode == 0 and ref.stdout.strip(),
           "prepush template: push to dev with fresh walk allowed [%s]" % p.stderr.strip()[:140])
    p = sh("git push origin :refs/heads/feature/qa-walk", cwd=r4)  # deletion passes (pilot parity)
    expect(p.returncode == 0, "prepush template: deletion passes")

    # ---------------- v2: what ships (card 3 pilot) ----------------
    import shutil as _sh
    r3 = os.path.join(tmp, "v2opted")
    os.makedirs(r3)
    sh("git init -q -b main && git config user.email t@t && git config user.name t", cwd=r3)
    os.makedirs(os.path.join(r3, ".qa"))
    json.dump({"schema_version": 1, "personas": ["admin"], "workflows": [{"name": "w1"}],
               "protected_branches": ["dev", "main"]},
              open(os.path.join(r3, ".qa", "config.json"), "w"))
    sha3 = sh("echo x > f && git add -A && git commit -qm init && git rev-parse HEAD", cwd=r3).stdout.strip().splitlines()[-1]
    qa3 = os.path.join(r3, ".qa")
    json.dump({"workflow": "w1", "persona": "admin", "entry": "/", "outcome": "done",
               "steps": ["s1"], "target": {"url": "http://x.test", "sha": sha3}},
              open(os.path.join(qa3, "workflow.json"), "w"))
    with open(os.path.join(qa3, "inventory.jsonl"), "w") as fh:
        fh.write(json.dumps({"id": "R1", "step": "s1", "symptom": "bug", "evidence": "e",
                             "predates_change": False, "severity": "high", "status": "closed"}) + "\n")
        fh.write(json.dumps({"id": "R2", "step": "s1", "symptom": "open bug", "evidence": "e",
                             "predates_change": False, "severity": "low", "status": "open"}) + "\n")
    sh("git add .qa && git commit -qm open-inv -- .qa", cwd=r3)
    json.dump({"clusters": [{"id": "CL-1", "hypothesis": "h", "repro_command": "x", "repro_failed_once": True}],
               "mapping": {"R1": "CL-1"}}, open(os.path.join(qa3, "clusters.json"), "w"))
    open(os.path.join(qa3, "plan.md"), "w").write("# p\n- CL-1\n")
    json.dump({"sha": sha3, "steps": [{"step": "s1", "verdict": "PASS", "evidence": "e"}]},
              open(os.path.join(qa3, "rewalk.json"), "w"))
    ev3 = json.load(open(os.path.join(qa, "evidence.json")))
    json.dump(ev3, open(os.path.join(qa3, "evidence.json"), "w"))

    p = hookrun(r3, "git push origin feature/qa-walk")
    expect(p.returncode == 0, "v2: feature-branch push with open inventory ALLOWED")
    p = hookrun(r3, "git push origin HEAD:dev")
    expect(p.returncode == 2 and "R2 still OPEN" in p.stderr, "v2: git push HEAD:dev DENIED")
    sh("git config branch.main.remote origin && git config branch.main.merge refs/heads/main", cwd=r3)
    p = hookrun(r3, "git push")
    expect(p.returncode == 2 and "R2 still OPEN" in p.stderr, "v2: no-refspec push with upstream main DENIED")
    p = hookrun(r3, 'git commit -m "pre-push hook"')
    expect(p.returncode == 0, "v2: git commit -m pre-push ALLOWED")
    p = hookrun(r3, "bb fleet validate claim --topic t")
    expect(p.returncode == 0, "v2: bb fleet validate ALLOWED")
    p = hookrun(r3, "gh pr create --title x --body-file -")
    expect(p.returncode == 0, "v2: gh pr create ALLOWED")
    p = hookrun(r3, "vercel deploy")
    expect(p.returncode == 0, "v2: vercel deploy (preview) ALLOWED")
    p = hookrun(r3, "vercel deploy --prod")
    expect(p.returncode == 2, "v2: vercel deploy --prod DENIED")
    p = hookrun(r3, "vercel promote my-app.vercel.app")
    expect(p.returncode == 2, "v2: vercel promote DENIED")
    p = hookrun(r3, "git push --mirror origin")
    expect(p.returncode == 2, "v2: git push --mirror DENIED")
    p = hookrun(r3, "git push origin refs/heads/main")
    expect(p.returncode == 2, "v2: git push refs/heads/main DENIED")
    p = hookrun(r3, "git --no-pager push origin main")
    expect(p.returncode == 2, "v2: flag-before-subcommand push DENIED")

    # merges: freshness against the PR head SHA (fake gh on PATH)
    lines = [json.loads(l) for l in open(os.path.join(qa3, "inventory.jsonl"))]
    lines[1]["status"] = "closed"
    with open(os.path.join(qa3, "inventory.jsonl"), "w") as fh:
        fh.write("\n".join(json.dumps(l) for l in lines) + "\n")
    doc = json.load(open(os.path.join(qa3, "clusters.json")))
    doc["mapping"]["R2"] = "CL-1"
    json.dump(doc, open(os.path.join(qa3, "clusters.json"), "w"))
    binp = os.path.join(tmp, "bin")
    os.makedirs(binp, exist_ok=True)
    prhead = "f" * 40
    fake = os.path.join(binp, "gh")
    open(fake, "w").write("#!/bin/sh\ncase \"$*\" in *--json*) echo %s;; *) exit 1;; esac\n" % prhead)
    os.chmod(fake, 0o755)
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = binp + os.pathsep + old_path
    doc = json.load(open(os.path.join(qa3, "rewalk.json")))
    doc["sha"] = sha3  # local HEAD, not the PR head: stale for the merge
    json.dump(doc, open(os.path.join(qa3, "rewalk.json"), "w"))
    p = hookrun(r3, "gh pr merge 22 --admin")
    expect(p.returncode == 2 and "shipped sha" in p.stderr, "v2: gh pr merge --admin with stale walk DENIED")
    doc["sha"] = prhead
    json.dump(doc, open(os.path.join(qa3, "rewalk.json"), "w"))
    commit_qa(r3)
    p = hookrun(r3, "gh pr merge 22 --admin")
    expect(p.returncode == 0, "v2: gh pr merge with fresh walk at PR head ALLOWED [%s]" % p.stderr.strip()[:140])
    os.environ["PATH"] = old_path

    # non-opted-in repo: everything allowed, ships included
    p = hookrun(r2, "git push origin main")
    expect(p.returncode == 0, "v2: non-opted push origin main ALLOWED")
    p = hookrun(r2, "gh pr merge 22 --admin")
    expect(p.returncode == 0, "v2: non-opted gh pr merge ALLOWED")

    # no dead classification branch: every class matches a canonical command
    segs = lambda c: command_segments(c)
    ok_classes = (
        segment_ship_kind(segs("git push origin main")[0], r3, cfgs_of(r3)) == "push"
        and segment_ship_kind(segs("gh pr merge 22")[0], r3, cfgs_of(r3)) == "merge"
        and segment_ship_kind(segs("gh pr ready 22")[0], r3, cfgs_of(r3)) == "merge"
        and segment_ship_kind(segs("vercel deploy --prod")[0], r3, cfgs_of(r3)) == "deploy"
        and segment_ship_kind(segs("netlify deploy --prod")[0], r3, cfgs_of(r3)) == "deploy"
        and segment_ship_kind(segs("fly deploy")[0], r3, cfgs_of(r3)) == "deploy"
        and segment_ship_kind(segs("bb fleet validate x")[0], r3, cfgs_of(r3)) is None
        and segment_ship_kind(segs('git commit -m "pre-push hook"')[0], r3, cfgs_of(r3)) is None
    )
    expect(ok_classes, "v2: every classification class matches a canonical sample (no dead patterns)")

    # ---------------- v3: per-run namespacing (change request) ----------------
    # Contract: evidence ships as .qa-only artifacts commits over the walked
    # code (the parent rule), so A/B below are artifacts commits:
    #   base -> codeA -> A(runs/a@codeA) -> codeB -> B(runs/a+b@codeB) -> codeC
    def write_run(repo, run, sha, status="closed"):
        d = os.path.join(repo, ".qa", "runs", run)
        os.makedirs(d, exist_ok=True)
        json.dump({"workflow": "w1", "persona": "admin", "entry": "/", "outcome": "o",
                   "steps": ["s1"], "target": {"url": "http://x.test", "sha": sha}},
                  open(os.path.join(d, "workflow.json"), "w"))
        with open(os.path.join(d, "inventory.jsonl"), "w") as fh:
            fh.write(json.dumps({"id": "R1", "step": "s1", "symptom": "b", "evidence": "e",
                                 "predates_change": False, "severity": "high", "status": status}) + "\n")
        json.dump({"clusters": [{"id": "CL-1", "hypothesis": "h", "repro_command": "x",
                                 "repro_failed_once": True}], "mapping": {"R1": "CL-1"}},
                  open(os.path.join(d, "clusters.json"), "w"))
        open(os.path.join(d, "plan.md"), "w").write("# p\n- CL-1\n")
        json.dump({"sha": sha, "steps": [{"step": "s1", "verdict": "PASS", "evidence": "e"}]},
                  open(os.path.join(d, "rewalk.json"), "w"))
        ev = json.load(open(os.path.join(qa, "evidence.json")))
        json.dump(ev, open(os.path.join(d, "evidence.json"), "w"))

    def check_sha(repo, sha):
        return sh('python3 "%s" check --repo %s --sha %s' % (GATE, repo, sha), cwd=repo)

    r5 = os.path.join(tmp, "runsrepo")
    os.makedirs(r5)
    sh("git init -q -b main && git config user.email t@t && git config user.name t", cwd=r5)
    os.makedirs(os.path.join(r5, ".qa"))
    json.dump({"schema_version": 1, "personas": ["admin"], "workflows": [{"name": "w1"}],
               "protected_branches": ["dev", "main"]}, open(os.path.join(r5, ".qa", "config.json"), "w"))
    open(os.path.join(r5, "f.txt"), "w").write("x")
    sh("git add -A && git commit -qm base", cwd=r5)  # opt-in committed with the base
    sh("echo a >> f.txt && git add -A && git commit -qm codeA", cwd=r5)
    codeA = sh("git rev-parse HEAD", cwd=r5).stdout.strip()
    write_run(r5, "a", codeA)
    sh("git add .qa && git commit -qm A", cwd=r5)
    shaA = sh("git rev-parse HEAD", cwd=r5).stdout.strip()
    sh("echo b >> f.txt && git add -A && git commit -qm codeB", cwd=r5)
    codeB = sh("git rev-parse HEAD", cwd=r5).stdout.strip()
    write_run(r5, "b", codeB)
    sh("git add .qa && git commit -qm B", cwd=r5)
    shaB = sh("git rev-parse HEAD", cwd=r5).stdout.strip()
    sh("echo c >> f.txt && git add -A && git commit -qm codeC", cwd=r5)
    shaC = sh("git rev-parse HEAD", cwd=r5).stdout.strip()

    p = check_sha(r5, shaA)
    expect(p.returncode == 0, "v3 case1: check at A reads runs/a [%s]" % " ".join(p.stdout.split())[:130])
    p = check_sha(r5, shaB)
    expect(p.returncode == 0, "v3 case1: check at B reads runs/b [%s]" % " ".join(p.stdout.split())[:130])
    p = check_sha(r5, shaC)
    expect(p.returncode == 1 and "no QA run has a re-walk at" in p.stdout and ".qa/runs/a@" in p.stdout
           and ".qa/runs/b@" in p.stdout, "v3 case3: no run at C names both runs")

    # case2: .qa-only head on top of A that adds another run walked at A
    sh("git checkout -q -b qa-only %s" % shaA, cwd=r5)
    write_run(r5, "a2", shaA)
    sh("git add .qa && git commit -qm add-run", cwd=r5)
    headA2 = sh("git rev-parse HEAD", cwd=r5).stdout.strip()
    p = check_sha(r5, headA2)
    expect(p.returncode == 0, "v3 case2: .qa-only head adding a run passes at the head [%s]" % " ".join(p.stdout.split())[:120])
    sh("git checkout -q main", cwd=r5)

    # case4: a head whose tree carries two runs both walked at its parent -> ambiguous
    sh("git checkout -q -b ambtest %s" % shaB, cwd=r5)
    doc = json.load(open(os.path.join(r5, ".qa", "runs", "b", "rewalk.json")))
    doc["sha"] = shaB
    json.dump(doc, open(os.path.join(r5, ".qa", "runs", "b", "rewalk.json"), "w"))
    write_run(r5, "amb", shaB)
    sh("git add .qa && git commit -qm amb", cwd=r5)
    headAmb = sh("git rev-parse HEAD", cwd=r5).stdout.strip()
    p = check_sha(r5, headAmb)
    expect(p.returncode == 1 and "ambiguous QA runs" in p.stdout,
           "v3 case4: two runs at the same sha are an ambiguous deny")
    sh("git checkout -q main", cwd=r5)

    # case6: legacy .qa/rewalk.json at an older sha coexists during migration
    json.dump({"sha": "0" * 40, "steps": []}, open(os.path.join(r5, ".qa", "rewalk.json"), "w"))
    sh("git add .qa && git commit -qm legacy", cwd=r5)
    p = check_sha(r5, shaB)
    expect(p.returncode == 0, "v3 case6: legacy rewalk coexists; run at B still selected [%s]" % " ".join(p.stdout.split())[:110])
    sh("git rm -q .qa/rewalk.json && git commit -qm rm-legacy", cwd=r5)

    # case7: branches p1/p2 each carry their own run; merged tree passes both
    sh("git checkout -q -b p2 main", cwd=r5)
    sh("echo p2 >> f.txt && git add -A && git commit -qm p2-code", cwd=r5)
    codeP2 = sh("git rev-parse HEAD", cwd=r5).stdout.strip()
    write_run(r5, "p2", codeP2)
    sh("git add .qa && git commit -qm p2-run", cwd=r5)
    shaP2 = sh("git rev-parse HEAD", cwd=r5).stdout.strip()
    sh("git checkout -q -b p1 main", cwd=r5)
    sh("echo p1 >> f.txt && git add -A && git commit -qm p1-code", cwd=r5)
    codeP1 = sh("git rev-parse HEAD", cwd=r5).stdout.strip()
    write_run(r5, "p1", codeP1)
    sh("git add .qa && git commit -qm p1-run", cwd=r5)
    shaP1 = sh("git rev-parse HEAD", cwd=r5).stdout.strip()
    sh("git checkout -q main", cwd=r5)
    sh("git merge -q --no-edit p1 >/dev/null 2>&1 && git merge -q --no-edit p2 >/dev/null 2>&1", cwd=r5)
    p1_ok = check_sha(r5, shaP1).returncode == 0
    p = check_sha(r5, shaP2)
    expect(p1_ok and p.returncode == 0,
           "v3 case7: both branches' runs live on the merged tree [%s]" % " ".join(p.stdout.split())[:110])

    # case8: prepush to a protected ref; bin + template installed
    bare5 = os.path.join(tmp, "remote5.git")
    sh("git init -q --bare -b main %s" % bare5)
    sh("git remote add r5 %s" % bare5, cwd=r5)
    sh("git push -q r5 main", cwd=r5)
    os.makedirs(os.path.join(r5, ".qa", "bin"), exist_ok=True)
    shutil.copy(GATE, os.path.join(r5, ".qa", "bin", "ship-gate.py"))
    shutil.copy(os.path.normpath(os.path.join(SKILL_DIR, "..", "templates", "pre-push")),
                os.path.join(r5, ".git", "hooks", "pre-push"))
    os.chmod(os.path.join(r5, ".git", "hooks", "pre-push"), 0o755)
    sh("git add .qa && git commit -qm bin", cwd=r5)
    sh("git push -q r5 main", cwd=r5)
    sh("git branch -f dev %s" % shaA, cwd=r5)
    p = sh("git push r5 dev", cwd=r5)
    expect(p.returncode == 0, "v3 case8: prepush to protected at A allowed (a@codeA, b@codeB) [%s]" % p.stderr.strip()[:120])
    sh("git push -q r5 --delete dev", cwd=r5)
    sh("git branch -f dev %s" % shaC, cwd=r5)
    p = sh("git push r5 dev", cwd=r5)
    expect(p.returncode != 0 and "no QA run has a re-walk at" in p.stderr,
           "v3 case8: prepush at C denied with the no-run message")
    sh("git branch -q -D dev", cwd=r5)

    # case9: default run selection on a branch (own repo: deterministic)
    r7 = os.path.join(tmp, "featrepo")
    os.makedirs(r7)
    sh("git init -q -b main && git config user.email t@t && git config user.name t && echo x > f && "
       "mkdir -p .qa/runs/feat-x && git add -A && git commit -qm base && git checkout -q -b feat/x", cwd=r7)
    d7 = os.path.join(r7, ".qa", "runs", "feat-x")
    open(os.path.join(d7, "inventory.jsonl"), "w").write(json.dumps(
        {"id": "R1", "step": "s", "symptom": "b", "evidence": "e", "predates_change": False,
         "severity": "h", "status": "closed"}) + "\n")
    p = sh('python3 "%s" record inventory-closed' % GATE, cwd=r7)
    expect(p.returncode == 0 and "rows=1" in p.stdout, "v3 case9: record on feat/x reads runs/feat-x [%s]" % p.stdout.strip()[:80])
    found_run = ""
    if os.path.exists(scratch_events):
        for ln in open(scratch_events).read().splitlines()[::-1]:
            d = json.loads(ln)
            if d.get("event") == "inventory_closed" and d.get("repo") == "featrepo":
                found_run = d.get("data", {}).get("run", "")
                break
    expect(found_run == ".qa/runs/feat-x", "v3 case9: event carries run=.qa/runs/feat-x (got %r)" % found_run)
    p = sh('python3 "%s" record inventory-closed --run .qa/runs/feat-x' % GATE, cwd=r7)
    expect(p.returncode == 0 and "rows=1" in p.stdout, "v3 case9: --run overrides")

    # case10: guarded template (no config -> pass; config without bin -> named deny)
    r6 = os.path.join(tmp, "guardrepo")
    os.makedirs(r6)
    sh("git init -q -b main && git config user.email t@t && git config user.name t && echo x > f && "
       "git add -A && git commit -qm i", cwd=r6)
    bare6 = os.path.join(tmp, "remote6.git")
    sh("git init -q --bare -b main %s" % bare6)
    sh("git remote add r6 %s && git push -q r6 main" % bare6, cwd=r6)
    shutil.copy(os.path.normpath(os.path.join(SKILL_DIR, "..", "templates", "pre-push")),
                os.path.join(r6, ".git", "hooks", "pre-push"))
    os.chmod(os.path.join(r6, ".git", "hooks", "pre-push"), 0o755)
    sh("echo y >> f && git add -A && git commit -qm two", cwd=r6)
    p = sh("git push r6 HEAD:dev", cwd=r6)
    expect(p.returncode == 0, "v3 case10: hook with NO .qa/config.json passes a dev push")
    os.makedirs(os.path.join(r6, ".qa"), exist_ok=True)
    json.dump({"personas": ["a"], "workflows": [{"name": "w"}], "protected_branches": ["dev", "main"]},
              open(os.path.join(r6, ".qa", "config.json"), "w"))
    p = sh("git push r6 HEAD:dev", cwd=r6)
    expect(p.returncode != 0 and ".qa/bin/ship-gate.py is missing" in p.stderr,
           "v3 case10: config present, bin missing -> named deny")
    os.makedirs(os.path.join(r6, ".qa", "bin"), exist_ok=True)
    shutil.copy(GATE, os.path.join(r6, ".qa", "bin", "ship-gate.py"))
    sh("echo z >> f && git add -A && git commit -qm three", cwd=r6)
    p = sh("git push r6 HEAD:dev", cwd=r6)
    expect(p.returncode != 0 and ("no QA run" in p.stderr or "missing" in p.stderr),
           "v3 case10: hook+config+bin with no pipeline denies")

    # ---------------- v4 (card 6): what else ships ----------------
    # Self-contained and subprocess-only, so the same cases run against any
    # gate/template pair: `selftest --gate <ship-gate.py> --templates <dir>`
    # replays them against an older release (the before-run of card 6).
    V4GATE = os.path.abspath(v4_gate or GATE)
    V4TMPL = os.path.abspath(v4_templates or os.path.join(SKILL_DIR, "..", "templates"))
    print("-- v4 cases against gate %s, templates %s" % (V4GATE, V4TMPL))

    def hook4(root, command):
        payload = json.dumps({"session_id": "selftest", "tool_name": "Bash",
                              "tool_input": {"command": command}, "cwd": root})
        return subprocess.run(["python3", V4GATE, "hook"], cwd=root, input=payload, capture_output=True,
                              text=True, env=dict(os.environ, QA_GATE_NO_GH="1"))

    def deny4(root, command, name):
        p = hook4(root, command)
        expect(p.returncode == 2 and "qa-ship-gate" in p.stderr, "v4 DENY  %s" % name)
        return p

    def allow4(root, command, name):
        p = hook4(root, command)
        expect(p.returncode == 0, "v4 ALLOW %s [%s]" % (name, " ".join(p.stderr.split())[:100]))
        return p

    # r9: base(opt-in) -> codeW -> W (.qa-only run at codeW) = main, vgood
    #                            -> codeU (unwalked) = feat = HEAD, vbad
    r9 = os.path.join(tmp, "v4repo")
    os.makedirs(r9)
    sh("git init -q -b main && git config user.email t@t && git config user.name t", cwd=r9)
    os.makedirs(os.path.join(r9, ".qa"))
    json.dump({"schema_version": 1, "personas": ["admin"], "workflows": [{"name": "w1"}],
               "protected_branches": ["dev", "main"]}, open(os.path.join(r9, ".qa", "config.json"), "w"))
    open(os.path.join(r9, "f.txt"), "w").write("x\n")
    sh("git add -A && git commit -qm base && echo w >> f.txt && git commit -qam codeW", cwd=r9)
    codeW = sh("git rev-parse HEAD", cwd=r9).stdout.strip()
    write_run(r9, "w", codeW)
    sh("git add .qa && git commit -qm evidence-w -- .qa && git tag vgood", cwd=r9)
    shaW = sh("git rev-parse HEAD", cwd=r9).stdout.strip()
    sh("git checkout -q -b feat && echo u >> f.txt && git commit -qam codeU && git tag vbad", cwd=r9)
    codeU = sh("git rev-parse HEAD", cwd=r9).stdout.strip()
    open(os.path.join(r9, "prod-body.json"), "w").write(json.dumps(
        {"name": "app", "target": "production", "gitSource": {"type": "github", "sha": codeU}}))
    open(os.path.join(r9, "preview-body.json"), "w").write(json.dumps(
        {"name": "app", "target": "preview", "gitSource": {"type": "github", "sha": codeU}}))
    p = sh('python3 "%s" check --repo %s --sha %s' % (GATE, r9, shaW), cwd=r9)
    expect(p.returncode == 0, "v4 fixture: the walked commit W passes check [%s]" % " ".join(p.stdout.split())[:100])

    # tags ship the tagged commit
    deny4(r9, "git push origin vbad", "tag push at an unwalked commit")
    deny4(r9, "git push origin refs/tags/vbad", "refs/tags/... refspec push")
    deny4(r9, "git push origin tag vbad", "`git push origin tag <name>`")
    deny4(r9, "git push --tags", "git push --tags (hook checks HEAD; pre-push checks each tag)")
    deny4(r9, "git push --follow-tags origin feat", "git push --follow-tags")
    allow4(r9, "git push origin vgood", "tag push at a walked commit (tagged commit checked, not HEAD)")
    deny4(r9, "git push origin vgood HEAD:dev", "walked tag next to an unwalked protected push")
    # releases and dispatches check the commit they publish
    deny4(r9, "gh release create vbad", "gh release create of an unwalked tag")
    deny4(r9, "gh release create -t 'Release title' --notes n vbad", "gh release create with value flags first")
    deny4(r9, "gh release create v9 --target feat", "gh release create --target <unwalked branch>")
    allow4(r9, "gh release create vgood", "gh release create of a walked tag")
    deny4(r9, "gh workflow run deploy.yaml --ref feat", "gh workflow run on an unwalked ref")
    allow4(r9, "gh workflow run deploy.yaml", "gh workflow run on the default branch at a walked commit")
    allow4(r9, "gh run watch 1", "gh run watch (not a dispatch)")
    # vercel CLI
    deny4(r9, "vercel redeploy dpl_abc", "vercel redeploy")
    deny4(r9, "vercel promote app-x.vercel.app", "vercel promote (covered since v2)")
    deny4(r9, "vercel deploy --target production", "vercel deploy --target production")
    deny4(r9, "npx vercel@latest --prod", "npx vercel@latest --prod")
    deny4(r9, "VERCEL_ORG_ID=team_x vercel --prod", "env-prefixed vercel --prod")
    allow4(r9, "vercel deploy", "vercel deploy (preview)")
    allow4(r9, "vercel rollback", "vercel rollback (incident recovery stays free)")
    # deployments API: production gated, previews free (meu-psi heal shape)
    allow4(r9, 'vercel api "/v13/deployments?teamId=team_x" -X POST --input preview-body.json --raw',
           "vercel api POST building a PREVIEW (meu-psi heal, body file)")
    deny4(r9, 'vercel api "/v13/deployments?teamId=team_x" -X POST --input prod-body.json --raw',
          "vercel api POST, PRODUCTION body file (pallium autoheal shape)")
    deny4(r9, "vercel api /v13/deployments -F target=production -F name=app",
          "vercel api fields imply POST, target=production")
    allow4(r9, "vercel api '/v6/deployments?target=production' -d", "vercel api GET list (-d is --debug)")
    deny4(r9, "curl -X POST https://api.vercel.com/v13/deployments -H 'Authorization: Bearer t' "
              "-d '{\"name\":\"app\",\"target\":\"production\"}'", "curl POST inline production body")
    deny4(r9, "curl -sS -XPOST https://api.vercel.com/v13/deployments -d @prod-body.json",
          "curl POST production body file")
    allow4(r9, "curl -X POST https://api.vercel.com/v13/deployments -d '{\"target\": \"preview\"}'",
           "curl POST preview body")
    allow4(r9, "curl 'https://api.vercel.com/v13/deployments?target=production&limit=1'",
           "curl GET list with a production filter")
    deny4(r9, "cat > body-later.json <<'EOF'\n{\"target\": \"production\"}\nEOF\n"
              "vercel api /v13/deployments -X POST --input body-later.json",
          "heredoc-built production body (file absent at hook time)")
    deny4(r9, "curl -X POST https://api.vercel.com/v10/projects/prj_1/promote/dpl_1", "promote API POST")
    # pushes: sources, wrappers, multi-line
    allow4(r9, "git push origin feat", "feature-branch push")
    allow4(r9, "git push origin main", "protected push of local main (walked) while HEAD is not")
    deny4(r9, "git push origin feat:main", "feat:main ships the unwalked source")
    deny4(r9, "git push origin +feat:dev", "forced refspec +feat:dev")
    deny4(r9, "git status\ngit push origin HEAD:dev", "ship on the second line of a multi-line command")
    deny4(r9, "GH_TOKEN=x gh pr merge 5", "env-prefixed gh pr merge")
    sh("git checkout -q -b dev", cwd=r9)
    deny4(r9, "git push origin HEAD", "git push origin HEAD while on a protected branch")
    deny4(r9, "git push origin +dev", "forced +dev")
    sh("git checkout -q feat && git branch -q -D dev", cwd=r9)

    # tree equivalence (coordinator decision): commits built from tree hashes
    # with no parent link to the walk, as a squash merge on main would be.
    #   S  = W's exact tree (identical-tree squash)          -> vsquash
    #   S2 = W's tree plus .qa/notes.md (differs under .qa)  -> vqaonly
    #   M  = W's tree plus f2.txt, parents base+W (a merge bringing in other code) -> vmerge
    base9 = sh("git rev-list --max-parents=0 HEAD", cwd=r9).stdout.strip()

    def tree_with(extra_path, content):
        idx = os.path.join(tmp, "v4-index")
        env = "GIT_INDEX_FILE=%s" % idx
        blob = sh("printf '%s' | git hash-object -w --stdin" % content, cwd=r9).stdout.strip()
        sh("%s git read-tree %s && %s git update-index --add --cacheinfo 100644,%s,%s"
           % (env, shaW, env, blob, extra_path), cwd=r9)
        tree = sh("%s git write-tree" % env, cwd=r9).stdout.strip()
        os.remove(idx)
        return tree

    shaS = sh("git commit-tree %s^{tree} -p %s -m squash" % (shaW, base9), cwd=r9).stdout.strip()
    shaS2 = sh("git commit-tree %s -p %s -m squash-qa" % (tree_with(".qa/notes.md", "n"), base9),
               cwd=r9).stdout.strip()
    shaM = sh("git commit-tree %s -p %s -p %s -m merge" % (tree_with("f2.txt", "other"), base9, shaW),
              cwd=r9).stdout.strip()
    sh("git tag vsquash %s && git tag vqaonly %s && git tag vmerge %s && git branch sq %s"
       % (shaS, shaS2, shaM, shaS), cwd=r9)
    allow4(r9, "git push origin vsquash", "tree-equiv: tag on an identical-tree squash commit")
    allow4(r9, "git push origin vqaonly", "tree-equiv: tag on a commit differing from the walk only under .qa/")
    deny4(r9, "git push origin vmerge", "tree-equiv: tag on a merge commit that brings in other changes")
    allow4(r9, "gh release create vsquash", "tree-equiv: release of the identical-tree squash commit")
    deny4(r9, "gh release create vmerge", "tree-equiv: release of the merge commit with other changes")
    deny4(r9, "git push origin vsquash:dev", "tree-equiv is NOT applied to protected pushes")
    deny4(r9, "git push origin vsquash sq:dev", "same commit as tag and protected push: strict wins")
    deny4(r9, "gh workflow run deploy.yaml --ref sq", "tree-equiv is NOT applied to a non-default dispatch")
    sh("git branch -f main %s" % shaS, cwd=r9)
    allow4(r9, "gh workflow run deploy.yaml", "tree-equiv: default-branch dispatch on the squash commit")
    sh("git branch -f main %s" % shaM, cwd=r9)
    deny4(r9, "gh workflow run deploy.yaml", "tree-equiv: default-branch dispatch on the merge commit")
    sh("git branch -f main %s && git branch -q -D sq" % shaW, cwd=r9)
    sh("git checkout -q -b rel %s && git config branch.rel.remote origin && "
       "git config branch.rel.merge refs/heads/main" % shaS, cwd=r9)
    deny4(r9, "git push --follow-tags", "tags pushed along a protected upstream push: strict")
    sh("git checkout -q feat && git branch -q -D rel", cwd=r9)

    # ---------------- v5 (card 11): deployment provenance ----------------
    # Deny cases run with HEAD on main = W (walked), where the v4 gate
    # checked only HEAD and so allowed them; allow cases run with HEAD on the
    # unwalked feat, where v4 denied them. Every one of them flips between
    # 77b8d56 and v5, except the controls marked "control".
    def hook5(root, command, env=None):
        payload = json.dumps({"session_id": "selftest", "tool_name": "Bash",
                              "tool_input": {"command": command}, "cwd": root})
        return subprocess.run(["python3", V4GATE, "hook"], cwd=root, input=payload, capture_output=True,
                              text=True, env=dict(os.environ, QA_GATE_NO_GH="1", **(env or {})))

    def deny5(root, command, name, why, env=None):
        p = hook5(root, command, env)
        expect(p.returncode == 2 and "qa-ship-gate" in p.stderr and why in p.stderr,
               "v5 DENY  %s [%s]" % (name, " ".join(p.stderr.split())[-110:]))

    def allow5(root, command, name):
        p = hook5(root, command)
        expect(p.returncode == 0, "v5 ALLOW %s [%s]" % (name, " ".join(p.stderr.split())[:100]))

    def git_dep(sha, **meta):
        return {"id": "dpl_x", "target": "production", "meta": meta,
                "gitSource": {"type": "github", "ref": "main", "sha": sha}}

    json.dump({
        "dpl_walked": git_dep(codeW, githubCommitSha=codeW),
        "app-walked.vercel.app": git_dep(codeW, githubCommitSha=codeW),
        "dpl_walkedqa": git_dep(shaW, githubCommitSha=shaW),
        "dpl_squash": git_dep(shaS),
        "dpl_unwalked": git_dep(codeU, githubCommitSha=codeU),
        "dpl_foreign": git_dep("ab" * 20),
        "dpl_nogit": {"id": "dpl_nogit", "target": "production", "meta": {}},
        "dpl_dirty": git_dep(codeW, githubCommitSha=codeW, gitDirty="1"),
        "dpl_mismatch": git_dep(codeW, githubCommitSha=codeU),
    }, open(os.path.join(stub_bin, "deployments.json"), "w"))
    os.makedirs(os.path.join(r9, ".vercel"))
    json.dump({"orgId": "team_fx", "projectId": "prj_1"}, open(os.path.join(r9, ".vercel", "project.json"), "w"))
    open(os.path.join(r9, "prod-body-w.json"), "w").write(json.dumps(
        {"name": "app", "target": "production", "gitSource": {"type": "github", "sha": codeW}}))
    with open(os.path.join(r9, ".git", "info", "exclude"), "a") as fh:
        fh.write("/.vercel/\n/prod-body.json\n/preview-body.json\n/prod-body-w.json\n")
    no_vercel = os.pathsep.join(d for d in os.environ["PATH"].split(os.pathsep)
                                if d and not os.path.isfile(os.path.join(d, "vercel")))
    U = codeU[:12]
    sh("git checkout -q main", cwd=r9)  # HEAD = W, walked
    deny5(r9, "vercel promote dpl_unwalked", "walked HEAD A cannot promote unwalked deployment B", U)
    deny5(r9, "vercel redeploy dpl_unwalked", "walked HEAD cannot redeploy unwalked deployment", U)
    deny5(r9, "vercel --scope team_fx promote dpl_unwalked", "global flag before the subcommand", U)
    deny5(r9, "curl -X POST 'https://api.vercel.com/v10/projects/prj_1/promote/dpl_unwalked?teamId=team_fx'",
          "promote API (curl) of an unwalked deployment", U)
    deny5(r9, "vercel api /v10/projects/prj_1/promote/dpl_unwalked -X POST",
          "promote API (vercel api, scope from .vercel/project.json)", U)
    deny5(r9, 'vercel api "/v13/deployments?teamId=team_x" -X POST --input prod-body.json',
          "production API create whose gitSource is unwalked", U)
    deny5(r9, "vercel alias set dpl_unwalked app.example.com", "vercel alias set to an unwalked deployment", U)
    deny5(r9, "vercel alias dpl_unwalked app.example.com", "vercel alias (no set) to an unwalked deployment", U)
    deny5(r9, "vercel alias app.example.com", "vercel alias with the deployment left implicit",
          "no deployment id")
    deny5(r9, "curl -X POST 'https://api.vercel.com/v2/deployments/dpl_unwalked/aliases?teamId=team_fx' "
              "-d '{\"alias\":\"app.example.com\"}'", "alias API on an unwalked deployment", U)
    deny5(r9, "vercel api /v13/deployments -X POST -F name=app -F deploymentId=dpl_unwalked -F target=production",
          "production API redeploy (deploymentId) of an unwalked deployment", U)
    deny5(r9, "vercel rolling-release start --dpl dpl_unwalked", "rolling release of an unwalked deployment", U)
    deny5(r9, "vercel promote dpl_unknown", "unknown deployment", "provenance lookup failed")
    deny5(r9, "vercel promote dpl_offline", "API offline", "provenance lookup failed")
    deny5(r9, "vercel promote dpl_slow", "lookup past the hook budget", "timed out")
    deny5(r9, "vercel promote dpl_foreign", "source commit not in this clone", "not in this clone")
    deny5(r9, "vercel promote dpl_nogit", "deployment without git metadata", "no git provenance")
    deny5(r9, "vercel promote dpl_dirty", "deployment built from a dirty tree", "uncommitted changes")
    deny5(r9, "vercel promote dpl_mismatch", "gitSource and meta disagree", "conflicting source commits")
    deny5(r9, "vercel promote", "promote with no deployment named", "no deployment id")
    deny5(r9, "vercel promote dpl_walked --scope team_other", "explicit scope that cannot see it",
          "provenance lookup failed")
    deny5(r9, "vercel promote dpl_walked", "vercel CLI missing from the hook PATH", "not on the hook's PATH",
          env={"PATH": no_vercel})
    deny5(r9, "gh release edit vbad --draft=false", "gh release edit publishing an unwalked tag", U)
    deny5(r9, "gh release edit vbad --draft=0", "gh release edit --draft=0 (pflag false)", U)
    deny5(r9, "gh release edit vgood --draft=false --tag vbad", "gh release edit moving to an unwalked tag", U)
    deny5(r9, "gh release edit vnope --draft=false", "gh release edit of a tag not in the clone",
          "not in this clone")
    gw = "GitHub API write"
    deny5(r9, "gh api -X PUT repos/o/r/pulls/5/merge", "gh api PR merge", gw)
    deny5(r9, "gh api repos/{owner}/{repo}/releases -f tag_name=v9", "gh api release create (fields imply POST)", gw)
    deny5(r9, "gh api -X PATCH repos/o/r/releases/123 -F draft=false", "gh api release publish", gw)
    deny5(r9, "gh api repos/o/r/git/refs -f ref=refs/tags/v9 -f sha=abc", "gh api ref create", gw)
    deny5(r9, "gh api -XPOST repos/o/r/actions/workflows/deploy.yml/dispatches -f ref=main",
          "gh api workflow dispatch", gw)
    deny5(r9, "gh api repos/o/r/merges -f base=main -f head=feat", "gh api branch merge", gw)
    deny5(r9, "gh api -X PUT repos/o/r/contents/f.txt -f message=m -f content=eA==", "gh api contents commit", gw)
    deny5(r9, "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) "
              "{ clientMutationId } }'", "gh api graphql mergePullRequest", gw)
    deny5(r9, "curl -X PUT https://api.github.com/repos/o/r/pulls/5/merge -H 'Authorization: token t'",
          "curl PR merge", gw)
    deny5(r9, "curl -d '{\"tag_name\":\"v9\"}' https://api.github.com/repos/o/r/releases", "curl release create", gw)
    allow5(r9, "vercel --prod", "control: upload deploy of a clean walked HEAD")
    with open(os.path.join(r9, "f.txt"), "a") as fh:
        fh.write("dirty\n")
    deny5(r9, "vercel --prod", "upload deploy of a walked HEAD with uncommitted code", "uploads the working tree")
    sh("git checkout -q -- f.txt", cwd=r9)
    sh("git checkout -q feat", cwd=r9)  # HEAD = U, unwalked
    allow5(r9, "vercel promote dpl_walked", "deployment built from the walked commit, HEAD unwalked")
    allow5(r9, "vercel promote dpl_walkedqa", "deployment built from the .qa commit on top of the walk")
    allow5(r9, "vercel promote dpl_squash", "deployment whose source tree equals the walked tree")
    allow5(r9, "vercel redeploy https://app-walked.vercel.app", "redeploy by URL of a walked deployment")
    allow5(r9, "curl -X POST 'https://api.vercel.com/v10/projects/prj_1/promote/dpl_walked?teamId=team_fx'",
           "promote API of a walked deployment")
    allow5(r9, 'vercel api "/v13/deployments?teamId=team_x" -X POST --input prod-body-w.json',
           "production API create whose gitSource is walked")
    allow5(r9, "vercel promote status", "vercel promote status (read-only)")
    allow5(r9, "vercel alias set dpl_walked app.example.com", "vercel alias set to a walked deployment")
    allow5(r9, "vercel api /v13/deployments -X POST -F name=app -F deploymentId=dpl_walked -F target=production",
           "production API redeploy (deploymentId) of a walked deployment")
    allow5(r9, "vercel alias ls", "control: vercel alias ls (read-only)")
    allow5(r9, "gh api repos/o/r/releases", "control: gh api release list (GET)")
    allow5(r9, "gh api repos/o/r/pulls/5/merge", "control: gh api is-merged check (GET)")
    allow5(r9, "gh api graphql -f query='query { viewer { login } }'", "control: gh api graphql query")
    allow5(r9, "gh api -X DELETE repos/o/r/git/refs/heads/old", "control: gh api branch delete")
    allow5(r9, "curl https://api.github.com/repos/o/r/releases", "control: curl GitHub GET")

    # the decision must land inside the host's hook timeout (a timed-out hook
    # lets the command run): a 2.5 s lookup followed by a deployed_check that
    # hangs for 10 s must still deny in time. HOOK_T0 leaves the gate 4.2 s of
    # its chain budget, the window these two cases were written for, so their
    # bounds do not depend on how fast this host is.
    def t0_left(seconds):
        return {"HOOK_T0": "%.3f" % (time.time() - (HOOK_HARD_S - seconds))}
    r12 = os.path.join(tmp, "v5budget")
    os.makedirs(os.path.join(r12, ".qa"))
    sh("git init -q -b main && git config user.email t@t && git config user.name t", cwd=r12)
    json.dump({"schema_version": 1, "personas": ["admin"], "workflows": [{"name": "w1"}],
               "deployed_check": {"command": "sleep 10", "timeout_s": 10}},
              open(os.path.join(r12, ".qa", "config.json"), "w"))
    open(os.path.join(r12, "f.txt"), "w").write("x\n")
    sh("git add -A && git commit -qm base", cwd=r12)
    code12 = sh("git rev-parse HEAD", cwd=r12).stdout.strip()
    write_run(r12, "w", code12)
    sh("git add .qa && git commit -qm evidence -- .qa", cwd=r12)
    os.makedirs(os.path.join(r12, ".vercel"))
    json.dump({"orgId": "team_fx"}, open(os.path.join(r12, ".vercel", "project.json"), "w"))
    fx = json.load(open(os.path.join(stub_bin, "deployments.json")))
    fx["dpl_budget"] = dict(git_dep(code12), _sleep=2.5)
    json.dump(fx, open(os.path.join(stub_bin, "deployments.json"), "w"))
    t0 = time.monotonic()
    p = hook5(r12, "vercel promote dpl_budget", env=t0_left(4.2))
    took = time.monotonic() - t0
    expect(p.returncode == 2 and took < 4.8,
           "v5 DENY  slow lookup + hanging deployed_check decides in %.1f s (< 4.8 s) [%s]"
           % (took, " ".join(p.stderr.split())[-90:]))
    # hard deadline: work no soft clamp bounds (every git call 0.3 s slower,
    # as on a loaded host) must still end in a deny before the host timeout
    slow_git = os.path.join(tmp, "slow-git")
    os.makedirs(slow_git)
    with open(os.path.join(slow_git, "git"), "w") as fh:
        fh.write("#!/bin/sh\nsleep 0.3\nexec %s \"$@\"\n" % shutil.which("git"))
    os.chmod(os.path.join(slow_git, "git"), 0o755)
    sh("git checkout -q main", cwd=r9)
    t0 = time.monotonic()
    p = hook5(r9, "git push origin main", env=dict(t0_left(4.2), PATH=slow_git + os.pathsep + os.environ["PATH"]))
    took = time.monotonic() - t0
    expect(p.returncode == 2 and "could not finish within" in p.stderr and took < 4.8,
           "v5 DENY  slow host: hard deadline denies a normally allowed push in %.1f s (< 4.8 s) [%s]"
           % (took, " ".join(p.stderr.split())[-90:]))
    # T1: the clock starts with the hook chain (HOOK_T0), not with this
    # process. A chain that already spent its budget before the gate started
    # (slow interpreter start, an earlier stage) denies a ship at once and
    # still allows everything else; a T0 in the future buys no extra time.
    spent = {"HOOK_T0": "%.3f" % (time.time() - HOOK_HARD_S - 1)}
    t0 = time.monotonic()
    p = hook5(r9, "git push origin main", env=spent)
    took = time.monotonic() - t0
    expect(p.returncode == 2 and "could not finish within" in p.stderr and took < 2.0,
           "T1 DENY  chain budget already spent: ship denied in %.2f s (< 2.0 s) [%s]"
           % (took, " ".join(p.stderr.split())[-90:]))
    p = hook5(r9, "ls -la", env=spent)
    expect(p.returncode == 0, "T1 ALLOW chain budget already spent: a non-ship command is allowed")
    os.environ["HOOK_T0"] = "%.3f" % (time.time() + 3600)
    future = hook_elapsed()
    os.environ["HOOK_T0"] = "not-a-time"
    garbage = hook_elapsed()
    os.environ.pop("HOOK_T0", None)
    expect(future == 0.0 and garbage == 0.0 and hook_elapsed() == 0.0,
           "T1 a future, unreadable or missing HOOK_T0 counts as 0 s spent (never extends the budget)")
    expect(HOOK_HARD_S <= HOOK_HOST_TIMEOUT_S - 3.0 and HOOK_BUDGET_S < HOOK_HARD_S,
           "T1 hard deadline leaves >= 3 s before the host timeout, soft budget before the hard one")

    sh("git checkout -q feat", cwd=r9)
    allow5(r9, "gh release edit vgood --draft=false", "control: gh release edit publishing a walked tag")
    allow5(r9, "gh release edit vbad --title x", "control: gh release edit that does not publish")

    # non-opted-in repo: every new ship command stays free
    r11 = os.path.join(tmp, "v4plain")
    os.makedirs(r11)
    sh("git init -q -b main && git config user.email t@t && git config user.name t && echo x > f && "
       "git add -A && git commit -qm i && git tag v1.2", cwd=r11)
    for c in ("git push origin v1.2", "git push --tags", "gh release create v1.2", "gh workflow run deploy",
              "vercel redeploy dpl_1", "npx vercel --prod",
              "vercel api /v13/deployments -X POST -F target=production",
              "curl -X POST https://api.vercel.com/v13/deployments -d '{\"target\":\"production\"}'"):
        allow4(r11, c, "non-opted repo: %s" % c)

    # git pre-push layer: real pushes to a local bare remote
    bare9 = os.path.join(tmp, "remote9.git")
    sh("git init -q --bare -b main %s" % bare9)
    sh("git remote add r9remote %s && git push -q r9remote main" % bare9, cwd=r9)
    os.makedirs(os.path.join(r9, ".qa", "bin"), exist_ok=True)
    shutil.copy(V4GATE, os.path.join(r9, ".qa", "bin", "ship-gate.py"))
    shutil.copy(os.path.join(V4TMPL, "pre-push"), os.path.join(r9, ".git", "hooks", "pre-push"))
    os.chmod(os.path.join(r9, ".git", "hooks", "pre-push"), 0o755)

    def landed(ref):
        return bool(sh("git --git-dir=%s rev-parse --verify -q %s" % (bare9, ref)).stdout.strip())

    p = sh("git push r9remote vgood", cwd=r9)
    expect(p.returncode == 0 and landed("refs/tags/vgood"), "v4 prepush: tag at a walked commit lands")
    p = sh("git push r9remote vbad", cwd=r9)
    expect(p.returncode != 0 and not landed("refs/tags/vbad"), "v4 prepush: tag at an unwalked commit denied, nothing landed")
    sh("git tag -a vann -m annotated %s" % codeU, cwd=r9)
    p = sh("git push r9remote vann", cwd=r9)
    expect(p.returncode != 0 and not landed("refs/tags/vann"), "v4 prepush: annotated tag peeled to its unwalked commit, denied")
    p = sh("git push r9remote --tags", cwd=r9)
    expect(p.returncode != 0 and not landed("refs/tags/vbad"), "v4 prepush: --tags denied on the unwalked tag")
    p = sh("git push r9remote feat", cwd=r9)
    expect(p.returncode == 0 and landed("refs/heads/feat"), "v4 prepush: feature branch still lands")
    p = sh("git push r9remote vsquash", cwd=r9)
    expect(p.returncode == 0 and landed("refs/tags/vsquash"),
           "v4 prepush tree-equiv: tag on the identical-tree squash commit lands [%s]" % p.stderr.strip()[-100:])
    p = sh("git push r9remote vqaonly", cwd=r9)
    expect(p.returncode == 0 and landed("refs/tags/vqaonly"), "v4 prepush tree-equiv: .qa-only tree difference lands")
    p = sh("git push r9remote vmerge", cwd=r9)
    expect(p.returncode != 0 and not landed("refs/tags/vmerge"),
           "v4 prepush tree-equiv: tag on the merge commit with other changes denied, nothing landed")
    p = sh("git push r9remote vsquash:refs/heads/dev", cwd=r9)
    expect(p.returncode != 0 and not landed("refs/heads/dev"),
           "v4 prepush tree-equiv: the squash commit pushed to protected dev stays denied")

    # merge_group: the resolver block of qa-ci.yml, run verbatim
    ci_text = open(os.path.join(V4TMPL, "qa-ci.yml")).read()
    expect(re.search(r"(?m)^\s+merge_group:", ci_text) is not None, "v4 qa-ci: merge_group trigger present")
    expect("pull-requests: read" in ci_text, "v4 qa-ci: pull-requests: read (gh pr view in queue runs)")
    m = re.search(r"# --- qa-gate resolve-sha begin[^\n]*\n(.*?)# --- qa-gate resolve-sha end", ci_text, re.S)
    expect(m is not None, "v4 qa-ci: marked SHA resolver present")
    resolver = os.path.join(tmp, "resolve-sha.sh")
    rlines = m.group(1).splitlines() if m else ["exit 3"]
    ded = min(len(l) - len(l.lstrip()) for l in rlines if l.strip())
    open(resolver, "w").write("\n".join(l[ded:] for l in rlines) + "\n")
    ghbin = os.path.join(tmp, "v4bin")
    os.makedirs(ghbin, exist_ok=True)
    real_head = "5c5c01b2e82ce9efbbc03f8945a98a5cbea86c7b"  # PR #167 head, shoc-backend run 35815603657
    open(os.path.join(ghbin, "gh"), "w").write(
        "#!/bin/sh\ncase \"$*\" in\n  'pr view 167 --json headRefOid --jq .headRefOid') echo %s;;\n"
        "  'pr view 42 --json headRefOid --jq .headRefOid') echo %s;;\n  *) exit 1;;\nesac\n" % (real_head, shaW))
    os.chmod(os.path.join(ghbin, "gh"), 0o755)

    def resolve(event, ref, sha, pr_head=""):
        out = os.path.join(tmp, "gh-output")
        if os.path.exists(out):
            os.remove(out)
        env = dict(os.environ, GITHUB_OUTPUT=out, GITHUB_EVENT_NAME=event, GITHUB_REF=ref, GITHUB_SHA=sha,
                   PR_HEAD=pr_head, PATH=ghbin + os.pathsep + os.environ.get("PATH", ""))
        p = subprocess.run(["/bin/sh", resolver], env=env, capture_output=True, text=True)
        val = ""
        if os.path.exists(out):
            val = next((l.strip()[4:] for l in open(out) if l.startswith("sha=")), "")
        return p.returncode, val

    grp = "f7db6b9f843f6e0ac8dfe5590a3015e6487fc861"
    rc, val = resolve("merge_group", "refs/heads/gh-readonly-queue/main/pr-167-b36b69df83f9caedf2f8ce11d3122d8795eec01e", grp)
    expect(rc == 0 and val == real_head, "v4 merge_group: real queue ref resolves the queued PR head, not the group sha (got %s)" % val[:12])
    rc, val = resolve("merge_group", "refs/heads/gh-readonly-queue/release/1.0/pr-167-" + "b" * 40, grp)
    expect(rc == 0 and val == real_head, "v4 merge_group: base branch with a slash (got %s)" % val[:12])
    rc, val = resolve("merge_group", "gh-readonly-queue/main/pr-167-" + "b" * 40, grp)
    expect(rc == 0 and val == real_head, "v4 merge_group: bare branch-name ref form (got %s)" % val[:12])
    rc, val = resolve("merge_group", "refs/heads/gh-readonly-queue/main/pr-999-" + "b" * 40, grp)
    expect(rc != 0 and not val, "v4 merge_group: unresolvable PR head fails the job")
    rc, val = resolve("merge_group", "refs/heads/something-else", grp)
    expect(rc != 0 and not val, "v4 merge_group: unparseable queue ref fails instead of checking the group commit")
    rc, val = resolve("pull_request", "refs/pull/9/merge", "c" * 40, "a" * 40)
    expect(rc == 0 and val == "a" * 40, "v4 pull_request: PR head sha")
    rc, val = resolve("push", "refs/heads/main", "c" * 40)
    expect(rc == 0 and val == "c" * 40, "v4 push: GITHUB_SHA")
    # the queued PR's head is what the gate then checks, against its .qa run
    rc, val = resolve("merge_group", "refs/heads/gh-readonly-queue/main/pr-42-" + codeW, codeU)
    ok_head = rc == 0 and val == shaW and subprocess.run(
        ["python3", V4GATE, "check", "--repo", r9, "--sha", val], capture_output=True).returncode == 0
    grp_fail = subprocess.run(["python3", V4GATE, "check", "--repo", r9, "--sha", codeU],
                              capture_output=True).returncode != 0
    expect(ok_head and grp_fail, "v4 merge_group: gate passes the queued PR head, would fail the group commit")

    # husky: gate block at the top of .husky/pre-push, pallium-style ref parser after it
    tmpl_text = open(os.path.join(V4TMPL, "pre-push")).read()
    mb = re.search(r"(?ms)^# --- qa-ship-gate begin.*?^# --- qa-ship-gate end[^\n]*\n", tmpl_text)
    block = mb.group(0) if mb else tmpl_text
    husky_tail = ('while read local_ref local_sha remote_ref remote_sha; do echo "husky-saw $remote_ref"; done\n'
                  'echo husky-after\n')

    def husky_repo(name, v9):
        r = os.path.join(tmp, name)
        os.makedirs(os.path.join(r, ".husky", "_"))
        sh("git init -q -b main && git config user.email t@t && git config user.name t && echo x > f && "
           "git add f && git commit -qm i", cwd=r)
        bare = os.path.join(tmp, name + ".git")
        sh("git init -q --bare -b main %s" % bare)
        sh("git remote add up %s && git push -q up main" % bare, cwd=r)
        open(os.path.join(r, ".husky", "pre-push"), "w").write("#!/usr/bin/env sh\n" + block + husky_tail)
        os.chmod(os.path.join(r, ".husky", "pre-push"), 0o755)
        if v9:  # husky v9 layout: .husky/_/<hook> sources h, which runs the script under sh -e
            open(os.path.join(r, ".husky", "_", "h"), "w").write(
                '#!/usr/bin/env sh\nn=$(basename "$0")\ns=$(dirname "$(dirname "$0")")/$n\n'
                '[ ! -f "$s" ] && exit 0\nsh -e "$s" "$@"\nc=$?\n'
                '[ $c != 0 ] && echo "husky - $n script failed (code $c)"\nexit $c\n')
            open(os.path.join(r, ".husky", "_", "pre-push"), "w").write('#!/usr/bin/env sh\n. "$(dirname "$0")/h"\n')
            os.chmod(os.path.join(r, ".husky", "_", "pre-push"), 0o755)
            sh("git config core.hooksPath .husky/_", cwd=r)
        else:
            sh("git config core.hooksPath .husky", cwd=r)
        return r, bare

    for label, v9 in (("husky v9 (sh -e)", True), ("husky plain", False)):
        r10, bare10 = husky_repo("husky-v9" if v9 else "husky-plain", v9)
        sh("git checkout -q -b feat/a && echo a >> f && git commit -qam a", cwd=r10)
        p = sh("git push up feat/a", cwd=r10)
        out = p.stdout + p.stderr
        expect(p.returncode == 0 and "husky-saw refs/heads/feat/a" in out and "husky-after" in out,
               "v4 %s: not opted in, push passes and the husky ref parser still sees the refs" % label)
        os.makedirs(os.path.join(r10, ".qa"))
        json.dump({"personas": ["a"], "workflows": [{"name": "w"}], "protected_branches": ["dev", "main"]},
                  open(os.path.join(r10, ".qa", "config.json"), "w"))
        sh("git add .qa && git commit -qm optin", cwd=r10)
        p = sh("git push up HEAD:dev", cwd=r10)
        exists = sh("git --git-dir=%s rev-parse --verify -q refs/heads/dev" % bare10).stdout.strip()
        expect(p.returncode != 0 and not exists and ".qa/bin/ship-gate.py is missing" in p.stderr,
               "v4 %s: config without .qa/bin -> named deny survives chaining" % label)
        os.makedirs(os.path.join(r10, ".qa", "bin"))
        shutil.copy(V4GATE, os.path.join(r10, ".qa", "bin", "ship-gate.py"))
        p = sh("git push up HEAD:dev", cwd=r10)
        exists = sh("git --git-dir=%s rev-parse --verify -q refs/heads/dev" % bare10).stdout.strip()
        expect(p.returncode != 0 and not exists and "husky-after" not in p.stdout + p.stderr,
               "v4 %s: opted in, dev push denied before the husky tail runs" % label)
        p = sh("git push up feat/a", cwd=r10)
        out = p.stdout + p.stderr
        expect(p.returncode == 0 and "husky-saw refs/heads/feat/a" in out and "husky-after" in out,
               "v4 %s: opted in, feature push passes and husky still sees the refs" % label)

    # Identity isolation (meu-psi 2026-09-25).
    def reader(files):
        return {"exists": lambda rel: rel in files, "read": lambda rel: files[rel]}
    row = {"id": "R9", "step": "s", "symptom": "gate 36/38: CI setup recreated the data mid-walk", "evidence": "e",
           "predates_change": True, "severity": "high", "status": "open", "kind": "environment_contamination"}
    f9 = []
    check_inventory("q", reader({"q/inventory.jsonl": json.dumps(row)}), f9, {})
    expect(any("must name the writer" in x for x in f9), "environment_contamination row without a writer is refused")
    f9 = []
    check_inventory("q", reader({"q/inventory.jsonl": json.dumps({**row, "writer": "gh run 18214"})}), f9, {})
    expect(not any("writer" in x for x in f9), "environment_contamination row naming its writer is accepted")
    pkt = {"authentication": {"required": True, "identity": {"label": "e2e.patient", "owned_by_automation": False}}}
    f9 = []
    check_e2e("q", reader({"q/evidence.json": json.dumps(pkt)}), {"automation_identities": ["e2e.patient"]}, f9)
    expect(any("automation_identities" in x for x in f9), "a config-listed CI identity declared unowned is refused")
    pkt2 = {"authentication": {"required": True, "identities": [
        {"label": "qa.professional", "owned_by_automation": False},
        {"label": "e2e.patient", "owned_by_automation": False}]}}
    f9 = []
    check_e2e("q", reader({"q/evidence.json": json.dumps(pkt2)}), {"automation_identities": ["e2e.patient"]}, f9)
    expect(any("'e2e.patient'" in x for x in f9), "a config-listed CI identity in identities[1] declared unowned is refused")
    pkt2["authentication"]["identity"] = {"label": "qa.professional", "owned_by_automation": False}
    pkt2["authentication"]["identities"] = [{"label": "e2e.patient", "owned_by_automation": False}]
    f9 = []
    check_e2e("q", reader({"q/evidence.json": json.dumps(pkt2)}), {"automation_identities": ["e2e.patient"]}, f9)
    expect(any("'e2e.patient'" in x for x in f9), "identity plus identities: the second persona is still cross-checked")
    pkt2["authentication"]["identity"] = {"label": "e2e.patient", "owned_by_automation": False}
    pkt2["authentication"]["identities"] = [{"label": "qa.professional", "owned_by_automation": False}]
    f9 = []
    check_e2e("q", reader({"q/evidence.json": json.dumps(pkt2)}), {"automation_identities": ["e2e.patient"]}, f9)
    expect(any("'e2e.patient'" in x for x in f9), "identity plus identities: the legacy identity is still cross-checked")

    pkt["authentication"]["identity"]["owned_by_automation"] = True

    f9 = []
    check_e2e("q", reader({"q/evidence.json": json.dumps(pkt)}), {"automation_identities": ["e2e.patient"]}, f9)
    expect(not any("automation_identities" in x for x in f9), "a config-listed CI identity declared owned passes the cross-check")
    # review r1 D4: however the listed label is spelled, both gates find it,
    # and the two gates agree label by label.
    probe = ["e2e.patient", "E2E.patient", "e2e.patient ", "e2e.patient@meupsi.test", "e2е.patient",
             "е2е.раtіеnt", "e2e.pat​ient", "E2E.PATİENT", "qa.vеndor", "qa.patient", "joão.silva", "Straße.qa"]
    refused = probe[:9]


    mjs_verdicts = {}
    if shutil.which("node") and os.path.isfile(E2E_GATE):
        js = ("import(process.argv[1]).then((m) => { const out = {};"
              " for (const l of JSON.parse(process.argv[2])) out[l] = [m.labelKey(l), m.labelProblem(l),"
              " m.listedIdentity(l, ['e2e.patient'])]; process.stdout.write(JSON.stringify(out)); })")
        run = subprocess.run(["node", "--input-type=module", "-e", js, "--", __import__("pathlib").Path(E2E_GATE).as_uri(), json.dumps(probe)],
                             capture_output=True, text=True, timeout=30)
        mjs_verdicts = json.loads(run.stdout or "{}")
    expect(bool(mjs_verdicts), "qa-e2e-gate.mjs label functions ran (%s)" % E2E_GATE)
    for label in probe:
        f9 = []
        pk = {"authentication": {"required": True, "identities": [
            {"label": label, "ownership_checked": True, "ownership_evidence": "searched", "owned_by_automation": False}]}}
        check_e2e("q", reader({"q/evidence.json": json.dumps(pk)}), {"automation_identities": ["e2e.patient"]}, f9)
        hit = any("refused" in x or "automation_identities" in x for x in f9)
        expect(hit == (label in refused), "label %r is %s by the ship gate" % (label, "refused" if label in refused else "accepted"))
        py = [label_key(label), label_problem(label), list(listed_identity(label, ["e2e.patient"]) or []) or None]
        expect(label not in mjs_verdicts or mjs_verdicts[label] == py,
               "label %r: ship-gate.py and qa-e2e-gate.mjs agree (%s vs %s)" % (label, py, mjs_verdicts.get(label)))
    # meu-psi PR #36: the suite's own CI run recorded as the walk (owner_run).
    base_or = {"label": "e2e.patient", "owned_by_automation": True, "owner": "deployed e2e gate",
               "walker": {"kind": "owner_run", "owner": "deployed e2e gate", "run_id": 36193694659,
                          "run_url": "https://github.com/albrand/psyche-project/actions/runs/36193694659"}}
    variants = {
        "valid": (base_or, ["e2e.patient"], True),
        "valid, attempt URL": ({**base_or, "walker": {**base_or["walker"], "run_url": base_or["walker"]["run_url"] + "/attempts/2"}}, ["e2e.patient"], True),
        "no list (r2a D5)": (base_or, [], False),
        "run_id x, no run_url (r2a D5)": ({**base_or, "walker": {"kind": "owner_run", "owner": "deployed e2e gate", "run_id": "x"}}, ["e2e.patient"], False),
        "run_url of another run (r2a D5)": ({**base_or, "walker": {**base_or["walker"], "run_id": 1, "run_url": "https://github.com/someone/else/actions/runs/999"}}, ["e2e.patient"], False),
        "run_url off github.com": ({**base_or, "walker": {**base_or["walker"], "run_url": "https://evil.test/a/b/actions/runs/36193694659"}}, ["e2e.patient"], False),
        "no walker": ({k: v for k, v in base_or.items() if k != "walker"}, ["e2e.patient"], True),
        "owner mismatch": ({**base_or, "walker": {**base_or["walker"], "owner": "other"}}, ["e2e.patient"], False),
        "no run_id": ({**base_or, "walker": {"kind": "owner_run", "owner": "deployed e2e gate"}}, ["e2e.patient"], False),
        "unlisted label": ({**base_or, "label": "e2e.other"}, ["e2e.patient"], False),
        "unowned": ({**base_or, "owned_by_automation": False}, ["e2e.patient"], False),
        "unknown kind": ({**base_or, "walker": {"kind": "borrowed"}}, ["e2e.patient"], False),
        "fullwidth digits (r2a-bis)": ({**base_or, "walker": {**base_or["walker"], "run_id": "３６１９３６９４６５９",
                                        "run_url": "https://github.com/albrand/psyche-project/actions/runs/３６１９３６９４６５９"}},
                                       ["e2e.patient"], False),
    }
    mjs_or = {}
    if shutil.which("node") and os.path.isfile(E2E_GATE):
        js = ("import(process.argv[1]).then((m) => { const out = {}; const v = JSON.parse(process.argv[2]);"
              " for (const k of Object.keys(v)) out[k] = m.ownerRunProblems(v[k][0], v[k][1]).problems.length === 0;"
              " process.stdout.write(JSON.stringify(out)); })")
        run = subprocess.run(["node", "--input-type=module", "-e", js, "--", __import__("pathlib").Path(E2E_GATE).as_uri(),
                              json.dumps(variants)], capture_output=True, text=True, timeout=30)
        mjs_or = json.loads(run.stdout or "{}")
    for name, (ident, lst, ok) in variants.items():
        py_ok = not owner_run_problems(ident, lst)
        expect(py_ok == ok, "owner_run %s: ship gate %s" % (name, "accepts" if ok else "refuses"))
        expect(mjs_or.get(name) == ok, "owner_run %s: qa-e2e-gate.mjs agrees (%s)" % (name, mjs_or.get(name)))
    # r2a D5, r2a-bis: the ship gate ties the run to this repository and checks
    # the run attempt with `gh api` (stubbed here: offline, deterministic). The
    # stub answers repos/albrand/psyche-project/actions/runs/<id>[/attempts/<n>]
    # from <dir>/<path with / as _>.json and logs every call.
    orr = os.path.join(tmp, "owner-run-repo")
    os.makedirs(orr)
    sh("git init -q && git remote add origin git@github.com:albrand/psyche-project.git", cwd=orr)
    orbin = os.path.join(tmp, "owner-run-bin")
    os.makedirs(orbin)
    ghdir = os.path.join(tmp, "gh-api")
    os.makedirs(ghdir)
    open(os.path.join(orbin, "gh"), "w").write(
        "#!/bin/sh\n[ -n \"$OR_GH_SLEEP\" ] && sleep \"$OR_GH_SLEEP\"\n"
        f"echo \"$*\" >> {ghdir}/calls\n"
        f"f={ghdir}/$(printf %s \"$2\" | tr / _).json\n"
        "[ \"$1\" = api ] && [ -f \"$f\" ] || { echo 'unexpected gh call' >&2; exit 1; }\n"
        "cat \"$f\"\n")
    os.chmod(os.path.join(orbin, "gh"), 0o755)
    walked = "a" * 40
    runs_path = "repos/albrand/psyche-project/actions/runs/36193694659"
    run_doc = {"head_sha": walked, "run_attempt": 1, "run_started_at": "2026-09-25T15:05:00Z",
               "updated_at": "2026-09-25T15:45:00Z", "status": "completed", "conclusion": "success"}
    ident_or = {**base_or, "walk_window": {"start": "2026-09-25T15:10:00Z", "end": "2026-09-25T15:40:00Z"}}
    saved_path = os.environ["PATH"]

    def gh_calls():
        p = os.path.join(ghdir, "calls")
        return open(p).read().splitlines() if os.path.isfile(p) else []

    def verify(ident, doc=run_doc, root=orr, sha=walked, path_first=orbin, sleep=None, attempts=None, cache=None,
               keep_calls=False):
        global _LOOKUP_DEADLINE
        for f in os.listdir(ghdir):
            if not (keep_calls and f == "calls"):
                os.remove(os.path.join(ghdir, f))

        for path, d in [(runs_path, doc)] + sorted((attempts or {}).items()):
            with open(os.path.join(ghdir, path.replace("/", "_") + ".json"), "w") as f:
                f.write(d if isinstance(d, str) else json.dumps(d))
        os.environ["PATH"] = (path_first + os.pathsep if path_first else "") + "/usr/bin:/bin"
        if sleep:
            os.environ["OR_GH_SLEEP"] = sleep
        _LOOKUP_DEADLINE = None
        try:
            return owner_run_verify(root, ident, sha, cache)
        finally:
            os.environ["PATH"] = saved_path
            os.environ.pop("OR_GH_SLEEP", None)
            _LOOKUP_DEADLINE = None

    expect(verify(ident_or) == [], "owner_run: right repo, matching id, run on the walked commit around the walk -> pass")
    expect(gh_calls() == ["api " + runs_path], "owner_run: no attempt named -> the run's latest attempt (%s)" % gh_calls())
    expect(any("not the walked commit" in p for p in verify(ident_or, {**run_doc, "head_sha": "b" * 40})),
           "owner_run: a run on another commit -> deny")
    expect(any("not inside it" in p for p in verify(ident_or, {**run_doc, "updated_at": "2026-09-25T15:30:00Z"})),
           "owner_run: a walk window outside the run -> deny")
    # r2a-bis: an unfinished or failed run is not a walk.
    expect(any("not completed/success" in p for p in verify(ident_or, {**run_doc, "status": "in_progress", "conclusion": None})),
           "owner_run: a run still in progress -> deny")
    expect(any("not completed/success" in p for p in verify(ident_or, {**run_doc, "conclusion": "failure"})),
           "owner_run: a failed run -> deny")
    expect(any("not completed/success" in p for p in verify(ident_or, {k: v for k, v in run_doc.items() if k != "conclusion"})),
           "owner_run: a run with no conclusion -> deny")
    expect(any("not completed/success" in p for p in verify(ident_or, {**run_doc, "status": "in_progress"})),
           "owner_run: a run in progress that reports a success conclusion -> deny")
    # r2a-bis: a re-run moves the run's updated time; the window is the attempt's own.
    rerun = {**run_doc, "run_attempt": 2, "run_started_at": "2026-09-27T10:00:00Z", "updated_at": "2026-09-27T10:40:00Z"}
    expect(any("not inside it" in p for p in verify(ident_or, rerun)),
           "owner_run: a walk in attempt 1, run re-run later, URL names no attempt -> deny (the latest attempt's window)")
    at1 = {**ident_or, "walker": {**ident_or["walker"], "run_url": ident_or["walker"]["run_url"] + "/attempts/1"}}
    expect(verify(at1, rerun, attempts={runs_path + "/attempts/1": run_doc}) == [],
           "owner_run: the same walk, URL names /attempts/1 -> pass on that attempt's window")
    expect(gh_calls() == ["api " + runs_path + "/attempts/1"], "owner_run: /attempts/1 asks for that attempt (%s)" % gh_calls())
    late = {**ident_or, "walk_window": {"start": "2026-09-27T10:05:00Z", "end": "2026-09-27T10:20:00Z"}}
    expect(any("not inside it" in p for p in verify({**late, "walker": at1["walker"]}, rerun, attempts={runs_path + "/attempts/1": run_doc})),
           "owner_run: a walk during attempt 2 recorded as /attempts/1 -> deny")
    # r2a-bis: a naive time is read in the local zone, so it is refused.
    naive = {**ident_or, "walk_window": {"start": "2026-09-25T15:10:00", "end": "2026-09-25T15:40:00"}}
    expect(any("with an offset" in p for p in verify(naive)), "owner_run: a walk window with no offset -> deny")
    # Inside a day-long run, so no local-zone reading of the naive times fits it by accident.
    day = {**run_doc, "run_started_at": "2026-09-25T00:00:00Z", "updated_at": "2026-09-26T00:00:00Z"}
    naive_mid = {**ident_or, "walk_window": {"start": "2026-09-25T12:10:00", "end": "2026-09-25T12:40:00"}}
    expect(any("with an offset" in p for p in verify(naive_mid, day)), "owner_run: a naive walk window inside a day-long run -> deny")
    expect(any("not inside it" in p for p in verify(ident_or, {**day, "run_started_at": "2026-09-25T00:00:00"})),
           "owner_run: a run start with no offset -> deny")
    fullwidth = "３６１９３６９４６５９"
    expect(owner_run_id({"run_id": fullwidth}) is None
           and not RUN_URL_RE.match("https://github.com/albrand/psyche-project/actions/runs/" + fullwidth),
           "owner_run: fullwidth digits are not a run id or a run URL (ASCII, as in qa-e2e-gate.mjs)")
    shifted = {**ident_or, "walk_window": {"start": "2026-09-25T12:10:00-03:00", "end": "2026-09-25T12:40:00-03:00"}}
    expect(verify(shifted) == [], "owner_run: the same walk window at -03:00 -> pass")
    # r2a-bis: a reply that is not a run object denies with a reason, not an exception.
    for bad in ("[]", "null", "\"x\"", "not json"):
        r = verify(ident_or, bad)
        expect(any("returned no run object" in p for p in r), "owner_run: gh replying %s -> deny (%s)" % (bad, r))
    # r2a-bis: one lookup per run attempt within a check (#36 names one run
    # twice), and none carried from one check into the next.
    one_check = {}
    verify(ident_or, cache=one_check)
    second = verify(ident_or, {**run_doc, "conclusion": "failure"}, cache=one_check, keep_calls=True)
    expect(second == [] and len(gh_calls()) == 1, "owner_run: the same run twice in one check -> one gh call (%d)" % len(gh_calls()))
    expect(any("not completed/success" in p for p in verify(ident_or, {**run_doc, "conclusion": "failure"}))
           and verify(ident_or) == [], "owner_run: a later check looks the run up again")
    verify(ident_or)  # leaves the stub's run doc in place
    os.remove(os.path.join(ghdir, "calls"))
    os.environ["PATH"] = orbin + os.pathsep + "/usr/bin:/bin"
    try:
        f_two = []
        check_e2e("q", reader({"q/evidence.json": json.dumps({"authentication": {"identities": [ident_or, dict(ident_or)]}})}),
                  {"automation_identities": ["e2e.patient"]}, f_two, orr, walked)
    finally:
        os.environ["PATH"] = saved_path
        _LOOKUP_DEADLINE = None
    expect(len(gh_calls()) == 1, "owner_run: check_e2e with two identities on one run -> one gh call (%d)" % len(gh_calls()))
    expect(any("not on the hook's PATH" in p for p in verify(ident_or, path_first=None)),
           "owner_run: gh unavailable -> deny")
    _LOOKUP_DEADLINE_SAVED = LOOKUP_BUDGET_S
    globals()["LOOKUP_BUDGET_S"] = 0.5
    try:
        expect(any("timed out" in p for p in verify(ident_or, sleep="3")), "owner_run: gh timing out -> deny")
    finally:
        globals()["LOOKUP_BUDGET_S"] = _LOOKUP_DEADLINE_SAVED
    at9 = {**ident_or, "walker": {**ident_or["walker"], "run_url": ident_or["walker"]["run_url"] + "/attempts/9"}}
    expect(any("failed (rc=1" in p for p in verify(at9)), "owner_run: an attempt the API does not have -> deny")
    other = {**ident_or, "walker": {**ident_or["walker"], "run_url": "https://github.com/someone/else/actions/runs/36193694659"}}
    expect(any("not of this repository" in p for p in verify(other)), "owner_run: a run of another repository -> deny")
    expect(verify(ident_or, root=None) != [], "owner_run: no repository to check against -> deny")
    expect(any("no walked commit" in p for p in verify(ident_or, sha=None)), "owner_run: no walked commit -> deny")




    shutil.rmtree(tmp, ignore_errors=True)
    os.environ["PATH"] = old_path
    EVENTS = live_events

    if old_qa_gate_events is None:
        os.environ.pop("QA_GATE_EVENTS_FILE", None)
    else:
        os.environ["QA_GATE_EVENTS_FILE"] = old_qa_gate_events
    print("selftest: %d failure(s)" % len(fails))
    return 1 if fails else 0


_LAST_INPUT = None


def coarse_ship(text):
    """Last-resort ship heuristic used only when hook() itself crashes: a
    crash on a ship-looking command in an opted-in repo must DENY (fail
    closed), never allow. Coarser than the classifier on purpose."""
    return re.search(r"git\s+push|--mirror|--tags|refs/tags/|gh\s+pr\s+(merge|ready)|"
                     r"gh\s+release\s+(create|edit)|gh\s+workflow\s+run|--prod|--target[=\s]+production|"
                     r"vercel\s+(promote|redeploy|alias|rolling-release|rr)|/v\d+/deployments|/v\d+/projects/\S+/promote/|"
                     r"repos/\S+/(pulls/\d+/merge|merges|releases|git/refs|dispatches|contents/|deployments)|"
                     r"mergePullRequest|createCommitOnBranch|updateRef", text)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # hook mode must never crash loudly
        if len(sys.argv) > 1 and sys.argv[1] == "hook":
            # fail closed for ship-looking commands; everything else fails open
            raw = globals().get("_LAST_INPUT") or ""
            if raw and coarse_ship(raw):
                reason = "[qa-ship-gate] gate crashed while evaluating a ship command; treated as DENIED. Complete the .qa pipeline (%s)" % exc
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                         "permissionDecision": "deny",
                                                         "permissionDecisionReason": reason}}))
                sys.stderr.write(reason + "\n")
                sys.exit(2)
            sys.exit(0)
        print("fatal:", exc)
        sys.exit(1)
