#!/usr/bin/env python3
"""Decision ledger: gated decisions and what happened to them, append-only.

This is the "outcome history" confidence source of the typed-decisions
contract. Without it every threshold is a human guess; with it a threshold can
be checked against how often decisions at that tier were later overturned.

Events are JSON lines in one file, never rewritten:
  {"type": "init", ...}
  {"type": "decision", "id", "ts", "point", "answer", "space", "source", "tier",
   "measurement", "ref", "agent"}
  {"type": "outcome", "id", "ts", "outcome": "held"|"overturned", "evidence"}

Commands:
  record   --point P --answer A [--space "a|b|c"] --source S [--tier T]
           --measurement TEXT [--ref TEXT] [--agent TEXT]      -> prints id
  resolve  ID | --ref TEXT [--point P]  --outcome held|overturned --evidence TEXT
           (--ref finds the one unresolved decision whose ref contains TEXT)
  import-hermes [--db PATH] [--window-days 7]
           read the fleet plugin's stored Hermes verdicts (read-only) as
           decisions. An `accept` with no non-accept verdict on the same topic
           within the window resolves `held` (a labelled proxy). An `accept`
           followed by an objection is only FLAGGED: stored verdicts cannot
           tell a real overturn from new work under a reused topic, so a
           person or agent resolves it with evidence.
  report   [--point P] [--min 20]
  check    [--stale-days 14]   ledger parses, outcomes reference decisions,
                               and it is actually in use
  --falsify                    prove check/record refuse what they must

Ledger: $DECISION_LEDGER or ~/.local/state/agent-decisions/ledger.jsonl.
Only the fields above are stored: never prompts, transcripts, env values or
secrets. Free-text fields are capped and screened.
"""
import argparse
import datetime as dt
import fcntl
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import uuid

SOURCES = ("agreement", "check", "history", "reviewer", "none")
TIERS = ("high", "medium", "low")
OUTCOMES = ("held", "overturned")
MAX_TEXT = 300
SECRET = re.compile(r"(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|-----BEGIN)")
SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class Refused(Exception):
    """A record that breaks the contract. Exit 2, never written."""


def ledger_path():
    return os.environ.get("DECISION_LEDGER") or os.path.expanduser(
        "~/.local/state/agent-decisions/ledger.jsonl")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def parse_ts(s):
    return dt.datetime.fromisoformat(s)


def clean(text, field):
    text = (text or "").strip()
    if len(text) > MAX_TEXT:
        raise Refused(f"{field} longer than {MAX_TEXT} chars; store a pointer, not the content")
    if SECRET.search(text):
        raise Refused(f"{field} looks like it contains a secret")
    return text


def read_events(path=None):
    path = path or ledger_path()
    events, bad = [], []
    if not os.path.exists(path):
        return events, bad
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                bad.append(n)
    return events, bad


def append(events):
    path = ledger_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fresh = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            if fresh:
                fh.write(json.dumps({"type": "init", "ts": now_iso()}) + "\n")
            stamp = now_iso()
            for ev in events:
                ev.setdefault("recorded", stamp)
                fh.write(json.dumps(ev, sort_keys=True) + "\n")
            fh.flush()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def build_decision(point, answer, space, source, tier, measurement, ref="", agent="", id_=None, ts=None):
    if not SLUG.match(point or ""):
        raise Refused("point must be a short lowercase slug, e.g. test-verdict")
    options = [s.strip() for s in space.split("|")] if space else None
    if options is not None and answer not in options:
        raise Refused(f"answer {answer!r} is outside the declared space {options}: a failed decision, not a record")
    if source not in SOURCES:
        raise Refused(f"source must be one of {SOURCES}")
    if tier is not None and tier not in TIERS:
        raise Refused(f"tier must be one of {TIERS}")
    if source == "none" and tier in ("high", "medium"):
        raise Refused("confidence with no measured source is a self-report; it can only be tier low")
    measurement = clean(measurement, "measurement")
    if source != "none" and not measurement:
        raise Refused("a confidence source needs its measurement (command, result, count)")
    return {"type": "decision", "id": id_ or uuid.uuid4().hex[:12], "ts": ts or now_iso(),
            "point": point, "answer": answer, "space": options, "source": source, "tier": tier,
            "measurement": measurement, "ref": clean(ref, "ref"), "agent": clean(agent, "agent")}


def index(events):
    decisions, outcomes = {}, {}
    for ev in events:
        if ev.get("type") == "decision":
            decisions[ev["id"]] = ev
        elif ev.get("type") == "outcome":
            outcomes[ev["id"]] = ev
    return decisions, outcomes


def cmd_record(a):
    ev = build_decision(a.point, a.answer, a.space, a.source, a.tier, a.measurement, a.ref, a.agent)
    append([ev])
    print(ev["id"])


def cmd_resolve(a):
    if a.outcome not in OUTCOMES:
        raise Refused(f"outcome must be one of {OUTCOMES}")
    decisions, outcomes = index(read_events()[0])
    if not a.id:
        # A later session rarely knows the id; it knows the PR, SHA or ticket.
        if not a.ref:
            raise Refused("give a decision id, or --ref (and optionally --point) to find it")
        hits = [d for d in decisions.values() if d["id"] not in outcomes
                and a.ref in d.get("ref", "") and (not a.point or d["point"] == a.point)]
        if len(hits) != 1:
            listing = ", ".join(f"{d['id']} ({d['point']}={d['answer']}, ref {d['ref']})" for d in hits[:8])
            raise Refused(f"--ref matched {len(hits)} unresolved decision(s); need exactly one. {listing}")
        a.id = hits[0]["id"]
    if a.id not in decisions:
        raise Refused(f"no decision with id {a.id}")
    if a.id in outcomes:
        raise Refused(f"{a.id} already resolved as {outcomes[a.id]['outcome']}; outcomes are append-once")
    evidence = clean(a.evidence, "evidence")
    if not evidence:
        raise Refused("an outcome needs its evidence")
    append([{"type": "outcome", "id": a.id, "ts": now_iso(), "outcome": a.outcome, "evidence": evidence}])
    print(f"{a.id} {a.outcome}")


def default_fleet_db():
    return os.path.expanduser("~/.bb/plugins/fleet/data.db")


def cmd_import_hermes(a):
    db = a.db or default_fleet_db()
    if not os.path.exists(db):
        print(f"import-hermes: n/a here (no fleet database at {db})")
        return
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("SELECT id, at, topic, verdict, machine FROM verdicts ORDER BY at, id").fetchall()
    con.close()
    decisions, outcomes = index(read_events()[0])
    new = []
    for vid, at, topic, verdict, machine in rows:
        did = f"hermes-{vid}"
        if did in decisions or verdict not in ("accept", "revise", "reject"):
            continue
        ts = dt.datetime.fromtimestamp(at / 1000, dt.timezone.utc).replace(microsecond=0).isoformat()
        ev = build_decision("hermes-review", verdict, "accept|revise|reject", "reviewer", None,
                            "independent Hermes verdict via bb fleet validate",
                            ref=(topic or "")[:MAX_TEXT], agent=(machine or "hermes")[:MAX_TEXT],
                            id_=did, ts=ts)
        new.append(ev)
        decisions[did] = ev
    window = dt.timedelta(days=a.window_days)
    now = dt.datetime.now(dt.timezone.utc)
    by_topic = {}
    for vid, at, topic, verdict, _ in rows:
        by_topic.setdefault(topic or "", []).append((at, vid, verdict))
    # An objection after an accept is NOT written as an overturn. Reading the
    # 16 such cases on 2026-09-21 showed the stored verdicts cannot tell a real
    # overturn ("NOT validated before I reported it") from new work filed under
    # a reused topic (the next promotion hop, a delta re-review) -- and the
    # claim text does not separate them either. So those are flagged for a
    # person or agent to resolve with evidence; only the silent case resolves.
    flagged = flags(read_events()[0])
    resolved, flags_new = [], []
    for topic, seq in by_topic.items():
        if not topic:
            continue  # no topic, no way to follow the decision forward
        for i, (at, vid, verdict) in enumerate(seq):
            did = f"hermes-{vid}"
            if verdict != "accept" or did in outcomes:
                continue
            t = dt.datetime.fromtimestamp(at / 1000, dt.timezone.utc)
            later = [(a2, v2, vd2) for a2, v2, vd2 in seq[i + 1:]
                     if dt.datetime.fromtimestamp(a2 / 1000, dt.timezone.utc) - t <= window]
            objection = next((x for x in later if x[2] != "accept"), None)
            if objection:
                if did not in flagged:
                    when = dt.datetime.fromtimestamp(objection[0] / 1000, dt.timezone.utc).date()
                    flags_new.append({"type": "flag", "id": did, "ts": now_iso(),
                                      "reason": f"{objection[2]} on the same topic {when} (hermes-{objection[1]}) "
                                                f"within {a.window_days}d: overturn or new work? resolve by hand"})
                    flagged.add(did)
            elif now - t > window:
                ev = {"type": "outcome", "id": did, "ts": now_iso(), "outcome": "held",
                      "evidence": f"proxy: no non-accept verdict on the same topic within {a.window_days}d"}
                resolved.append(ev)
                outcomes[did] = ev
    if new or resolved or flags_new:
        append(new + resolved + flags_new)
    print(f"import-hermes: {len(new)} new decision(s), {len(resolved)} held, {len(flags_new)} flagged for review, "
          f"from {len(rows)} stored verdict(s)")


def flags(events):
    return {e["id"] for e in events if e.get("type") == "flag"}


def cmd_report(a):
    events, bad = read_events()
    decisions, outcomes = index(events)
    rows = {}
    for d in decisions.values():
        if a.point and d["point"] != a.point:
            continue
        key = (d["point"], d.get("tier") or "untiered", d["answer"])
        r = rows.setdefault(key, {"n": 0, "resolved": 0, "overturned": 0})
        r["n"] += 1
        o = outcomes.get(d["id"])
        if o:
            r["resolved"] += 1
            r["overturned"] += o["outcome"] == "overturned"
    if not rows:
        print("no decisions recorded")
        return
    print(f"{'point':22} {'tier':9} {'answer':14} {'n':>6} {'resolved':>9} {'overturned':>11} {'rate':>7}")
    notes = []
    for (point, tier, answer), r in sorted(rows.items()):
        rate = (r["overturned"] / r["resolved"]) if r["resolved"] else None
        print(f"{point:22} {tier:9} {answer:14} {r['n']:6} {r['resolved']:9} {r['overturned']:11} "
              f"{(f'{rate:.0%}' if rate is not None else '-'):>7}")
        if r["resolved"] >= a.min and rate is not None:
            if tier == "high" and rate > 0.10:
                notes.append(f"{point}/{answer}: high tier overturned {rate:.0%} of {r['resolved']} -- "
                             "the high threshold is too loose, or its confidence source is not measuring")
            if tier == "medium" and rate == 0:
                notes.append(f"{point}/{answer}: medium tier never overturned in {r['resolved']} -- "
                             "candidate to act without the verify step (a human decision)")
    open_flags = [e for e in events if e.get("type") == "flag" and e["id"] not in outcomes
                  and (not a.point or decisions.get(e["id"], {}).get("point") == a.point)]
    if open_flags:
        notes.append(f"{len(open_flags)} decision(s) flagged for review, unresolved -- resolve each with evidence:")
        for e in open_flags[:20]:
            notes.append(f"  {e['id']}: {e['reason']}")
    if bad:
        notes.append(f"{len(bad)} unparseable line(s): {bad[:5]}")
    for n in notes:
        print("note: " + n)
    print(f"(notes appear once a row has >= {a.min} resolved decisions; thresholds stay human-set)")


def check(stale_days, path=None):
    """Return a list of problems; empty means healthy."""
    events, bad = read_events(path)
    problems = [f"unparseable line {n}" for n in bad]
    if not events:
        return problems + ["ledger missing or empty"]
    decisions, outcomes = index(events)
    for oid in outcomes:
        if oid not in decisions:
            problems.append(f"outcome for unknown decision {oid}")
    init = next((e for e in events if e.get("type") == "init"), None)
    now = dt.datetime.now(dt.timezone.utc)
    started = parse_ts(init["ts"]) if init else now
    # Recording time, not decision time: an import of old verdicts is still use.
    recorded = [parse_ts(e.get("recorded", e["ts"])) for e in events if e.get("type") in ("decision", "outcome")]
    last = max(recorded) if recorded else None
    if now - started > dt.timedelta(days=stale_days) and (last is None or now - last > dt.timedelta(days=stale_days)):
        problems.append(f"nothing recorded for {stale_days}+ days: installed but unused")
    return problems


def cmd_check(a):
    problems = check(a.stale_days)
    for p in problems:
        print("PROBLEM " + p)
    if not problems:
        events, _ = read_events()
        d, o = index(events)
        print(f"decision-ledger: ok ({len(d)} decisions, {len(o)} outcomes)")
    return 1 if problems else 0


def falsify():
    """Each refusal and each failure mode must actually fire."""
    tmp = tempfile.mkdtemp()
    os.environ["DECISION_LEDGER"] = os.path.join(tmp, "l.jsonl")
    me = os.path.abspath(__file__)
    failures = []

    def run(*args):
        return subprocess.run([sys.executable, me, *args], capture_output=True, text=True,
                              env={**os.environ})

    def expect(label, cond):
        print(f"falsify: {label} -> {'ok' if cond else 'FAILED'}")
        if not cond:
            failures.append(label)

    r = run("record", "--point", "test-verdict", "--answer", "PASS", "--space", "PASS|FAIL|BLOCKED|NOT RUN",
            "--source", "check", "--tier", "high", "--measurement", "persona completed signup on sha abc123")
    expect("a valid decision records", r.returncode == 0)
    did = r.stdout.strip()
    expect("out-of-space answer refused", run("record", "--point", "test-verdict", "--answer", "mostly",
           "--space", "PASS|FAIL", "--source", "check", "--measurement", "x").returncode == 2)
    expect("self-reported high confidence refused", run("record", "--point", "x", "--answer", "a",
           "--source", "none", "--tier", "high", "--measurement", "").returncode == 2)
    expect("measured source without measurement refused", run("record", "--point", "x", "--answer", "a",
           "--source", "check", "--measurement", "").returncode == 2)
    expect("secret-looking text refused", run("record", "--point", "x", "--answer", "a", "--source", "check",
           "--measurement", "token sk-" + "a" * 20).returncode == 2)
    expect("unknown id cannot be resolved", run("resolve", "nope", "--outcome", "held",
           "--evidence", "x").returncode == 2)
    expect("resolve works", run("resolve", did, "--outcome", "overturned",
           "--evidence", "signup broke on sha def456").returncode == 0)
    expect("second resolution refused", run("resolve", did, "--outcome", "held",
           "--evidence", "x").returncode == 2)
    run("record", "--point", "review-finding", "--answer", "confirmed", "--source", "check",
        "--measurement", "repro on changed path", "--ref", "repo#12@abc")
    run("record", "--point", "review-finding", "--answer", "confirmed", "--source", "check",
        "--measurement", "repro on changed path", "--ref", "repo#12@abc")
    expect("ambiguous --ref refused", run("resolve", "--ref", "repo#12", "--outcome", "held",
           "--evidence", "x").returncode == 2)
    run("record", "--point", "scope-verdict", "--answer", "aligned", "--source", "check",
        "--measurement", "3/3 requirements covered", "--ref", "task-77")
    expect("unique --ref resolves", run("resolve", "--ref", "task-77", "--outcome", "held",
           "--evidence", "user accepted the result").returncode == 0)
    expect("healthy ledger passes check", run("check").returncode == 0)

    with open(os.environ["DECISION_LEDGER"], "a") as fh:
        fh.write("{not json\n")
    expect("corrupt line fails check", run("check").returncode == 1)

    stale = os.path.join(tmp, "stale.jsonl")
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
    with open(stale, "w") as fh:
        fh.write(json.dumps({"type": "init", "ts": old}) + "\n")
    expect("unused ledger fails check", any("unused" in p for p in check(14, stale)))

    db = os.path.join(tmp, "fleet.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE verdicts (id INTEGER PRIMARY KEY, at INTEGER, topic TEXT, verdict TEXT, claim TEXT, machine TEXT)")
    day = 86_400_000
    t0 = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).timestamp() * 1000)
    con.executemany("INSERT INTO verdicts VALUES (?,?,?,?,?,?)", [
        (1, t0, "a", "accept", "", "m"), (2, t0 + day, "a", "reject", "", "m"),  # overturned
        (3, t0, "b", "revise", "", "m"), (4, t0 + day, "b", "accept", "", "m"),  # held (nothing after)
    ])
    con.commit()
    con.close()
    os.environ["DECISION_LEDGER"] = os.path.join(tmp, "h.jsonl")
    run("import-hermes", "--db", db)
    run("import-hermes", "--db", db)  # idempotent
    d, o = index(read_events()[0])
    expect("hermes import is idempotent", len(d) == 4)
    expect("accept followed by reject is flagged, not auto-overturned",
           "hermes-1" not in o and "hermes-1" in flags(read_events()[0]))
    expect("flag is written once across imports", sum(1 for e in read_events()[0] if e.get("type") == "flag") == 1)
    expect("accept with no later objection is held", o.get("hermes-4", {}).get("outcome") == "held")
    expect("revise is not auto-resolved", "hermes-3" not in o)

    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    print("falsify: " + ("ok" if not failures else "FAILED"))
    return not failures


def main():
    if "--falsify" in sys.argv:
        sys.exit(0 if falsify() else 1)
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--point", required=True)
    r.add_argument("--answer", required=True)
    r.add_argument("--space")
    r.add_argument("--source", required=True)
    r.add_argument("--tier")
    r.add_argument("--measurement", default="")
    r.add_argument("--ref", default="")
    r.add_argument("--agent", default="")
    s = sub.add_parser("resolve")
    s.add_argument("id", nargs="?")
    s.add_argument("--ref")
    s.add_argument("--point")
    s.add_argument("--outcome", required=True)
    s.add_argument("--evidence", required=True)
    h = sub.add_parser("import-hermes")
    h.add_argument("--db")
    h.add_argument("--window-days", type=int, default=7)
    rp = sub.add_parser("report")
    rp.add_argument("--point")
    rp.add_argument("--min", type=int, default=20)
    c = sub.add_parser("check")
    c.add_argument("--stale-days", type=int, default=14)
    a = p.parse_args()
    try:
        rc = {"record": cmd_record, "resolve": cmd_resolve, "import-hermes": cmd_import_hermes,
              "report": cmd_report, "check": cmd_check}[a.cmd](a)
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        sys.exit(2)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
