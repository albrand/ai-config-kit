# Card 21 instruction size measurements

After sizes are rendered proposals, not installed homes. Approximate tokens use
bytes / 4. Home and kit before sizes were measured before editing on 2026-09-28.
The provider context includes the bb baseline appended to every provider-backed
thread; `bb guide agent-configuration` confirmed Codex also reads its native
global file.

| File/context | Before bytes | Proposed after bytes | Before tokens approx. | After tokens approx. | Reduction |
|---|---:|---:|---:|---:|---:|
| Claude home | 45,926 | 3,417 | 11,482 | 854 | 92.6% |
| Codex home | 52,922 | 4,540 | 13,231 | 1,135 | 91.4% |
| OpenCode home | 41,853 | 4,063 | 10,463 | 1,016 | 90.3% |
| bb baseline | 27,268 | 16,627 | 6,817 | 4,157 | 39.0% |
| Kit `GLOBAL_AGENTS.md` | 42,565 | 15,751 | 10,641 | 3,938 | 63.0% |
| **Claude + bb context** | **73,194** | **20,044** | **18,299** | **5,011** | **72.6%** |
| **Codex + bb context** | **80,190** | **21,167** | **20,048** | **5,292** | **73.6%** |

Both requested agent contexts exceed the 40% reduction target. Live homes remain
unchanged pending the user's review.
