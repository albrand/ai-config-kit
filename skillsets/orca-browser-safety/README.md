# Orca Browser Safety Skillset

This portable skillset constrains agent-driven interactive browsing to Orca's
embedded browser and adds ownership-safe page hygiene: an agent closes only
pages it created and can identify.

## Install

Copy `codex/orca-browser-safety/` as a complete directory to the shared agent
skill root. For Orca installs, use
`~/.agents/skills/orca-browser-safety/`. Then refresh and check the installed
skill router index when one is present. Do not merge it into a personal browser
profile or substitute a desktop/browser automation tool.

## Use

Load `codex/orca-browser-safety/SKILL.md` before interactive navigation,
browser E2E, screenshots, DOM/console/network inspection, or authentication.
Browser discovery and creation use an isolated workspace-scoped profile and the
full worktree ID. Every page-scoped command after creation also uses the
explicit `browserPageId` it targets. The agent records its own page IDs, reuses
them only for the active bounded browser slice, and closes them as soon as that
slice is done, blocked, abandoned, or superseded.

Never close a page whose ownership is unknown or whose owner is another agent
or the user. Leave it open and report it instead.

Validate the source package from the repository root:

```sh
node scripts/validate-codex-skills.cjs
```
