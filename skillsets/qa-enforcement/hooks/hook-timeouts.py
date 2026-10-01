#!/usr/bin/env python3
"""Hold host hook timeouts above the chains' delivery budgets.

A timed-out PreToolUse hook lets the command run: verified 2026-09-25 with a
live probe on Claude Code 2.1.282 (a hook sleeping past its 2 s timeout, the
command still ran), and in codex-rs/hooks/src/events/pre_tool_use.rs at
rust-v0.157.0 (a timeout is a Failed run, and only a Blocked run blocks).
The ship gate and the scope gate decide at HOOK_HARD_S (10 s) from the hook
chain's start; coordinator-hook-pretool.sh kills a gate stage at 11 s and
decides by shape in shell, and cuts its last stage at 12.5 s. That only holds if the host
timeout on the entry that runs coordinator-hook-pretool.sh is at least
HOOK_HOST_TIMEOUT_S; with the old 5 s a loaded host decided in 4.9-6.0 s and
the command ran ungated.

    hook-timeouts.py check [config ...]   exit 1 if any chain entry is below the gates' host timeout
    hook-timeouts.py apply [config ...]   set it (backup first; nothing else in the file may change)

Configs default to ~/.claude/settings.json and ~/.codex/hooks.json. The gates
are read from ~/.agents/skills unless HOOK_GATES_DIR points at a skills tree.

The Stop chain also needs margin: its repository lookup alone permits 5 s,
before Python startup and the evidence/closeout stages. A 5 s Stop timeout
can discard a valid continuation decision. Keep this chain at least 15 s.
"""
import copy
import datetime
import json
import os
import re
import shutil
import sys

CHAIN = "coordinator-hook-pretool.sh"
STOP_CHAIN = "qa-stop-hook.sh"
STOP_HOST_TIMEOUT_S = 15
HOME = os.path.expanduser("~")
DEFAULT_CONFIGS = [os.path.join(HOME, ".claude", "settings.json"), os.path.join(HOME, ".codex", "hooks.json")]
GATES = ["qa-sweep/scripts/ship-gate.py", "scope-ledger/scripts/scope-gate.py"]
CONST = re.compile(r"^HOOK_HOST_TIMEOUT_S\s*=\s*([0-9.]+)\s*$", re.M)


def host_timeout(problems, warn=print):
    """The largest HOOK_HOST_TIMEOUT_S among the installed gates. A gate that
    is missing or predates the constant is a warning, not a failure: during
    an install one gate is already new and the other is not yet, and the
    host timeout only has to cover the largest constant found."""
    root = os.environ.get("HOOK_GATES_DIR") or os.path.join(HOME, ".agents", "skills")
    values = {}
    for rel in GATES:
        path = os.path.join(root, rel)
        try:
            with open(path, encoding="utf-8") as stream:
                m = CONST.search(stream.read())
        except FileNotFoundError:
            continue  # that gate is not installed here (install.sh ships only qa-sweep)
        except OSError as e:
            warn(f"warn {path}: unreadable ({e})")
            continue
        if not m:
            warn(f"warn {path}: no HOOK_HOST_TIMEOUT_S (an older gate; reinstall it)")
            continue
        values[rel] = float(m.group(1))
    if len(set(values.values())) > 1:
        warn(f"warn the gates disagree on HOOK_HOST_TIMEOUT_S: {values}; using the largest")
    if not values:
        problems.append(f"no installed gate declares HOOK_HOST_TIMEOUT_S under {root} ({', '.join(GATES)})")
    return max(values.values()) if values else None


def chain_entries(cfg, event="PreToolUse", chain=CHAIN):
    """(group index, hook index, hook) for matching entries of one event."""
    for gi, group in enumerate((cfg.get("hooks") or {}).get(event) or []):
        for hi, h in enumerate(group.get("hooks") or []):
            if str(h.get("command", "")).rstrip().endswith(chain):
                yield gi, hi, h


def delivery_entries(cfg, pretool_need):
    for gi, hi, h in chain_entries(cfg):
        yield "PreToolUse", gi, hi, h, pretool_need
    for gi, hi, h in chain_entries(cfg, "Stop", STOP_CHAIN):
        yield "Stop", gi, hi, h, STOP_HOST_TIMEOUT_S


def check(configs):
    problems = []
    need = host_timeout(problems)
    for path in configs:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as stream:
                cfg = json.load(stream)
        except (OSError, ValueError) as e:
            problems.append(f"{path}: unreadable ({e})")
            continue
        entries = list(chain_entries(cfg))
        if not entries:
            problems.append(f"{path}: no PreToolUse entry runs {CHAIN}")
        for event, gi, hi, h, required in delivery_entries(cfg, need):
            t = h.get("timeout")
            if required is None:
                continue  # no gate to compare against: already a problem
            if not isinstance(t, (int, float)) or t < required:
                problems.append(f"{path}: {event}[{gi}].hooks[{hi}] timeout {t} < {required:.0f} s "
                                "(the chain needs delivery margin before the host timeout)")
            else:
                print(f"ok {path}: {event}[{gi}].hooks[{hi}] timeout {t} >= {required:.0f}")
    for p in problems:
        print(f"FAIL {p}")
    return 1 if problems else 0


def apply(configs):
    problems = []
    need = host_timeout(problems)
    if need is None:
        for p in problems:
            print(f"FAIL {p}")
        return 1
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    bk = os.path.join(HOME, ".agent-hooks", "backups", f"hook-timeouts-{stamp}")
    for path in configs:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as stream:
            before = json.load(stream)
        after = copy.deepcopy(before)
        changed = 0
        for event, gi, hi, h, required in delivery_entries(after, need):
            if not isinstance(h.get("timeout"), (int, float)) or h["timeout"] < required:
                after["hooks"][event][gi]["hooks"][hi]["timeout"] = int(required)
                changed += 1
        if not changed:
            print(f"unchanged {path}")
            continue
        # Nothing but the chain entries' timeouts may differ.
        strip = copy.deepcopy(after)
        for event, gi, hi, h, _ in delivery_entries(strip, need):
            original = before["hooks"][event][gi]["hooks"][hi]
            if "timeout" in original:
                h["timeout"] = original["timeout"]
            else:
                h.pop("timeout", None)
        if strip != before:
            print(f"FAIL {path}: refusing, the patch would change more than the chain timeouts")
            return 1
        os.makedirs(bk, exist_ok=True)
        shutil.copy2(path, os.path.join(bk, os.path.basename(os.path.dirname(path)).lstrip(".") + "-" + os.path.basename(path)))
        tmp = path + f".tmp-{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(after, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(tmp, os.stat(path).st_mode & 0o777)
        os.replace(tmp, path)
        print(f"set {changed} chain timeout(s) to their required budgets in {path} (backup {bk})")
    return check(configs)


def main(argv):
    if not argv or argv[0] not in ("check", "apply"):
        print(__doc__)
        return 2
    configs = argv[1:] or DEFAULT_CONFIGS
    return check(configs) if argv[0] == "check" else apply(configs)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
