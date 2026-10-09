#!/usr/bin/env python3
"""No idle child without work: every idle child of COORD either gets its next step or closes out.

User, 2026-10-09: "create watchers that does not allow an idle thread to not have work, they
should either have work or archive and remove its worktree if no longer needed".

Per live child of COORD, once its last turn ended IDLE_MIN ago and nothing is queued:
  1. nudge   - tell COORD (batched): give this child its next step, or let it close.
  2. closeout- still idle CLOSEOUT_MIN after the nudge: tell the child itself to continue
               any remaining authorized work, or close out: remove the worktrees it created
               (clean ones only, `git worktree remove` without --force), report to COORD,
               and end with the line CARD-CLOSED.
  3. archive - the child's last message says CARD-CLOSED, or it stayed silent ARCHIVE_MIN
               after the closeout ask: release it from the scope ledger, then archive it.
A child that works again (a newer turn) starts over. Worktrees are removed only by the child
that created them (hard rule); the watcher never deletes one.

Usage: idle-watch.py COORD [--loop SECONDS] [--dry-run]
"""
import json, os, sqlite3, subprocess, sys, time

HOME = os.path.expanduser("~")
STATE = f"{HOME}/.local/state/elyra-acp/idle-watch.json"
BB_DB = f"{HOME}/.bb/bb.db"
SCOPE_GATE = f"{HOME}/.agents/skills/scope-ledger/scripts/scope-gate.py"
MIGRATIONS = f"{HOME}/.local/state/elyra-acp/migrations.json"
IDLE_MIN, CLOSEOUT_MIN, ARCHIVE_MIN = 20, 40, 40
SKIP = {"thr_8bqtrnzyca"}  # GRAPHLANE-A runs on hsrpc-wsl, outside this Mac's fleet tooling

def bbj(*a):
    try:
        return json.loads(subprocess.run(["bb", *a, "--json"], capture_output=True, text=True).stdout)
    except Exception:
        return None

def bb(*a):
    return subprocess.run(["bb", *a], capture_output=True, text=True)

def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)

def last_turn(db, tid):
    """(ended_at_ms, last agent message text) for the child's latest completed turn."""
    row = db.execute("select max(created_at) from events where thread_id=? and type='turn/completed'", (tid,)).fetchone()
    ended = row[0] if row and row[0] else 0
    msg = db.execute("select data from events where thread_id=? and type='item/completed' and item_kind='agentMessage' "
                     "order by sequence desc limit 1", (tid,)).fetchone()
    text = ""
    if msg:
        try:
            d = json.loads(msg[0]); item = d.get("item") or d
            text = item.get("text") or json.dumps(item)[:4000]
        except Exception:
            text = msg[0][:4000]
    return ended, text

def closed_out(text):
    """The child closed only if its reply ENDS with the line CARD-CLOSED. A mention such as
    "No CARD-CLOSED declaration" is the opposite, and once archived a card that way."""
    lines = [l.strip().strip("*`_ ") for l in (text or "").strip().splitlines() if l.strip()]
    return bool(lines) and lines[-1] == "CARD-CLOSED"

def save(state):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE)

def tick(coord, dry):
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {}
    db = sqlite3.connect(f"file:{BB_DB}?mode=ro", uri=True)
    now = time.time() * 1000
    try:
        moved = {v["old"] for v in json.load(open(MIGRATIONS)).values() if v.get("done")}
    except Exception:
        moved = set()
    kids = [k for k in (bbj("thread", "list", "--parent-thread", coord) or []) if not k.get("archivedAt") and k["id"] not in SKIP]
    for k in [k for k in kids if k["id"] in moved]:
        # A moved original is history; its session now lives in an Elyra card. Never message
        # it (that would start bb's native provider as a second writer): release and re-archive.
        log(f"re-archive moved original {k['id']}")
        if not dry:
            subprocess.run(["python3", SCOPE_GATE, "release", coord, k["id"], "--evidence", "moved to Elyra; archived original"], capture_output=True, text=True)
            bb("thread", "archive", k["id"])
    # A child still on bb's native provider is migrate-children's: it moves it into Elyra
    # within ~2 min of going idle. Nudging it first would hand it work and block the move.
    kids = [k for k in kids if k["id"] not in moved and k["providerId"].startswith("acp-elyra")]
    to_nudge = []
    for k in kids:
        tid = k["id"]
        rec = state.get(tid, {})
        show = (bbj("thread", "show", tid) or {}).get("thread", {})
        ended, text = last_turn(db, tid)
        if show.get("status") != "idle" or show.get("queuedMessageCount") or show.get("activeBackgroundAgentCount"):
            state.pop(tid, None); continue
        if rec.get("turn") and ended > rec["turn"] and rec.get("stage") != "closeout":
            rec = {}  # worked again since the last step: start over
        idle_min = (now - ended) / 60000 if ended else 0
        title = (k.get("title") or "")[:70]
        stage = rec.get("stage")
        since = (now - rec.get("at", now)) / 60000
        closed = closed_out(text)
        if stage == "closeout" and ((closed and ended > rec["at"]) or (ended <= rec["at"] and since >= ARCHIVE_MIN)):
            why = "closed out by the child (CARD-CLOSED)" if closed else f"silent {int(since)} min after the closeout ask"
            log(f"archive {tid} {title}: {why}")
            if not dry:
                ev = f"idle-watch: idle child, coordinator nudged, {why}"
                subprocess.run(["python3", SCOPE_GATE, "release", coord, tid, "--evidence", ev], capture_output=True, text=True)
                bb("thread", "archive", tid)
                bb("thread", "tell", coord, f"[bb operator] idle-watch archived @thread:{tid} ({title}): {why}. It is released from the scope ledger. If it still had work, unarchive it and give it the next step.")
            state.pop(tid, None); continue
        if stage == "closeout" and ended > rec["at"]:
            # It answered without closing: it kept working, so it gets a fresh cycle.
            state.pop(tid, None); continue
        if stage == "nudged" and since >= CLOSEOUT_MIN and ended <= rec["at"]:
            log(f"closeout ask {tid} {title} (idle {int(idle_min)} min)")
            if not dry:
                bb("thread", "tell", tid,
                   f"[bb operator, idle-watch] You have been idle {int(idle_min)} min and the coordinator has not given you a next step. "
                   "If your card has remaining authorized work, continue it now. Your card is NOT finished while its PR is open and unmerged, a replay or review it owes has not passed, or a tool failure stopped you; in those cases continue, or report the exact blocker to the coordinator and do not close. If it is truly finished: remove the git worktrees you created for this card "
                   "(only clean ones, `git worktree remove` without --force; keep any that are dirty or hold `.keep-worktree`, and say why), "
                   f"report your final state to the coordinator @thread:{coord}, and end your reply with the line CARD-CLOSED.")
            state[tid] = {"stage": "closeout", "at": now, "turn": ended}; continue
        if not stage and idle_min >= IDLE_MIN:
            to_nudge.append((tid, title, int(idle_min)))
            state[tid] = {"stage": "nudged", "at": now, "turn": ended}
    if to_nudge:
        lines = "\n".join(f"- @thread:{t} {title} (idle {m} min)" for t, title, m in to_nudge)
        log("nudge coordinator: " + " ".join(t for t, _, _ in to_nudge))
        if not dry:
            bb("thread", "tell", coord,
               "[bb operator, idle-watch] These children are idle with nothing queued. The user wants no idle thread without work: "
               f"give each its next step now, or let it close out. In {CLOSEOUT_MIN} min I ask each still-idle one to finish or close "
               f"(it removes its own clean worktrees), then archive it.\n{lines}")
    if not dry:
        save(state)

def main():
    coord = sys.argv[1]
    loop = int(sys.argv[sys.argv.index("--loop") + 1]) if "--loop" in sys.argv else 0
    dry = "--dry-run" in sys.argv
    while True:
        try:
            tick(coord, dry)
        except Exception as e:
            log(f"ERROR {e}")
        if not loop:
            break
        time.sleep(loop)

if __name__ == "__main__":
    main()
