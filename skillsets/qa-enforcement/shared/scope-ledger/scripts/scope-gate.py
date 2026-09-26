#!/usr/bin/env python3
"""Scope ledger and the spawn/tell gate.

Operator complaint (2026-09-25): "agents are deviating and drifting from the
original focus and there is nothing enforcing this scope". Scope rules were
prose; nothing checked a dispatch against what the user asked for.

A coordinator thread's ledger lives at
    ~/.local/state/agent-quality/scope/<thread_id>.json
and holds the user's purposes in the user's own words:
    {"thread_id": "thr_...",
     "purposes": [{"id": "P1", "text": "<verbatim>", "done_when": "...",
                   "status": "open|done|blocked-on-user", "evidence": [],
                   "status_marked_at": "<iso>", "ask": null}],
     "accepted_revisions": [{"quote": "<the user's approval, verbatim>",
                             "accepted_at": "<iso>", "source": "..."}],
     "released_children": [{"thread_id": "thr_...", "evidence": "<why done>",
                            "released_at": "<iso>"}]}

`hook` is the PreToolUse gate. From a thread that HAS a ledger, every
dispatch -- `bb thread spawn|create|tell|message` in a shell command,
fleet_member_spawn, fleet_member_tell, fleet_delegate -- must carry
    serves: P<n>                  (an OPEN purpose), or
    serves: revision "<quote>"    (equal to an accepted revision's quote)
or it is denied with the open purposes listed. Threads without a ledger are
never touched. A ledger that exists but cannot be read denies dispatches
(fail closed); everything that is not a dispatch is allowed.

Subcommands:
    hook                                    PreToolUse (stdin payload, env BB_THREAD_ID)
    check <thread> <text|->                 the decision for a brief, without a tool call
    init <thread> --from <ledger.json>      create a ledger (refuses to overwrite)
    add <thread> --text T --done-when D     append a purpose in the user's words
    mark <thread> <Pn> <status> [--ask Q] [--evidence E]
    revise <thread> --quote Q [--source S]  record a user-approved scope change
    release <thread> <child> --evidence E   a finished child: fleet stops holding it
                                            from archive (only the child's parent
                                            ledger counts; its own ledger still holds)
    show <thread>
    selftest

SCOPE_LEDGER_DIR overrides the ledger directory (tests only).
"""
import datetime
import json
import os
import re
import shlex
import sys
import tempfile

sys.dont_write_bytecode = True  # no __pycache__: the four skill homes stay identical
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shell_dispatch import dispatches  # noqa: E402

LEDGER_DIR = os.environ.get("SCOPE_LEDGER_DIR") or os.path.expanduser("~/.local/state/agent-quality/scope")
DECISIONS = os.path.expanduser("~/.local/state/agent-quality/scope-decisions.jsonl")
THREAD_ID = re.compile(r"^thr_[a-z0-9]+$")
STATUSES = ("open", "done", "blocked-on-user")

FILE_FLAG = re.compile(r"""--(?:prompt|message)-file(?:=|\s+)(?:"([^"]+)"|'([^']+)'|(\S+))""")
CAT_SUB = re.compile(r"""\$\(\s*cat\s+(?:"([^"]+)"|'([^']+)'|([^\s)]+))\s*\)""")
REDIRECT_IN = re.compile(r"""(?<![<0-9])<\s*(?:"([^"]+)"|'([^']+)'|([^\s<;&|)]+))""")
MCP_TOOL = re.compile(r"(?:^|[^a-z])(fleet_member_spawn|fleet_member_tell|fleet_delegate)$")
# The decision must land before the host's hook timeout, because a timed-out
# hook lets the command run (Claude Code 2.1.282, probed live 2026-09-25;
# Codex 0.157.0, codex-rs/hooks pre_tool_use.rs). The clock starts with the
# hook chain (HOOK_T0 from coordinator-hook-pretool.sh), so start-up and the
# ship gate before this stage count. At HOOK_HARD_S a dispatch-shaped payload
# from a ledger thread with no `serves:` is denied by shape; anything else is
# allowed, as when the gate crashes. Same constants as qa-sweep's ship gate;
# hooks/check-hook-timeouts.sh holds the host config to them.
HOOK_HOST_TIMEOUT_S = 15.0
# Below the chain supervisor's GATE_DEADLINE (11 s, coordinator-hook-pretool.sh),
# which kills a stage still running then; this gate's own deny usually wins.
HOOK_HARD_S = 10.0
# Matched against the payload with quotes and backslashes removed, so
# `bb thr"ead" tell` reads as the dispatch the shell will run.
COARSE_DISPATCH = re.compile(r'fleet_member_(spawn|tell)|fleet_delegate|thread.{0,40}(spawn|create|fork|tell|message|edit-message|queue)|'
                             r'fleet.{0,20}(group-create|task-add|advise)', re.I)
MCP_FIELDS = {"fleet_member_spawn": ("prompt", "concern"), "fleet_member_tell": ("message",), "fleet_delegate": ("task",)}
SERVES_P = re.compile(r"serves:\s*((?:P\d+\b[\s,/&+]*(?:and\s+)?)+)", re.I)
SERVES_REV = re.compile(r"""serves:\s*revision\s*["“]([^"”]+)["”]""", re.I)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collapse(s):
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- the ledger

class LedgerError(Exception):
    pass


def ledger_path(thread):
    if not THREAD_ID.match(thread or ""):
        raise LedgerError(f"not a thread id: {thread!r}")
    return os.path.join(LEDGER_DIR, f"{thread}.json")


def validate(ledger, thread):
    if not isinstance(ledger, dict):
        raise LedgerError("ledger is not an object")
    if ledger.get("thread_id") != thread:
        raise LedgerError(f"thread_id {ledger.get('thread_id')!r} != {thread}")
    purposes = ledger.get("purposes")
    if not isinstance(purposes, list) or not purposes:
        raise LedgerError("no purposes")
    seen = set()
    for p in purposes:
        if not isinstance(p, dict) or not re.match(r"^P\d+$", str(p.get("id", ""))):
            raise LedgerError(f"bad purpose id {p.get('id') if isinstance(p, dict) else p!r}")
        if p["id"] in seen:
            raise LedgerError(f"duplicate purpose {p['id']}")
        seen.add(p["id"])
        if not isinstance(p.get("text"), str) or not p["text"].strip():
            raise LedgerError(f"{p['id']} has no text")
        if p.get("status") not in STATUSES:
            raise LedgerError(f"{p['id']} status {p.get('status')!r}")
    revisions = ledger.setdefault("accepted_revisions", [])
    if not isinstance(revisions, list) or any(not isinstance(r, dict) or not str(r.get("quote", "")).strip() for r in revisions):
        raise LedgerError("accepted_revisions must be a list of {quote}")
    released = ledger.get("released_children", [])
    if not isinstance(released, list) or any(
            not isinstance(r, dict) or not THREAD_ID.match(str(r.get("thread_id", "")))
            or not isinstance(r.get("evidence"), str) or not r["evidence"].strip() for r in released):
        raise LedgerError("released_children must be a list of {thread_id, evidence}")
    return ledger


def read_ledger(thread):
    """None when absent; raises LedgerError when present but unusable."""
    path = ledger_path(thread)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise LedgerError(f"unreadable: {e}")
    try:
        data = json.loads(text)
    except ValueError as e:
        raise LedgerError(f"unparseable: {e}")
    return validate(data, thread)


def write_ledger(thread, ledger):
    validate(ledger, thread)
    os.makedirs(LEDGER_DIR, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=LEDGER_DIR, prefix=".ledger-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, ledger_path(thread))


# ---------------------------------------------------------------- the decision

def decide(ledger, texts):
    """(allow, reason, serves) for dispatch texts against a ledger."""
    purposes = {p["id"]: p for p in ledger["purposes"]}
    revisions = {collapse(r["quote"]) for r in ledger.get("accepted_revisions", [])}
    served = []
    for text in texts:
        ok = None
        for m in SERVES_P.finditer(text):
            for pid in re.findall(r"P\d+", m.group(1), re.I):
                pid = pid.upper()
                p = purposes.get(pid)
                if p and p["status"] == "open":
                    ok = pid
                    break
                served.append(f"{pid} ({'unknown' if not p else p['status']})")
            if ok:
                break
        if not ok:
            for m in SERVES_REV.finditer(text):
                if collapse(m.group(1)) in revisions:
                    ok = "revision"
                    break
                served.append("revision (no accepted revision has that exact quote)")
        if not ok:
            return False, served, None
    return True, served, ok


def deny_reason(ledger, thread, served):
    lines = [f"[scope-gate] Dispatch from {thread} denied: the brief must say which of the user's purposes it serves."]
    if served:
        lines.append("It named: " + ", ".join(served) + " -- only an OPEN purpose or an accepted revision counts.")
    opened = [p for p in ledger["purposes"] if p["status"] == "open"]
    lines.append("Open purposes (the user's words):" if opened else "No purpose is open.")
    for p in opened:
        lines.append(f'  serves: {p["id"]}   "{p["text"]}"')
    for p in ledger["purposes"]:
        if p["status"] == "blocked-on-user":
            lines.append(f'  ({p["id"]} is blocked-on-user: {p.get("ask") or "no ask recorded"})')
    for r in ledger.get("accepted_revisions", []):
        lines.append(f'  serves: revision "{collapse(r["quote"])}"')
    lines.append("Add one of those lines to the brief or message. If the work serves none of them, it is outside the request: ask the user, and record their approval with `scope-gate.py revise`.")
    return "\n".join(lines)


# ---------------------------------------------------------------- the payload

ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:?-)?([^}]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
# Why a brief file could not be read, for the deny message; reset per payload.
FILE_NOTES = []


# Names a command assigns itself: `D=...;`, `export D=...`, `for D in`, `read D`.
# The hook reads brief files before the command runs, so its value for such a
# name is not the one the command will use (live miss, 2026-09-25 23:15Z:
# `D=...; bb thread tell ... --message-file $D/x.md`). Over-approximates on
# purpose (a prefix assignment, or `D=` inside a quoted argument, also counts):
# the cost is a deny whose message says to use a literal path.
ASSIGNED_NAME = re.compile(
    r"(?:^|[\s;&|(){}`])(?:(?:export|local|declare|typeset|readonly)\s+(?:-\w+\s+)*)?([A-Za-z_][A-Za-z0-9_]*)\+?="
    r"|\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b"
    r"|\bread\s+(?:-\w+\s+)*([A-Za-z_][A-Za-z0-9_]*)")


def assigned_names(cmd):
    return {n for g in ASSIGNED_NAME.findall(cmd or "") for n in g if n}


def expand_path(path, assigned=frozenset()):
    """`path` with $VAR, ${VAR}, ${VAR:-default} and a leading ~ expanded from
    this hook's environment, which the host gives the hook and the command
    alike; None when a variable is unset (the file cannot be known, so the
    dispatch is denied) or is one the command assigns itself (`assigned`: the
    hook would read another file than the command). A coordinator's brief in
    $TMPDIR/m.txt was denied until 2026-09-25 because $TMPDIR was read as a
    relative directory name."""
    unset, inside = [], []

    def sub(m):
        name = m.group(1) or m.group(4)
        op, rest = m.group(2), m.group(3) or ""
        if name in assigned:
            inside.append("$" + name)
            return ""
        val = os.environ.get(name)
        if m.group(1) and op is None and rest:
            unset.append(m.group(0))  # ${VAR/x/y} and friends: not expanded
            return ""
        if (op == ":-" and not val) or (op == "-" and val is None):
            return ENV_REF.sub(sub, rest)

        if val is None:
            unset.append("$" + name)
            return ""
        return val

    out = ENV_REF.sub(sub, path)
    if inside:
        FILE_NOTES.append(f"{path}: {', '.join(sorted(set(inside)))} is set by this same command, and the hook reads "
                          f"the brief file before the command runs, so it cannot know which file that is: "
                          f"name the brief file by a literal path")
        return None
    if unset:
        FILE_NOTES.append(f"{path}: {', '.join(unset)} is not set in the hook's environment, so the file cannot be read")
        return None
    return os.path.expanduser(out)


def read_file_text(path, cwd, assigned=frozenset()):
    shown = path
    path = expand_path(path, assigned)
    if path is None:
        return ""
    if not os.path.isabs(path) and cwd:
        path = os.path.join(cwd, path)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(200_000)
    except FileNotFoundError:
        FILE_NOTES.append(f"{shown}: no such file when the hook ran. A file the same command writes does not exist "
                          f"yet when the hook reads it: write the brief file in a separate step, then dispatch")
    except OSError as e:
        FILE_NOTES.append(f"{shown}: unreadable ({e.strerror})")
    return ""


def command_text(inp):
    cmd = inp.get("command") if isinstance(inp, dict) else None
    if cmd is None and isinstance(inp, dict):
        cmd = inp.get("cmd")
    if isinstance(cmd, list):
        # Codex: ["/bin/zsh", "-lc", "<script>"] -- the script is what runs.
        parts = [str(c) for c in cmd]
        if len(parts) >= 3 and parts[1] in ("-c", "-lc", "-ic"):
            return parts[2]
        return " ".join(shlex.quote(p) for p in parts)
    return cmd if isinstance(cmd, str) else None


def dispatch_texts(payload):
    """([texts], label) when the tool call dispatches work; ([], None) otherwise."""
    del FILE_NOTES[:]
    tool = str(payload.get("tool_name") or payload.get("toolName") or "")
    inp = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    if isinstance(inp, str):
        try:
            inp = json.loads(inp)
        except ValueError:
            inp = {"command": inp}
    if isinstance(inp, dict) and isinstance(inp.get("arguments"), dict):
        inp = {**inp, **inp["arguments"]}
    m = MCP_TOOL.search(tool)
    if m:
        kind = m.group(1)
        text = "\n".join(str(inp.get(k) or "") for k in MCP_FIELDS[kind])
        return [text], kind
    cmd = command_text(inp)
    if not cmd:
        return [], None
    # Only a command whose command word is bb runs a dispatch; the same words
    # inside a quoted argument (printf, echo, grep, git commit -m) are data.
    found = dispatches(cmd)
    if not found:
        return [], None
    cwd = (inp.get("workdir") or inp.get("cwd") or payload.get("cwd") or "") if isinstance(inp, dict) else ""
    texts = []
    assigned = assigned_names(cmd)
    for text, heredocs, _verb in found:
        # Each dispatch carries its own serves line: its words, its heredoc,
        # and the files it reads its brief from.
        body = "\n".join([text, *heredocs])
        for rx in (FILE_FLAG, CAT_SUB, REDIRECT_IN):
            for g in rx.findall(text):
                path = next((x for x in g if x), "")
                if path and path != "-":
                    body += "\n" + read_file_text(path, cwd, assigned)
        texts.append(body)
    return texts, "bb " + "/".join(sorted({v for _t, _h, v in found}))



def record(entry):
    try:
        os.makedirs(os.path.dirname(DECISIONS), exist_ok=True)
        with open(DECISIONS, "a", encoding="utf-8") as f:
            f.write(json.dumps({"schema_version": 1, "at": now_iso(), **entry}) + "\n")
    except OSError:
        pass


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}))
    print(reason, file=sys.stderr)
    return 2


def hook_elapsed(now=None):
    """Seconds since the hook chain started (HOOK_T0). 0 when unset or
    unreadable, never negative: a future T0 cannot buy more time."""
    try:
        t0 = float(os.environ.get("HOOK_T0", ""))
    except ValueError:
        return 0.0
    return max(0.0, (datetime.datetime.now().timestamp() if now is None else now) - t0)


def shape_serves(thread, flat):
    """Shape mode: does the (quote-stripped) payload name an OPEN purpose of
    the ledger, or quote one of its accepted revisions? An unknown or
    blocked P-id does not count; an unreadable ledger serves nothing."""
    try:
        led = read_ledger(thread)
    except Exception:
        return False
    if not led:
        return False
    opened = {p["id"] for p in led["purposes"] if p["status"] == "open"}
    for m in SERVES_P.finditer(flat):
        if {pid.upper() for pid in re.findall(r"P\d+", m.group(1), re.I)} & opened:
            return True
    if re.search(r"serves:\s*revision", flat, re.I):
        body = collapse(flat)
        return any(collapse(re.sub(r"[\\'\"]", "", r["quote"])) in body for r in led.get("accepted_revisions", []))
    return False


def hook_under_deadline(thread, stdin=None):
    """hook() with a hard deadline measured from the chain start."""
    import signal
    held = {"text": ""}

    def expire(signum, frame):
        try:
            has = bool(thread) and bool(THREAD_ID.match(thread)) and os.path.exists(ledger_path(thread))
        except Exception:
            has = False
        text = re.sub(r"[\\'\"]", "", held["text"])
        if has and COARSE_DISPATCH.search(text) and not shape_serves(thread, text):
            deny(f"[scope-gate] the gate could not finish within {HOOK_HARD_S:.0f} s of the hook chain starting "
                 f"(the host's hook timeout is {HOOK_HOST_TIMEOUT_S:.0f} s, and a timed-out hook lets the command "
                 f"run); this dispatch names no purpose, so it is denied: add `serves: P<n>` and retry")
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(2)
        os._exit(0)

    left = HOOK_HARD_S - hook_elapsed()
    if left <= 0:  # the chain spent the budget before this stage: decide by shape now
        held["text"] = (stdin or sys.stdin).read()
        expire(None, None)
    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, left)
    try:
        held["text"] = (stdin or sys.stdin).read()
        return hook(held["text"], thread)
    finally:

        signal.setitimer(signal.ITIMER_REAL, 0)


def hook(stdin_text, thread):
    if not thread or not THREAD_ID.match(thread):
        return 0
    try:
        payload = json.loads(stdin_text or "{}")
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    texts, label = dispatch_texts(payload)
    if not texts:
        return 0
    try:
        ledger = read_ledger(thread)
    except LedgerError as e:
        record({"event": "scope_denied", "thread": thread, "tool": label, "why": f"ledger unusable: {e}"})
        return deny(f"[scope-gate] {thread} has a scope ledger that cannot be used ({e}); dispatches are denied until it is fixed: {ledger_path(thread)}")
    if ledger is None:
        return 0
    allow, served, via = decide(ledger, texts)
    if allow:
        record({"event": "scope_passed", "thread": thread, "tool": label, "serves": via})
        return 0
    record({"event": "scope_denied", "thread": thread, "tool": label, "named": served})
    notes = "".join("\nBrief file " + n + "." for n in FILE_NOTES)
    return deny(deny_reason(ledger, thread, served) + notes)


# ---------------------------------------------------------------- CLI

def arg(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return default


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "hook":
        try:
            return hook_under_deadline(os.environ.get("BB_THREAD_ID", ""))
        except Exception as e:  # a crash on a dispatch from a ledger thread denies
            thread = os.environ.get("BB_THREAD_ID", "")
            try:
                has = bool(thread) and os.path.exists(ledger_path(thread))
            except LedgerError:
                has = False
            if has:
                return deny(f"[scope-gate] gate error, dispatch denied: {e}")
            return 0
    if cmd == "selftest":
        return selftest()
    if not args:
        print(f"usage: scope-gate.py {cmd} <thread> ...", file=sys.stderr)
        return 2
    thread = args[0]
    try:
        if cmd == "show":
            ledger = read_ledger(thread)
            print(json.dumps(ledger, indent=2, ensure_ascii=False) if ledger else f"no ledger for {thread}")
            return 0 if ledger else 1
        if cmd == "check":
            text = sys.stdin.read() if len(args) < 2 or args[1] == "-" else args[1]
            ledger = read_ledger(thread)
            if ledger is None:
                print(f"ALLOW  {thread} has no ledger; the gate does not apply")
                return 0
            allow, served, via = decide(ledger, [text])
            print(f"ALLOW  serves {via}" if allow else "DENY\n" + deny_reason(ledger, thread, served))
            return 0 if allow else 2
        if cmd == "init":
            src = arg(args, "--from")
            if not src:
                raise LedgerError("init needs --from <ledger.json>")
            if os.path.exists(ledger_path(thread)):
                raise LedgerError(f"{ledger_path(thread)} exists; use add/mark/revise")
            with open(src, encoding="utf-8") as f:
                ledger = json.load(f)
            ledger["thread_id"] = thread
            write_ledger(thread, ledger)
            print(f"wrote {ledger_path(thread)}")
            return 0
        ledger = read_ledger(thread)
        if ledger is None:
            raise LedgerError(f"no ledger for {thread}")
        if cmd == "add":
            text, done = arg(args, "--text"), arg(args, "--done-when", "")
            if not text:
                raise LedgerError("add needs --text (the user's words)")
            n = 1 + max(int(p["id"][1:]) for p in ledger["purposes"])
            ledger["purposes"].append({"id": f"P{n}", "text": text, "done_when": done, "status": "open", "evidence": [], "status_marked_at": now_iso(), "ask": None})
            write_ledger(thread, ledger)
            print(f"added P{n}")
            return 0
        if cmd == "mark":
            if len(args) < 3:
                raise LedgerError("mark <thread> <Pn> <open|done|blocked-on-user> [--ask Q] [--evidence E]")
            pid, status = args[1].upper(), args[2]
            if status not in STATUSES:
                raise LedgerError(f"status must be one of {', '.join(STATUSES)}")
            p = next((p for p in ledger["purposes"] if p["id"] == pid), None)
            if not p:
                raise LedgerError(f"no purpose {pid}")
            ask = arg(args, "--ask")
            if status == "blocked-on-user" and not (ask and ask.strip()):
                raise LedgerError("blocked-on-user needs --ask with the exact question for the user")
            p["status"], p["status_marked_at"] = status, now_iso()
            p["ask"] = ask if status == "blocked-on-user" else None
            ev = arg(args, "--evidence")
            if ev:
                p.setdefault("evidence", []).append({"at": now_iso(), "note": ev})
            write_ledger(thread, ledger)
            print(f"{pid} -> {status} at {p['status_marked_at']}")
            return 0
        if cmd == "revise":
            quote = arg(args, "--quote")
            if not quote or not quote.strip():
                raise LedgerError("revise needs --quote with the user's approval, verbatim")
            ledger["accepted_revisions"].append({"quote": quote, "accepted_at": now_iso(), "source": arg(args, "--source", "")})
            write_ledger(thread, ledger)
            print("revision recorded")
            return 0
        if cmd == "release":
            # The fleet archive guard restores every archive of a child whose
            # parent ledger has an unfinished purpose. A release is the
            # coordinator saying this one child is done, with the reason.
            child, ev = (args[1] if len(args) > 1 else ""), arg(args, "--evidence")
            if not THREAD_ID.match(child):
                raise LedgerError("release <coordinator> <child thr_...> --evidence E")
            if child == thread:
                raise LedgerError("a coordinator is not its own child; mark its purposes done instead")
            if not (ev and ev.strip()):
                raise LedgerError("release needs --evidence saying why the child is done")
            rel = [r for r in ledger.get("released_children", []) if r["thread_id"] != child]
            rel.append({"thread_id": child, "evidence": ev, "released_at": now_iso()})
            ledger["released_children"] = rel
            write_ledger(thread, ledger)
            print(f"released {child} from {thread}'s archive hold")
            return 0

    except (LedgerError, OSError, ValueError) as e:
        print(f"scope-gate: {e}", file=sys.stderr)
        return 1
    print(f"unknown command {cmd}", file=sys.stderr)
    return 2


# ---------------------------------------------------------------- selftest

# bb verbs whose help shows text but that dispatch no work, with the reason.
VERB_EXEMPT = {
    "fleet validate": "a claim sent to the reviewer, not work for a thread",
    "fleet review": "a claim sent to the reviewer, not work for a thread",
    "fleet hermes": "a claim sent to the reviewer, not work for a thread",
}


def shutil_which(name):
    import shutil
    return shutil.which(name)


def gated_verbs():
    from shell_dispatch import THREAD_VERBS, QUEUE_VERBS, FLEET_VERBS
    return ({f"thread {v}" for v in THREAD_VERBS} | {f"thread queue {v}" for v in QUEUE_VERBS}
            | {f"fleet {v}" for v in FLEET_VERBS})


def bb_text_verbs(bb="bb"):
    """Every verb of `bb thread`, `bb thread queue` and `bb fleet` whose help
    says it carries a prompt, a message, a charter, a title, a question or a
    claim. The per-verb help calls run concurrently (about 1 s each)."""
    import subprocess

    def helptext(*args):
        try:
            return subprocess.run([bb, *args, "--help"], capture_output=True, text=True, timeout=60).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
    listed = re.compile(r"^  ([a-z][a-z-]*)(?:\|[a-z-]+)?\s", re.M)
    jobs = {f"thread {v}": ["thread", v] for v in listed.findall(helptext("thread")) if v not in ("help", "queue")}
    jobs.update({f"thread queue {v}": ["thread", "queue", v] for v in listed.findall(helptext("thread", "queue")) if v != "help"})
    procs = {k: subprocess.Popen([bb, *a, "--help"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
             for k, a in jobs.items()}
    text = re.compile(r"--prompt\b|--message\b|--prompt-file|--message-file|\[message\]|<message>|--charter")
    carries = set()
    for k, p in procs.items():
        out, _ = p.communicate(timeout=120)
        if text.search(out or ""):
            carries.add(k)
    for m in re.finditer(r"^\s+bb fleet (\S+)(.*)$", helptext("fleet"), re.M):
        if re.search(r'--charter|--prompt|--message|"<(title|question|claim)>"', m.group(2)):
            carries.add(f"fleet {m.group(1)}")
    return carries


def selftest():

    global LEDGER_DIR, DECISIONS
    here = os.path.dirname(os.path.abspath(__file__))
    fixture = os.path.join(here, "..", "tests", "fixtures", "scope-ledger.json")
    with open(fixture, encoding="utf-8") as f:
        base = json.load(f)
    tmp = tempfile.mkdtemp(prefix="scope-gate-selftest-")
    LEDGER_DIR, DECISIONS = tmp, os.path.join(tmp, "decisions.jsonl")
    thread = base["thread_id"]
    write_ledger(thread, base)
    brief = os.path.join(tmp, "brief.md")
    with open(brief, "w") as f:
        f.write("[child of @thread:thr_coordfixture]\nserves: P1\nDo the thing.\n")
    nobrief = os.path.join(tmp, "nobrief.md")
    with open(nobrief, "w") as f:
        f.write("Do the thing.\n")

    def claude_bash(cmd):
        return {"tool_name": "Bash", "tool_input": {"command": cmd}}

    def codex_shell(cmd):
        return {"tool_name": "shell", "tool_input": {"command": ["/bin/zsh", "-lc", cmd], "workdir": tmp}}

    rev = base["accepted_revisions"][0]["quote"]
    cases = [
        # (label, payload, thread, expected rc)
        ("claude: bb thread spawn without serves", claude_bash('bb thread spawn --parent-self --prompt "fix the dashboard"'), thread, 2),
        ("claude: bb thread spawn serving open P1", claude_bash('bb thread spawn --parent-self --prompt "serves: P1\nfix it"'), thread, 0),
        ("claude: serving blocked-on-user P2 is denied", claude_bash('bb thread spawn --prompt "serves: P2 go"'), thread, 2),
        ("claude: serving unknown P9 is denied", claude_bash('bb thread tell thr_abc "serves: P9 go"'), thread, 2),
        ("claude: tell without serves", claude_bash('bb thread tell thr_abc "please also refactor the sparkline"'), thread, 2),
        ("claude: \"$BB_CLI\" thread message without serves", claude_bash('"$BB_CLI" thread message thr_abc "hi"'), thread, 2),
        ("claude: /abs/path/bb thread create without serves", claude_bash("/usr/local/bin/bb thread create --prompt x"), thread, 2),
        ("claude: heredoc brief with serves", claude_bash("bb thread spawn --prompt-file - <<'EOF'\nserves: P1\nwork\nEOF"), thread, 0),
        ("claude: --prompt-file brief with serves", claude_bash(f"bb thread spawn --parent-self --prompt-file {brief}"), thread, 0),
        ("claude: --prompt-file brief without serves", claude_bash(f"bb thread spawn --parent-self --prompt-file {nobrief}"), thread, 2),
        ("claude: $(cat brief) with serves", claude_bash(f'bb thread spawn --prompt "$(cat {brief})"'), thread, 0),
        ("claude: tell < file with serves", claude_bash(f"bb thread tell thr_abc < {brief}"), thread, 0),
        ("claude: accepted revision quoted exactly", claude_bash(f"bb thread tell thr_abc 'serves: revision \"{rev}\" go'"), thread, 0),
        ("claude: revision that is only a substring", claude_bash("bb thread tell thr_abc 'serves: revision \"same class of harness defect\" go'"), thread, 2),
        ("claude: not a dispatch (bb thread list)", claude_bash("bb thread list --parent-thread thr_x"), thread, 0),
        ("claude: not a dispatch (git status)", claude_bash("git status"), thread, 0),
        ("claude mcp: fleet_member_spawn without serves", {"tool_name": "mcp__bb-bridge__fleet_member_spawn", "tool_input": {"name": "x", "prompt": "do x"}}, thread, 2),
        ("claude mcp: fleet_member_spawn serving P1", {"tool_name": "mcp__bb-bridge__fleet_member_spawn", "tool_input": {"name": "x", "prompt": "serves: P1\ndo x"}}, thread, 0),
        ("claude mcp: fleet_member_tell without serves", {"tool_name": "mcp__bb-bridge__fleet_member_tell", "tool_input": {"member": "x", "message": "also do y"}}, thread, 2),
        ("claude mcp: fleet_delegate serving P1", {"tool_name": "mcp__bb-bridge__fleet_delegate", "tool_input": {"task": "serves: p1 -- do z"}}, thread, 0),
        ("codex: shell argv spawn without serves", codex_shell("cd /tmp && bb thread spawn --prompt 'x'"), thread, 2),
        ("codex: shell argv spawn with brief file (relative to workdir)", codex_shell("bb thread spawn --prompt-file brief.md"), thread, 0),
        ("codex: bare fleet_member_tell without serves", {"tool_name": "fleet_member_tell", "tool_input": {"member": "x", "message": "go"}}, thread, 2),
        ("codex: bare fleet_member_spawn serving P1", {"tool_name": "fleet_member_spawn", "tool_input": {"prompt": "serves: P1"}}, thread, 0),
        ("no ledger: spawn without serves is allowed", claude_bash("bb thread spawn --prompt x"), "thr_noledger", 0),
        ("no thread id: allowed", claude_bash("bb thread spawn --prompt x"), "", 0),
        # 2026-09-25: a brief in $TMPDIR was denied, the variable read as a directory name.
        ("claude: --message-file $TMPDIR/brief with serves", claude_bash("bb thread tell thr_x --message-file $TMPDIR/brief.md"), thread, 0),
        ("claude: --message-file \"${TMPDIR}/nobrief\" without serves", claude_bash('bb thread tell thr_x --message-file "${TMPDIR}/nobrief.md"'), thread, 2),
        ("claude: --prompt-file ${UNSET:-$TMPDIR}/brief takes the default", claude_bash("bb thread spawn --prompt-file ${SCOPE_GATE_UNSET_VAR:-$TMPDIR}/brief.md"), thread, 0),
        ("claude: --prompt-file ${UNSET:-/nonexistent}/brief takes the default and is denied", claude_bash("bb thread spawn --prompt-file ${SCOPE_GATE_UNSET_VAR:-/nonexistent}/brief.md"), thread, 2),
        ("claude: --message-file $UNSET/brief is denied", claude_bash("bb thread tell thr_x --message-file $SCOPE_GATE_UNSET_VAR/brief.md"), thread, 2),
        ("claude: an unset variable before a real path is denied", claude_bash("bb thread tell thr_x --message-file $SCOPE_GATE_UNSET_VAR$TMPDIR/brief.md"), thread, 2),

        ("claude: $(cat $TMPDIR/brief) with serves", claude_bash('bb thread tell thr_x "$(cat $TMPDIR/brief.md)"'), thread, 0),
        ("claude: tell < $TMPDIR/brief with serves", claude_bash("bb thread tell thr_x < $TMPDIR/brief.md"), thread, 0),
        # 2026-09-25 23:15Z: a variable the command sets itself. The hook would
        # read $TMPDIR/brief.md from its own environment, not /nonexistent.
        ("claude: TMPDIR reassigned in the command, then --message-file $TMPDIR/brief", claude_bash("TMPDIR=/nonexistent; bb thread tell thr_x --message-file $TMPDIR/brief.md"), thread, 2),
        ("claude: D=... && --message-file $D/brief", claude_bash("D=$TMPDIR && bb thread tell thr_x --message-file $D/brief.md"), thread, 2),
        ("claude: export D=...; --prompt-file ${D}/brief", claude_bash("export D=/x; bb thread spawn --prompt-file ${D}/brief.md"), thread, 2),
        ("claude: for TMPDIR in ...; $(cat $TMPDIR/brief)", claude_bash('for TMPDIR in /nonexistent; do bb thread tell thr_x "$(cat $TMPDIR/brief.md)"; done'), thread, 2),
        ("claude: read TMPDIR; tell < $TMPDIR/brief", claude_bash("read -r TMPDIR < /dev/null; bb thread tell thr_x < $TMPDIR/brief.md"), thread, 2),
        ("claude: an assignment of another name leaves $TMPDIR/brief readable", claude_bash("X=1; bb thread tell thr_x --message-file $TMPDIR/brief.md"), thread, 0),
        ("claude: --message-file ~/brief with serves (HOME)", claude_bash("bb thread tell thr_x --message-file ~/brief.md"), thread, 0),
    ]
    saved_env = {k: os.environ.get(k) for k in ("TMPDIR", "HOME", "SCOPE_GATE_UNSET_VAR")}
    os.environ["TMPDIR"], os.environ["HOME"] = tmp, tmp
    os.environ.pop("SCOPE_GATE_UNSET_VAR", None)

    # Tokenizer cases, shared with the fail-before replay against an older gate.
    with open(os.path.join(here, "..", "tests", "fixtures", "dispatch-cases.json"), encoding="utf-8") as f:
        shared = json.load(f)["cases"]
    for c in shared:
        cmd = c["command"].replace("{brief}", brief).replace("{nobrief}", nobrief).replace("{tmp}", tmp)
        cases.append((f"claude: {c['label']}", {**claude_bash(cmd), "cwd": tmp}, thread, c["want"]))
        cases.append((f"codex: {c['label']}", codex_shell(cmd), thread, c["want"]))
    failed = 0
    for label, payload, t, want in cases:
        out = sys.stdout
        sys.stdout = open(os.devnull, "w")
        err = sys.stderr
        sys.stderr = open(os.devnull, "w")
        try:
            got = hook(json.dumps(payload), t)
        finally:
            sys.stdout.close()
            sys.stdout, sys.stderr = out, err
        mark = "ok  " if got == want else "FAIL"
        if got != want:
            failed += 1
        print(f"{mark} {label}: rc={got} want={want}")
    import io
    for label, cmd, needle in [
        ("a missing brief file says to write it in a separate step",
         "printf 'serves: P1' > $TMPDIR/late.md && bb thread tell thr_x --message-file $TMPDIR/late.md", "separate step"),
        ("an unset variable is named", "bb thread tell thr_x --message-file $SCOPE_GATE_UNSET_VAR/b.md", "$SCOPE_GATE_UNSET_VAR is not set"),
        ("a variable the command sets asks for a literal path",
         "D=$TMPDIR; bb thread tell thr_x --message-file $D/brief.md", "$D is set by this same command"),

    ]:
        out, err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = io.StringIO(), open(os.devnull, "w")
        try:
            got = hook(json.dumps(claude_bash(cmd)), thread)
            said = sys.stdout.getvalue()
        finally:
            sys.stderr.close()
            sys.stdout, sys.stderr = out, err
        ok = got == 2 and needle in said
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} deny message: {label}: rc={got}")
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    # A broken ledger denies dispatches (fail closed) but not other tools.

    with open(ledger_path("thr_broken"), "w") as f:
        f.write("{ not json")
    for label, payload, want in [
        ("broken ledger: spawn denied", claude_bash("bb thread spawn --prompt 'serves: P1'"), 2),
        ("broken ledger: git status allowed", claude_bash("git status"), 0),
    ]:
        out, err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = open(os.devnull, "w"), open(os.devnull, "w")
        try:
            got = hook(json.dumps(payload), "thr_broken")
        finally:
            sys.stdout.close()
            sys.stdout, sys.stderr = out, err
        failed += got != want
        print(f"{'ok  ' if got == want else 'FAIL'} {label}: rc={got} want={want}")
    # mark: blocked-on-user needs an ask and records when.
    rc = main(["mark", thread, "P1", "blocked-on-user"])
    failed += rc != 1
    print(f"{'ok  ' if rc == 1 else 'FAIL'} mark blocked-on-user without --ask is refused: rc={rc}")
    rc = main(["mark", thread, "P1", "blocked-on-user", "--ask", "Which host?"])
    led = read_ledger(thread)
    good = rc == 0 and led["purposes"][0]["status"] == "blocked-on-user" and led["purposes"][0]["ask"] == "Which host?" and led["purposes"][0]["status_marked_at"]
    failed += not good
    print(f"{'ok  ' if good else 'FAIL'} mark blocked-on-user records the ask and when")
    out, err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = open(os.devnull, "w"), open(os.devnull, "w")
    try:
        got = hook(json.dumps(claude_bash("bb thread spawn --prompt 'serves: P1'")), thread)
    finally:
        sys.stdout.close()
        sys.stdout, sys.stderr = out, err
    failed += got != 2
    print(f"{'ok  ' if got == 2 else 'FAIL'} once P1 is blocked-on-user, serving it is denied: rc={got}")
    # release: a finished child, with the reason; fleet's archive hold skips it.
    quiet = sys.stderr
    sys.stderr = open(os.devnull, "w")
    try:
        refused = [main(["release", thread, "thr_child1"]),
                   main(["release", thread, "thr_child1", "--evidence", "  "]),
                   main(["release", thread, thread, "--evidence", "done"]),
                   main(["release", thread, "not-a-thread", "--evidence", "done"])]
    finally:
        sys.stderr.close()
        sys.stderr = quiet
    failed += refused != [1, 1, 1, 1]
    print(f"{'ok  ' if refused == [1, 1, 1, 1] else 'FAIL'} release refuses no evidence, blank evidence, itself, a non-thread: {refused}")
    rc1 = main(["release", thread, "thr_child1", "--evidence", "PR #22 merged"])
    rc2 = main(["release", thread, "thr_child1", "--evidence", "PR #22 merged at d0ce389"])
    rel = read_ledger(thread).get("released_children", [])
    good = rc1 == rc2 == 0 and len(rel) == 1 and rel[0]["thread_id"] == "thr_child1" \
        and rel[0]["evidence"] == "PR #22 merged at d0ce389" and rel[0]["released_at"]
    failed += not good
    print(f"{'ok  ' if good else 'FAIL'} release records the child, the evidence and when; a second release replaces it")
    led = read_ledger(thread)
    led["released_children"].append({"thread_id": "thr_child2"})
    with open(ledger_path(thread), "w") as f:
        json.dump(led, f)
    try:
        read_ledger(thread)
        bad_ok = False
    except LedgerError:
        bad_ok = True
    failed += not bad_ok
    print(f"{'ok  ' if bad_ok else 'FAIL'} a release without evidence makes the ledger invalid (fleet holds, the gate denies)")
    led["released_children"].pop()
    with open(ledger_path(thread), "w") as f:
        json.dump(led, f)

    # Hard deadline on the chain clock (HOOK_T0): with the budget already
    # spent, an undeclared dispatch is denied by shape at once, a serving one
    # and a non-dispatch are allowed; a future T0 buys nothing extra and the
    # normal decision runs.
    import subprocess
    import time
    main(["mark", thread, "P1", "open"])
    spent = "%.3f" % (time.time() - HOOK_HARD_S - 1)
    future = "%.3f" % (time.time() + 3600)
    for label, cmd, t0, want, text in [
        ("deadline: undeclared tell denied by shape", "bb thread tell thr_x hi", spent, 2, "could not finish"),
        ("deadline: a quote-split dispatch word is still one", 'bb thr"ea"d tell thr_x hi', spent, 2, "could not finish"),

        ("deadline: tell with serves allowed", "bb thread tell thr_x 'serves: P1 hi'", spent, 0, ""),
        ("deadline: a blocked purpose does not serve", "bb thread tell thr_x 'serves: P2 hi'", spent, 2, "could not finish"),
        ("deadline: an unknown purpose does not serve", "bb thread tell thr_x 'serves: P9 hi'", spent, 2, "could not finish"),
        ("deadline: an open id in a list serves", "bb thread tell thr_x 'serves: P9, P1 hi'", spent, 0, ""),
        ("deadline: fork is a dispatch", "bb thread fork thr_x --prompt hi", spent, 2, "could not finish"),
        ("deadline: non-dispatch allowed", "ls -la", spent, 0, ""),
        ("future HOOK_T0: normal decision", "bb thread tell thr_x hi", future, 2, "must say which"),
    ]:
        env = dict(os.environ, HOME=tmp, SCOPE_LEDGER_DIR=tmp, BB_THREAD_ID=thread, HOOK_T0=t0)
        start = time.monotonic()
        p = subprocess.run([sys.executable, os.path.abspath(__file__), "hook"], env=env, text=True, capture_output=True,
                           input=json.dumps(claude_bash(cmd)))
        took = time.monotonic() - start
        good = p.returncode == want and text in p.stderr and took < 2.0
        failed += not good
        print(f"{'ok  ' if good else 'FAIL'} {label}: rc={p.returncode} want={want} in {took:.2f} s")
    # Every bb verb whose help says it hands a thread text to act on is gated
    # (review r1 D3): a new prompt-carrying verb fails here until it is added
    # to shell_dispatch or to VERB_EXEMPT with the reason.
    if shutil_which("bb"):
        carries = bb_text_verbs()
        missing = sorted(carries - gated_verbs() - set(VERB_EXEMPT))
        failed += bool(missing) or not carries
        print(f"{'ok  ' if carries and not missing else 'FAIL'} every prompt-carrying bb verb is gated "
              f"({len(carries)} found in bb's help){': missing ' + ', '.join(missing) if missing else ''}")
    else:
        print("skip bb verb coverage: no bb on PATH")
    with open(DECISIONS) as f:
        n = sum(1 for _ in f)

    failed += n == 0
    print(f"{'ok  ' if n else 'FAIL'} decisions are recorded ({n} lines)")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print("scope-gate selftest: " + ("all pass" if not failed else f"{failed} FAIL"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
