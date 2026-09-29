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
| Claude home | 45,926 | 6,407 | 11,482 | 1,602 | 86.0% |
| Codex home | 52,922 | 8,436 | 13,231 | 2,109 | 84.1% |
| OpenCode home | 41,853 | 7,548 | 10,463 | 1,887 | 82.0% |
| bb baseline | 27,268 | 20,198 | 6,817 | 5,050 | 25.9% |
| Kit `GLOBAL_AGENTS.md` | 42,565 | 19,200 | 10,641 | 4,800 | 54.9% |
| **Claude + bb context** | **73,194** | **26,605** | **18,299** | **6,651** | **63.7%** |
| **Codex + bb context** | **80,190** | **28,634** | **20,048** | **7,158** | **64.3%** |

Both requested agent contexts exceed the 40% reduction target. Live homes remain
unchanged pending the user's review.
