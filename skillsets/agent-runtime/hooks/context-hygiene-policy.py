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
import bisect
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
_PGREP_OPT_SHORT_TAKES_ARG = frozenset("dFUGPgstu")
_PGREP_OPT_LONG_TAKES_ARG = frozenset(
    {
        "pidfile",
        "signal",
        "ns",
        "nslist",
        "cgroup",
        "parent",
        "session",
        "terminal",
        "euid",
        "uid",
        "group",
        "pgroup",
        "delim",
        "delimiter",
    }
)


def _pgrep_bare_option_token(tok):
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "'\"":
        return tok[1:-1]
    return tok


def _pgrep_iter_pgrep_segment_tokens(segment):
    i, n = 0, len(segment)
    while i < n:
        while i < n and segment[i].isspace():
            i += 1
        if i >= n:
            return
        if segment[i] in ";&|":
            return
        if segment[i] == "'":
            j = i + 1
            while j < n and segment[j] != "'":
                j += 1
            if j < n:
                j += 1
            yield segment[i:j]
            i = j
            continue
        if segment[i] == '"':
            j = i + 1
            while j < n:
                if segment[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if segment[j] == '"':
                    j += 1
                    break
                j += 1
            yield segment[i:j]
            i = j
            continue
        j = i
        while j < n and not segment[j].isspace() and segment[j] not in ";&|":
            j += 1
        yield segment[i:j]
        i = j


def _pgrep_short_option_token_has_full(bare):
    if not bare.startswith("-") or bare.startswith("--"):
        return False
    body = bare[1:]
    if not body:
        return False
    i = 0
    while i < len(body):
        c = body[i]
        if c == "f":
            return True
        if c in _PGREP_OPT_SHORT_TAKES_ARG:
            return False
        i += 1
    return False


def _pgrep_long_option_token_has_full(bare):
    if not bare.startswith("--"):
        return False
    name = bare[2:]
    if not name:
        return False
    eq = name.find("=")
    opt = name[:eq] if eq >= 0 else name
    return opt == "full"


def _pgrep_segment_option_prefix(segment):
    m = re.search(r"(?:^|\s)--(?:\s|$)", segment)
    return segment[: m.start()] if m else segment


def _pgrep_segment_tokenize(segment):
    tokens = list(_pgrep_iter_pgrep_segment_tokens(segment))
    for tok in tokens:
        if tok and tok[0] in "'\"":
            if len(tok) < 2 or tok[0] != tok[-1]:
                return tokens, False
    return tokens, True


def _pgrep_argv_tokens_has_full_flag(tokens):
    idx = 0
    while idx < len(tokens):
        bare = _pgrep_bare_option_token(tokens[idx])
        if bare == "--":
            return False
        if bare.startswith("--"):
            if _pgrep_long_option_token_has_full(bare):
                return True
            opt = bare[2:].split("=", 1)[0]
            if opt in _PGREP_OPT_LONG_TAKES_ARG and "=" not in bare[2:] and idx + 1 < len(tokens):
                idx += 1
            idx += 1
            continue
        if bare.startswith("-") and len(bare) > 1:
            if _pgrep_short_option_token_has_full(bare):
                return True
            body = bare[1:]
            if body and body[0] in _PGREP_OPT_SHORT_TAKES_ARG and len(body) == 1:
                if idx + 1 < len(tokens):
                    idx += 1
            idx += 1
            continue
        idx += 1
    return False


def _pgrep_segment_argv_has_full_flag(segment):
    segment = _pgrep_segment_option_prefix(segment)
    tokens, ok = _pgrep_segment_tokenize(segment)
    if ok:
        return _pgrep_argv_tokens_has_full_flag(tokens)
    rough = re.findall(r"\S+", segment)
    return _pgrep_argv_tokens_has_full_flag(rough)
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

def _pgrep_sq_skip_past(spans, pos, idx):
    n = len(spans)
    while idx < n and pos >= spans[idx][1]:
        idx += 1
    if idx < n and spans[idx][0] <= pos < spans[idx][1]:
        return spans[idx][1], idx
    return None, idx


def _pgrep_in_single_quote(spans, pos):
    end, _ = _pgrep_sq_skip_past(spans, pos, 0)
    return end is not None


def _pgrep_single_quote_end(spans, pos):
    end, _ = _pgrep_sq_skip_past(spans, pos, 0)
    return end if end is not None else pos + 1


def _pgrep_read_dollar_paren(text, i, sq, sq_idx=0):
    j, depth, n = i + 2, 1, len(text)
    while j < n and depth:
        skip, sq_idx = _pgrep_sq_skip_past(sq, j, sq_idx)
        if skip is not None:
            j = skip
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
    return text[i + 2 : j - 1], j, sq_idx


def _pgrep_read_backtick(text, i, sq, sq_idx=0):
    j, n = i + 1, len(text)
    while j < n:
        skip, sq_idx = _pgrep_sq_skip_past(sq, j, sq_idx)
        if skip is not None:
            j = skip
            continue
        if text[j] == "`":
            return text[i + 1 : j], j + 1, sq_idx
        if text[j] == "\\" and j + 1 < n:
            j += 2
            continue
        j += 1
    return None, n, sq_idx


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

def _pgrep_skip_case_header(text, i):
    n = len(text)
    while i < n:
        i = _pgrep_skip_space(text, i)
        if re.match(r"in\b", text[i:], re.I):
            return _pgrep_skip_space(text, i + 2)
        i = _pgrep_skip_one_word(text, i, n)
    return i


_PGREP_LEADER_KWS = frozenset(
    ("if", "while", "until", "then", "do", "else", "function", "case")
)
_PGREP_LEADER_DELTA = {}


def _pgrep_after_command_leaders(text, i):
    n = len(text)
    i = _pgrep_skip_space(text, i)
    base = i
    semi = text.find(";", base)
    probe_ok = semi != -1 and semi - base <= 120
    if probe_ok:
        delta = _PGREP_LEADER_DELTA.get(text[base:semi])
        if delta is not None:
            return base + delta
    if i < n and text[i] not in "({!":
        wend = _pgrep_skip_one_word(text, i, n)
        if text[i:wend].lower() not in _PGREP_LEADER_KWS and not re.match(
            r"\w+\s*\(\s*\)", text[i:]
        ):
            if probe_ok:
                _PGREP_LEADER_DELTA[text[base:semi]] = i - base
            return i
    while i < n:
        start = i
        if text[i] == "(":
            i = _pgrep_skip_space(text, i + 1)
            continue
        if text[i] == "{":
            i = _pgrep_skip_space(text, i + 1)
            continue
        if text[i] == "!":
            i = _pgrep_skip_space(text, i + 1)
            continue
        for kw in ("if", "while", "until", "then", "do", "else", "function", "case"):
            m = re.match(rf"{kw}\b", text[i:], re.I)
            if m:
                kwl = m.group(0).lower()
                i = _pgrep_skip_space(text, i + m.end())
                if kwl == "function":
                    wm = re.match(r"(\w+)\b", text[i:])
                    if wm:
                        i = _pgrep_skip_space(text, i + wm.end())
                    if i < n and text[i] == "{":
                        i = _pgrep_skip_space(text, i + 1)
                elif kwl == "case":
                    i = _pgrep_skip_case_header(text, i)
                    pm = re.match(r"[^)]*\)", text[i:])
                    if pm:
                        i = _pgrep_skip_space(text, i + pm.end())
                continue
        m = re.match(r"(\w+)\s*\(\s*\)", text[i:])
        if m:
            i = _pgrep_skip_space(text, i + m.end())
            if i < n and text[i] == "{":
                i = _pgrep_skip_space(text, i + 1)
            continue
        if i == start:
            break
    if probe_ok:
        _PGREP_LEADER_DELTA[text[base:semi]] = i - base
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


def _pgrep_skip_one_word(text, i, limit):
    i = _pgrep_skip_space(text, i)
    if i >= limit:
        return i
    if text[i] == '"':
        j = i + 1
        while j < limit:
            if text[j] == "\\" and j + 1 < limit:
                j += 2
                continue
            if text[j] == '"':
                return j + 1
            j += 1
        return limit
    if text[i] == "'":
        j = i + 1
        while j < limit and text[j] != "'":
            j += 1
        return j + 1 if j < limit else limit
    m = re.match(r"[^\s\"';|&]+", text[i:limit])
    return i + m.end() if m else i + 1


def _pgrep_skip_dash_options(text, i, limit, short_with_arg, short_flags, long_with_arg, long_flags):
    short_with_arg = set(short_with_arg)
    short_flags = set(short_flags)
    long_with_arg = set(long_with_arg)
    long_flags = set(long_flags)
    while i < limit:
        i = _pgrep_skip_space(text, i)
        if i >= limit or text[i] != "-":
            break
        if text.startswith("--", i):
            m = re.match(r"--([\w-]+)", text[i:limit])
            if not m:
                break
            opt = m.group(1)
            i += m.end()
            if opt in long_with_arg:
                i = _pgrep_skip_one_word(text, i, limit)
            continue
        if i + 1 < limit and text[i + 1].isdigit():
            i = _pgrep_skip_one_word(text, i, limit)
            continue
        j = i + 1
        while j < limit and text[j].isalpha():
            ch = text[j]
            j += 1
            if ch in short_with_arg:
                i = j
                i = _pgrep_skip_one_word(text, i, limit)
                j = i
                break
        else:
            i = j
    return i


def _pgrep_skip_wrapper_consumer(name, text, i, limit):
    n = name.lower()
    if n == "sudo":
        return _pgrep_skip_sudo_prefix(text, i)
    if n == "env":
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
        return i
    if n == "xargs":
        return _pgrep_skip_xargs_options(text, i)
    if n == "timeout":
        i = _pgrep_skip_dash_options(
            text,
            i,
            limit,
            short_with_arg="sk",
            short_flags="fv",
            long_with_arg=("kill-after", "signal"),
            long_flags=("foreground", "preserve-status", "verbose"),
        )
        return _pgrep_skip_one_word(text, i, limit)
    if n == "nice":
        i = _pgrep_skip_dash_options(
            text, i, limit, short_with_arg="n", short_flags="", long_with_arg=(), long_flags=()
        )
        return i
    if n == "ionice":
        return _pgrep_skip_dash_options(
            text, i, limit, short_with_arg="cn", short_flags="t", long_with_arg=(), long_flags=()
        )
    if n == "stdbuf":
        return _pgrep_skip_dash_options(
            text, i, limit, short_with_arg="ioe", short_flags="", long_with_arg=("input", "output", "error"), long_flags=()
        )
    if n == "chrt":
        i = _pgrep_skip_dash_options(
            text,
            i,
            limit,
            short_with_arg="bf",
            short_flags="",
            long_with_arg=("pid", "ppid", "clock", "deadline", "sched", "policy"),
            long_flags=(),
        )
        return _pgrep_skip_one_word(text, i, limit)
    if n == "taskset":
        i = _pgrep_skip_dash_options(
            text, i, limit, short_with_arg="cp", short_flags="a", long_with_arg=(), long_flags=()
        )
        return _pgrep_skip_one_word(text, i, limit)
    if n == "flock":
        i = _pgrep_skip_dash_options(
            text, i, limit, short_with_arg="n", short_flags="ux", long_with_arg=(), long_flags=()
        )
        return _pgrep_skip_one_word(text, i, limit)
    if n == "setsid":
        return _pgrep_skip_dash_options(
            text, i, limit, short_with_arg="w", short_flags="fc", long_with_arg=(), long_flags=()
        )
    if n == "time":
        return _pgrep_skip_dash_options(
            text, i, limit, short_with_arg="", short_flags="pv", long_with_arg=(), long_flags=("format", "output", "verbose")
        )
    if n == "caffeinate":
        return _pgrep_skip_dash_options(
            text,
            i,
            limit,
            short_with_arg="dimsutw",
            short_flags="",
            long_with_arg=("timeout", "expire", "sleep", "wake", "start", "end"),
            long_flags=("fail", "assert", "lock", "disable", "enable"),
        )
    if n == "doas":
        return _pgrep_skip_dash_options(
            text, i, limit, short_with_arg="unL", short_flags="", long_with_arg=(), long_flags=()
        )
    if n == "runuser":
        i = _pgrep_skip_dash_options(
            text, i, limit, short_with_arg="u", short_flags="", long_with_arg=(), long_flags=()
        )
        i = _pgrep_skip_space(text, i)
        if i + 1 < limit and text[i : i + 2] == "--":
            i += 2
        return i
    if n == "watch":
        return _pgrep_skip_dash_options(
            text,
            i,
            limit,
            short_with_arg="ntd",
            short_flags="bg",
            long_with_arg=("interval", "differences", "errexit", "color", "exec"),
            long_flags=("beep", "color", "exact", "no-title", "precise", "show", "differences"),
        )
    if n == "command":
        return _pgrep_skip_dash_options(
            text, i, limit, short_with_arg="p", short_flags="v", long_with_arg=(), long_flags=()
        )
    return i


_PGREP_WRAPPER_WORDS = (
    "sudo",
    "env",
    "command",
    "exec",
    "nohup",
    "time",
    "nice",
    "xargs",
    "timeout",
    "ionice",
    "stdbuf",
    "chrt",
    "taskset",
    "flock",
    "setsid",
    "caffeinate",
    "doas",
    "runuser",
    "watch",
)
_PGREP_WRAPPER_RE = re.compile(
    r"(?:%s)\b" % "|".join(re.escape(w) for w in _PGREP_WRAPPER_WORDS),
    re.I,
)


def _pgrep_skip_assignments_and_wrappers(text, i, limit):
    while i < limit:
        i = _pgrep_skip_space(text, i)
        if i >= limit:
            return i
        m = re.match(r"(\w+)=(?:[^\s\"';|&]+|\"(?:\\.|[^\"\\])*\"|'[^']*')", text[i:limit])
        if m:
            i += m.end()
            continue
        wm = _PGREP_WRAPPER_RE.match(text[i:limit])
        if not wm:
            break
        w = wm.group(0)
        i += wm.end()
        i = _pgrep_skip_wrapper_consumer(w, text, i, limit)
    return i


def _pgrep_bare_word(word):
    if len(word) >= 2 and word[0] == word[-1] and word[0] in "'\"":
        return word[1:-1]
    return word


def _pgrep_command_words(text, cmd_start, cmd_end):
    words = []
    i = cmd_start
    while i < cmd_end:
        i = _pgrep_skip_space(text, i)
        if i >= cmd_end:
            break
        s = i
        e = _pgrep_skip_one_word(text, i, cmd_end)
        words.append((s, e, text[s:e]))
        i = e
    return words


def _pgrep_skip_launcher_options(text, i, limit, short_with_arg, short_flags, long_with_arg=(), long_flags=()):
    return _pgrep_skip_dash_options(
        text, i, limit, short_with_arg, short_flags, long_with_arg, long_flags
    )


def _pgrep_prefix_launch_region(text, cmd_start, cmd_end):
    i = _pgrep_after_command_leaders(text, cmd_start)
    i = _pgrep_skip_assignments_and_wrappers(text, i, cmd_end)
    if i >= cmd_end:
        return None
    s = i
    e = _pgrep_skip_one_word(text, i, cmd_end)
    base = _pgrep_bare_word(text[s:e]).rsplit("/", 1)[-1].lower()
    if base == "chroot":
        i = _pgrep_skip_one_word(text, e, cmd_end)
        i = _pgrep_skip_space(text, i)
        if i >= cmd_end:
            return None
        return i, cmd_end
    if base in ("strace", "ltrace"):
        i = _pgrep_skip_launcher_options(
            text,
            e,
            cmd_end,
            short_with_arg="p",
            short_flags="faehikqrstvxy",
            long_with_arg=("trace", "trace-path", "output", "write", "chdir", "stack-traces", "follow-execve"),
            long_flags=("follow-forks", "follow-fork", "follow-clone", "follow-vfork"),
        )
        return i, cmd_end
    if base == "nsenter":
        i = _pgrep_skip_launcher_options(
            text, e, cmd_end, short_with_arg="tU", short_flags="F", long_with_arg=("target", "user"), long_flags=()
        )
        return i, cmd_end
    if base == "unshare":
        i = _pgrep_skip_launcher_options(
            text, e, cmd_end, short_with_arg="f", short_flags="", long_with_arg=("mount-proc", "mount-sys"), long_flags=()
        )
        return i, cmd_end
    if base == "valgrind":
        i = _pgrep_skip_launcher_options(
            text,
            e,
            cmd_end,
            short_with_arg="",
            short_flags="",
            long_with_arg=("tool", "log-file", "log-fd", "log-socket", "xml-file", "xml-fd", "xml-socket"),
            long_flags=("help", "version", "quiet", "trace-children", "track-fds", "time-stamp"),
        )
        return i, cmd_end
    if base == "gdb":
        words = _pgrep_command_words(text, s, cmd_end)
        for idx, (ws, we, w) in enumerate(words):
            if _pgrep_bare_word(w) == "--args" and idx + 1 < len(words):
                return words[idx + 1][0], cmd_end
        return None
    return None


def _pgrep_embedded_launch_regions(text, cmd_start, cmd_end):
    chunk = text[cmd_start:cmd_end]
    if "-exec" not in chunk and "-ok" not in chunk and ":::" not in chunk:
        return
    words = _pgrep_command_words(text, cmd_start, cmd_end)
    if not words:
        return
    first = _pgrep_bare_word(words[0][2]).rsplit("/", 1)[-1].lower()
    if first == "parallel":
        j = 1
        while j < len(words):
            w = words[j][2]
            if _pgrep_bare_word(w) == ":::":
                break
            if w.startswith("-"):
                j += 1
                continue
            inner_start = words[j][0]
            inner_end = cmd_end
            for k in range(j, len(words)):
                if _pgrep_bare_word(words[k][2]) == ":::":
                    inner_end = words[k][0]
                    break
            yield inner_start, inner_end
            return
    for idx, (ws, we, w) in enumerate(words):
        bare = _pgrep_bare_word(w)
        if bare in ("-exec", "-execdir", "-ok", "-okdir") and idx + 1 < len(words):
            inner_start = words[idx + 1][0]
            inner_end = cmd_end
            for j in range(idx + 2, len(words)):
                bj = _pgrep_bare_word(words[j][2])
                if bj in ("\\;", ";", "+"):
                    inner_end = words[j][0]
                    break
            yield inner_start, inner_end


def _pgrep_iter_launched_command_regions(text, cmd_start, cmd_end):
    pref = _pgrep_prefix_launch_region(text, cmd_start, cmd_end)
    if pref:
        yield pref
    yield from _pgrep_embedded_launch_regions(text, cmd_start, cmd_end)


def _pgrep_position_is_launched_pgrep(text, pos):
    for cmd_start, cmd_end in _pgrep_iter_simple_command_spans(text):
        if pos < cmd_start or pos >= cmd_end:
            continue
        for ls, le in _pgrep_iter_launched_command_regions(text, cmd_start, cmd_end):
            span = _pgrep_first_word_span(text, ls, le)
            if span and span[0] <= pos < span[1]:
                return bool(re.search(r"pgrep$", text[span[0] : span[1]], re.I))
        return False
    return False

def _pgrep_first_word_span(text, cmd_start, cmd_end, *, _leader=None):
    i = _leader if _leader is not None else _pgrep_after_command_leaders(text, cmd_start)
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
    if span and re.search(r"pgrep$", word, re.I):
        return True
    return _pgrep_position_is_launched_pgrep(text, pos)

def _pgrep_each_dollar_paren(text):
    sq = _pgrep_single_quote_spans(text)
    i, n, dq, sq_idx = 0, len(text), False, 0
    while i < n:
        skip, sq_idx = _pgrep_sq_skip_past(sq, i, sq_idx)
        if skip is not None:
            i = skip
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
                inner, i, sq_idx = _pgrep_read_dollar_paren(text, i, sq, sq_idx)
                yield inner
                continue
            i += 1
            continue
        if text[i] == '"':
            dq = True
            i += 1
            continue
        if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
            inner, i, sq_idx = _pgrep_read_dollar_paren(text, i, sq, sq_idx)
            yield inner
            continue
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        i += 1


def _pgrep_each_backtick(text):
    sq = _pgrep_single_quote_spans(text)
    i, n, dq, sq_idx = 0, len(text), False, 0
    while i < n:
        skip, sq_idx = _pgrep_sq_skip_past(sq, i, sq_idx)
        if skip is not None:
            i = skip
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
                inner, i, sq_idx = _pgrep_read_backtick(text, i, sq, sq_idx)
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
            inner, i, sq_idx = _pgrep_read_backtick(text, i, sq, sq_idx)
            if inner is not None:
                yield inner
            continue
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        i += 1


_PGREP_FRAGMENT_MAX_DEPTH = 64


def _pgrep_pgrep_match_in_fragment(text, raw_for_bindings=None, _ctx=None, _depth=0):
    if _depth > _PGREP_FRAGMENT_MAX_DEPTH:
        return False
    if _ctx is None:
        raw = text if raw_for_bindings is None else raw_for_bindings
        _ctx = _PgrepScanContext(raw)
        text = _ctx.scan
    else:
        raw = _ctx.raw
    for m in PGREP_WORD.finditer(text):
        if not _ctx.pgrep_word_is_invocation(m.start()):
            continue
        _, _, flags_here = _ctx.bindings_at(m.start())
        if not flags_here:
            tail = text[m.end() : m.end() + 96].lstrip()
            if tail and not pgrep_segment_has_full_flag(
                tail[:32]
            ) and not pgrep_segment_uses_flag_var(tail[:32], flags_here):
                continue
        segment = re.match(r"[^\n;&|]*", text[m.end() :])
        if not segment:
            continue
        seg = segment.group(0)
        if pgrep_segment_has_full_flag(seg) or pgrep_segment_uses_flag_var(seg, flags_here):
            return True
    for start, end, is_exec in _pgrep_iter_quoted_spans_meta(text):
        if is_exec:
            inner = text[start + 1 : end - 1]
            if _pgrep_pgrep_match_in_fragment(inner, _depth=_depth + 1):
                return True
    for inner in _pgrep_each_dollar_paren(text):
        if not re.search(r"pgrep", inner, re.I):
            continue
        if _pgrep_pgrep_match_in_fragment(inner, _depth=_depth + 1):
            return True
    for inner in _pgrep_each_backtick(text):
        if not re.search(r"pgrep", inner, re.I):
            continue
        if _pgrep_pgrep_match_in_fragment(inner, _depth=_depth + 1):
            return True
    for body_start, body_end, executable in _pgrep_iter_heredoc_bodies(raw):
        if executable and _pgrep_pgrep_match_in_fragment(text[body_start:body_end], _depth=_depth + 1):
            return True
    return False


_PGREP_SHELL_WORDS = frozenset(("bash", "sh", "zsh", "dash", "ksh"))
_PGREP_DASH_C_OPENERS = frozenset(("su", "runuser", "script"))


def _pgrep_word_is_dash_c_flag(word):
    return bool(re.match(r"^-[a-zA-Z]*c$", _pgrep_bare_word(word)))


def _pgrep_mark_dash_c_exec_quote(text, i, cmd_end, out):
    while i < cmd_end:
        i = _pgrep_skip_space(text, i)
        if i >= cmd_end:
            return
        ws = i
        we = _pgrep_skip_one_word(text, i, cmd_end)
        if _pgrep_word_is_dash_c_flag(text[ws:we]):
            i = _pgrep_skip_space(text, we)
            if i < cmd_end and text[i] in "'\"":
                out.add(i)
            return
        i = we


def _pgrep_mark_ssh_exec_quote(text, i, cmd_end, out):
    saw_word = False
    while i < cmd_end:
        i = _pgrep_skip_space(text, i)
        if i >= cmd_end:
            return
        if text[i] in "'\"":
            if saw_word:
                out.add(i)
            return
        i = _pgrep_skip_one_word(text, i, cmd_end)
        saw_word = True


def _pgrep_mark_exec_quotes_in_command(text, cmd_start, cmd_end, out):
    i0 = _pgrep_skip_space(text, cmd_start)
    if i0 < cmd_end:
        wend = _pgrep_skip_one_word(text, i0, cmd_end)
        if text[i0:wend].lower() in ("for", "while", "until"):
            return
    i = _pgrep_after_command_leaders(text, cmd_start)
    while i < cmd_end:
        i = _pgrep_skip_space(text, i)
        if i >= cmd_end:
            return
        asn = _pgrep_assignment_at(text, i, cmd_end)
        if asn:
            i = asn[2]
            continue
        wm = _PGREP_WRAPPER_RE.match(text[i:cmd_end])
        if wm:
            w = wm.group(0)
            wl = w.lower()
            wi = i + len(w)
            if wl == "watch":
                wi = _pgrep_skip_wrapper_consumer(w, text, wi, cmd_end)
                wi = _pgrep_skip_space(text, wi)
                if wi < cmd_end and text[wi] in "'\"":
                    out.add(wi)
                return
            if wl == "xargs":
                wi = _pgrep_skip_wrapper_consumer(w, text, wi, cmd_end)
                wi = _pgrep_skip_space(text, wi)
                if wi < cmd_end and text[wi] in "'\"":
                    out.add(wi)
                return
            if wl == "runuser":
                wi = _pgrep_skip_wrapper_consumer(w, text, wi, cmd_end)
                _pgrep_mark_dash_c_exec_quote(text, wi, cmd_end, out)
                return
            wi = _pgrep_skip_wrapper_consumer(w, text, wi, cmd_end)
            i = wi
            continue
        break
    ws = i
    we = _pgrep_skip_one_word(text, i, cmd_end)
    if we <= ws:
        return
    base = _pgrep_bare_word(text[ws:we]).rsplit("/", 1)[-1].lower()
    if base in _PGREP_SHELL_WORDS:
        _pgrep_mark_dash_c_exec_quote(text, we, cmd_end, out)
    elif base == "eval":
        i = _pgrep_skip_space(text, we)
        if i < cmd_end and text[i] in "'\"":
            out.add(i)
    elif base == "ssh":
        _pgrep_mark_ssh_exec_quote(text, we, cmd_end, out)
    elif base in _PGREP_DASH_C_OPENERS:
        _pgrep_mark_dash_c_exec_quote(text, we, cmd_end, out)


def _pgrep_enqueue_substitution_chunks(chunk, origin, pending):
    sq = _pgrep_single_quote_spans(chunk)
    i, n, dq, sq_idx = 0, len(chunk), False, 0
    while i < n:
        skip, sq_idx = _pgrep_sq_skip_past(sq, i, sq_idx)
        if skip is not None:
            i = skip
            continue
        if dq:
            if chunk[i] == "\\" and i + 1 < n:
                i += 2
                continue
            if chunk[i] == '"':
                dq = False
                i += 1
                continue
            if chunk.startswith("$", i) and i + 1 < n and chunk[i + 1] == "(":
                inner, j, sq_idx = _pgrep_read_dollar_paren(chunk, i, sq, sq_idx)
                if "'" in inner or '"' in inner:
                    pending.append((origin + i + 2, inner))
                i = j
                continue
            if chunk[i] == "`":
                inner, j, sq_idx = _pgrep_read_backtick(chunk, i, sq, sq_idx)
                if inner is not None and ("'" in inner or '"' in inner):
                    pending.append((origin + i + 1, inner))
                i = j
                continue
            i += 1
            continue
        if chunk[i] == '"':
            dq = True
            i += 1
            continue
        if chunk.startswith("$", i) and i + 1 < n and chunk[i + 1] == "(":
            inner, j, sq_idx = _pgrep_read_dollar_paren(chunk, i, sq, sq_idx)
            if "'" in inner or '"' in inner:
                pending.append((origin + i + 2, inner))
            i = j
            continue
        if chunk[i] == "`":
            inner, j, sq_idx = _pgrep_read_backtick(chunk, i, sq, sq_idx)
            if inner is not None and ("'" in inner or '"' in inner):
                pending.append((origin + i + 1, inner))
            i = j
            continue
        if chunk[i] == "\\" and i + 1 < n:
            i += 2
            continue
        i += 1


def _pgrep_executable_single_quote_starts(text):
    if "'" not in text and '"' not in text:
        return set()
    out = set()
    pending = [(0, text)]
    idx = 0
    while idx < len(pending):
        origin, chunk = pending[idx]
        idx += 1
        for cmd_start, cmd_end in _pgrep_iter_simple_command_spans(chunk):
            i0 = _pgrep_skip_space(chunk, cmd_start)
            if i0 < cmd_end:
                wend = _pgrep_skip_one_word(chunk, i0, cmd_end)
                if chunk[i0:wend].lower() in ("for", "while", "until"):
                    continue
            local = set()
            _pgrep_mark_exec_quotes_in_command(chunk, cmd_start, cmd_end, local)
            for pos in local:
                out.add(origin + pos)
        _pgrep_enqueue_substitution_chunks(chunk, origin, pending)
    return out


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

def _pgrep_quote_is_assignment_value(text, start):
    i = start - 1
    while i >= 0 and text[i].isspace():
        i -= 1
    if i < 0 or text[i] != "=":
        return False
    j = i - 1
    while j >= 0 and (text[j].isalnum() or text[j] == "_"):
        j -= 1
    return True


def _pgrep_iter_quoted_spans_meta(text):
    if "'" not in text and '"' not in text:
        for start, end in _pgrep_iter_quoted_spans(text):
            yield start, end, False
        return
    exec_starts = _pgrep_executable_single_quote_starts(text)
    for start, end in _pgrep_iter_quoted_spans(text):
        yield start, end, start in exec_starts




def _pgrep_blank_data_quotes(text):
    chars = list(text)
    for start, end, is_exec in _pgrep_iter_quoted_spans_meta(text):
        if is_exec or _pgrep_quote_is_assignment_value(text, start):
            continue
        inner = text[start + 1 : end - 1]
        if "$(" in inner or "`" in inner:
            continue
        if "pgrep" not in inner.lower():
            continue
        if not PGREP_WORD.search(pgrep_obfuscation_fold(inner)):
            continue
        for k in range(start + 1, end - 1):
            chars[k] = " "
    return "".join(chars)

def _pgrep_process_command_substitutions(text, inner_fn):
    sq = _pgrep_single_quote_spans(text)
    parts, i, n, dq, sq_idx = [], 0, len(text), False, 0
    while i < n:
        skip, sq_idx = _pgrep_sq_skip_past(sq, i, sq_idx)
        if skip is not None:
            parts.append(text[i:skip])
            i = skip
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
                inner, j, sq_idx = _pgrep_read_dollar_paren(text, i, sq, sq_idx)
                parts.append("$(" + inner_fn(inner) + ")")
                i = j
                continue
            if text[i] == "`":
                inner, j, sq_idx = _pgrep_read_backtick(text, i, sq, sq_idx)
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
            inner, j, sq_idx = _pgrep_read_dollar_paren(text, i, sq, sq_idx)
            parts.append("$(" + inner_fn(inner) + ")")
            i = j
            continue
        if text[i] == "`":
            inner, j, sq_idx = _pgrep_read_backtick(text, i, sq, sq_idx)
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


_PGREP_SUBST_EXPAND_MAX = 64


def _pgrep_prepare_scan_text(text):
    chunk = pgrep_obfuscation_fold(text)
    for _ in range(_PGREP_SUBST_EXPAND_MAX):
        nxt = _pgrep_process_command_substitutions(chunk, pgrep_obfuscation_fold)
        if nxt == chunk:
            break
        chunk = nxt
    return _pgrep_blank_data_quotes(chunk)


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


def _pgrep_simple_command_is_assignments_only(text, cmd_start, cmd_end):
    i = _pgrep_after_command_leaders(text, cmd_start)
    saw = False
    while i < cmd_end:
        i = _pgrep_skip_space(text, i)
        if i >= cmd_end:
            return saw
        asn = _pgrep_assignment_at(text, i, cmd_end)
        if not asn:
            return False
        saw = True
        i = asn[2]
    return saw


def _pgrep_collect_var_bindings(text):
    binary, script, flag_vars = set(), set(), set()
    for cmd_start, cmd_end in _pgrep_iter_simple_command_spans(text):
        eb, es, ef = set(binary), set(script), set(flag_vars)
        i = _pgrep_after_command_leaders(text, cmd_start)
        while i < cmd_end:
            i = _pgrep_skip_space(text, i)
            if i >= cmd_end:
                break
            asn = _pgrep_assignment_at(text, i, cmd_end)
            if not asn:
                break
            name, val, nxt = asn
            _pgrep_apply_var_binding(name, val, eb, es, ef)
            i = nxt
        if _pgrep_simple_command_is_assignments_only(text, cmd_start, cmd_end):
            binary, script, flag_vars = eb, es, ef
    return binary, script, flag_vars


def _pgrep_bindings_at_pos(text, pos):
    binary, script, flag_vars = set(), set(), set()
    for cmd_start, cmd_end in _pgrep_iter_simple_command_spans(text):
        if pos < cmd_start:
            break
        eb, es, ef = set(binary), set(script), set(flag_vars)
        i = _pgrep_after_command_leaders(text, cmd_start)
        while i < cmd_end:
            i = _pgrep_skip_space(text, i)
            if i >= cmd_end:
                break
            asn = _pgrep_assignment_at(text, i, cmd_end)
            if not asn:
                break
            name, val, nxt = asn
            _pgrep_apply_var_binding(name, val, eb, es, ef)
            i = nxt
        if cmd_start <= pos < cmd_end:
            return eb, es, ef
        if _pgrep_simple_command_is_assignments_only(text, cmd_start, cmd_end):
            binary, script, flag_vars = eb, es, ef
    return binary, script, flag_vars

import bisect


class _PgrepScanContext:
    __slots__ = (
        "raw",
        "scan",
        "cmd_spans",
        "_bind_pos",
        "_bind_b",
        "_bind_s",
        "_bind_f",
        "_inv_starts",
        "_inv_ends",
        "_cmd_starts",
    )

    def __init__(self, raw):
        self.raw = raw
        self.scan = _pgrep_prepare_scan_text(raw)
        self.cmd_spans = tuple(_pgrep_iter_simple_command_spans(self.scan))
        pos, b, s, f, inv = _pgrep_build_binding_snapshot_arrays(self.scan, self.cmd_spans)
        self._bind_pos = pos
        self._bind_b = b
        self._bind_s = s
        self._bind_f = f
        self._cmd_starts = [c[0] for c in self.cmd_spans]
        self._inv_starts = [p[0] for p in inv]
        self._inv_ends = [p[1] for p in inv]

    def bindings_at(self, pos):
        idx = bisect.bisect_right(self._bind_pos, pos) - 1
        if idx < 0:
            return set(), set(), set()
        return self._bind_b[idx], self._bind_s[idx], self._bind_f[idx]

    def pgrep_word_is_invocation(self, pos):
        idx = bisect.bisect_right(self._inv_starts, pos) - 1
        if idx < 0:
            return False
        return pos < self._inv_ends[idx]

    def var_is_command_word(self, pos, var):
        idx = bisect.bisect_right(self._cmd_starts, pos) - 1
        if idx < 0:
            return False
        cmd_start, cmd_end = self.cmd_spans[idx]
        if pos >= cmd_end:
            return False
        span = _pgrep_first_word_span(self.scan, cmd_start, cmd_end)
        if span and span[0] <= pos < span[1]:
            return _pgrep_word_is_var_command(self.scan[span[0] : span[1]], var)
        return False


_PGREP_EMPTY_BIND = frozenset()


_PGREP_LAUNCH_HINT = re.compile(
    r"(?:^|[\s;|&(])(?:ssh|bash|sh|eval|sudo|docker|kubectl|find|parallel|chroot|strace|gdb|nsenter|valgrind|ltrace|unshare|runuser|xargs|watch)\b",
    re.I,
)


def _pgrep_build_binding_snapshot_arrays(text, cmd_spans):
    positions = [0]
    binaries = [_PGREP_EMPTY_BIND]
    scripts = [_PGREP_EMPTY_BIND]
    flags = [_PGREP_EMPTY_BIND]
    inv = []
    binary, script, flag_vars = set(), set(), set()
    for cmd_start, cmd_end in cmd_spans:
        leader = _pgrep_after_command_leaders(text, cmd_start)
        positions.append(leader)
        binaries.append(frozenset(binary) if binary else _PGREP_EMPTY_BIND)
        scripts.append(frozenset(script) if script else _PGREP_EMPTY_BIND)
        flags.append(frozenset(flag_vars) if flag_vars else _PGREP_EMPTY_BIND)
        fw = _pgrep_first_word_span(text, cmd_start, cmd_end, _leader=leader)
        if fw and _pgrep_word_span_is_pgrep_command_word(text, fw[0], fw[1]):
            inv.append(fw)
        else:
            chunk = text[cmd_start:cmd_end]
            if PGREP_WORD.search(chunk) and _PGREP_LAUNCH_HINT.search(chunk):
                for ls, le in _pgrep_iter_launched_command_regions(text, cmd_start, cmd_end):
                    lfw = _pgrep_first_word_span(text, ls, le)
                    if lfw and _pgrep_word_span_is_pgrep_command_word(text, lfw[0], lfw[1]):
                        inv.append(lfw)
        eb, es, ef = set(binary), set(script), set(flag_vars)
        i = leader
        while i < cmd_end:
            i = _pgrep_skip_space(text, i)
            if i >= cmd_end:
                break
            asn = _pgrep_assignment_at(text, i, cmd_end)
            if not asn:
                break
            name, val, nxt = asn
            _pgrep_apply_var_binding(name, val, eb, es, ef)
            positions.append(nxt)
            binaries.append(frozenset(eb))
            scripts.append(frozenset(es))
            flags.append(frozenset(ef))
            i = nxt
        if "=" in text[cmd_start:cmd_end] and _pgrep_simple_command_is_assignments_only(
            text, cmd_start, cmd_end
        ):
            binary, script, flag_vars = eb, es, ef
    return positions, binaries, scripts, flags, inv


def _pgrep_word_span_is_pgrep_command_word(text, s, e):
    w = text[s:e]
    if w and w[0] not in "'\"":
        wl = w.lower()
        if wl == "pgrep" or wl.endswith("/pgrep"):
            return True
    if len(w) >= 2 and w[0] == w[-1] and w[0] in "'\"":
        inner = w[1:-1].lstrip()
        if not inner:
            return False
        iw = _pgrep_skip_one_word(inner, 0, len(inner))
        return bool(re.search(r"(?:^|(?:\S+/)*)(?:pgrep)\b", pgrep_obfuscation_fold(inner[:iw]), re.I))
    return bool(re.search(r"(?:\S+/)*pgrep\b", pgrep_obfuscation_fold(w), re.I))



def pgrep_segment_has_full_flag(segment):
    segment = re.sub(r'\\(-f|--full)(?=\s|$)', r'\1', segment)
    opts = _pgrep_segment_option_prefix(segment)
    tokens, ok = _pgrep_segment_tokenize(opts)
    if ok:
        return _pgrep_argv_tokens_has_full_flag(tokens)
    unquoted = re.sub(r"(?:^|\s)'(-f|--full)'(?=\s|$)", r" \1", segment)
    unquoted = re.sub(r'(?:^|\s)"(-f|--full)"(?=\s|$)', r" \1", unquoted)
    uopts = _pgrep_segment_option_prefix(unquoted)
    tokens, ok = _pgrep_segment_tokenize(uopts)
    if ok:
        return _pgrep_argv_tokens_has_full_flag(tokens)
    rough = re.findall(r"\S+", uopts)
    return _pgrep_argv_tokens_has_full_flag(rough)

def pgrep_segment_uses_flag_var(segment, flag_vars):
    for var in flag_vars:
        if re.search(rf'["\']?\${{{var}}}|["\']?\${var}\b', segment):
            return True
    return False

def pgrep_full_match(text):
    if not PGREP_WORD.search(pgrep_obfuscation_fold(text)):
        return False
    ctx = _PgrepScanContext(text)
    if _pgrep_pgrep_match_in_fragment(ctx.scan, _ctx=ctx):
        return True
    scan = ctx.scan
    for m in PGREP_VAR_INVOKE.finditer(scan):
        var = m.group(1) or m.group(2)
        binary_aliases, script_aliases, flag_vars = ctx.bindings_at(m.start())
        if var in script_aliases:
            if ctx.var_is_command_word(m.start(), var):
                return True
            continue
        if var not in binary_aliases:
            continue
        if not ctx.var_is_command_word(m.start(), var):
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
    try:
        if pgrep_full_match(text):
            verdict(True, PGREP_F_DENY)
    except Exception:
        pass
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
