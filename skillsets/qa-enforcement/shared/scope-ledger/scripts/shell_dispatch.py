"""Find the `bb thread spawn|create|tell|message` invocations in a shell script.

The gate matched the dispatch words anywhere in a command, so a quoted string
that merely MENTIONED them was treated as a dispatch: on 2026-09-25 it denied
    printf '%s\n' "...a REAL undeclared bb thread tell from this session was DENIED..." >> plan.md
Logging or grepping about dispatches is exactly what a coordinator does, and
a false deny pushes it to reword evidence to get past the gate.

Here a dispatch is only a simple command that RUNS bb (command word bb, a path
ending in /bb, or $BB_CLI / ${BB_CLI}), followed by `thread` and a dispatch
verb. Scripts are split into simple commands at unquoted ; && || | & newlines
and parentheses; $(...) and `...` contents are commands of their own; comments
are dropped; heredoc bodies are data attached to the command that declared
them. Words come from shlex. Leading assignments and the wrappers env,
command, exec, nohup and time are skipped, and bb as an unquoted word after
any other command (timeout, xargs, nice, sudo, find -exec) counts. `sh|bash|zsh|dash|ksh -c '<script>'`,
`eval <words>` and a shell reading a heredoc (`bash <<EOF`) are parsed
recursively.

Review r1 (2026-09-25) added: the command word is case-folded (`BB` runs bb
on a case-insensitive filesystem); `${VAR:-bb}` resolves to its default; a
command word that is a variable or a command substitution (`$B`,
`$(printf bb)`) counts when a dispatch verb follows it; a here-string fed to a
shell (`bash <<< '...'`), `env -S '...'`, and a process substitution a shell
reads (`bash <(echo '...')`, `source <(...)`) are parsed as scripts; and
`xargs [opts] bb` is a dispatch, since its arguments arrive on stdin.

Review r2b (2026-09-26) added: `thread interactions respond` (its --value is
free text for the thread) and `thread interactions answer --text`, and
`fleet member-add --concern` (the concern goes into every member's
instructions); an answer that only picks offered choices (--choice), and a
member-add without a concern, carry no new text. ANSI-C quoting (`$'tell'`)
is decoded before matching.

Review r2c (2026-09-26) added the plugin groups: `automation create|update`
with --prompt (an agent runs it when due; --target-thread re-prompts an
existing thread) or --script/--script-file (scope-gate.py scans the script
for dispatches), `automation run|resume` and an update that retargets or
reschedules (the stored prompt or script fires; scope-gate.py reads it from
bb), and `instructions set` (custom instructions injected into every agent).
Only a bare `bb <verb path> --help|-h` passes as a help request.

Dispatch verbs are every bb verb that hands a thread new text to act on
(`bb thread --help`, `bb fleet --help`, 2026-09-25): thread spawn|create|fork|
tell|message|edit-message, thread queue create|update|send, thread
interactions answer (--text)|respond, and fleet group-create|task-add|advise
and member-add (--concern), automation create|update|run|resume, and
instructions set. scope-gate.py selftest walks the installed bb's help, from
every core and plugin command group and nested groups included, for a
text-carrying verb missing here.

Not covered (documented in SKILL.md known limits): a script run from a file
(`sh dispatch.sh`), a script piped into a shell (`cat x | sh`), a command
given to a wrapper as one quoted string (`watch 'bb thread tell ...'`,
`ssh host 'bb ...'`), and a bb invoked through an alias or a function.
"""
import re
import shlex

THREAD_VERBS = ("spawn", "create", "fork", "tell", "message", "edit-message")
QUEUE_VERBS = ("create", "update", "send")
FLEET_VERBS = ("group-create", "task-add", "advise")
# Gated only when one of the flags is given (None: always): without them they
# carry no new text for a thread. An automation's --prompt is the prompt an
# agent runs when it is due (--target-thread re-prompts an existing thread),
# and its --script/--script-file is a script bb runs then; run, resume and a
# retarget or reschedule (--target-thread, --cron, --at, --in) fire the text
# the automation already stores, which scope-gate.py reads from bb. Custom
# instructions (`instructions set <text...>`) are injected into every agent.
CONDITIONAL_VERBS = {"thread interactions answer": ("--text",), "thread interactions respond": None,
                     "fleet member-add": ("--concern",),
                     "automation create": ("--prompt", "--script", "--script-file"),
                     "automation update": ("--prompt", "--script", "--script-file",
                                           "--target-thread", "--cron", "--at", "--in"),
                     "automation run": None, "automation resume": None,
                     "instructions set": None}
GROUPS = ("thread", "fleet", "automation", "instructions")
HELP_WORDS = ("--help", "-h")
DISPATCH_VERBS = THREAD_VERBS  # kept for callers of the old name
SUBST = "__SUBST__"
DEFAULTED = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*:?[-=+]([^}]*)\}$")
XARGS_ARG_OPTS = {"-I", "-i", "-n", "-P", "-L", "-l", "-d", "-E", "-e", "-s", "-a", "-J", "-R", "-S"}
VARIABLE = re.compile(
r"^\$(\{[A-Za-z_][A-Za-z0-9_]*\}|[A-Za-z_][A-Za-z0-9_]*)$")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
WRAPPERS = {"command", "exec", "nohup", "time", "builtin"}
PREFIX_WORDS = {"!", "{", "}", "then", "do", "else", "elif", "if", "while", "until"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC = re.compile(r"<<(-?)[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
MAX_DEPTH = 4


class Command:
    __slots__ = ("text", "heredocs", "procsubs")

    def __init__(self):
        self.text = []
        self.heredocs = []
        self.procsubs = []  # the inner scripts of <(...) words

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
        if script.startswith("$'", i):
            j = _ansi_end(script, i + 2)
            cur.text.append(script[i:j + 1])
            i = j + 1
            continue
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
        if script.startswith("<(", i) or script.startswith(">(", i):
            j = _matching(script, i + 1)
            cur.procsubs.append(script[i + 2:j])
            substitute(i, j, script[i + 2:j])
            i = j + 1
            continue
        if c in ";&|()":
            push()
            i += 1
            continue

        cur.text.append(c)
        i += 1
    push()
    return out


def mask(text):
    """The command text with each $(...), `...`, <(...) and >(...) replaced by
    SUBST, so shlex keeps a substitution as one word instead of splitting it."""
    out, i, n, q = [], 0, len(text), None
    while i < n:
        c = text[i]
        if q == "'":
            out.append(c)
            if c == "'":
                q = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(text[i:i + 2])
            i += 2
            continue
        if text.startswith("$(", i) or (q is None and (text.startswith("<(", i) or text.startswith(">(", i))):
            j = _matching(text, i + 1)
            out.append(SUBST)
            i = j + 1
            continue
        if c == "`":
            j = text.find("`", i + 1)
            out.append(SUBST)
            i = n if j < 0 else j + 1
            continue
        if c in "'\"":
            q = c if q is None else (None if q == c else q)
        out.append(c)
        i += 1
    return "".join(out)


ANSI_ESCAPE = re.compile(r"\\(x[0-9A-Fa-f]{1,2}|u[0-9A-Fa-f]{1,4}|U[0-9A-Fa-f]{1,8}|[0-7]{1,3}|c.|.)", re.S)
ANSI_SIMPLE = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}


def _ansi_end(s, k):
    """Index of the quote closing an ANSI-C string whose body starts at k."""
    i = k
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "'":
            return i
        i += 1
    return len(s) - 1


def _ansi_decode(body):
    def one(m):
        e = m.group(1)
        if e[0] in "xuU":
            return chr(min(int(e[1:], 16), 0x10FFFF))
        if e[0] in "01234567":
            return chr(int(e, 8) & 0xFF)
        if e[0] == "c" and len(e) == 2:
            return chr(ord(e[1]) & 0x1F)
        return ANSI_SIMPLE.get(e, e)
    return ANSI_ESCAPE.sub(one, body)


def ansi_c(text):
    """The text with each unquoted $'...' decoded into a plain quoted word,
    so `$'tell'` or `$'\x74ell'` reads as the tell bash runs."""
    if "$'" not in text:
        return text
    out, i, n, q = [], 0, len(text), None
    while i < n:
        c = text[i]
        if q == "'":
            out.append(c)
            if c == "'":
                q = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(text[i:i + 2])
            i += 2
            continue
        if q is None and text.startswith("$'", i):
            j = _ansi_end(text, i + 2)
            out.append(shlex.quote(_ansi_decode(text[i + 2:j])))
            i = j + 1
            continue
        if c in "'\"":
            q = c if q is None else (None if q == c else q)
        out.append(c)
        i += 1
    return "".join(out)


def words(text):
    text = mask(ansi_c(text))
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


def _env_split(w):
    """The command line `env -S '<line>'` runs (the -S string, then the words
    after it), or None when this is not an env -S."""
    i = 0
    while i < len(w) and (w[i] in PREFIX_WORDS or ASSIGNMENT.match(w[i])):
        i += 1
    if i >= len(w) or w[i].rsplit("/", 1)[-1] != "env":
        return None
    i += 1
    while i < len(w) and (w[i].startswith("-") or ASSIGNMENT.match(w[i])):
        a = w[i]
        if a in ("-S", "--split-string") and i + 1 < len(w):
            return " ".join(w[i + 1:])
        if a.startswith("--split-string="):
            return " ".join([a.split("=", 1)[1], *w[i + 1:]])
        if a.startswith("-S") and len(a) > 2:
            return " ".join([a[2:], *w[i + 1:]])
        i += 2 if a in ("-u", "--unset", "-C", "--chdir") else 1
    return None


def is_bb(word):
    """A word that runs bb: bb or a path to it (any case: the filesystem is
    case-insensitive), $BB_CLI, or ${VAR:-<one of those>}."""
    m = DEFAULTED.match(word)
    if m:
        return is_bb(m.group(1))
    return word in ("$BB_CLI", "${BB_CLI}") or word.rsplit("/", 1)[-1].lower() == "bb"


def maybe_bb(word):
    """A command word whose program is only known at run time."""
    return word == SUBST or bool(VARIABLE.match(word)) or bool(DEFAULTED.match(word))


def _printed(script, depth):
    """What the echo/printf commands in a process substitution print, as
    script text a shell reading it would run."""
    out = []
    for cmd in split_script(script, depth + 1):
        w = words(cmd.string())
        k = _command_word(w)
        if k is not None and w[k].rsplit("/", 1)[-1] in ("echo", "printf"):
            out.append(" ".join(a for a in w[k + 1:] if a not in ("-e", "-n", "-E", "--")))
    return out


def dispatches(script, depth=0):
    """[(command_text, heredoc_bodies, verb)] for each bb dispatch in the script."""
    found = []
    for cmd in split_script(script, depth):
        text = cmd.string()
        w = words(text)
        split = _env_split(w)
        if split is not None:
            if depth < MAX_DEPTH:
                found.extend(dispatches(split, depth + 1))
            continue
        k = _command_word(w)
        if k is None:
            continue
        head, rest = w[k], w[k + 1:]
        base = head.rsplit("/", 1)[-1]
        if base in SHELLS or base in ("source", "."):
            if depth < MAX_DEPTH:
                inner = None
                if base in SHELLS:
                    for j, a in enumerate(rest):
                        if a.startswith("-") and not a.startswith("--") and "c" in a[1:]:
                            inner = rest[j + 1] if j + 1 < len(rest) else None
                            break
                if inner is not None:
                    scripts = [inner]
                else:
                    # what the shell reads: here-strings, heredocs, and what a
                    # process substitution prints
                    scripts = [rest[j + 1] for j, a in enumerate(rest) if a == "<<<" and j + 1 < len(rest)]
                    scripts += [a[3:] for a in rest if a.startswith("<<<") and len(a) > 3]
                    scripts += list(cmd.heredocs)
                    for p in cmd.procsubs:
                        scripts += _printed(p, depth)
                for s in scripts:
                    found.extend(dispatches(s, depth + 1))
            continue
        if base == "eval" and depth < MAX_DEPTH:
            found.extend(dispatches(" ".join(rest), depth + 1))
            continue
        if is_bb(head) or maybe_bb(head):
            verb = _dispatch_verb(rest)
            if verb and not bare_help(rest, verb):
                found.append((text, list(cmd.heredocs), verb))
            continue
        # `xargs [opts] bb ...` runs bb with words from stdin, so it is a
        # dispatch even when no verb is written.
        if base == "xargs":
            j = k + 1
            while j < len(w) and w[j].startswith("-"):
                j += 2 if w[j] in XARGS_ARG_OPTS else 1
            if j < len(w) and is_bb(w[j]):
                found.append((text, list(cmd.heredocs), _dispatch_verb(w[j + 1:]) or "xargs bb"))
                continue
        # bb as an unquoted word after any other command that runs its
        # arguments (timeout, nice, sudo, stdbuf, find -exec, ...). Quoted
        # text is one shlex word, so a sentence that mentions a dispatch
        # never matches.
        for b in [i for i in range(k + 1, len(w)) if is_bb(w[i])]:
            verb = _dispatch_verb(w[b + 1:])
            if verb and not bare_help(w[b + 1:], verb):
                found.append((text, list(cmd.heredocs), verb))
                break
    return found


def changes_dir(script):
    """Whether any simple command in the script is cd or pushd: a relative
    brief path is then relative to a directory the hook cannot know."""
    for cmd in split_script(script):
        w = words(cmd.string())
        k = _command_word(w)
        if k is not None and w[k] in ("cd", "pushd"):
            return True
    return False


def _flagged(words_, flags):
    return any(a == f or a.startswith(f + "=") for a in words_ for f in flags)


def bare_help(rest, verb):
    """`bb <verb path> --help|-h` and nothing else: bb prints the help and
    sends nothing. A help word anywhere else can be an option's value
    (`--title -h`) or a positional after `--`, and the dispatch runs (review
    r2c), so it does not count."""
    return len(rest) == len(verb.split()) + 1 and rest[-1] in HELP_WORDS and rest[:-1] == verb.split()


def _dispatch_verb(rest):
    """'thread tell', 'thread queue create', 'fleet group-create', ... when
    `rest` (the words after bb) is a dispatch, after at most a few global
    options (`--json`, `--host h`)."""
    for j, a in enumerate(rest[:5]):
        if a in GROUPS:
            nxt = rest[j + 1] if j + 1 < len(rest) else ""
            if a in ("automation", "instructions"):
                verb = f"{a} {nxt}"
                if verb in CONDITIONAL_VERBS and (CONDITIONAL_VERBS[verb] is None or _flagged(rest[j + 2:], CONDITIONAL_VERBS[verb])):
                    return verb
                return None
            if a == "thread" and nxt in THREAD_VERBS:
                return f"thread {nxt}"
            if a == "thread" and nxt == "queue" and j + 2 < len(rest) and rest[j + 2] in QUEUE_VERBS:
                return f"thread queue {rest[j + 2]}"
            if a == "thread" and nxt == "interactions" and j + 2 < len(rest):
                verb = f"thread interactions {rest[j + 2]}"
                if verb in CONDITIONAL_VERBS and (CONDITIONAL_VERBS[verb] is None or _flagged(rest[j + 3:], CONDITIONAL_VERBS[verb])):
                    return verb
                return None
            if a == "fleet" and nxt == "member-add" and _flagged(rest[j + 2:], CONDITIONAL_VERBS["fleet member-add"]):
                return "fleet member-add"
            if a == "fleet" and nxt in FLEET_VERBS:
                return f"fleet {nxt}"
            return None
        if not a.startswith("-") and not (j and rest[j - 1].startswith("-")):
            return None
    return None
