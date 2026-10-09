#!/usr/bin/env python3
"""Move an orchestrator's bb children onto the Elyra bridge, one idle child at a time.

For each live child of PARENT that is idle and runs locally:
  1. record a user-approved import (cwd -> native session) in the bridge config,
  2. stop the bb child (it is idle, so nothing is interrupted),
  3. spawn its replacement on acp-elyra-claude / acp-elyra-codex in the same
     directory, parented to PARENT, resuming the same native session,
  4. re-point the old child's own live children to the replacement,
  5. archive the stopped child, so nothing can wake it as a second writer,
  6. tell PARENT the old -> new mapping.
Every step is recorded in migrations.json, so a rerun skips finished children.

Usage: migrate-children.py PARENT HISTORY [--loop SECONDS] [--only ID ...]
"""
import json, os, re, subprocess, sys, time, collections

HOME = os.path.expanduser("~")
CONFIG = f"{HOME}/.config/elyra-acp/config.json"
LEDGER = f"{HOME}/.local/state/elyra-acp/migrations.json"
LOCAL_PREFIX = HOME + "/"
APPROVAL = "user, 2026-10-09: \"bring everything in, including codex childrens, all of them\""

def bb(*a, check=False):
    r = subprocess.run(["bb", *a], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"bb {' '.join(a[:3])} failed: {(r.stderr or r.stdout)[-400:]}")
    return r

def bbj(*a):
    try:
        return json.loads(bb(*a, "--json").stdout)
    except Exception:
        return None

def load(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default

def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)

def native_session(tid):
    s, seen = 0, collections.OrderedDict()
    while True:
        d = bbj("thread", "log", tid, "--limit", "200", "--after-seq", str(s))
        if not isinstance(d, list) or not d:
            break
        for e in d:
            data = e.get("data") or {}
            for k in ("providerSessionId", "providerThreadId"):
                v = data.get(k)
                if isinstance(v, str) and re.fullmatch(r"[0-9a-f-]{36}", v):
                    seen.pop(v, None); seen[v] = 1
        s = d[-1]["seq"]
    return list(seen)[-1] if seen else None

def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)

def migrate(child, parent, history, ledger):
    tid = child["id"]
    show = bbj("thread", "show", tid) or {}
    env = show.get("environment") or {}
    cwd = env.get("path")
    provider = child["providerId"]
    if provider not in ("claude-code", "codex"):
        return "skip: provider " + provider
    if not cwd or not cwd.startswith(LOCAL_PREFIX) or not os.path.isdir(cwd):
        return f"skip: not local ({cwd})"
    sid = native_session(tid)
    if not sid:
        return "skip: no native session id"
    target = "acp-elyra-claude" if provider == "claude-code" else "acp-elyra-codex"
    model = "claude-sonnet-5-5" if provider == "claude-code" else "gpt-6-luna"
    title = (child.get("title") or tid)
    rec = ledger.setdefault(tid, {"old": tid, "cwd": cwd, "nativeSessionId": sid, "provider": target})

    cfg = load(CONFIG, {})
    cfg.setdefault("imports", {})["cwd:" + cwd] = {"resumeSessionId": sid, "model": model, "fromBbThread": tid, "approvedBy": APPROVAL, "approvedAt": "2026-10-09"}
    save(CONFIG, cfg)

    if bbj("thread", "show", tid).get("thread", {}).get("status") != "idle":
        return "wait: became busy"
    bb("thread", "stop", tid, check=True)
    rec["stopped"] = time.time(); save(LEDGER, ledger)

    prompt = (f"[bb operator] This card has moved: it now runs in an Elyra terminal under the native {('Claude Code' if target.endswith('claude') else 'Codex')} CLI, "
              f"resuming your own session, so your context is intact. Your bb thread is now this one; the old thread {tid} is stopped and kept as history. "
              f"Your parent is still the coordinator, now @thread:{parent}. Carry on with your card exactly where you left off and report to the coordinator as before.")
    r = bbj("thread", "spawn", "--project", child.get("projectId") or show.get("thread", {}).get("projectId"), "--environment", cwd,
            "--provider", target, "--model", model, "--parent-thread", parent, "--title", f"{title[:90]} (Elyra)", "--prompt", prompt)
    new = (r or {}).get("id")
    if not new:
        rec["error"] = f"spawn failed: {r}"; save(LEDGER, ledger)
        return "FAIL spawn " + str(r)[:300]
    rec["new"] = new; save(LEDGER, ledger)

    for g in bbj("thread", "list", "--parent-thread", tid) or []:
        if not g.get("archivedAt"):
            bb("thread", "update", g["id"], "--parent-thread", new)
            rec.setdefault("grandchildren", []).append(g["id"])
    # Archive the stopped original: an archived thread rejects messages (409), so
    # nothing can wake it as a second writer on the session now in Elyra.
    # (Re-parenting it instead sends a notice that starts a turn on the parent.)
    bb("thread", "archive", tid)
    rec["done"] = time.time(); save(LEDGER, ledger)
    bb("thread", "tell", parent, f"[bb operator] Card moved to Elyra: @thread:{tid} is now @thread:{new} (same session, resumed in Elyra, provider {target}). "
       f"Send that card's follow-ups to {new}; {tid} is stopped history. Update PLAN.md.")
    return f"moved -> {new}"

def main():
    parent, history = sys.argv[1], sys.argv[2]
    loop = int(sys.argv[sys.argv.index("--loop") + 1]) if "--loop" in sys.argv else 0
    only = set(sys.argv[sys.argv.index("--only") + 1:]) if "--only" in sys.argv else None
    while True:
        ledger = load(LEDGER, {})
        kids = [k for k in (bbj("thread", "list", "--parent-thread", parent) or []) if not k.get("archivedAt")]
        pending = [k for k in kids if k["providerId"] in ("claude-code", "codex") and not ledger.get(k["id"], {}).get("done") and (not only or k["id"] in only)]
        for k in pending:
            if k["status"] != "idle":
                continue
            try:
                log(f"{k['id']} {k['providerId']}: {migrate(k, parent, history, ledger)}")
            except Exception as e:
                log(f"{k['id']}: ERROR {e}")
        remaining = [k["id"] for k in pending if not load(LEDGER, {}).get(k["id"], {}).get("done")]
        log(f"pending {len(remaining)}: {' '.join(remaining)}")
        if not loop or not remaining:
            break
        time.sleep(loop)

if __name__ == "__main__":
    main()
