# Card 21 standing-rule checks

Before source compression, the initial checker run passed on all four current
homes and the original `GLOBAL_AGENTS.md` (11 then-applicable rules). After the
checker was expanded, it was run against all four unchanged homes and the
original kit snapshot. The original kit source did not mention `pkill`/`pgrep -f`,
the own-bb-environment exception, or Codex-only context-GC rules; those
presence-scoped checks were N/A where absent. The Codex home and rendered
Codex proposal require the complete context-GC procedure.

After source compression, the final check was run against all four unchanged
live homes and compact `GLOBAL_AGENTS.md`. Result: **PASS** — all five files
matched applicable rules in the final checker (60 regexes; 36 applicable to the
Codex home). The rendered proposals plus kit source also passed all 60 regexes,
including each Codex-only context-GC, email-consent, browser-lifecycle,
browser-input-quarantine, and Hermes transport obligation. Worktree subrules
have separate checks and mutation fixtures for each safeguard. A historical
marker on the matching line or directly preceding line invalidates a policy.

`python3 scripts/test_check_standing_rules.py`: **22 tests, OK**. Fixtures cover
an intact document, deleted rules, deletion in a file, and separate worktree
mutations for dirty trees, `.keep-worktree`, detached commits with history words
retained, detached-worktree lifetime, worktree-scoped `--force`, nonownership,
entire worktree-policy historical relabeling, adjacent-line historical notes,
and own-environment protection. Historical notes separated from the policy by
a blank line do not invalidate it. Email fixtures reject general-task and
different-message consent, and delete each mail-safety obligation in turn.
Mutation cases weaken each remaining hard prohibition and require the checker
to reject the change. Browser tests combine every actual rendered provider
proposal with the rendered bb baseline, then delete or weaken each page lifecycle
and input-quarantine safeguard: exclusive delivery proof, IDs not proving
isolation, per-input persistent quarantine, read-only-only after a leak,
quarantine surviving restart, regression-gated re-enablement, and no prompt
bypass. They also reject opposite “do not close” and “do not close before
cookie isolation” instructions, and “do not enumerate before open.”
Hermes transport fixtures combine each rendered provider with the shared bb
baseline and separately weaken reverse SSH, listeners, broad environment
forwarding, `CMUX_SOCKET_CAPABILITY`/`CMUX_*` export, and the
`acp-hermes-agent --model` override prohibition. Tests also require broker SSH
stdin, reject prompts in argv and local terminal socket requirements, and weaken
the absolute ban on placing or retaining project source on Hermes while
preserving the old “never ask Hermes to mount” wording; the checker still rejects it.
The verified-QA mutation narrows triggers to login/auth only, modeling an
already-authenticated browser E2E, and separately changes a missing or failing
gate into an optional gate; both mutations must fail.
Takeover mutations also reject calling a shared-window page dedicated or
foregrounded and claiming the exact login is open without adapter evidence.
Codex-scoped deletion fixtures cover each context-GC
obligation and the ban on garbage-collecting repositories, journals, user-owned
sessions, or active sessions.

Baseline checker stdout:

```text
PASS all 5 files contain all applicable rules (20 regexes)
```

Final checker stdout (live homes + kit source):

```text
PASS all 5 files contain all applicable rules (60 regexes)
```

Rendered-home checker stdout:

```text
PASS all 5 files contain all applicable rules (60 regexes)
```

Unit-test stdout:

```text
Ran 23 tests
OK
```

Live homes were not modified. The renderer remains in proposal mode; its
`--install` option was not run.
