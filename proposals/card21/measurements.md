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
| Claude home | 45,926 | 3,417 | 11,482 | 854 | 92.6% |
| Codex home | 52,922 | 4,540 | 13,231 | 1,135 | 91.4% |
| OpenCode home | 41,853 | 4,063 | 10,463 | 1,016 | 90.3% |
| bb baseline | 27,268 | 16,670 | 6,817 | 4,168 | 38.9% |
| Kit `GLOBAL_AGENTS.md` | 42,565 | 15,794 | 10,641 | 3,949 | 62.9% |
| **Claude + bb context** | **73,194** | **20,087** | **18,299** | **5,022** | **72.6%** |
| **Codex + bb context** | **80,190** | **21,210** | **20,048** | **5,303** | **73.6%** |

Both requested agent contexts exceed the 40% reduction target. Live homes remain
unchanged pending the user's review.
