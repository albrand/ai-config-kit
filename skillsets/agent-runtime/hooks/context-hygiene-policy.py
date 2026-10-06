#!/usr/bin/env python3
"""Shared context-hygiene policy for every agent harness on this machine.

One source of truth. Claude Code and Codex call this directly; the opencode
plugin mirrors the same two rules.

Rules (both measured as dominant in real transcripts):
  1. Bash/shell heredoc >10 lines AND >1000 bytes
     -> 40.5% of all tool_use_input. Write to /tmp once, invoke by path.
  2. Read of a file >15KB with no offset/limit
     -> 41 such calls were 86% of all Read bytes. Locate first, then read a slice.

Contract: print a JSON verdict {"block": bool, "reason": str} on stdout.
FAILS OPEN. Any parse failure, unknown schema or unexpected error returns
block=false. A blocking hook that misfires must never wedge an agent.

Disable entirely with CONTEXT_HYGIENE=off.
"""
import sys, json, os, re

HEREDOC_LINES, HEREDOC_BYTES = 10, 1000
READ_BYTES = 15000

# Two shapes the heredoc rule must not block, because for them its own remedy
# is either impossible or is the thing being done.
#
#  1. A heredoc that IS the write to /tmp the message asks for. Telling an agent
#     "write a parameterized script to /tmp once and re-invoke it by path" and
#     then blocking `cat > /tmp/x.py <<'EOF'` is a loop with no compliant exit,
#     and an instruction with no compliant exit teaches agents to distrust the
#     hook rather than to follow it.
#  2. A heredoc carrying a one-shot MESSAGE to a command that reads it from
#     stdin -- a commit message, a PR body, a tag annotation. There is no reuse
#     to gain: the text is written once, consumed once, and never invoked again,
#     so staging it through a file is pure overhead. Blocked a real
#     `git commit -F-` on 2026-09-20 and cost a round trip to work around.
#
# Both are matched against the command only -- the text before the first `<<`
# -- so a mention inside the heredoc body cannot buy an exemption. The script
# write must additionally be the whole of the command that owns the heredoc.
#
# Each list is empty-able on its own: context-hygiene-check.py --falsify deletes
# them to prove every exempted case was exempted, not merely under a floor.
HEREDOC_EXEMPT = [
    # 1. `cat > path` / `tee path`, and nothing else, as the command the heredoc
    # feeds. Anchored at both ends, so `... | cat > file` is not exempt.
    re.compile(r"^\s*(?:cat|tee)\s+(?:-a\s+)?>{0,2}\s*\S+\s*$"),
]
MESSAGE_ON_STDIN = [
    # 2. git commit -F - / --file=- / tag -F -, gh ... --body-file -
    re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:commit|tag|notes)\b[^\n]*"
               r"(?:-F\s*-|--file[= ]-)"),
    re.compile(r"\bgh\s+\w+\s+\w+[^\n]*--body-file[= ]-"),
]

# The read rule says "locate the lines you want, then read that slice". That
# advice only means anything for text. A PNG has no lines: offset/limit are
# meaningless, grep cannot locate anything inside it, and the agent is left
# with no compliant way to open the file at all. On 2026-09-20 an 18 KB
# screenshot the user attached to a thread was unreadable for three turns for
# exactly this reason. Never block a format that cannot be sliced.
UNSLICEABLE_EXT = {
    # raster and vector images the harness renders visually
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico", ".avif", ".heic",
    # paged and cell-addressed documents: read by page/sheet, not byte offset
    ".pdf", ".ipynb", ".xlsx", ".xls", ".docx", ".pptx",
    # audio and video
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".mov", ".webm", ".avi", ".mkv",
}

def verdict(block, reason=""):
    print(json.dumps({"block": bool(block), "reason": reason}))
    sys.exit(0)

# Quitting, killing or replacing the running bb desktop app kills every agent
# thread on the machine. On 2026-09-21 a Codex thread hand-installed its own
# build three times (osascript quit, mv /Applications/bb.app, ditto, then
# `kill -TERM` when the quit hung), bypassing fork-swap.sh and its
# agents-survive gate, and took down the operator's running work. The only
# sanctioned path is ~/projects/bb-fork-tools/fork-swap.sh (or fork-rollback.sh),
# whose own internal commands this hook never sees. Matched against the RAW
# payload, not a parsed command: Codex's `exec` tool sends a JS string, which
# the parsed path below discards. Not switched off by CONTEXT_HYGIENE=off.
# `kill <pid>` is resolved at hook time: each pid is looked up with ps and
# blocked if it is a bb.app process (the incident's final step was
# `kill -TERM 78123`, the desktop main process).
BB_LIFECYCLE = [
    re.compile(r'tell\s+application\s+(?:id\s+)?[\\"]*(?:dev\.bb\.desktop|bb)[\\"]*\s+to\s+quit', re.I),
    re.compile(r'\b(?:mv|rm|ditto|rsync)\b[^\n;&|]*?/Applications/bb\.app(?![\w./-]*/Contents/)'),
    re.compile(r'\bkillall\s+(?:-\S+\s+)*[\\"]*bb[\\"]*(?:\s|$|[\\";])'),
    re.compile(r'\bpkill\b[^\n;&|]*(?:bb\.app|dev\.bb\.desktop)'),
]
NON_SHELL_TOOLS = {"write", "edit", "multiedit", "notebookedit", "read", "view", "readfile", "grep", "glob"}

KILL_PIDS = re.compile(r'\bkill\s+((?:-\S+\s+)*)((?:\d+\s*)+)')

def kills_bb_pid(text):
    import subprocess
    for m in KILL_PIDS.finditer(text):
        if re.search(r'-(?:0|s\s*0)\b', m.group(1) or ""):
            continue  # kill -0 only probes existence
        for pid in m.group(2).split():
            try:
                cmd = subprocess.run(["ps", "-o", "command=", "-p", pid], capture_output=True,
                                     text=True, timeout=2).stdout
            except Exception:
                continue
            if "/Applications/bb.app/" in cmd or "bb.app/Contents/MacOS/bb" in cmd:
                # provider bridge workers are the agents themselves; the app,
                # its server, host daemon and helpers are what hosts them all
                return True
    return False

def bb_lifecycle_guard(raw):
    try:
        p = json.loads(raw)
        tool = str(p.get("tool_name") or p.get("toolName") or p.get("tool")
                   or (p.get("tool_use") or {}).get("name") or "")
    except Exception:
        tool = ""
    if tool.lower() in NON_SHELL_TOOLS:
        return
    # Decoded string values, not the raw JSON: in raw form every newline is a
    # literal `\n`, so `\bkillall` after a line break never matched.
    def strings(v):
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            for x in v.values():
                yield from strings(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                yield from strings(x)
    try:
        text = "\n".join(strings(p))
    except Exception:
        text = raw
    # Codex `exec` wraps the shell in a JS string literal, so its newlines and
    # quotes arrive escaped once more. Unescape twice to reach the shell text.
    for _ in range(2):
        text = text.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
    try:
        cmd = (p.get("tool_input") or {}).get("command")
        if isinstance(cmd, list):
            cmd = " ".join(c for c in cmd if isinstance(c, str))
        # A heredoc that only writes a file (cat > /tmp/x <<'EOF') executes
        # nothing; scan just the command before it, as the heredoc rule does.
        if isinstance(cmd, str) and "<<" in cmd:
            head = cmd.split("<<", 1)[0]
            if any(rx.search(re.split(r"&&|\|\||;", head)[-1]) for rx in HEREDOC_EXEMPT):
                text = head
    except Exception:
        pass
    if any(rx.search(text) for rx in BB_LIFECYCLE) or kills_bb_pid(text):
        verdict(True,
            "[bb-lifecycle] Quitting, killing or replacing /Applications/bb.app kills every "
            "running agent thread on this machine. Use ~/projects/bb-fork-tools/fork-swap.sh "
            "(it gates on agent survival) or leave the build staged for fork-autoinstall. "
            "If the operator explicitly asked for a restart in this conversation, tell them "
            "to run fork-swap.sh themselves.")

def main():
    raw = sys.stdin.read()
    bb_lifecycle_guard(raw)
    if os.environ.get("CONTEXT_HYGIENE", "").lower() in ("off", "0", "false"):
        verdict(False)
    try:
        p = json.loads(raw)
    except Exception:
        verdict(False)
    if not isinstance(p, dict):
        verdict(False)

    # Tolerate several harness schemas; unknown shape -> allow.
    tool = (p.get("tool_name") or p.get("toolName") or p.get("tool")
            or (p.get("tool_use") or {}).get("name") or "")
    inp = (p.get("tool_input") or p.get("toolInput") or p.get("input")
           or p.get("arguments") or (p.get("tool_use") or {}).get("input") or {})
    if not isinstance(inp, dict):
        verdict(False)
    tool = str(tool)

    cmd = inp.get("command") or inp.get("cmd") or ""
    # Codex passes argv, not a command line: ['/bin/zsh', '-lc', '<script>'].
    # Discarding a non-string here silently disarmed the whole rule for Codex
    # -- the hook was registered, ran, exited 0 and enforced nothing. Verified
    # 2026-09-20 against a real rollout: 95 of 96 shell calls sent a list.
    if isinstance(cmd, (list, tuple)):
        cmd = " ".join(p for p in cmd if isinstance(p, str))
    if not isinstance(cmd, str): cmd = ""
    looks_shell = tool.lower() in ("bash", "shell", "run", "execute", "terminal") or bool(cmd)
    if looks_shell and cmd:
        # Matched against the COMMAND, not the payload: the text before the
        # first `<<`. A first version searched the whole string, so a heredoc
        # whose body merely mentioned `git commit -F -` -- in a comment -- let
        # an ordinary inline script through. The check caught it.
        head = cmd.split("<<", 1)[0]
        # The heredoc belongs to the LAST command before `<<`, so that is the
        # one the file-write shape is tested against. Anchoring on the whole
        # head blocked `cd /repo && cat > /tmp/x <<'EOF'` -- the remedy again.
        last = re.split(r"&&|\|\||;", head)[-1]
        exempt = (any(rx.search(last) for rx in HEREDOC_EXEMPT)
                  or any(rx.search(head) for rx in MESSAGE_ON_STDIN))
        if (not exempt and "<<" in cmd and cmd.count("\n") > HEREDOC_LINES
                and len(cmd) > HEREDOC_BYTES):
            verdict(True,
                "[context-hygiene] Not a safety rule: a format request, so the context "
                "stays small. This inline heredoc (%d lines, %.1f KB) did not run. Do the "
                "same work this way and carry on with the task: re-run or extend a script "
                "you already wrote, or write the script once to /tmp (`cat > /tmp/<name> "
                "<<'EOF'` and the Write tool are both fine) and run it by path with "
                "arguments."
                % (cmd.count("\n"), len(cmd) / 1024.0))

    fp = inp.get("file_path") or inp.get("filePath") or inp.get("path") or ""
    if tool.lower() in ("read", "view", "readfile") and isinstance(fp, str) and fp:
        sliceable = os.path.splitext(fp)[1].lower() not in UNSLICEABLE_EXT
        if sliceable and not inp.get("limit") and not inp.get("offset"):
            try: sz = os.path.getsize(fp)
            except Exception: sz = 0        # unknown size -> allow
            if sz > READ_BYTES:
                verdict(True,
                    "[context-hygiene] Not a safety rule: a format request. The unbounded "
                    "read of %s (%.0f KB, ~%d tokens) did not run. Find the lines you need "
                    "with grep or rg, read that slice with offset and limit, and carry on."
                    % (os.path.basename(fp), sz / 1024.0, sz / 4))
    verdict(False)

try:
    main()
except Exception:
    verdict(False)   # fail open, always
