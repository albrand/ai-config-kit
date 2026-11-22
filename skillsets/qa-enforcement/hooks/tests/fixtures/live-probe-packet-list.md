**QA evidence packet**

- **Persona:** Scheduler team engineer.
- **Target:** Python, `HEAD cb0a373fb69cd6cb46b32cf2d017621b0f4c205a`, with requested changes in the working tree.
- **Command:** `python3 -m unittest discover -s tests -v`
- **Observed:** 2 tests ran; both passed.

**User outcomes and verdicts**

1. **Compound parsing:** Expected `1h30m → 5400` and `2m15s → 135`; observed both assertions pass in `test_compound_units`. **PASS**
2. **Regression tests added:** Expected both compound cases in `tests/test_durations.py`; observed `test_compound_units` ran and passed. **PASS**
3. **README example updated:** Expected a visible compound-input example; observed `README.md` documents `parse_duration("1h30m")` returning `5400`. **PASS**

No scheduler-level integration workflow was run. Nothing was pushed.