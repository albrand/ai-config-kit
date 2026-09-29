# Card 21 instruction size measurements

After sizes are rendered proposals, not installed homes. Approximate tokens use
bytes / 4. Home and kit before sizes were measured before editing on 2026-09-28.
The provider context includes the bb baseline appended to every provider-backed
thread; `bb guide agent-configuration` confirmed Codex also reads its native
global file. Before sizes come from direct `wc -c` of the unchanged home files.
The four full-context home diffs reconstruct byte-for-byte to the unchanged
live homes; hashes are recorded in `live-home-hashes.md`. An earlier extraction
mistakenly skipped a Claude source line beginning `--topic` because the diff
prefix made it start `---`; the corrected reconstruction skips only headers.

| File/context | Before bytes | Proposed after bytes | Before tokens approx. | After tokens approx. | Reduction |
|---|---:|---:|---:|---:|---:|
| Claude home | 45,926 | 6,900 | 11,482 | 1,725 | 85.0% |
| Codex home | 52,922 | 8,929 | 13,231 | 2,232 | 83.1% |
| OpenCode home | 41,853 | 8,041 | 10,463 | 2,010 | 80.8% |
| bb baseline | 27,268 | 20,363 | 6,817 | 5,091 | 25.3% |
| Kit `GLOBAL_AGENTS.md` | 42,565 | 19,365 | 10,641 | 4,841 | 54.5% |
| **Claude + bb context** | **73,194** | **27,263** | **18,299** | **6,816** | **62.8%** |
| **Codex + bb context** | **80,190** | **29,292** | **20,048** | **7,323** | **63.5%** |

Both requested agent contexts exceed the 40% reduction target. Live homes remain
unchanged pending the user's review.
