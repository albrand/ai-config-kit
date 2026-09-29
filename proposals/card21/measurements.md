# Card 21 instruction size measurements

After sizes are rendered proposals, not installed homes. Approximate tokens use
bytes / 4. Home and kit before sizes were measured before editing on 2026-09-28.
The kit baseline is the exact `GLOBAL_AGENTS.md` blob at the initial Card 21
worktree commit `b6775918a3f749bc643c76094aee8cedac5dbb11` (42,565 bytes,
SHA-256 `e1adb62a75f5732501d66366d91e8ac00e84d5253156628be752d065878bb465`);
the archived source and preservation comparison are in `baseline/` and
`kit-preservation.md`.
The provider context includes the bb baseline appended to every provider-backed
thread; `bb guide agent-configuration` confirmed Codex also reads its native
global file. Before sizes come from direct `wc -c` of the unchanged home files.
The four full-context home diffs reconstruct byte-for-byte to the unchanged
live homes; hashes are recorded in `live-home-hashes.md`. An earlier extraction
mistakenly skipped a Claude source line beginning `--topic` because the diff
prefix made it start `---`; the corrected reconstruction skips only headers.

| File/context | Before bytes | Proposed after bytes | Before tokens approx. | After tokens approx. | Reduction |
|---|---:|---:|---:|---:|---:|
| Claude home | 45,926 | 7,661 | 11,482 | 1,915 | 83.3% |
| Codex home | 52,922 | 10,573 | 13,231 | 2,643 | 80.0% |
| OpenCode home | 41,853 | 9,485 | 10,463 | 2,371 | 77.3% |
| bb baseline | 27,268 | 22,733 | 6,817 | 5,683 | 16.6% |
| Kit `GLOBAL_AGENTS.md` | 42,565 | 21,777 | 10,641 | 5,444 | 48.8% |
| **Claude + bb context** | **73,194** | **30,394** | **18,299** | **7,599** | **58.5%** |
| **Codex + bb context** | **80,190** | **33,306** | **20,048** | **8,327** | **58.5%** |

Both requested agent contexts exceed the 40% reduction target. Live homes remain
unchanged pending the user's review.

## Line counts

| Context file | Before lines | Proposed after lines |
|---|---:|---:|
| Claude home | 710 | 48 |
| Codex home | 838 | 72 |
| OpenCode home | 688 | 71 |
| bb baseline | 432 | 134 |
| Kit `GLOBAL_AGENTS.md` | 715 | 125 |
