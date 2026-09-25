"""Find the `bb thread spawn|create|tell|message` invocations in a shell script.

The gate matched the dispatch words anywhere in a command, so a quoted string
that merely MENTIONED them was treated as a dispatch: on 2026-09-25 it denied
    printf '%s\n' "...a REAL undeclared bb thread tell from this session was DENIED..." >> plan.md
Logging or grepping about dispatches is exactly what a coordinator does, and
a false deny pushes it to reword evidence to get past the gate.

Here a dispatch is only a simple command whose COMMAND WORD is bb, a path
ending in /bb, or $BB_CLI / ${BB_CLI}, followed by `thread` and a dispatch
verb. Scripts are split into simple commands at unquoted ; && || | & newlines
and parentheses; $(...) and `...` contents are commands of their own; comments
are dropped; heredoc bodies are data attached to the command that declared
them. Words come from shlex. Leading assignments and the wrappers env,
command, exec, nohup and time are skipped. `sh|bash|zsh|dash|ksh -c '<script>'`,
`eval <words>` and a shell reading a heredoc (`bash <<EOF`) are parsed
recursively.

Not covered (documented in SKILL.md known limits): a script run from a file
(`sh dispatch.sh`), a script piped into a shell (`cat x | sh`), and a bb
invoked through an alias, a function or a variable other than BB_CLI.
"""
import re
import shlex

DISPATCH_VERBS = ("spawn", "create", "tell", "message")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
WRAPPERS = {"command", "exec", "nohup", "time", "builtin"}
PREFIX_WORDS = {"!", "{", "}", "then", "do", "else", "elif", "if", "while", "until"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC = re.compile(r"<<(-?)[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
MAX_DEPTH = 4


class Command:
    __slots__ = ("text", "heredocs")

    def __init__(self):
        self.text = []
        self.heredocs = []

    def string(self):
        return "".join(self.text).strip()


def _matching(s, k, open_ch="(", close_ch=")"):
    """Index of the bracket closing s[k], respecting quotes and heredoc
    bodies (a brief's "don't" must not open a quote); len-1 if none."""
    depth, q, i = 0, None, k
    delims = []
    while i < len(s):
        ch = s[i]
        if ch == "\n" and not q and delims:
            i += 1
            for delim, strip in delims:
                while i < len(s):
                    j = s.find("\n", i)
                    line = s[i:] if j < 0 else s[i:j]
                    i = len(s) if j < 0 else j + 1
                    if (line.lstrip("\t") if strip else line) == delim:
                        break
            delims = []
            continue
        if not q and s.startswith("<<", i) and not s.startswith("<<<", i):
            m = HEREDOC.match(s, i)
            if m:
                delims.append((m.group(3), m.group(1) == "-"))
                i = m.end()
                continue
        if q:
            if ch == "\\" and q == '"':
                i += 2
                continue
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
        elif ch == "\\":
            i += 2
            continue
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(s) - 1


def split_script(script, depth=0):
    """Split a shell script into Command objects (simple commands)."""
    out = []
    cur = Command()
    pending = []  # (delimiter, strip_tabs, owner)
    i, n = 0, len(script)
    quote = None

    def push():
        nonlocal cur
        if cur.string():
            out.append(cur)
        cur = Command()

    def substitute(start, end, inner):
        # The substitution stays in the outer word as text, and its contents
        # are commands of their own.
        cur.text.append(script[start:end + 1])
        if depth < MAX_DEPTH:
            out.extend(split_script(inner, depth + 1))

    while i < n:
        c = script[i]
        if quote == "'":
            cur.text.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            cur.text.append(script[i:i + 2])
            i += 2
            continue
        if script.startswith("$((", i):
            j = _matching(script, i + 1)
            cur.text.append(script[i:j + 1])
            i = j + 1
            continue
        if script.startswith("$(", i):
            j = _matching(script, i + 1)
            substitute(i, j, script[i + 2:j])
            i = j + 1
            continue
        if c == "`":
            j = script.find("`", i + 1)
            j = n - 1 if j < 0 else j
            substitute(i, j, script[i + 1:j])
            i = j + 1
            continue
        if script.startswith("${", i):
            j = _matching(script, i + 1, "{", "}")
            cur.text.append(script[i:j + 1])
            i = j + 1
            continue
        if quote == '"':
            cur.text.append(c)
            if c == '"':
                quote = None
            i += 1
            continue
        # Unquoted from here.
        if c in "'\"":
            quote = c
            cur.text.append(c)
            i += 1
            continue
        if c == "#" and (not cur.text or cur.text[-1][-1:].isspace()):
            j = script.find("\n", i)
            i = n if j < 0 else j
            continue
        if script.startswith("<<<", i):
            cur.text.append("<<<")  # a here-string is a word, not a heredoc
            i += 3
            continue
        if script.startswith("<<", i):
            m = HEREDOC.match(script, i)
            if m:
                pending.append((m.group(3), m.group(1) == "-", cur))
                cur.text.append(m.group(0))
                i = m.end()
                continue
        if c == "\n":
            push()
            i += 1
            for delim, strip, owner in pending:
                body = []
                while i < n:
                    j = script.find("\n", i)
                    line = script[i:] if j < 0 else script[i:j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if strip else line) == delim:
                        break
                    body.append(line)
                owner.heredocs.append("\n".join(body))
            pending.clear()
            continue
        if c == "&" and (script[i - 1:i] == ">" or script[i + 1:i + 2] == ">"):
            cur.text.append(c)  # 2>&1, &> file: a redirection, not a separator
            i += 1
            continue
        if c in ";&|()":
            push()
            i += 1
            continue
        cur.text.append(c)
        i += 1
    push()
    return out


def words(text):
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return text.split()


def _command_word(w):
    """Index of the command word after assignments, prefixes and wrappers."""
    i = 0
    while i < len(w):
        t = w[i]
        if t in PREFIX_WORDS or ASSIGNMENT.match(t):
            i += 1
            continue
        if t == "env":
            i += 1
            while i < len(w) and (w[i].startswith("-") or ASSIGNMENT.match(w[i])):
                i += 2 if w[i] in ("-u", "--unset", "-C", "--chdir", "-S") else 1
            continue
        if t in WRAPPERS:
            i += 1
            while i < len(w) and w[i].startswith("-"):
                i += 1
            continue
        return i
    return None


def is_bb(word):
    return word in ("$BB_CLI", "${BB_CLI}") or word.rsplit("/", 1)[-1] == "bb"


def dispatches(script, depth=0):
    """[(command_text, heredoc_bodies, verb)] for each bb thread dispatch in the script."""
    found = []
    for cmd in split_script(script, depth):
        text = cmd.string()
        w = words(text)
        k = _command_word(w)
        if k is None:
            continue
        head, rest = w[k], w[k + 1:]
        base = head.rsplit("/", 1)[-1]
        if base in SHELLS and depth < MAX_DEPTH:
            inner = None
            for j, a in enumerate(rest):
                if a.startswith("-") and not a.startswith("--") and "c" in a[1:]:
                    inner = rest[j + 1] if j + 1 < len(rest) else None
                    break
            scripts = [inner] if inner is not None else list(cmd.heredocs)
            for s in scripts:
                found.extend(dispatches(s, depth + 1))
            continue
        if base == "eval" and depth < MAX_DEPTH:
            found.extend(dispatches(" ".join(rest), depth + 1))
            continue
        if not is_bb(head):
            continue
        # `thread` is the subcommand, after at most a few global options
        # (`bb --json thread tell`, `bb --host h thread spawn`).
        for j, a in enumerate(rest[:4]):
            if a == "thread":
                if j + 1 < len(rest) and rest[j + 1] in DISPATCH_VERBS:
                    found.append((text, list(cmd.heredocs), rest[j + 1]))
                break
            if not a.startswith("-") and not (j and rest[j - 1].startswith("-")):
                break
    return found
