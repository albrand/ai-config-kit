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

The board credential must never be reachable from the pull request. A job in
`qa-gate` is not safe even without a checkout: on `pull_request` events the
workflow file comes from the pull request, so a branch could rewrite the job
and print the secret. Put the reporting in a `workflow_run` workflow, like
`qa-approval` (or as a step of it):

- triggered when `qa-gate` completes, so it runs the default branch's file;
- never checks out or runs the pull request's code; it downloads
  `verdict.json` from the triggering run as data;
- takes the pull request number, head SHA, title and body from the API, and
  re-extracts the ticket keys from them with `board.keyPattern`; it posts only
  to those keys, never to keys read from the artifact;
- treats titles and error lines from the artifact as untrusted text: caps
  their length and strips links and mentions before posting;
- skips pull requests from forks;
- puts the secrets only in that step's environment;
- never fails: if the board is down, it logs and exits 0.

## Proving it works

1. With the QA, pick one ticket and a pull request that names it.
2. Show the exact comment text you will post and get their approval for that
   post.
3. Run the pipeline, then fetch the ticket through the board tool and confirm
   the comment is there with the right content.
4. Push another commit and confirm the same comment was edited, not duplicated.

Report the ticket, comment link and run links.
