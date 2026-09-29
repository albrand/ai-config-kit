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
| Claude home | 45,926 | 4,378 | 11,482 | 1,095 | 90.5% |
| Codex home | 52,922 | 5,932 | 13,231 | 1,483 | 88.8% |
| OpenCode home | 41,853 | 5,475 | 10,463 | 1,369 | 86.9% |
| bb baseline | 27,268 | 19,738 | 6,817 | 4,934 | 27.6% |
| Kit `GLOBAL_AGENTS.md` | 42,565 | 18,740 | 10,641 | 4,685 | 56.0% |
| **Claude + bb context** | **73,194** | **24,116** | **18,299** | **6,029** | **67.1%** |
| **Codex + bb context** | **80,190** | **25,670** | **20,048** | **6,418** | **68.0%** |

Both requested agent contexts exceed the 40% reduction target. Live homes remain
unchanged pending the user's review.
