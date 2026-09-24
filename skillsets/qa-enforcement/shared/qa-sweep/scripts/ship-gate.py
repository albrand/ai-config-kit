#!/usr/bin/env python3
"""QA ship gate: fail-closed push/PR/deploy gate for repos that opted in.

A repo opts in by committing `.qa/config.json`. From that moment the gate is
ALWAYS ON for that repo for ship commands (merges, pushes to protected
branches, production deploys, releases, tag pushes, workflow dispatch -- see
segment_ship_kind). It denies unless the whole
discover->cluster->plan->fix->re-walk pipeline is complete at exactly the SHA
being shipped:

  .qa/config.json     repo opt-in: personas, workflows, optional deployed_check
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
    os.path.expanduser("~/.agents/skills/verified-qa-e2e/scripts/qa-e2e-gate.mjs"),
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
                          "--target", "--discussion-category", "-R", "--repo"}
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


def resolve_run(root, sha, rd):
    """(dir, None) for the one run re-walked at `sha` (or at its parent under
    a .qa/-only head); (None, failure) when none or several match. A single
    candidate is returned as is, so the legacy flat layout and a lone run
    behave exactly as before."""
    cands = qa_run_dirs(root, sha, rd)
    if len(cands) == 1:
        return cands[0], None
    seen, matches = [], []
    for d in cands:
        try:
            walked = str(json.loads(rd["read"](d + "/rewalk.json")).get("sha") or "")
        except Exception:
            walked = ""
        seen.append("%s@%s" % (d, walked[:12] or "-"))
        if walked and (walked == sha or rewalk_parent_ok(root, sha, walked)):
            matches.append(d)
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


def check_rewalk(root, qa, rd, wf, sha, fails, stats):
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
        if not (rewalk_parent_ok(root, sha, doc["sha"])):
            fails.append(f"{rel} sha {str(doc['sha'])[:12]} != shipped sha {str(sha)[:12]}: re-walk at the new commit")
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


def check_e2e(qa, rd, cfg, fails):
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
    tmppath = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            tf.write(body)
            tmppath = tf.name
        proc = subprocess.run(["node", gate, "check", tmppath], capture_output=True, text=True, timeout=20)
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
            with urllib.request.urlopen(target, timeout=3) as resp:
                if resp.status not in (200, 204):
                    fails.append(f"deployed check HTTP {resp.status} for {target}")
        except Exception as exc:
            fails.append(f"deployed check failed for {target}: {exc}")
        return
    cmd = dc.get("command")
    if cmd:
        try:
            proc = subprocess.run([cmd], shell=True, cwd=root, capture_output=True, text=True,
                                  timeout=dc.get("timeout_s", 3))
            if proc.returncode != 0:
                fails.append(f"deployed check exited {proc.returncode}: {(proc.stdout or proc.stderr).strip()[:200]}")
        except subprocess.TimeoutExpired:
            fails.append("deployed check timed out")
        except Exception as exc:
            fails.append(f"deployed check could not run: {exc}")
    else:
        fails.append(".qa/config.json deployed_check needs a url template or a command")


def check_all(root, sha=None):
    """Return (ok, failures, stats, cfg). Never raises. Artifacts are read
    from the shipped commit's tree when sha is resolvable (v3)."""
    fails, stats = [], {"rows_total": 0, "open_rows": 0, "predates_count": 0, "clusters": 0,
                        "rewalk_steps": 0, "rewalk_failed": 0}
    cfg = None
    try:
        if not sha:
            sha = run_git(root, "rev-parse", "HEAD").stdout.strip() or None
        rd = qa_reader(root, sha)
        cfg = check_config(root, rd, fails)
        qa, err = resolve_run(root, sha, rd)
        if err:
            fails.append(err)
            return (False, fails, stats, cfg)
        wf = check_workflow(qa, rd, cfg, fails)
        rows = check_inventory(qa, rd, fails, stats)
        clusters = check_clusters(qa, rd, rows, fails, stats)
        check_plan(qa, rd, clusters, fails)
        check_rewalk(root, qa, rd, wf, sha, fails, stats)
        check_e2e(qa, rd, cfg, fails)
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


def workflow_commit(root, toks):
    """Commit `gh workflow run` dispatches on: --ref/-r as the remote knows
    it, else the remote default branch (GitHub's default), else HEAD."""
    _, vals = _positionals(toks, GH_WORKFLOW_VALUE_FLAGS)
    ref = vals.get("--ref") or vals.get("-r")
    if ref:
        return remote_commit(root, ref.replace("refs/heads/", "", 1)) or head_commit(root)
    return remote_commit(root, default_branch(root)) or head_commit(root)


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
    urls = [t for t in toks if DEPLOY_CREATE_RE.search(t) or PROMOTE_API_RE.search(t)]
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
        return False
    if any(PROMOTE_API_RE.search(u) for u in urls):
        return True
    texts.append(command)
    return any(PROD_TARGET_RE.search(t) for t in texts)


def _vercel_prod_flag(seg):
    """`--prod`, or `--target production` / `--target=production`."""
    for i, t in enumerate(seg):
        if t == "--prod" or t == "--target=production":
            return True
        if t == "--target" and i + 1 < len(seg) and seg[i + 1] == "production":
            return True
    return False


def segment_ship(seg, root, cfg, command="", cwd=None):
    """(kind, shas) for one unwrapped shell segment. kind: "merge" | "push" |
    "deploy" | None. shas: the commits this segment ships, resolved locally,
    so a tag pointing at an unwalked commit cannot pass on a walked HEAD.
    For merges the caller resolves the PR head (shas empty here)."""
    if not seg:
        return None, []
    head = seg[0]
    cwd = cwd or root
    if head == "git":
        if git_subcommand(seg) != "push":
            return None, []
        mode, flags, pairs = push_refspecs(seg)
        if mode == "all":
            return "push", [head_commit(root)]
        prot = protected_refs(root, cfg)
        kind, shas = None, []
        if any(f.split("=")[0] in TAG_PUSH_FLAGS for f in flags):
            # --tags/--follow-tags: which tags are new is only known to the
            # remote; the hook checks HEAD, the pre-push layer checks each
            # pushed tag exactly (git lists them on stdin)
            kind, shas = "deploy", [head_commit(root)]
        if not pairs:
            up = upstream_branch(root)
            if up and normalize_ref(up) in prot:
                return "push", shas + [head_commit(root)]
            return kind, shas
        for src, dst in pairs:
            dst_branch = current_branch(root) if dst in ("HEAD", "@") else normalize_ref(dst)
            if dst_branch in prot:
                kind = "push"
                shas.append(resolve_commit(root, src) or head_commit(root))
                continue
            t = tag_ref(root, src) or tag_ref(root, dst if dst.startswith("refs/tags/") else "")
            if t:
                kind = kind or "deploy"
                shas.append(resolve_commit(root, t) or head_commit(root))
        return kind, shas
    if head == "gh" and len(seg) > 2:
        if seg[1] == "pr" and seg[2] in ("merge", "ready"):
            return "merge", []
        if seg[1] == "release" and seg[2] == "create":
            return "deploy", [release_commit(root, seg[3:])]
        if seg[1] == "workflow" and seg[2] == "run":
            # ANY dispatch is shipping. Deploy workflows run exactly this way
            # (seahaven deploy.yaml is workflow_dispatch dev/staging/prod); a
            # reliable workflow-name -> file -> jobs mapping needs GitHub API
            # round trips inside a hook, and a missed deploy workflow is an
            # ungated production deploy while a false positive only asks for
            # a completed .qa pipeline on a rare manual command.
            return "deploy", [workflow_commit(root, seg[3:])]
        return None, []
    if head == "vercel":
        sub = seg[1] if len(seg) > 1 else ""
        if sub == "api":
            return ("deploy", [head_commit(root)]) if api_deploy_post(seg, command, cwd) else (None, [])
        # `vercel rollback` stays free: it restores an already-shipped
        # deployment, and gating incident recovery on a fresh walk is wrong
        if _vercel_prod_flag(seg) or sub in ("promote", "redeploy"):
            return "deploy", [head_commit(root)]
        return None, []
    if head == "netlify" and "deploy" in seg[1:3] and "--prod" in seg:
        return "deploy", [head_commit(root)]
    if head in ("fly", "flyctl") and len(seg) > 1 and seg[1] == "deploy":
        return "deploy", [head_commit(root)]
    if head in ("curl", "curl.exe") and api_deploy_post(seg, command, cwd):
        return "deploy", [head_commit(root)]
    return None, []


def segment_ship_kind(seg, root, cfg):
    """"merge" | "push" | "deploy" for one shell segment, else None."""
    return segment_ship(seg, root, cfg)[0]


def ship_plan(command, root, cfg, cwd=None):
    """(kind, shas): the highest-stakes ship kind anywhere in the command and
    every commit its non-merge segments ship. A `ship_commands` match adds
    HEAD. Merges get their PR head from the caller."""
    kinds, shas = [], []
    for seg in command_segments(command):
        k, s = segment_ship(seg, root, cfg, command, cwd)
        if k:
            kinds.append(k)
            shas += [x for x in s if x and x not in shas]
    try:
        if cfg and isinstance(cfg.get("ship_commands"), list):
            if any(re.search(str(p), command) for p in cfg["ship_commands"]):
                kinds.append("extra")
                h = head_commit(root)
                if h and h not in shas:
                    shas.append(h)
    except Exception:
        pass
    if "merge" in kinds:
        return "merge", shas   # needs PR-head freshness, the stricter sha rule
    if "push" in kinds:
        return "push", shas
    return (kinds[0] if kinds else None), shas


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


def hook(raw=None):
    """PreToolUse adapter: deny ship commands in opted-in repos with an open pipeline."""
    global _LAST_INPUT
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
        return 0
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
        shas = list(plans[root][1])
        if kind == "merge" and merge_args is not None:
            shas.insert(0, pr_head_sha(root, merge_args) or head_commit(root))
        if not shas:
            shas = [head_commit(root)]
        ok, fails, stats = True, [], {"rows_total": 0, "clusters": 0, "open_rows": 0}
        for sha in shas:
            o, f, s, _ = check_all(root, sha or None)
            ok = ok and o
            fails += ["[%s] %s" % ((sha or "HEAD")[:12], x) for x in f] if len(shas) > 1 else f
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
        ok, fails, stats, _ = check_all(root, sha)
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

    shutil.rmtree(tmp, ignore_errors=True)
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
                     r"gh\s+release\s+create|gh\s+workflow\s+run|--prod|--target[=\s]+production|"
                     r"vercel\s+(promote|redeploy)|/v\d+/deployments|/v\d+/projects/\S+/promote/", text)


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
