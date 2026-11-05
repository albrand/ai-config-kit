#!/usr/bin/env python3
"""Coordinator mode: make "orchestrate this" and big tasks actually get delegated.

Written 2026-09-21. The operator kept asking gpt-5.6-terra threads to act as
the orchestrator and coordinate child agents; they acknowledged it and then did
all of the work themselves. An instruction that a model may weigh against
"it's faster if I just do it" loses. This makes the role mechanical.

One script, two hook events, every harness (Claude Code, Codex, opencode):

  prompt  (UserPromptSubmit) -- classify the session from what the user said:
      child       the prompt carries the child marker "[child of " (coordinators
                  put it in every brief; the fleet plugin adds it to spawns)
      solo        the user said to do it yourself / without children
      coordinator the user asked for orchestration / children / fan-out
    and, for coordinator, inject a reminder of the role into context.

  pretool (PreToolUse) -- count spawns and edits, and enforce:
      coordinator  -> any edit to a real file is blocked with instructions
      unmarked     -> never blocked; edited files are only counted (the
                      edit-count promotion was removed 2026-09-21)
      child, solo  -> never blocked

Scratch space is always writable (/tmp, thread storage, plans, memory).
Agent-tool subagents (payload carries agent_id) are children by definition.
A session with no recorded prompt (a harness-internal sub-agent) is never
promoted, so native sub-agents are not jammed by the counter.

State: ~/.agent-hooks/state/coordinator/<session>.json. Events (no prompt or
file contents, only kinds and counts) append to coordinator-events.jsonl, which
coordinator-report.py reads to show whether sessions actually delegate.

Output: JSON {"block": bool, "reason": str, "context": str}. FAILS OPEN.
"""
import json
import os
import re
import sys
import time

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, ".agent-hooks", "state", "coordinator")
EVENTS = os.path.join(HOME, ".agent-hooks", "coordinator-events.jsonl")

# In the session's FIRST prompt only: a line that starts with the child
# marker. bb puts a coordinator preamble before the brief, so the marker is
# usually NOT the first line (2026-09-24: a child was misclassified as its own
# coordinator and blocked). A marker quoted mid-sentence still does not count;
# completion notices arrive as later prompts, which classify() ignores.
CHILD_MARK = re.compile(r"^\s*\[child of (?:@thread:|thr_)", re.I | re.M)
# Intent to BE the coordinator or to USE children -- not a mention of the words.
# "fix the fleet plugin" or "coordinate with design" must not lock a thread.
_AGENTS = r"(?:multiple |several |many |some |the |parallel |more |other )?(?:child(?:ren)?(?: agents?| threads?)?|sub-?agents?|agents|workers|members|lanes)"
SOLO = re.compile(
    r"\b((?<!don't )(?<!dont )(?<!do not )(?<!never )do (it|this|everything) (yourself|alone|directly)|(?<!not )by yourself|"
    r"(no|without|don'?t use|do not use|skip) (the )?(children|child agents|sub-?agents|delegat\w*|orchestrat\w*)|"
    r"don'?t (delegate|orchestrate|spawn)|do not (delegate|orchestrate|spawn)|solo mode|work solo)\b", re.I)
# Stop a negated span at punctuation or a clause joiner so a later positive ask stays.
_NEG_TAIL = r"(?:(?!\s+(?:and|but|then|so|or)\b)[^.;,])*"
NEGATION_STRIP = (
    re.compile(r"don'?t orchestrate(?:\s+(?!(?:and|but|then|so|or)\b)\w+){0,2}", re.I),
    re.compile(r"do not orchestrate(?:\s+(?!(?:and|but|then|so|or)\b)\w+){0,2}", re.I),
    re.compile(r"don'?t spawn" + _NEG_TAIL, re.I),
    re.compile(r"do not spawn" + _NEG_TAIL, re.I),
    re.compile(r"don'?t delegate" + _NEG_TAIL, re.I),
    re.compile(r"do not delegate" + _NEG_TAIL, re.I),
    re.compile(r"no need to (?:delegate|orchestrat\w*)" + _NEG_TAIL, re.I),
    re.compile(r"skip (?:the )?children" + _NEG_TAIL, re.I),
    re.compile(r"don'?t use (?:the )?(?:children|child agents|sub-?agents)" + _NEG_TAIL, re.I),
)
WEAK_WITH_AGENTS = re.compile(r"\bwith\s+" + _AGENTS, re.I)
COORD = re.compile(
    r"\b(?:(?:be|act as|become|you are|you're|as|work as|run as) (?:the |an |a |my |our )?(?:orchestrator|coordinator|master(?: thread)?|lead agent)"
    r"|orchestrate(?! (?:plugin|skill|tool)s?\b)"
    r"|(?:use|spawn|launch|coordinate|create|dispatch|delegate to|split (?:it |this |the work )?(?:across|between|among)|with) " + _AGENTS +
    r"|fan[- ]?out|subagents swarm allowed|divide (?:and|&) conquer)\b", re.I)

SPAWN_TOOLS = {"agent", "task", "spawn_agent", "fleet_member_spawn", "mcp__bb-bridge__fleet_member_spawn",
               "fleet_delegate", "mcp__bb-bridge__fleet_delegate"}
SPAWN_SHELL = re.compile(r"\bbb\s+(thread\s+spawn|fleet\s+(spawn|delegate))\b|fleet_member_spawn|spawn_agent\s*\(")
EDIT_TOOLS = {"edit", "write", "multiedit", "notebookedit", "apply_patch", "str_replace_based_edit_tool"}
# A shell edit only when the patch tool is the command being run: at the
# start of the command or right after | && ; or a newline. A mention inside a
# quoted argument or a heredoc body is not an edit (2026-09-24: a read-only
# grep for the word, and a heredoc body that mentioned it, both blocked a
# live coordinator session).
SHELL_EDIT = re.compile(r"(?:^|&&|[|;\n])\s*(?:apply_patch\b|sed\s+(?:-\w+\s+)*-i\b|perl\s+(?:-\w+\s+)*-p?i\b)")
PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.M)
SCRATCH = ("/tmp/", "/private/tmp/", "/var/folders/", os.path.join(HOME, ".bb", "thread-storage"),
           os.path.join(HOME, ".claude", "projects"), os.path.join(HOME, ".claude", "plans"),
           os.path.join(HOME, ".agent-hooks", "state"))

COORD_CONTEXT = (
    "[coordinator-mode] You are the COORDINATOR for this request. Load the `orchestration` "
    "skill now and follow it. You plan, cut the work into cards, spawn children with "
    "self-contained briefs (first line `[child of @thread:<your thread id>]`), wait, verify their "
    "evidence and integrate. You do not implement: edits to project files from this session "
    "are blocked by a hook. Reading, planning, spawning, reviewing and running checks are yours.")


def out(block=False, reason="", context=""):
    print(json.dumps({"block": bool(block), "reason": reason, "context": context}))
    sys.exit(0)


def load(sid):
    try:
        with open(os.path.join(STATE, sid + ".json")) as fh:
            return json.load(fh)
    except Exception:
        return {"mode": "", "files": [], "spawns": 0, "prompted": False}


def save(sid, st):
    os.makedirs(STATE, exist_ok=True)
    tmp = os.path.join(STATE, sid + ".json.tmp")
    with open(tmp, "w") as fh:
        json.dump(st, fh)
    os.replace(tmp, os.path.join(STATE, sid + ".json"))


def event(sid, kind, **kw):
    try:
        with open(EVENTS, "a") as fh:
            fh.write(json.dumps(dict(at=time.strftime("%Y-%m-%dT%H:%M:%S"), session=sid, kind=kind,
                                     thread=os.environ.get("BB_THREAD_ID", ""), **kw)) + "\n")
    except Exception:
        pass


def negation_floor(span):
    head = re.match(
        r"(?:(?:don'?t|do not)\s+(?:orchestrate|spawn|delegate)|"
        r"no need to (?:delegate|orchestrat\w*)|"
        r"skip (?:the )?children|"
        r"don'?t use (?:the )?(?:children|child agents|sub-?agents))\b",
        span,
        re.I,
    )
    return head.end() if head else 0


def negation_removal_end(span):
    """How much of a negation match may be removed without swallowing a COORD hit."""
    floor = negation_floor(span)
    hit = COORD.search(span, floor)
    if hit:
        return hit.start()
    return len(span)


def strip_negated_spans(prompt):
    text = prompt
    while True:
        removed = False
        for pat in NEGATION_STRIP:
            m = pat.search(text)
            if not m:
                continue
            span = m.group(0)
            end = negation_removal_end(span)
            if end <= 0:
                continue
            text = text[: m.start()] + (" " * end) + text[m.start() + end :]
            removed = True
            break
        if not removed:
            break
    return text


def wants_coordinator(prompt):
    """True when COORD still matches after negated spans are removed."""
    stripped = strip_negated_spans(prompt)
    if not COORD.search(stripped):
        return False
    if WEAK_WITH_AGENTS.search(stripped) and re.search(
            r"do not delegate|don'?t delegate", prompt, re.I):
        without_weak = re.sub(r"\bwith\s+" + _AGENTS, " ", stripped, flags=re.I)
        return bool(COORD.search(without_weak))
    return True


def classify(prompt, first):
    if first and CHILD_MARK.search(prompt):
        return "child"
    if wants_coordinator(prompt):
        return "coordinator"
    if re.search(r"don'?t orchestrate|do not orchestrate", prompt, re.I):
        return "solo"
    if SOLO.search(prompt):
        return "solo"
    return ""


def on_prompt(p, sid, st):
    prompt = p.get("prompt") or p.get("user_prompt") or p.get("message") or ""
    if not isinstance(prompt, str):
        prompt = json.dumps(prompt)
    first = not st.get("prompted")
    st["prompted"] = True
    new = classify(prompt, first)
    # child is sticky: a child's later messages from its coordinator stay child
    if st.get("mode") != "child" and new:
        if new != st.get("mode"):
            event(sid, "mode", mode=new, via="prompt")
        st["mode"] = new
    save(sid, st)
    if st.get("mode") == "coordinator":
        out(context=COORD_CONTEXT)
    out()


def tool_parts(p):
    tool = str(p.get("tool_name") or p.get("toolName") or p.get("tool") or "")
    inp = p.get("tool_input") or p.get("toolInput") or p.get("input") or p.get("arguments") or {}
    return tool, inp


def flatten(v):
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v)
    except Exception:
        return ""


def edited_paths(tool, inp, text):
    paths = []
    if isinstance(inp, dict):
        for k in ("file_path", "filePath", "path", "notebook_path"):
            if isinstance(inp.get(k), str):
                paths.append(inp[k])
    paths += [m.strip() for m in PATCH_FILE.findall(text.replace("\\n", "\n"))]
    return paths


def is_scratch(path, cwd):
    full = path if os.path.isabs(path) else os.path.join(cwd or "", path)
    full = os.path.normpath(os.path.expanduser(full))
    return any(full.startswith(s) for s in SCRATCH)


def shell_edit_probe(inp):
    """The text SHELL_EDIT is judged on: the real command string with heredoc
    bodies removed, so a body that merely mentions a patch tool cannot read
    as an edit. Non-command inputs fall back to the flattened payload."""
    cmd = inp.get("command") if isinstance(inp, dict) else None
    if not isinstance(cmd, str):
        return flatten(inp)
    return re.sub(r"(<<-?\s*[\"']?(\w+)[\"']?\n)[\s\S]*?\n\2(?=\n|$)", r"\1\2", cmd)


def on_pretool(p, sid, st):
    tool, inp = tool_parts(p)
    text = flatten(inp)
    low = tool.lower()
    if p.get("agent_id") or p.get("agentId"):
        out()  # a Claude Agent-tool subagent is a child by definition
    if low in SPAWN_TOOLS or low.endswith("fleet_member_spawn") or SPAWN_SHELL.search(text):
        st["spawns"] = st.get("spawns", 0) + 1
        save(sid, st)
        event(sid, "spawn", tool=tool)
        out()
    is_edit = low in EDIT_TOOLS or bool(SHELL_EDIT.search(shell_edit_probe(inp)))
    if not is_edit:
        out()
    mode = st.get("mode", "")
    if mode in ("child", "solo"):
        out()
    cwd = p.get("cwd") or os.getcwd()
    paths = edited_paths(tool, inp, text)
    real = [x for x in paths if not is_scratch(x, cwd)]
    if paths and not real:
        out()  # scratch only
    if mode == "coordinator":
        event(sid, "block", why="coordinator-edit", files=len(real) or 1)
        out(True,
            "[coordinator-mode] Blocked: this session is the coordinator, and coordinators do not "
            "edit project files. Put this change in a card and spawn a durable bb child for it: "
            "`bb fleet route <kind>`, then `bb thread spawn --parent-self` or fleet_member_spawn "
            "(in-session subagents such as Codex spawn_agent are invisible in bb and lack the bb "
            "browser; use them only for read-only research). Give it a self-contained brief whose "
            "first line is `[child of @thread:<this thread id>]`. "
            "Keep planning, reviewing and verifying. See the `orchestration` skill. Only the user can "
            "switch this off, by telling you to do it yourself.")
    if not st.get("prompted"):
        out()  # harness-internal sub-agent: never promoted
    files = set(st.get("files", []))
    files.update(real or ["<shell-edit>"])
    st["files"] = sorted(files)
    # No edit-count promotion (removed 2026-09-21, "Delivery first"): a
    # one-repo fix touching many files is one agent's job, and a hard block
    # mid-fix cost more than the delegation it forced. Only an explicit ask
    # from the user makes a coordinator. The file count stays for the report.
    save(sid, st)
    out()


def main():
    event_kind = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        p = json.loads(sys.stdin.read())
    except Exception:
        out()
    if not isinstance(p, dict):
        out()
    sid =str(p.get("session_id") or p.get("sessionId") or p.get("sessionID")
              or os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("BB_THREAD_ID") or "")
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", sid)
    if not sid:
        out()
    st = load(sid)
    if event_kind == "prompt":
        on_prompt(p, sid, st)
    if event_kind == "pretool":
        on_pretool(p, sid, st)
    out()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        out()
