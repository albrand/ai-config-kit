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
        r"\b(?:it|this|everything|all|(?:all|both|each|every|the|these|those|my|our)\s+"
        r"(?:(?!(?:so|that|and|or|but|to|of|if|when|once|until|after|before|while|its|is|are|was|were|in|on|for|"
        r"with|by|from|as|at|each|every|all|both|these|those)\b)[\w-]+\s+){0,3}?"
        r"(?:work|tasks?|changes?|fix(?:es)?|features?|workflows?|flows?|issues?|bugs?|requests?|implementations?|"
        r"builds?|apps?|sites?|releases?|prs?|deployments?|branch(?:es)?|journeys?|items?|steps?|deliverables?|"
        r"outcomes?|edits?|updates?))\s+"
        r"(?:is|are|was|were|has been|have been|is now|are now|was now|were now)\s+"
        # "merged" counts only with a work subject ("all three PRs are merged"); "I merged origin/develop into
        # the branch" is a git step, not a report that the work is done.
        r"(?P<claim>done|complete(?:d)?|finished|shipped|merged|deployed|ready|fixed|resolved|implemented|works?\b|working|tested|verified|validated)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:\*\*)?(?P<claim>done|complete(?:d)?|finished|shipped|deployed|ready|fixed|resolved|implemented|tested|verified|validated)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
)
# "Once everything is fixed, I push" is a condition; "Before handing off, all three fixes are done" reports done
# work after the comma, and "Before dispatch I fixed three defects" is an I/we main clause, not a condition.
TIME_CLAUSE = re.compile(r"\b(?:when|once|after|before)\s+[^.;,\n]*$", re.IGNORECASE)
NEGATED = re.compile(
    r"\b(?:not|never|cannot|can't|isn't|aren't|wasn't|weren't|didn't|"
    r"haven't|hasn't|won't|will not|not yet|unable to|nothing)\b",
    re.IGNORECASE,
)
# A claim inside a condition, an instruction or an in-progress check is not a report that the work is done:
# "when each fix is ready", "confirm the deployment is ready", "none of the items is fixed".
NOT_A_REPORT = re.compile(
    r"\b(?:(?:if|until|unless|whether)\s+[^.;\n]*|"
    r"(?:confirm(?:s|ing)?|check(?:s|ing)?|verify(?:ing)?|ensure|make sure|none of|neither|proves?|"
    r"recommend(?:s|ed|ation)?|approve|propose|suggest|should|would|could)\b[^.;:\n]*)$",
    re.IGNORECASE,
)
NOT_RUN = re.compile(r"\bimplemented\s*[;—-]\s*workflow\s+not\s+run\b", re.IGNORECASE)
REMAINS = re.compile(r"\b(?:what remains|remaining|still needs? to|next steps?|remains? to)\b", re.IGNORECASE)
EVENTS = os.environ.get("QA_GATE_EVENTS_FILE") or os.path.join(
    os.path.expanduser("~"), ".local", "state", "agent-quality", "events.jsonl")
# The retry after this hook's own nudge carries stop_hook_active. A probe answered the nudge with "Tests were
# not run" and stopped with a sub-second suite unrun (2026-10-01). Detecting every way of saying "not run" is
# open-ended, so the retry instead checks for one of the two answers the nudge asks for: an evidence packet,
# or a blocker that names an outside constraint. Neither present: one last nudge.
# Only an explicit blocker statement counts: an ordinary word such as "requires" or "sandbox" elsewhere in
# the message must not excuse runnable work (PR #36 review).
BLOCKER = re.compile(
    r"\bblockers?\s*(?:is|was)?\s*[:\-\u2014\u2013]\s*(?!(?:none|n/?a|nothing|not applicable|no blockers?)\b)\w+"
    r"|\bblocked\s+(?:by|on)\s+\w+"
    r"|\b(?:cannot|can't|can not|could not|couldn't|unable to)\s+(?:be\s+)?(?:run|execute|reach|access|start)\b"
    r"[^.\n]{0,60}?(?:\b(?:because|since|due to|without)\b|:)\s*\w+",
    re.IGNORECASE,
)
# A stated cause that is only a choice is not a blocker.
NOT_A_BLOCKER = re.compile(
    r"\b(?:time|timing|time ?box(?:ed)?|bandwidth|priorit(?:y|ies|ise|ize|ised|ized)|busy|effort|"
    r"convenience|preference|for brevity|not needed|unnecessary|not worth|too slow|takes too long|later)\b",
    re.IGNORECASE,
)
# A blocker must name a constraint outside the agent's own choices. Anything else ("capacity", "other work")
# gets the one bounded extra nudge; a fabricated but specific constraint still passes, by design.
REAL_CAUSE = re.compile(
    r"\b(?:credentials?|access|permissions?|login|log in|sign[- ]?in|auth\w*|secrets?|tokens?|api keys?|vpn|"
    r"network|offline|internet|sandbox\w*|not installed|install\w*|missing|unavailable|down|outage|"
    r"unreachable|timed? ?out|crash\w*|fail\w*|errors?|broken|owner|approval|approve|user|customer|"
    r"hardware|device|phone|licen[cs]e|quota|rate[- ]limit\w*|disk|space|memory|ci|staging|production|prod|"
    r"database|db|server|service|api|endpoint|dependenc\w*|package|toolchain|python|node|browser|"
    r"environment|env|data|fixtures?|account|vendor|third[- ]party|external|upstream|"
    r"not (?:allowed|permitted)|denied|forbidden)\b",
    re.IGNORECASE,
)
MARKER = re.compile(r"^\s*(?:blockers?\s*(?:is|was)?\s*[:\-\u2014\u2013]|blocked\s+(?:by|on))", re.IGNORECASE)
CLAUSE_END = re.compile(r"[.;\n]")


def names_blocker(plain):
    """True when some blocker statement, read up to the end of its own clause, gives a cause that is not a choice."""
    for match in BLOCKER.finditer(plain):
        end = CLAUSE_END.search(plain, match.end())
        clause = plain[match.start():end.start() if end else len(plain)]
        cause = MARKER.sub("", clause, count=1)
        if REAL_CAUSE.search(cause) and not NOT_A_BLOCKER.search(clause):
            return True
    return False


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
    both = re.compile(r"^(?:user\s+)?(?:outcomes?|goals?)(?:\s+attempted)?\s+(?:and|&|with)\s+verdicts?\s*:?$", re.I)
    columns = None  # (goal index, verdict index) of a multi-column table with those headers
    lines = text.splitlines()
    for index, raw in enumerate(lines):
        stripped = raw.lstrip()
        if not stripped.startswith("|"):
            columns = None  # the table ended: its goal and verdict columns do not apply to a later table
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
        heading_text = re.sub(r"[*_`]", "", re.sub(r"^#{1,6}\s*", "", stripped)).strip()
        if both.match(heading_text):
            current = "both"
            fields.setdefault("goals", [])
            fields.setdefault("derived_verdict", [])
            continue
        setext = bool(stripped and re.fullmatch(r"(?:=+|-+)", next_line))
        html_heading = re.match(r"^<h[1-6](?:\s[^>]*)?>", stripped, re.I)
        if setext or html_heading or re.match(r"^#{1,6}(?:\s|$)", stripped) or re.fullmatch(r"(?:[-*_]\s*){3,}", stripped):
            current = None
            continue
        line = re.sub(r"[*_`]", "", raw).strip().lstrip("- ")
        table_row = line.startswith("|")
        if table_row:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells if cell):
                continue  # separator row
            if len(cells) > 2:
                heads = [cell.lower() for cell in cells]
                goal = next((i for i, h in enumerate(heads) if re.match(r"(?:user\s+)?(?:goals?|outcomes?)\b", h)), None)
                verdict = next((i for i, h in enumerate(heads) if re.match(r"verdicts?\b", h)), None)
                if goal is not None and verdict is not None:
                    columns = (goal, verdict)
                elif columns and len(cells) > max(columns):
                    fields.setdefault("goals", []).append(cells[columns[0]])
                    fields.setdefault("derived_verdict", []).append(cells[columns[1]])
                current = None
                continue
            if len(cells) == 2:
                line = cells[0] + ": " + cells[1]
        match = label.match(line)
        if match:
            key = match.group(1).lower()
            current = "goals" if key.startswith(("goal", "user outcome")) else key.rstrip("s")
            fields.setdefault(current, []).append(match.group(2))
        elif table_row:
            current = None
        elif current == "both":
            if re.match(r"(?:\d+[.)]|[-*+])\s", stripped):
                fields["goals"].append(line)
                fields["derived_verdict"].append(line)
            elif line:
                current = None  # prose after the list is not part of the section
        elif re.match(r"^[A-Za-z][A-Za-z /()&-]{0,30}:\s", line):
            current = None  # another field, such as "Command:", ends the current one
        elif current and line:
            fields[current].append(line)
    values = {key: " ".join(parts).strip() for key, parts in fields.items()}
    if not all(values.get(key) for key in ("persona", "target", "goals")):
        return False
    # A "Verdict:" field may say "pass"; a verdict read from a table column or an outcomes section must be the
    # explicit uppercase token, so prose such as "the assertion pass" is not a verdict. Each source is judged
    # on its own value, so an empty "Verdict:" label cannot relax the check on the other.
    token = r"\b(?:PASS|FAIL|BLOCKED|NOT RUN)\b"
    labelled = bool(re.search(token, values.get("verdict", ""), re.I))
    derived = bool(re.search(token, values.get("derived_verdict", "")))
    if not (labelled or derived):
        return False
    target = values["target"]
    has_deployment = bool(re.search(r"https?://\S+", target) and re.search(r"\bdeployment(?:\s+id)?\b", target, re.IGNORECASE))
    has_stack_sha = bool(
        re.search(r"\b(?:stack|repo|project|commit|sha|head|branch|worktree)\b", target, re.IGNORECASE)
        and re.search(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b", target, re.IGNORECASE)
    )
    return has_deployment or has_stack_sha


def first_claim(text):
    found = []
    for pattern in CLAIM_PATTERNS:
        found.extend(pattern.finditer(text))
    for match in sorted(found, key=lambda item: item.start()):
        prefix = text[max(0, match.start() - 36):match.start()]
        line = text[text.rfind("\n", 0, match.start()) + 1:match.start()]
        quoted = (line.count("`") % 2 == 1 or text.count("```", 0, match.start()) % 2 == 1
                  or line.count('"') % 2 == 1 or line.count("\u201c") > line.count("\u201d"))
        clause = re.split(r"[.,;!?\n]", prefix)[-1]
        if line.lstrip().startswith(">") or quoted or NEGATED.search(clause) or NOT_A_REPORT.search(prefix):
            continue
        if TIME_CLAUSE.search(prefix) and match.re is not CLAIM_PATTERNS[0]:
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


def retry_key(payload):
    return str(payload.get("session_id") or payload.get("sessionId") or payload.get("transcript_path")
               or payload.get("transcriptPath") or payload.get("cwd") or "")


def _load_state():
    try:
        with open(RETRY_STATE, encoding="utf-8") as stream:
            state = json.load(stream)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state):
    os.makedirs(os.path.dirname(RETRY_STATE), mode=0o700, exist_ok=True)
    tmp = RETRY_STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as stream:
        json.dump(state, stream)
    os.replace(tmp, RETRY_STATE)


def record_first_pass(payload, nudged):
    """First stop of a turn: remember whether this hook nudged, so only its own retry is checked."""
    now = time.time()
    state = {k: v for k, v in _load_state().items()
             if isinstance(v, dict) and isinstance(v.get("t"), (int, float)) and now - v["t"] < RETRY_WINDOW_S}
    key = retry_key(payload)
    if nudged:
        state[key] = {"t": now, "retried": False}
    elif key not in state:
        return
    else:
        del state[key]
    try:
        _save_state(state)
    except OSError:
        return  # without the record the retry is not checked: fail open


def retry_check(payload, text):
    """On the retry after this hook's nudge: allow only an evidence packet or a named outside blocker, once."""
    key = retry_key(payload)
    state = _load_state()
    entry = state.get(key)
    if (not isinstance(entry, dict) or entry.get("retried") or not isinstance(entry.get("t"), (int, float))
            or time.time() - entry["t"] >= RETRY_WINDOW_S):
        return None  # not our nudge, already checked once, or expired: never loop
    entry["retried"] = True
    try:
        _save_state(state)
    except OSError:
        return None  # without the bound, do not block
    plain = text.replace("**", "").replace("__", "")
    if has_evidence_packet(text) or names_blocker(plain):
        return None
    return ("[qa-evidence] The reply to the evidence nudge has neither an evidence packet nor a blocker that names "
            "an outside constraint. If the workflow or tests can run, run them now and report the result with a "
            "packet. If they cannot, name what blocks them. This is the last nudge for this turn.")


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
        if not retry:
            record_first_pass(payload, False)
        return 0
    if retry:
        reason = retry_check(payload, text)
        if reason:
            append_claim_event(payload, "unanswered-nudge", "block")
            print(json.dumps({"decision": "block", "reason": reason}))
        return 0
    result = inspect(text)
    record_first_pass(payload, result["block"])
    if result.get("claim"):
        append_claim_event(payload, result["claim"], "block" if result["block"] else "allow")
    if result["block"]:
        print(json.dumps({"decision": "block", "reason": result["reason"]}))
    else:
        print(json.dumps({"decision": "allow", "claim": result.get("claim"), "not_run": result.get("not_run", False)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
