# QA test builder

A skill for QA people who know Playwright but not the application code. They
name the tickets; their AI agent reads them, asks every open question, designs
scenarios against the acceptance criteria, writes and proves the Playwright
tests (UI or API), reports through Allure, and sets up CI so pull requests are
gated on those tests. It works on repositories with a full QA setup, a partial
one, or nothing at all, frontend or backend, with the tests in the app
repository or in a separate one.

It needs only two things from the QA: read access to the board, and write
access to the repository that will hold the tests.

## Install

### Claude Code (plugin)

```
claude plugin marketplace add albrand/ai-config-kit
claude plugin install qa-test-builder@ai-config-kit
```

Update later with `claude plugin marketplace update ai-config-kit` and
`claude plugin update qa-test-builder@ai-config-kit`.

To offer it to everyone who opens a project, commit this to the project's
`.claude/settings.json`; Claude Code asks each person to trust the project and
then loads the plugin:

```json
{
  "extraKnownMarketplaces": {
    "ai-config-kit": { "source": { "source": "github", "repo": "albrand/ai-config-kit" } }
  },
  "enabledPlugins": { "qa-test-builder@ai-config-kit": true }
}
```

### Codex, Cursor and other agents

Copy the skill folder into the agent's skills directory:

```
git clone --depth 1 https://github.com/albrand/ai-config-kit /tmp/ai-config-kit
mkdir -p ~/.agents/skills
cp -R /tmp/ai-config-kit/skillsets/qa-test-builder/skills/qa-test-builder ~/.agents/skills/
```

Codex and Cursor read `~/.agents/skills/`. Cursor also reads `~/.claude/skills/`.

## Use

Connect the agent to the board (an Atlassian, Linear or GitHub MCP server, or
the board's CLI), open the repository, and ask, for example:

> Create the test scenarios for PROJ-123 and PROJ-130.

The agent works in phases and stops at each gate: survey the repository and
ask where tests should live, read the tickets and ask questions one at a time,
show the scenario table for confirmation, build the test layer if needed,
write and prove each test, wire CI, and offer to post results on the board.

## Files

- `skills/qa-test-builder/SKILL.md`: the procedure and its gates.
- `skills/qa-test-builder/references/`: loaded as each phase needs them:
  `repo-survey.md`, `ticket-reading.md`, `scenario-design.md`,
  `framework-blueprint.md`, `writing-tests.md`, `allure.md`, `ci-same-repo.md`,
  `ci-separate-repo.md`, `qa-authorship.md`, `board-reporting.md`,
  `definition-of-done.md`.

The skill carries no framework code. The blueprint describes the contracts and
the agent builds the QA layer for each repository in that repository's own
idiom.
