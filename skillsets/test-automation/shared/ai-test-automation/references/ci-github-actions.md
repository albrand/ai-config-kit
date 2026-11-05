# GitHub Actions template

```yaml
name: QA gate
on: [pull_request]
permissions:
  contents: read
jobs:
  qa:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - run: node qa/bin/qa.mjs plan --base origin/${{ github.base_ref }}
      - run: node qa/bin/qa.mjs judge --base origin/${{ github.base_ref }}
````
Configure this check as required in branch protection. Add a separate QA repo PR workflow running `check-scenarios`; do not expose secrets to test execution.
