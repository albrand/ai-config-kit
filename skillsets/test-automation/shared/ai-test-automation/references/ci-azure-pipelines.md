# Azure Pipelines template

Declare the QA repository as a repository resource with a read-only service connection. Authorize the cross-repository resource before the first run. Keep the credential out of the test step and protect the PR build policy.

```yaml
trigger: none
pr:
  branches:
    include: [main]
resources:
  repositories:
    - repository: qaAuthority
      type: git
      name: acme-qa/qa-tests
      ref: refs/heads/main
      endpoint: qa-readonly
pool:
  vmImage: ubuntu-latest
steps:
  - checkout: self
    fetchDepth: 0
  - checkout: qaAuthority
    path: s/qa-authority
    persistCredentials: false
  - script: node $(Pipeline.Workspace)/s/qa-authority/qa/bin/qa.mjs plan --base origin/main
    displayName: Plan QA
  - script: node $(Pipeline.Workspace)/s/qa-authority/qa/bin/qa.mjs install-authoritative --source $(Pipeline.Workspace)/s/qa-authority --target .
    displayName: Install QA authority
  - script: npm test -- --reporter=junit
    displayName: Execute tests without secrets
  - script: node $(Pipeline.Workspace)/s/qa-authority/qa/bin/qa.mjs judge --base origin/main
    displayName: Judge QA
    condition: always()
```

Use corresponding deployment environment approvals for DEV, STAGING and PROD. Keep pre-push, PR and release test tiers distinct.
