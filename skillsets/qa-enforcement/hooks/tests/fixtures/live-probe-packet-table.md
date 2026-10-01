### QA evidence packet

- **Persona:** Scheduler team engineer
- **Target:** Python unittest; `HEAD` `cb0a373fb69cd6cb46b32cf2d017621b0f4c205a`, with the requested changes in the working tree.
- **Command:** `python3 -m unittest discover -s tests -v`
- **Result:** 2 tests ran; both passed.

| Goal attempted | Expected | Observed | Verdict |
|---|---|---|---|
| Parse `1h30m` and `2m15s` | Return 5400 and 135 seconds | `test_compound_units` passed for both values | **PASS** |
| Add compound cases to the tests | Both cases are present and exercised | `test_compound_units` ran and passed | **PASS** |
| Document compound input in README | Example shows `1h30m` returning 5400 | Example is present in the working tree | **PASS** |

The test run covers the parser behavior; no scheduler-level integration workflow was run. Nothing was pushed.