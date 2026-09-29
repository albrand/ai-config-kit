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
| Claude home | 45,926 | 6,357 | 11,482 | 1,589 | 86.2% |
| Codex home | 52,922 | 8,386 | 13,231 | 2,097 | 84.2% |
| OpenCode home | 41,853 | 7,498 | 10,463 | 1,875 | 82.1% |
| bb baseline | 27,268 | 20,144 | 6,817 | 5,036 | 26.1% |
| Kit `GLOBAL_AGENTS.md` | 42,565 | 19,146 | 10,641 | 4,787 | 55.0% |
| **Claude + bb context** | **73,194** | **26,501** | **18,299** | **6,625** | **63.8%** |
| **Codex + bb context** | **80,190** | **28,530** | **20,048** | **7,133** | **64.4%** |

Both requested agent contexts exceed the 40% reduction target. Live homes remain
unchanged pending the user's review.
