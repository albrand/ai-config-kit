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
    re.compile(r'(?:^|[;&|(`\n])\s*(?:(?:sudo|env|command|exec|nohup)\s+(?:-\S+\s+|\w+=\S*\s+)*)*(?:\w+=\S*\s+)*(?:\S*/)?pkill(?=\s|$|[;&|)`])'),
]
PGREP_FULL_FLAG = re.compile(
    r'(?:^|\s)(?:-f(?:\s|$|=)|-[^\s=]*f[^\s=]*(?:\s|$|=)|--full(?:\s|$|=))')
PGREP_F_DENY = (
    "[no-pgrep-f] Hard prohibition: never use pgrep -f or pgrep --full. "
    "Use pgrep -x NAME or ps -o pid,command -p PID instead."
)
PGREP_WORD = re.compile(r'\bpgrep\b')
PGREP_VAR_INVOKE = re.compile(r'["\']?\$\{(\w+)\}|["\']?\$(\w+)\b')
# fork-stage.sh repairs the bb Electron runtime only from this cache. A session
# freeing disk on 2026-10-28 ran `rm -rf ~/Library/Caches/electron/*` and the
# next install (i31) refused; 2026-10-20 had the same cause. Deleting the whole
# Caches directory deletes it too.
ELECTRON_CACHE = [
    re.compile(r'\b(?:rm|mv|trash|rmdir)\b[^\n;&|]*?Library/Caches(?:/(?:electron(?:-builder)?(?![\w.-])|\*)|/?["\']?(?=\s|$|[;&|"\']))'),
    # find that deletes, started at the cache or at Caches itself
    re.compile(r'\bfind\s+["\']?\S*Library/Caches(?:/(?:electron(?:-builder)?(?![\w.-])|\*)\S*)?/?["\']?(?=\s|$)[^\n;&|]*?(?:-delete\b|-exec(?:dir)?\s+(?:\S*/)?(?:rm|mv|trash)\b)'),
    # cd into the cache, then any relative delete in the same command
    re.compile(r'\b(?:cd|pushd)\s+["\']?\S*Library/Caches/electron(?:-builder)?/?["\']?(?=\s|$|[;&|])[^\n]*?(?:\b(?:rm|mv|trash|rmdir)\s|\bfind\b[^\n;&|]*?(?:-delete\b|-exec(?:dir)?\s+(?:\S*/)?(?:rm|mv|trash)\b))'),
    # cd into Caches, then a delete naming the cache or every entry
    re.compile(r'\b(?:cd|pushd)\s+["\']?\S*Library/Caches/?["\']?(?=\s|$|[;&|])[^\n]*?(?:\b(?:rm|mv|trash|rmdir)\b[^\n;&|]*?(?:(?<![\w.-])electron(?:-builder)?(?![\w.-])|(?<![\w.-])(?:\./)?\*)|\bfind\s+(?:\.|(?:\./)?electron(?:-builder)?)/?(?=\s)[^\n;&|]*?(?:-delete\b|-exec(?:dir)?\s+(?:\S*/)?(?:rm|mv|trash)\b))'),
]
NON_SHELL_TOOLS = {"write", "edit", "multiedit", "notebookedit", "read", "view", "readfile", "grep", "glob"}

KILL_PIDS = re.compile(r'\bkill\s+((?:-\S+\s+)*)((?:\d+\s*)+)')

def pgrep_obfuscation_fold(text):
    text = re.sub(r"\\\n\s*", "", text)
    text = re.sub(r"(?<=[a-zA-Z0-9_])['\"]{2}(?=[a-zA-Z0-9_])", "", text)
    text = re.sub(r'(?<=[a-zA-Z0-9_])"([a-zA-Z0-9_])"(?=[a-zA-Z0-9_])', r"\1", text)
    text = re.sub(r"(?<=[a-zA-Z0-9_])'([a-zA-Z0-9_])'(?=[a-zA-Z0-9_])", r"\1", text)
    text = re.sub(r"\bp(?:\\?g)(?:\\?r)(?:\\?e)(?:\\?p)\b", "pgrep", text, flags=re.I)
    return text




def _pgrep_skip_space(text, i):
    n = len(text)
    while i < n and text[i].isspace():
        i += 1
    return i


def _pgrep_single_quote_spans(text):
    """One pass: single-quoted regions (shell: no escapes inside '...')."""
    spans = []
    i, n = 0, len(text)
    dq = False
    while i < n:
        if dq:
            if text[i] == "\\" and i + 1 < n:
                i += 2
                continue
            if text[i] == '"':
                dq = False
            i += 1
            continue
        if text[i] == "'":
            start = i
            i += 1
            while i < n and text[i] != "'":
                i += 1
            if i < n:
                i += 1
            spans.append((start, i))
            continue
        if text[i] == '"':
            dq = True
            i += 1
            continue
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        i += 1
    return spans

def _pgrep_in_single_quote(spans, pos):
    for start, end in spans:
        if start <= pos < end:
            return True
    return False

def _pgrep_single_quote_end(spans, pos):
    for start, end in spans:
        if start <= pos < end:
            return end
    return pos + 1

def _pgrep_read_dollar_paren(text, i, sq):
    j, depth, n = i + 2, 1, len(text)
    while j < n and depth:
        if _pgrep_in_single_quote(sq, j):
            j = _pgrep_single_quote_end(sq, j)
            continue
        if text.startswith("$", j) and j + 1 < n and text[j + 1] == "(":
            depth += 1
            j += 2
            continue
        if text[j] == ")":
            depth -= 1
            j += 1
            continue
        j += 1
    return text[i + 2 : j - 1], j

def _pgrep_read_backtick(text, i, sq):
    j, n = i + 1, len(text)
    while j < n:
        if _pgrep_in_single_quote(sq, j):
            j = _pgrep_single_quote_end(sq, j)
            continue
        if text[j] == "`":
            return text[i + 1 : j], j + 1
        if text[j] == "\\" and j + 1 < n:
            j += 2
            continue
        j += 1
    return None, n


def _pgrep_parse_heredoc_delim(text, i):
    n = len(text)
    if i + 2 > n or text[i : i + 2] != "<<":
        return None
    j = i + 2
    strip_tabs = False
    if j < n and text[j] == "-":
        strip_tabs = True
        j += 1
    if j >= n:
        return ("", strip_tabs, j)
    if text[j] in "'\"":
        q = text[j]
        k = j + 1
        while k < n and text[k] != q:
            k += 1
        if k >= n:
            return ("", strip_tabs, n)
        return (text[j + 1 : k], strip_tabs, k + 1)
    m = re.match(r"[A-Za-z0-9_]+", text[j:])
    if not m:
        return None
    return (m.group(0), strip_tabs, j + m.end())


def _pgrep_heredoc_owner_executable(text, cmd_start, op_start):
    span = _pgrep_first_word_span(text, cmd_start, op_start)
    if not span:
        return False
    word = text[span[0] : span[1]].strip().strip("\"'")
    base = word.rsplit("/", 1)[-1].lower()
    if base in ("bash", "sh", "zsh", "dash", "ksh"):
        return True
    segment = text[cmd_start:op_start]
    if re.search(r"\beval\b", segment, re.I):
        return True
    if re.search(r"\bxargs\b", segment, re.I):
        return True
    if re.search(
        r"(?:^|[;&|(\s])(?:sudo|env|command|exec|nohup|time|nice)\s+(?:\S+\s+)*?(?:\S+/)*(?:bash|sh|zsh|dash|ksh)\b",
        segment,
        re.I,
    ):
        return True
    if re.search(r"\bssh\b", segment, re.I):
        after = text[span[1] : op_start]
        cleaned = re.sub(r"-\S+", " ", after)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned.split()) <= 1:
            return True
    return False


def _pgrep_iter_heredoc_bodies(text):
    n = len(text)
    i = 0
    sq = dq = False
    cmd_start = 0
    while i < n:
        if sq:
            if text[i] == "'":
                sq = False
            i += 1
            continue
        if dq:
            if text[i] == "\\" and i + 1 < n:
                i += 2
                continue
            if text[i] == '"':
                dq = False
            i += 1
            continue
        if text[i] == "'":
            sq = True
            i += 1
            continue
        if text[i] == '"':
            dq = True
            i += 1
            continue
        if text[i] in ";\n|&":
            i += 1
            cmd_start = _pgrep_skip_space(text, i)
            continue
        if text.startswith("&&", i) or text.startswith("||", i):
            i += 2
            cmd_start = _pgrep_skip_space(text, i)
            continue
        if text[i : i + 2] == "<<" and (i == 0 or text[i - 1] in " \t\n;&|("):
            parsed = _pgrep_parse_heredoc_delim(text, i)
            if not parsed:
                i += 2
                continue
            delim, strip_tabs, j = parsed
            executable = _pgrep_heredoc_owner_executable(text, cmd_start, i)
            line_end = text.find("\n", j)
            if line_end == -1:
                body_start = n
                body_end = n
                if executable and body_start < body_end:
                    yield body_start, body_end, executable
                break
            body_start = line_end + 1
            k = body_start
            while k < n:
                line_term = text.find("\n", k)
                if line_term == -1:
                    line_term = n
                line = text[k:line_term]
                if line.endswith("\r"):
                    line = line[:-1]
                cmp_line = line.lstrip("\t") if strip_tabs else line
                if cmp_line == delim:
                    body_end = k
                    if executable and body_start < body_end:
                        yield body_start, body_end, executable
                    i = line_term + 1 if line_term < n else n
                    break
                k = line_term + 1 if line_term < n else n
            else:
                if executable and body_start < n:
                    yield body_start, n, executable
                break
            continue
        i += 1


def _pgrep_iter_simple_command_spans(text):
    n = len(text)
    start = 0
    i = 0
    sq = dq = False
    hd = None
    while i < n:
        if hd is not None:
            delim, strip_tabs, phase = hd
            if phase == "op":
                if text[i] == "\n":
                    hd = (delim, strip_tabs, "body")
                i += 1
                continue
            line_term = text.find("\n", i)
            if line_term == -1:
                line_term = n
            line = text[i:line_term]
            if line.endswith("\r"):
                line = line[:-1]
            cmp_line = line.lstrip("\t") if strip_tabs else line
            if cmp_line == delim:
                hd = None
                i = line_term
                if i < n and text[i] == "\n":
                    yield start, i
                    i += 1
                    start = _pgrep_skip_space(text, i)
                continue
            i = line_term + 1 if line_term < n else n
            continue
        c = text[i]
        if sq:
            if c == "'":
                sq = False
            i += 1
            continue
        if dq:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == '"':
                dq = False
            i += 1
            continue
        if c == "'":
            sq = True
            i += 1
            continue
        if c == '"':
            dq = True
            i += 1
            continue
        if text.startswith("&&", i) or text.startswith("||", i):
            yield start, i
            i += 2
            start = _pgrep_skip_space(text, i)
            continue
        if c in ";\n|":
            yield start, i
            i += 1
            start = _pgrep_skip_space(text, i)
            continue
        if c == "&":
            yield start, i
            i += 1
            start = _pgrep_skip_space(text, i)
            continue
        if text[i : i + 2] == "<<" and (i == 0 or text[i - 1] in " \t\n;&|("):
            parsed = _pgrep_parse_heredoc_delim(text, i)
            if parsed:
                delim, strip_tabs, j = parsed
                hd = (delim, strip_tabs, "op")
                i = j
                continue
        i += 1
    yield start, n

def _pgrep_after_command_leaders(text, i):
    i = _pgrep_skip_space(text, i)
    if i < len(text) and text[i] == "(":
        i = _pgrep_skip_space(text, i + 1)
    for kw in ("if", "while", "until", "then", "do", "else", "!"):
        m = re.match(rf"{kw}\b", text[i:], re.I)
        if m:
            i = _pgrep_skip_space(text, i + m.end())
            break
    return i

def _pgrep_skip_env_token(text, i):
    i = _pgrep_skip_space(text, i)
    if i >= len(text):
        return i
    if text[i] == "-":
        m = re.match(r"-(\w+)(?:\s+(\S+))?", text[i:])
        return i + m.end() if m else i + 1
    m = re.match(r"(\w+)=(?:[^\s\"';|&]+|\"(?:\\.|[^\"\\])*\"|'[^']*')", text[i:])
    if m:
        return i + m.end()
    m = re.match(r"\S+", text[i:])
    return i + m.end() if m else i + 1

def _pgrep_skip_sudo_prefix(text, i):
    while True:
        i = _pgrep_skip_space(text, i)
        if i >= len(text) or text[i] != "-":
            break
        m = re.match(r"-(\w+)(?:\s+(\S+))?", text[i:])
        if not m:
            break
        i += m.end()
    return i

def _pgrep_skip_xargs_options(text, i):
    while True:
        i = _pgrep_skip_space(text, i)
        if i >= len(text) or text[i] != "-":
            break
        m = re.match(r"-\S+", text[i:])
        if not m:
            break
        i += m.end()
    return i

def _pgrep_skip_assignments_and_wrappers(text, i, limit):
    while i < limit:
        i = _pgrep_skip_space(text, i)
        if i >= limit:
            return i
        m = re.match(r"(\w+)=(?:[^\s\"';|&]+|\"(?:\\.|[^\"\\])*\"|'[^']*')", text[i:limit])
        if m:
            i += m.end()
            continue
        wm = re.match(r"(sudo|env|command|exec|nohup|time|nice|xargs)\b", text[i:limit], re.I)
        if not wm:
            break
        w = wm.group(1).lower()
        i += wm.end()
        if w == "sudo":
            i = _pgrep_skip_sudo_prefix(text, i)
        elif w == "env":
            while True:
                i = _pgrep_skip_space(text, i)
                if i >= limit:
                    break
                if text[i] == "-":
                    nxt = _pgrep_skip_env_token(text, i)
                    if nxt == i or nxt > limit:
                        break
                    i = nxt
                    continue
                m = re.match(
                    r"(\w+)=(?:[^\s\"'';|&]+|\"(?:\\.|[^\"\\])*\"|'[^']*')",
                    text[i:limit],
                )
                if m:
                    i += m.end()
                    continue
                break
        elif w == "xargs":
            i = _pgrep_skip_xargs_options(text, i)
    return i

def _pgrep_first_word_span(text, cmd_start, cmd_end):
    i = _pgrep_after_command_leaders(text, cmd_start)
    i = _pgrep_skip_assignments_and_wrappers(text, i, cmd_end)
    if i >= cmd_end:
        return None
    if text[i] == '"':
        j = i + 1
        while j < cmd_end:
            if text[j] == "\\" and j + 1 < cmd_end:
                j += 2
                continue
            if text[j] == '"':
                return i, j + 1
            j += 1
        return i, cmd_end
    if text[i] == "'":
        j = i + 1
        while j < cmd_end and text[j] != "'":
            j += 1
        if j < cmd_end:
            j += 1
        return i, j
    m = re.match(r"((?:[^\s\"';|&]+/)*pgrep)\b", text[i:cmd_end], re.I)
    if m:
        return i, i + m.end()
    m = re.match(r"(\S+)", text[i:cmd_end])
    if m:
        return i, i + m.end()
    return None


def _pgrep_position_in_command_word(text, pos):
    for cmd_start, cmd_end in _pgrep_iter_simple_command_spans(text):
        if pos < cmd_start or pos >= cmd_end:
            continue
        span = _pgrep_first_word_span(text, cmd_start, cmd_end)
        if span and span[0] <= pos < span[1]:
            return span, text[span[0] : span[1]]
        return None, None
    return None, None


def _pgrep_word_is_var_command(word, var):
    if re.match(rf"^\$\{{{var}\}}$|^\${var}\b$", word):
        return True
    return bool(re.match(rf'^"\$\{{{var}\}}"$|^"\${var}"$', word))


# pgrep invocation routes (each must be the first word of a simple command):
# - literal pgrep or path-prefixed pgrep with -f/--full or flag-var tail
# - $VAR / ${VAR} binary alias (P=pgrep, P=/usr/bin/pgrep) with -f/--full or flag-var tail
# - script-alias variable as command word (CMD='pgrep -f …'; $CMD)
# - the same rules inside bash -c / eval / ssh / $(…) / backticks


def _pgrep_position_is_var_invocation(text, pos, var):
    span, word = _pgrep_position_in_command_word(text, pos)
    if not span:
        return False
    return _pgrep_word_is_var_command(word, var)


def _pgrep_position_is_invocation(text, pos):
    span, word = _pgrep_position_in_command_word(text, pos)
    if not span:
        return False
    return bool(re.search(r"pgrep$", word, re.I))

def _pgrep_each_dollar_paren(text):
    sq = _pgrep_single_quote_spans(text)
    i, n, dq = 0, len(text), False
    while i < n:
        if _pgrep_in_single_quote(sq, i):
            i = _pgrep_single_quote_end(sq, i)
            continue
        if dq:
            if text[i] == "\\" and i + 1 < n:
                i += 2
                continue
            if text[i] == '"':
                dq = False
                i += 1
                continue
            if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
                inner, i = _pgrep_read_dollar_paren(text, i, sq)
                yield inner
                continue
            i += 1
            continue
        if text[i] == '"':
            dq = True
            i += 1
            continue
        if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
            inner, i = _pgrep_read_dollar_paren(text, i, sq)
            yield inner
            continue
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        i += 1


def _pgrep_each_backtick(text):
    sq = _pgrep_single_quote_spans(text)
    i, n, dq = 0, len(text), False
    while i < n:
        if _pgrep_in_single_quote(sq, i):
            i = _pgrep_single_quote_end(sq, i)
            continue
        if dq:
            if text[i] == "\\" and i + 1 < n:
                i += 2
                continue
            if text[i] == '"':
                dq = False
                i += 1
                continue
            if text[i] == "`":
                inner, i = _pgrep_read_backtick(text, i, sq)
                if inner is not None:
                    yield inner
                continue
            i += 1
            continue
        if text[i] == '"':
            dq = True
            i += 1
            continue
        if text[i] == "`":
            inner, i = _pgrep_read_backtick(text, i, sq)
            if inner is not None:
                yield inner
            continue
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        i += 1


def _pgrep_pgrep_match_in_fragment(text, raw_for_bindings=None):
    raw = text if raw_for_bindings is None else raw_for_bindings
    for m in PGREP_WORD.finditer(text):
        if not _pgrep_position_is_invocation(text, m.start()):
            continue
        _, _, flags_here = _pgrep_bindings_at_pos(raw, m.start())
        segment = re.match(r"[^\n;&|]*", text[m.end() :])
        if not segment:
            continue
        seg = segment.group(0)
        if pgrep_segment_has_full_flag(seg) or pgrep_segment_uses_flag_var(seg, flags_here):
            return True
    for start, end in _pgrep_iter_quoted_spans(text):
        if _pgrep_quote_opener_is_executable(text, start):
            inner = text[start + 1 : end - 1]
            if _pgrep_pgrep_match_in_fragment(inner):
                return True
    for inner in _pgrep_each_dollar_paren(text):
        if _pgrep_pgrep_match_in_fragment(inner):
            return True
    for inner in _pgrep_each_backtick(text):
        if _pgrep_pgrep_match_in_fragment(inner):
            return True
    for body_start, body_end, executable in _pgrep_iter_heredoc_bodies(raw):
        if executable and _pgrep_pgrep_match_in_fragment(text[body_start:body_end]):
            return True
    return False

def _pgrep_quote_opener_is_executable(text, start):
    before = text[:start].rstrip()
    if re.search(
        r"(?:^|[;&|(\s])(?:(?:sudo|env)\s+\S+\s+)*?(?:\S+/)*(?:bash|sh|zsh|dash|ksh)\b(?:\s+\S+)*\s-(?:[a-zA-Z]*c|c)\s*$",
        before,
    ):
        return True
    if re.search(r"\beval\s*$", before):
        return True
    if re.search(r"\bssh\b(?:\s+(?:-\S+|\S+))*\s+\S+\s*$", before):
        return True
    if re.search(r"\bxargs\b(?:\s+\S+)*\s+$", before):
        return True
    return False

def _pgrep_iter_quoted_spans(text):
    i, n, dq, dq_start = 0, len(text), False, 0
    while i < n:
        if dq:
            if text[i] == "\\" and i + 1 < n:
                i += 2
                continue
            if text[i] == '"':
                yield dq_start, i + 1
                dq = False
            i += 1
            continue
        if text[i] == "'":
            start = i
            i += 1
            while i < n and text[i] != "'":
                i += 1
            if i < n:
                i += 1
            yield start, i
            continue
        if text[i] == '"':
            dq = True
            dq_start = i
            i += 1
            continue
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        i += 1


def _pgrep_blank_data_quotes(text):
    chars = list(text)
    for start, end in _pgrep_iter_quoted_spans(text):
        if _pgrep_quote_opener_is_executable(text, start):
            continue
        inner = text[start + 1 : end - 1]
        if "$(" in inner or "`" in inner:
            continue
        if not PGREP_WORD.search(pgrep_obfuscation_fold(inner)):
            continue
        for k in range(start + 1, end - 1):
            chars[k] = " "
    return "".join(chars)

def _pgrep_process_command_substitutions(text, inner_fn):
    sq = _pgrep_single_quote_spans(text)
    parts, i, n, dq = [], 0, len(text), False
    while i < n:
        if _pgrep_in_single_quote(sq, i):
            end = _pgrep_single_quote_end(sq, i)
            parts.append(text[i:end])
            i = end
            continue
        if dq:
            if text[i] == "\\" and i + 1 < n:
                parts.append(text[i : i + 2])
                i += 2
                continue
            if text[i] == '"':
                parts.append(text[i])
                dq = False
                i += 1
                continue
            if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
                inner, j = _pgrep_read_dollar_paren(text, i, sq)
                parts.append("$(" + inner_fn(inner) + ")")
                i = j
                continue
            if text[i] == "`":
                inner, j = _pgrep_read_backtick(text, i, sq)
                if inner is None:
                    parts.append(text[i:])
                    break
                parts.append("`" + inner_fn(inner) + "`")
                i = j
                continue
            parts.append(text[i])
            i += 1
            continue
        if text[i] == '"':
            parts.append(text[i])
            dq = True
            i += 1
            continue
        if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
            inner, j = _pgrep_read_dollar_paren(text, i, sq)
            parts.append("$(" + inner_fn(inner) + ")")
            i = j
            continue
        if text[i] == "`":
            inner, j = _pgrep_read_backtick(text, i, sq)
            if inner is None:
                parts.append(text[i:])
                break
            parts.append("`" + inner_fn(inner) + "`")
            i = j
            continue
        if text[i] == "\\" and i + 1 < n:
            parts.append(text[i : i + 2])
            i += 2
            continue
        parts.append(text[i])
        i += 1
    return "".join(parts)


def _pgrep_prepare_scan_text(text):
    def normalize(chunk):
        chunk = pgrep_obfuscation_fold(chunk)
        chunk = _pgrep_process_command_substitutions(chunk, normalize)
        return _pgrep_blank_data_quotes(chunk)
    return normalize(text)


_PGREP_ASSIGNMENT = re.compile(
    r"(\w+)=(?:[^\s\"';|&]+|\"(?:\\.|[^\"\\])*\"|'[^']*')"
)


def _pgrep_unquote_assign_value(val):
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
        return val[1:-1]
    return val


def _pgrep_assignment_at(text, i, limit):
    m = _PGREP_ASSIGNMENT.match(text[i:limit])
    if not m:
        return None
    name = m.group(1)
    val = text[i + len(name) + 1 : i + m.end()]
    return name, val, i + m.end()


def _pgrep_apply_var_binding(name, val, binary, script, flag_vars):
    binary.discard(name)
    script.discard(name)
    flag_vars.discard(name)
    raw = _pgrep_unquote_assign_value(val)
    folded = pgrep_obfuscation_fold(raw).strip()
    if re.match(r"^(-f|--full)$", folded):
        flag_vars.add(name)
        return
    wm = re.match(r"(?:\S+/)*pgrep\b", folded, re.I)
    if not wm:
        return
    tail = folded[wm.end() :]
    if pgrep_segment_has_full_flag(tail):
        script.add(name)
    else:
        binary.add(name)


def _pgrep_collect_var_bindings(text):
    binary, script, flag_vars = set(), set(), set()
    for cmd_start, cmd_end in _pgrep_iter_simple_command_spans(text):
        i = _pgrep_after_command_leaders(text, cmd_start)
        while i < cmd_end:
            i = _pgrep_skip_space(text, i)
            if i >= cmd_end:
                break
            asn = _pgrep_assignment_at(text, i, cmd_end)
            if not asn:
                break
            name, val, nxt = asn
            _pgrep_apply_var_binding(name, val, binary, script, flag_vars)
            i = nxt
    return binary, script, flag_vars


def _pgrep_bindings_at_pos(text, pos):
    binary, script, flag_vars = set(), set(), set()
    for cmd_start, cmd_end in _pgrep_iter_simple_command_spans(text):
        i = _pgrep_after_command_leaders(text, cmd_start)
        while i < cmd_end:
            i = _pgrep_skip_space(text, i)
            asn = _pgrep_assignment_at(text, i, cmd_end)
            if not asn:
                break
            name, val, nxt = asn
            _pgrep_apply_var_binding(name, val, binary, script, flag_vars)
            i = nxt
        if pos < cmd_start:
            break
        if cmd_start <= pos < cmd_end:
            return binary, script, flag_vars
    return binary, script, flag_vars

def pgrep_segment_has_full_flag(segment):
    segment = re.sub(r'\\(-f|--full)(?=\s|$)', r'\1', segment)
    if PGREP_FULL_FLAG.search(segment):
        return True
    unquoted = re.sub(r"(?:^|\s)'(-f|--full)'(?=\s|$)", r" \1", segment)
    unquoted = re.sub(r'(?:^|\s)"(-f|--full)"(?=\s|$)', r" \1", unquoted)
    return bool(PGREP_FULL_FLAG.search(unquoted))

def pgrep_segment_uses_flag_var(segment, flag_vars):
    for var in flag_vars:
        if re.search(rf'["\']?\${{{var}}}|["\']?\${var}\b', segment):
            return True
    return False

def pgrep_full_match(text):
    scan = _pgrep_prepare_scan_text(text)
    if _pgrep_pgrep_match_in_fragment(scan, raw_for_bindings=text):
        return True
    for m in PGREP_VAR_INVOKE.finditer(scan):
        var = m.group(1) or m.group(2)
        binary_aliases, script_aliases, flag_vars = _pgrep_bindings_at_pos(text, m.start())
        if var in script_aliases:
            if _pgrep_position_is_var_invocation(scan, m.start(), var):
                return True
            continue
        if var not in binary_aliases:
            continue
        if not _pgrep_position_is_var_invocation(scan, m.start(), var):
            continue
        segment = re.match(r"[^\n;&|]*", scan[m.end() :])
        if not segment:
            continue
        seg = segment.group(0)
        if pgrep_segment_has_full_flag(seg) or pgrep_segment_uses_flag_var(seg, flag_vars):
            return True
    return False

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
    if pgrep_full_match(text):
        verdict(True, PGREP_F_DENY)
    if any(rx.search(text) for rx in ELECTRON_CACHE):
        verdict(True,
            "[electron-cache] ~/Library/Caches/electron and electron-builder hold the Electron "
            "runtime that fork-stage.sh installs bb from, offline and checksum-verified. Without "
            "them the next bb install refuses. Free disk elsewhere: pnpm store prune, node-gyp, "
            "pip or Homebrew caches, ~/.cache, or merged worktrees.")
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
