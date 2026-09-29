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
matched fixed applicable-rule inventories in the final checker (91 regexes;
46 Claude, 55 Codex, 51 OpenCode, 50 bb, and 84 kit rules applicable). The
rendered proposals plus kit source also passed all 91 regexes: 75 Claude, 91
Codex, 84 OpenCode, 84 bb, and 84 kit rules applicable. Candidate text cannot
make an optional rule inapplicable: native paths select a profile only when
the candidate exactly matches a checked-in legacy or rendered-home SHA-256;
any edited or unknown native-path content fails closed. Rendered paths select
fixed proposal profiles. Codex-only
context-GC, email-consent, browser-lifecycle, browser-input-quarantine, and
Hermes transport obligations are covered. Worktree subrules have separate
checks and mutation fixtures for each safeguard. A historical marker on the
matching line or directly preceding line invalidates a policy.

`python3 -m unittest scripts/test_check_standing_rules.py`: **39 tests, OK**. Fixtures cover
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
The provider hard-rule source independently retains browser ownership,
enumeration/lifecycle, input mutation/quarantine, exclusive-delivery, post-leak,
restart, re-enable, takeover-claim, and verified-QA gate rules. A separate test
copies each native proposal without the bb baseline, deletes/weakens all 19
browser/QA rules, and invokes `check-standing-rules.py --files` as a subprocess;
all 57 standalone cases fail as required.
Hermes transport fixtures check Codex and OpenCode proposals alone. The actual
`--files` entrypoint rejects deletion/weakening of argv-prompt, reverse-SSH,
listener, and broad-environment prohibitions in both contexts (8 cases). Other
standalone mutations cover `CMUX_SOCKET_CAPABILITY`/`CMUX_*`, `acp-hermes-agent
--model`, broker SSH stdin, local terminal sockets, and the absolute ban on
placing or retaining source on Hermes, including a mutation that retains the
old “never ask Hermes to mount” wording.
The security gate has separate regexes and rendered-path CLI mutations for
scope, required references, supply-chain priority, residual-exposure review,
authorized defensive testing, offensive-tooling prohibition, high-stakes sweep,
and strongest exploit-validation path. Every mutation is rejected across all
four proposal homes; intact proposals pass.
Credential typing, pasting, and handling each have a separate regex; strict
rendered profiles require all three, and live baselines enforce each action
present there. Rendered-path CLI weakening fixtures cover all four homes. Typed decisions
require batched isolated Jev judgments recorded as `system-one`, prohibit hook
and secret use, and prohibit relying on Jev alone for irreversible/security
decisions; each obligation has a deletion fixture.
The credential fixture also retains all three prohibition phrases while adding
an exception for login; the contradiction veto rejects it at the rendered
`--files` entrypoint for every provider.
The rendered-path CLI also rejects an added permission saying routine emails
may be sent without asking, across all four proposals, while intact proposals
pass. Full-workflow testing is checked separately from the persona/target/goals/
verdict reporting rule. The rendered `--files` fixture passes intact Claude,
Codex, OpenCode, and bb proposals, then replaces each full-workflow PASS
requirement with “focused unit tests; the full workflow is optional”; all four
mutated proposals fail for `testing-pass-full-workflow`.
Public exposure separately requires a current-conversation request naming the
service/port, closing the temporary share at task end, and checking
`bb connect shares` before closeout. Rendered-path mutations for stale consent
and either deleted cleanup obligation fail across all four homes.
Hermes defect-blocking checks reject both an explicit “does not block” reversal
and an “advisory” exception through rendered `--files` paths for all providers
and the shared bb baseline.

The real `--files` entrypoint also accepts native-shaped home paths. Intact
native baseline fixtures pass; intact rendered homes at native paths pass;
deleting/weakening a required rule in an installed artifact fails because its
fingerprint is no longer recognized. Unknown paths and content fail closed.
This guards against the previous content-driven applicability bug, including
deleting Codex's browser E2E/QA-gate rule at `~/.codex/AGENTS.md`.

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
all 36 cases fail as required. Another standalone `--files` fixture deletes
the node_modules symlink ban and low-disk install/build limit from each provider
proposal and requires rejection. Both safeguards also pass against all four
unchanged homes and the kit source.
Codex-scoped deletion fixtures cover each context-GC
obligation and the ban on garbage-collecting repositories, journals, user-owned
sessions, or active sessions.

Baseline checker stdout:

```text
PASS all 5 files contain all applicable rules (20 regexes)
```

Final checker stdout (live homes + kit source):

```text
PASS all 5 files contain all applicable rules (91 regexes)
```

Rendered-home checker stdout:

```text
PASS all 5 files contain all applicable rules (91 regexes)
```

Unit-test stdout:

```text
Ran 39 tests
OK
```

Live homes were not modified. The renderer remains in proposal mode; its
`--install` option was not run.
