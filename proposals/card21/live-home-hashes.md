# Live home noninstallation evidence

These SHA-256 values were captured after final proposal rendering. The renderer
read each home and wrote only to the proposal/diff directories; `--install` was
never run. No task command wrote to a live home. The files therefore remained
at the same content observed during the initial inventory and diff generation.
No pre-edit digest was captured, so the identity claim rests on the recorded
read-only command sequence rather than a pair of independently timestamped
hash snapshots.

| Home | SHA-256 after proposal rendering |
|---|---|
| Claude | `e84334424e03baef698279c184de2ef252891124b70e549924c2d17f0f5a05cd` |
| Codex | `2f7433b7928b17aacbe3988519788300760e8239c840121db5cf3b1f089d871b` |
| OpenCode | `79ce2b7596ccf3b90f4e8d3eecde4e070f236c92e3e90e84af3aea67f39acae2` |
| bb | `db5814411d08fa2deb320e51582326e8e8a245020e262b74f4e2a3724c97283c` |

All four homes report the same modification time: `2026-09-28 17:00:01`.
The task's first home inventory was taken on 2026-09-28; the unchanged earlier
modification time is additional evidence that no installation occurred.

The four full-context diffs were generated with
`scripts/render-standing-homes.py --full-context-diffs`. Reconstructing the old
side after skipping the two file-header lines matches each live source byte for
byte, including Claude at 45,926 bytes and SHA-256
`e84334424e03baef698279c184de2ef252891124b70e549924c2d17f0f5a05cd`. Hermes's
earlier 45,848-byte result came from a parser that discarded any diff line
starting `---`; that also dropped Claude's original `--topic ...` source line
after the diff added its own leading `-`. The corrected extraction skips only
the two headers; all four old-side hashes now match their homes.
