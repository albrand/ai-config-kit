# Card 21 standing-rule checks

Before source compression, `check-standing-rules.py` was run against all four
current homes and the original `GLOBAL_AGENTS.md` snapshot. Result: **PASS** —
all 5 files matched all applicable rules (12 regexes). The original kit source
did not mention `pkill`/`pgrep -f`; its optional “where present” regex was
therefore not applicable in that one file. The compact kit source and all homes
now state and match it.

After source compression, the same check was run against all four unchanged live
homes and the compact `GLOBAL_AGENTS.md`. Result: **PASS** — all 5 files matched
all 12 hard-rule patterns. The rendered proposals plus kit source also passed
all 12 patterns in each of 5 files.

`python3 scripts/test_check_standing_rules.py`: **4 tests, OK**. The fixtures
cover an intact document, a deleted rule, deletion in a file, and deletion of
`.keep-worktree` protection while the other worktree rules remain.

Baseline checker stdout:

```text
PASS all 5 files contain all applicable rules (12 regexes)
```

Final checker stdout (live homes + kit source):

```text
PASS all 5 files contain all applicable rules (12 regexes)
```

Rendered-home checker stdout:

```text
PASS all 5 files contain all applicable rules (12 regexes)
```

Unit-test stdout:

```text
Ran 4 tests
OK
```

Live homes were not modified. The renderer remains in proposal mode; its
`--install` option was not run.
