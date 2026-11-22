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
| Claude home | 45,926 | 7,888 | 11,482 | 1,972 | 82.8% |
| Codex home | 52,922 | 10,800 | 13,231 | 2,700 | 79.6% |
| OpenCode home | 41,853 | 9,712 | 10,463 | 2,428 | 76.8% |
| bb baseline | 27,268 | 23,420 | 6,817 | 5,855 | 14.1% |
| Kit `GLOBAL_AGENTS.md` | 42,565 | 22,464 | 10,641 | 5,616 | 47.2% |
| **Claude + bb context** | **73,194** | **31,308** | **18,299** | **7,827** | **57.2%** |
| **Codex + bb context** | **80,190** | **34,220** | **20,048** | **8,555** | **57.3%** |

Both requested agent contexts exceed the 40% reduction target. Live homes remain
unchanged pending the user's review.

## Line counts

| Context file | Before lines | Proposed after lines |
|---|---:|---:|
| Claude home | 710 | 48 |
| Codex home | 838 | 72 |
| OpenCode home | 688 | 71 |
| bb baseline | 432 | 135 |
| Kit `GLOBAL_AGENTS.md` | 715 | 126 |
