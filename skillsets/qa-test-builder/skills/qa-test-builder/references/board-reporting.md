# Posting results to the board

Optional. Offer it once the CI gate works: "Do you want each pull request's QA
result posted on its tickets?" If the QA says no, record that and stop here.

## What gets posted

One comment per ticket and pull request, edited on later runs instead of
stacking new ones (find it by a marker such as `[qa-gate PR #42]` in the text):

- the verdict, the commit and the pull request;
- one line per scenario of that ticket: ID, title, passed or failed;
- for failures, the first error line;
- the run link, where the Allure report is downloaded.

No screenshots, data dumps or secrets in the comment. Do not change the
ticket's status, fields or assignee; posting is the whole job.

## Credentials

The person who administers the board creates a credential for a service
account, not for a person, with only the permission to comment on the project:

| Board | Credential | CI secrets |
|---|---|---|
| Jira Cloud | API token of a service user with "Add comments" on the project (scoped token if the site supports it) | `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` |
| Linear | Personal API key of a service user, or an OAuth app with `comments:create` | `LINEAR_API_KEY` |
| GitHub Issues | The GitHub App from CI, with issues: write | already present |
| Azure DevOps | PAT with Work Items: read & write | `ADO_ORG_URL`, `ADO_PAT` |

Walk the administrator through each screen: where to create the user or app,
which permission to tick, where to paste the value in the repository's
Settings → Secrets and variables → Actions. They type the secret; you never
see it, and never ask for it in chat.

## The job

A separate job after the gate, like the comment job:

- `needs: qa-gate`, runs `if: always()` on pull requests from the same
  repository only (never from forks, which must not reach the secrets);
- no checkout of the pull request's code: it downloads `verdict.json` and posts
  from it, so code under review never holds the board credential;
- uses the secrets only in that step's environment;
- posts only for tickets in the plan, and only to keys that match
  `board.keyPattern`;
- never fails the gate: if the board is down, it logs and exits 0.

## Proving it works

1. With the QA, pick one ticket and a pull request that names it.
2. Show the exact comment text you will post and get their approval for that
   post.
3. Run the pipeline, then fetch the ticket through the board tool and confirm
   the comment is there with the right content.
4. Push another commit and confirm the same comment was edited, not duplicated.

Report the ticket, comment link and run links.
