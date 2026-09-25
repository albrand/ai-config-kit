#!/usr/bin/env python3
"""Re-score marketing-advisor against real outcomes, so its accuracy is tracked after calibration.

The ledger is JSONL, one record per line, joined on asset_id:
  {"kind":"advice", "asset_id", "date", "config", "decision":"accept|revise", "ranking", ...}   <- advisor.py --log
  {"kind":"outcome", "asset_id", "date", "source":"owner", "value":"accept|reject"}           <- owner approval
  {"kind":"outcome", "asset_id", "date", "source":"ab", "test_id", "winner":true|false, "significant":true|false}
  {"kind":"outcome", "asset_id", "date", "source":"ctr", "campaign_id", "impressions":N, "clicks":N}

usage: rescore.py LEDGER [--calibrated-kappa K] [--min-impressions 1000] [--since YYYY-MM-DD]
Prints the metrics JSON and a RECALIBRATE line when a trigger fires; exit 2 if one fires.
"""
import argparse, json, sys
from collections import defaultdict
from itertools import combinations


def kappa(y, p):
    n = len(y)
    if not n:
        return None
    po = sum(a == b for a, b in zip(y, p)) / n
    py, pp = sum(y) / n, sum(p) / n
    pe = py * pp + (1 - py) * (1 - pp)
    return 0.0 if pe == 1 else (po - pe) / (1 - pe)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ledger")
    ap.add_argument("--calibrated-kappa", type=float, default=None)
    ap.add_argument("--min-impressions", type=int, default=1000)
    ap.add_argument("--since", default="")
    a = ap.parse_args()
    recs = [json.loads(l) for l in open(a.ledger) if l.strip()]
    recs = [r for r in recs if r.get("date", "") >= a.since]
    advice = {}
    for r in sorted((r for r in recs if r["kind"] == "advice"), key=lambda r: r["date"]):
        advice[r["asset_id"]] = r  # latest advice per asset
    out, triggers = {}, []

    # 1. owner approvals: accept/revise agreement
    own = [(r, advice[r["asset_id"]]) for r in recs if r["kind"] == "outcome" and r["source"] == "owner" and r["asset_id"] in advice]
    y = [o["value"] == "accept" for o, _ in own]; p = [ad["decision"] == "accept" for _, ad in own]
    k = kappa(y, p)
    out["owner"] = {"n": len(own), "accuracy": (sum(a == b for a, b in zip(y, p)) / len(own)) if own else None,
                    "kappa": k, "always_reject_accuracy": (y.count(False) / len(y)) if y else None}
    last = own[-20:]
    k20 = kappa([o["value"] == "accept" for o, _ in last], [ad["decision"] == "accept" for _, ad in last])
    out["owner"]["kappa_last20"] = k20
    if a.calibrated_kappa is not None and len(last) >= 10 and k20 is not None and k20 < a.calibrated_kappa - 0.2:
        triggers.append(f"owner kappa over last {len(last)} = {k20:.2f}, calibrated {a.calibrated_kappa:.2f}")
    if len(own) >= 10:
        triggers.append(f"{len(own)} owner labels available: re-run calibration with them added to the labelled set")

    # 2. A/B tests: did the advisor rank the significant winner highest?
    tests = defaultdict(list)
    for r in recs:
        if r["kind"] == "outcome" and r["source"] == "ab" and r.get("significant") and r["asset_id"] in advice:
            tests[r["test_id"]].append(r)
    hits = []
    for tid, rs in tests.items():
        if len(rs) < 2 or not any(r["winner"] for r in rs):
            continue
        top = max(rs, key=lambda r: advice[r["asset_id"]]["ranking"])
        hits.append(bool(top["winner"]))
    out["ab"] = {"tests": len(hits), "winner_ranked_first": (sum(hits) / len(hits)) if hits else None}
    if len(hits) >= 5 and sum(hits) / len(hits) <= 0.5:
        triggers.append(f"A/B: winner ranked first in {sum(hits)}/{len(hits)} tests (chance or worse)")

    # 3. ad CTR: pairwise concordance between advisor ranking and CTR within a campaign
    camp = defaultdict(list)
    for r in recs:
        if r["kind"] == "outcome" and r["source"] == "ctr" and r["impressions"] >= a.min_impressions and r["asset_id"] in advice:
            camp[r["campaign_id"]].append((advice[r["asset_id"]]["ranking"], r["clicks"] / r["impressions"]))
    conc = disc = 0
    for rows in camp.values():
        for (s1, c1), (s2, c2) in combinations(rows, 2):
            if s1 == s2 or c1 == c2:
                continue
            conc += (s1 > s2) == (c1 > c2); disc += (s1 > s2) != (c1 > c2)
    out["ctr"] = {"campaigns": len(camp), "pairs": conc + disc,
                  "concordance": (conc / (conc + disc)) if conc + disc else None}
    if conc + disc >= 20 and conc / (conc + disc) <= 0.5:
        triggers.append(f"CTR: concordance {conc}/{conc + disc} (chance or worse)")

    out["triggers"] = triggers
    print(json.dumps(out, indent=1))
    for t in triggers:
        print("RECALIBRATE:", t)
    sys.exit(2 if triggers else 0)


if __name__ == "__main__":
    main()
