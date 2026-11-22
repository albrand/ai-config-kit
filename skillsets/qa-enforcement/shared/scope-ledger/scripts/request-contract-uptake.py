#!/usr/bin/env python3
"""Count request-contract events for the standing line's kill rule.

Reads both places the logger writes: ~/.local/state/agent-quality/events.jsonl and
the sandbox fallback /tmp/agent-quality-<uid>/events.jsonl (see request-contract-log.py).
Threads under --exclude-tree (that root and every descendant, from bb's read-only
store) are reported separately, so an author's own probes do not count as uptake.

  request-contract-uptake.py --since 2026-10-01T12:31:47Z --exclude-tree thr_x
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

LOGGER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(LOGGER_DIR))


def event_files():
    import importlib.util
    spec = importlib.util.spec_from_file_location("rclog", LOGGER_DIR / "request-contract-log.py")
    rclog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rclog)
    return [Path.home() / ".local/state/agent-quality/events.jsonl", rclog.fallback_events_path()]


def parse_ts(value):
    """ISO 8601 with Z or an offset and optional fractions -> aware UTC datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        when = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(dt.timezone.utc)


def tree(root, db_path):
    """The root thread and all of its descendants, read from bb's store without writing."""
    if not root:
        return set()
    if not os.path.isfile(db_path):
        raise FileNotFoundError(db_path)
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    found, frontier = {root}, [root]
    while frontier:
        marks = ",".join("?" * len(frontier))
        rows = db.execute(f"select id from threads where parent_thread_id in ({marks})", frontier).fetchall()
        frontier = [r[0] for r in rows if r[0] not in found]
        found.update(frontier)
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", required=True, help="ISO UTC timestamp; events at or after it count")
    ap.add_argument("--exclude-tree", default="", help="root thread whose tree is reported separately")
    ap.add_argument("--bb-db", default=os.path.expanduser("~/.bb/bb.db"))
    args = ap.parse_args(argv)
    since = parse_ts(args.since)
    if since is None:
        ap.error("--since must be an ISO 8601 timestamp, e.g. 2026-10-01T12:31:47Z")
    try:
        excluded = tree(args.exclude_tree, args.bb_db)
    except (OSError, sqlite3.Error) as exc:
        print(f"request-contract uptake: cannot read bb's thread store ({type(exc).__name__}); "
              "pass --bb-db or drop --exclude-tree", file=sys.stderr)
        return 2
    seen, rows = set(), []
    per_file = {}
    for path in event_files():
        count = 0
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            when = parse_ts(event.get("ts"))
            if event.get("event") != "request-contract" or when is None or when < since:
                continue
            # Same row in both files counts once; distinct rows in the same second count separately.
            key = hashlib.sha256(json.dumps(event, sort_keys=True).encode("utf-8")).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            count += 1
            rows.append(event)
        per_file[str(path)] = count
    outside = sorted({e["thread_id"] for e in rows if e.get("thread_id") not in excluded})
    inside = sorted({e["thread_id"] for e in rows if e.get("thread_id") in excluded})
    print(json.dumps({"since": args.since, "files": per_file, "events": len(rows),
                      "threads_outside_tree": outside, "threads_inside_tree": inside}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
