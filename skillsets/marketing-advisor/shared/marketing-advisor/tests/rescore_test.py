#!/usr/bin/env python3
"""rescore.py on a synthetic ledger: owner agreement, A/B winner hit, CTR concordance, triggers."""
import json, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
recs = []
for i in range(12):
    recs.append({"kind": "advice", "asset_id": f"a{i}", "date": "2026-10-01", "config": "x",
                 "decision": "accept" if i % 3 == 0 else "revise", "ranking": i / 12})
    recs.append({"kind": "outcome", "asset_id": f"a{i}", "date": "2026-10-02", "source": "owner",
                 "value": "accept" if i % 4 == 0 else "reject"})
recs += [{"kind": "outcome", "asset_id": "a1", "date": "2026-10-03", "source": "ab", "test_id": "t1", "winner": False, "significant": True},
         {"kind": "outcome", "asset_id": "a5", "date": "2026-10-03", "source": "ab", "test_id": "t1", "winner": True, "significant": True},
         {"kind": "outcome", "asset_id": "a2", "date": "2026-10-03", "source": "ctr", "campaign_id": "c", "impressions": 2000, "clicks": 20},
         {"kind": "outcome", "asset_id": "a7", "date": "2026-10-03", "source": "ctr", "campaign_id": "c", "impressions": 2000, "clicks": 40},
         {"kind": "outcome", "asset_id": "a3", "date": "2026-10-03", "source": "ctr", "campaign_id": "c", "impressions": 10, "clicks": 9}]
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
    f.write("\n".join(json.dumps(r) for r in recs))
p = subprocess.run([sys.executable, str(HERE / "rescore.py"), f.name, "--calibrated-kappa", "0.9"], capture_output=True, text=True)
Path(f.name).unlink()
out = json.loads(p.stdout[: p.stdout.rindex("}") + 1])
checks = [
    ("owner n", out["owner"]["n"] == 12),
    ("owner accuracy", abs(out["owner"]["accuracy"] - 7 / 12) < 1e-9),   # agree on i = 0,1,2,5,7,10,11
    ("ab winner ranked first", out["ab"] == {"tests": 1, "winner_ranked_first": 1.0}),
    ("ctr drops low-impression rows", out["ctr"]["pairs"] == 1 and out["ctr"]["concordance"] == 1.0),
    ("kappa trigger + label-count trigger", len(out["triggers"]) == 2 and p.returncode == 2),
]
bad = [n for n, ok in checks if not ok]
print(f"rescore_test {len(checks) - len(bad)}/{len(checks)}", "FAIL: " + ", ".join(bad) if bad else "")
sys.exit(1 if bad else 0)
