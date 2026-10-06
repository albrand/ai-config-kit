# Writing

One skill for text people read: PR bodies, QA steps for testers, reports, docs, and marketing copy.

| Skill | Use |
|---|---|
| `no-ai-slop` | Edit a draft so it reads as a person wrote it, keeping the writer's voice, or flag the AI-writing patterns in it without rewriting. |

## Provenance

`shared/no-ai-slop/` is a vendored copy of [petergyang/no-ai-slop](https://github.com/petergyang/no-ai-slop), MIT licence (`shared/no-ai-slop/LICENSE`), pinned to commit `000650b156983f5159695b441477f4e63b25dc85`:

| File | Upstream path | SHA-256 |
|---|---|---|
| `SKILL.md` | `skills/no-ai-slop/SKILL.md` | `992b365f51a2f62cf4c1c5ed22049a9ee551dfea677550c1a72b371c0ceadd62` |
| `eval.md` | `skills/no-ai-slop/eval.md` | `8ad8d83ed1abe7fc054ad74966bfca64fc182bc71f59d701b24b962c39d11ad7` |
| `LICENSE` | `LICENSE` | `b7a7fe370cc4c9e974528c7cea7841cf8ac886bc9ed947edb11b289441fba4a8` |

The files are unmodified. To update, fetch the new commit's files, read the diff (the skill must stay plain writing guidance, with no commands, URLs or tool instructions), then update the commit and the digests here.

## Install

```sh
sh skillsets/writing/install.sh
```

It copies `shared/no-ai-slop` into each skill home that exists (`~/.agents`, `~/.bb`, `~/.claude`, `~/.codex`), after checking the digests above.
