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
BB_LIFECYCLE_PKILL = re.compile(
    r'(?:^|[;&|(`\n])\s*(?:(?:sudo|env|command|exec|nohup)\s+(?:-\S+\s+|\w+=\S*\s+)*)*(?:\w+=\S*\s+)*(?:\S*/)?pkill(?=\s|$|[;&|)`])'
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


def _pgrep_python_stdin_shell_invoke(body):
    import tokenize
    from io import BytesIO

    try:
        tokens = list(
            tokenize.tokenize(
                BytesIO(body.encode("utf-8", "surrogateescape")).readline
            )
        )
    except (tokenize.TokenError, SyntaxError, UnicodeError):
        return False

    def _collect_call_args(open_idx):
        idx = open_idx
        if idx >= len(tokens) or tokens[idx].type != tokenize.OP or tokens[idx].string != "(":
            return None
        idx += 1
        depth = 1
        parts = []
        while idx < len(tokens) and depth:
            tok = tokens[idx]
            if tok.type == tokenize.OP and tok.string == "(":
                depth += 1
            elif tok.type == tokenize.OP and tok.string == ")":
                depth -= 1
                if depth == 0:
                    break
            elif tok.type == tokenize.STRING:
                parts.append(tok.string)
            elif tok.type == tokenize.NAME and depth == 1:
                parts.append(tok.string)
            idx += 1
        return " ".join(parts) if parts else None

    def _snippet_hits_pgrep_or_pkill(snippet):
        if not snippet:
            return False
        import ast

        raw = snippet.strip()
        try:
            if raw.startswith(("\"", "'")):
                raw = ast.literal_eval(raw)
        except Exception:
            raw = raw.strip("\"'")
        folded = pgrep_obfuscation_fold(_pgrep_mask_shell_comments(raw))
        if PGREP_WORD.search(folded):
            seg = re.match(r"[^\n;&|]*", folded.lstrip())
            if seg and (
                pgrep_segment_has_full_flag(seg.group(0))
                or _pgrep_lifecycle_pkill_match(raw)
            ):
                return True
        return bool(_pgrep_lifecycle_pkill_match(raw))

    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if (
            tok.type == tokenize.NAME
            and tok.string == "os"
            and idx + 2 < len(tokens)
            and tokens[idx + 1].type == tokenize.OP
            and tokens[idx + 1].string == "."
            and tokens[idx + 2].type == tokenize.NAME
            and tokens[idx + 2].string == "system"
        ):
            snippet = _collect_call_args(idx + 3)
            if snippet and _snippet_hits_pgrep_or_pkill(snippet):
                return True
        if tok.type == tokenize.NAME and tok.string == "subprocess":
            j = idx + 1
            while j + 1 < len(tokens):
                if tokens[j].type != tokenize.OP or tokens[j].string != ".":
                    break
                if tokens[j + 1].type != tokenize.NAME:
                    break
                meth = tokens[j + 1].string
                if meth not in ("run", "call", "Popen", "check_output"):
                    j += 2
                    continue
                args_start = j + 2
                if (
                    args_start < len(tokens)
                    and tokens[args_start].type == tokenize.OP
                    and tokens[args_start].string == "("
                ):
                    blob = _collect_call_args(args_start)
                    if blob and _snippet_hits_pgrep_or_pkill(blob):
                        return True
                    if blob and re.search(r"['\"]pgrep['\"]", blob, re.I) and re.search(
                        r"['\"]-f['\"]", blob
                    ):
                        return True
                break
        idx += 1
    return False


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
        if text[j] == "'":
            sq_local = True
            j += 1
            continue
        if text[j] == '"':
            dq = True
            j += 1
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


def _pgrep_heredoc_body_spans(text):
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
    if "#" not in text and "$(" not in text and "`" not in text:
        return text
    sq = _pgrep_single_quote_spans(text)
    out = []
    i, n, dq, sq_idx = 0, len(text), False, 0
    subst_depth = 0
    sub_dq = sub_sq = False

    def _mask_hash_run():
        nonlocal i
        while i < n and text[i] != "\n":
            out.append(" ")
            i += 1

    while i < n:
        skip, sq_idx = _pgrep_sq_skip_past(sq, i, sq_idx)
        if skip is not None:
            out.append(text[i:skip])
            i = skip
            continue
        if subst_depth > 0:
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
                out.append(text[i])
                if text[i] == '"':
                    sub_dq = False
                i += 1
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
                subst_depth += 1
                i += 2
                continue
            if text[i] == ")":
                out.append(text[i])
                subst_depth -= 1
                i += 1
                continue
            if text[i] == "#" and _pgrep_hash_starts_comment(text, i):
                _mask_hash_run()
                continue
            if text[i] == "`":
                inner, j, sq_idx = _pgrep_read_backtick(text, i, sq, sq_idx)
                if inner is None:
                    out.append(text[i:])
                    break
                if "#" in inner:
                    inner = _pgrep_mask_lifecycle_comments_linear(inner)
                out.append("`" + inner + "`")
                i = j
                continue
            out.append(text[i])
            i += 1
            continue
        if dq:
            if text[i] == "\\" and i + 1 < n:
                out.append(text[i : i + 2])
                i += 2
                continue
            if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
                out.append("$(")
                subst_depth = 1
                sub_dq = sub_sq = False
                i += 2
                continue
            if text[i] == '"':
                out.append(text[i])
                dq = False
                i += 1
                continue
            if text[i] == "`":
                inner, j, sq_idx = _pgrep_read_backtick(text, i, sq, sq_idx)
                if inner is None:
                    out.append(text[i:])
                    break
                if "#" in inner:
                    inner = _pgrep_mask_lifecycle_comments_linear(inner)
                out.append("`" + inner + "`")
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
            _mask_hash_run()
            continue
        if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
            out.append("$(")
            subst_depth = 1
            sub_dq = sub_sq = False
            i += 2
            continue
        if text[i] == "`":
            inner, j, sq_idx = _pgrep_read_backtick(text, i, sq, sq_idx)
            if inner is None:
                out.append(text[i:])
                break
            if "#" in inner:
                inner = _pgrep_mask_lifecycle_comments_linear(inner)
            out.append("`" + inner + "`")
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _pgrep_mask_lifecycle_comments(text):
    try:
        if "#" not in text and "$(" not in text:
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


def _pgrep_pkill_pos_in_nonexec_quote(text, pos):
    for start, end, is_exec in _pgrep_iter_quoted_spans_meta(text):
        if is_exec or text[start] != "'":
            continue
        if end <= start + 1 or text[end - 1] != "'":
            continue
        if start + 1 <= pos < end - 1:
            return True
    return False


def _pgrep_lifecycle_pkill_word_match(text, masked):
    for m in BB_LIFECYCLE_PKILL.finditer(masked):
        if not _pgrep_pkill_pos_in_nonexec_quote(text, m.start()):
            return True
    return False


def _pgrep_lifecycle_pkill_match(text):
    masked = _pgrep_mask_lifecycle_comments(text)
    if _pgrep_lifecycle_pkill_word_match(text, masked):
        return True
    for cmd_start, cmd_end in _pgrep_iter_simple_command_spans(text):
        for ls, le in _pgrep_iter_launched_command_regions(text, cmd_start, cmd_end):
            chunk = _pgrep_mask_lifecycle_comments(text[ls:le])
            if _pgrep_lifecycle_pkill_word_match(text[ls:le], chunk):
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



def _pgrep_ssh_remote_shell_reads_heredoc(text, cmd_start, op_start):
    i = cmd_start
    while i < op_start:
        i = _pgrep_skip_space(text, i)
        if i >= op_start:
            break
        ws = i
        we = _pgrep_skip_one_word(text, i, op_start)
        if ws >= we:
            break
        if _pgrep_bare_word(text[ws:we]).rsplit("/", 1)[-1].lower() != "ssh":
            i = we
            continue
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
    return False


def _pgrep_heredoc_cat_subst_for_exec(text, cmd_start, op_start):
    line_start = text.rfind("\n", 0, op_start) + 1
    op_line = text[line_start:op_start]
    if not re.search(r"\$\(\s*(?:\S+/)*(?:cat|tee)\s*<<", op_line, re.I):
        return False
    if re.search(r"\bcat\s*>|\btee\s+[^<\s]", op_line):
        return False
    tokens = _pgrep_word_tokens_before(text, cmd_start, op_start)
    if not tokens:
        return False
    base = tokens[0].rsplit("/", 1)[-1].lower()
    if base == "eval":
        return True
    if base in ("bash", "sh", "zsh", "dash", "ksh"):
        for tok in tokens[1:]:
            bare = _pgrep_bare_word(tok)
            if bare == "-c" or _pgrep_word_is_dash_c_flag(tok):
                return True
    return False


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
            if not (
                text[i : i + 2] == "<<"
                and (i == 0 or text[i - 1] in " \t\n;&|(")
            ):
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
            executable = _pgrep_heredoc_owner_executable(text, cmd_start, i)
            if not executable:
                executable = _pgrep_heredoc_opener_line_pipes_to_shell(text, j, op_line_end)
            if not executable and _pgrep_heredoc_cat_subst_for_exec(text, cmd_start, i):
                executable = True
            line_end = text.find("\n", j)
            if line_end == -1:
                body_start = n
                body_end = n
                if body_start < body_end:
                    yield body_start, body_end, executable, stdin_prog, literal
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
                        yield body_start, body_end, executable, stdin_prog, literal
                    i = line_term + 1 if line_term < n else n
                    break
                k = line_term + 1 if line_term < n else n
            else:
                if body_start < n:
                    yield body_start, n, executable, stdin_prog, literal
                break
            continue
        i += 1


def _pgrep_iter_simple_command_spans(text):
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
        if text.startswith("$", i) and i + 1 < n and text[i + 1] == "(":
            subst_depth = 1
            sub_dq = sub_sq = False
            i += 2
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


def _pgrep_blank_nonexecutable_heredoc_bodies(text):
    chars = list(text)
    for body_start, body_end, executable, stdin_prog, literal in _pgrep_iter_heredoc_bodies(text):
        if executable or not literal:
            continue
        for k in range(body_start, body_end):
            if chars[k] != "\n":
                chars[k] = " "
    return "".join(chars)




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
    if _pgrep_fail_closed_after_shell_fault(text, cmd=cmd):
        return True
    shell = cmd if isinstance(cmd, str) and cmd.strip() else text
    if _pgrep_match_expandable_data_heredoc_substitutions(shell):
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
        # A heredoc that only writes a file (cat > /tmp/x <<'EOF') executes
        # nothing; scan just the command before it, as the heredoc rule does.
        if isinstance(cmd, str) and "<<" in cmd:
            head = cmd.split("<<", 1)[0]
            if any(rx.search(re.split(r"&&|\|\||;", head)[-1]) for rx in HEREDOC_EXEMPT):
                tail = _pgrep_tail_after_first_heredoc(cmd)
                text = head + ("\n" + tail if tail else "")
    except Exception:
        pass
    try:
        pgrep_cmd = cmd if isinstance(cmd, str) else None
        if pgrep_full_match(text, cmd=pgrep_cmd):
            verdict(True, PGREP_F_DENY)
    except Exception:
        pass
    if any(rx.search(text) for rx in ELECTRON_CACHE):
        verdict(True,
            "[electron-cache] ~/Library/Caches/electron and electron-builder hold the Electron "
            "runtime that fork-stage.sh installs bb from, offline and checksum-verified. Without "
            "them the next bb install refuses. Free disk elsewhere: pnpm store prune, node-gyp, "
            "pip or Homebrew caches, ~/.cache, or merged worktrees.")
    lifecycle_block = kills_bb_pid(text)
    if not lifecycle_block:
        lifecycle_block = any(rx.search(text) for rx in BB_LIFECYCLE[:-1])
    if not lifecycle_block:
        lifecycle_block = _pgrep_lifecycle_pkill_match(text)
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
