#!/usr/bin/env python3
"""Codex runs a hook from ~/.codex/hooks.json only if config.toml trusts its hash.

An untrusted hook is skipped with no error: on 2026-09-21 the coordinator-mode
hook fired for every Claude session and never once for Codex, for this reason.
The hash is codex-rs hook_hash (hooks/src/engine/discovery.rs) through
version_for_toml (config/src/fingerprint.rs): sha256 of compact, key-sorted
JSON of {event_name, matcher?, hooks:[{type, command, timeout, async}]}, with
None fields dropped because the identity passes through TOML.

  codex-hook-trust.py --check   exit 1 if any hooks.json command hook is untrusted
  codex-hook-trust.py --trust   record trust only for commands resolving under
                                ~/.agent-hooks (backs up config.toml first)
  --falsify                     prove the hash reproduces a known trusted value
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import time
import tomllib

CFG = os.path.expanduser("~/.codex/config.toml")
HOOKS = os.path.expanduser("~/.codex/hooks.json")
LABEL = {"PreToolUse": "pre_tool_use", "PostToolUse": "post_tool_use", "UserPromptSubmit": "user_prompt_submit",
         "SessionStart": "session_start", "SessionEnd": "session_end", "Stop": "stop",
         "SubagentStart": "subagent_start", "SubagentStop": "subagent_stop",
         "PermissionRequest": "permission_request", "PreCompact": "pre_compact", "PostCompact": "post_compact"}


def codex_hook_hash(event_label, command, timeout, matcher=None):
    ident = {"event_name": event_label,
             "hooks": [{"type": "command", "command": command, "timeout": timeout, "async": False}]}
    if matcher is not None:
        ident["matcher"] = matcher
    s = json.dumps(ident, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(s.encode()).hexdigest()


def hook_entries():
    out = {}
    for ev, groups in json.load(open(HOOKS)).get("hooks", {}).items():
        for gi, g in enumerate(groups):
            for hi, h in enumerate(g.get("hooks", [])):
                if h.get("type", "command") != "command":
                    continue
                key = "%s:%s:%d:%d" % (HOOKS, LABEL.get(ev, ev), gi, hi)
                command = h.get("command", "")
                out[key] = {
                    "hash": codex_hook_hash(LABEL.get(ev, ev), command, h.get("timeout", 600), g.get("matcher")),
                    "owned": is_agent_hook_command(command),
                }
    return out


def is_agent_hook_command(command):
    """Only trust command hooks whose executable script lives in agent-hooks."""
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    index = 0
    if os.path.basename(parts[0]) == "env":
        index = 1
        while index < len(parts) and (parts[index].startswith("-") or "=" in parts[index]):
            index += 1
    executable = os.path.basename(parts[index]) if index < len(parts) else ""
    interpreters = {"bash", "sh", "zsh", "python", "python3", "node", "ruby", "perl"}
    target = parts[index + 1] if executable in interpreters and index + 1 < len(parts) else parts[index]
    if not target or target.startswith("-") or target == "-c":
        return False
    expanded = os.path.expanduser(target)
    if not os.path.isabs(expanded):
        expanded = shutil.which(expanded) or expanded
    resolved = os.path.realpath(expanded)
    root = os.path.realpath(os.path.expanduser("~/.agent-hooks"))
    return resolved.startswith(root + os.sep)


def check(scope_only=False):
    state = tomllib.load(open(CFG, "rb")).get("hooks", {}).get("state", {})
    bad = 0
    for key, entry in hook_entries().items():
        if scope_only and not entry["owned"]:
            continue
        h = entry["hash"]
        st = state.get(key, {})
        if st.get("trusted_hash") != h or st.get("enabled") is False:
            bad += 1
            scope = "" if entry["owned"] else " (outside ~/.agent-hooks; left unchanged)"
            print("UNTRUSTED", key.split(":", 1)[1] + scope, "(Codex will silently skip it; inspect before trusting)")
    print("codex hooks: %d checked, %d untrusted" % (len(hook_entries()), bad))
    return 1 if bad else 0


def trust():
    entries = hook_entries()
    owned = {key: entry["hash"] for key, entry in entries.items() if entry["owned"]}
    for key, entry in entries.items():
        if not entry["owned"]:
            state = tomllib.load(open(CFG, "rb")).get("hooks", {}).get("state", {}).get(key, {})
            if state.get("trusted_hash") != entry["hash"] or state.get("enabled") is False:
                print("SKIP untrusted hook outside ~/.agent-hooks:", key.split(":", 1)[1])
    if not owned:
        print("no ~/.agent-hooks command hooks found; no trust entries changed")
        return check(scope_only=True)
    s = open(CFG).read()
    shutil.copy(CFG, CFG + ".bak-" + time.strftime("%Y%m%d%H%M%S"))
    for key, h in owned.items():
        header = '[hooks.state."%s"]' % key
        block = re.compile(re.escape(header) + r"\n(?:(?!\[).*\n?)*")
        new = header + '\ntrusted_hash = "%s"\nenabled = true\n\n' % h
        s = block.sub(new, s, count=1) if block.search(s) else s.rstrip("\n") + "\n\n" + new
    tomllib.loads(s)  # refuse to write invalid TOML
    open(CFG, "w").write(s)
    return check(scope_only=True)


def falsify():
    ok = codex_hook_hash("pre_tool_use", "/Users/alexandrebrandizzi/.agent-hooks/codex-context-hygiene.sh", 5) == \
        "sha256:80367355e038758b8be8ac940f2854317fc103d13916f60d26bde0896eb47c5f"
    ok_neg = codex_hook_hash("pre_tool_use", "/x", 5) != codex_hook_hash("pre_tool_use", "/x", 6)
    print("falsify: known hash reproduced=%s, timeout change alters hash=%s" % (ok, ok_neg))
    return 0 if ok and ok_neg else 1


if __name__ == "__main__":
    rc = 0
    if "--falsify" in sys.argv:
        rc |= falsify()
    if "--trust" in sys.argv:
        rc |= trust()
    elif "--check" in sys.argv or len(sys.argv) == 1:
        rc |= check()
    sys.exit(rc)
