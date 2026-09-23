#!/usr/bin/env python3
"""Ask a System One model (TypeSafe Jev) typed questions about one state packet.

Jev never generates text: it takes a state and typed questions and returns, per
question, an answer from the declared space with a calibrated probability, in one
pass. Questions in one call are judged in parallel and cannot see each other's
answers, which is the isolation typed-decisions section 4 asks for.

Usage:
  jev.py --state-file diff.txt --yn auth "Does this diff change auth or permissions?"
  jev.py --state "$TEXT" --pick triage "Where does this issue go?" \
         "needs-info=missing repro or expected behaviour|ready-for-agent|ready-for-human|wontfix"
  jev.py --state-file packet.json --level sev "How severe is the risk?" \
         "cosmetic|minor, workaround exists|broken feature|data loss or auth bypass"
  jev.py --spec questions.json --state-file packet.json      # full TypeSafe questions map
  ... --record --point review-finding --ref "repo#123 f1"    # also write the decision ledger
  ... --record --point "triage=triage,sev=severity" --ref X  # per-question points; unmapped not recorded

Output: one JSON object {model, answers: {id: {type, answer, p|confidence, tier, ...}}}.
Tiers use the human-set thresholds below until the ledger's outcome history for a
point says otherwise (`decision-ledger.py report`, source system-one).

Environment: TYPESAFE_BASE_URL (API root; default: the gateway set at publish,
else https://api.typesafe.ai) and
TYPESAFE_API_KEY (a placeholder is fine behind a gateway that injects the key).
JEV_DRY_RUN=1 or --dry-run prints the request instead of sending it.

Exit: 0 answered; 2 refused input (bad spec, secret-looking state); 3 service
failure after bounded retries. On 3, do not invent an answer: judge it yourself
and record it with --source none --tier low, or escalate.
"""
import argparse, json, os, re, subprocess, sys, time, urllib.error, urllib.request

# Human-set thresholds (typed-decisions section 5). Tune from outcome history, never
# lower them to get a decision through.
YN_HIGH, YN_MEDIUM = 0.90, 0.75          # p >= HIGH -> yes/high; p <= 1-HIGH -> no/high
PICK_HIGH, PICK_MEDIUM = 0.85, 0.60       # Choice/Score confidence

SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|tskey-[A-Za-z0-9-]{10,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})")
LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "decision-ledger.py")


class Refused(Exception):
    pass


def options(spec):
    """'a=desc|b|c=desc' -> {"a": "desc", "b": None, "c": "desc"} (order kept)."""
    out = {}
    for part in spec.split("|"):
        k, _, d = part.partition("=")
        k = k.strip()
        if not k:
            raise Refused(f"empty option in {spec!r}")
        out[k] = d.strip() or None
    if len(out) < 2:
        raise Refused(f"need at least two options in {spec!r}")
    return out


def build_questions(a):
    qs = {}
    if a.spec:
        qs.update(json.load(open(a.spec)))
    for qid, text in a.yn or []:
        qs[qid] = {"type": "noul", "instructions": text}
    for qid, text, opts in a.pick or []:
        qs[qid] = {"type": "choice", "instructions": text, "criteria": options(opts)}
    for qid, text, levels in a.level or []:
        lv = [x.strip() for x in levels.split("|")]
        if len(lv) < 2 or not all(lv):
            raise Refused(f"level {qid}: need 2+ written anchors, got {levels!r}")
        qs[qid] = {"type": "score", "instructions": text, "criteria": lv}
    if not qs:
        raise Refused("no questions: use --yn, --pick, --level or --spec")
    for qid, q in qs.items():
        if q.get("type") not in ("noul", "choice", "score"):
            raise Refused(f"{qid}: type must be noul, choice or score")
    return qs


def load_state(a):
    if a.state is not None:
        raw = a.state
    elif a.state_file:
        raw = sys.stdin.read() if a.state_file == "-" else open(a.state_file).read()
    else:
        raise Refused("no state: use --state or --state-file")
    if SECRET.search(raw):
        raise Refused("state looks like it contains a secret; remove it (state leaves this machine)")
    if len(raw) > a.max_chars:
        raise Refused(f"state is {len(raw)} chars (> {a.max_chars}); send the relevant packet, not everything")
    try:
        v = json.loads(raw)
        return v if isinstance(v, (dict, list)) else raw
    except ValueError:
        return raw


# Filled in at publish time from the machine overlay, so a process without the shell
# profile (cron, launchd, a GUI-launched agent) still reaches the shared gateway.
PUBLISHED_BASE = "{{SYSTEM_ONE_BASE_URL}}"


def base_url():
    if os.environ.get("TYPESAFE_BASE_URL"):
        return os.environ["TYPESAFE_BASE_URL"].rstrip("/")
    if not PUBLISHED_BASE.startswith("{{"):
        return PUBLISHED_BASE.rstrip("/")
    return "https://api.typesafe.ai"


def call(body, timeout):
    base = base_url()
    key = os.environ.get("TYPESAFE_API_KEY", "")
    req = urllib.request.Request(base + "/v1/systemone", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "TypeSafeJev/1.0",
                                          **({"Authorization": f"Bearer {key}"} if key else {})})
    last = None
    for attempt in range(2):                      # bounded: 2 attempts, then fail loudly
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            if e.code in (429, 500, 502, 503, 504) and attempt == 0:
                last = f"HTTP {e.code}: {detail}"; time.sleep(2); continue
            raise RuntimeError(f"HTTP {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError) as e:
            last = f"{type(e).__name__}: {e}"
            if attempt == 0:
                time.sleep(2); continue
    raise RuntimeError(last or "unknown failure")


def tier_of(ans):
    if ans["type"] == "noul":
        p = ans["noul"]
        if p >= YN_HIGH or p <= 1 - YN_HIGH:
            return "high"
        if p >= YN_MEDIUM or p <= 1 - YN_MEDIUM:
            return "medium"
        return "low"
    c = ans.get("confidence", 0)
    return "high" if c >= PICK_HIGH else "medium" if c >= PICK_MEDIUM else "low"


def shape(ans):
    t = ans["type"]
    if t == "noul":
        out = {"type": "yes/no", "answer": "yes" if ans["noul"] >= 0.5 else "no", "p_yes": ans["noul"]}
    elif t == "choice":
        out = {"type": "pick-one", "answer": ans["choice"], "confidence": ans.get("confidence"),
               "distribution": ans.get("probabilities")}
    else:
        probs = ans.get("probabilities") or {}
        top = max(probs, key=lambda k: probs[k]) if probs else str(round(ans["score"]))
        out = {"type": "level", "answer": f"L{top}", "label": (ans.get("legend") or {}).get(top),
               "score": ans.get("score"), "confidence": ans.get("confidence"), "distribution": probs}
    out["tier"] = tier_of(ans)
    return out


def space_of(q):
    if q["type"] == "noul":
        return "yes|no"
    if q["type"] == "choice":
        return "|".join(q["criteria"])
    return "|".join(f"L{i}" for i in range(len(q["criteria"])))


def points(spec, qids):
    """'triage' -> every question at that point; 'q1=triage,q2=done' -> only mapped ones."""
    if "=" not in spec:
        return {q: spec for q in qids}
    m = dict(part.split("=", 1) for part in spec.split(","))
    unknown = set(m) - set(qids)
    if unknown:
        raise Refused(f"--point maps unknown question(s): {', '.join(sorted(unknown))}")
    return m


def agent_id():
    """Who asked: JEV_AGENT, else the bb thread, else the runtime session (for velocity per agent)."""
    if os.environ.get("JEV_AGENT"):
        return os.environ["JEV_AGENT"]
    runtime = ("claude" if os.environ.get("CLAUDECODE") else "codex" if os.environ.get("CODEX_THREAD_ID")
               else "opencode" if os.environ.get("OPENCODE") else "shell")
    who = (os.environ.get("BB_THREAD_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")[:8]
           or os.environ.get("CODEX_THREAD_ID", "")[:8])
    return f"{runtime}:{who}" if who else runtime


def record(a, qs, model, answers, latency_ms, tokens):
    pmap = points(a.point, list(answers))
    for qid, out in answers.items():
        if qid not in pmap:
            continue
        meas = f"{model} " + (f"p_yes={out['p_yes']}" if "p_yes" in out else f"confidence={out['confidence']}")
        ref = a.ref if len(pmap) == 1 else f"{a.ref} #{qid}"
        cmd = [sys.executable, LEDGER, "record", "--point", pmap[qid], "--answer", out["answer"],
               "--space", space_of(qs[qid]), "--source", "system-one", "--tier", out["tier"],
               "--measurement", meas, "--ref", ref, "--agent", agent_id(),
               "--latency-ms", str(latency_ms), "--batch", str(len(answers))]
        if tokens is not None:
            cmd += ["--tokens", str(tokens)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        out["ledger"] = r.stdout.strip() if r.returncode == 0 else f"refused: {r.stderr.strip()[:200]}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state"); ap.add_argument("--state-file")
    ap.add_argument("--yn", nargs=2, action="append", metavar=("ID", "QUESTION"))
    ap.add_argument("--pick", nargs=3, action="append", metavar=("ID", "QUESTION", "A=desc|B|C"))
    ap.add_argument("--level", nargs=3, action="append", metavar=("ID", "QUESTION", "L0|L1|L2"))
    ap.add_argument("--spec", help="JSON file: a TypeSafe questions map")
    ap.add_argument("--model", default="jev-latest")
    ap.add_argument("--timeout", type=float, default=30)
    ap.add_argument("--max-chars", type=int, default=60000)
    ap.add_argument("--record", action="store_true"); ap.add_argument("--point"); ap.add_argument("--ref")
    ap.add_argument("--raw", action="store_true", help="print the service response unshaped")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        if a.record and not (a.point and a.ref):
            raise Refused("--record needs --point and --ref")
        qs = build_questions(a)
        if a.record:
            points(a.point, list(qs))          # validate the map before spending a call
        body = {"state": load_state(a), "model": a.model, "questions": qs}
    except (Refused, OSError, ValueError) as e:
        print(f"jev: refused: {e}", file=sys.stderr); return 2
    if a.dry_run or os.environ.get("JEV_DRY_RUN") == "1":
        print(json.dumps(body, indent=1)); return 0
    t0 = time.monotonic()
    try:
        resp = call(body, a.timeout)
    except RuntimeError as e:
        print(f"jev: service failure: {e}", file=sys.stderr); return 3
    latency_ms = int((time.monotonic() - t0) * 1000)
    if a.raw:
        print(json.dumps(resp)); return 0
    model = resp.get("model", a.model)
    answers = {qid: shape(ans) for qid, ans in resp.get("answers", {}).items()}
    usage = resp.get("usage") or {}
    tokens = (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)) if usage else None
    if a.record:
        record(a, qs, model, answers, latency_ms, tokens)
    print(json.dumps({"model": model, "answers": answers, "usage": resp.get("usage"),
                      "latency_ms": latency_ms}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
