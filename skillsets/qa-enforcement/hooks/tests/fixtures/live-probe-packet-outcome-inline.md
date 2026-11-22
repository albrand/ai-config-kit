Implemented all three requested changes. The compound duration tests now pass.

**Evidence**

- Persona: scheduler team consumer
- Target: Python 3 unittest stack at commit `cb0a373fb69cd6cb46b32cf2d017621b0f4c205a`
- Outcome: `1h30m` returns `5400` and `2m15s` returns `135` — **PASS**
- Evidence: `python3 -m unittest discover -s tests -v` — 2 tests passed, including both compound cases. The README documents `1h30m` returning `5400`.
