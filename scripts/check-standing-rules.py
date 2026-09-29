#!/usr/bin/env python3
"""Check that the always-on safety rules remain in every loaded instruction file."""

from __future__ import annotations

import argparse
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
    "no-pkill-pgrep-app-kill-path": re.compile(
        r"(?is)never\s+use\s+(?:`?pkill`?\s+or\s+`?pgrep\s+-f`?|"
        r"`?pgrep\s+-f`?\s+or\s+`?pkill`?)"
    ),
    "credentials": re.compile(
        r"(?is)never\s+(?:type|paste|handle).{0,80}credentials"
    ),
    "public-exposure": re.compile(
        r"(?is)(?:(?:never|do not).{0,45}(?:publicly\s+expose|expose(?:\s+a)?\s+service|"
        r"run\s+`?bb connect expose`?).{0,140}(?:unless|without).{0,60}(?:explicit|user asks)|"
        r"hard prohibitions.{0,120}public exposure)"
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
    "no-ai-signatures": re.compile(
        r"(?is)(?:do not|never) add AI attribution.{0,150}"
        r"(?:signature|watermark)"
    ),
    "hermes-defects-block": re.compile(
        r"(?is)Hermes.{0,180}(?:defect|bug).{0,120}(?:block|merge)"
    ),
    "testing-claim": re.compile(
        r"(?is)persona.{0,180}target.{0,220}(?:goals|user outcomes).{0,200}"
        r"verdict.{0,220}NOT RUN"
    ),
    "security-first": re.compile(r"(?is)security-first defaults"),
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
}

HOME_FILES = (
    Path("~/.claude/CLAUDE.md").expanduser(),
    Path("~/.codex/AGENTS.md").expanduser(),
    Path("~/.config/opencode/AGENTS.md").expanduser(),
    Path("~/.bb/AGENTS.md").expanduser(),
)
KIT_SOURCE = Path(__file__).resolve().parents[1] / "GLOBAL_AGENTS.md"


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
    contradictions = {
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
    return True


def check_files(paths: list[Path]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for path in paths:
        if not path.is_file():
            failures.append(f"{path}: file missing")
            continue
        resolved = path.resolve()
        rendered = "rendered-homes" in path.parts
        strict = resolved == KIT_SOURCE.resolve() or rendered
        content = path.read_text(encoding="utf-8")
        required_optional: set[str] = set()
        if strict:
            required_optional.update({
                "no-pkill-pgrep-app-kill-path",
                "worktree-own-bb-environment",
            })
            if resolved == KIT_SOURCE.resolve() or (rendered and path.name == "bb-AGENTS.md"):
                required_optional.update({
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
                })
            if rendered and path.name != "bb-AGENTS.md":
                required_optional.update({
                    "browser-input-is-mutation",
                    "browser-exclusive-delivery-proof",
                    "browser-persistent-quarantine-per-input",
                })
        if (rendered and path.name == "codex-AGENTS.md") or resolved == Path(
            "~/.codex/AGENTS.md"
        ).expanduser().resolve():
            required_optional.update({
                "no-gc-user-owned-state",
                "context-gc-boundary",
                "context-gc-resume-packet",
                "context-gc-discard-logs",
                "context-gc-fresh-opencode-sessions",
                "context-gc-audit",
                "context-gc-managed-runner-self-check",
            })
        skip_rules = set()
        if rendered and path.name != "bb-AGENTS.md":
            skip_rules.update({
                "browser-never-access-unowned",
                "browser-enumerate-before-open",
                "browser-no-standard-preamble",
                "browser-close-before-isolation-change",
                "browser-lifecycle-ops-noncreating",
                "browser-close-every-slice-outcome",
                "browser-target-id-is-not-proof",
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
            })
        missing = missing_rules(
            content,
            required_optional=required_optional,
            skip_rules=skip_rules,
        )
        if missing:
            failures.append(f"{path}: missing {', '.join(missing)}")
        else:
            applicable = len(RULES) - sum(
                name in OPTIONAL_WHEN_ABSENT
                and name not in required_optional
                and not optional_present(name, content)
                or name in skip_rules
                for name in RULES
            )
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
