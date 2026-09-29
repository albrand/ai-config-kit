# Card 21 standing-rule checks

Before source compression, the initial checker run passed on all four current
homes and the original `GLOBAL_AGENTS.md` (11 then-applicable rules). After the
checker was expanded, the final checker was also run against all four unchanged
homes and the original kit snapshot; all five passed all applicable rules with
20 regexes. The original kit source did not mention `pkill`/`pgrep -f` or the
own-bb-environment exception; the Codex-only context-GC rule was likewise not
a kit-source rule. Those presence-scoped checks were N/A where absent.

After source compression, the final check was run against all four unchanged
live homes and compact `GLOBAL_AGENTS.md`. Result: **PASS** — all 5 files matched
all applicable rules in the final checker (20 regexes). The rendered proposals
plus kit source also passed all 20 in each of 5 files. Worktree subrules have
separate checks and mutation fixtures for each safeguard.

`python3 scripts/test_check_standing_rules.py`: **12 tests, OK**. Fixtures cover
an intact document, deleted rules, deletion in a file, and separate worktree
mutations for dirty trees, `.keep-worktree`, detached commits with history words
retained, detached-worktree lifetime, worktree-scoped `--force`, nonownership,
entire worktree-policy historical relabeling, and own-environment protection.
A Codex-scoped historical-only fixture protects the ban on garbage-collecting
repositories, journals, user-owned sessions, or active sessions.

Baseline checker stdout:

```text
PASS all 5 files contain all applicable rules (20 regexes)
```

Final checker stdout (live homes + kit source):

```text
PASS all 5 files contain all applicable rules (20 regexes)
```

Rendered-home checker stdout:

```text
PASS all 5 files contain all applicable rules (20 regexes)
```

Unit-test stdout:

```text
Ran 12 tests
OK
```

Live homes were not modified. The renderer remains in proposal mode; its
`--install` option was not run.
