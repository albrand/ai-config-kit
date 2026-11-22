# P5 full-workflow re-walk procedure

## P5 Re-walk: `.qa/rewalk.json` + `.qa/evidence.json`

After the batch inventory closes, do this once at the aggregate batch head,
not after every individual fix. Cover the ENTIRE workflow again — including
steps you never touched. Every workflow step gets a verdict and evidence;
automated steps use the Playwright converter above, while `NOT_AUTOMATED`
steps need matching manual evidence. `rewalk.json` records the SHA; the gate
rejects a re-walk whose SHA is not the one being shipped (except the single
QA-only evidence commit on top). Write `.qa/evidence.json` as a
`claim_e2e_complete` packet (verified-qa-e2e evidence contract) — the gate
runs `qa-e2e-gate.mjs check` on it. Then record the events:

```sh
python3 <skill-dir>/scripts/ship-gate.py record inventory-closed   # after P1 rows close
python3 <skill-dir>/scripts/ship-gate.py record rewalk             # after P5
python3 <skill-dir>/scripts/ship-gate.py record escape --source sentry --ref <id>  # on any escape
```
