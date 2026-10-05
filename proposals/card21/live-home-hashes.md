# Live home fingerprints before the pending full-picture update

Captured read-only on 2026-10-05. Each live home was rendered from commit
`dbf21b728ca86d3be1660ea35d23c269761fb291` (immediately before PR #46) into a
temporary directory and compared byte-for-byte; all four live homes matched.
No live-only lines were found. These fingerprints let the compare-and-swap
installer recognize that verified pre-#46 baseline before installing the
reviewed, merged sources.

To refresh this manifest, first render the currently accepted baseline into a
temporary directory and require all four live files to match exactly. Then run
`shasum -a 256 ~/.claude/CLAUDE.md ~/.codex/AGENTS.md ~/.config/opencode/AGENTS.md ~/.bb/AGENTS.md`
and copy those command-produced digests into the table below. Do not update
fingerprints for unmatched files or use the manifest to waive a live-home
difference.

| Home | SHA-256 verified before install |
|---|---|
| Claude | `22b46f2f071acdaf10faa9380e38731e56e40670f83bec4c4a793d6c4a72f970` |
| Codex | `f8e2cc523e504419781bb5a5a089a09431ea9be2c7abf1ee2843ae93ea7a9f9b` |
| OpenCode | `a2c5ee4e1d1c7f6ba80aa59c58511be4d11dfe0d70a4f1008734e787ec2d1292` |
| bb | `7e3e22ce2effbdb92d95f58627b706db88d72d4066173db909af43406adc94fb` |
