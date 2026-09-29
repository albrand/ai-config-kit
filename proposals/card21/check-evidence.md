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
matched applicable rules in the final checker (72 regexes; 41 applicable to the
Codex home). The rendered proposals plus kit source also passed all 72 regexes,
including each Codex-only context-GC, email-consent, browser-lifecycle,
browser-input-quarantine, and Hermes transport obligation. Worktree subrules
have separate checks and mutation fixtures for each safeguard. A historical
marker on the matching line or directly preceding line invalidates a policy.

`python3 scripts/test_check_standing_rules.py`: **29 tests, OK**. Fixtures cover
an intact document, deleted rules, deletion in a file, and separate worktree
mutations for dirty trees, `.keep-worktree`, detached commits with history words
retained, detached-worktree lifetime, worktree-scoped `--force`, nonownership,
entire worktree-policy historical relabeling, adjacent-line historical notes,
and own-environment protection. Historical notes separated from the policy by
a blank line do not invalidate it. Email fixtures reject general-task and
different-message consent, and delete each mail-safety obligation in turn.
Mutation cases weaken each remaining hard prohibition and require the checker
to reject the change. Browser tests combine every actual rendered provider
proposal with the rendered bb baseline, then delete or weaken page ownership,
enumeration/lifecycle and target-ID isolation rules.
They also reject opposite “do not close” and “do not close before cookie
isolation” instructions, and “do not enumerate before open.”
The provider hard-rule source independently retains browser-input mutation,
persistent per-input quarantine, exclusive-delivery proof, read-only-only after
leaks, quarantine across agents/restarts, regression-gated re-enablement, and
no-prompt-bypass. A separate test copies each native proposal without the bb
baseline, deletes/weakens each of those seven rules, and invokes
`check-standing-rules.py --files` as a subprocess; all 21 standalone cases fail
as required.
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
Standalone provider-context mutations separately weaken the three-child no-ask
limit, the six-child orchestration limit, the host-capacity bound, and its
distinction from the 10-instance OpenCode session cap. Dependency mutation
weakens delegate dependency approval; the checker requires a new master
decision before adding a dependency. Broker-lane mutations independently remove
the default-off state, concurrency/depth 1, explicit bounded activation, or
separation from ordinary bb child threads. Delegation authorization mutations
retain the “ordinary delegation authorized by default” sentence while deleting
the explicit outward-effect approval, large/unbounded fan-out approval, or
cross-session cmux default-off boundary. Each test reads one rendered native
provider file alone, without the bb baseline, and requires the appropriate
regex to fail after each mutation.
The real `--files` entrypoint now also requires every delegation, child-cap,
dependency, and broker boundary in standalone provider proposals. A subprocess
fixture runs all 12 mutations against each of Claude, Codex, and OpenCode;
all 36 cases fail as required.
Codex-scoped deletion fixtures cover each context-GC
obligation and the ban on garbage-collecting repositories, journals, user-owned
sessions, or active sessions.

Baseline checker stdout:

```text
PASS all 5 files contain all applicable rules (20 regexes)
```

Final checker stdout (live homes + kit source):

```text
PASS all 5 files contain all applicable rules (72 regexes)
```

Rendered-home checker stdout:

```text
PASS all 5 files contain all applicable rules (72 regexes)
```

Unit-test stdout:

```text
Ran 29 tests
OK
```

Live homes were not modified. The renderer remains in proposal mode; its
`--install` option was not run.
