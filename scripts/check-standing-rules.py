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
        r"(?is)(?=.*(?:delete your own worktree|never remove.{0,150}own.{0,100}"
        r"(?:environment|worktree)|never remove a worktree you did not create))"
        r"(?=.*\.keep-worktree)(?=.*unreferenced detached)"
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
OPTIONAL_WHEN_ABSENT = {"no-pkill-pgrep-app-kill-path"}

HOME_FILES = (
    Path("~/.claude/CLAUDE.md").expanduser(),
    Path("~/.codex/AGENTS.md").expanduser(),
    Path("~/.config/opencode/AGENTS.md").expanduser(),
    Path("~/.bb/AGENTS.md").expanduser(),
)
KIT_SOURCE = Path(__file__).resolve().parents[1] / "GLOBAL_AGENTS.md"


def missing_rules(text: str) -> list[str]:
    missing: list[str] = []
    for name, pattern in RULES.items():
        if name in OPTIONAL_WHEN_ABSENT and not re.search(r"(?i)\bpkill\b|\bpgrep\s+-f\b", text):
            continue
        if not pattern.search(text):
            missing.append(name)
    return missing


def check_files(paths: list[Path]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for path in paths:
        if not path.is_file():
            failures.append(f"{path}: file missing")
            continue
        missing = missing_rules(path.read_text(encoding="utf-8"))
        if missing:
            failures.append(f"{path}: missing {', '.join(missing)}")
        else:
            applicable = len(RULES)
            if not re.search(r"(?i)\bpkill\b|\bpgrep\s+-f\b", path.read_text(encoding="utf-8")):
                applicable -= len(OPTIONAL_WHEN_ABSENT)
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
