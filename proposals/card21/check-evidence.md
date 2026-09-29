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
matched fixed applicable-rule inventories in the final checker (109 regexes;
64 Claude, 73 Codex, 69 OpenCode, 63 bb, and 102 kit rules applicable). The
rendered proposals plus kit source also passed all 109 regexes: 93 Claude, 109
Codex, 102 OpenCode, 102 bb, and 102 kit rules applicable. Safety-hook
non-bypass is required in every profile, including unchanged native-home
fingerprints and standalone provider proposals. Candidate text cannot
make an optional rule inapplicable: native paths select a profile only when
the candidate exactly matches a checked-in legacy or rendered-home SHA-256;
any edited or unknown native-path content fails closed. Rendered paths select
fixed proposal profiles. Codex-only
context-GC, email-consent, browser-lifecycle, browser-input-quarantine, and
Hermes transport obligations are covered. Worktree subrules have separate
checks and mutation fixtures for each safeguard. A historical marker on the
matching line or directly preceding line invalidates a policy.

`python3 -m unittest scripts/test_check_standing_rules.py`: **45 tests, OK**. Fixtures cover
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
The real `--files` entrypoint checks quit, kill, replace, move, delete, and
overwrite protections for the running bb app and `/Applications/bb.app` as six
separate rules. Intact rendered files pass; deletion and reversal mutations for
each rule across Claude, Codex, OpenCode, and bb fail (48 CLI cases).
The real `--files` entrypoint now also requires every delegation, child-cap,
dependency, and broker boundary in standalone provider proposals. A subprocess
fixture runs all 12 mutations against each of Claude, Codex, and OpenCode;
all 36 cases fail as required. Another standalone `--files` fixture deletes
the node_modules symlink ban and low-disk install/build limit from each provider
proposal and requires rejection. Both safeguards also pass against all four
unchanged homes and the kit source.
The standalone provider fixture also weakens one-writer-per-worktree,
no-sibling-edits, stop-on-collision, and survivor re-read of `git diff`; all
four mutations are rejected for each of Claude, Codex, and OpenCode.
Another standalone provider fixture independently deletes and reverses
single-flight-per-target and push-is-not-completion clauses for all three
providers; all 12 `--files` mutations are rejected.
The active-session fixture separately deletes and reverses the skill trigger,
adapter-only attestations, authenticated exact-lease supersede chain, forbidden
supersede input classes, and write-owner mismatch block in each provider; all
30 `--files` mutations are rejected.
The app/bundle fixtures separately delete and reverse the quit, kill, replace,
move, delete, and overwrite prohibitions in all four rendered homes; all 48
`--files` mutations are rejected. A second fixture wraps a task exception onto
the following line for each prohibition and adds task-specific `you may`,
`you are explicitly permitted to`, `you are explicitly allowed to`, temporary
and intervening-adverb permission forms, including multiword modifiers, and
explicit allowed-permission sentences; all 240
exception and permission mutations fail through `--files`.
Each mutation supplies all four rendered homes as separate `--files`
candidates, changing the same rule in each; the checker reports each path
independently and all four must fail. All four intact rendered homes pass
together.
Codex-scoped deletion fixtures cover each context-GC
obligation and the ban on garbage-collecting repositories, journals, user-owned
sessions, or active sessions.

Baseline checker stdout:

```text
PASS all 5 files contain all applicable rules (20 regexes)
```

Final checker stdout (live homes + kit source; current head):

```text
PASS all 5 files contain all applicable rules (109 regexes)
```

Rendered-home checker stdout:

```text
PASS all 5 files contain all applicable rules (109 regexes)
```

Unit-test stdout:

```text
Ran 45 tests
OK
```

Safety-hook block policy has a dedicated regex and contradiction veto. Through
the real `--files` entrypoint, each of four intact rendered homes passes;
deletion, direct bypass permission, an `unless necessary` exception, and
task-specific `explicitly permitted/allowed to bypass` clauses, direct
task-specific commands for quit, kill (including “forcibly kill”), replace,
move, delete, and overwrite of the running app/bundle, including each action
phrased “you must [action],” both
with “also” and “first,”
colon-delimited task prefixes, parenthetical/punctuated command modifiers,
and en/em dash delimited modifiers,
`never`/`do not` exception forms, passive permission, and conditional action
forms, condition-first bypass forms, and exception-before-prohibition variants
all fail for each home (492 direct contradiction assertions). The actual
`--files` entrypoint rejects direct commands, bold-formatted app/bundle targets,
bare “bb app” targets, and “Do not wait, [action]” for all six actions in all
four rendered homes. The checker also passes all four
unchanged live-home files and the kit source. Markdown “must not [action]”
controls pass for all six actions in all four rendered homes.

After generalizing direct-command detection across all six app/bundle actions
and their “you must,” “you must also,” “you must first,” colon-prefixed,
parenthetical/punctuated, and dash-delimited modifier forms, including e.g.
abbreviations, line breaks, and parenthetical modifiers between each action and
target; six Markdown-negated controls per rendered home still pass. The complete
test module passed again (46 tests, 153.096s).
The focused case passes all four intact homes and rejects each appended command
through `--files` for every rendered home.

The hash-confirmed kit baseline at Card 21 start is also a regression fixture.
The reusable `--preserve-baseline` mode selects every standing-rule regex that
matches that exact source and requires it to match the current kit source; the
unit suite deletes each of those 42 matched clauses in turn and requires a
failure.

Latest baseline-preservation and current-home CLI output:

```text
PASS /Users/alexandrebrandizzi/.claude/CLAUDE.md: 64 applicable standing rules
PASS /Users/alexandrebrandizzi/.codex/AGENTS.md: 73 applicable standing rules
PASS /Users/alexandrebrandizzi/.config/opencode/AGENTS.md: 69 applicable standing rules
PASS /Users/alexandrebrandizzi/.bb/AGENTS.md: 63 applicable standing rules
PASS /Users/alexandrebrandizzi/projects/wt-card21-shorter-instructions/GLOBAL_AGENTS.md: 102 applicable standing rules
PASS /Users/alexandrebrandizzi/projects/wt-card21-shorter-instructions/GLOBAL_AGENTS.md: retained all 42 rules matched in proposals/card21/baseline/GLOBAL_AGENTS.card21-baseline.md
PASS all 5 files contain all applicable rules (109 regexes)
```

Live homes were not modified. The renderer remains in proposal mode; its
`--install` option was not run.
