#!/usr/bin/env python3
"""Register ~/.agent-hooks/verify-hook.sh as a PostToolUse hook for Claude Code and Codex.

Idempotent: an existing registration of the same command is left as is. Each config is backed up
next to itself (<file>.bak-<tag>-<timestamp>) before it is written.
  register_verify_hook.py [--check]   --check: exit 1 if either host lacks the registration
  register_verify_hook.py --command PATH --claude-matcher M --tag T [--check]
                                      the same for another PostToolUse hook (scope-ledger's
                                      gap-map-hook.sh uses it)
"""
import json
import os
import shutil
import sys
import time

COMMAND = os.path.expanduser("~/.agent-hooks/verify-hook.sh")
TARGETS = (
    # (config path, matcher or None). Claude names the shell tool Bash; Codex hooks here carry no
    # matcher, and the hook filters on the command itself.
    (os.path.expanduser("~/.claude/settings.json"), "Bash"),
    (os.path.expanduser("~/.codex/hooks.json"), None),
)


def opt(name, default):
    args = sys.argv[1:]
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def registered(cfg, command=COMMAND):
    for entry in cfg.get("hooks", {}).get("PostToolUse", []):
        if any(h.get("command") == command for h in entry.get("hooks", [])):
            return True
    return False


def main():
    check = "--check" in sys.argv[1:]
    command = os.path.expanduser(opt("--command", COMMAND))
    tag = opt("--tag", "verify")
    missing = []
    for path, matcher in TARGETS:
        if path.endswith("settings.json"):
            matcher = opt("--claude-matcher", matcher)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            cfg = json.load(f)
        if registered(cfg, command):
            print(f"present  {path}")
            continue
        if check:
            missing.append(path)
            continue
        entry = {"hooks": [{"type": "command", "command": command, "timeout": 20}]}
        if matcher:
            entry = {"matcher": matcher, **entry}
        cfg.setdefault("hooks", {}).setdefault("PostToolUse", []).append(entry)
        shutil.copy2(path, f"{path}.bak-{tag}-{time.strftime('%Y%m%d%H%M%S')}")
        tmp = path + ".tmp-" + tag
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
        print(f"added    {path}")
    for path in missing:
        print(f"MISSING  {path}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
