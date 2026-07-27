---
name: orca-browser-safety
description: >-
  Enforce isolated Orca-only interactive browsing and ownership-safe browser
  page hygiene. Use for website navigation, browser E2E, visual inspection,
  authentication, screenshots, DOM, console, network, or page interaction.
---

# Orca Browser Safety

Use Orca's embedded browser as the only agent-driven interactive browser
surface. Load the version-matched `orca-cli` guide with `orca skills get
orca-cli` before browser commands.

## Mandatory boundary

- Use an isolated browser profile scoped to the current workspace. Never use a
  `default` or `imported` profile.
- Resolve the full current worktree ID. Use it for browser discovery and page
  creation. After creation, every page-scoped command must include that
  worktree ID and the returned full `browserPageId`; never rely on active-page
  or focused-tab state.
- Never use Computer Use, accessibility APIs, AppleScript, browser extensions
  in a user's browser, external Chrome/Safari/Firefox, OS mouse/keyboard
  automation, focus switching, or clipboard operations for browser work.
- Never use `orca computer ...` for browser windows, webviews, or
  authentication. Do not control or close the user's personal browser.
- Never use `tab switch`, `terminal switch`, `--focus`, clipboard read/write,
  or unqualified browser input. Target the recorded page directly.
- Headless repository-owned browser suites may run as tests. They do not permit
  interactive-browser fallback or attachment to a personal browser.
- If Orca's embedded browser cannot do the task, report the blocker. Do not
  substitute another browser surface.

## Isolated page lifecycle

1. Confirm `orca status --json`, resolve the full worktree ID, and list browser
   profiles/pages for only that worktree.
2. Reuse an isolated workspace-scoped profile, or create one with a neutral
   label. Create a page with explicit worktree and profile, without focus.
3. Record the returned full `browserPageId` in the task state as owned by this
   agent. Use that exact ID and full worktree ID for every navigation, snapshot,
   interaction, wait, evaluation, network, console, screenshot, and close
   command. Re-snapshot after page changes.
4. Reuse an owned page only while the same bounded browser slice still needs
   it. Create a separate explicit page for a separate slice when needed.
5. As soon as the slice is done, blocked, abandoned, or superseded, close every
   no-longer-needed page whose ID this agent recorded during the current task.
   Do not defer cleanup to unrelated later work. Before close-out, list pages
   for the exact worktree and report any owned pages left open.
6. Never close unknown, pre-existing, user-owned, default/imported-profile, or
   another agent's page. When ownership is uncertain, leave it open and report
   the uncertainty.

## Authentication and data

- Keep login state inside the isolated profile. Never export or serialize
  cookies, credentials, authentication state, environment variables, pairing
  data, or socket capabilities.
- When human authentication is required, ask the user to perform it in Orca's
  embedded browser. Never redirect them to a personal browser.
- Accept a user-provided MFA code through conversation and enter it only into
  the explicitly targeted Orca page. Never derive, inspect, or export MFA
  secrets.

## Completion evidence

Report the isolated profile label, worktree ID, each owned page ID, whether it
was closed, any owned leftover after the final page listing, and any
authentication or Orca capability blocker. Never claim interactive browser
verification from source inspection or headless tests alone.
