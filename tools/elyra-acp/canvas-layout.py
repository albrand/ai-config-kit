#!/usr/bin/env python3
"""Lay out a fleet on the Elyra Canvas: the coordinator card on top, an orchestration line to each
live child card, children in a grid below, grouped by card prefix. The layout is written as a
control request that the coordinator's own bridge applies at its next turn (only a bridge, spawned
by bb outside any card, may drive cards).

Usage: canvas-layout.py COORD [--cols N] [--via THREAD] [--dry-run]
"""
import json, os, subprocess, sys

HOME = os.path.expanduser("~")
REG = f"{HOME}/.local/state/elyra-acp/sessions.json"
CONTROL = f"{HOME}/.local/state/elyra-acp/control"

def bbj(*a):
    try:
        return json.loads(subprocess.run(["bb", *a, "--json"], capture_output=True, text=True).stdout)
    except Exception:
        return None

def main():
    coord = sys.argv[1]
    cols = int(sys.argv[sys.argv.index("--cols") + 1]) if "--cols" in sys.argv else 4
    reg = json.load(open(REG))
    card = {}
    for r in reg.values():
        if r.get("bbThreadId") and r.get("cardTitle"):
            card[r["bbThreadId"]] = (r["cardTitle"], r.get("workspace"))
    if coord not in card:
        sys.exit(f"no Elyra card recorded for {coord}")
    ctitle, ws = card[coord]
    kids = [k for k in (bbj("thread", "list", "--parent-thread", coord) or []) if not k.get("archivedAt") and k["id"] in card]
    # Group related cards next to each other: REALDATA*, DEVPR*, HFIX*, ... by title prefix.
    kids.sort(key=lambda k: ((k.get("title") or "").split(":")[0].split("-")[0], k.get("title") or ""))
    W, H, GX, GY = 860, 520, 40, 60
    total_w = cols * W + (cols - 1) * GX
    ops = [["canvas", "move", ctitle, "--position", f"{(total_w - 1400) // 2},0", "--size", "1400,760", "--workspace", ws]]
    for i, k in enumerate(kids):
        t, kws = card[k["id"]]
        x, y = (i % cols) * (W + GX), 760 + 120 + (i // cols) * (H + GY)
        ops.append(["canvas", "move", t, "--position", f"{x},{y}", "--size", f"{W},{H}", "--workspace", kws or ws])
        ops.append(["canvas", "link", ctitle, t, "--workspace", ws])
    if "--dry-run" in sys.argv:
        print(json.dumps(ops, indent=1)); return
    os.makedirs(CONTROL, mode=0o700, exist_ok=True)
    via = sys.argv[sys.argv.index("--via") + 1] if "--via" in sys.argv else coord  # any bridge on current code can apply it
    path = f"{CONTROL}/{via}.json"
    try:
        prev = json.load(open(path))
    except Exception:
        prev = {}
    prev["canvas"] = ops
    with open(path, "w") as f:
        json.dump(prev, f)
    os.chmod(path, 0o600)
    print(f"queued {len(ops)} canvas ops for {via}'s bridge ({len(kids)} child cards)")

if __name__ == "__main__":
    main()
