#!/usr/bin/env python3
"""One-turn nudge when a final message makes an unsupported completion claim."""
import json
import datetime
import os
import re
import subprocess
import sys
import time


CLAIM_PATTERNS = (
    re.compile(
        r"\b(?:i|we)\s+(?:(?:have|has)\s+)?(?:now\s+|just\s+)?"
        r"(?P<claim>done|complete(?:d)?|finished|shipped|deployed|ready|fixed|resolved|implemented|works?\b|working|tested|verified|validated)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:it|this|everything|all|the\s+(?:requested\s+)?(?:work|task|change|fix|feature|workflow|flow|issue|bug|request|implementation|build|app|site|release|pr|deployment|branch|journey))\s+"
        r"(?:is|are|was|were|has been|have been|is now|are now|was now|were now)\s+"
        r"(?P<claim>done|complete(?:d)?|finished|shipped|deployed|ready|fixed|resolved|implemented|works?\b|working|tested|verified|validated)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:\*\*)?(?P<claim>done|complete(?:d)?|finished|shipped|deployed|ready|fixed|resolved|implemented|tested|verified|validated)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
)
NEGATED = re.compile(
    r"\b(?:not|never|cannot|can't|isn't|aren't|wasn't|weren't|didn't|"
    r"haven't|hasn't|won't|will not|not yet|unable to)\b",
    re.IGNORECASE,
)
NOT_RUN = re.compile(r"\bimplemented\s*[;—-]\s*workflow\s+not\s+run\b", re.IGNORECASE)
REMAINS = re.compile(r"\b(?:what remains|remaining|still needs? to|next steps?|remains? to)\b", re.IGNORECASE)
EVENTS = os.environ.get("QA_GATE_EVENTS_FILE") or os.path.join(
    os.path.expanduser("~"), ".local", "state", "agent-quality", "events.jsonl")
# The retry after a nudge carries stop_hook_active. A probe answered the nudge with "Tests were not run" and
# stopped with a sub-second suite unrun (2026-10-01), so one more bounded check runs on that retry.
UNRUN = re.compile(
    r"\b(?:tests?|test suite|suite|workflow|checks?|e2e|qa)\b[^.\n]{0,40}?"
    r"\b(?:not run|were not run|was not run|weren't run|wasn't run|not executed|not exercised)\b"
    r"|\bworkflow\s+not\s+run\b",
    re.IGNORECASE,
)
BLOCKER = re.compile(
    r"\b(?:blocked|blocker|cannot|can't|unable|requires?|required|unavailable|no access|denied|"
    r"not permitted|permission|credentials?|log ?in|offline|timed? out|missing|not installed|"
    r"no (?:test|python|node|network|browser)|sandbox)\b",
    re.IGNORECASE,
)
RETRY_STATE = os.environ.get("QA_EVIDENCE_RETRY_STATE") or os.path.join(
    os.path.expanduser("~"), ".local", "state", "agent-quality", "evidence-retry.json")
RETRY_WINDOW_S = 600


def has_evidence_packet(text):
    # Read labeled fields in any order, including bold labels and field/value
    # tables. Formatting should not make an otherwise complete packet invalid.
    fields = {}
    current = None
    fence = None
    label = re.compile(r"^(persona|target|goals?(?: attempted)?|user outcomes?|verdicts?)\s*:\s*(.*)$", re.I)
    lines = text.splitlines()
    for index, raw in enumerate(lines):
        stripped = raw.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if fence == marker:
                fence = None
            elif fence is None:
                fence = marker
            current = None
            continue
        if fence is not None or stripped.startswith(">"):
            current = None
            continue
        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
        setext = bool(stripped and re.fullmatch(r"(?:=+|-+)", next_line))
        html_heading = re.match(r"^<h[1-6](?:\s[^>]*)?>", stripped, re.I)
        if setext or html_heading or re.match(r"^#{1,6}(?:\s|$)", stripped) or re.fullmatch(r"(?:[-*_]\s*){3,}", stripped):
            current = None
            continue
        line = re.sub(r"[*_`]", "", raw).strip().lstrip("- ")
        table_row = line.startswith("|")
        if table_row:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) == 2:
                line = cells[0] + ": " + cells[1]
        match = label.match(line)
        if match:
            key = match.group(1).lower()
            current = "goals" if key.startswith(("goal", "user outcome")) else key.rstrip("s")
            fields.setdefault(current, []).append(match.group(2))
        elif table_row:
            current = None
        elif current and line:
            fields[current].append(line)
    values = {key: " ".join(parts).strip() for key, parts in fields.items()}
    if not all(values.get(key) for key in ("persona", "target", "goals", "verdict")):
        return False
    if not re.search(r"\b(?:PASS|FAIL|BLOCKED|NOT RUN)\b", values["verdict"], re.I):
        return False
    target = values["target"]
    has_deployment = bool(re.search(r"https?://\S+", target) and re.search(r"\bdeployment(?:\s+id)?\b", target, re.IGNORECASE))
    has_stack_sha = bool(
        re.search(r"\b(?:stack|repo|project)\b", target, re.IGNORECASE)
        and re.search(r"\b(?:commit|sha)\b", target, re.IGNORECASE)
        and re.search(r"\b[0-9a-f]{7,40}\b", target, re.IGNORECASE)
    )
    return has_deployment or has_stack_sha


def first_claim(text):
    found = []
    for pattern in CLAIM_PATTERNS:
        found.extend(pattern.finditer(text))
    for match in sorted(found, key=lambda item: item.start()):
        prefix = text[max(0, match.start() - 36):match.start()]
        line = text[text.rfind("\n", 0, match.start()) + 1:match.start()]
        if line.lstrip().startswith(">") or NEGATED.search(prefix):
            continue
        return match.group("claim").lower()
    return None


def inspect(text):
    claim = first_claim(text)
    if claim is None or has_evidence_packet(text):
        return {"block": False, "claim": claim}
    not_run = NOT_RUN.search(text)
    if not_run and REMAINS.search(text[not_run.end():]):
        return {"block": False, "claim": claim, "not_run": True}
    reason = (
        "[qa-evidence] Final message contains a completion or test claim without an evidence packet. "
        "If you can run the workflow or its tests now, run them first, then attach a packet with persona, "
        "target (stack plus commit SHA or deployment ID), user outcomes attempted, and a verdict for each "
        "goal. Only when it cannot be run now, restate the claim as ‘implemented; workflow NOT RUN’, name "
        "the blocker, and say what remains. Relabelling a runnable check as NOT RUN is not a fix. "
        "If you then report it unrun without naming a blocker, one last nudge follows."
    )
    return {"block": True, "claim": claim, "reason": reason}


def part_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            str(part.get("text", "")) for part in value
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def assistant_text(entry):
    """Extract assistant text from Claude JSONL or Codex rollout entries."""
    if not isinstance(entry, dict):
        return ""
    if entry.get("type") == "assistant":
        message = entry.get("message") if isinstance(entry.get("message"), dict) else entry
        return part_text(message.get("content")) or part_text(message.get("text"))
    payload = entry.get("payload")
    if isinstance(payload, dict):
        if payload.get("role") == "assistant" or payload.get("type") in ("agent_message", "assistant_message"):
            return part_text(payload.get("content")) or part_text(payload.get("message")) or part_text(payload.get("text"))
        if payload.get("type") == "message" and payload.get("role") == "assistant":
            return part_text(payload.get("content")) or part_text(payload.get("text"))
    if entry.get("role") == "assistant":
        return part_text(entry.get("content")) or part_text(entry.get("text"))
    return ""


def transcript_assistant_text(path):
    if not isinstance(path, str) or not path:
        return ""
    try:
        latest = ""
        with open(path, encoding="utf-8") as stream:
            for line in stream:
                try:
                    text = assistant_text(json.loads(line))
                except (json.JSONDecodeError, TypeError):
                    continue
                if text:
                    latest = text
        return latest
    except (OSError, UnicodeError):
        return ""


def event_provider(payload):
    provider = safe_label(payload.get("provider"))
    if provider:
        return provider
    runtime = safe_label(payload.get("runtime"))
    if runtime:
        return runtime
    transcript = str(payload.get("transcript_path") or payload.get("transcriptPath") or "")
    if "/.codex/sessions/" in transcript or "/rollout-" in transcript or payload.get("turn_id") is not None or payload.get("model"):
        return "codex"
    if "/.claude/projects/" in transcript or payload.get("prompt_id") is not None or str(payload.get("tool_use_id", "")).startswith("toolu_"):
        return "claude-code"
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "claude-code"
    if any(key.startswith("CODEX_") for key in os.environ):
        return "codex"
    return safe_label(os.environ.get("QA_GATE_PROVIDER") or os.environ.get("AGENT_PROVIDER"))


def safe_label(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value) else ""


def event_repo(cwd):
    if not isinstance(cwd, str) or not cwd:
        return ""
    try:
        root = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=1, check=True,
        ).stdout.strip()
        return root or cwd
    except (OSError, subprocess.SubprocessError):
        return cwd


def append_claim_event(payload, claim, decision):
    """Append only bounded metadata; final message text is never persisted."""
    try:
        cwd = payload.get("cwd") or payload.get("working_directory") or ""
        provider = event_provider(payload)
        event = {
            "schema_version": 1,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "event": "evidence-claim",
            "cwd": event_repo(cwd),
            "provider": provider,
            "runtime": safe_label(payload.get("runtime")),
            "claim": claim,
            "decision": decision,
        }
        os.makedirs(os.path.dirname(EVENTS), mode=0o700, exist_ok=True)
        fd = os.open(EVENTS, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            with os.fdopen(fd, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
    except Exception:
        # Evidence nudging must not strand a turn if telemetry is unavailable.
        pass


def retry_check(payload, text):
    """On the retry stop: one more nudge when work is reported unrun with no blocker named."""
    plain = text.replace("**", "").replace("__", "")
    if not UNRUN.search(plain) or BLOCKER.search(plain):
        return None
    key = str(payload.get("session_id") or payload.get("sessionId") or payload.get("transcript_path")
              or payload.get("transcriptPath") or payload.get("cwd") or "")
    now = time.time()
    try:
        with open(RETRY_STATE, encoding="utf-8") as stream:
            state = json.load(stream)
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    state = {k: v for k, v in state.items() if isinstance(v, (int, float)) and now - v < RETRY_WINDOW_S}
    if key in state:
        return None  # already nudged on a retry in this window: never loop
    state[key] = now
    try:
        os.makedirs(os.path.dirname(RETRY_STATE), mode=0o700, exist_ok=True)
        tmp = RETRY_STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as stream:
            json.dump(state, stream)
        os.replace(tmp, RETRY_STATE)
    except OSError:
        return None  # without the bound, do not block
    return ("[qa-evidence] You report the workflow or tests as not run and name no blocker. If they can run, "
            "run them now and report the result with an evidence packet. If they cannot, name the blocker. "
            "This is the last nudge for this turn.")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    retry = bool(payload.get("stop_hook_active") or payload.get("stopHookActive"))
    text = payload.get("text")
    if not isinstance(text, str):
        text = payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or ""
    if not isinstance(text, str) or not text:
        text = transcript_assistant_text(payload.get("transcript_path") or payload.get("transcriptPath"))
    if not isinstance(text, str) or not text:
        return 0
    if retry:
        reason = retry_check(payload, text)
        if reason:
            append_claim_event(payload, "unrun-on-retry", "block")
            print(json.dumps({"decision": "block", "reason": reason}))
        return 0
    result = inspect(text)
    if result.get("claim"):
        append_claim_event(payload, result["claim"], "block" if result["block"] else "allow")
    if result["block"]:
        print(json.dumps({"decision": "block", "reason": result["reason"]}))
    else:
        print(json.dumps({"decision": "allow", "claim": result.get("claim"), "not_run": result.get("not_run", False)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
