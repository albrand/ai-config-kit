# Live home fingerprints

The installer is compare-and-swap: it accepts a live set only when all four
files match one complete profile below. It never combines hashes from different
profiles. The accepted live profile is the #47 render, verified byte-for-byte
against all four current homes on 2026-10-05. The current rendered profile is
the output of this source revision; keeping it here means that after this
revision is merged and installed, the next installer recognizes that complete
set without weakening the live-edit guard.

To update this manifest, render the currently accepted baseline into a
temporary directory and require every live file to match byte-for-byte. Run
`shasum -a 256` on the matched live files and record those command-produced
digests as an accepted live profile. Then render the candidate source and run
`shasum -a 256` on all four outputs; update the current rendered profile from
those command-produced digests. The renderer tests require this profile to
match the current rendered source. Keep older fingerprints under superseded
history; never accept them or use a fingerprint to waive a live-home difference.

### Accepted live profile: #47 render at 539e88a2

Verified against `/tmp/card59-539-render/rendered-homes` with `cmp`; all four
live files matched. Digests below are the output of `shasum -a 256` on the live
files after that comparison.

| Home | SHA-256 |
|---|---|
| Claude | `dadf571ab794b9ad1044965533f1d86ba320022f2120de244375bb93b440d791` |
| Codex | `88dbf9327a772301aecc03baea87613ca8161c8f17687daf48429e8f25464093` |
| OpenCode | `8782ff2a2b448e5403f5c36f44059ed039958127069a1a6db0d20aedd6361f6a` |
| bb | `b819ae2f146f2d9336765004403f13ccebdcd4c4e168ab3d8b6e64ce0864696c` |

### Current rendered profile: PR candidate based on 7cb52e1a

Generated with `python3 scripts/render-standing-homes.py --output-dir
/tmp/card59-render-current/rendered-homes`; digests below are the output of
`shasum -a 256` on those rendered files.

| Home | SHA-256 |
|---|---|
| Claude | `a6af822320f1bc7af0f73de5ec740861a363f5a6c0e8d312575474bc1a28b69d` |
| Codex | `6345c59c8c1db69db95d160c34bd58ffd6ac8190f01b222e1ba3d900226049f4` |
| OpenCode | `53f511c69b684efdb6ceff00ba8f7babd0439ac801243696d3317bbce884c385` |
| bb | `4c8b614fcbd7454ba2b41fcc2fc6e919c993b49c61e72250b1b14bd4f973cbab` |

### Superseded profile: pre-#46 render at dbf21b72 (history only)

These were the installer's previous accepted fingerprints. They are retained to
document the old baseline, but the installer does not accept this profile.

| Home | SHA-256 |
|---|---|
| Claude | `22b46f2f071acdaf10faa9380e38731e56e40670f83bec4c4a793d6c4a72f970` |
| Codex | `f8e2cc523e504419781bb5a5a089a09431ea9be2c7abf1ee2843ae93ea7a9f9b` |
| OpenCode | `a2c5ee4e1d1c7f6ba80aa59c58511be4d11dfe0d70a4f1008734e787ec2d1292` |
| bb | `7e3e22ce2effbdb92d95f58627b706db88d72d4066173db909af43406adc94fb` |
