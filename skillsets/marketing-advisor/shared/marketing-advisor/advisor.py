#!/usr/bin/env python3
"""marketing-advisor: typed accept/revise decision on one marketing asset.

One LLM call per asset (rubric), plus a persona-panel call when --panel is given or w > 0. The decision is computed
here, never by the model. Defaults are the calibrated configuration in spec.json ("calibrated").

usage:
  advisor.py --text-file hero.txt --type copy|name --audience patient|professional --surface "landing hero" \
             --brand brand.json [--facts facts.md] [--judge opus] [--w 0] [--panel] [--context "..."]
Prints one JSON object (schema.json). Exit 0 on accept, 3 on revise, 1 on error.
"""
import argparse, json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = json.loads((HERE / "spec.json").read_text())

CLAUDE = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5", "haiku": "claude-haiku-4-5-20251001"}
CURSOR = {"gpt": "gpt-5.6-sol-high", "gemini": "gemini-3.7-flash-high"}
SYSTEM = "You are a strict marketing reviewer. Judge only the material given. Do not use tools. Answer with one JSON object and nothing else."


def call(judge, prompt, empty_dir=None, timeout=600):
    """Return (parsed_json, meta). Claude judges run through `claude -p` with tools and settings off;
    GPT/Gemini run through `cursor-agent` in ask mode from an empty directory."""
    if judge in CLAUDE:
        cmd = ["claude", "-p", "--model", CLAUDE[judge], "--tools", "", "--setting-sources", "",
               "--strict-mcp-config", "--disable-slash-commands", "--system-prompt", SYSTEM, "--output-format", "json"]
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
        r = json.loads(p.stdout)
        txt, meta = r.get("result", ""), {"cost_usd": r.get("total_cost_usd"), "usage": r.get("usage")}
    elif judge in CURSOR:
        cwd = empty_dir or HERE / ".empty"
        Path(cwd).mkdir(exist_ok=True)
        p = subprocess.run(["cursor-agent", "-p", "--trust", "--mode", "ask", "--model", CURSOR[judge],
                            "--output-format", "json", SYSTEM + "\n\n" + prompt],
                           capture_output=True, text=True, cwd=cwd, timeout=timeout)
        r = json.loads(p.stdout)
        txt, meta = r.get("result", ""), {"usage": r.get("usage")}
    else:
        raise SystemExit(f"unknown judge {judge}")
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise ValueError("no JSON in judge output: " + txt[:200])
    try:
        return json.loads(m.group(0)), meta
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(0))), meta  # trailing commas only


def asset_block(a):
    ctx = f"\nContext: {a['context']}" if a.get("context") else ""
    return (f"Asset type: {a['type']}\nAudience: {a['audience']}\nSurface: {a['surface']}{ctx}\n"
            f"--- ASSET START ---\n{a['text']}\n--- ASSET END ---")


def rubric_prompt(a, principles, facts):
    crit = [c for c in SPEC["criteria"]]
    lines = "\n".join(f"- {c['id']} {c['name']}: {c['test']}"
                      + ("" if a["type"] in c["applies_to"] else "  [not applicable to this asset type: answer \"na\"]")
                      for c in crit)
    plines = "\n".join(f"- {p['id']}: {p['text']}" for p in principles) or "(none)"
    return f"""Review one marketing asset for a Brazilian product aimed at psychologists and their patients.

=== PRODUCT FACT SHEET (the only allowed source of facts) ===
{facts}

=== ASSET ===
{asset_block(a)}

=== CRITERIA (pass/fail each; "na" only where marked not applicable) ===
{lines}

=== BRAND PRINCIPLES (pass/fail each; "na" if it cannot apply to this asset) ===
{plines}

Judge strictly, as a demanding brand owner would before publishing. For each failure quote the words that fail.
Answer with ONLY this JSON:
{{"criteria": [{{"id": "R1", "pass": true|false|"na", "evidence": "<max 25 words>"}}, ...all R1-R8...],
 "principles": [{{"id": "F1", "pass": true|false|"na"}}, ...one per brand principle...],
 "compliance_violations": [{{"rule": "<e.g. CDC art. 37>", "excerpt": "<words>"}}]}}"""


def panel_prompt(a, facts):
    who = "\n".join(f"- {p['id']} {p['name']}: {p['profile']}" for p in SPEC["personas"])
    if a["audience"] == "professional":
        q = ("would_click: would you click to learn more after reading this? "
             "would_sign_up: would you create an account / join the waitlist on the strength of this?")
    else:
        q = ("This asset is aimed at people looking for therapy. would_click: reading it as a Brazilian adult "
             "looking for a psychologist, would it make you want to read on? would_sign_up: as a psychologist, "
             "would you list your profile on (or send patients to) a platform whose public page says this?")
    return f"""Simulate a panel of Brazilian psychologists reacting to one marketing asset. Each persona answers
honestly and independently, in character, based only on the asset and the facts below. Most real readers skim
and say no; a yes needs a reason.

=== PRODUCT FACT SHEET ===
{facts}

=== PANEL ===
{who}

=== ASSET ===
{asset_block(a)}

Questions for each persona: {q}
Answer with ONLY this JSON:
{{"panel": [{{"persona": "P1", "would_click": true|false, "would_sign_up": true|false, "reason": "<max 25 words, in character>"}}, ...P1-P4...]}}"""


def decide(a, rub, pan, w, principle_ids, threshold=None, judge=None):
    """Typed decision. rub/pan are the raw judge objects; returns the schema object."""
    crit = {c["id"]: c for c in rub.get("criteria", [])}
    spec = {c["id"]: c for c in SPEC["criteria"]}
    rows, applicable, passed = [], 0, 0
    for cid, c in spec.items():
        v = crit.get(cid, {}).get("pass", False)
        if a["type"] not in c["applies_to"]:
            v = "na"
        rows.append({"id": cid, "pass": v, "evidence": crit.get(cid, {}).get("evidence", "")})
        if v != "na":
            applicable += 1; passed += v is True
    got = {p["id"]: p.get("pass", False) for p in rub.get("principles", [])}
    prows = [{"id": pid, "pass": got.get(pid, False)} for pid in principle_ids]
    for p in prows:
        if p["pass"] != "na":
            applicable += 1; passed += p["pass"] is True
    rubric = passed / applicable if applicable else 0.0
    votes = pan.get("panel", [])
    panel = sum((bool(v.get("would_click")) + bool(v.get("would_sign_up"))) / 2 for v in votes) / len(votes) if votes else 0.0
    combined = (1 - w) * rubric + w * panel
    r7 = next(r for r in rows if r["id"] == "R7")
    gate_fail = r7["pass"] is not True
    if w < 1:
        gate_fail |= any(r["pass"] is False for r in rows if spec[r["id"]]["critical"])
    prereg = (not gate_fail) and combined >= SPEC["scoring"]["accept_threshold"]
    failed = [r["id"] for r in rows if r["pass"] is False] + [p["id"] for p in prows if p["pass"] is False]
    # Calibrated rule (see SKILL.md): the taste score decides accept/revise; truth and compliance failures do not
    # veto it -- they turn an accept into "verify" (confirm the flagged claims before publishing).
    cal = SPEC["calibrated"]
    t = cal["threshold"] if threshold is None else threshold
    violations = rub.get("compliance_violations", [])
    flagged = r7["pass"] is not True or any(r["id"] == "R6" and r["pass"] is False for r in rows) or bool(violations)
    decision = "revise" if combined < t else ("verify" if flagged else "accept")
    return {"asset_id": a.get("id", "asset"), "criteria": rows, "founder_principles": prows,
            "compliance": {"pass": r7["pass"] is True, "violations": violations},
            "panel": votes, "scores": {"rubric": round(rubric, 3), "panel": round(panel, 3), "combined": round(combined, 3),
                                       "w": w, "threshold": t, "ranking": round(combined - (1 if gate_fail else 0), 3)},
            "decision": decision, "calibrated": a["type"] in cal["scope"] and w == cal["w"] and judge == cal["judge"],
            "decision_preregistered": "accept" if prereg else "revise", "failed_criteria": failed}


def selftest():
    """Decision logic only, no model calls: exits non-zero if the typed rules drift."""
    ok = lambda ids, v=True: [{"id": i, "pass": v} for i in ids]
    allr = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
    yes = {"panel": [{"persona": p, "would_click": True, "would_sign_up": True} for p in ("P1", "P2", "P3", "P4")]}
    no = {"panel": [{"persona": p, "would_click": False, "would_sign_up": False} for p in ("P1", "P2", "P3", "P4")]}
    name = {"type": "name", "audience": "patient", "text": "x"}
    copy = {"type": "copy", "audience": "patient", "text": "x"}
    P = "decision_preregistered"
    cases = [
        ("prereg: name, all pass", decide(name, {"criteria": ok(allr)}, yes, 0.3, []), P, "accept"),
        ("prereg: name ignores non-applicable fails", decide(name, {"criteria": ok(["R1", "R6", "R7", "R8"]) + ok(["R2", "R3", "R5"], False)}, yes, 0.0, []), P, "accept"),
        ("prereg: R7 gate beats a perfect panel", decide(copy, {"criteria": ok(allr[:6]) + ok(["R7"], False) + ok(["R8"])}, yes, 1.0, []), P, "revise"),
        ("prereg: critical fail blocks when w<1", decide(copy, {"criteria": ok(["R1", "R2"]) + ok(["R3"], False) + ok(allr[3:])}, yes, 0.5, []), P, "revise"),
        ("prereg: panel-only ignores critical fails", decide(copy, {"criteria": ok(["R3"], False) + ok(["R1", "R2", "R4", "R5", "R6", "R7", "R8"])}, yes, 1.0, []), P, "accept"),
        ("prereg: threshold 0.75", decide(copy, {"criteria": ok(allr)}, no, 0.3, []), P, "revise"),
        ("prereg: principle failure counts", decide(copy, {"criteria": ok(allr), "principles": ok(["F1", "F2", "F3"], False)}, yes, 0.0, ["F1", "F2", "F3"]), P, "revise"),
        ("calibrated: clean pass", decide(copy, {"criteria": ok(allr)}, no, 0.0, []), "decision", "accept"),
        ("calibrated: below threshold", decide(copy, {"criteria": ok(allr[:4]) + ok(allr[4:], False)}, yes, 0.0, []), "decision", "revise"),
        ("calibrated: R7 turns accept into verify", decide(copy, {"criteria": ok(allr[:6]) + ok(["R7"], False) + ok(["R8"])}, no, 0.0, []), "decision", "verify"),
        ("calibrated: violation listed -> verify", decide(copy, {"criteria": ok(allr), "compliance_violations": [{"rule": "CDC art. 37", "excerpt": "x"}]}, no, 0.0, []), "decision", "verify"),
        ("calibrated: R6 fail -> verify", decide(copy, {"criteria": ok(allr[:5]) + ok(["R6"], False) + ok(["R7", "R8"])}, no, 0.0, []), "decision", "verify"),
    ]
    bad = [(n, d[key], want) for n, d, key, want in cases if d[key] != want]
    for n, got, want in bad:
        print(f"FAIL {n}: got {got}, want {want}")
    print(f"selftest {len(cases) - len(bad)}/{len(cases)}")
    sys.exit(1 if bad else 0)


def main():
    if "--selftest" in sys.argv:
        selftest()
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--type", choices=["copy", "name"], default="copy")
    ap.add_argument("--audience", choices=["patient", "professional"], required=True)
    ap.add_argument("--surface", default="landing section")
    ap.add_argument("--context", default="")
    ap.add_argument("--brand", required=True, help="brand profile JSON (principles, facts_file)")
    ap.add_argument("--facts", help="fact sheet; default: the brand's facts_file")
    ap.add_argument("--judge", default=SPEC["calibrated"]["judge"])
    ap.add_argument("--w", type=float, default=SPEC["calibrated"]["w"])
    ap.add_argument("--panel", action="store_true", help="run the persona panel even at w=0 (its reasons only)")
    ap.add_argument("--id", default="asset", help="stable asset id; outcomes are joined on it")
    ap.add_argument("--log", help="outcomes ledger (JSONL) to append the advice record to; see rescore.py")
    a = ap.parse_args()
    brand_path = Path(a.brand).expanduser()
    brand = json.loads(brand_path.read_text())
    facts = Path(a.facts or brand_path.parent / brand["facts_file"]).expanduser().read_text()
    asset = {"id": a.id, "type": a.type, "audience": a.audience, "surface": a.surface, "context": a.context,
             "text": Path(a.text_file).read_text().strip()}
    try:
        rub, _ = call(a.judge, rubric_prompt(asset, brand["principles"], facts))
        pan = call(a.judge, panel_prompt(asset, facts))[0] if (a.panel or a.w > 0) else {"panel": []}
    except Exception as e:
        print(json.dumps({"error": repr(e)[:300]})); sys.exit(1)
    out = decide(asset, rub, pan, a.w, [p["id"] for p in brand["principles"]], judge=a.judge)
    out["judge"] = a.judge
    if a.log:
        import datetime, hashlib
        rec = {"kind": "advice", "asset_id": a.id, "date": datetime.date.today().isoformat(),
               "config": f"{a.judge}/w={a.w}", "spec_version": SPEC["version"], "decision": out["decision"],
               "ranking": out["scores"]["ranking"], "failed": out["failed_criteria"],
               "text_sha": hashlib.sha256(asset["text"].encode()).hexdigest()[:16]}
        with open(Path(a.log).expanduser(), "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    sys.exit(0 if out["decision"] == "accept" else 3)


if __name__ == "__main__":
    main()
