#!/usr/bin/env python3
"""Benchmark typed decisions: Jev (System One) against LLM-reasoned answers.

Runs a fixed set of labelled decision cases (the decision points the skills use:
workflow track, risk triggers, finding real, in scope, severity, done) through
each method, and writes accuracy, per-decision latency and per-decision tokens
to <velocity dir>/bench-<ts>.json, which `decision-ledger.py velocity` reads.

Every method gets the same batching: one call per state, all its questions at
once. The LLM side runs `claude -p` with no tools, no settings and a minimal
system prompt, and counts API time only: the cheapest an LLM decision can be.
Real in-agent reasoning also pays its whole context and thinking, so the gap
this reports is a floor.

Usage: jev-bench.py [--methods jev,claude:haiku,claude:sonnet] [--cases FILE] [--dry-run]
Exit 0 written; 3 when a method failed on every case.
"""
import argparse, datetime as dt, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
JEV = os.path.join(HERE, "jev.py")

YN = "yes|no"
TRACK = ("quick=clear small change|standard=normal implementation with tests|"
         "big-change=architecture, security, data, migration or release|"
         "recovery=failing tests, CI, deploy or runtime incident|review=PR, diff or design review")
SEV = "cosmetic|minor, workaround exists|broken feature|data loss or auth bypass"

# (state, {qid: (kind, question, options-or-None, expected)})
CASES = [
    ("Task: rename the CSS class .btn-primary to .button-primary in one stylesheet and its two usages.",
     {"track": ("pick", "Which workflow track fits?", TRACK, "quick"),
      "auth": ("yn", "Does this task touch security, auth, secrets or data loss?", None, "no")}),
    ("Report: checkout returns HTTP 500 for every user since this morning's deploy. No code change yet.",
     {"track": ("pick", "Which workflow track fits?", TRACK, "recovery"),
      "release": ("yn", "Is this tied to a release or rollout?", None, "yes"),
      "sev": ("level", "How severe is the problem?", SEV, "L2")}),
    ("Task: replace session cookies with JWT bearer tokens across the API and the web client, "
     "including a migration for existing sessions.",
     {"track": ("pick", "Which workflow track fits?", TRACK, "big-change"),
      "auth": ("yn", "Does this task touch security, auth, secrets or data loss?", None, "yes"),
      "reversible": ("yn", "Is this change easy to reverse after release?", None, "no")}),
    ("Request: review PR #88, which adds pagination to the orders list endpoint.",
     {"track": ("pick", "Which workflow track fits?", TRACK, "review")}),
    ("Finding: `if user.role = 'admin':` in auth.py line 40 of the diff. The reviewer reproduced that any "
     "logged-in user passes the admin check.",
     {"real": ("yn", "Is this finding a real defect on the changed path?", None, "yes"),
      "sev": ("level", "How severe is it?", SEV, "L3")}),
    ("Finding: a reviewer says the variable name `tmp` in utils.py could be more descriptive. "
     "Behaviour is correct and tested.",
     {"real": ("yn", "Is this finding a real defect on the changed path?", None, "no"),
      "sev": ("level", "How severe is it?", SEV, "L0")}),
    ("Request: 'add CSV export to the invoices page'. Result: CSV export added, plus a redesigned "
     "invoices table and a new dark mode toggle.",
     {"covered": ("yn", "Is the requested CSV export delivered?", None, "yes"),
      "extra": ("yn", "Was work added that the user did not request?", None, "yes")}),
    ("Request: 'fix the typo in the README title'. Result: the README title typo is fixed; nothing else "
     "changed.",
     {"covered": ("yn", "Is the requested fix delivered?", None, "yes"),
      "extra": ("yn", "Was work added that the user did not request?", None, "no")}),
    ("Evidence: unit tests pass. The signup page was never opened in a browser; no persona walked the "
     "signup flow.",
     {"verdict": ("pick", "What is the test verdict for 'a new user can sign up'?",
                  "PASS=persona completed the goal|FAIL=persona could not complete it|"
                  "BLOCKED=could not attempt, blocker named|NOT RUN=goal was not attempted", "NOT RUN")}),
    ("Evidence: persona 'new customer' on staging at sha 4f2a1c opened /signup, submitted the form and "
     "landed on the dashboard showing their name.",
     {"verdict": ("pick", "What is the test verdict for 'a new user can sign up'?",
                  "PASS=persona completed the goal|FAIL=persona could not complete it|"
                  "BLOCKED=could not attempt, blocker named|NOT RUN=goal was not attempted", "PASS")}),
    ("Status: the fix is committed and its focused test passes. The PR is not opened and the requested "
     "deploy has not run.",
     {"done": ("yn", "Is all the requested work finished?", None, "no")}),
    ("Issue: 'The app is slow sometimes.' No steps, no page, no timing, no expected behaviour.",
     {"triage": ("pick", "Where does this issue go?",
                 "needs-info=missing repro or expected behaviour|ready-for-agent=clear enough to implement|"
                 "wontfix=out of scope", "needs-info")}),
]


def jev_question(kind, q, opts):
    if kind == "yn":
        return {"type": "noul", "instructions": q}
    if kind == "pick":
        crit = {}
        for part in opts.split("|"):
            k, _, d = part.partition("=")
            crit[k.strip()] = d.strip() or None
        return {"type": "choice", "instructions": q, "criteria": crit}
    return {"type": "score", "instructions": q, "criteria": opts.split("|")}


def run_jev(state, qs):
    spec = {qid: jev_question(k, q, o) for qid, (k, q, o, _) in qs.items()}
    path = os.path.join("/tmp", f"jev-bench-{os.getpid()}.json")
    json.dump(spec, open(path, "w"))
    try:
        r = subprocess.run([sys.executable, JEV, "--state", state, "--spec", path],
                           capture_output=True, text=True, timeout=90)
    finally:
        os.remove(path)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200])
    out = json.loads(r.stdout)
    u = out.get("usage") or {}
    return ({qid: a["answer"] for qid, a in out["answers"].items()}, out["latency_ms"],
            u.get("input_tokens", 0) + u.get("output_tokens", 0))


def llm_prompt(state, qs):
    lines = [f"State:\n{state}\n", "Answer each question with exactly one allowed value."]
    for qid, (k, q, o, _) in qs.items():
        if k == "yn":
            allowed = "yes | no"
        elif k == "pick":
            allowed = " | ".join(p.partition("=")[0].strip() + (f" ({p.partition('=')[2]})" if "=" in p else "")
                                 for p in o.split("|"))
        else:
            allowed = " | ".join(f"L{i} ({lab})" for i, lab in enumerate(o.split("|")))
        lines.append(f"- {qid}: {q} Allowed: {allowed}")
    lines.append('Reply with only a JSON object mapping each id to its value, e.g. {"id": "yes"}. '
                 "For levels reply the L-code only.")
    return "\n".join(lines)


def run_claude(model, state, qs):
    cmd = ["claude", "-p", llm_prompt(state, qs), "--model", model, "--output-format", "json",
           "--system-prompt", "You make typed engineering decisions. Output only JSON.",
           "--tools", "", "--strict-mcp-config", "--setting-sources", ""]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200] or r.stdout.strip()[:200])
    d = json.loads(r.stdout)
    text = d.get("result", "").strip()
    text = text[text.find("{"): text.rfind("}") + 1]
    u = d.get("usage", {})
    tokens = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
              + u.get("cache_read_input_tokens", 0) + u.get("output_tokens", 0))
    return json.loads(text), d.get("duration_api_ms") or d.get("duration_ms"), tokens


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--methods", default="jev,claude:haiku,claude:sonnet")
    ap.add_argument("--cases", help="JSON list of [state, {qid: [kind, question, options, expected]}]")
    ap.add_argument("--out-dir")
    ap.add_argument("--dry-run", action="store_true", help="print the LLM prompts and exit")
    a = ap.parse_args()
    cases = [(s, {k: tuple(v) for k, v in q.items()}) for s, q in json.load(open(a.cases))] if a.cases else CASES
    if a.dry_run:
        for s, qs in cases:
            print(llm_prompt(s, qs), "\n---")
        return 0
    n_dec = sum(len(q) for _, q in cases)
    result = {"ts": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
              "states": len(cases), "decisions": n_dec, "methods": {}, "misses": {}}
    rc = 0
    for method in a.methods.split(","):
        right, ms, tok, done, misses, errors = 0, 0, 0, 0, [], 0
        for i, (state, qs) in enumerate(cases):
            try:
                if method == "jev":
                    ans, lat, t = run_jev(state, qs)
                else:
                    ans, lat, t = run_claude(method.split(":", 1)[1], state, qs)
            except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
                errors += 1
                print(f"{method} case {i}: {e}", file=sys.stderr)
                continue
            done += len(qs); ms += lat; tok += t
            for qid, (_, _, _, want) in qs.items():
                got = str(ans.get(qid, "")).strip()
                if got == want:
                    right += 1
                else:
                    misses.append(f"case {i} {qid}: want {want}, got {got or '-'}")
        if not done:
            rc = 3
            continue
        result["methods"][method] = {"accuracy": right / n_dec, "answered": done, "errors": errors,
                                     "ms_per_decision": ms / done, "tokens_per_decision": tok / done}
        result["misses"][method] = misses
        m = result["methods"][method]
        print(f"{method:16} accuracy {m['accuracy']:.0%}  {m['ms_per_decision']:.0f} ms/decision  "
              f"{m['tokens_per_decision']:.0f} tokens/decision  errors {errors}")
    ledger = os.environ.get("DECISION_LEDGER") or os.path.expanduser("~/.local/state/agent-decisions/ledger.jsonl")
    out = a.out_dir or os.environ.get("DECISION_VELOCITY_DIR") or os.path.join(os.path.dirname(ledger), "velocity")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "bench-" + result["ts"].replace(":", "").replace("+0000", "Z") + ".json")
    json.dump(result, open(path, "w"), indent=1)
    print("wrote " + path)
    return rc


if __name__ == "__main__":
    sys.exit(main())
