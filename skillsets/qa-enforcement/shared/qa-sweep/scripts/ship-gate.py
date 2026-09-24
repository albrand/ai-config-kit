#!/usr/bin/env python3
"""QA ship gate: fail-closed push/PR/deploy gate for repos that opted in.

A repo opts in by committing `.qa/config.json`. From that moment the gate is
ALWAYS ON for that repo for ship commands (git push, gh pr create/merge/ready,
bb fleet validate, vercel/netlify/fly deploy). It denies unless the whole
discover->cluster->plan->fix->re-walk pipeline is complete at exactly the SHA
being shipped:

  .qa/config.json     repo opt-in: personas, workflows, optional deployed_check
  .qa/workflow.json   the task's scope: persona, entry, outcome, steps, target
  .qa/inventory.jsonl one row per defect found on the full walk (no fixing yet)
  .qa/clusters.json   row -> cluster, repro command, repro_failed_once: true
  .qa/plan.md         one plan covering every cluster id
  .qa/rewalk.json     verdict per workflow step, at the SHA being shipped
  .qa/evidence.json   qa-e2e-gate.mjs packet (claim_e2e_complete)

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
EVENTS = os.path.join(HOME, ".local", "state", "agent-quality", "events.jsonl")
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

SHIP_PATTERNS = [
    r"\bgit\s+[^|;&]*\bpush\b",
    r"\bgh\s+pr\s+(create|merge|ready)\b",
    r"\bbh\s+fleet\s+validate\b",
    r"\bb\s+fleet\s+validate\b",
    r"\bvercel\b[^|;&]*\b(deploy\b|--prod\b)",
    r"\bnetlify\s+deploy\b",
    r"\bfly(\.io)?\s+deploy\b",
    r"\bflyctl\s+deploy\b",
]

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


def check_config(root, fails):
    path = os.path.join(root, ".qa", "config.json")
    if not os.path.isfile(path):
        fails.append(".qa/config.json missing (repo opt-in)")
        return None
    try:
        cfg = load_json(path)
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


def check_workflow(root, cfg, fails):
    path = os.path.join(root, ".qa", "workflow.json")
    if not os.path.isfile(path):
        fails.append(".qa/workflow.json missing (P0 scope: persona, entry, outcome, steps, target)")
        return None
    try:
        wf = load_json(path)
    except Exception as exc:
        fails.append(f".qa/workflow.json unparseable: {exc}")
        return None
    if not (wf.get("persona") or wf.get("personas")):
        fails.append("workflow.json: persona missing")
    for key in ("entry", "outcome"):
        if not wf.get(key):
            fails.append(f"workflow.json: {key} missing")
    steps = wf.get("steps")
    if not (isinstance(steps, list) and steps and all(isinstance(s, str) and s for s in steps)):
        fails.append("workflow.json: steps must be a non-empty list of step names")
    target = wf.get("target")
    if not (isinstance(target, dict) and target.get("url") and target.get("sha")):
        fails.append("workflow.json: target needs url and sha")
    if cfg and isinstance(cfg.get("workflows"), list):
        names = {w.get("name") for w in cfg["workflows"] if isinstance(w, dict)}
        if wf.get("workflow") and names and wf["workflow"] not in names:
            fails.append(f"workflow.json: '{wf['workflow']}' is not a workflow named in .qa/config.json")
    return wf


def check_inventory(root, fails, stats):
    path = os.path.join(root, ".qa", "inventory.jsonl")
    if not os.path.isfile(path):
        fails.append(".qa/inventory.jsonl missing (P1 full-walk inventory)")
        return []
    rows = []
    try:
        for i, ln in enumerate(read_lines(path), 1):
            try:
                row = json.loads(ln)
            except Exception as exc:
                fails.append(f"inventory.jsonl line {i} unparseable: {exc}")
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
        fails.append(f".qa/inventory.jsonl unreadable: {exc}")
        return []
    stats["rows_total"] = len(rows)
    stats["open_rows"] = sum(1 for r in rows if r["status"] == "open")
    stats["predates_count"] = sum(1 for r in rows if r.get("predates_change") is True)
    return rows


def check_clusters(root, rows, fails, stats):
    path = os.path.join(root, ".qa", "clusters.json")
    if not os.path.isfile(path):
        fails.append(".qa/clusters.json missing (P2 clustering with red repro)")
        return None
    try:
        doc = load_json(path)
        clusters = doc.get("clusters", [])
        mapping = doc.get("mapping", {})
    except Exception as exc:
        fails.append(f".qa/clusters.json unparseable: {exc}")
        return None
    ids = set()
    for cl in clusters if isinstance(clusters, list) else []:
        if not (isinstance(cl, dict) and cl.get("id")):
            fails.append("clusters.json: every cluster needs an id")
            continue
        ids.add(cl["id"])
        if not cl.get("hypothesis"):
            fails.append(f"cluster {cl['id']}: hypothesis missing (root cause, not symptom)")
        if not cl.get("repro_command"):
            fails.append(f"cluster {cl['id']}: repro_command missing")
        if cl.get("repro_failed_once") is not True:
            fails.append(f"cluster {cl['id']}: repro_failed_once must be true (make it fail once before trusting it)")
    if not isinstance(mapping, dict):
        fails.append("clusters.json: mapping must be an object of row-id -> cluster-id")
        mapping = {}
    for row in rows:
        cid = mapping.get(row["id"])
        if not cid:
            fails.append(f"inventory row {row['id']} is not mapped to a cluster")
        elif cid not in ids:
            fails.append(f"inventory row {row['id']} maps to unknown cluster '{cid}'")
    stats["clusters"] = len(ids)
    return doc


def check_plan(root, clusters, fails):
    path = os.path.join(root, ".qa", "plan.md")
    if not os.path.isfile(path):
        fails.append(".qa/plan.md missing (P3 one plan for every cluster)")
        return False
    try:
        text = open(path, encoding="utf-8").read()
    except Exception as exc:
        fails.append(f".qa/plan.md unreadable: {exc}")
        return False
    for cl in (clusters or {}).get("clusters", []) if isinstance(clusters, dict) else []:
        if isinstance(cl, dict) and cl.get("id") and cl["id"] not in text:
            fails.append(f"plan.md does not cover cluster {cl['id']}")
    return True


def rewalk_parent_ok(root, head, walked):
    """True when `head` is exactly one .qa/-only commit on top of `walked`."""
    parent = run_git(root, "rev-parse", "HEAD~1").stdout.strip()
    if not parent or parent != walked:
        return False
    diff = run_git(root, "diff", "--name-only", "HEAD~1", "HEAD").stdout.split()
    return bool(diff) and all(d == ".qa" or d.startswith(".qa/") for d in diff)


def check_rewalk(root, wf, sha, fails, stats):
    path = os.path.join(root, ".qa", "rewalk.json")
    if not os.path.isfile(path):
        fails.append(".qa/rewalk.json missing (P5 re-walk of the whole workflow)")
        return None
    try:
        doc = load_json(path)
    except Exception as exc:
        fails.append(f".qa/rewalk.json unparseable: {exc}")
        return None
    if not doc.get("sha"):
        fails.append("rewalk.json: sha missing")
    elif sha and doc["sha"] != sha:
        # The .qa artifacts are committed after the walk, so the pushed HEAD may
        # be exactly one commit on top of the walked code, touching only .qa/.
        if not (rewalk_parent_ok(root, sha, doc["sha"])):
            fails.append(f"rewalk.json sha {str(doc['sha'])[:12]} != shipped sha {str(sha)[:12]}: re-walk at the new commit")
    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        fails.append("rewalk.json: steps must be a non-empty list")
    else:
        for st in steps:
            if not isinstance(st, dict) or not st.get("step"):
                fails.append("rewalk.json: every step needs a step name")
                continue
            if st.get("verdict") != "PASS":
                fails.append(f"rewalk step '{st['step']}': verdict {st.get('verdict')!r} (only PASS clears the gate)")
            if not st.get("evidence"):
                fails.append(f"rewalk step '{st['step']}': evidence missing")
        if isinstance(wf, dict) and isinstance(wf.get("steps"), list):
            walked = {st.get("step") for st in steps if isinstance(st, dict)}
            for name in wf["steps"]:
                if name not in walked:
                    fails.append(f"rewalk.json: workflow step '{name}' has no verdict")
        stats["rewalk_steps"] = len(steps)
        stats["rewalk_failed"] = sum(1 for st in steps if isinstance(st, dict) and st.get("verdict") != "PASS")
    return doc


def check_e2e(root, cfg, fails):
    path = os.path.join(root, ".qa", "evidence.json")
    gate = (cfg or {}).get("e2e_evidence_gate") or E2E_GATE
    if not os.path.isfile(path):
        fails.append(".qa/evidence.json missing (qa-e2e-gate packet, claim_e2e_complete)")
        return
    if not os.path.isfile(gate):
        fails.append(f"qa-e2e-gate.mjs not found at {gate}")
        return
    try:
        proc = subprocess.run(["node", gate, "check", path], capture_output=True, text=True, timeout=20)
    except Exception as exc:
        fails.append(f"qa-e2e-gate.mjs could not run: {exc}")
        return
    # Require a parsed {"ok": true} verdict. rc=0 alone is NOT a pass: the gate
    # script self-check can no-op (empty output, exit 0) when invoked through a
    # path whose realpath differs (symlinked skill dir), and a silent no-op must
    # never read as green (caught 2026-09-24 while testing the hook path).
    result, detail = None, ""
    try:  # the gate prints one JSON document (pretty-printed); parse it whole
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
    """Return (ok, failures, stats, cfg). Never raises."""
    fails, stats = [], {"rows_total": 0, "open_rows": 0, "predates_count": 0, "clusters": 0,
                        "rewalk_steps": 0, "rewalk_failed": 0}
    cfg = None
    try:
        cfg = check_config(root, fails)
        if not sha:
            sha = run_git(root, "rev-parse", "HEAD").stdout.strip()
        wf = check_workflow(root, cfg, fails)
        rows = check_inventory(root, fails, stats)
        clusters = check_clusters(root, rows, fails, stats)
        check_plan(root, clusters, fails)
        check_rewalk(root, wf, sha, fails, stats)
        check_e2e(root, cfg, fails)
        check_deployed(root, cfg, sha, fails)
    except Exception as exc:  # fail closed on anything unexpected
        fails.append(f"gate internal error: {exc}")
    return (not fails), fails, stats, cfg


def is_ship(command, cfg=None):
    pats = list(SHIP_PATTERNS)
    try:
        if cfg and isinstance(cfg.get("ship_commands"), list):
            pats += [str(p) for p in cfg["ship_commands"]]
    except Exception:
        pass
    return any(re.search(p, command) for p in pats)


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
    if i >= n or s[i] in ";&|":
        return None, i
    out = []
    while i < n:
        c = s[i]
        if c in " \t;&|":
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


def hook():
    """PreToolUse adapter: deny ship commands in opted-in repos with an open pipeline."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
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
    if not is_ship(command) and not any(is_ship(command, c) for c in cfgs.values()):
        return 0
    prov = derive_provider(payload)
    sections, denied = [], []
    for root in targets:
        cfg = cfgs[root]
        ok, fails, stats, _ = check_all(root)
        if ok:
            emit("gate_passed", root, data={"rows_total": stats["rows_total"], "clusters": stats["clusters"]},
                 provider=prov)
            continue
        denied.append(root)
        emit("gate_denied", root, data={"reason": (fails[0] if fails else "")[:200], "open_rows": stats["open_rows"]},
             provider=prov)
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
    path = os.path.join(root, ".qa", "inventory.jsonl")
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
    cfg = check_config(root, fails)
    check_workflow(root, cfg, fails)
    rows = check_inventory(root, fails, stats)
    clusters = check_clusters(root, rows, fails, stats)
    check_plan(root, clusters, fails)
    print("PASS" if not fails else "DENY")
    for f in fails:
        print("  -", f)
    return 0 if not fails else 1


def cmd_record(args):
    kind = args.get("kind")
    root = repo_root(os.getcwd())
    sha = run_git(root, "rev-parse", "HEAD").stdout.strip() if root else ""
    if kind == "inventory-closed":
        fails, stats = [], {"rows_total": 0, "open_rows": 0, "predates_count": 0}
        check_inventory(root, fails, stats)
        hard = [f for f in fails if "still OPEN" in f or "missing" in f or "unparseable" in f or "unreadable" in f]
        if hard:
            print("refuse: inventory not closed:\n  - " + "\n  - ".join(hard))
            return 1
        emit("inventory_closed", root, sha, {"rows": stats["rows_total"], "predates_count": stats["predates_count"]})
        print("recorded inventory_closed rows=%d predates=%d" % (stats["rows_total"], stats["predates_count"]))
        return 0
    if kind == "rewalk":
        fails, stats = [], {"rewalk_steps": 0, "rewalk_failed": 0}
        check_rewalk(root, None, sha, fails, stats)
        if stats["rewalk_steps"] == 0 or any("verdict" in f or "no verdict" in f for f in fails):
            print("refuse: rewalk not green:\n  - " + "\n  - ".join(fails))
            return 1
        emit("rewalk", root, sha, {"steps": stats["rewalk_steps"], "failed": stats["rewalk_failed"]})
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
        return hook()
    if cmd == "stop":
        return stop()
    if cmd == "check":
        return cmd_check(rest)
    if cmd == "clusters":
        return cmd_clusters(rest)
    if cmd == "record":
        rest["kind"] = argv[1] if len(argv) > 1 else ""
        return cmd_record(rest)
    if cmd == "selftest":
        return selftest()
    print(__doc__)
    return 2


def selftest():
    """Prove each deny/allow path on scratch repos. A check that cannot go red proves nothing."""
    import shutil
    tmp = tempfile.mkdtemp(prefix="qa-gate-selftest-")
    fails = []

    def expect(cond, name):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    def sh(cmd, cwd=None, inp=""):
        return subprocess.run(cmd, shell=True, cwd=cwd, input=inp, capture_output=True, text=True)

    def mkrepo(name, optin=True):
        r = os.path.join(tmp, name)
        os.makedirs(r)
        sh("git init -q && git config user.email t@t && git config user.name t", cwd=r)
        if optin:
            os.makedirs(os.path.join(r, ".qa"))
            with open(os.path.join(r, ".qa", "config.json"), "w") as fh:
                json.dump({"schema_version": 1, "personas": ["admin"], "workflows": [{"name": "w1"}]}, fh)
        return r

    def hookrun(root, command):
        payload = json.dumps({"session_id": "selftest", "tool_name": "Bash",
                              "tool_input": {"command": command}, "cwd": root})
        return sh('python3 "%s" hook' % os.path.abspath(__file__), cwd=root, inp=payload)

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
         "tool_input": {"command": 'git --work-tree="%s" -C %s push origin main' % (spaced, spaced)}, "cwd": foreign}))
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
    p = sh('python3 "%s" record inventory-closed' % GATE, cwd=r1)
    expect(p.returncode == 0 and "rows=2" in p.stdout, "record inventory-closed accepted")

    cfgp = os.path.join(qa, "config.json")
    cfg = json.load(open(cfgp))
    cfg["deployed_check"] = {"command": "false"}
    json.dump(cfg, open(cfgp, "w"))
    p = hookrun(r1, "git push origin main")
    expect(p.returncode == 2 and "deployed check" in p.stderr, "failing deployed check denies ship")
    cfg["deployed_check"] = {"command": "true"}
    json.dump(cfg, open(cfgp, "w"))
    sha2 = sh("git rev-parse HEAD", cwd=r1).stdout.strip()
    doc = json.load(open(os.path.join(qa, "rewalk.json")))
    doc["sha"] = sha2
    json.dump(doc, open(os.path.join(qa, "rewalk.json"), "w"))
    p = hookrun(r1, "git push origin main")
    expect(p.returncode == 0, "green deployed check allows ship [%s]" % p.stderr.strip()[:160])

    p = sh('python3 "%s" hook' % GATE, cwd=tmp, inp=json.dumps(
        {"session_id": "selftest", "tool_name": "Bash",
         "tool_input": {"command": "git -C %s push origin main" % r1}, "cwd": tmp}))
    expect(p.returncode == 0, "git -C push allowed once pipeline complete [%s]" % p.stderr.strip()[:120])
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
    p = hookrun(r1, "git push origin main")
    expect(p.returncode == 2 and "no verdict" in p.stderr, "silent no-op e2e gate is a deny")
    del cfg["e2e_evidence_gate"]
    json.dump(cfg, open(cfgp, "w"))
    p = hookrun(r1, "git push origin main")
    expect("no verdict" not in p.stderr, "real gate verdict restored after removing the noop override")

    shutil.rmtree(tmp, ignore_errors=True)
    print("selftest: %d failure(s)" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # hook mode must never crash loudly
        if len(sys.argv) > 1 and sys.argv[1] == "hook":
            sys.exit(0)
        print("fatal:", exc)
        sys.exit(1)
