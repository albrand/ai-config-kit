# Azure Pipelines template

```yaml
trigger: none
pr:
  branches:
    include: [ main ]
pool:
  vmImage: ubuntu-latest
steps:
- checkout: self
  fetchDepth: 0
- script: node qa/bin/qa.mjs plan --base origin/main
  displayName: Plan QA
- script: node qa/bin/qa.mjs judge --base origin/main
  displayName: Judge QA
````
Authorize cross-repo resource on first run; protect required PR policy. Keep test step token-free.
