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
| Claude home | 45,926 | 3,480 | 11,482 | 870 | 92.4% |
| Codex home | 52,922 | 5,034 | 13,231 | 1,259 | 90.5% |
| OpenCode home | 41,853 | 4,577 | 10,463 | 1,144 | 89.1% |
| bb baseline | 27,268 | 19,088 | 6,817 | 4,772 | 30.0% |
| Kit `GLOBAL_AGENTS.md` | 42,565 | 18,090 | 10,641 | 4,523 | 57.5% |
| **Claude + bb context** | **73,194** | **22,568** | **18,299** | **5,642** | **69.2%** |
| **Codex + bb context** | **80,190** | **24,122** | **20,048** | **6,030** | **69.9%** |

Both requested agent contexts exceed the 40% reduction target. Live homes remain
unchanged pending the user's review.
