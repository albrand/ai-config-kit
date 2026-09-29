#!/usr/bin/env python3
"""Check that the always-on safety rules remain in every loaded instruction file."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path


RULES: dict[str, re.Pattern[str]] = {
    "email-compose-send": re.compile(
        r"(?is)never\s+(?:add|fill|populate).{0,160}recipient.{0,160}"
        r"(?:compose|send).{0,100}(?:send|message|email)"
    ),
    "email-exact-message-approval": re.compile(
        r"(?is)(?:approval for that (?:exact|specific) message.{0,80}in\s+(?:the\s+)?(?:current|this)\s+conversation|"
        r"user approving.{0,30}(?:that|the) message.{0,40}in\s+the\s+current\s+conversation)"
    ),
    "email-general-approval-is-insufficient": re.compile(
        r"(?is)(?:general (?:task )?(?:approval|authorization).{0,80}"
        r"(?:is\s+not|does\s+not\s+count\s+as|isn.t).{0,60}(?:email approval|approval for this one)|"
        r"general instruction to proceed.{0,160}NOT\s+approval to email)"
    ),
    "email-other-message-approval-is-insufficient": re.compile(
        r"(?is)(?:approval for another message.{0,80}not approval for this one|"
        r"(?:neither|nor).{0,80}approval.{0,80}(?:different|another) message)"
    ),
    "email-safe-path-verification": re.compile(
        r"(?is)(?:inspect(?:ing)?\s+(?:the\s+)?constructed (?:path|URL|payload|template|handler)|"
        r"constructed (?:URL|payload|template|handler).{0,120}disposable account).{0,180}"
        r"(?:disposable account|never (?:use|fire|send).{0,80}live (?:mail )?client)"
    ),
    "email-open-compose-left-alone": re.compile(
        r"(?is)(?:disclose and leave.{0,80}open.{0,80}compose.{0,80}(?:untouched|alone)|"
        r"if a compose surface.{0,120}already (?:been )?open(?:ed)?.{0,100}(?:disclose|say so plainly).{0,80}leave it alone)"
    ),
    "bb-app-process": re.compile(
        r"(?is)never\s+(?:quit|kill|replace).{0,120}bb.{0,100}app"
    ),
    "bb-app-never-quit": re.compile(
        r"(?is)(?:never quit.{0,60}running bb app|quitting it.{0,80}ends everyone's running work)"
    ),
    "bb-app-never-kill": re.compile(
        r"(?is)(?:never quit,\s*kill.{0,40}running bb app|never kill the running bb app|killing it.{0,80}ends everyone's running work)"
    ),
    "bb-app-never-replace": re.compile(
        r"(?is)(?:never quit,\s*kill or replace.{0,40}running bb app|never quit,\s*kill, or replace.{0,40}running bb app|never replace the running bb app|replacing it.{0,80}ends everyone's running work)"
    ),
    "bb-app-bundle-never-move": re.compile(
        r"(?is)(?:never move `?/Applications/bb\.app|moving, deleting or overwriting `?/Applications/bb\.app.{0,100}ends everyone's running\s+work)"
    ),
    "bb-app-bundle-never-delete": re.compile(
        r"(?is)(?:never delete `?/Applications/bb\.app|moving, deleting or overwriting `?/Applications/bb\.app.{0,100}ends everyone's running\s+work)"
    ),
    "bb-app-bundle-never-overwrite": re.compile(
        r"(?is)(?:never overwrite `?/Applications/bb\.app|moving, deleting or overwriting `?/Applications/bb\.app.{0,100}ends everyone's running\s+work)"
    ),
    "dependencies-no-node-modules-symlink": re.compile(
        r"(?is)never symlink\s+`?node_modules`?"
    ),
    "disk-no-install-build-below-20gb": re.compile(
        r"(?is)below 20 GB free.{0,80}(?:do not install/build|start no(?: new)? installs? or builds?)"
    ),
    "no-pkill-pgrep-app-kill-path": re.compile(
        r"(?is)never\s+use\s+(?:`?pkill`?\s+or\s+`?pgrep\s+-f`?|"
        r"`?pgrep\s+-f`?\s+or\s+`?pkill`?)"
    ),
    "credentials-never-type": re.compile(r"(?is)never.{0,35}\btype\b.{0,50}credentials"),
    "credentials-never-paste": re.compile(r"(?is)never.{0,35}\bpaste\b.{0,50}credentials"),
    "credentials-never-handle": re.compile(r"(?is)never.{0,35}\bhandle\b.{0,50}credentials"),
    "public-exposure": re.compile(
        r"(?is)(?:(?:never|do not).{0,45}(?:publicly\s+expose|expose(?:\s+a)?\s+service|"
        r"run\s+`?bb connect expose`?).{0,140}(?:unless|without).{0,60}(?:explicit|user asks)|"
        r"hard prohibitions.{0,120}public exposure)"
    ),
    "public-exposure-current-conversation-service": re.compile(
        r"(?is)(?:user )?explicitly asks in this conversation to expose that named service/port"
    ),
    "public-share-close-task-end": re.compile(
        r"(?is)authorized share is temporary and task-scoped.{0,80}close it when the task ends"
    ),
    "public-share-closeout-audit": re.compile(
        r"(?is)run `bb connect shares` before closeout"
    ),
    "isolated-browser": re.compile(
        r"(?is)(?:(?:only )?permitted interactive browser surface|"
        r"use only bb.s isolated browser)"
    ),
    "no-personal-browser-control": re.compile(
        r"(?is)(?:never control.{0,80}personal(?:/default)? browser|"
        r"never use (?:a |the user.s )?personal(?:/default)? browser)"
    ),
    "browser-never-access-unowned": re.compile(
        r"(?is)never access or close.{0,100}(?:unowned|pre-existing).{0,80}"
        r"(?:user-owned|other-thread)"
    ),
    "browser-enumerate-before-open": re.compile(
        r"(?is)(?:call|enumerate).{0,80}browser_instances.{0,80}before.{0,40}browser_open"
    ),
    "browser-no-standard-preamble": re.compile(
        r"(?is)(?:never use `?browser_open`? as a standard first step|"
        r"do not (?:call )?`?browser_open`? as a standard first step|"
        r"do not open a page as a standard preamble)"
    ),
    "browser-close-before-isolation-change": re.compile(
        r"(?is)(?:close (?:the )?(?:owned )?(?:instance|page).{0,80}"
        r"before changing (?:cookie )?isolation|close it before changing isolation)"
    ),
    "browser-lifecycle-ops-noncreating": re.compile(
        r"(?is)(?:lookup|listing).{0,40}(?:refresh|refreshing).{0,40}"
        r"(?:release|releasing).{0,40}(?:close|closing).{0,120}"
        r"(?:must\s+never\s+create\s+a replacement (?:tab|page)|"
        r"remain\s+non-creating|creates a tab as an adapter\s+lifecycle defect)"
    ),
    "browser-close-every-slice-outcome": re.compile(
        r"(?is)(?:close (?:this thread.s|the thread-owned).{0,60}instance.{0,120}"
        r"bounded browser slice.{0,100}pass.{0,40}fail.{0,60}block.{0,60}"
        r"abandon.{0,60}supersed|close it when.{0,80}bounded browser slice ends|"
        r"close no-longer-needed instances.{0,100}slice is done.{0,60}blocked.{0,60}"
        r"abandoned.{0,60}superseded|close\s+(?:the\s+)?thread-owned\s+instance\s+afterward)"
    ),
    "browser-input-is-mutation": re.compile(r"(?is)browser input is a mutation"),
    "browser-exclusive-delivery-proof": re.compile(
        r"(?is)require adapter control-plane proof of exclusive delivery to the owned page"
        r".{0,100}zero terminal/OS input side effects"
    ),
    "browser-target-id-is-not-proof": re.compile(
        r"(?is)(?:target IDs|worktree/page/profile IDs|IDs).{0,80}"
        r"successful return do not prove isolation"
    ),
    "browser-persistent-quarantine-per-input": re.compile(
        r"(?is)before every.{0,500}check persistent adapter quarantine"
    ),
    "browser-leak-readonly-only": re.compile(
        r"(?is)on any non-target (?:input )?leak, preserve sessions and (?:allow|permit)"
        r" read-only browser operations only"
    ),
    "browser-quarantine-survives-restart": re.compile(
        r"(?is)new agent.{0,80}resumed session.{0,80}restart.{0,80}"
        r"runtime-ID change.{0,80}(?:never|does not) clear(?:s)? quarantine"
    ),
    "browser-quarantine-reenable-regression": re.compile(
        r"(?is)re-enable only after a fixed or changed build identity passes a regression"
        r".{0,100}no non-target PTY/UI input"
    ),
    "browser-prompts-cannot-bypass-quarantine": re.compile(
        r"(?is)ordinary agent prompts cannot bypass this gate"
    ),
    "browser-no-dedicated-takeover-claim": re.compile(
        r"(?is)never (?:describe a shared-window takeover as|call (?:it|a shared-window takeover) a) dedicated"
    ),
    "browser-no-foreground-takeover-claim": re.compile(
        r"(?is)(?:never.{0,100}foregrounded|(?:does not|cannot) prove.{0,80}"
        r"(?:the )?target tab is foregrounded)"
    ),
    "browser-no-unverified-login-claim": re.compile(
        r"(?is)never.{0,100}claim the exact login is open without adapter evidence"
    ),
    "hermes-no-reverse-ssh": re.compile(r"(?is)never (?:create )?reverse SSH"),
    "hermes-no-listeners": re.compile(
        r"(?is)never (?:create )?reverse SSH(?: or|,) listeners"
    ),
    "hermes-no-broad-env-forwarding": re.compile(
        r"(?is)never.{0,100}reverse SSH.{0,100}"
        r"(?:broad environment forwarding|forward broad environment values)"
        r"(?:, or export|[.;])"
    ),
    "hermes-no-cmux-capability-export": re.compile(
        r"(?is)never.{0,120}export `CMUX_SOCKET_CAPABILITY`/`CMUX_\*` values"
    ),
    "hermes-agent-no-model-override": re.compile(
        r"(?is)(?:never|do not) pass a `--model` override to `acp-hermes-agent`"
    ),
    "hermes-no-project-source": re.compile(
        r"(?is)(?:never place or retain a project source on Hermes"
        r".{0,180}never ask Hermes to mount a project source|"
        r"Hermes.{0,40}will never hold a project source)"
    ),
    "hermes-prompts-use-stdin": re.compile(
        r"(?is)use only the approved broker to send bounded (?:Hermes )?prompts via SSH stdin"
    ),
    "hermes-no-prompts-in-argv": re.compile(r"(?is)never put prompts in argv"),
    "hermes-no-local-terminal-socket": re.compile(
        r"(?is)never put prompts in argv(?:,| or) require a local terminal socket"
    ),
    "verified-qa-e2e-full-trigger-set": re.compile(
        r"(?is)for any browser E2E, authentication, seeded identit(?:y|ies), manual login handoff,"
        r" QA publication, or E2E completion.{0,100}load `?verified-qa-e2e`?"
        r" and pass its deterministic gate"
    ),
    "verified-qa-e2e-missing-fails-closed": re.compile(
        r"(?is)a missing or failing gate blocks the requested action at every reasoning effort"
    ),
    "child-thread-cap-three-without-asking": re.compile(
        r"(?is)up to 3 concurrent (?:child )?(?:threads|children) without asking"
    ),
    "child-thread-cap-six-with-orchestration": re.compile(
        r"(?is)an orchestration request (?:authorizes|approves) up to 6"
    ),
    "child-thread-cap-host-capacity": re.compile(
        r"(?is)up to 6.{0,80}(?:subject to host capacity|host capacity permitting)"
    ),
    "child-cap-distinct-opencode-instance-cap": re.compile(
        r"(?is)this is separate from OpenCode's 10 concurrent instances per session cap"
    ),
    "delegate-no-unapproved-dependencies": re.compile(
        r"(?is)(?:delegates may not add dependencies without a new master decision|"
        r"delegates? never.{0,200}add dependencies.{0,100}without a new master decision|"
        r"no architecture changes, new deps,.{0,180}without a new master decision)"
    ),
    "hermes-broker-delegation-default-off": re.compile(
        r"(?is)(?:Hermes/cmux broker delegation|Broker(?: \(Hermes/cmux\))? lane delegation) defaults off"
    ),
    "hermes-broker-concurrency-depth-one": re.compile(
        r"(?is)broker.{0,30}delegation defaults off.{0,80}concurrency/depth (?:default )?1(?!\d)"
    ),
    "hermes-broker-model-call-explicit-activation": re.compile(
        r"(?is)model calls require explicit bounded activation"
    ),
    "hermes-broker-limits-not-bb-children": re.compile(
        r"(?is)(?:these broker limits do not restrict|this does not limit)"
        r" bb child threads"
    ),
    "delegation-approval-scale-and-bounded-fanout": re.compile(
        r"(?is)(?:require explicit approval for more than 3 concurrent delegates,"
        r" broad parallel/swarm work, or fan-out without a named stop condition|"
        r"explicit approval is required at either threshold.{0,220}more than 3"
        r" concurrent delegates.{0,180}fan-out you cannot name the stop condition)"
    ),
    "delegation-cross-session-cmux-off": re.compile(
        r"(?is)cross-session cmux delegation stays off by default|"
        r"cmux cross-session delegation is off by default"
    ),
    "delegation-explicit-approval-outward-effects": re.compile(
        r"(?is)(?:require explicit approval before outward or hard-to-undo effects:"
        r" board mutations, bulk imports, cloud changes, secret access,"
        r" CI/repo-policy changes, destructive edits, PR/check automation,"
        r" or shared-remote pushes|explicit approval is required at either threshold"
        r".{0,400}outward/irreversible effect.{0,180}board mutations.{0,300}"
        r"shared remote|Get explicit approval before.{0,300}board mutations.{0,300}"
        r"PR/check automation)"
    ),
    "no-new-feature-flags": re.compile(
        r"(?is)no feature flags.{0,120}explicit ask"
    ),
    "worktree-removal": re.compile(
        r"(?is)(?:remove only clean worktrees you created|"
        r"never remove a worktree you did not create)"
    ),
    "worktree-dirty-protection": re.compile(
        r"(?is)(?:remove only clean worktrees you created|"
        r"never one that is dirty|never remove.{0,180}dirty tree)"
    ),
    "worktree-keep-protection": re.compile(
        r"(?is)(?:never remove.{0,120}dirty tree,\s*(?:a\s*)?`?\.keep-worktree|"
        r"never one that is dirty,.{0,160}carries `\.keep-worktree`)"
    ),
    "worktree-unreferenced-detached": re.compile(
        r"(?is)(?:never remove.{0,180}unreferenced detached commit|"
        r"refuses to touch.{0,120}unreferenced detached (?:HEAD|commit)s?)"
    ),
    "worktree-detached-lifetime": re.compile(
        r"(?is)(?:never create a detached-HEAD worktree.{0,140}outlives? its command|"
        r"detached-HEAD worktree must not outlive its command|"
        r"detached review worktree.{0,100}end with its command)"
    ),
    "worktree-never-force": re.compile(
        r"(?is)(?:worktree remove.{0,100}(?:never|without).{0,40}--force|"
        r"never.{0,40}--force.{0,100}worktree remove)"
    ),
    "worktree-not-owned": re.compile(
        r"(?is)(?:never remove a worktree you did not create|"
        r"never remove.{0,120}another agent.s/user.s worktree)"
    ),
    "worktree-own-bb-environment": re.compile(
        r"(?is)never remove.{0,100}(?:your own (?:live )?bb environment|"
        r"the worktree your own bb thread runs in)"
    ),
    "worktree-one-writer": re.compile(
        r"(?is)one writer per PR, branch,? and worktree"
    ),
    "worktree-no-sibling-edits": re.compile(
        r"(?is)(?:never a sibling.s\.|never edit a sibling.s worktree)"
    ),
    "worktree-collision-stop": re.compile(
        r"(?is)Workspace collision detected.{0,100}stop editing"
    ),
    "worktree-collision-reread-diff": re.compile(
        r"(?is)(?:survivor )?re-?reads? `git diff` before commit(?:ting)?"
    ),
    "automation-single-flight-per-target": re.compile(
        r"(?is)automations? (?:(?:are|must be) )?single-flight per target"
    ),
    "agent-push-is-not-completion": re.compile(
        r"(?is)(?:never treat an agent.s push as completion while its thread is still running|"
        r"never treat their own agent.s\s+push as completion while its\s+thread is still running|"
        r"must not treat their own push as completion while its agent still runs)"
    ),
    "active-session-input-skill-trigger": re.compile(
        r"(?is)(?:before active-session input.{0,100}load `?native-agent-surface`?.{0,100}"
        r"metadata-only.{0,80}session-input-guard\.py|"
        r"before delivering input to an active\s+agent.{0,300}(?:"
        r"metadata-only guard.{0,150}native-agent-surface|"
        r"native-agent-surface.{0,150}metadata-only.{0,100}session-input-guard\.py))"
    ),
    "active-session-supersede-authority": re.compile(
        r"(?is)(?:supersede only via `?superseding`?.{0,140}authenticated user authority.{0,180}"
        r"exact active workspace/session/lease/epoch.{0,160}adapter-validated resume-packet reference|"
        r"supersede\s+requires\s+authenticated user authority.{0,250}exact\s+workspace/session/lease/epoch.{0,250}"
        r"validated\s+resume-packet attestation.{0,120}(?:`)?superseding(?:`)?\s+transition)"
    ),
    "active-session-untrusted-input-no-supersede": re.compile(
        r"(?is)group,\s*dispatch,\s*terminal-injection,\s*unattributed,\s*handoff,\s*and recovery inputs\s+"
        r"never\s+(?:silently\s+)?supersede"
    ),
    "active-session-attestations-control-plane-only": re.compile(
        r"(?is)(?:(?:authority/topic/resume|authority,\s*topic-relation,\s*and resume-packet)\s+"
        r"attestations\s+(?:must\s+)?come\s+(?:only\s+)?from adapter\s+control-plane records,\s*never prompt text|"
        r"attestations\s+come from adapter\s+control-plane records,\s*never prompt text)"
    ),
    "active-session-write-owner-mismatch-blocks": re.compile(
        r"(?is)same-workspace\s+write-owner mismatch blocks\s+delivery"
    ),
    "no-ai-signatures": re.compile(
        r"(?is)(?:do not|never) add AI attribution.{0,150}"
        r"(?:signature|watermark)"
    ),
    "hermes-defects-block": re.compile(
        r"(?is)(?:Hermes names a defect in a PR: fix it; defects block merge|"
        r"any named defect blocks merge until fixed and cleared on the same topic|"
        r"a named defect blocks: fix it and rerun the same topic until it is no longer named|"
        r"a PR never merges while Hermes names a defect in it:\s*fix\s+it, then re-run on the same `--topic`"
        r" until that defect is no longer named)"
    ),
    "testing-claim": re.compile(
        r"(?is)persona.{0,180}target.{0,220}(?:goals|user outcomes).{0,200}"
        r"verdict.{0,220}NOT RUN"
    ),
    "testing-pass-full-workflow": re.compile(
        r"(?is)(?:PASS (?:requires the persona to complete|means the persona completed)"
        r" the full workflow.{0,50}(?:otherwise FAIL|anything else is FAIL)|"
        r"PASS means the\s+persona.{0,100}completed the goal"
        r"(?=.*unit of test is the workflow)"
        r"(?=.*entire.{0,30}workflow completes end to end))"
    ),
    "security-first": re.compile(r"(?is)security-first defaults"),
    "security-first-scope": re.compile(
        r"(?is)security-first defaults.{0,350}auth.{0,70}access\s+control.{0,70}secrets.{0,70}crypto.{0,90}"
        r"external input.{0,90}outbound requests.{0,90}dependencies.{0,80}build/config"
    ),
    "security-required-gate": re.compile(
        r"(?is)load.{0,100}SECURITY_AND_PENTEST\.md.{0,100}QUALITY_GATES\.md.{0,50}Security Gate"
    ),
    "security-supply-chain-priority": re.compile(
        r"(?is)(?:supply-chain.{0,100}build-config compromise.{0,35}first|"
        r"prioritize supply-chain/build-config compromise)"
    ),
    "security-residual-exposure": re.compile(
        r"(?is)residual exposure after\s+(?:existing\s+)?mitigations.{0,80}"
        r"(?:(?:rather than|not) )?(?:raw )?scanner labels"
    ),
    "security-active-testing-authorization": re.compile(
        r"(?is)(?:active testing (?:must be authorized and defensive|requires authorization and must stay defensive)|"
        r"establish authorization before active testing)"
    ),
    "security-no-offensive-tooling": re.compile(
        r"(?is)never build offensive, self-propagating, evasive,? or mass-targeting (?:tools|tooling)"
    ),
    "security-high-stakes-sweep": re.compile(
        r"(?is)high-stakes review.{0,100}(?:one pass is not sign-off|single pass is not a sign-off).{0,100}"
        r"adversarial-security-sweep"
    ),
    "security-strongest-exploit-path": re.compile(
        r"(?is)exploit[- ]validation.{0,70}severity.{0,70}fix[- ]design.{0,70}strongest reasoning path"
    ),
    "typed-decisions-jev-system-one": re.compile(
        r"(?is)run semantic atomic judgments on Jev.{0,120}(?:in batches|batched).{0,80}"
        r"isolated.{0,80}recorded as `?system-one`?"
    ),
    "typed-decisions-jev-never-sole-control": re.compile(
        r"(?is)(?:alone never enough for an irreversible\s+or security call|"
        r"never use Jev.{0,100}alone for irreversible/security calls)"
    ),
    "typed-decisions-jev-no-hooks-or-secrets": re.compile(
        r"(?is)never (?:use Jev )?in a blocking hook.{0,100}(?:never )?with secrets"
    ),
    "no-gc-user-owned-state": re.compile(
        r"(?is)never garbage-collect repositories,\s*journals,\s*user-owned sessions,\s*or active sessions"
    ),
    "context-gc-boundary": re.compile(
        r"(?is)context GC.{0,100}execution boundaries"
    ),
    "context-gc-resume-packet": re.compile(
        r"(?is)retain\s+only\s+a\s+compact\s+resume\s+packet"
    ),
    "context-gc-discard-logs": re.compile(
        r"(?is)discard\s+raw\s+tool\s+logs\s+and\s+completed-agent\s+transcripts"
    ),
    "context-gc-fresh-opencode-sessions": re.compile(
        r"(?is)use\s+fresh\s+opencode\s+sessions\s+for\s+new\s+plan\s+steps"
    ),
    "context-gc-audit": re.compile(
        r"(?is)run\s+the\s+available\s+GC\s+audit\s+across\s+storage/process\s+state"
    ),
    "context-gc-managed-runner-self-check": re.compile(
        r"(?is)do\s+not\s+depend\s+on\s+a\s+managed\s+runner\s+unless\s+its\s+installed\s+implementation\s+passes\s+a\s+live\s+self-check"
    ),
}
OPTIONAL_WHEN_ABSENT = {
    "public-exposure-current-conversation-service",
    "public-share-close-task-end",
    "public-share-closeout-audit",
    "credentials-never-paste",
    "credentials-never-handle",
    "no-pkill-pgrep-app-kill-path",
    "worktree-own-bb-environment",
    "no-gc-user-owned-state",
    "context-gc-boundary",
    "context-gc-resume-packet",
    "context-gc-discard-logs",
    "context-gc-fresh-opencode-sessions",
    "context-gc-audit",
    "context-gc-managed-runner-self-check",
    "browser-never-access-unowned",
    "browser-enumerate-before-open",
    "browser-no-standard-preamble",
    "browser-close-before-isolation-change",
    "browser-lifecycle-ops-noncreating",
    "browser-close-every-slice-outcome",
    "browser-input-is-mutation",
    "browser-exclusive-delivery-proof",
    "browser-target-id-is-not-proof",
    "browser-persistent-quarantine-per-input",
    "browser-leak-readonly-only",
    "browser-quarantine-survives-restart",
    "browser-quarantine-reenable-regression",
    "browser-prompts-cannot-bypass-quarantine",
    "browser-no-dedicated-takeover-claim",
    "browser-no-foreground-takeover-claim",
    "browser-no-unverified-login-claim",
    "hermes-no-reverse-ssh",
    "hermes-no-listeners",
    "hermes-no-broad-env-forwarding",
    "hermes-no-cmux-capability-export",
    "hermes-agent-no-model-override",
    "hermes-no-project-source",
    "hermes-prompts-use-stdin",
    "hermes-no-prompts-in-argv",
    "hermes-no-local-terminal-socket",
    "verified-qa-e2e-full-trigger-set",
    "verified-qa-e2e-missing-fails-closed",
    "child-thread-cap-three-without-asking",
    "child-thread-cap-six-with-orchestration",
    "child-thread-cap-host-capacity",
    "child-cap-distinct-opencode-instance-cap",
    "delegate-no-unapproved-dependencies",
    "hermes-broker-delegation-default-off",
    "hermes-broker-concurrency-depth-one",
    "hermes-broker-model-call-explicit-activation",
    "hermes-broker-limits-not-bb-children",
    "delegation-approval-scale-and-bounded-fanout",
    "delegation-cross-session-cmux-off",
    "delegation-explicit-approval-outward-effects",
    "active-session-input-skill-trigger",
    "active-session-supersede-authority",
    "active-session-untrusted-input-no-supersede",
    "active-session-attestations-control-plane-only",
    "active-session-write-owner-mismatch-blocks",
}

HOME_FILES = (
    Path("~/.claude/CLAUDE.md").expanduser(),
    Path("~/.codex/AGENTS.md").expanduser(),
    Path("~/.config/opencode/AGENTS.md").expanduser(),
    Path("~/.bb/AGENTS.md").expanduser(),
)
KIT_SOURCE = Path(__file__).resolve().parents[1] / "GLOBAL_AGENTS.md"

# These inventories are selected by exact content fingerprints at native paths.
# The four pre-compression snapshots retain their legacy applicability; the
# exact rendered install artifacts receive the complete proposal inventories.
# Any edited or unknown candidate fails closed before optional-rule handling.
LIVE_HOME_RULES = {
    "claude": {
        "browser-close-every-slice-outcome", "browser-lifecycle-ops-noncreating",
        "browser-close-before-isolation-change", "browser-no-foreground-takeover-claim",
        "browser-input-is-mutation", "browser-no-standard-preamble",
        "child-thread-cap-six-with-orchestration", "delegate-no-unapproved-dependencies",
        "delegation-cross-session-cmux-off",
        "active-session-input-skill-trigger", "active-session-supersede-authority",
        "active-session-untrusted-input-no-supersede",
        "active-session-attestations-control-plane-only",
        "active-session-write-owner-mismatch-blocks",
    },
    "codex": {
        "context-gc-boundary", "context-gc-managed-runner-self-check",
        "context-gc-fresh-opencode-sessions", "context-gc-audit",
        "browser-close-every-slice-outcome", "delegate-no-unapproved-dependencies",
        "hermes-broker-delegation-default-off", "browser-lifecycle-ops-noncreating",
        "hermes-broker-concurrency-depth-one", "browser-no-dedicated-takeover-claim",
        "hermes-no-prompts-in-argv", "browser-input-is-mutation",
        "hermes-no-local-terminal-socket", "no-gc-user-owned-state",
        "child-thread-cap-six-with-orchestration", "context-gc-discard-logs",
        "hermes-broker-model-call-explicit-activation", "context-gc-resume-packet",
        "active-session-input-skill-trigger", "active-session-supersede-authority",
        "active-session-untrusted-input-no-supersede",
        "active-session-attestations-control-plane-only",
        "active-session-write-owner-mismatch-blocks",
    },
    "opencode": {
        "browser-close-every-slice-outcome", "hermes-no-reverse-ssh",
        "hermes-no-cmux-capability-export", "browser-lifecycle-ops-noncreating",
        "worktree-own-bb-environment", "browser-close-before-isolation-change",
        "browser-quarantine-survives-restart", "browser-no-dedicated-takeover-claim",
        "hermes-no-listeners", "browser-no-foreground-takeover-claim",
        "browser-input-is-mutation", "browser-exclusive-delivery-proof",
        "child-thread-cap-six-with-orchestration", "browser-no-standard-preamble",
        "active-session-input-skill-trigger", "active-session-supersede-authority",
        "active-session-untrusted-input-no-supersede",
        "active-session-attestations-control-plane-only",
        "active-session-write-owner-mismatch-blocks",
    },
    "bb": {
        "credentials-never-paste", "credentials-never-handle",
        "browser-enumerate-before-open", "browser-close-every-slice-outcome",
        "browser-lifecycle-ops-noncreating", "worktree-own-bb-environment",
        "browser-close-before-isolation-change", "browser-no-dedicated-takeover-claim",
        "browser-no-foreground-takeover-claim", "child-thread-cap-six-with-orchestration",
        "hermes-agent-no-model-override", "browser-no-standard-preamble",
        "hermes-no-project-source",
    },
}
KIT_BASELINE_RULES = {
    "public-exposure-current-conversation-service", "public-share-close-task-end",
    "public-share-closeout-audit",
    "credentials-never-paste", "credentials-never-handle",
    "child-thread-cap-three-without-asking", "no-pkill-pgrep-app-kill-path",
    "browser-enumerate-before-open", "browser-leak-readonly-only",
    "child-thread-cap-host-capacity", "browser-close-every-slice-outcome",
    "hermes-no-reverse-ssh", "delegate-no-unapproved-dependencies",
    "hermes-no-cmux-capability-export", "hermes-broker-delegation-default-off",
    "browser-prompts-cannot-bypass-quarantine", "browser-lifecycle-ops-noncreating",
    "child-cap-distinct-opencode-instance-cap", "browser-never-access-unowned",
    "browser-quarantine-reenable-regression", "hermes-broker-concurrency-depth-one",
    "delegation-approval-scale-and-bounded-fanout", "hermes-no-broad-env-forwarding",
    "worktree-own-bb-environment", "browser-close-before-isolation-change",
    "browser-quarantine-survives-restart", "browser-no-dedicated-takeover-claim",
    "hermes-no-prompts-in-argv", "hermes-no-listeners",
    "hermes-broker-limits-not-bb-children", "delegation-explicit-approval-outward-effects",
    "browser-target-id-is-not-proof", "browser-no-foreground-takeover-claim",
    "browser-input-is-mutation", "browser-exclusive-delivery-proof",
    "hermes-prompts-use-stdin", "hermes-no-local-terminal-socket",
    "verified-qa-e2e-missing-fails-closed", "child-thread-cap-six-with-orchestration",
    "browser-no-unverified-login-claim", "hermes-agent-no-model-override",
    "hermes-broker-model-call-explicit-activation", "verified-qa-e2e-full-trigger-set",
    "browser-persistent-quarantine-per-input", "delegation-cross-session-cmux-off",
    "browser-no-standard-preamble", "hermes-no-project-source",
    "active-session-input-skill-trigger", "active-session-supersede-authority",
    "active-session-untrusted-input-no-supersede",
    "active-session-attestations-control-plane-only",
    "active-session-write-owner-mismatch-blocks",
}
CONTEXT_GC_RULES = {
    "no-gc-user-owned-state", "context-gc-boundary", "context-gc-resume-packet",
    "context-gc-discard-logs", "context-gc-fresh-opencode-sessions",
    "context-gc-audit", "context-gc-managed-runner-self-check",
}
HERMES_TRANSPORT_RULES = {
    "hermes-no-reverse-ssh", "hermes-no-listeners", "hermes-no-broad-env-forwarding",
    "hermes-no-cmux-capability-export", "hermes-agent-no-model-override",
    "hermes-no-project-source", "hermes-prompts-use-stdin", "hermes-no-prompts-in-argv",
    "hermes-no-local-terminal-socket",
}
PROFILE_RULES = {
    **LIVE_HOME_RULES,
    "kit": KIT_BASELINE_RULES,
    # Rendered proposals deliberately use the full closed inventory; this is
    # what makes the mutation fixtures fail closed for newly required clauses.
    "proposal-claude": OPTIONAL_WHEN_ABSENT - HERMES_TRANSPORT_RULES - CONTEXT_GC_RULES,
    "proposal-codex": OPTIONAL_WHEN_ABSENT,
    "proposal-opencode": OPTIONAL_WHEN_ABSENT - CONTEXT_GC_RULES,
    "proposal-bb": OPTIONAL_WHEN_ABSENT - CONTEXT_GC_RULES,
}

LIVE_HOME_SHA256 = {
    "e84334424e03baef698279c184de2ef252891124b70e549924c2d17f0f5a05cd": "claude",
    "2f7433b7928b17aacbe3988519788300760e8239c840121db5cf3b1f089d871b": "codex",
    "79ce2b7596ccf3b90f4e8d3eecde4e070f236c92e3e90e84af3aea67f39acae2": "opencode",
    "db5814411d08fa2deb320e51582326e8e8a245020e262b74f4e2a3724c97283c": "bb",
}
INSTALLED_HOME_SHA256 = {
    "a9e41cdc5282fbbaaad77ab94f993bdfcec756a96dc4e7cf97b0f699248754b0": "proposal-claude",
    "a71af211551f41b9b517cc63ab1613320102c97e5d1e84096e583d5e544aebeb": "proposal-codex",
    "5bf7e6814ee7bad0b231f1797fe554b6d8f98891357b398ce296be15545be1e2": "proposal-opencode",
    "fa49ad169ce7352e45edcedc052ef51bacd466ad1b18845b001b74db643142bd": "proposal-bb",
}


def profile_for(path: Path, content: str) -> str | None:
    """Resolve a fixed profile by target path and exact known-home fingerprint."""
    parts = path.resolve().parts
    if path.resolve() == KIT_SOURCE.resolve():
        return "kit"
    if len(parts) >= 2 and parts[-2] == "rendered-homes":
        return {
            "CLAUDE.md": "proposal-claude",
            "codex-AGENTS.md": "proposal-codex",
            "opencode-AGENTS.md": "proposal-opencode",
            "bb-AGENTS.md": "proposal-bb",
        }.get(path.name)
    suffix_profiles = {
        (".claude", "CLAUDE.md"): "claude",
        (".codex", "AGENTS.md"): "codex",
        (".config", "opencode", "AGENTS.md"): "opencode",
        (".bb", "AGENTS.md"): "bb",
    }
    home_kind = None
    for suffix, profile in suffix_profiles.items():
        if parts[-len(suffix):] == suffix:
            home_kind = profile
            break
    if home_kind is None:
        return None
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    known_profile = LIVE_HOME_SHA256.get(digest) or INSTALLED_HOME_SHA256.get(digest)
    expected_kind = known_profile.removeprefix("proposal-") if known_profile else None
    if expected_kind == home_kind:
        return known_profile
    return None


def missing_rules(
    text: str,
    require_optional: bool = False,
    required_optional: set[str] | None = None,
    skip_rules: set[str] | None = None,
) -> list[str]:
    missing: list[str] = []
    for name, pattern in RULES.items():
        if skip_rules is not None and name in skip_rules:
            continue
        match = pattern.search(text)
        required = require_optional or (required_optional is not None and name in required_optional)
        if (
            name in OPTIONAL_WHEN_ABSENT
            and not required
            and not optional_present(name, text)
        ):
            continue
        if (
            not match
            or historical_clause(text, match.start())
            or contradicted_rule(name, text)
        ):
            missing.append(name)
    return missing


def contradicted_rule(name: str, text: str) -> bool:
    if name == "testing-pass-full-workflow":
        partial_pass = re.compile(
            r"(?is)PASS.{0,100}(?:only|just).{0,50}(?:focused |unit )?tests?"
            r".{0,120}(?:full workflow is optional|workflow.{0,30}optional)|"
            r"(?:full workflow|end-to-end workflow).{0,50}(?:optional|not required)"
        )
        if partial_pass.search(text):
            return True
    if name == "hermes-defects-block":
        advisory_defect = re.compile(
            r"(?is)(?:any|each|a) named defect.{0,100}"
            r"(?:does not|doesn't|need not|may not|is advisory|is non-blocking|is nonblocking)"
            r".{0,80}(?:block|merge)|"
            r"named defects? (?:are )?(?:advisory|non-blocking|nonblocking)"
        )
        if advisory_defect.search(text):
            return True
    if name == "public-exposure" or name.startswith("public-exposure-"):
        stale_consent = re.compile(
            r"(?is)(?:user )?explicitly asks in (?:a|any|the) "
            r"(?:previous|past|earlier|different) conversation"
        )
        if stale_consent.search(text):
            return True
    if name.startswith("credentials-never-"):
        credential_exception = re.compile(
            r"(?is)never.{0,100}\b(?:type|paste|handle)\b.{0,100}credentials.{0,80}"
            r"(?:unless|except when|except if|when).{0,100}"
            r"(?:the user asks|user requested|user asks|login|log in)"
        )
        if credential_exception.search(text):
            return True
    if name.startswith("email-"):
        email_approval_exception = re.compile(
            r"(?is)(?:(?:routine|standard|internal|automated|follow[- ]up|low[- ]risk)\s+)?"
            r"(?:e-?mails?|messages?|mail).{0,100}"
            r"(?:may|can|could|are allowed to|are permitted to).{0,100}"
            r"(?:be sent|send|proceed|go out).{0,100}"
            r"without\s+(?:asking|(?:user\s+)?approval|consent)"
        )
        if email_approval_exception.search(text):
            return True
    contradictions = {
        "bb-app-never-quit": re.compile(
            r"(?is)(?:never quit[^\n]{0,150}\b(?:unless|except)\b|"
            r"quitting the running bb app[^\n]{0,80}\b(?:allowed|permitted)\b)"
        ),
        "bb-app-never-kill": re.compile(
            r"(?is)(?:never kill[^\n]{0,150}\b(?:unless|except)\b|"
            r"killing the running bb app[^\n]{0,80}\b(?:allowed|permitted)\b)"
        ),
        "bb-app-never-replace": re.compile(
            r"(?is)(?:never replace[^\n]{0,150}\b(?:unless|except)\b|"
            r"replacing the running bb app[^\n]{0,80}\b(?:allowed|permitted)\b)"
        ),
        "bb-app-bundle-never-move": re.compile(
            r"(?is)(?:never move[^\n]{0,150}\b(?:unless|except)\b|"
            r"moving `?/Applications/bb\.app[^\n]{0,80}\b(?:allowed|permitted)\b)"
        ),
        "bb-app-bundle-never-delete": re.compile(
            r"(?is)(?:never delete[^\n]{0,150}\b(?:unless|except)\b|"
            r"deleting `?/Applications/bb\.app[^\n]{0,80}\b(?:allowed|permitted)\b)"
        ),
        "bb-app-bundle-never-overwrite": re.compile(
            r"(?is)(?:never overwrite[^\n]{0,150}\b(?:unless|except)\b|"
            r"overwriting `?/Applications/bb\.app[^\n]{0,80}\b(?:allowed|permitted)\b)"
        ),
        "browser-never-access-unowned": re.compile(
            r"(?is)(?:allow|may|can).{0,80}(?:access|close).{0,120}"
            r"(?:unowned|pre-existing|user-owned|other-thread)"
        ),
        "browser-enumerate-before-open": re.compile(
            r"(?is)do\s+not\s+(?:call|enumerate).{0,80}browser_instances.{0,80}"
            r"before.{0,40}browser_open"
        ),
        "browser-no-standard-preamble": re.compile(
            r"(?is)(?:use|call).{0,30}`?browser_open`?.{0,40}as (?:the )?standard first step"
        ),
        "browser-close-before-isolation-change": re.compile(
            r"(?is)(?:do\s+not|never|must\s+not|should\s+not|don.t)\s+close"
            r".{0,100}(?:owned )?(?:instance|page).{0,100}before changing (?:cookie )?isolation"
        ),
        "browser-lifecycle-ops-noncreating": re.compile(
            r"(?is)(?:lookup|refresh|release|close).{0,100}"
            r"(?:may|can|are allowed to|are permitted to).{0,60}"
            r"create a replacement (?:tab|page)"
        ),
        "browser-close-every-slice-outcome": re.compile(
            r"(?is)(?:do\s+not|never|must\s+not|should\s+not|don.t)\s+"
            r"close.{0,180}bounded browser slice"
        ),
    }
    pattern = contradictions.get(name)
    return bool(pattern and pattern.search(text))


def historical_clause(text: str, position: int) -> bool:
    lines = text.splitlines()
    offset = 0
    line_index = 0
    for index, line in enumerate(lines):
        next_offset = offset + len(line) + 1
        if offset <= position < next_offset:
            line_index = index
            break
        offset = next_offset
    candidates = [lines[line_index]]
    previous = line_index - 1
    if previous >= 0 and lines[previous].strip():
        candidates.append(lines[previous])
    return bool(re.search(r"(?i)historical note|no longer binding", "\n".join(candidates)))


def optional_present(name: str, text: str) -> bool:
    if name == "no-pkill-pgrep-app-kill-path":
        return bool(RULES[name].search(text))
    if name.startswith("credentials-never-"):
        return bool(RULES[name].search(text))
    if name.startswith("public-exposure-") or name.startswith("public-share-"):
        return bool(RULES[name].search(text))
    if name == "worktree-own-bb-environment":
        return bool(RULES[name].search(text))
    if name == "browser-never-access-unowned":
        return bool(RULES[name].search(text))
    if name.startswith("browser-"):
        return bool(RULES[name].search(text))
    if name.startswith("hermes-"):
        return bool(RULES[name].search(text))
    if name.startswith("verified-qa-e2e-"):
        return bool(RULES[name].search(text))
    if name.startswith("child-thread-cap-") or name == "child-cap-distinct-opencode-instance-cap":
        return bool(RULES[name].search(text))
    if name == "delegate-no-unapproved-dependencies":
        return bool(RULES[name].search(text))
    if name.startswith("delegation-"):
        return bool(RULES[name].search(text))
    if name == "no-gc-user-owned-state":
        return bool(RULES[name].search(text))
    if name.startswith("context-gc-"):
        return bool(RULES[name].search(text))
    if name.startswith("active-session-"):
        return bool(RULES[name].search(text))
    return True


def check_files(paths: list[Path]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for path in paths:
        if not path.is_file():
            failures.append(f"{path}: file missing")
            continue
        content = path.read_text(encoding="utf-8")
        profile = profile_for(path, content)
        if profile is None:
            failures.append(
                f"{path}: no fixed profile for this path and exact known-home content"
            )
            continue
        required_optional = set(PROFILE_RULES[profile])
        missing = missing_rules(
            content,
            required_optional=required_optional,
        )
        if missing:
            failures.append(f"{path}: missing {', '.join(missing)}")
        else:
            applicable = len(RULES) - len(OPTIONAL_WHEN_ABSENT - required_optional)
            print(f"PASS {path}: {applicable} applicable standing rules")
    return not failures, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--files", nargs="+", type=Path,
        help="override the four home files and kit source (for fixtures)",
    )
    args = parser.parse_args()
    paths = args.files or [*HOME_FILES, KIT_SOURCE]
    ok, failures = check_files(paths)
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    if ok:
        print(f"PASS all {len(paths)} files contain all applicable rules ({len(RULES)} regexes)")
        return 0
    print(f"FAIL {len(failures)} of {len(paths)} files", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
