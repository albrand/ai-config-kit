# Ledger and request-contract procedure

## The ledger

`~/.local/state/agent-quality/scope/<thread_id>.json`, one per coordinator
thread:

- `purposes`: `{id: "P1", text, done_when, status, evidence, status_marked_at, ask}`.
  - `text` is the user's own words, verbatim.
  - `status` is `open`, `done` or `blocked-on-user`.
- `accepted_revisions`: `{quote, accepted_at, source}`. Each entry is a scope
  change the user approved, quoted verbatim.

```sh
G=~/.claude/skills/scope-ledger/scripts/scope-gate.py
python3 $G init <thread> --from ledger.json        # refuses to overwrite
python3 $G add <thread> --text "<user's words>" --done-when "<observable end state>"
python3 $G mark <thread> P2 blocked-on-user --ask "<the exact question for the user>"
python3 $G mark <thread> P1 done --evidence "<commit / URL / measurement>"
python3 $G revise <thread> --quote "<the user's approval, verbatim>" --source <ref>
python3 $G show <thread>
python3 $G check <thread> "<brief text>"           # the gate's decision, no tool call
```
## Request contract

For requests with two or more outcomes, or a named target, persona, or
constraint, keep a request contract as a review step; it is not a gate. Before
the first edit, external call, or delegation, write:

- `target`: the repository, environment, file, and persona as relevant;
- `outcomes`: one row per requested outcome, in the user's words;
- `constraints`: the user's limits and permissions;
- `state_claims`: the latest state claims the work relies on.

At closeout, mark every outcome `complete` with evidence or `blocked` with the
exact blocker. Use a JSON contract with those four fields; each outcome row has
`request`, `status`, `evidence`, and `blocker`. After closeout, record metadata:

```sh
python3 ~/.agents/skills/scope-ledger/scripts/request-contract-log.py \
  <contract.json> --thread-id <thread-id>
```

The logger stores only the thread id, row count, and status counts in
`~/.local/state/agent-quality/events.jsonl`. When a sandbox cannot write there
(Codex workspace-write), it appends to `/tmp/agent-quality-<uid>/events.jsonl`,
a directory only that user can enter. Count uptake from both files with
`python3 ~/.agents/skills/scope-ledger/scripts/request-contract-uptake.py --since <iso> --exclude-tree <thread>`.
If both fail, note the failure and continue; this review step never blocks work.
