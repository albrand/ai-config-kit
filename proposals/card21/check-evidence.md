# Card 21 standing-rule checks

Before source compression, `check-standing-rules.py` was run against all four
current homes and the original `GLOBAL_AGENTS.md` snapshot. Result: **PASS** —
all 5 files matched the 11 applicable hard-rule patterns. The original kit
source did not mention `pkill`/`pgrep -f`; the task's “where present” guard was
added explicitly during compression and checked after.

After source compression, the same check was run against all four unchanged live
homes and the compact `GLOBAL_AGENTS.md`. Result: **PASS** — all 5 files matched
all 12 hard-rule patterns. The rendered proposals plus kit source also passed
all 12 patterns in each of 5 files.

`python3 scripts/test_check_standing_rules.py`: **3 tests, OK**. The fixtures
cover an intact document, a deleted rule, and a deleted rule in a file.

The exact checker output is retained in the task transcript. Live homes were
not modified. The renderer remains in proposal mode; its `--install` option was
not run.
