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
| Codex home | 52,922 | 9,690 | 13,231 | 2,423 | 81.7% |
| OpenCode home | 41,853 | 8,802 | 10,463 | 2,201 | 79.0% |
| bb baseline | 27,268 | 22,289 | 6,817 | 5,572 | 18.3% |
| Kit `GLOBAL_AGENTS.md` | 42,565 | 21,333 | 10,641 | 5,333 | 49.9% |
| **Claude + bb context** | **73,194** | **29,950** | **18,299** | **7,488** | **59.1%** |
| **Codex + bb context** | **80,190** | **31,979** | **20,048** | **7,995** | **60.1%** |

Both requested agent contexts exceed the 40% reduction target. Live homes remain
unchanged pending the user's review.

## Line counts

| Context file | Before lines | Proposed after lines |
|---|---:|---:|
| Claude home | 710 | 48 |
| Codex home | 838 | 55 |
| OpenCode home | 688 | 56 |
| bb baseline | 432 | 134 |
| Kit `GLOBAL_AGENTS.md` | 715 | 125 |
