#!/usr/bin/env python3
import datetime
import json
import os
import re
import shlex
import stat
import sys
from pathlib import Path

MODE_FILE = os.environ.get("SPAWN_ROUTE_MODE_FILE", os.path.expanduser("~/.agent-hooks/spawn-route.mode"))
LOG_FILE = os.environ.get(
    "SPAWN_ROUTE_LOG", os.path.join(os.path.expanduser("~"), ".agent-hooks", "spawn-route.log")
)
# body-3d: owner 2026-10-18 — tissue/organ/body-part/animation work runs on Claude.
LANES = {"architecture", "security", "auth", "authentication", "data-loss", "migration", "release", "final-review", "body-3d", "creative"}


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def declared_lane(text):
    normalized = text.lower().replace("_", "-")
    for lane in LANES:
        variants = {lane, lane.replace("-", " ")}
        for variant in variants:
            pattern = r"(?:claude[- ]lane|lane|role)\s*[:=]\s*(?:child[- ]+)?" + re.escape(variant) + r"\b"
            if re.search(pattern, normalized):
                return lane
    return ""


def bash_spawn(command):
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        words = list(lexer)
    except Exception:
        return False, None, "", []
    segments = []
    current = []
    for word in words:
        if word and all(char in ";&|" for char in word):
            if current:
                segments.append(current)
                current = []
        else:
            current.append(word)
    if current:
        segments.append(current)
    for segment in segments:
        i = 0
        while i < len(segment) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", segment[i]):
            i += 1
        while i < len(segment) and segment[i] in {"env", "command", "exec"}:
            i += 1
            while i < len(segment) and (segment[i].startswith("-") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", segment[i])):
                i += 1
        if i + 2 < len(segment) and os.path.basename(segment[i]) == "bb" and segment[i + 1:i + 3] == ["thread", "spawn"]:
            provider = None
            model = ""
            brief_files = []
            j = i + 3
            while j < len(segment):
                word = segment[j]
                if word == "--message":
                    j += 2
                    continue
                if word.startswith("--message="):
                    j += 1
                    continue
                if word.startswith("--provider="):
                    provider = word.split("=", 1)[1]
                elif word == "--provider" and j + 1 < len(segment):
                    provider = segment[j + 1]
                    j += 1
                elif word.startswith("--model="):
                    model = word.split("=", 1)[1]
                elif word == "--model" and j + 1 < len(segment):
                    model = segment[j + 1]
                    j += 1
                elif word.startswith(("--message-file=", "--prompt-file=")):
                    brief_files.append(word.split("=", 1)[1])
                elif word in ("--message-file", "--prompt-file") and j + 1 < len(segment):
                    brief_files.append(segment[j + 1])
                    j += 1
                j += 1
            return True, provider, model, brief_files
    return False, None, "", []


def evaluate(payload):
    tool = payload.get("tool_name") or payload.get("name") or ""
    args = payload.get("tool_input", payload.get("arguments", {}))
    if not isinstance(args, dict):
        return {"matched": False}
    is_spawn = False
    provider = args.get("provider") or args.get("providerId")
    model = args.get("model") or ""
    brief_files = []
    if tool == "Bash":
        command = args.get("command")
        if not isinstance(command, str):
            return {"matched": False}
        is_spawn, parsed_provider, parsed_model, brief_files = bash_spawn(command)
        if parsed_provider is not None:
            provider = parsed_provider
        if parsed_model:
            model = parsed_model
    elif tool.endswith("fleet_member_spawn") or tool == "fleet_member_spawn":
        is_spawn = True
    elif tool.endswith("fleet_task_create") or tool == "fleet_task_create":
        is_spawn = bool(args.get("spawnThread") is True or args.get("spawn_thread") is True
                        or any(k in args for k in ("provider", "providerId", "model", "prompt")))
    if not is_spawn:
        return {"matched": False}
    brief_parts = list(strings(args))
    for filename in brief_files:
        path = os.path.expanduser(filename)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "r", encoding="utf-8", errors="replace") as brief_file:
                metadata = os.fstat(brief_file.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 131072:
                    return {"matched": False}
                brief_parts.append(brief_file.read(131073))
        except OSError:
            return {"matched": False}
    brief = "\n".join(brief_parts)
    lane = declared_lane(brief)
    normalized_provider = str(provider or "claude-code").lower()
    targets_claude = normalized_provider in {"claude-code", "claude"}
    model_id = str(model).lower().replace("[", "-").replace("]", "")
    needs_1m = bool(re.search(r"\b(?:need|needs|require|requires)\s+(?:the\s+)?1m(?:\s+context)?\b", brief, re.I))
    denies_1m = bool(re.search(r"\b(?:do not|don't|does not|doesn't|never)\s+(?:need|needs|require|requires)\s+(?:the\s+)?1m(?:\s+context)?\b", brief, re.I))
    oversized = targets_claude and model_id.endswith("-1m") and not (needs_1m and not denies_1m)
    would_deny = (targets_claude and not lane) or oversized
    if targets_claude and not lane:
        reason = "Claude child spawn requires a declared Claude lane. For implementation, ops or bulk work, run 'bb fleet route implementation --role child' and use its provider, model, and reasoning. If the work really is a Claude lane, add a line 'lane: <architecture|security|auth|data-loss|migration|release|final-review|body-3d|creative>' to the brief."
    elif oversized:
        reason = "Use non-1M Claude model id (claude-opus-5-5 or claude-sonnet-5-5) unless the brief explicitly says it needs 1M."
    else:
        reason = ""
    return {"matched": True, "tool": tool, "provider": normalized_provider, "model": str(model),
            "lane": lane, "route_deny": targets_claude and not lane, "oversized": oversized,
            "would_deny": would_deny, "reason": reason}


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        decision = evaluate(payload)
        if not decision.get("matched"):
            return 0
        mode = Path(MODE_FILE).read_text(encoding="utf-8").strip()
        provider_class = decision["provider"] if decision["provider"] in {"claude-code", "claude", "codex", "openai"} else "other"
        model_value = str(decision["model"]).lower()
        model_class = "claude-1m" if "claude" in model_value and "1m" in model_value else "claude-standard" if "claude" in model_value else "codex" if model_value.startswith("gpt-") else "other"
        record = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                  "tool": decision["tool"], "provider": provider_class, "model": model_class,
                  "lane": decision["lane"], "route_deny": decision["route_deny"], "oversized": decision["oversized"], "would_deny": decision["would_deny"], "mode": mode}
        try:
            Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as out:
                out.write(json.dumps(record, separators=(",", ":")) + "\n")
        except Exception:
            return 0
        if mode == "deny" and decision["would_deny"]:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                  "permissionDecision": "deny", "permissionDecisionReason": decision["reason"]}}))
            print(decision["reason"], file=sys.stderr)
            return 2
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
