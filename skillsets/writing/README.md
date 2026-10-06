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

It installs exactly the three files above into each skill home that exists (`~/.agents`, `~/.bb`, `~/.claude`, `~/.codex`). Before touching any home, it refuses if the vendored directory holds any other entry, or if a file is missing or is a link. It then copies the three files once into a private staging directory and checks their digests there. Each home gets those staged copies, checked before and again after they are moved into place. If the installed copy fails that last check, the previous copy is restored and the run exits 1. The source is not read after staging, so a change to it during the run cannot reach a home. `sh skillsets/writing/test-install.sh` exercises each of those cases in a throwaway HOME, including a file changed between the digest check and the copy, and one changed just before the move.
