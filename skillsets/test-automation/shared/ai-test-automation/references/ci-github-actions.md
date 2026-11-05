# GitHub Actions template

The QA repository owns definitions/tests. Set `QA_REPOSITORY`, a read-only `QA_READ_TOKEN`, and code such that the application test command does not receive that token. Configure this check as required in branch protection. Draft pull requests may not trigger build validation.

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
      - uses: actions/checkout@v4
        with:
          repository: ${{ vars.QA_REPOSITORY }}
          ref: main
          path: .qa-authority
          token: ${{ secrets.QA_READ_TOKEN }}
          persist-credentials: false
      - name: Plan linked and regression scenarios
        run: node .qa-authority/qa/bin/qa.mjs plan --base origin/${{ github.base_ref }}
      - name: Install authoritative tests over branch copies
        run: node .qa-authority/qa/bin/qa.mjs install-authoritative --source .qa-authority --target .
      - name: Execute QA tests without secrets
        env: {}
        run: npm test -- --reporter=junit
      - name: Judge and report
        if: always()
        run: node .qa-authority/qa/bin/qa.mjs judge --base origin/${{ github.base_ref }}
```

The test step has no board or checkout token. Keep generated authoritative files outside commit scope and report any branch copies ignored by the overlay.
