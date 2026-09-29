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
    "bb-app-process": re.compile(
        r"(?is)never\s+(?:quit|kill|replace).{0,120}bb.{0,100}app"
    ),
    "no-pkill-pgrep-app-kill-path": re.compile(
        r"(?is)never.{0,160}bb.{0,100}app.{0,320}(?:pkill|pgrep\s+-f)"
    ),
    "credentials": re.compile(
        r"(?is)never\s+(?:type|paste|handle).{0,80}credentials"
    ),
    "public-exposure": re.compile(
        r"(?is)(?:never|do not).{0,100}(?:public exposure|bb connect expose)"
        r"|hard prohibitions.{0,120}public exposure"
    ),
    "isolated-browser": re.compile(
        r"(?is)(?:never control the user.s personal browser|"
        r"never use personal/external browsers|"
        r"only permitted interactive browser surface|"
        r"use only bb.s isolated browser|"
        r"isolated browser tools.{0,160}personal browser|"
        r"personal browser.{0,240}isolated bb profile)"
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
}
OPTIONAL_WHEN_ABSENT = {
    "no-pkill-pgrep-app-kill-path",
    "worktree-own-bb-environment",
}

HOME_FILES = (
    Path("~/.claude/CLAUDE.md").expanduser(),
    Path("~/.codex/AGENTS.md").expanduser(),
    Path("~/.config/opencode/AGENTS.md").expanduser(),
    Path("~/.bb/AGENTS.md").expanduser(),
)
KIT_SOURCE = Path(__file__).resolve().parents[1] / "GLOBAL_AGENTS.md"


def missing_rules(text: str, require_optional: bool = False) -> list[str]:
    missing: list[str] = []
    for name, pattern in RULES.items():
        if (
            name in OPTIONAL_WHEN_ABSENT
            and not require_optional
            and not optional_present(name, text)
        ):
            continue
        if not pattern.search(text):
            missing.append(name)
    return missing


def optional_present(name: str, text: str) -> bool:
    if name == "no-pkill-pgrep-app-kill-path":
        return bool(re.search(r"(?i)\bpkill\b|\bpgrep\s+-f\b", text))
    if name == "worktree-own-bb-environment":
        return bool(RULES[name].search(text))
    return True


def check_files(paths: list[Path]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for path in paths:
        if not path.is_file():
            failures.append(f"{path}: file missing")
            continue
        strict = path.resolve() == KIT_SOURCE.resolve() or "rendered-homes" in path.parts
        content = path.read_text(encoding="utf-8")
        missing = missing_rules(content, require_optional=strict)
        if missing:
            failures.append(f"{path}: missing {', '.join(missing)}")
        else:
            applicable = len(RULES) - sum(
                name in OPTIONAL_WHEN_ABSENT and not optional_present(name, content)
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
