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
                             "accepted_at": "<iso>", "source": "..."}]}

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

LEDGER_DIR = os.environ.get("SCOPE_LEDGER_DIR") or os.path.expanduser("~/.local/state/agent-quality/scope")
DECISIONS = os.path.expanduser("~/.local/state/agent-quality/scope-decisions.jsonl")
THREAD_ID = re.compile(r"^thr_[a-z0-9]+$")
STATUSES = ("open", "done", "blocked-on-user")

# `bb thread spawn|create|tell|message`, with bb as a bare word, a path ending
# in /bb, or "$BB_CLI" / ${BB_CLI}.
BB_DISPATCH = re.compile(
    r"""(?:^|[\s;&|(`{])(?:"?\$\{?BB_CLI\}?"?|(?:[\w./~-]*/)?bb)\s+(?:--?[\w-]+(?:[= ]\S+)?\s+)*thread\s+(spawn|create|tell|message)\b"""
)
FILE_FLAG = re.compile(r"""--(?:prompt|message)-file(?:=|\s+)(?:"([^"]+)"|'([^']+)'|(\S+))""")
CAT_SUB = re.compile(r"""\$\(\s*cat\s+(?:"([^"]+)"|'([^']+)'|([^\s)]+))\s*\)""")
REDIRECT_IN = re.compile(r"""(?<![<0-9])<\s*(?:"([^"]+)"|'([^']+)'|([^\s<;&|)]+))""")
MCP_TOOL = re.compile(r"(?:^|[^a-z])(fleet_member_spawn|fleet_member_tell|fleet_delegate)$")
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

def read_file_text(path, cwd):
    path = os.path.expanduser(path)
    if not os.path.isabs(path) and cwd:
        path = os.path.join(cwd, path)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(200_000)
    except OSError:
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
    found = BB_DISPATCH.findall(cmd)
    if not found:
        return [], None
    cwd = (inp.get("workdir") or inp.get("cwd") or payload.get("cwd") or "") if isinstance(inp, dict) else ""
    text = cmd
    for rx in (FILE_FLAG, CAT_SUB, REDIRECT_IN):
        for g in rx.findall(cmd):
            path = next((x for x in g if x), "")
            if path and path != "-":
                text += "\n" + read_file_text(path, cwd)
    return [text], "bb thread " + "/".join(sorted(set(found)))


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
    return deny(deny_reason(ledger, thread, served))


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
            return hook(sys.stdin.read(), os.environ.get("BB_THREAD_ID", ""))
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
    except (LedgerError, OSError, ValueError) as e:
        print(f"scope-gate: {e}", file=sys.stderr)
        return 1
    print(f"unknown command {cmd}", file=sys.stderr)
    return 2


# ---------------------------------------------------------------- selftest

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
    ]
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
