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
import tokenize

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
BB_LIFECYCLE_PKILL = re.compile(
    r'(?:^|[;&|(`\n])\s*(?:(?:sudo|env|command|exec|nohup|timeout)\s+(?:-\S+\s+|\d+\s+|\w+=\S*\s+)*)*(?:\w+=\S*\s+)*(?:\S*/)?pkill(?=\s|$|[;&|)`])'
)
BB_LIFECYCLE = [
    re.compile(r'tell\s+application\s+(?:id\s+)?[\\"]*(?:dev\.bb\.desktop|bb)[\\"]*\s+to\s+quit', re.I),
    re.compile(r'\b(?:mv|rm|ditto|rsync)\b[^\n;&|]*?/Applications/bb\.app(?![\w./-]*/Contents/)'),
    re.compile(r'\bkillall\s+(?:-\S+\s+)*[\\"]*bb[\\"]*(?:\s|$|[\\";])'),
    BB_LIFECYCLE_PKILL,
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
_PGREP_RE_CASE = re.compile(r"case\b", re.I)
_PGREP_RE_ESAC = re.compile(r"esac\b", re.I)
_PGREP_RE_IN = re.compile(r"in\b", re.I)
_PGREP_RE_ONE_WORD = re.compile(r"[^\s\"';|&]+")
_PGREP_LEADING_ASSIGN = re.compile(
    r"(\w+)=(?:[^\s\"';|&]+|\"(?:\\.|[^\"\\])*\"|'[^']*')"
)
_PGREP_LEADING_ASSIGN_WS = re.compile(r"(\w+)=(?=\s)")
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



def _pgrep_data_heredoc_body_spans(text):
    return [
        (body_start, body_end)
        for body_start, body_end, executable, stdin_prog, literal in _pgrep_iter_heredoc_bodies(text)
        if not executable and not stdin_prog and literal
    ]


def _pgrep_nonexecutable_heredoc_body_spans(text):
    # Literal data heredoc bodies: delimiter quoted; body is not expanded.
    return [
        (body_start, body_end)
        for body_start, body_end, executable, stdin_prog, literal in _pgrep_iter_heredoc_bodies(text)
        if not executable and not stdin_prog and literal
    ]




def _pgrep_backtick_data_heredoc_body_spans(text):
    # Literal non-shell heredoc bodies: backticks are data, not command substitutions.
    return [
        (body_start, body_end)
        for body_start, body_end, executable, _stdin_prog, literal in _pgrep_iter_heredoc_bodies(text)
        if not executable and literal
    ]



def _pgrep_interpreter_stdin_heredoc_body_spans(text):
    return [
        (body_start, body_end)
        for body_start, body_end, executable, stdin_prog, _literal in _pgrep_iter_heredoc_bodies(text)
        if stdin_prog and not executable
    ]


def _pgrep_outer_scan_skip_heredoc_body_spans(text):
    data = _pgrep_nonexecutable_heredoc_body_spans(text)
    interp = _pgrep_interpreter_stdin_heredoc_body_spans(text)
    if not data:
        return interp
    if not interp:
        return data
    merged = data + interp
    merged.sort()
    return merged


def _pgrep_python_normalise_literal(val):
    if isinstance(val, bytes):
        return val.decode("latin-1")
    if isinstance(val, str):
        return val
    return None


def _pgrep_python_string_literal_has_replacements(tok_string):
    s = tok_string.lstrip("rRbBfFuU")
    if len(s) < 2:
        return False
    q = s[0]
    if q not in ('"', "'") or s[-1] != q:
        return False
    body = s[1:-1]
    i = 0
    while i < len(body):
        if body[i] == "{":
            j = i + 1
            while j < len(body) and body[j] != "}":
                j += 1
            if j < len(body):
                inner = body[i + 1 : j].strip()
                if inner or body[i : j + 1] != "{}":
                    return True
            i = j + 1 if j < len(body) else len(body)
        else:
            i += 1
    return False


def _pgrep_python_fstring_token_types():
    start = getattr(tokenize, "FSTRING_START", None)
    middle = getattr(tokenize, "FSTRING_MIDDLE", None)
    end = getattr(tokenize, "FSTRING_END", None)
    return start, middle, end


def _pgrep_python_read_plain_fstring(tokens, idx):
    fstart, fmid, fend = _pgrep_python_fstring_token_types()
    if fstart is None or tokens[idx].type != fstart:
        return None, idx
    parts = []
    idx += 1
    while idx < len(tokens):
        tok = tokens[idx]
        if tok.type == fmid:
            parts.append(tok.string)
            idx += 1
        elif tok.type == fend:
            idx += 1
            break
        else:
            return None, idx
    text = "".join(parts)
    if "{" in text and "}" in text:
        return None, idx
    return text, idx


def _pgrep_python_decode_string_token(tok_string):
    import ast

    if tok_string and tok_string[0] in "fF":
        if _pgrep_python_string_literal_has_replacements(tok_string):
            return None
    try:
        val = ast.literal_eval(tok_string)
    except Exception:
        if tok_string[:1] in "fFrRbBuU" or (
            len(tok_string) > 1 and tok_string[1:2] in "fFrRbBuU"
        ):
            return None
        val = tok_string.strip(chr(34) + chr(39))
    return _pgrep_python_normalise_literal(val)


def _pgrep_python_literal_at(tokens, idx):
    tok = tokens[idx]
    fstart, _fmid, _fend = _pgrep_python_fstring_token_types()
    if tok.type == tokenize.STRING:
        return _pgrep_python_decode_string_token(tok.string), idx + 1
    if fstart is not None and tok.type == fstart:
        return _pgrep_python_read_plain_fstring(tokens, idx)
    return None, idx + 1


_PGREP_PYTHON_EXEC_UNKNOWN = object()
_PGREP_PYTHON_SUBPROCESS_METHODS = frozenset(
    ("run", "call", "check_call", "check_output", "Popen")
)

_PGREP_PYTHON_ARGV_LAUNCHERS = frozenset(
    ("sudo", "env", "command", "exec", "nohup", "timeout", "nice")
)


def _pgrep_python_register_from_import_symbol(
    mod, imported, alias, subprocess_direct, os_system
):
    if mod == "subprocess" and imported in _PGREP_PYTHON_SUBPROCESS_METHODS:
        subprocess_direct[alias] = True
    elif mod == "os" and imported == "system":
        os_system.add(alias)


def _pgrep_python_read_from_import_symbol(tokens, idx, end_idx):
    if idx >= end_idx or tokens[idx].type != tokenize.NAME:
        return None, idx
    imported = tokens[idx].string
    alias = imported
    nxt = idx + 1
    if (
        nxt + 1 < end_idx
        and tokens[nxt].type == tokenize.NAME
        and tokens[nxt].string == "as"
        and tokens[nxt + 1].type == tokenize.NAME
    ):
        alias = tokens[nxt + 1].string
        return (imported, alias), nxt + 2
    return (imported, alias), idx + 1


def _pgrep_python_advance_from_import_list(
    tokens, idx, end_idx, mod, subprocess_direct, os_system
):
    if idx < end_idx and tokens[idx].type == tokenize.OP and tokens[idx].string == "(":
        idx += 1
        depth = 1
        while idx < end_idx and depth:
            tok = tokens[idx]
            if tok.type == tokenize.OP:
                if tok.string == "(":
                    depth += 1
                elif tok.string == ")":
                    depth -= 1
                    if depth == 0:
                        idx += 1
                        break
                idx += 1
                continue
            if tok.type == tokenize.NAME and depth == 1:
                sym, idx = _pgrep_python_read_from_import_symbol(tokens, idx, end_idx)
                if sym is not None:
                    imported, alias = sym
                    _pgrep_python_register_from_import_symbol(
                        mod, imported, alias, subprocess_direct, os_system
                    )
                continue
            if tok.type == tokenize.OP and tok.string == "," and depth == 1:
                idx += 1
                continue
            if tok.type == tokenize.OP and tok.string == ";":
                break
            idx += 1
        return idx
    while idx < end_idx and tokens[idx].type not in (
        tokenize.NEWLINE,
        tokenize.NL,
    ):
        if tokens[idx].type == tokenize.OP and tokens[idx].string == ";":
            break
        if tokens[idx].type == tokenize.NAME:
            sym, idx = _pgrep_python_read_from_import_symbol(tokens, idx, end_idx)
            if sym is not None:
                imported, alias = sym
                _pgrep_python_register_from_import_symbol(
                    mod, imported, alias, subprocess_direct, os_system
                )
            continue
        if tokens[idx].type == tokenize.OP and tokens[idx].string == ",":
            idx += 1
            continue
        break
    return idx


def _pgrep_python_argv_index_after_wrappers(elements, start=0):
    idx = start
    n = len(elements)
    while idx < n:
        el = elements[idx]
        if not isinstance(el, str):
            return idx
        base = el.rsplit("/", 1)[-1].lower()
        if base not in _PGREP_PYTHON_ARGV_LAUNCHERS:
            return idx
        idx += 1
        if base == "sudo":
            while (
                idx < n
                and isinstance(elements[idx], str)
                and elements[idx].startswith("-")
                and elements[idx] != "--"
            ):
                idx += 1
        elif base == "env":
            while idx < n and isinstance(elements[idx], str):
                w = elements[idx]
                if w.startswith("-"):
                    idx += 1
                    continue
                if "=" in w:
                    idx += 1
                    continue
                break
        elif base == "nice":
            while idx < n and isinstance(elements[idx], str) and elements[idx].startswith("-"):
                w = elements[idx]
                idx += 1
                if w == "-n" and idx < n:
                    idx += 1
        elif base == "timeout":
            while idx < n and isinstance(elements[idx], str) and elements[idx].startswith("-"):
                idx += 1
            if idx < n and isinstance(elements[idx], str):
                idx += 1
        elif base == "command":
            while idx < n and isinstance(elements[idx], str) and elements[idx].startswith("-"):
                idx += 1
    return idx


def _pgrep_python_is_pgrep_executable(argv0):

    if not isinstance(argv0, str):
        return False
    return argv0.rsplit("/", 1)[-1].lower() == "pgrep"


def _pgrep_python_collect_sequence_elements(tokens, start):
    if start >= len(tokens) or tokens[start].type != tokenize.OP:
        return None, start
    open_ch = tokens[start].string
    if open_ch not in ("[", "("):
        return None, start
    close_ch = "]" if open_ch == "[" else ")"
    idx = start + 1
    depth = 1
    elements = []
    fstart, _fmid, _fend = _pgrep_python_fstring_token_types()
    while idx < len(tokens) and depth:
        tok = tokens[idx]
        if tok.type == tokenize.OP and tok.string == open_ch:
            depth += 1
        elif tok.type == tokenize.OP and tok.string == close_ch:
            depth -= 1
            if depth == 0:
                idx += 1
                break
        elif depth == 1 and (
            tok.type == tokenize.STRING
            or (fstart is not None and tok.type == fstart)
        ):
            lit, idx = _pgrep_python_literal_at(tokens, idx)
            if lit is not None:
                elements.append(lit)
            continue
        idx += 1
    return elements, idx


def _pgrep_python_skip_value(tokens, idx):
    if idx >= len(tokens):
        return idx
    tok = tokens[idx]
    fstart, fmid, fend = _pgrep_python_fstring_token_types()
    if fstart is not None and tok.type == fstart:
        idx += 1
        while idx < len(tokens) and tokens[idx].type != fend:
            idx += 1
        return idx + 1 if idx < len(tokens) else idx
    if tok.type in (tokenize.STRING, tokenize.NAME, tokenize.NUMBER):
        return idx + 1
    if tok.type == tokenize.OP and tok.string in ("[", "(", "{"):
        open_ch = tok.string
        close = {"[": "]", "(": ")", "{": "}"}[open_ch]
        depth = 1
        idx += 1
        while idx < len(tokens) and depth:
            t = tokens[idx]
            if t.type == tokenize.OP and t.string == open_ch:
                depth += 1
            elif t.type == tokenize.OP and t.string == close:
                depth -= 1
            idx += 1
        return idx
    return idx + 1



def _pgrep_python_is_shell_program(program):
    if not isinstance(program, str):
        return False
    return program.rsplit("/", 1)[-1].lower() in _PGREP_SHELL_WORDS


def _pgrep_python_resolved_runner(executable_override, elements, shell_default=None):
    if executable_override is _PGREP_PYTHON_EXEC_UNKNOWN:
        return _PGREP_PYTHON_EXEC_UNKNOWN
    if executable_override is not None:
        return executable_override
    if shell_default is not None:
        return shell_default
    if elements:
        return elements[0]
    return None


def _pgrep_python_shell_cmd_blocks(runner, cmd_text):
    if runner is _PGREP_PYTHON_EXEC_UNKNOWN or not isinstance(runner, str):
        return False
    if not _pgrep_python_is_pgrep_executable(runner) and not _pgrep_python_is_shell_program(
        runner
    ):
        return False
    return _pgrep_python_shell_string_blocks(cmd_text)


def _pgrep_python_list_argv_blocks(elements, executable_override=None):
    if executable_override is _PGREP_PYTHON_EXEC_UNKNOWN:
        return False
    if not elements:
        return False
    scan_launcher_argv = executable_override is None or executable_override is _PGREP_PYTHON_EXEC_UNKNOWN
    if isinstance(executable_override, str):
        exec_base = executable_override.rsplit("/", 1)[-1].lower()
        scan_launcher_argv = (
            _pgrep_python_is_pgrep_executable(executable_override)
            or _pgrep_python_is_shell_program(executable_override)
            or exec_base in _PGREP_PYTHON_ARGV_LAUNCHERS
        )
    if scan_launcher_argv:
        pg_idx = _pgrep_python_argv_index_after_wrappers(elements, 0)
        if pg_idx < len(elements) and _pgrep_python_is_pgrep_executable(elements[pg_idx]):
            tail = elements[pg_idx:]
            if _pgrep_argv_tokens_has_full_flag(tail[1:]):
                return True
            return any(
                isinstance(el, str) and _pgrep_python_shell_string_blocks(el)
                for el in tail[1:]
            )
    runner = _pgrep_python_resolved_runner(executable_override, elements)

    if runner is _PGREP_PYTHON_EXEC_UNKNOWN or not isinstance(runner, str):
        return False
    if _pgrep_python_is_pgrep_executable(runner):
        if _pgrep_argv_tokens_has_full_flag(elements[1:]):
            return True
        return any(
            isinstance(el, str) and _pgrep_python_shell_string_blocks(el)
            for el in elements[1:]
        )
    if _pgrep_python_is_shell_program(runner):
        return _pgrep_python_list_shell_invoke_blocks(elements)
    return False


def _pgrep_python_shell_string_blocks(snippet):
    if not snippet or not isinstance(snippet, str):
        return False
    folded = pgrep_obfuscation_fold(_pgrep_mask_shell_comments(snippet))
    if PGREP_WORD.search(folded):
        seg = re.match(r"[^\n;&|]*", folded.lstrip())
        if seg and (
            pgrep_segment_has_full_flag(seg.group(0))
            or _pgrep_lifecycle_pkill_match(snippet)
        ):
            return True
    return bool(_pgrep_lifecycle_pkill_match(snippet))


def _pgrep_python_call_executable_override(tokens, open_paren_idx):
    idx = open_paren_idx + 1
    paren_depth = 1
    while idx < len(tokens) and paren_depth:
        tok = tokens[idx]
        if tok.type == tokenize.OP and tok.string == "(":
            paren_depth += 1
        elif tok.type == tokenize.OP and tok.string == ")":
            paren_depth -= 1
            if paren_depth == 0:
                break
        elif (
            paren_depth == 1
            and tok.type == tokenize.NAME
            and tok.string == "executable"
            and idx + 2 < len(tokens)
            and tokens[idx + 1].type == tokenize.OP
            and tokens[idx + 1].string == "="
        ):
            val = tokens[idx + 2]
            if val.type == tokenize.STRING:
                return _pgrep_python_decode_string_token(val.string)
            if val.type == tokenize.NAME and val.string == "None":
                return None
            return _PGREP_PYTHON_EXEC_UNKNOWN
        idx += 1
    return None


def _pgrep_python_call_has_kwargs_star(tokens, open_paren_idx):
    idx = open_paren_idx + 1
    paren_depth = 1
    while idx < len(tokens) and paren_depth:
        tok = tokens[idx]
        if tok.type == tokenize.OP and tok.string == "(":
            paren_depth += 1
        elif tok.type == tokenize.OP and tok.string == ")":
            paren_depth -= 1
        elif paren_depth == 1 and tok.type == tokenize.OP and tok.string == "**":
            return True
        idx += 1
    return False


def _pgrep_python_call_has_args_star(tokens, open_paren_idx):
    idx = open_paren_idx + 1
    paren_depth = 1
    while idx < len(tokens) and paren_depth:
        tok = tokens[idx]
        if tok.type == tokenize.OP and tok.string == "(":
            paren_depth += 1
        elif tok.type == tokenize.OP and tok.string == ")":
            paren_depth -= 1
        elif paren_depth == 1 and tok.type == tokenize.OP and tok.string == "*":
            return True
        idx += 1
    return False


def _pgrep_python_skip_positional_value(tokens, idx):
    if idx >= len(tokens):
        return idx
    tok = tokens[idx]
    if (
        tok.type == tokenize.OP
        and tok.string == "-"
        and idx + 1 < len(tokens)
        and tokens[idx + 1].type == tokenize.NUMBER
    ):
        return idx + 2
    return _pgrep_python_skip_value(tokens, idx)


def _pgrep_python_positional_program_value(tokens, idx):
    if idx >= len(tokens):
        return _PGREP_PYTHON_EXEC_UNKNOWN
    tok = tokens[idx]
    fstart, _fmid, _fend = _pgrep_python_fstring_token_types()
    if tok.type == tokenize.STRING:
        return _pgrep_python_decode_string_token(tok.string)
    if fstart is not None and tok.type == fstart:
        lit, _end = _pgrep_python_literal_at(tokens, idx)
        if lit is None or not isinstance(lit, str):
            return _PGREP_PYTHON_EXEC_UNKNOWN
        return lit
    if tok.type == tokenize.NAME:
        if tok.string == "None":
            return None
        return _PGREP_PYTHON_EXEC_UNKNOWN
    return _PGREP_PYTHON_EXEC_UNKNOWN


def _pgrep_python_popen_style_positional_executable(tokens, open_paren_idx):
    idx = open_paren_idx + 1
    paren_depth = 1
    positionals = []
    while idx < len(tokens) and paren_depth:
        tok = tokens[idx]
        if tok.type == tokenize.OP and tok.string == "(":
            paren_depth += 1
        elif tok.type == tokenize.OP and tok.string == ")":
            paren_depth -= 1
            if paren_depth == 0:
                break
        elif paren_depth == 1:
            if tok.type == tokenize.OP and tok.string == ",":
                idx += 1
                continue
            if tok.type == tokenize.OP and tok.string == "*":
                return _PGREP_PYTHON_EXEC_UNKNOWN
            if (
                tok.type == tokenize.NAME
                and idx + 2 < len(tokens)
                and tokens[idx + 1].type == tokenize.OP
                and tokens[idx + 1].string == "="
            ):
                break
            val_idx = idx
            positionals.append(val_idx)
            idx = _pgrep_python_skip_positional_value(tokens, val_idx) - 1
        idx += 1
    if len(positionals) < 3:
        return None
    return _pgrep_python_positional_program_value(tokens, positionals[2])


def _pgrep_python_subprocess_executable_override(tokens, open_paren_idx):
    kw = _pgrep_python_call_executable_override(tokens, open_paren_idx)
    if kw is not None:
        return kw
    return _pgrep_python_popen_style_positional_executable(tokens, open_paren_idx)


def _pgrep_python_call_has_shell_true(tokens, open_paren_idx):
    idx = open_paren_idx + 1
    paren_depth = 1
    while idx < len(tokens) and paren_depth:
        tok = tokens[idx]
        if tok.type == tokenize.OP and tok.string == "(":
            paren_depth += 1
        elif tok.type == tokenize.OP and tok.string == ")":
            paren_depth -= 1
            if paren_depth == 0:
                break
        elif (
            paren_depth == 1
            and tok.type == tokenize.NAME
            and tok.string == "shell"
            and idx + 2 < len(tokens)
            and tokens[idx + 1].type == tokenize.OP
            and tokens[idx + 1].string == "="
            and tokens[idx + 2].type == tokenize.NAME
            and tokens[idx + 2].string == "True"
        ):
            return True
        idx += 1
    return False


def _pgrep_python_scan_args_keyword_value(tokens, idx, shell_true, executable_override=None):
    if idx >= len(tokens):
        return False
    tok = tokens[idx]
    if tok.type == tokenize.OP and tok.string in ("[", "("):
        elements, _end = _pgrep_python_collect_sequence_elements(tokens, idx)
        if (
            shell_true
            and elements
            and _pgrep_python_list_argv_blocks_shell_true(
                elements, executable_override
            )
        ):
            return True
        return bool(
            elements
            and _pgrep_python_list_argv_blocks(elements, executable_override)
        )
    fstart, _fmid, _fend = _pgrep_python_fstring_token_types()
    if shell_true and (
        tok.type == tokenize.STRING
        or (fstart is not None and tok.type == fstart)
    ):
        lit, _end = _pgrep_python_literal_at(tokens, idx)
        if lit is None:
            return False
        runner = _pgrep_python_resolved_runner(
            executable_override, None, shell_default="/bin/sh" if shell_true else None
        )
        return _pgrep_python_shell_cmd_blocks(runner, lit)
    return False


def _pgrep_python_call_args_block(
    tokens,
    open_paren_idx,
    string_is_shell=False,
    popen_style=False,
    exec_style=False,
):
    idx = open_paren_idx + 1
    paren_depth = 1
    saw_positional = False
    shell_true = _pgrep_python_call_has_shell_true(tokens, open_paren_idx)
    kwargs_unknown = _pgrep_python_call_has_kwargs_star(tokens, open_paren_idx)
    args_unknown = popen_style and _pgrep_python_call_has_args_star(
        tokens, open_paren_idx
    )
    program_unknown = kwargs_unknown or args_unknown
    if popen_style:
        executable_override = _pgrep_python_subprocess_executable_override(
            tokens, open_paren_idx
        )
    else:
        executable_override = _pgrep_python_call_executable_override(
            tokens, open_paren_idx
        )
    if program_unknown:
        executable_override = _PGREP_PYTHON_EXEC_UNKNOWN
    fstart, _fmid, _fend = _pgrep_python_fstring_token_types()
    if exec_style:
        return _pgrep_python_exec_call_blocks(tokens, open_paren_idx)
    while idx < len(tokens) and paren_depth:
        tok = tokens[idx]
        if tok.type == tokenize.OP and tok.string == "(":
            paren_depth += 1
        elif tok.type == tokenize.OP and tok.string == ")":
            paren_depth -= 1
            if paren_depth == 0:
                break
        elif paren_depth == 1:
            if (
                tok.type == tokenize.NAME
                and idx + 2 < len(tokens)
                and tokens[idx + 1].type == tokenize.OP
                and tokens[idx + 1].string == "="
            ):
                kw = tok.string
                val_idx = idx + 2
                if (
                    kw == "args"
                    and not program_unknown
                    and _pgrep_python_scan_args_keyword_value(
                        tokens, val_idx, shell_true, executable_override
                    )
                ):
                    return True
                idx = _pgrep_python_skip_value(tokens, val_idx) - 1
            elif tok.type == tokenize.STRING or (
                fstart is not None and tok.type == fstart
            ):
                if not saw_positional:
                    saw_positional = True
                    if string_is_shell or shell_true:
                        lit, idx = _pgrep_python_literal_at(tokens, idx)
                        if lit is not None:
                            if string_is_shell and not shell_true:
                                if _pgrep_python_shell_string_blocks(lit):
                                    return True
                            else:
                                runner = _pgrep_python_resolved_runner(
                                    executable_override,
                                    None,
                                    shell_default="/bin/sh" if shell_true else None,
                                )
                                if _pgrep_python_shell_cmd_blocks(runner, lit):
                                    return True
                        continue
            elif tok.type == tokenize.OP and tok.string in ("[", "("):
                elements, idx = _pgrep_python_collect_sequence_elements(
                    tokens, idx
                )
                if (
                    shell_true
                    and not program_unknown
                    and elements
                    and _pgrep_python_list_argv_blocks_shell_true(
                        elements, executable_override
                    )
                ):
                    return True
                if (
                    not program_unknown
                    and elements
                    and _pgrep_python_list_argv_blocks(
                        elements, executable_override
                    )
                ):
                    return True
                if not saw_positional:
                    saw_positional = True
                continue
            elif tok.type == tokenize.NAME:
                saw_positional = True
        idx += 1
    return False





def _pgrep_python_shell_true_argv0_blocks(runner, cmd_text):
    if runner is _PGREP_PYTHON_EXEC_UNKNOWN or not isinstance(runner, str):
        return False
    if not isinstance(cmd_text, str):
        return False
    if _pgrep_python_is_pgrep_executable(runner):
        return _pgrep_python_shell_string_blocks(cmd_text)
    if not _pgrep_python_is_shell_program(runner):
        return False
    masked = _pgrep_mask_shell_comments(cmd_text.strip())
    folded = pgrep_obfuscation_fold(masked)
    launch_at = _pgrep_skip_assignments_and_wrappers(folded, 0, len(folded))
    folded = folded[launch_at:]
    if not folded.strip():
        return _pgrep_python_shell_string_blocks(cmd_text)
    m = re.match(r"\s*(\S+)", folded)
    if not m:
        return False
    head = m.group(1).rsplit("/", 1)[-1].lower()
    if head in (
        "echo",
        "printf",
        "print",
        "cat",
        "grep",
        "egrep",
        "fgrep",
        "tee",
        "sort",
        "wc",
        "test",
        "true",
        "false",
    ):
        return False
    if head == "pkill" or head.endswith("pkill"):
        return _pgrep_lifecycle_pkill_match(cmd_text)
    if head == "pgrep" or head.endswith("pgrep"):
        seg = re.match(r"[^\n;&|]*", folded.lstrip())
        if seg and pgrep_segment_has_full_flag(seg.group(0)):
            return True
        return bool(_pgrep_lifecycle_pkill_match(cmd_text))
    return False


def _pgrep_python_list_argv_blocks_shell_true(elements, executable_override=None):
    if executable_override is _PGREP_PYTHON_EXEC_UNKNOWN:
        return False
    if not elements:
        return False
    runner = _pgrep_python_resolved_runner(
        executable_override, None, shell_default="/bin/sh"
    )
    if runner is _PGREP_PYTHON_EXEC_UNKNOWN or not isinstance(runner, str):
        return False
    first = elements[0]
    if isinstance(first, str):
        return _pgrep_python_shell_true_argv0_blocks(runner, first)
    return False


def _pgrep_python_drop_import_binding(subprocess_direct, os_system, name):
    subprocess_direct.pop(name, None)
    os_system.discard(name)


def _pgrep_python_bindings_at(tokens, before_idx):
    subprocess_aliases = {"subprocess"}
    subprocess_direct = {}
    os_system = set()
    idx = 0
    while idx < before_idx:
        tok = tokens[idx]
        if tok.type == tokenize.NAME and tok.string == "from" and idx + 3 < before_idx:
            mod_tok = tokens[idx + 1]
            kw_tok = tokens[idx + 2]
            if (
                mod_tok.type == tokenize.NAME
                and kw_tok.type == tokenize.NAME
                and kw_tok.string == "import"
            ):
                mod = mod_tok.string
                if mod in ("subprocess", "os"):
                    idx += 3
                    idx = _pgrep_python_advance_from_import_list(
                        tokens, idx, before_idx, mod, subprocess_direct, os_system
                    )
                    continue
        if tok.type == tokenize.NAME and tok.string == "import":
            idx += 1
            while idx < before_idx and tokens[idx].type not in (
                tokenize.NEWLINE,
                tokenize.NL,
            ):
                if tokens[idx].type == tokenize.NAME and tokens[idx].string == "subprocess":
                    j = idx + 1
                    if (
                        j + 1 < len(tokens)
                        and tokens[j].type == tokenize.NAME
                        and tokens[j].string == "as"
                        and tokens[j + 1].type == tokenize.NAME
                    ):
                        subprocess_aliases.add(tokens[j + 1].string)
                idx += 1
            continue
        if tok.type == tokenize.NAME and tok.string in ("def", "class"):
            if idx + 1 < before_idx and tokens[idx + 1].type == tokenize.NAME:
                _pgrep_python_drop_import_binding(
                    subprocess_direct, os_system, tokens[idx + 1].string
                )
        elif (
            tok.type == tokenize.NAME
            and idx + 1 < before_idx
            and tokens[idx + 1].type == tokenize.OP
            and tokens[idx + 1].string == "="
            and tok.string not in ("if", "elif", "for", "while")
            and not (
                idx > 0
                and tokens[idx - 1].type == tokenize.OP
                and tokens[idx - 1].string == ":"
            )
        ):
            _pgrep_python_drop_import_binding(subprocess_direct, os_system, tok.string)
        idx += 1
    return subprocess_aliases, subprocess_direct, os_system




def _pgrep_python_bindings_advance_to(
    tokens,
    cursor,
    end_idx,
    subprocess_aliases,
    subprocess_direct,
    os_system,
):
    idx = cursor
    while idx < end_idx:
        tok = tokens[idx]
        if tok.type == tokenize.NAME and tok.string == "from" and idx + 3 < end_idx:
            mod_tok = tokens[idx + 1]
            kw_tok = tokens[idx + 2]
            if (
                mod_tok.type == tokenize.NAME
                and kw_tok.type == tokenize.NAME
                and kw_tok.string == "import"
            ):
                mod = mod_tok.string
                if mod in ("subprocess", "os"):
                    idx += 3
                    idx = _pgrep_python_advance_from_import_list(
                        tokens, idx, end_idx, mod, subprocess_direct, os_system
                    )
                    continue
        if tok.type == tokenize.NAME and tok.string == "import":
            idx += 1
            while idx < end_idx and tokens[idx].type not in (
                tokenize.NEWLINE,
                tokenize.NL,
            ):
                if tokens[idx].type == tokenize.NAME and tokens[idx].string == "subprocess":
                    j = idx + 1
                    if (
                        j + 1 < len(tokens)
                        and tokens[j].type == tokenize.NAME
                        and tokens[j].string == "as"
                        and tokens[j + 1].type == tokenize.NAME
                    ):
                        subprocess_aliases.add(tokens[j + 1].string)
                idx += 1
            continue
        if tok.type == tokenize.NAME and tok.string in ("def", "class"):
            if idx + 1 < end_idx and tokens[idx + 1].type == tokenize.NAME:
                _pgrep_python_drop_import_binding(
                    subprocess_direct, os_system, tokens[idx + 1].string
                )
        elif (
            tok.type == tokenize.NAME
            and idx + 1 < end_idx
            and tokens[idx + 1].type == tokenize.OP
            and tokens[idx + 1].string == "="
            and tok.string not in ("if", "elif", "for", "while")
            and not (
                idx > 0
                and tokens[idx - 1].type == tokenize.OP
                and tokens[idx - 1].string == ":"
            )
        ):
            _pgrep_python_drop_import_binding(subprocess_direct, os_system, tok.string)
        idx += 1
    return idx


def _pgrep_python_shadowed_import_name(shadow_stack, inline_shadow, comp_stack, name):
    if name in inline_shadow:
        return True
    for layer in comp_stack:
        if name in layer:
            return True
    for layer in shadow_stack:
        if name in layer:
            return True
    return False


def _pgrep_python_def_parameter_names(tokens, def_idx):
    idx = def_idx + 1
    while idx < len(tokens) and tokens[idx].type != tokenize.NAME:
        idx += 1
    if idx >= len(tokens):
        return set()
    idx += 1
    while idx < len(tokens) and not (
        tokens[idx].type == tokenize.OP and tokens[idx].string == "("
    ):
        idx += 1
    if idx >= len(tokens):
        return set()
    idx += 1
    depth = 1
    names = set()
    while idx < len(tokens) and depth:
        t = tokens[idx]
        if t.type == tokenize.OP:
            if t.string == "(":
                depth += 1
            elif t.string == ")":
                depth -= 1
            elif t.string == ":" and depth == 1:
                idx += 1
                while idx < len(tokens) and depth:
                    tt = tokens[idx]
                    if tt.type == tokenize.OP:
                        if tt.string == "(":
                            depth += 1
                        elif tt.string == ")":
                            depth -= 1
                            if depth == 1:
                                idx += 1
                                break
                        elif tt.string == "," and depth == 1:
                            break
                    idx += 1
                continue
        elif t.type == tokenize.NAME and depth == 1:
            if t.string not in ("True", "False", "None"):
                names.add(t.string)
        idx += 1
    return names


def _pgrep_python_lambda_parameter_names(tokens, lambda_idx):
    idx = lambda_idx + 1
    depth = 0
    names = set()
    while idx < len(tokens):
        t = tokens[idx]
        if t.type == tokenize.OP and t.string == "(":
            depth += 1
            idx += 1
            continue
        if t.type == tokenize.OP and t.string == ")":
            if depth:
                depth -= 1
                idx += 1
                continue
        if t.type == tokenize.OP and t.string == ":" and not depth:
            break
        if t.type == tokenize.NAME and (depth or not names):
            if t.string not in ("True", "False", "None", "lambda"):
                names.add(t.string)
        idx += 1
    return names




def _pgrep_python_stdin_body_worth_scanning(body):
    masked = _pgrep_mask_shell_comments(body)
    folded = pgrep_obfuscation_fold(masked)
    if PGREP_WORD.search(folded):
        return True
    if re.search(r"\bpkill\b", folded, re.I):
        return True
    return False


def _pgrep_python_comprehension_for_bind_names(tokens, idx):
    j = idx + 1
    names = []
    while j < len(tokens):
        if tokens[j].type == tokenize.NAME:
            names.append(tokens[j].string)
            j += 1
            if j < len(tokens) and tokens[j].type == tokenize.OP and tokens[j].string == ",":
                j += 1
                continue
            break
        break
    if (
        len(names) >= 1
        and j < len(tokens)
        and tokens[j].type == tokenize.NAME
        and tokens[j].string == "in"
    ):
        return names
    return None


def _pgrep_python_comprehension_shadow_by_index(tokens):
    frames = []
    frame_at = []
    stack = []
    for idx, tok in enumerate(tokens):
        if tok.type == tokenize.OP and tok.string in ("[", "(", "{"):
            parent = stack[-1] if stack else None
            fid = len(frames)
            frames.append({"parent": parent, "names": set()})
            stack.append(fid)
        frame_at.append(stack[-1] if stack else -1)
        if tok.type == tokenize.OP and tok.string in ("]", ")", "}"):
            if stack:
                stack.pop()
        elif stack and tok.type == tokenize.NAME and tok.string == "for":
            bound = _pgrep_python_comprehension_for_bind_names(tokens, idx)
            if bound is not None:
                frames[stack[-1]]["names"].update(bound)
    return frames, frame_at


def _pgrep_python_comprehension_shadows_name(frames, frame_at, idx, name):
    fid = frame_at[idx]
    while fid is not None and fid >= 0:
        if name in frames[fid]["names"]:
            return True
        fid = frames[fid]["parent"]
    return False


def _pgrep_python_shadowed_import_name_at(
    shadow_stack, inline_shadow, comp_frames, comp_frame_at, idx, name
):
    if name in inline_shadow:
        return True
    if _pgrep_python_comprehension_shadows_name(
        comp_frames, comp_frame_at, idx, name
    ):
        return True
    for layer in shadow_stack:
        if name in layer:
            return True
    return False


def _pgrep_python_comprehension_for_names(tokens, open_idx):
    names = set()
    depth = 0
    idx = open_idx
    while idx < len(tokens):
        t = tokens[idx]
        if t.type == tokenize.OP and t.string == "[":
            depth += 1
        elif t.type == tokenize.OP and t.string == "]":
            depth -= 1
            if depth == 0:
                break
        if (
            depth >= 1
            and t.type == tokenize.NAME
            and t.string == "for"
            and idx + 2 < len(tokens)
            and tokens[idx + 1].type == tokenize.NAME
            and tokens[idx + 2].type == tokenize.NAME
            and tokens[idx + 2].string == "in"
        ):
            names.add(tokens[idx + 1].string)
        idx += 1
    return names


def _pgrep_python_stdin_shell_invoke_one_pass_v3(tokens):
    _SUBPROCESS_METHODS = frozenset(
        ("run", "call", "check_call", "check_output", "Popen")
    )
    subprocess_aliases = {"subprocess"}
    subprocess_direct = {}
    os_system = set()
    shadow_stack = []
    inline_shadow = set()
    comp_stack = []
    pending_scope_params = None
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok.type == tokenize.INDENT:
            shadow_stack.append(set(pending_scope_params or ()))
            pending_scope_params = None
            idx += 1
            continue
        if tok.type == tokenize.DEDENT:
            if shadow_stack:
                shadow_stack.pop()
            idx += 1
            continue
        if tok.type == tokenize.OP and tok.string == "[":
            comp_stack.append(_pgrep_python_comprehension_for_names(tokens, idx))
        elif tok.type == tokenize.OP and tok.string == "]" and comp_stack:
            comp_stack.pop()
        if tok.type == tokenize.NAME and tok.string == "from" and idx + 3 < len(tokens):
            mod_tok = tokens[idx + 1]
            kw_tok = tokens[idx + 2]
            if (
                mod_tok.type == tokenize.NAME
                and kw_tok.type == tokenize.NAME
                and kw_tok.string == "import"
            ):
                mod = mod_tok.string
                if mod in ("subprocess", "os"):
                    idx += 3
                    idx = _pgrep_python_advance_from_import_list(
                        tokens, idx, len(tokens), mod, subprocess_direct, os_system
                    )
                    continue
        if tok.type == tokenize.NAME and tok.string == "import":
            idx += 1
            while idx < len(tokens) and tokens[idx].type not in (
                tokenize.NEWLINE,
                tokenize.NL,
            ):
                if tokens[idx].type == tokenize.OP and tokens[idx].string == ";":
                    break
                if tokens[idx].type == tokenize.NAME and tokens[idx].string == "subprocess":
                    j = idx + 1
                    if (
                        j + 1 < len(tokens)
                        and tokens[j].type == tokenize.NAME
                        and tokens[j].string == "as"
                        and tokens[j + 1].type == tokenize.NAME
                    ):
                        subprocess_aliases.add(tokens[j + 1].string)
                idx += 1
            continue
        if tok.type == tokenize.NAME and tok.string == "def":
            pending_scope_params = _pgrep_python_def_parameter_names(tokens, idx)
        elif tok.type == tokenize.NAME and tok.string == "lambda":
            pending_scope_params = _pgrep_python_lambda_parameter_names(tokens, idx)
        elif tok.type == tokenize.NAME and tok.string == "for" and idx + 3 < len(tokens):
            if (
                tokens[idx + 1].type == tokenize.NAME
                and tokens[idx + 2].type == tokenize.NAME
                and tokens[idx + 2].string == "in"
            ):
                pending_scope_params = {tokens[idx + 1].string}
        elif (
            tok.type == tokenize.NAME
            and tok.string == "as"
            and idx + 1 < len(tokens)
            and tokens[idx + 1].type == tokenize.NAME
        ):
            pending_scope_params = {tokens[idx + 1].string}
        elif tok.type == tokenize.OP and tok.string == ":" and pending_scope_params is not None:
            nxt = idx + 1
            while nxt < len(tokens) and tokens[nxt].type in (tokenize.NL, tokenize.NEWLINE):
                nxt += 1
            if nxt < len(tokens) and tokens[nxt].type != tokenize.INDENT:
                inline_shadow = set(pending_scope_params)
                pending_scope_params = None
        elif tok.type in (tokenize.NEWLINE, tokenize.NL):
            inline_shadow = set()
        if tok.type == tokenize.NAME and tok.string in ("def", "class"):
            if idx + 1 < len(tokens) and tokens[idx + 1].type == tokenize.NAME:
                _pgrep_python_drop_import_binding(
                    subprocess_direct, os_system, tokens[idx + 1].string
                )
        elif (
            tok.type == tokenize.NAME
            and idx + 1 < len(tokens)
            and tokens[idx + 1].type == tokenize.OP
            and tokens[idx + 1].string == "="
            and tok.string not in ("if", "elif", "for", "while")
            and not (
                idx > 0
                and tokens[idx - 1].type == tokenize.OP
                and tokens[idx - 1].string == ":"
            )
        ):
            _pgrep_python_drop_import_binding(subprocess_direct, os_system, tok.string)
        tok = tokens[idx]
        if (
            tok.type == tokenize.NAME
            and tok.string in os_system
            and not _pgrep_python_shadowed_import_name(
                shadow_stack, inline_shadow, comp_stack, tok.string
            )
            and idx + 1 < len(tokens)
            and tokens[idx + 1].type == tokenize.OP
            and tokens[idx + 1].string == "("
            and _pgrep_python_call_args_block(
                tokens, idx + 1, string_is_shell=True
            )
        ):
            return True
        if (
            tok.type == tokenize.NAME
            and tok.string in subprocess_direct
            and not _pgrep_python_shadowed_import_name(
                shadow_stack, inline_shadow, comp_stack, tok.string
            )
            and idx + 1 < len(tokens)
            and tokens[idx + 1].type == tokenize.OP
            and tokens[idx + 1].string == "("
            and _pgrep_python_call_args_block(tokens, idx + 1, popen_style=True)
        ):
            return True
        if (
            tok.type == tokenize.NAME
            and tok.string == "os"
            and idx + 2 < len(tokens)
            and tokens[idx + 1].type == tokenize.OP
            and tokens[idx + 1].string == "."
            and tokens[idx + 2].type == tokenize.NAME
        ):
            meth = tokens[idx + 2].string
            if meth in ("system", "popen"):
                args_start = idx + 3
                if (
                    args_start < len(tokens)
                    and tokens[args_start].type == tokenize.OP
                    and tokens[args_start].string == "("
                    and _pgrep_python_call_args_block(
                        tokens, args_start, string_is_shell=True
                    )
                ):
                    return True
            if meth.startswith("exec") or meth.startswith("spawn"):
                args_start = idx + 3
                if (
                    args_start < len(tokens)
                    and tokens[args_start].type == tokenize.OP
                    and tokens[args_start].string == "("
                    and _pgrep_python_call_args_block(
                        tokens, args_start, exec_style=True
                    )
                ):
                    return True
        if tok.type == tokenize.NAME and tok.string in subprocess_aliases:
            j = idx + 1
            while j + 1 < len(tokens):
                if tokens[j].type != tokenize.OP or tokens[j].string != ".":
                    break
                if tokens[j + 1].type != tokenize.NAME:
                    break
                meth = tokens[j + 1].string
                if meth not in _SUBPROCESS_METHODS:
                    j += 2
                    continue
                args_start = j + 2
                if (
                    args_start < len(tokens)
                    and tokens[args_start].type == tokenize.OP
                    and tokens[args_start].string == "("
                    and _pgrep_python_call_args_block(
                        tokens, args_start, popen_style=True
                    )
                ):
                    return True
                break
        idx += 1
    return False

def _pgrep_python_stdin_shell_invoke_one_pass_v4(tokens):
    _SUBPROCESS_METHODS = frozenset(
        ("run", "call", "check_call", "check_output", "Popen")
    )
    subprocess_aliases = {"subprocess"}
    subprocess_direct = {}
    os_system = set()
    shadow_stack = []
    inline_shadow = set()
    comp_frames, comp_frame_at = _pgrep_python_comprehension_shadow_by_index(tokens)
    pending_scope_params = None
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok.type == tokenize.INDENT:
            shadow_stack.append(set(pending_scope_params or ()))
            pending_scope_params = None
            idx += 1
            continue
        if tok.type == tokenize.DEDENT:
            if shadow_stack:
                shadow_stack.pop()
            idx += 1
            continue
        if tok.type == tokenize.NAME and tok.string == "from" and idx + 3 < len(tokens):
            mod_tok = tokens[idx + 1]
            kw_tok = tokens[idx + 2]
            if (
                mod_tok.type == tokenize.NAME
                and kw_tok.type == tokenize.NAME
                and kw_tok.string == "import"
            ):
                mod = mod_tok.string
                if mod in ("subprocess", "os"):
                    idx += 3
                    idx = _pgrep_python_advance_from_import_list(
                        tokens, idx, len(tokens), mod, subprocess_direct, os_system
                    )
                    continue
        if tok.type == tokenize.NAME and tok.string == "import":
            idx += 1
            while idx < len(tokens) and tokens[idx].type not in (
                tokenize.NEWLINE,
                tokenize.NL,
            ):
                if tokens[idx].type == tokenize.OP and tokens[idx].string == ";":
                    break
                if tokens[idx].type == tokenize.NAME and tokens[idx].string == "subprocess":
                    j = idx + 1
                    if (
                        j + 1 < len(tokens)
                        and tokens[j].type == tokenize.NAME
                        and tokens[j].string == "as"
                        and tokens[j + 1].type == tokenize.NAME
                    ):
                        subprocess_aliases.add(tokens[j + 1].string)
                idx += 1
            continue
        if tok.type == tokenize.NAME and tok.string == "def":
            pending_scope_params = _pgrep_python_def_parameter_names(tokens, idx)
        elif tok.type == tokenize.NAME and tok.string == "lambda":
            pending_scope_params = _pgrep_python_lambda_parameter_names(tokens, idx)
        elif tok.type == tokenize.NAME and tok.string == "for" and idx + 3 < len(tokens):
            if (
                tokens[idx + 1].type == tokenize.NAME
                and tokens[idx + 2].type == tokenize.NAME
                and tokens[idx + 2].string == "in"
            ):
                pending_scope_params = {tokens[idx + 1].string}
        elif (
            tok.type == tokenize.NAME
            and tok.string == "as"
            and idx + 1 < len(tokens)
            and tokens[idx + 1].type == tokenize.NAME
        ):
            pending_scope_params = {tokens[idx + 1].string}
        elif tok.type == tokenize.OP and tok.string == ":" and pending_scope_params is not None:
            nxt = idx + 1
            while nxt < len(tokens) and tokens[nxt].type in (tokenize.NL, tokenize.NEWLINE):
                nxt += 1
            if nxt < len(tokens) and tokens[nxt].type != tokenize.INDENT:
                inline_shadow = set(pending_scope_params)
                pending_scope_params = None
        elif tok.type in (tokenize.NEWLINE, tokenize.NL):
            inline_shadow = set()
        if tok.type == tokenize.NAME and tok.string in ("def", "class"):
            if idx + 1 < len(tokens) and tokens[idx + 1].type == tokenize.NAME:
                _pgrep_python_drop_import_binding(
                    subprocess_direct, os_system, tokens[idx + 1].string
                )
        elif (
            tok.type == tokenize.NAME
            and idx + 1 < len(tokens)
            and tokens[idx + 1].type == tokenize.OP
            and tokens[idx + 1].string == "="
            and tok.string not in ("if", "elif", "for", "while")
            and not (
                idx > 0
                and tokens[idx - 1].type == tokenize.OP
                and tokens[idx - 1].string == ":"
            )
        ):
            _pgrep_python_drop_import_binding(subprocess_direct, os_system, tok.string)
        tok = tokens[idx]
        if (
            tok.type == tokenize.NAME
            and tok.string in os_system
            and not _pgrep_python_shadowed_import_name_at(
                shadow_stack,
                inline_shadow,
                comp_frames,
                comp_frame_at,
                idx,
                tok.string,
            )
            and idx + 1 < len(tokens)
            and tokens[idx + 1].type == tokenize.OP
            and tokens[idx + 1].string == "("
            and _pgrep_python_call_args_block(
                tokens, idx + 1, string_is_shell=True
            )
        ):
            return True
        if (
            tok.type == tokenize.NAME
            and tok.string in subprocess_direct
            and not _pgrep_python_shadowed_import_name_at(
                shadow_stack,
                inline_shadow,
                comp_frames,
                comp_frame_at,
                idx,
                tok.string,
            )
            and idx + 1 < len(tokens)
            and tokens[idx + 1].type == tokenize.OP
            and tokens[idx + 1].string == "("
            and _pgrep_python_call_args_block(tokens, idx + 1, popen_style=True)
        ):
            return True
        if (
            tok.type == tokenize.NAME
            and tok.string == "os"
            and idx + 2 < len(tokens)
            and tokens[idx + 1].type == tokenize.OP
            and tokens[idx + 1].string == "."
            and tokens[idx + 2].type == tokenize.NAME
        ):
            meth = tokens[idx + 2].string
            if meth in ("system", "popen"):
                args_start = idx + 3
                if (
                    args_start < len(tokens)
                    and tokens[args_start].type == tokenize.OP
                    and tokens[args_start].string == "("
                    and _pgrep_python_call_args_block(
                        tokens, args_start, string_is_shell=True
                    )
                ):
                    return True
            if meth.startswith("exec") or meth.startswith("spawn"):
                args_start = idx + 3
                if (
                    args_start < len(tokens)
                    and tokens[args_start].type == tokenize.OP
                    and tokens[args_start].string == "("
                    and _pgrep_python_call_args_block(
                        tokens, args_start, exec_style=True
                    )
                ):
                    return True
        if tok.type == tokenize.NAME and tok.string in subprocess_aliases:
            j = idx + 1
            while j + 1 < len(tokens):
                if tokens[j].type != tokenize.OP or tokens[j].string != ".":
                    break
                if tokens[j + 1].type != tokenize.NAME:
                    break
                meth = tokens[j + 1].string
                if meth not in _SUBPROCESS_METHODS:
                    j += 2
                    continue
                args_start = j + 2
                if (
                    args_start < len(tokens)
                    and tokens[args_start].type == tokenize.OP
                    and tokens[args_start].string == "("
                    and _pgrep_python_call_args_block(
                        tokens, args_start, popen_style=True
                    )
                ):
                    return True
                break
        idx += 1
    return False


def _pgrep_python_stdin_shell_invoke(body):
    from io import BytesIO

    try:
        tokens = list(
            tokenize.tokenize(
                BytesIO(body.encode("utf-8", "surrogateescape")).readline
            )
        )
    except (tokenize.TokenError, SyntaxError, UnicodeError):
        return False

    if not _pgrep_python_stdin_body_worth_scanning(body):
        return False
    try:
        return _pgrep_python_stdin_shell_invoke_one_pass_v4(tokens)
    except Exception:
        return _pgrep_python_stdin_shell_invoke_one_pass_v3(tokens)

def _pgrep_python_list_shell_invoke_blocks(elements):
    if len(elements) < 2:
        return False
    i = 0
    while i < len(elements):
        el = elements[i]
        if el == "-c" or (isinstance(el, str) and el.startswith("-") and "c" in el[1:]):
            if i + 1 < len(elements):
                script = elements[i + 1]
                if isinstance(script, str) and _pgrep_python_shell_string_blocks(script):
                    return True
            return False
        i += 1
    return False


def _pgrep_python_subprocess_aliases(tokens):
    aliases = {"subprocess"}
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok.type == tokenize.NAME and tok.string == "import":
            idx += 1
            while idx < len(tokens) and tokens[idx].type not in (
                tokenize.NEWLINE,
                tokenize.NL,
            ):
                if tokens[idx].type == tokenize.NAME and tokens[idx].string == "subprocess":
                    j = idx + 1
                    if (
                        j + 1 < len(tokens)
                        and tokens[j].type == tokenize.NAME
                        and tokens[j].string == "as"
                        and tokens[j + 1].type == tokenize.NAME
                    ):
                        aliases.add(tokens[j + 1].string)
                idx += 1
            continue
        idx += 1
    return aliases


def _pgrep_python_exec_call_blocks(tokens, open_paren_idx):
    idx = open_paren_idx + 1
    paren_depth = 1
    first_string = None
    tail_tokens = []
    while idx < len(tokens) and paren_depth:
        tok = tokens[idx]
        if tok.type == tokenize.OP and tok.string == "(":
            paren_depth += 1
        elif tok.type == tokenize.OP and tok.string == ")":
            paren_depth -= 1
            if paren_depth == 0:
                break
        elif paren_depth == 1:
            if tok.type == tokenize.OP and tok.string == ",":
                idx += 1
                continue
            if tok.type == tokenize.OP and tok.string in ("[", "("):
                elements, idx = _pgrep_python_collect_sequence_elements(tokens, idx)
                if first_string is not None and elements:
                    tail_tokens.extend(elements)
                continue
            fstart, _fm, _fe = _pgrep_python_fstring_token_types()
            if tok.type == tokenize.STRING or (
                fstart is not None and tok.type == fstart
            ):
                lit, idx = _pgrep_python_literal_at(tokens, idx)
                if not isinstance(lit, str):
                    continue
                if first_string is None:
                    first_string = lit
                else:
                    tail_tokens.append(lit)
                continue
        idx += 1
    if not first_string or not _pgrep_python_is_pgrep_executable(first_string):
        return False
    return _pgrep_argv_tokens_has_full_flag(tail_tokens)



def _pgrep_pgrep_match_interpreter_stdin_body(body):
    if _pgrep_python_stdin_shell_invoke(body):
        return True
    masked = _pgrep_mask_shell_comments(body)
    if not PGREP_WORD.search(pgrep_obfuscation_fold(masked)):
        return False
    chunk = _pgrep_prepare_scan_text(pgrep_obfuscation_fold(masked))
    for inner in _pgrep_each_dollar_paren(chunk):
        if not re.search(r"pgrep", inner, re.I):
            continue
        inner = _pgrep_mask_shell_comments(inner)
        if _pgrep_pgrep_match_in_fragment(inner, _depth=1):
            return True
    for inner in _pgrep_each_backtick(chunk):
        if not re.search(r"pgrep", inner, re.I):
            continue
        inner = _pgrep_mask_shell_comments(inner)
        if _pgrep_pgrep_match_in_fragment(inner, _depth=1):
            return True
    return False


def _pgrep_match_expandable_data_heredoc_substitutions(text):
    for body_start, body_end, executable, stdin_prog, literal in _pgrep_iter_heredoc_bodies(text):
        if executable or stdin_prog or literal:
            continue
        body = text[body_start:body_end]
        if _pgrep_pgrep_match_heredoc_body_substitutions(body):
            return True
    return False

def _pgrep_pgrep_match_heredoc_body_substitutions(body):
    masked = _pgrep_mask_shell_comments(body)
    chunk = _pgrep_prepare_scan_text(pgrep_obfuscation_fold(masked))
    for inner in _pgrep_each_dollar_paren(chunk):
        inner = _pgrep_mask_shell_comments(inner)
        if re.search(r"pgrep", inner, re.I) and _pgrep_pgrep_match_in_fragment(inner, _depth=1):
            return True
        if _pgrep_lifecycle_pkill_match(inner):
            return True
    for inner in _pgrep_each_backtick(chunk):
        inner = _pgrep_mask_shell_comments(inner)
        if re.search(r"pgrep", inner, re.I) and _pgrep_pgrep_match_in_fragment(inner, _depth=1):
            return True
        if _pgrep_lifecycle_pkill_match(inner):
            return True
    return False

def _pgrep_pos_in_nonexecutable_heredoc_body(text, pos, spans=None, hint=0):
    if spans is None:
        spans = _pgrep_nonexecutable_heredoc_body_spans(text)
    in_span, _ = _pgrep_pos_in_sorted_spans(pos, spans, hint)
    return in_span


def _pgrep_pos_in_sorted_spans(pos, spans, hint=0):
    n = len(spans)
    while hint < n and spans[hint][1] <= pos:
        hint += 1
    if hint < n and spans[hint][0] <= pos < spans[hint][1]:
        return True, hint
    return False, hint


def _pgrep_pos_in_data_heredoc_body(text, pos, data_spans=None):
    spans = data_spans if data_spans is not None else _pgrep_data_heredoc_body_spans(text)
    in_span, _ = _pgrep_pos_in_sorted_spans(pos, spans, 0)
    return in_span


def pgrep_obfuscation_fold(text):
    data_spans = _pgrep_data_heredoc_body_spans(text)
    hint = [0]

    def _fold_backslash_nl(m):
        in_span, hint[0] = _pgrep_pos_in_sorted_spans(m.start(), data_spans, hint[0])
        if in_span:
            return m.group(0)
        return ""

    text = re.sub(r"\\\n\s*", _fold_backslash_nl, text)
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


def _pgrep_skip_past_heredoc_body(text, i, bodies, bi):
    nb = len(bodies)
    while bi < nb and i >= bodies[bi][1]:
        bi += 1
    if bi < nb and bodies[bi][0] <= i < bodies[bi][1]:
        return bodies[bi][1], bi
    return None, bi


def _pgrep_single_quote_spans(text):
    """One pass: single-quoted regions (shell: no escapes inside '...')."""
    spans = []
    i, n = 0, len(text)
    dq = False
    hd_bodies = _pgrep_heredoc_body_spans(text)
    hd_bi = 0
    while i < n:
        skip, hd_bi = _pgrep_skip_past_heredoc_body(text, i, hd_bodies, hd_bi)
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
    dq = sq_local = False
    case_stack = [_PgrepSubstCaseState()]
    while j < n and depth:
        skip, sq_idx = _pgrep_sq_skip_past(sq, j, sq_idx)
        if skip is not None:
            j = skip
            continue
        if sq_local:
            if text[j] == "'":
                sq_local = False
            j += 1
            continue
        if dq:
            if text[j] == "\\" and j + 1 < n:
                j += 2
                continue
            if text[j] == '"':
                dq = False
                j += 1
                continue
            j += 1
            continue
        cs = case_stack[-1]
        ni = _pgrep_subst_case_unquoted_step(text, j, n, cs)
        if ni is not None:
            j = ni
            continue
        if text[j] == "(":
            _pgrep_subst_case_open_paren(cs)
            j += 1
            continue
        if text[j] == "'":
            sq_local = True
            j += 1
            continue
        if text[j] == '"':
            dq = True
            j += 1
            continue
        if text.startswith("$", j) and j + 1 < n and text[j + 1] == "(":
            case_stack.append(_PgrepSubstCaseState())
            depth += 1
            j += 2
            continue
        if text[j] == ")":
            if _pgrep_subst_case_close_paren_is_pattern(cs):
                j += 1
                continue
            depth -= 1
            if len(case_stack) > 1:
                case_stack.pop()
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


def _pgrep_heredoc_body_spans(text):
    cache = getattr(_pgrep_heredoc_body_spans, "_cache", None)
    if cache is None:
        cache = {}
        _pgrep_heredoc_body_spans._cache = cache
    key = text
    hit = cache.get(key)
    if hit is not None:
        return hit
    spans = []
    n = len(text)
    i = 0
    sq = dq = False
    hd = None
    body_start = None
    while i < n:
        if hd is not None:
            delim, strip_tabs, phase = hd
            if phase == "op":
                if text[i] == "\n":
                    hd = (delim, strip_tabs, "body")
                    body_start = i + 1
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
                if body_start is not None and body_start < i:
                    spans.append((body_start, i))
                hd = None
                body_start = None
                i = line_term
                if i < n and text[i] == "\n":
                    i += 1
                continue
            i = line_term + 1 if line_term < n else n
            continue
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
        if text[i : i + 2] == "<<" and (i == 0 or text[i - 1] in " \t\n;&|("):
            parsed = _pgrep_parse_heredoc_delim(text, i)
            if parsed:
                _, strip_tabs, j = parsed
                hd = (parsed[0], strip_tabs, "op")
                i = j
                continue
        i += 1
    if hd is not None and body_start is not None and body_start < n:
        spans.append((body_start, n))
    cache[key] = spans
    if len(cache) > 8:
        cache.clear()
    return spans


_PGREP_MASK_SUBST_STACK_MAX = 500000
_PGREP_EXEC_QUOTE_PENDING_MAX = 128


def _pgrep_mask_shell_comments_linear_scan(text):
    if "#" not in text:
        return text
    sq = _pgrep_single_quote_spans(text)
    out = []
    i, n, dq, sq_idx = 0, len(text), False, 0
    while i < n:
        skip, sq_idx = _pgrep_sq_skip_past(sq, i, sq_idx)
        if skip is not None:
            out.append(text[i:skip])
            i = skip
            continue
        if dq:
            if text[i] == "\\" and i + 1 < n:
                out.append(text[i : i + 2])
                i += 2
                continue
            if text[i] == '"':
                out.append(text[i])
                dq = False
                i += 1
                continue
            if text[i] == "`":
                inner, j, sq_idx = _pgrep_read_backtick(text, i, sq, sq_idx)
                out.append(text[i:j])
                i = j
                continue
            out.append(text[i])
            i += 1
            continue
        if text[i] == '"':
            out.append(text[i])
            dq = True
            i += 1
            continue
        if text[i] == "#" and _pgrep_hash_starts_comment(text, i):
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
            inner, j, sq_idx = _pgrep_read_dollar_paren(text, i, sq, sq_idx)
            out.append(text[i:j])
            i = j
            continue
        if text[i] == "`":
            inner, j, sq_idx = _pgrep_read_backtick(text, i, sq, sq_idx)
            out.append(text[i:j])
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)



def _pgrep_mask_shell_comments_outside_heredoc(text):
    return _pgrep_mask_shell_comments_linear_scan(text)


def _pgrep_mask_shell_comments_for_lifecycle(text):
    try:
        return _pgrep_mask_shell_comments(text)
    except Exception:
        return text


def _pgrep_mask_shell_comments_safe(text):
    try:
        return _pgrep_mask_shell_comments(text)
    except Exception:
        return text



def _pgrep_mask_line_hash_comments(text):
    if "#" not in text:
        return text
    lines = text.split("\n")
    out = []
    for line in lines:
        i = 0
        n = len(line)
        buf = []
        while i < n:
            if line[i] == "#" and _pgrep_hash_starts_comment(line, i):
                buf.append(" " * (n - i))
                break
            buf.append(line[i])
            i += 1
        out.append("".join(buf))
    return "\n".join(out)



def _pgrep_mask_lifecycle_comments_linear(text):
    if "#" not in text and "$(" not in text and "`" not in text and not re.search(r"\bcase\b", text, re.I):
        return text
    sq = _pgrep_single_quote_spans(text)
    close_at = _pgrep_subst_close_at_map(text)
    out = []
    i, n, dq, sq_idx = 0, len(text), False, 0
    subst_depth = 0
    sub_dq = sub_sq = sub_dsq = False
    subst_stack = []
    subst_openers = []
    case_stack = []
    case_top = _PgrepSubstCaseState()

    def _case_state_active():
        if subst_depth > 0 and case_stack:
            return case_stack[-1]
        if subst_depth == 0 and case_top.phase == 2:
            return case_top
        return None

    def _emit_char(ch):
        cs = _case_state_active()
        if (
            cs is not None
            and cs.phase == 2
            and not cs.in_pattern
            and cs.body_mask_kill
            and ch not in " \t\n"
        ):
            ch = " "
        out.append(ch)

    def _mask_hash_run():
        nonlocal i
        closes_after = False
        if subst_depth > 0 and subst_openers:
            opener = subst_openers[subst_depth - 1]
            closes_after = _pgrep_subst_hash_closes_after_newline(
                text, i, opener, close_at, n
            )
        use_newline = text.find("\n", i) != -1 and (subst_depth == 0 or closes_after)
        if use_newline and subst_depth > 0 and _pgrep_hash_paren_before_newline_has_separator(
            text, i, n
        ):
            use_newline = False
        if use_newline:
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            return
        close_depth = subst_depth
        cs = case_stack[-1] if case_stack else None
        if cs is None and subst_depth == 0 and case_top.phase == 2:
            cs = case_top
        while i < n:
            if text[i] == ")" and subst_depth == close_depth:
                if cs is not None and _pgrep_subst_case_append_pattern_close(out, cs, text, i):
                    i += 1
                    continue
                return
            if cs is not None and text[i] == "(":
                _pgrep_subst_case_open_paren(cs)
            out.append(" ")
            i += 1

    def _push_subst_frame(close_on_backtick=False, opener_i=0):
        nonlocal subst_depth, sub_dq, sub_sq, sub_dsq
        subst_stack.append((sub_dq, sub_sq, sub_dsq, close_on_backtick))
        case_stack.append(_PgrepSubstCaseState())
        subst_depth += 1
        sub_dq = sub_sq = sub_dsq = False
        subst_openers.append(opener_i)

    def _pop_subst_frame():
        nonlocal subst_depth, sub_dq, sub_sq, sub_dsq
        subst_depth -= 1
        if subst_openers:
            subst_openers.pop()
        if case_stack:
            case_stack.pop()
        if subst_stack:
            sub_dq, sub_sq, sub_dsq, _ = subst_stack.pop()

    def _subst_root_is_backtick():
        return bool(subst_stack and subst_stack[0][3])

    while i < n:
        if subst_depth == 0:
            if not (case_top.phase == 2 and case_top.in_pattern):
                skip, sq_idx = _pgrep_sq_skip_past(sq, i, sq_idx)
                if skip is not None:
                    out.append(text[i:skip])
                    i = skip
                    continue
            if case_top.phase == 2 and case_top.in_pattern and text[i] == "'":
                out.append(text[i])
                i += 1
                while i < n and text[i] != "'":
                    out.append(text[i])
                    i += 1
                if i < n:
                    out.append(text[i])
                    i += 1
                continue
            if case_top.phase == 2 and case_top.in_pattern and text[i] == '"':
                out.append(text[i])
                i += 1
                while i < n and text[i] != '"':
                    if text[i] == "\\" and i + 1 < n:
                        out.append(text[i : i + 2])
                        i += 2
                        continue
                    out.append(text[i])
                    i += 1
                if i < n:
                    out.append(text[i])
                    i += 1
                continue
            if not dq:
                ni = _pgrep_subst_case_unquoted_step(text, i, n, case_top)
                if ni is not None:
                    out.append(text[i:ni])
                    i = ni
                    continue
                if case_top.phase == 2 and text[i] == "(":
                    _pgrep_subst_case_open_paren(case_top)
                if case_top.phase == 2 and text[i] == ")":
                    if _pgrep_subst_case_append_pattern_close(out, case_top, text, i):
                        i += 1
                        continue
        if subst_depth > 0:
            if not sub_sq and not sub_dq and not sub_dsq:
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i : i + 2])
                    i += 2
                    continue
            if sub_dsq:
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i : i + 2])
                    i += 2
                    continue
                out.append(text[i])
                if text[i] == "'":
                    sub_dsq = False
                i += 1
                continue
            if sub_sq:
                out.append(text[i])
                if text[i] == "'":
                    sub_sq = False
                i += 1
                continue
            if sub_dq:
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i : i + 2])
                    i += 2
                    continue
                if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
                    out.append("$(")
                    _push_subst_frame(opener_i=i)
                    i += 2
                    continue
                if text[i] == "`":
                    out.append("`")
                    _push_subst_frame(close_on_backtick=True, opener_i=i)
                    i += 1
                    continue
                out.append(text[i])
                if text[i] == '"':
                    sub_dq = False
                i += 1
                continue
            if text.startswith("$'", i):
                out.append("$'")
                i += 2
                sub_dsq = True
                continue
            if text[i] == "'":
                out.append(text[i])
                sub_sq = True
                i += 1
                continue
            if text[i] == '"':
                out.append(text[i])
                sub_dq = True
                i += 1
                continue
            if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
                out.append("$(")
                _push_subst_frame(opener_i=i)
                i += 2
                continue
            cs = case_stack[-1]
            ni = _pgrep_subst_case_unquoted_step(text, i, n, cs)
            if ni is not None:
                out.append(text[i:ni])
                i = ni
                continue
            if text[i] == "(":
                out.append(text[i])
                _pgrep_subst_case_open_paren(cs)
                i += 1
                continue
            if text[i] == ")":
                if _pgrep_subst_case_append_pattern_close(out, cs, text, i):
                    i += 1
                    continue
                out.append(text[i])
                _pop_subst_frame()
                i += 1
                continue
            if text[i] == "#" and (
                _pgrep_hash_starts_comment(text, i)
                or (i > 0 and text[i - 1] == "`")
            ):
                _mask_hash_run()
                continue
            if text[i] == "`":
                if subst_stack and subst_stack[-1][3]:
                    out.append("`")
                    _pop_subst_frame()
                    i += 1
                    continue
                out.append("`")
                _push_subst_frame(close_on_backtick=True, opener_i=i)
                i += 1
                continue
            _emit_char(text[i])
            i += 1
            continue
        if dq:
            if text[i] == "\\" and i + 1 < n:
                out.append(text[i : i + 2])
                i += 2
                continue
            if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
                out.append("$(")
                subst_stack.clear()
                case_stack.clear()
                subst_openers.clear()
                _push_subst_frame(opener_i=i)
                i += 2
                continue
            if text[i] == '"':
                out.append(text[i])
                dq = False
                i += 1
                continue
            if text[i] == "`":
                out.append("`")
                subst_stack.clear()
                case_stack.clear()
                subst_openers.clear()
                _push_subst_frame(close_on_backtick=True, opener_i=i)
                i += 1
                continue
            out.append(text[i])
            i += 1
            continue
        if text[i] == '"':
            out.append(text[i])
            dq = True
            i += 1
            continue
        if text[i] == "#" and _pgrep_hash_starts_comment(text, i):
            _mask_hash_run()
            continue
        if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
            out.append("$(")
            subst_stack.clear()
            case_stack.clear()
            subst_openers.clear()
            _push_subst_frame(opener_i=i)
            i += 2
            continue
        if text[i] == "`":
            out.append("`")
            subst_stack.clear()
            case_stack.clear()
            subst_openers.clear()
            _push_subst_frame(close_on_backtick=True, opener_i=i)
            i += 1
            continue
        _emit_char(text[i])
        i += 1
    return "".join(out)

def _pgrep_mask_lifecycle_comments(text):
    try:
        if "#" not in text and "$(" not in text and "`" not in text and not re.search(r"\bcase\b", text, re.I):
            return text
        spans = _pgrep_heredoc_body_spans(text)
        if not spans:
            return _pgrep_mask_lifecycle_comments_linear(text)
        out = []
        i, n, si = 0, len(text), 0
        while i < n:
            while si < len(spans) and i >= spans[si][1]:
                si += 1
            if si < len(spans) and spans[si][0] <= i < spans[si][1]:
                end = spans[si][1]
                out.append(text[i:end])
                i = end
                continue
            j = spans[si][0] if si < len(spans) and i < spans[si][0] else n
            chunk = text[i:j]
            if chunk:
                out.append(_pgrep_mask_lifecycle_comments_linear(chunk))
            i = j
        return "".join(out)
    except Exception:
        return text



def _pgrep_single_quote_literal_regions(text):
    """Every single-quoted literal interior (any nesting), as (inner_start, inner_end, open_pos)."""
    if "'" not in text:
        return []
    regions = []
    n = len(text)
    i = 0
    dq = False
    subst_depth = 0
    sub_dq = sub_sq = sub_dsq = False
    sub_sq_open = None
    case_stack = []
    while i < n:
        if subst_depth > 0:
            if sub_dsq:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if text[i] == "'":
                    sub_dsq = False
                i += 1
                continue
            if sub_sq:
                if text[i] == "'":
                    if sub_sq_open is not None:
                        regions.append((sub_sq_open + 1, i, sub_sq_open))
                        sub_sq_open = None
                    sub_sq = False
                i += 1
                continue
            if sub_dq:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
                    subst_depth += 1
                    i += 2
                    continue
                if text[i] == "`":
                    subst_depth += 1
                    i += 1
                    continue
                if text[i] == '"':
                    sub_dq = False
                i += 1
                continue
            if not sub_sq and not sub_dq and not sub_dsq:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
            if text[i] == "#" and (
                _pgrep_hash_starts_comment(text, i)
                or (i > 0 and text[i - 1] == "`")
            ):
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if text.startswith("$'", i):
                i += 2
                sub_dsq = True
                continue
            if text[i] == "'":
                sub_sq = True
                sub_sq_open = i
                i += 1
                continue
            if text[i] == '"':
                sub_dq = True
                i += 1
                continue
            if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
                case_stack.append(_PgrepSubstCaseState())
                subst_depth += 1
                i += 2
                continue
            cs = case_stack[-1] if case_stack else None
            if cs is not None:
                ni = _pgrep_subst_case_unquoted_step(text, i, n, cs)
                if ni is not None:
                    i = ni
                    continue
                if text[i] == "(":
                    _pgrep_subst_case_open_paren(cs)
                    i += 1
                    continue
            if text[i] == ")":
                if cs is not None and _pgrep_subst_case_close_paren_is_pattern(cs):
                    i += 1
                    continue
                subst_depth -= 1
                if case_stack:
                    case_stack.pop()
                i += 1
                continue
            if text[i] == "`":
                case_stack.append(_PgrepSubstCaseState())
                subst_depth += 1
                i += 1
                continue
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
            if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
                subst_depth = 1
                sub_dq = sub_sq = sub_dsq = False
                sub_sq_open = None
                case_stack.append(_PgrepSubstCaseState())
                i += 2
                continue
            if text[i] == "`":
                subst_depth = 1
                sub_dq = sub_sq = sub_dsq = False
                sub_sq_open = None
                case_stack.append(_PgrepSubstCaseState())
                i += 1
                continue
            i += 1
            continue
        if text[i] == '"':
            dq = True
            i += 1
            continue
        if text[i] == "'":
            open_pos = i
            i += 1
            while i < n and text[i] != "'":
                i += 1
            if i < n:
                regions.append((open_pos + 1, i, open_pos))
                i += 1
            continue
        if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
            subst_depth = 1
            sub_dq = sub_sq = sub_dsq = False
            sub_sq_open = None
            case_stack.append(_PgrepSubstCaseState())
            i += 2
            continue
        if text[i] == "`":
            subst_depth = 1
            sub_dq = sub_sq = sub_dsq = False
            sub_sq_open = None
            case_stack.append(_PgrepSubstCaseState())
            i += 1
            continue
        i += 1
    return regions


def _pgrep_lifecycle_pkill_word_match(
    text, masked, exec_starts=None, regions=None, region_idx=None, pos_offset=0
):
    if exec_starts is None:
        exec_starts = _pgrep_executable_single_quote_starts(text)
    if regions is None:
        regions = _pgrep_single_quote_literal_regions(text)
    if region_idx is None:
        region_idx = [0]
    idx = region_idx[0]
    n_regions = len(regions)
    for m in BB_LIFECYCLE_PKILL.finditer(masked):
        pos = pos_offset + m.start()
        while idx < n_regions and pos >= regions[idx][1]:
            idx += 1
        if idx < n_regions:
            inner_start, inner_end, quote_start = regions[idx]
            if inner_start <= pos < inner_end:
                if quote_start not in exec_starts:
                    continue
                region_idx[0] = idx
                return True
        region_idx[0] = idx
        return True
    region_idx[0] = idx
    return False


_PGREP_LIFECYCLE_VAR_REF = re.compile(r"^\$(\w+)$|^\$\{(\w+)\}$")


def _pgrep_lifecycle_var_ref_name(word):
    w = word.strip()
    if len(w) >= 2 and w[0] == w[-1] and w[0] in "'\"":
        w = w[1:-1].strip()
    m = _PGREP_LIFECYCLE_VAR_REF.match(w)
    if not m:
        return None
    return m.group(1) or m.group(2)


_PGREP_LIFECYCLE_DECL_WORDS = frozenset(
    ("export", "readonly", "declare", "typeset", "local")
)


def _pgrep_lifecycle_normalize_test_span(span):
    return re.sub(r"\s+", " ", span.strip())


def _pgrep_lifecycle_bracket_inner_always_true(inner):
    inner = inner.strip()
    if not inner or inner in ('""', "''"):
        return False
    if "$" in inner or "`" in inner or "$(" in inner:
        return False
    if inner.startswith("-") or inner.startswith("!"):
        return False
    if re.match(r"^-n\s+(''|\"\")\s*$", inner):
        return False
    return True


def _pgrep_lifecycle_test_always_true(span):
    s = _pgrep_lifecycle_normalize_test_span(span)
    if not s:
        return False
    if s in ("true", ":"):
        return True
    if re.match(r"^!\s*false$", s, re.I):
        return True
    m = re.match(r"^\[\[\s*(.+?)\s+\]\]$", s)
    if m:
        return _pgrep_lifecycle_bracket_inner_always_true(m.group(1))
    m = re.match(r"^\[\s*([^]]+)\s*\]$", s)
    if m:
        return _pgrep_lifecycle_bracket_inner_always_true(m.group(1))
    m = re.match(r"^test\s+(.+)$", s, re.I)
    if m:
        return _pgrep_lifecycle_bracket_inner_always_true(m.group(1))
    return False


def _pgrep_lifecycle_test_always_false(span):
    s = _pgrep_lifecycle_normalize_test_span(span)
    if not s:
        return False
    if s == "false":
        return True
    if re.match(r"^!\s*true$", s, re.I):
        return True
    m = re.match(r"^\[\s*([^]]+)\s*\]$", s)
    if m:
        inner = m.group(1).strip()
        if inner in ('""', "''"):
            return True
        if re.match(r"^-n\s+(''|\"\")\s*$", inner):
            return True
    return False


def _pgrep_lifecycle_span_first_word_base(text, cmd_start, cmd_end):
    i = _pgrep_after_command_leaders(text, cmd_start)
    i = _pgrep_skip_space(text, i)
    if i >= cmd_end:
        return None
    ws = i
    we = _pgrep_skip_one_word(text, i, cmd_end)
    if ws >= we:
        return None
    return _pgrep_bare_word(text[ws:we]).rsplit("/", 1)[-1].lower()


def _pgrep_lifecycle_should_apply_unset(
    text, prev_start, prev_end, cmd_start, cmd_end
):
    if _pgrep_lifecycle_span_is_subshell(text, cmd_start, cmd_end):
        return False
    if _pgrep_lifecycle_span_first_word_base(text, cmd_start, cmd_end) != "unset":
        return True
    if prev_end is None or prev_end >= cmd_start or prev_start is None:
        return True
    glue = text[prev_end:cmd_start]
    prev = text[prev_start:prev_end]
    if "&&" in glue:
        return _pgrep_lifecycle_test_always_true(prev)
    if "||" in glue:
        return _pgrep_lifecycle_test_always_false(prev)
    return True


def _pgrep_lifecycle_span_is_subshell(text, cmd_start, cmd_end):
    i = _pgrep_skip_space(text, _pgrep_after_command_leaders(text, cmd_start))
    return i < cmd_end and text[i] == "("


def _pgrep_lifecycle_resolve_assign_value(val, into):
    ref = _pgrep_lifecycle_var_ref_name(val)
    if ref is not None and ref in into:
        return into[ref]
    return _pgrep_unquote_assign_value(val)


def _pgrep_lifecycle_apply_unset_words(text, i, cmd_end, into):
    function_only = False
    while i < cmd_end:
        i = _pgrep_skip_space(text, i)
        if i >= cmd_end:
            break
        ws = i
        we = _pgrep_skip_one_word(text, i, cmd_end)
        if ws >= we:
            break
        w = _pgrep_bare_word(text[ws:we])
        if w.startswith("-") and not w.startswith("--"):
            opts = w[1:]
            has_f = "f" in opts
            has_v = "v" in opts
            if has_f and not has_v:
                function_only = True
            elif has_v or (not has_f and opts in ("n",)):
                function_only = False
            i = we
            continue
        if w.startswith("-"):
            i = we
            continue
        if not function_only:
            into.pop(w, None)
        i = we


def _pgrep_lifecycle_mutate_bindings_in_command(
    text, cmd_start, cmd_end, into, *, apply_unset=True, subshell=False
):
    if subshell:
        return
    i = _pgrep_after_command_leaders(text, cmd_start)
    pending = []
    while i < cmd_end:
        i = _pgrep_skip_space(text, i)
        if i >= cmd_end:
            break
        asn = _pgrep_assignment_at(text, i, cmd_end)
        if asn:
            name, val, nxt = asn
            pending.append((name, _pgrep_lifecycle_resolve_assign_value(val, into)))
            i = nxt
            continue
        me = re.match(r"(\w+)=$", text[i:cmd_end])
        if me:
            pending.append((me.group(1), ""))
            i += me.end()
            continue
        break
    if i >= cmd_end:
        for name, val in pending:
            into[name] = val
        return
    i = _pgrep_skip_space(text, i)
    ws = i
    we = _pgrep_skip_one_word(text, i, cmd_end)
    if ws >= we:
        return
    base = _pgrep_bare_word(text[ws:we]).rsplit("/", 1)[-1].lower()
    if base == "unset":
        if apply_unset:
            _pgrep_lifecycle_apply_unset_words(text, we, cmd_end, into)
        return
    if base in _PGREP_LIFECYCLE_DECL_WORDS:
        i = we
        while i < cmd_end:
            i = _pgrep_skip_space(text, i)
            if i >= cmd_end:
                break
            asn = _pgrep_assignment_at(text, i, cmd_end)
            if asn:
                name, val, nxt = asn
                into[name] = _pgrep_lifecycle_resolve_assign_value(val, into)
                i = nxt
                continue
            ws2 = i
            we2 = _pgrep_skip_one_word(text, i, cmd_end)
            if ws2 >= we2:
                break
            i = we2
        return
    # Prefix assignments before a command word are temporary in bash.
    return


def _pgrep_lifecycle_collect_script_bindings(text, cmd_start, cmd_end, into):
    _pgrep_lifecycle_mutate_bindings_in_command(
        text, cmd_start, cmd_end, into, apply_unset=True, subshell=False
    )


def _pgrep_lifecycle_expand_var_segment(segment, binds):
    if not binds:
        return segment
    var = _pgrep_lifecycle_var_ref_name(segment)
    if var is None:
        return segment
    return binds.get(var)


def _pgrep_lifecycle_bindings_for_pos(text, pos):
    binds = {}
    prev_start = prev_end = None
    for cmd_start, cmd_end in _pgrep_iter_simple_command_spans(text):
        if pos < cmd_start:
            break
        sub = _pgrep_lifecycle_span_is_subshell(text, cmd_start, cmd_end)
        apply_unset = _pgrep_lifecycle_should_apply_unset(
            text, prev_start, prev_end, cmd_start, cmd_end
        )
        _pgrep_lifecycle_mutate_bindings_in_command(
            text, cmd_start, cmd_end, binds, apply_unset=apply_unset, subshell=sub
        )
        prev_start, prev_end = cmd_start, cmd_end
        if pos < cmd_end:
            break
    return binds


def _pgrep_lifecycle_scan_resolved_arg(text, arg_text, binds, depth):
    expanded = _pgrep_lifecycle_expand_var_segment(arg_text, binds)
    if not expanded:
        return False
    if expanded == arg_text:
        inner = expanded
        if len(inner) >= 2 and inner[0] == inner[-1] and inner[0] in "'\"":
            inner = inner[1:-1]
        return _pgrep_lifecycle_pkill_match(inner, depth + 1)
    return _pgrep_lifecycle_pkill_match(expanded, depth + 1)


def _pgrep_lifecycle_var_and_nested_exec_pkill(text, cmd_start, cmd_end, binds, depth):
    i = _pgrep_after_command_leaders(text, cmd_start)
    i = _pgrep_skip_assignments_and_wrappers(text, i, cmd_end)
    i = _pgrep_skip_space(text, i)
    if i >= cmd_end:
        return False
    ws = i
    we = _pgrep_skip_one_word(text, i, cmd_end)
    if we <= ws:
        return False
    word = text[ws:we]
    var = _pgrep_lifecycle_var_ref_name(word)
    if var and var in binds:
        expanded = binds[var]
        if expanded and _pgrep_lifecycle_pkill_match(expanded, depth + 1):
            return True
    base = _pgrep_bare_word(word).rsplit("/", 1)[-1].lower()
    if base == "eval":
        j = _pgrep_skip_space(text, we)
        if j < cmd_end:
            arg_ws = j
            arg_we = _pgrep_skip_one_word(text, j, cmd_end)
            if _pgrep_lifecycle_scan_resolved_arg(
                text, text[arg_ws:arg_we], binds, depth
            ):
                return True
    if base in ("bash", "sh", "zsh", "dash", "ksh"):
        k = we
        while k < cmd_end:
            k = _pgrep_skip_space(text, k)
            if k >= cmd_end:
                break
            ws2 = k
            we2 = _pgrep_skip_one_word(text, k, cmd_end)
            if ws2 >= we2:
                break
            if _pgrep_word_is_dash_c_flag(text[ws2:we2]) or _pgrep_bare_word(
                text[ws2:we2]
            ) == "-c":
                j = _pgrep_skip_space(text, we2)
                if j < cmd_end:
                    arg_ws = j
                    arg_we = _pgrep_skip_one_word(text, j, cmd_end)
                    if _pgrep_lifecycle_scan_resolved_arg(
                        text, text[arg_ws:arg_we], binds, depth
                    ):
                        return True
                return False
            k = we2
    return False



def _pgrep_lifecycle_subst_inner_blocks(inner):
    if re.search(r"\b(?:bash|sh|zsh|dash|ksh|eval)\b", inner, re.I):
        return True
    masked = _pgrep_mask_lifecycle_comments(inner)
    launch = _pgrep_skip_assignments_and_wrappers(masked, 0, len(masked))
    tail = masked[launch:].lstrip()
    return bool(re.match(r"(?:\S+/)*pkill\b", tail, re.I))

def _pgrep_lifecycle_pkill_match(text, _depth=0):
    if _depth > _PGREP_FRAGMENT_MAX_DEPTH:
        return False
    masked = _pgrep_mask_lifecycle_comments(text)
    exec_starts = _pgrep_executable_single_quote_starts(text)
    regions = _pgrep_single_quote_literal_regions(text)
    region_idx = [0]
    if _pgrep_lifecycle_pkill_word_match(
        text, masked, exec_starts, regions, region_idx, 0
    ):
        return True
    carry = {}
    prev_start = prev_end = None
    for cmd_start, cmd_end in _pgrep_iter_simple_command_spans(text):
        sub = _pgrep_lifecycle_span_is_subshell(text, cmd_start, cmd_end)
        apply_unset = _pgrep_lifecycle_should_apply_unset(
            text, prev_start, prev_end, cmd_start, cmd_end
        )
        _pgrep_lifecycle_mutate_bindings_in_command(
            text, cmd_start, cmd_end, carry, apply_unset=apply_unset, subshell=sub
        )
        prev_start, prev_end = cmd_start, cmd_end
        for ls, le in _pgrep_iter_launched_command_regions(text, cmd_start, cmd_end):
            chunk = _pgrep_mask_lifecycle_comments(text[ls:le])
            if _pgrep_lifecycle_pkill_word_match(
                text, chunk, exec_starts, regions, region_idx, ls
            ):
                return True
        if _pgrep_lifecycle_var_and_nested_exec_pkill(
            text, cmd_start, cmd_end, carry, _depth
        ):
            return True
    if not re.search(r"\bpkill\b", text, re.I):
        return False
    for start, end, is_exec in _pgrep_iter_quoted_spans_meta(text):
        if not is_exec:
            continue
        inner = text[start + 1 : end - 1]
        binds = _pgrep_lifecycle_bindings_for_pos(text, start)
        expanded = _pgrep_lifecycle_expand_var_segment(inner, binds)
        if not expanded:
            continue
        if expanded != inner:
            if _pgrep_lifecycle_pkill_match(expanded, _depth + 1):
                return True
            continue
        if _pgrep_lifecycle_pkill_match(
            _pgrep_mask_lifecycle_comments(inner), _depth + 1
        ):
            return True
    for inner in _pgrep_each_dollar_paren(text):
        if not re.search(r"\bpkill\b", inner, re.I):
            continue
        if not _pgrep_lifecycle_subst_inner_blocks(inner):
            continue
        if _pgrep_lifecycle_pkill_match(
            _pgrep_mask_lifecycle_comments(inner), _depth + 1
        ):
            return True
    for inner in _pgrep_each_backtick(text):
        if not re.search(r"\bpkill\b", inner, re.I):
            continue
        if not _pgrep_lifecycle_subst_inner_blocks(inner):
            continue
        if _pgrep_lifecycle_pkill_match(
            _pgrep_mask_lifecycle_comments(inner), _depth + 1
        ):
            return True
    return False



def _pgrep_quote_fault_in_segment(text, base, fault):
    dq = sq = False
    dq_start = sq_start = 0
    n = len(text)
    i = 0
    while i < n:
        if dq:
            if text[i] == "\\" and i + 1 < n:
                i += 2
                continue
            if text[i] == '"':
                dq = False
            i += 1
            continue
        if sq:
            if text[i] == "'":
                sq = False
            i += 1
            continue
        if text[i] == "#" and _pgrep_hash_starts_comment(text, i):
            nl = text.find("\n", i)
            i = n if nl == -1 else nl + 1
            continue
        if text[i] == "'":
            sq = True
            sq_start = base + i
            i += 1
            continue
        if text[i] == '"':
            dq = True
            dq_start = base + i
            i += 1
            continue
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        i += 1
    if dq:
        fault[0] = min(fault[0], dq_start)
    if sq:
        fault[0] = min(fault[0], sq_start)


def _pgrep_earliest_shell_fault(text, quote_fault=True):
    n = len(text)
    fault = [n]
    spans = _pgrep_heredoc_body_spans(text)
    if quote_fault:
        if not spans:
            _pgrep_quote_fault_in_segment(text, 0, fault)
        else:
            pos = 0
            for body_start, body_end in spans:
                if pos < body_start:
                    _pgrep_quote_fault_in_segment(text[pos:body_start], pos, fault)
                pos = body_end
            if pos < n:
                _pgrep_quote_fault_in_segment(text[pos:], pos, fault)
    hd = None
    hd_start = 0
    i = 0
    sq = dq2 = False
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
                    i += 1
                continue
            i = line_term + 1 if line_term < n else n
            continue
        if text[i] == "#" and _pgrep_hash_starts_comment(text, i):
            nl = text.find("\n", i)
            i = n if nl == -1 else nl + 1
            continue
        if sq:
            if text[i] == "'":
                sq = False
            i += 1
            continue
        if dq2:
            if text[i] == "\\" and i + 1 < n:
                i += 2
                continue
            if text[i] == '"':
                dq2 = False
            i += 1
            continue
        if text[i] == "'":
            sq = True
            i += 1
            continue
        if text[i] == '"':
            dq2 = True
            i += 1
            continue
        if text[i : i + 2] == "<<" and (i == 0 or text[i - 1] in " \t\n;&|("):
            parsed = _pgrep_parse_heredoc_delim(text, i)
            if parsed:
                hd_start = i
                _, strip_tabs, j = parsed
                hd = (parsed[0], strip_tabs, "op")
                i = j
                continue
        i += 1
    if hd is not None:
        fault[0] = min(fault[0], hd_start)
    data_spans = _pgrep_data_heredoc_body_spans(text)
    span_hint = 0
    for m in re.finditer(r"\\(?:\r?\n|$)", text):
        pos = m.start()
        in_span, span_hint = _pgrep_pos_in_sorted_spans(pos, data_spans, span_hint)
        if in_span:
            continue
        line_start = text.rfind("\n", 0, pos) + 1
        hash_at = text.find("#", line_start, pos)
        if hash_at != -1 and _pgrep_hash_starts_comment(text, hash_at):
            continue
        fault[0] = min(fault[0], pos)
    return fault[0] if fault[0] < n else None




def _pgrep_fail_closed_skip_unterminated_data_heredoc(shell, fault):
    if fault is None or fault + 2 > len(shell) or not shell.startswith("<<", fault):
        return False
    cmd_start = 0
    for m in re.finditer(r"[;&|\n]|&&|\|\|", shell[:fault]):
        cmd_start = m.end()
    cmd_start = _pgrep_skip_space(shell, cmd_start)
    if _pgrep_heredoc_owner_executable(shell, cmd_start, fault):
        return False
    line_end = shell.find("\n", fault)
    if line_end == -1:
        line_end = len(shell)
    parsed = _pgrep_parse_heredoc_delim(shell, fault)
    if parsed:
        if parsed[0] == "":
            return True
        if _pgrep_heredoc_opener_line_pipes_to_shell(shell, parsed[2], line_end):
            return False
    head = shell.split("<<", 1)[0]
    last = re.split(r"&&|\|\||;", head)[-1]
    if any(rx.search(last) for rx in HEREDOC_EXEMPT):
        return True
    if _pgrep_heredoc_interpreter_stdin_executable(shell, cmd_start, fault):
        return True
    return True




def _pgrep_bash_n_syntax_error(cmd):
    import subprocess

    cache = getattr(_pgrep_bash_n_syntax_error, "_cache", None)
    if cache is None:
        cache = {}
        _pgrep_bash_n_syntax_error._cache = cache
    if cmd in cache:
        return cache[cmd]
    try:
        r = subprocess.run(
            ["bash", "-n"],
            input=cmd,
            capture_output=True,
            text=True,
            timeout=1,
        )
        out = r.returncode != 0
    except UnicodeEncodeError:
        out = True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        out = None
    cache[cmd] = out
    return out


def _pgrep_fail_closed_after_shell_fault(text, cmd=None):
    shell = cmd if isinstance(cmd, str) and cmd.strip() else text
    if not isinstance(shell, str) or not shell.strip():
        return False
    bash_err = _pgrep_bash_n_syntax_error(shell)
    if bash_err is True:
        tail = shell
    elif bash_err is False:
        return False
    else:
        fault = _pgrep_earliest_shell_fault(shell, quote_fault=True)
        if fault is None:
            return False
        if _pgrep_fail_closed_skip_unterminated_data_heredoc(shell, fault):
            return False
        if _pgrep_pos_in_data_heredoc_body(shell, fault):
            return False
        tail = shell[fault:]
    if _pgrep_lifecycle_pkill_match(tail):
        return False
    try:
        scan = _pgrep_prepare_scan_text(tail)
        if _pgrep_pgrep_match_in_fragment(scan):
            return True
    except Exception:
        pass
    folded = pgrep_obfuscation_fold(tail)
    if PGREP_WORD.search(folded) and PGREP_FULL_FLAG.search(folded):
        return True
    return False







def _pgrep_subst_hash_closes_after_newline(text, hash_i, opener, close_at, n):
    """Same decision as daf8 rescan, using ``close_at`` from the pre-pass."""
    if opener not in close_at:
        return False
    nl = text.find("\n", hash_i)
    if nl == -1:
        return False
    if close_at[opener] > nl:
        return True
    rp = text.find(")", hash_i, nl)
    if rp == -1:
        return False
    tail = text[rp + 1 : nl].lstrip()
    while tail.startswith(")"):
        tail = tail[1:].lstrip()
    if tail.startswith('"'):
        tail = tail[1:].lstrip()
    if not tail:
        return False
    if tail[0] in ";|":
        return False
    if tail.startswith("&&"):
        return False
    return True


def _pgrep_subst_close_at_map(text):
    """One forward scan: map each ``$(`` / backtick opener index to its closer (if any)."""
    if "#" not in text and "$(" not in text and "`" not in text and not re.search(r"\bcase\b", text, re.I):
        return {}
    sq = _pgrep_single_quote_spans(text)
    close_at = {}
    opener_stack = []
    n = len(text)
    i = dq = sq_idx = 0
    subst_depth = 0
    sub_dq = sub_sq = sub_dsq = False
    subst_stack = []
    case_stack = []

    def _push(opener_i, close_on_backtick=False):
        nonlocal subst_depth, sub_dq, sub_sq, sub_dsq
        subst_stack.append((sub_dq, sub_sq, sub_dsq, close_on_backtick))
        case_stack.append(_PgrepSubstCaseState())
        subst_depth += 1
        sub_dq = sub_sq = sub_dsq = False
        opener_stack.append(opener_i)

    def _pop(close_i):
        nonlocal subst_depth, sub_dq, sub_sq, sub_dsq
        if opener_stack:
            close_at[opener_stack.pop()] = close_i
        subst_depth -= 1
        if case_stack:
            case_stack.pop()
        if subst_stack:
            sub_dq, sub_sq, sub_dsq, _ = subst_stack.pop()

    while i < n:
        if subst_depth == 0:
            skip, sq_idx = _pgrep_sq_skip_past(sq, i, sq_idx)
            if skip is not None:
                i = skip
                continue
        if subst_depth > 0:
            if not sub_sq and not sub_dq and not sub_dsq:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
            if sub_dsq:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if text[i] == "'":
                    sub_dsq = False
                i += 1
                continue
            if sub_sq:
                if text[i] == "'":
                    sub_sq = False
                i += 1
                continue
            if sub_dq:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
                    _push(i)
                    i += 2
                    continue
                if text[i] == "`":
                    _push(i, close_on_backtick=True)
                    i += 1
                    continue
                if text[i] == '"':
                    sub_dq = False
                i += 1
                continue
            if text.startswith("$'", i):
                i += 2
                sub_dsq = True
                continue
            if text[i] == "'":
                sub_sq = True
                i += 1
                continue
            if text[i] == '"':
                sub_dq = True
                i += 1
                continue
            if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
                _push(i)
                i += 2
                continue
            cs = case_stack[-1]
            ni = _pgrep_subst_case_unquoted_step(text, i, n, cs)
            if ni is not None:
                i = ni
                continue
            if text[i] == "(":
                _pgrep_subst_case_open_paren(cs)
                i += 1
                continue
            if text[i] == ")":
                if _pgrep_subst_case_close_paren_is_pattern(cs):
                    i += 1
                    continue
                _pop(i)
                i += 1
                continue
            if text[i] == "#" and (
                _pgrep_hash_starts_comment(text, i)
                or (i > 0 and text[i - 1] == "`")
            ):
                i += 1
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if text[i] == "`":
                if subst_stack and subst_stack[-1][3]:
                    _pop(i)
                    i += 1
                    continue
                _push(i, close_on_backtick=True)
                i += 1
                continue
            i += 1
            continue
        if dq:
            if text[i] == "\\" and i + 1 < n:
                i += 2
                continue
            if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
                subst_stack.clear()
                case_stack.clear()
                opener_stack.clear()
                _push(i)
                i += 2
                continue
            if text[i] == '"':
                dq = False
                i += 1
                continue
            if text[i] == "`":
                subst_stack.clear()
                opener_stack.clear()
                _push(i, close_on_backtick=True)
                i += 1
                continue
            i += 1
            continue
        if text[i] == '"':
            dq = True
            i += 1
            continue
        if text[i] == "#" and _pgrep_hash_starts_comment(text, i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
            subst_stack.clear()
            case_stack.clear()
            opener_stack.clear()
            _push(i)
            i += 2
            continue
        if text[i] == "`":
            subst_stack.clear()
            opener_stack.clear()
            _push(i, close_on_backtick=True)
            i += 1
            continue
        i += 1
    return close_at


def _pgrep_hash_paren_before_newline_has_separator(text, hash_tail_i, n):
    """r33 fail-safe: ``)`` before newline then ``;`` ``|`` or ``&&`` — do not newline-mask the tail."""
    seg_end = text.find("\n", hash_tail_i)
    if seg_end == -1:
        seg_end = n
    rp = text.find(")", hash_tail_i, seg_end)
    if rp == -1:
        return False
    j = rp + 1
    while j < n and text[j] in " \t":
        j += 1
    if j + 1 < n and text[j : j + 2] == "&&":
        return True
    if j < n and text[j] in ";|":
        return True
    return False



def _pgrep_hash_starts_comment(text, i):
    if i >= len(text) or text[i] != "#":
        return False
    if i > 0 and text[i - 1] == "\\":
        return False
    if i > 0 and text[i - 1] == "$":
        return False
    if i >= 2 and text[i - 1] == "{" and text[i - 2] == "$":
        return False
    if i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_"):
        return False
    if i == 0:
        return True
    return text[i - 1] in " \t\n;&|()"


def _pgrep_mask_shell_comments(text):
    if "#" not in text:
        return text
    spans = _pgrep_heredoc_body_spans(text)
    if not spans:
        return _pgrep_mask_shell_comments_outside_heredoc(text)
    out = []
    i, n, si = 0, len(text), 0
    while i < n:
        while si < len(spans) and i >= spans[si][1]:
            si += 1
        if si < len(spans) and spans[si][0] <= i < spans[si][1]:
            end = spans[si][1]
            out.append(text[i:end])
            i = end
            continue
        j = spans[si][0] if si < len(spans) and i < spans[si][0] else n
        chunk = text[i:j]
        if chunk:
            out.append(_pgrep_mask_shell_comments_outside_heredoc(chunk))
        i = j
    return "".join(out)


def _pgrep_tail_after_first_heredoc(text):
    i = text.find("<<")
    if i == -1:
        return ""
    if i > 0 and text[i - 1] not in " \t\n;&|(":
        return ""
    parsed = _pgrep_parse_heredoc_delim(text, i)
    if not parsed:
        return ""
    delim, strip_tabs, j = parsed
    n = len(text)
    k = j
    while k < n and text[k] != "\n":
        k += 1
    if k >= n:
        return ""
    k += 1
    while k < n:
        line_term = text.find("\n", k)
        if line_term == -1:
            line_term = n
        line = text[k:line_term]
        if line.endswith("\r"):
            line = line[:-1]
        cmp_line = line.lstrip("\t") if strip_tabs else line
        if cmp_line == delim:
            k = line_term
            if k < n and text[k] == "\n":
                k += 1
            return text[k:]
        k = line_term + 1 if line_term < n else n
    return ""


def _pgrep_parse_heredoc_delim_ex(text, i):
    n = len(text)
    if i + 2 > n or text[i : i + 2] != "<<":
        return None
    j = i + 2
    strip_tabs = False
    if j < n and text[j] == "-":
        strip_tabs = True
        j += 1
    if j >= n:
        return ("", strip_tabs, j, True)
    if text[j] in "'\"":
        q = text[j]
        k = j + 1
        while k < n and text[k] != q:
            k += 1
        if k >= n:
            return ("", strip_tabs, n, True)
        return (text[j + 1 : k], strip_tabs, k + 1, True)
    if text[j] == "\\" and j + 1 < n:
        m = re.match(r"[A-Za-z0-9_]+", text[j + 1 :])
        if m:
            return (m.group(0), strip_tabs, j + 1 + m.end(), True)
    m = re.match(r"[A-Za-z0-9_]+", text[j:])
    if not m:
        return None
    return (m.group(0), strip_tabs, j + m.end(), False)


def _pgrep_parse_heredoc_delim(text, i):
    parsed = _pgrep_parse_heredoc_delim_ex(text, i)
    if parsed is None:
        return None
    return parsed[0], parsed[1], parsed[2]




_PGREP_HEREDOC_STDIN_WRAPPERS = frozenset(
    {"sudo", "env", "timeout", "command", "exec", "nohup", "time", "nice"}
)
_PGREP_HEREDOC_STDIN_INTERP = frozenset(
    {"python", "python3", "node", "perl", "ruby", "bash", "sh", "zsh", "dash", "ksh"}
)


def _pgrep_word_tokens_before(text, cmd_start, op_start):
    tokens = []
    i = cmd_start
    while i < op_start:
        i = _pgrep_skip_space(text, i)
        if i >= op_start:
            break
        ws = i
        we = _pgrep_skip_one_word(text, i, op_start)
        if ws >= we:
            break
        tokens.append(_pgrep_bare_word(text[ws:we]))
        i = we
    return tokens


def _pgrep_heredoc_interpreter_stdin_executable(text, cmd_start, op_start):
    tokens = _pgrep_word_tokens_before(text, cmd_start, op_start)
    if not tokens:
        return False
    idx = 0
    while idx < len(tokens) and tokens[idx].lower() in _PGREP_HEREDOC_STDIN_WRAPPERS:
        idx += 1
    if idx >= len(tokens):
        return False
    base = tokens[idx].rsplit("/", 1)[-1].lower()
    if base not in _PGREP_HEREDOC_STDIN_INTERP:
        return False
    if base in ("bash", "sh", "zsh", "dash", "ksh"):
        return False
    rest = tokens[idx + 1 :]
    if base in ("python", "python3", "node", "perl", "ruby"):
        if not rest:
            return True
        for tok in rest:
            if tok == "-":
                return True
            if tok.startswith("-"):
                continue
            return False
        return True
    return False



def _pgrep_find_exec_script_quote_open(text, cmd_start, op_start):
    i = _pgrep_skip_assignments_and_wrappers(text, cmd_start, op_start)
    i = _pgrep_skip_space(text, i)
    if i >= op_start:
        return None
    ws = i
    we = _pgrep_skip_one_word(text, i, op_start)
    if ws >= we:
        return None
    base = _pgrep_bare_word(text[ws:we]).rsplit("/", 1)[-1].lower()
    if base == "eval":
        j = _pgrep_skip_space(text, we)
        if j < op_start and text[j] in "'\"":
            return j
        return None
    if base in _PGREP_SHELL_WORDS:
        k = we
        while k < op_start:
            k = _pgrep_skip_space(text, k)
            if k >= op_start:
                break
            ws2 = k
            we2 = _pgrep_skip_one_word(text, k, op_start)
            if ws2 >= we2:
                break
            if _pgrep_word_is_dash_c_flag(text[ws2:we2]) or _pgrep_bare_word(text[ws2:we2]) == "-c":
                j = _pgrep_skip_space(text, we2)
                if j < op_start and text[j] in "'\"":
                    return j
                return None
            k = we2
    return None


def _pgrep_skip_leading_assignments(text, i, limit):
    while i < limit:
        i = _pgrep_skip_space(text, i)
        if i >= limit:
            return i
        m = _PGREP_LEADING_ASSIGN.match(text, i, limit)
        if m:
            i = m.end()
            continue
        m = _PGREP_LEADING_ASSIGN_WS.match(text, i, limit)
        if m:
            i = m.end()
            continue
        break
    return i


def _pgrep_dollar_at_inner_shell_command_position(text, quote_open, dollar_pos):
    if quote_open is None or dollar_pos <= quote_open + 1:
        return True
    _after_assign = _pgrep_skip_leading_assignments(text, quote_open + 1, dollar_pos)
    if _after_assign >= dollar_pos or not text[_after_assign:dollar_pos].strip():
        return True
    prefix = text[quote_open + 1 : dollar_pos].rstrip()
    if not prefix:
        return True
    if prefix[-1] in ";\n|":
        return True
    if prefix.endswith("&&") or prefix.endswith("||"):
        return True
    return False


def _pgrep_ssh_remote_shell_reads_heredoc(text, cmd_start, op_start):
    i = _pgrep_skip_assignments_and_wrappers(text, cmd_start, op_start)
    i = _pgrep_skip_space(text, i)
    if i >= op_start:
        return False
    ws = i
    we = _pgrep_skip_one_word(text, i, op_start)
    if ws >= we:
        return False
    if _pgrep_bare_word(text[ws:we]).rsplit("/", 1)[-1].lower() != "ssh":
        return False
    rem = _pgrep_skip_ssh_prefix_after_command(text, we, op_start)
    if rem is None or rem >= op_start:
        return False
    rem = _pgrep_skip_space(text, rem)
    ws2 = rem
    we2 = _pgrep_skip_one_word(text, rem, op_start)
    if ws2 >= we2:
        return False
    sh = _pgrep_bare_word(text[ws2:we2]).rsplit("/", 1)[-1].lower()
    return sh in ("bash", "sh", "zsh", "dash", "ksh")


def _pgrep_heredoc_cat_subst_for_exec(text, cmd_start, op_start):
    if text[op_start : op_start + 2] != "<<":
        return False
    op_line = text[cmd_start:op_start]
    if "$(" not in op_line:
        return False
    m = re.search(r"\$\(\s*(?:\S+/)*(?:cat|tee)\b", op_line, re.I)
    if not m:
        return False
    if re.search(r"\bcat\s*>|\btee\s+[^<\s]", op_line):
        return False
    quote_open = _pgrep_find_exec_script_quote_open(text, cmd_start, op_start)
    if quote_open is None:
        return False
    dollar_pos = cmd_start + m.start()
    return _pgrep_dollar_at_inner_shell_command_position(text, quote_open, dollar_pos)


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
    if _pgrep_ssh_remote_shell_reads_heredoc(text, cmd_start, op_start):
        return True
    if re.search(r"\bssh\b", segment, re.I):
        after = text[span[1] : op_start]
        cleaned = re.sub(r"-\S+", " ", after)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned.split()) <= 1:
            return True
    return False


_PGREP_SSH_OPT_WITH_ARG = frozenset("BbcDEeFIiJLlmOoPpQRSWw")


def _pgrep_skip_ssh_option_token(text, i, limit):
    ws = i
    we = _pgrep_skip_one_word(text, i, limit)
    word = _pgrep_bare_word(text[ws:we])
    if not word.startswith("-") or word == "-":
        return we
    if word.startswith("--"):
        return we
    if word == "-o":
        j = _pgrep_skip_space(text, we)
        if j < limit:
            return _pgrep_skip_one_word(text, j, limit)
        return we
    if word.startswith("-o") and len(word) > 2:
        return we
    opt = word[1:]
    k = 0
    while k < len(opt):
        ch = opt[k]
        k += 1
        if ch in _PGREP_SSH_OPT_WITH_ARG:
            if k < len(opt):
                return we
            j = _pgrep_skip_space(text, we)
            if j < limit:
                return _pgrep_skip_one_word(text, j, limit)
            return we
    return we


def _pgrep_skip_ssh_prefix_after_command(text, i, limit):
    while i < limit:
        i = _pgrep_skip_space(text, i)
        if i >= limit or text[i] != "-":
            break
        i = _pgrep_skip_ssh_option_token(text, i, limit)
    i = _pgrep_skip_space(text, i)
    if i >= limit:
        return None
    i = _pgrep_skip_one_word(text, i, limit)
    while i < limit:
        i = _pgrep_skip_space(text, i)
        if i >= limit or text[i] != "-":
            break
        i = _pgrep_skip_ssh_option_token(text, i, limit)
    i = _pgrep_skip_space(text, i)
    if i >= limit:
        return limit
    return i




def _pgrep_skip_heredoc_pipe_env_prefix(text, i, limit):
    assign = re.compile(r"(\w+)=(?:[^\s\"';|&]+|\"(?:\\.|[^\"\\])*\"|'[^']*')")
    while i < limit:
        i = _pgrep_skip_space(text, i)
        if i >= limit:
            return i
        ws = i
        we = _pgrep_skip_one_word(text, i, limit)
        if _pgrep_bare_word(text[ws:we]).lower() != "env":
            return i
        i = we
        while i < limit:
            i = _pgrep_skip_space(text, i)
            if i >= limit:
                break
            if text[i] == "-":
                i = _pgrep_skip_one_word(text, i, limit)
                continue
            m = assign.match(text[i:limit])
            if m:
                i += m.end()
                continue
            break
    return i


def _pgrep_heredoc_opener_line_pipes_to_shell(text, after_delim, line_end):
    i = after_delim
    sq = dq = False
    shell_words = frozenset(("bash", "sh", "zsh", "dash", "ksh"))
    while i < line_end:
        if sq:
            if text[i] == "'":
                sq = False
            i += 1
            continue
        if dq:
            if text[i] == "\\" and i + 1 < line_end:
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
        if text[i] == "#" and _pgrep_hash_starts_comment(text, i):
            return False
        if text[i] == "|":
            j = _pgrep_skip_space(text, i + 1)
            if j >= line_end:
                return False
            j = _pgrep_skip_heredoc_pipe_env_prefix(text, j, line_end)
            if j >= line_end:
                return False
            ws = j
            we = _pgrep_skip_one_word(text, j, line_end)
            base = _pgrep_bare_word(text[ws:we]).rsplit("/", 1)[-1].lower()
            if base in shell_words:
                return True
            if base == "ssh":
                rem = _pgrep_skip_ssh_prefix_after_command(text, we, line_end)
                return rem is not None and rem >= line_end
            return False
        i += 1
    return False


_PGREP_HEREDOC_BODIES_CACHE = {}


def _pgrep_clear_heredoc_bodies_cache():
    _PGREP_HEREDOC_BODIES_CACHE.clear()


def _pgrep_heredoc_bodies_for_text(text):
    cached = _PGREP_HEREDOC_BODIES_CACHE.get(text)
    if cached is not None:
        return cached
    cached = _pgrep_collect_heredoc_bodies(text)
    if len(_PGREP_HEREDOC_BODIES_CACHE) > 16:
        _PGREP_HEREDOC_BODIES_CACHE.clear()
    _PGREP_HEREDOC_BODIES_CACHE[text] = cached
    return cached


def _pgrep_iter_heredoc_bodies(text):
    for item in _pgrep_heredoc_bodies_for_text(text):
        yield item


def _pgrep_collect_heredoc_bodies(text):
    bodies = []
    n = len(text)
    i = 0
    sq = dq = False
    cmd_start = 0
    quoted_cat_subst_exec = False
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
            if text[i : i + 2] == "<<" and (i == 0 or text[i - 1] in " \t\n;&|("):
                if "$(" in text[cmd_start:i] and _pgrep_heredoc_cat_subst_for_exec(
                    text, cmd_start, i
                ):
                    quoted_cat_subst_exec = True
                else:
                    i += 2
                    continue
            else:
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
            parsed = _pgrep_parse_heredoc_delim_ex(text, i)
            if not parsed:
                i += 2
                continue
            delim, strip_tabs, j, literal = parsed
            line_end = text.find("\n", j)
            op_line_end = line_end if line_end != -1 else n
            stdin_prog = _pgrep_heredoc_interpreter_stdin_executable(text, cmd_start, i)
            if quoted_cat_subst_exec:
                executable = True
                quoted_cat_subst_exec = False
            else:
                executable = _pgrep_heredoc_owner_executable(text, cmd_start, i)
                if not executable:
                    executable = _pgrep_heredoc_opener_line_pipes_to_shell(text, j, op_line_end)
                if not executable and "$(" in text[cmd_start:i] and _pgrep_heredoc_cat_subst_for_exec(
                    text, cmd_start, i
                ):
                    executable = True
            line_end = text.find("\n", j)
            if line_end == -1:
                body_start = n
                body_end = n
                if body_start < body_end:
                    bodies.append((body_start, body_end, executable, stdin_prog, literal))
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
                    if body_start < body_end:
                        bodies.append((body_start, body_end, executable, stdin_prog, literal))
                    i = line_term + 1 if line_term < n else n
                    cmd_start = _pgrep_skip_space(text, i)
                    break
                k = line_term + 1 if line_term < n else n
            else:
                if body_start < n:
                    bodies.append((body_start, n, executable, stdin_prog, literal))
                break
            continue
        i += 1
    return bodies

def _pgrep_iter_simple_command_spans(text):
    cache = getattr(_pgrep_iter_simple_command_spans, "_cache", None)
    if cache is None:
        cache = {}
        _pgrep_iter_simple_command_spans._cache = cache
    key = text
    hit = cache.get(key)
    if hit is not None:
        for span in hit:
            yield span
        return
    spans = []
    n = len(text)
    start = 0
    i = 0
    sq = dq = False
    subst_depth = 0
    sub_dq = sub_sq = False
    hd = None
    while i < n:
        if subst_depth > 0:
            if sub_sq:
                if text[i] == "'":
                    sub_sq = False
                i += 1
                continue
            if sub_dq:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if text[i] == '"':
                    sub_dq = False
                    i += 1
                    continue
                i += 1
                continue
            if text[i] == "'":
                sub_sq = True
                i += 1
                continue
            if text[i] == '"':
                sub_dq = True
                i += 1
                continue
            if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
                subst_depth += 1
                i += 2
                continue
            if text[i] == ")":
                subst_depth -= 1
                i += 1
                continue
            i += 1
            continue
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
                    spans.append((start, i))
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
        if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
            subst_depth = 1
            sub_dq = sub_sq = False
            i += 2
            continue
        if text.startswith("&&", i) or text.startswith("||", i):
            spans.append((start, i))
            i += 2
            start = _pgrep_skip_space(text, i)
            continue
        if c in ";\n|":
            spans.append((start, i))
            i += 1
            start = _pgrep_skip_space(text, i)
            continue
        if c == "&":
            spans.append((start, i))
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
    spans.append((start, n))
    cache[key] = spans
    if len(cache) > 32:
        cache.clear()
    for span in spans:
        yield span


def _pgrep_skip_case_header(text, i):
    n = len(text)
    while i < n:
        i = _pgrep_skip_space(text, i)
        if _PGREP_RE_IN.match(text, i):
            return _pgrep_skip_space(text, i + 2)
        i = _pgrep_skip_one_word(text, i, n)
    return i


def _pgrep_case_token_may_match(token):
    if not token:
        return True
    if "$" in token or "`" in token:
        return True
    if any(c in token for c in "*?["):
        return True
    return False


def _pgrep_case_unquote_token(token):
    """Bash quote removal for case words/patterns; (False, None) if the arm may match."""
    if _pgrep_case_token_may_match(token):
        return False, None
    i, n = 0, len(token)
    out = []
    while i < n:
        c = token[i]
        if c == "'":
            i += 1
            while i < n and token[i] != "'":
                out.append(token[i])
                i += 1
            if i < n:
                i += 1
            continue
        if c == '"':
            i += 1
            while i < n and token[i] != '"':
                if token[i] == "\\" and i + 1 < n:
                    nxt = token[i + 1]
                    if nxt in '$"`\\':
                        out.append(nxt)
                        i += 2
                        continue
                    if nxt == "\n":
                        i += 2
                        continue
                    out.append("\\")
                    out.append(nxt)
                    i += 2
                    continue
                if token[i] in "$`":
                    return False, None
                out.append(token[i])
                i += 1
            if i < n:
                i += 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(token[i + 1])
            i += 2
            continue
        out.append(c)
        i += 1
    return True, "".join(out)


def _pgrep_case_word_span(text, case_end, n):
    i = _pgrep_skip_space(text, case_end)
    w0 = i
    while i < n:
        i = _pgrep_skip_space(text, i)
        if _PGREP_RE_IN.match(text, i):
            break
        if text[i] == "'":
            i += 1
            while i < n and text[i] != "'":
                i += 1
            if i < n:
                i += 1
            continue
        if text[i] == '"':
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                i += 1
            if i < n:
                i += 1
            continue
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        j = i
        while j < n and not text[j].isspace():
            j += 1
        i = j
    return w0, i


def _pgrep_case_word_literal(text, start, end):
    w = text[start:end]
    if not w:
        return False, None
    ok, lit = _pgrep_case_unquote_token(w)
    if not ok:
        return False, None
    return True, lit


def _pgrep_case_pattern_alt_unwrap(alt):
    alt = alt.strip()
    while len(alt) >= 2 and alt[0] == "(" and alt[-1] == ")":
        inner = alt[1:-1].strip()
        if "|" in inner:
            break
        alt = inner
    return alt


def _pgrep_case_pattern_alt_plain(alt):
    alt = _pgrep_case_pattern_alt_unwrap(alt)
    if not alt:
        return False, None
    ok, lit = _pgrep_case_unquote_token(alt)
    if not ok:
        return False, None
    return True, lit


_PGREP_CASE_LITERAL_CHARS = frozenset(
    r"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.,:/=+%@\-"
)


def _pgrep_case_literal_only_after_quotes(text):
    return all(c in _PGREP_CASE_LITERAL_CHARS for c in text)


def _pgrep_case_alt_raw_allowlist_ok(raw_alt):
    if any(c in raw_alt for c in "()~{}"):
        return False
    i = 0
    n = len(raw_alt)
    while i < n:
        if raw_alt[i] == "@" and i + 1 < n and raw_alt[i + 1] == "(":
            return False
        i += 1
    return True


def _pgrep_case_split_pattern_alts(pattern):
    alts = []
    i, n, depth = 0, len(pattern), 0
    start = 0
    while i < n:
        c = pattern[i]
        if c in "'\"":
            q = c
            i += 1
            while i < n and pattern[i] != q:
                if pattern[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                i += 1
            if i < n:
                i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            if depth:
                depth -= 1
        elif c == "|" and depth == 0:
            alts.append(pattern[start:i])
            start = i + 1
        i += 1
    alts.append(pattern[start:])
    return alts


def _pgrep_case_arm_statically_unreachable(state, pattern_text):
    if not state.word_plain or state.word_lit is None:
        return False
    if state.word_lit == "":
        return False
    if not _pgrep_case_literal_only_after_quotes(state.word_lit):
        return False
    for alt in _pgrep_case_split_pattern_alts(pattern_text):
        if not _pgrep_case_alt_raw_allowlist_ok(alt):
            return False
        ok, lit = _pgrep_case_unquote_token(_pgrep_case_pattern_alt_unwrap(alt))
        if not ok:
            return False
        if not _pgrep_case_literal_only_after_quotes(lit):
            return False
        if lit.casefold() == state.word_lit.casefold():
            return False
    return True


def _pgrep_subst_case_finish_pattern(state, text, close_i):
    inner = text[state.pat_start:close_i]
    if (
        close_i < len(text)
        and text[close_i] == ")"
        and inner.count("(") > inner.count(")")
    ):
        pat = inner + ")"
    else:
        pat = inner
    unreachable = _pgrep_case_arm_statically_unreachable(state, pat)
    state.arm_body_reachable = state.fallthrough_next or not unreachable
    state.body_mask_kill = not state.arm_body_reachable
    state.fallthrough_next = False


def _pgrep_subst_case_append_pattern_close(out, state, text, close_i):
    if not _pgrep_subst_case_close_paren_is_pattern(state, text, close_i):
        return False
    if state.in_pattern:
        out.append(")")
        return True
    if state.arm_body_reachable:
        out.append("\n")
    else:
        out.append(")")
    return True


class _PgrepSubstCaseState:
    __slots__ = (
        "phase",
        "in_pattern",
        "pat_paren",
        "word_plain",
        "word_lit",
        "pat_start",
        "fallthrough_next",
        "arm_body_reachable",
        "body_mask_kill",
    )

    def __init__(self):
        self.phase = 0
        self.in_pattern = False
        self.pat_paren = 0
        self.word_plain = False
        self.word_lit = None
        self.pat_start = 0
        self.fallthrough_next = False
        self.arm_body_reachable = False
        self.body_mask_kill = False

    def reset(self):
        self.phase = 0
        self.in_pattern = False
        self.pat_paren = 0
        self.word_plain = False
        self.word_lit = None
        self.pat_start = 0
        self.fallthrough_next = False
        self.arm_body_reachable = False


def _pgrep_shell_word_start(text, i):
    return i == 0 or text[i - 1] in " \t\n;&|(`"


def _pgrep_subst_case_try_enter(text, i, n, state):
    if state.phase != 0:
        return i
    m = _PGREP_RE_CASE.match(text, i)
    if not m or not _pgrep_shell_word_start(text, i):
        return i
    p = m.end()
    w0, in_i = _pgrep_case_word_span(text, p, n)
    w1 = in_i
    while w1 > w0 and text[w1 - 1].isspace():
        w1 -= 1
    if w1 <= w0 or in_i >= n or not _PGREP_RE_IN.match(text, in_i):
        return i
    ni = _pgrep_skip_space(text, in_i + 2)
    wp, wl = _pgrep_case_word_literal(text, w0, w1)
    state.word_plain = wp
    state.word_lit = wl
    state.pat_start = ni
    state.fallthrough_next = False
    state.arm_body_reachable = False
    state.body_mask_kill = False
    state.phase = 2
    state.in_pattern = True
    state.pat_paren = 0
    return ni


def _pgrep_subst_case_advance(text, i, n, state):
    if state.phase != 2:
        return i
    m = _PGREP_RE_ESAC.match(text, i)
    if m:
        state.reset()
        return m.end()
    if text.startswith(";;&", i):
        state.fallthrough_next = False
        state.in_pattern = True
        state.pat_paren = 0
        state.pat_start = _pgrep_skip_space(text, i + 3)
        return i + 3
    if text.startswith(";;", i):
        state.fallthrough_next = False
        state.in_pattern = True
        state.pat_paren = 0
        state.pat_start = _pgrep_skip_space(text, i + 2)
        return i + 2
    if text.startswith(";&", i):
        if state.arm_body_reachable:
            state.fallthrough_next = True
        state.in_pattern = True
        state.pat_paren = 0
        state.pat_start = _pgrep_skip_space(text, i + 2)
        return i + 2
    return i


def _pgrep_subst_case_open_paren(state):
    if state.phase == 2 and state.in_pattern:
        state.pat_paren += 1


def _pgrep_subst_case_close_paren_is_pattern(state, text=None, close_i=None):
    if state.phase != 2 or not state.in_pattern:
        return False
    if state.pat_paren > 0:
        state.pat_paren -= 1
        if state.pat_paren > 0:
            return True
    if text is not None and close_i is not None:
        inner = text[state.pat_start:close_i]
        if (
            "(" in inner
            and close_i + 1 < len(text)
            and text[close_i + 1] == ")"
        ):
            return True
    state.in_pattern = False
    if text is not None and close_i is not None:
        _pgrep_subst_case_finish_pattern(state, text, close_i)
    return True


def _pgrep_subst_case_unquoted_step(text, i, n, state):
    if state.phase == 0:
        if text[i : i + 1].lower() != "c" or not _PGREP_RE_CASE.match(text, i):
            return None
        if not _pgrep_shell_word_start(text, i):
            return None
    ni = _pgrep_subst_case_try_enter(text, i, n, state)
    if ni != i:
        return ni
    if state.phase != 0:
        ni = _pgrep_subst_case_advance(text, i, n, state)
        if ni != i:
            return ni
    return None

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
    m = _PGREP_RE_ONE_WORD.match(text, i, limit)
    return m.end() if m else i + 1


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
    if base == "ssh":
        rem = _pgrep_skip_ssh_prefix_after_command(text, e, cmd_end)
        if rem is None or rem >= cmd_end:
            return None
        return rem, cmd_end
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
    skip_hd = _pgrep_outer_scan_skip_heredoc_body_spans(text)
    skip_hint = [0]
    i, n, dq, sq_idx = 0, len(text), False, 0
    while i < n:
        skip, sq_idx = _pgrep_sq_skip_past(sq, i, sq_idx)
        if skip is not None:
            i = skip
            continue
        in_skip, skip_hint[0] = _pgrep_pos_in_sorted_spans(i, skip_hd, skip_hint[0])
        if in_skip:
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
    ne_hd = _pgrep_backtick_data_heredoc_body_spans(text)
    ne_hint = [0]
    i, n, dq, sq_idx = 0, len(text), False, 0
    while i < n:
        skip, sq_idx = _pgrep_sq_skip_past(sq, i, sq_idx)
        if skip is not None:
            i = skip
            continue
        in_ne_hd, ne_hint[0] = _pgrep_pos_in_sorted_spans(i, ne_hd, ne_hint[0])
        if in_ne_hd:
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
            inner = _pgrep_mask_shell_comments(text[start + 1 : end - 1])
            if _pgrep_pgrep_match_in_fragment(inner, _depth=_depth + 1):
                return True
    for inner in _pgrep_each_dollar_paren(text):
        if not re.search(r"pgrep", inner, re.I):
            continue
        inner = _pgrep_mask_shell_comments(inner)
        if _pgrep_pgrep_match_in_fragment(inner, _depth=_depth + 1):
            return True
    for inner in _pgrep_each_backtick(text):
        if not re.search(r"pgrep", inner, re.I):
            continue
        inner = _pgrep_mask_shell_comments(inner)
        if _pgrep_pgrep_match_in_fragment(inner, _depth=_depth + 1):
            return True
    for body_start, body_end, executable, stdin_prog, literal in _pgrep_iter_heredoc_bodies(raw):
        body = raw[body_start:body_end]
        if executable:
            masked_body = _pgrep_mask_shell_comments(body)
            if _pgrep_pgrep_match_in_fragment(masked_body, _depth=_depth + 1):
                return True
            if _pgrep_pgrep_match_shell_script_lines(masked_body):
                return True
        elif stdin_prog:
            if _pgrep_pgrep_match_interpreter_stdin_body(body):
                return True
        elif not literal:
            if _pgrep_pgrep_match_heredoc_body_substitutions(body):
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


def _pgrep_mark_exec_quotes_in_remote_region(text, rem, cmd_end, out):
    i = rem
    while i < cmd_end:
        i = _pgrep_skip_space(text, i)
        if i >= cmd_end:
            return
        if text[i] in "'\"":
            return
        ws = i
        we = _pgrep_skip_one_word(text, i, cmd_end)
        if we <= ws:
            return
        base = _pgrep_bare_word(text[ws:we]).rsplit("/", 1)[-1].lower()
        if base in _PGREP_SHELL_WORDS:
            _pgrep_mark_dash_c_exec_quote(text, we, cmd_end, out)
            return
        if base == "eval":
            j = _pgrep_skip_space(text, we)
            if j < cmd_end and text[j] in "'\"":
                out.add(j)
            return
        if base in _PGREP_DASH_C_OPENERS:
            _pgrep_mark_dash_c_exec_quote(text, we, cmd_end, out)
            return
        i = we


def _pgrep_mark_ssh_exec_quote(text, i, cmd_end, out):
    rem = _pgrep_skip_ssh_prefix_after_command(text, i, cmd_end)
    if rem is None or rem >= cmd_end:
        return
    rem = _pgrep_skip_space(text, rem)
    if rem < cmd_end and text[rem] in "'\"":
        out.add(rem)
        return
    _pgrep_mark_exec_quotes_in_remote_region(text, rem, cmd_end, out)


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
    def _maybe_enqueue(inner, off):
        if len(pending) >= _PGREP_EXEC_QUOTE_PENDING_MAX:
            return
        if ("'" in inner or '"' in inner) and (
            "pgrep" in inner.lower() or "$(" not in inner
        ):
            pending.append((origin + off, inner))

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
                _maybe_enqueue(inner, i + 2)
                i = j
                continue
            if chunk[i] == "`":
                inner, j, sq_idx = _pgrep_read_backtick(chunk, i, sq, sq_idx)
                if inner is not None:
                    _maybe_enqueue(inner, i + 1)
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
            _maybe_enqueue(inner, i + 2)
            i = j
            continue
        if chunk[i] == "`":
            inner, j, sq_idx = _pgrep_read_backtick(chunk, i, sq, sq_idx)
            if inner is not None:
                _maybe_enqueue(inner, i + 1)
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
    while idx < len(pending) and idx < _PGREP_EXEC_QUOTE_PENDING_MAX:
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
    hd_bodies = _pgrep_heredoc_body_spans(text)
    hd_bi = 0
    while i < n:
        skip, hd_bi = _pgrep_skip_past_heredoc_body(text, i, hd_bodies, hd_bi)
        if skip is not None:
            i = skip
            continue
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




def _pgrep_text_outside_nonexecutable_heredoc_bodies(text):
    parts = []
    pos = 0
    for body_start, body_end, executable, stdin_prog, literal in _pgrep_iter_heredoc_bodies(text):
        if executable or stdin_prog:
            continue
        parts.append(text[pos:body_start])
        pos = body_end
    parts.append(text[pos:])
    return "".join(parts)

def _pgrep_blank_nonexecutable_heredoc_bodies(text):
    parts = []
    pos = 0
    for body_start, body_end, executable, stdin_prog, literal in _pgrep_iter_heredoc_bodies(text):
        if executable or stdin_prog:
            continue
        parts.append(text[pos:body_start])
        body = text[body_start:body_end]
        if body:
            parts.append(re.sub(r"[^\n]", " ", body))
        pos = body_end
    parts.append(text[pos:])
    return "".join(parts)




def _pgrep_pgrep_match_shell_script_lines(text):
    for line in _pgrep_mask_shell_comments(text).split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(
            r"(?:\S+/)*pgrep\b(.*)$",
            line,
            re.I,
        )
        if not m:
            continue
        seg = m.group(1)
        if pgrep_segment_has_full_flag(seg):
            return True
    return False


def _pgrep_prepare_scan_text(text):
    chunk = pgrep_obfuscation_fold(text)
    chunk = _pgrep_mask_shell_comments_safe(chunk)
    for _ in range(_PGREP_SUBST_EXPAND_MAX):
        nxt = _pgrep_process_command_substitutions(chunk, pgrep_obfuscation_fold)
        if nxt == chunk:
            break
        chunk = nxt
    chunk = _pgrep_blank_nonexecutable_heredoc_bodies(chunk)
    return _pgrep_blank_data_quotes(chunk)


_PGREP_ASSIGNMENT = re.compile(
    r"(\w+)=(?:[^\s\"';|&]+|\"(?:\\.|[^\"\\])*\"|'[^']*')"
)


def _pgrep_unquote_assign_value(val):
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
        return val[1:-1]
    return val


def _pgrep_assignment_at(text, i, limit):
    m = _PGREP_ASSIGNMENT.match(text, i, limit)
    if not m:
        return None
    name = m.group(1)
    val = text[i + len(name) + 1 : m.end()]
    return name, val, m.end()


def _pgrep_apply_var_binding(name, val, binary, script, flag_vars):
    binary.discard(name)
    script.discard(name)
    flag_vars.discard(name)
    ref = _pgrep_lifecycle_var_ref_name(val)
    if ref is not None:
        if ref in script:
            script.add(name)
            return
        if ref in binary:
            binary.add(name)
            return
        if ref in flag_vars:
            flag_vars.add(name)
            return
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
    if len(w) > 128:
        head = w.lstrip()[:48].lower()
        if head != "pgrep" and not head.endswith("/pgrep") and "/pgrep" not in head:
            return False
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

def pgrep_full_match(text, cmd=None):
    _pgrep_clear_heredoc_bodies_cache()
    if _pgrep_fail_closed_after_shell_fault(text, cmd=cmd):
        return True
    shell = cmd if isinstance(cmd, str) and cmd.strip() else text
    if _pgrep_match_expandable_data_heredoc_substitutions(shell):
        return True
    for body_start, body_end, executable, stdin_prog, literal in _pgrep_iter_heredoc_bodies(
        shell
    ):
        if stdin_prog and not executable:
            if _pgrep_pgrep_match_interpreter_stdin_body(shell[body_start:body_end]):
                return True
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
    cmd = None
    try:
        cmd = (p.get("tool_input") or {}).get("command")
        if isinstance(cmd, list):
            cmd = " ".join(c for c in cmd if isinstance(c, str))
    except Exception:
        pass
    try:
        pgrep_cmd = cmd if isinstance(cmd, str) else None
        shell_for_pgrep = cmd if isinstance(cmd, str) and cmd.strip() else text
        pgrep_scan = _pgrep_blank_nonexecutable_heredoc_bodies(shell_for_pgrep)
        if isinstance(cmd, str) and "<<" in cmd:
            head = cmd.split("<<", 1)[0]
            if any(rx.search(re.split(r"&&|\|\||;", head)[-1]) for rx in HEREDOC_EXEMPT):
                tail = _pgrep_tail_after_first_heredoc(cmd)
                if not tail:
                    pgrep_scan = head
        if pgrep_full_match(pgrep_scan, cmd=pgrep_cmd):
            verdict(True, PGREP_F_DENY)
    except Exception:
        pass
    if any(rx.search(text) for rx in ELECTRON_CACHE):
        verdict(True,
            "[electron-cache] ~/Library/Caches/electron and electron-builder hold the Electron "
            "runtime that fork-stage.sh installs bb from, offline and checksum-verified. Without "
            "them the next bb install refuses. Free disk elsewhere: pnpm store prune, node-gyp, "
            "pip or Homebrew caches, ~/.cache, or merged worktrees.")
    shell_for_lifecycle = cmd if isinstance(cmd, str) and cmd.strip() else text
    lifecycle_scan = _pgrep_text_outside_nonexecutable_heredoc_bodies(shell_for_lifecycle)
    lifecycle_block = kills_bb_pid(lifecycle_scan)
    if not lifecycle_block:
        lifecycle_block = any(rx.search(lifecycle_scan) for rx in BB_LIFECYCLE[:-1])
    if not lifecycle_block:
        lifecycle_block = _pgrep_lifecycle_pkill_match(lifecycle_scan)
    if lifecycle_block:
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

if __name__ == "__main__":
    try:
        main()
    except Exception:
        verdict(False)   # fail open, always
