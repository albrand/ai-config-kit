# Live home fingerprints before the request-contract update

Captured read-only on 2026-10-01 after #31 was installed and before #32 is
installed. `render-standing-homes.py --check` at 219fe6e reported all four live
homes equal to that commit's render. Installation must use reviewed, merged
sources and refuse if any target differs from these exact pre-installation
fingerprints. Replacements preserve backups under the existing compare-and-swap
installer. No installation claim is made by this capture.

| Home | SHA-256 observed before install |
|---|---|
| Claude | `47e39d6a5e545e949a7283c01521677dbfebbe69ad88ec614ea9285780774a60` |
| Codex | `83b424d810ac633763b4b66ff1dbb788acc332603a94e22f8978785328a53e08` |
| OpenCode | `86175d5e0cd3588d8199ea3c02331a75b8edc45f1fa5f9f1e311c6d72ad8e304` |
| bb | `25bfd8afbab3cfd42841c9b4a2ac6a7c5c8f20b86c41dd286edb07375dda97ed` |
