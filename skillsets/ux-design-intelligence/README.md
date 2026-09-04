# UI/UX Design Intelligence Skillset

This skillset vendors the useful, self-contained design-intelligence portion of
[`nextlevelbuilder/ui-ux-pro-max-skill`](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)
for global use across Codex, Claude Code, bb, OpenCode, and other agents that read
the shared skill library.

It adds:

- local, offline BM25 search over UI/UX, accessibility, responsive-layout,
  typography, color, chart, motion, React, Next.js, and component-stack guidance;
- focused design-system generation for new products, with explicit protection for
  existing product tokens and brand systems;
- a static accessibility/performance checklist that can be loaded without running
  the search tool;
- upstream validation plus 130 self-contained regression tests.

It intentionally does not import the upstream CLI, galleries, screenshots,
marketing site, generated platform templates, or unrelated banner/slides skills.
Those assets add installation and maintenance surface without improving the
shared design-review workflow.

Four upstream tests coupled to repository-root catalog generators are excluded
with those generators. The 130 tests owned by the vendored skill remain intact.

`ux-design-agent` remains the workflow owner for product discovery, source of
truth, signoff, and handoff. `ui-ux-pro-max` is the searchable evidence layer used
inside that workflow.

## Source and license

- Upstream repository: `https://github.com/nextlevelbuilder/ui-ux-pro-max-skill`
- Imported commit: `f3ac195224eac1eb0dfe1a3059c2a6add78ffbe3`
- Upstream package version: `2.13.0`
- License: MIT; the upstream license is preserved in
  `shared/ui-ux-pro-max/LICENSE`.

## Validate

```bash
python3 skillsets/ux-design-intelligence/shared/ui-ux-pro-max/scripts/validate_data.py
python3 -m unittest discover \
  -s skillsets/ux-design-intelligence/shared/ui-ux-pro-max/scripts/tests \
  -p 'test_*.py'
node scripts/publish.mjs --check
```

## Publish locally

The shared skill is discovered by `scripts/publish.mjs` and can be installed into
the configured local agent skill roots. Publishing the entire library can replace
local drift, so inspect `--check` output first. For a bounded import, copy only
`shared/ui-ux-pro-max/` into the desired agent skill roots.
