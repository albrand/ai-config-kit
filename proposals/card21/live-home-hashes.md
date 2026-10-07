# Live home fingerprints

The installer is compare-and-swap: it accepts a live set only when all four
files match one complete profile below. It never combines hashes from different
profiles. Accepted live profiles include the #47 and #49 renders and
the #50, #51 and #60 renders; #60 is installed in all four homes. The current rendered profile is the
output of this source revision; keeping it here means that after this revision
is merged and installed, the next installer recognizes that complete set
without weakening the live-edit guard.

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

### Accepted live profile: #49 render at 73786e99

Verified byte-for-byte against all four current live homes by comparing them
with the committed #49 render. Digests below are the command-produced SHA-256
values for those live files.

| Home | SHA-256 |
|---|---|
| Claude | `a6af822320f1bc7af0f73de5ec740861a363f5a6c0e8d312575474bc1a28b69d` |
| Codex | `6345c59c8c1db69db95d160c34bd58ffd6ac8190f01b222e1ba3d900226049f4` |
| OpenCode | `53f511c69b684efdb6ceff00ba8f7babd0439ac801243696d3317bbce884c385` |
| bb | `4c8b614fcbd7454ba2b41fcc2fc6e919c993b49c61e72250b1b14bd4f973cbab` |

### Accepted live profile: #50 render at 192f652a

Verified byte-for-byte against all four current live homes on 2026-10-06 by
comparing them with the committed #50 render. Digests below are the
command-produced SHA-256 values for those live files.

| Home | SHA-256 |
|---|---|
| Claude | `b3bdd0c2f423a50d0d1640c5e6c313f82cf38aee81fa86ebd797e0f3b7f309ad` |
| Codex | `0cc932493b3b4b58c3f26831f61285bd9e60a22c997d56037ea8e53d2feeb1d4` |
| OpenCode | `935d2be4fa6c0c629b066b231bb298f7660b8ce07f7b34881894dcedc190f2b8` |
| bb | `db5d8261357900775c7ccdc3d73e2936c945c8e62a75e4dd038d57349d073dd1` |

### Accepted live profile: #51 render at f9e6837 (installed before #56)

Verified byte-for-byte on 2026-10-06: all four live homes equal the output of
`python3 scripts/render-standing-homes.py --output-dir <dir>` at f9e6837, the
last commit before #56. #56 replaced this bb digest in the current rendered
profile without keeping it as an accepted one, so the installer refused the
very homes it had installed.

| Home | SHA-256 |
|---|---|
| Claude | `cf5ca4009d0473f55dfcbe7fb3f0c860f12300581f12e6663bcc252406832fa5` |
| Codex | `e593b4903f6264d813a09ce84c554349e042c193886f4e7ef1b89b44758fe1e7` |
| OpenCode | `ed6919d94821b5c4003c6a603c62783d81350481e7abce90c4d5a7a59d1ec68d` |
| bb | `ec2131079c52a46015df40c4bb53b52d05988b08e82bffc4c61cc46f39e5d1eb` |

### Accepted live profile: #60 render at b55f327 (installed 2026-10-06)

Verified on 2026-10-07: `python3 scripts/render-standing-homes.py --check` at
5be3296 reported all four live homes MATCH. Digests below are the output of
`shasum -a 256` on those live files.

| Home | SHA-256 |
|---|---|
| Claude | `cf5ca4009d0473f55dfcbe7fb3f0c860f12300581f12e6663bcc252406832fa5` |
| Codex | `e593b4903f6264d813a09ce84c554349e042c193886f4e7ef1b89b44758fe1e7` |
| OpenCode | `ed6919d94821b5c4003c6a603c62783d81350481e7abce90c4d5a7a59d1ec68d` |
| bb | `d36a7d65a51f9529e5daca36a4f55598193a6f92295e29ac567ff46033ebd41e` |

### Current rendered profile: one-page bb baseline and restart ban based on 5be3296

Generated with `python3 scripts/render-standing-homes.py`; digests below are the
output of `shasum -a 256` on the files in `proposals/card21/rendered-homes`.

| Home | SHA-256 |
|---|---|
| Claude | `9bc9d866b7fcdd1e760afd7c174cd4cb7f1ad579f0ca6843ce28271bf3260ab1` |
| Codex | `afe6281966c5ffebc3f86aca2fc30ba5109f86c15c611492e6d26a55f605bd33` |
| OpenCode | `f64a39465e92c6701fcd4f908933368eac1589b320eeff790fe46561f8864ec0` |
| bb | `c0c189a02da137b5915c99cffe1e353aa54374ee72109aad460f25bf412ff83c` |

### Superseded profile: pre-#46 render at dbf21b72 (history only)

These were the installer's previous accepted fingerprints. They are retained to
document the old baseline, but the installer does not accept this profile.

| Home | SHA-256 |
|---|---|
| Claude | `22b46f2f071acdaf10faa9380e38731e56e40670f83bec4c4a793d6c4a72f970` |
| Codex | `f8e2cc523e504419781bb5a5a089a09431ea9be2c7abf1ee2843ae93ea7a9f9b` |
| OpenCode | `a2c5ee4e1d1c7f6ba80aa59c58511be4d11dfe0d70a4f1008734e787ec2d1292` |
| bb | `7e3e22ce2effbdb92d95f58627b706db88d72d4066173db909af43406adc94fb` |
