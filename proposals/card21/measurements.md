# Card 21 instruction size measurements

After sizes are rendered proposals, not installed homes. Approximate tokens use
bytes / 4. Home and kit before sizes were measured before editing on 2026-09-28.
The provider context includes the bb baseline appended to every provider-backed
thread; `bb guide agent-configuration` confirmed Codex also reads its native
global file. Before sizes come from direct `wc -c` of the unchanged home files.
For Claude, direct file bytes and old-side bytes reconstructed from the refreshed
unified diff both equal 45,926; the earlier 45,848 hunk estimate was superseded.

| File/context | Before bytes | Proposed after bytes | Before tokens approx. | After tokens approx. | Reduction |
|---|---:|---:|---:|---:|---:|
| Claude home | 45,926 | 3,441 | 11,482 | 860 | 92.5% |
| Codex home | 52,922 | 4,995 | 13,231 | 1,249 | 90.6% |
| OpenCode home | 41,853 | 4,087 | 10,463 | 1,022 | 90.2% |
| bb baseline | 27,268 | 16,694 | 6,817 | 4,174 | 38.8% |
| Kit `GLOBAL_AGENTS.md` | 42,565 | 15,818 | 10,641 | 3,955 | 62.8% |
| **Claude + bb context** | **73,194** | **20,135** | **18,299** | **5,034** | **72.5%** |
| **Codex + bb context** | **80,190** | **21,689** | **20,048** | **5,422** | **73.0%** |

Both requested agent contexts exceed the 40% reduction target. Live homes remain
unchanged pending the user's review.
