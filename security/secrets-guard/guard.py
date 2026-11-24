#!/usr/bin/env python3
"""Fail-closed PreToolUse command guard. Reads hook JSON on stdin."""
import json, os, re, shlex, subprocess, sys, time

SENSITIVE = re.compile(r'(TOKEN|SECRET|KEY|PASSWORD|PASS|URI|URL|DSN|DATABASE|CREDENTIAL)', re.I)
URI = re.compile(r'(?i)\b(?:mongodb(?:\+srv)?|neo4j\+s|postgres(?:ql)?|mysql|redis)://[^\s\'"<>]*:[^\s\'"<>]*@')
FILES = re.compile(r'(?i)(?:\.env[^/\s]*|[^/\s]*\.env|credentials?(?:\.json)?|id_(?:rsa|ed25519)|\.netrc|\.npmrc|\.pypirc|\.aws/credentials|Aura[^/]*credentials[^/]*)')
DUMP = re.compile(r'(?i)^(?:env|printenv|set|export\s+-p|declare\s+-x)$')
READERS = {'cat','head','tail','less','grep','egrep','fgrep','sed','awk','strings','xxd','base64'}
INTERPRETERS = {'python','python2','python3','node','ruby','perl'}
WRAPPERS = {'ssh','bash','sh','eval','command','sudo','env'}

def flatten(cmd):
    # Split shell operators and recursively inspect common wrapper payloads.
    # Wrapper commands themselves are not policy leaves; their payloads are.
    out=[]; pending=[cmd]
    while pending:
        source=pending.pop()
        lexer=shlex.shlex(source,posix=True,punctuation_chars=';&|()')
        lexer.whitespace_split=True; lexer.commenters='#'
        tokens=list(lexer); segments=[]; segment=[]
        for token in tokens:
            if token and all(char in ';&|()' for char in token):
                if segment: segments.append(segment); segment=[]
            else: segment.append(token)
        if segment: segments.append(segment)
        for words in segments:
            if not words: continue
            verb=os.path.basename(words[0])
            if verb in ('bash','sh','zsh'):
                for i,word in enumerate(words[:-1]):
                    if word in ('-c','-lc','-ec'):
                        pending.append(words[i+1]); break
                else: out.append(' '.join(words))
            elif verb=='eval': pending.append(' '.join(words[1:]))
            elif verb=='ssh':
                options_with_value={'-b','-c','-D','-E','-F','-i','-J','-L','-l','-m','-O','-o','-p','-Q','-R','-S','-W','-w'}
                i=1
                while i<len(words):
                    word=words[i]
                    if word=='--': i+=1; break
                    if not word.startswith('-'): break
                    i+=2 if word in options_with_value else 1
                if i+1<len(words): pending.append(' '.join(words[i+1:]))
                else: out.append(' '.join(words))
            elif verb in ('command','sudo','nohup','time','env'):
                nested=words[1:]
                while nested and (nested[0].startswith('-') or (verb=='env' and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*',nested[0]))): nested=nested[1:]
                if nested: pending.append(' '.join(nested))
                elif verb=='env': out.append('env')  # no payload: env prints the whole environment
            else: out.append(' '.join(words))
    return out

def contains_eval(cmd):
    pending=[cmd]; seen=set()
    while pending:
        source=pending.pop()
        if source in seen: continue
        seen.add(source)
        lexer=shlex.shlex(source,posix=True,punctuation_chars=';&|()')
        lexer.whitespace_split=True; lexer.commenters='#'
        tokens=list(lexer)
        if any(os.path.basename(token)=='eval' for token in tokens): return True
        for i,token in enumerate(tokens[:-1]):
            if token in ('-c','-lc','-ec'): pending.append(tokens[i+1])
        if tokens and os.path.basename(tokens[0])=='ssh' and len(tokens)>2:
            pending.append(' '.join(tokens[2:]))
    return False

def denied(command):
    if FILES.search(command) and ('$' in command or '`' in command):
        return True
    if FILES.search(command):
        try:
            if contains_eval(command): return True
        except ValueError: return True  # cannot tokenize a command that names a secret file: fail closed
    if FILES.search(command) and re.search(r'(?is)(?:\bfunction\s+[A-Za-z_][A-Za-z0-9_]*|\b[A-Za-z_][A-Za-z0-9_]*\s*\(\s*\)\s*(?:\{|\()|\balias\s+[A-Za-z_][A-Za-z0-9_]*\s*=)',command):
        return True
    if URI.search(command): return True
    if re.search(r'(?im)(?:^|[;&|]\s*)(?:env|printenv|set|export\s+-p|declare\s+-x)(?:\s*(?:$|[;&|]))', command): return True
    if re.search(r'(?i)(?:os\.environ|process\.env|getenv\s*\()',command) and re.search(r'(?i)(?:print|echo|printf|console\.log|write\s*\()',command) and SENSITIVE.search(command): return True
    # Printing one secret-named variable is a value dump too, whether or not the tokenizer can parse the rest.
    if re.search(r'(?i)\bprintenv\s+(?:-\S+\s+)*[\'"]?[A-Z0-9_]*'+SENSITIVE.pattern, command): return True
    # `set -a` is an assignment-export mode, not a shell variable dump.
    if re.search(r'(?<!\S)set\s+-a\s*;\s*(?:\.|source)\s+[^;]+\.env[^;]*;\s*set\s+\+a', command):
        command = re.sub(r'(?<!\S)set\s+-a\s*;\s*(?:\.|source)\s+[^;]+;\s*set\s+\+a', 'source-env-internally', command)
    try: return _denied_tokenized(command)
    except ValueError: return _denied_untokenizable(command)

def _denied_untokenizable(command):
    # An unbalanced quote (an apostrophe in a heredoc or patch body) defeats the shell tokenizer.
    # Fall back to whole-text checks, which stay strict: any secret-file name or secret-variable print denies.
    command=re.sub(r'\\\n[ \t]*',' ',command)  # a line continuation is a space to the shell
    if FILES.search(command): return True
    if re.search(r'(?i)(?:console\.log|print|printf|echo)\s*\(?\s*(?:process\.env\.|\$\{?)[A-Z0-9_]*'+SENSITIVE.pattern, command): return True
    if re.search(r'(?i)\b(?:echo|printf)\b[^\n;&|]*\$\{?'+SENSITIVE.pattern, command): return True
    if re.search(r'(?im)(?:^|[;&|(){`!]|\$\(|\b(?:if|then|else|elif|do|while|until|time)\b)\s*(?:(?:command|sudo|nohup|time|exec|builtin|xargs|nice|stdbuf)\s+(?:-\S+\s+)*)*(?:[A-Za-z_]\w*=\S*\s+)*(?:\S*/)?(?:env|printenv|set|export\s+-p|declare\s+-x)(?:\s+-[-\w=]*)*\s*(?=$|[;&|(){}`)<>])', command): return True
    lowered=command.lower()
    if re.search(r'\bbb\s+(?:variable|variables|settings|config)\b',lowered) and re.search(r'\b(show|list|get|dump|print|view)\b',lowered): return True
    if re.search(r'\bvercel\s+env\s+(?:pull|ls)\b',lowered): return True
    if re.search(r'\bgit\s+config\s+--get(?:-all)?\s+(?:credential\.helper|credential\.\w+)',lowered): return True
    return False

def _denied_tokenized(command):
    for text in flatten(command):
        if re.search(r'(?i)(?:console\.log|print|printf|echo)\s*\(?\s*(?:process\.env\.|\$\{?)[A-Z0-9_]*(?:TOKEN|SECRET|KEY|PASSWORD|PASS|URI|URL|DSN|DATABASE|CREDENTIAL)', text): return True
        toks=shlex.split(text)
        if not toks: continue
        words=[t for t in toks if t not in ('2>/dev/null','>/dev/null')]
        # A dump verb counts only in command position: the segment's first word after assignments and wrappers.
        # Later words are arguments or heredoc body text (SQL `SET search_path`), not a shell `set`.
        head=0
        while head<len(words) and (re.fullmatch(r'[A-Za-z_]\w*=.*',words[head])
                or os.path.basename(words[head]) in ('command','sudo','nohup','exec','xargs','time','nice','builtin','stdbuf')
                or (head>0 and words[head].startswith('-'))): head+=1
        if head<len(words) and DUMP.fullmatch(words[head].rsplit('/',1)[-1]): return True
        for i,t in enumerate(words):
            base=t.rsplit('/',1)[-1]
            if base in READERS and any(FILES.search(x) for x in words[i+1:]):
                # grep count and name-only searches are safe
                if base in ('grep','egrep','fgrep') and any(x in ('-c','--count','-l','--files-with-matches') for x in words[i+1:]): continue
                return True
            if base in ('echo','printf') and any(re.search(r'\$\{?'+SENSITIVE.pattern+r'[A-Z0-9_]*\}?',x,re.I) for x in words[i+1:]): return True
        joined=' '.join(words).lower()
        if FILES.search(joined):
            verb=os.path.basename(words[0]).lower()
            safe_file_operation = (verb in ('ls','stat','secret-names')
                                   or (verb in ('grep','egrep','fgrep') and any(x in ('-c','--count','-l','--files-with-matches') for x in words[1:]))
                                   or (verb in ('.','source') and re.search(r'(?i)\.env(?:\.[^/\s]+)?$',words[-1])))
            if not safe_file_operation:
                return True
        if (any(os.path.basename(word).lower() in INTERPRETERS for word in words)
                and FILES.search(joined)
                and re.search(r'\b(?:open|read|read_text|read_bytes|readFile|readFileSync|createReadStream)\b',joined)):
            return True
        if re.search(r'\bbb\s+(?:variable|variables|settings|config)\b',joined) and re.search(r'\b(show|list|get|dump|print|view)\b',joined): return True
        if re.search(r'\bvercel\s+env\s+(?:pull|ls)\b',joined) and not re.search(r'>\s*[^\s]+',text): return True
        if re.search(r'\bgit\s+config\s+--get(?:-all)?\s+(?:credential\.helper|credential\.\w+)',joined): return True
    return False

def wrap(command):
    """Run an allowed command through the scrubber so known secret values are masked."""
    scrubber=os.path.expanduser('~/.agent-hooks/secrets-scrub-exec.py')
    return '/usr/bin/python3 '+shlex.quote(scrubber)+' -- '+shlex.quote(command)

# Sessions read hooks once, at start. A session older than the hook file runs unguarded.
HOOK_FILES={'claude':'claude-pretool.sh','codex':'codex-pretool.sh','antigravity':'gemini-pretool.py'}
PROVIDER_BY_EXE={'claude':'claude','codex':'codex','agy':'antigravity','antigravity':'antigravity'}
PS_ROW=re.compile(r'^\s*(\d+)\s+(\d+)\s+(\w{3}\s+\w{3}\s+\d+\s+\d\d:\d\d:\d\d\s+\d{4})\s+(.*)$')
RELAUNCH=("Restart each listed session so it loads the hook (this tool kills and restarts nothing):\n"
          "  1. Type /exit in the session itself. `bb terminal close` plus `bb thread native` does not restart it:\n"
          "     bb reattaches the new terminal to the same old process.\n"
          "  2. bb thread native <thr>\n"
          "  3. Confirm with: python3 ~/.agent-hooks/secrets-guard.py --check-sessions   (exit 0 means covered)\n"
          "Rows with thread '-' are not native-hold terminals; /exit them in whatever terminal or bb thread runs them.")

def hook_mtimes(hooks_dir=None):
    hooks_dir=hooks_dir or os.path.expanduser('~/.agent-hooks'); out={}
    for provider,name in HOOK_FILES.items():
        try: out[provider]=os.stat(os.path.join(hooks_dir,name)).st_mtime
        except OSError: out[provider]=None
    return out

NODE_LAUNCHERS={'node','nodejs','bun'}
NODE_PACKAGES=(('@anthropic-ai/claude-code','claude'),('@openai/codex','codex'))

def session_provider(command):
    """Provider of a Claude Code, Codex or Antigravity process, else None. Matches the executable
    name, or for a node launcher the script it runs (a package path or a script named like the tool)."""
    toks=command.split()
    if not toks: return None
    exe=os.path.basename(toks[0])
    if exe in PROVIDER_BY_EXE: return PROVIDER_BY_EXE[exe]
    if exe in NODE_LAUNCHERS:
        for t in toks[1:]:  # any argument, so options that take a value (--require x) cannot hide the script
            for package,provider in NODE_PACKAGES:
                if package in t: return provider
            stem,ext=os.path.splitext(os.path.basename(t))
            if ext in ('.js','.mjs','.cjs') and stem in PROVIDER_BY_EXE: return PROVIDER_BY_EXE[stem]
    return None

def stale_sessions(ps_text,mtimes):
    """Rows of (provider,pid,start text,thread,why) for sessions started before their hook file.
    ps_text is `ps -axo pid=,ppid=,lstart=,command=` output. An unparseable start time or a
    missing hook file cannot be proven covered, so it is listed."""
    rows={}
    for line in ps_text.splitlines():
        m=PS_ROW.match(line)
        if m: rows[int(m.group(1))]=(int(m.group(2)),m.group(3),m.group(4))
        else:
            m=re.match(r'^\s*(\d+)\s+(\d+)\s+(.*)$',line)
            if m:  # garbled start time: resume the command at the first known executable
                toks=m.group(3).split()
                at=next((i for i in range(len(toks)) if session_provider(' '.join(toks[i:]))),len(toks))
                rows[int(m.group(1))]=(int(m.group(2)),None,' '.join(toks[at:]))
    found=[]
    for pid,(ppid,start,command) in sorted(rows.items()):
        provider=session_provider(command)
        if not provider: continue
        thread='-'
        parent=rows.get(ppid)
        if parent:
            t=re.search(r'\bnative-hold\s+(thr_\w+)',parent[2])
            if t: thread=t.group(1)
        mtime=mtimes.get(provider)
        if mtime is None: why='hook file missing'
        else:
            try: started=time.mktime(time.strptime(re.sub(r'\s+',' ',start),'%a %b %d %H:%M:%S %Y'))
            except (TypeError,ValueError): started=None
            if started is None: why='unparseable start time'
            elif started<mtime: why='started before hook'
            else: continue
        found.append((provider,pid,start or '?',thread,why))
    return found

def format_sessions(found):
    if not found: return 'All running Claude Code, Codex and Antigravity sessions started after their guard hook.'
    lines=['%d running session(s) are NOT covered by the secrets guard hook:'%len(found)]
    lines+=['  %-11s pid %-6d started %-24s thread %-16s %s'%(p,pid,st,th,why) for p,pid,st,th,why in found]
    return '\n'.join(lines)+'\n'+RELAUNCH

def check_sessions(ps_text=None,hooks_dir=None):
    if ps_text is None:
        try:
            ran=subprocess.run(['/bin/ps','-axo','pid=,ppid=,lstart=,command='],capture_output=True,text=True,
                               env=dict(os.environ,LC_ALL='C'))
            ps_text=ran.stdout
            if ran.returncode!=0 or not ps_text.strip(): raise OSError('ps exited %s'%ran.returncode)
        except Exception as error:  # an empty or failed inventory proves nothing
            print('INVENTORY ERROR: could not list processes (%s); coverage is NOT established.'%error); return 2
    found=stale_sessions(ps_text,hook_mtimes(hooks_dir))
    print(format_sessions(found)); return 1 if found else 0

def main():
    if '--check-sessions' in sys.argv[1:]:
        args=sys.argv[1:]
        ps=open(args[args.index('--ps-file')+1]).read() if '--ps-file' in args else None
        return check_sessions(ps)
    try:
        event=json.load(sys.stdin); tool_input=event.get('tool_input',{})
        command=(tool_input.get('command') or tool_input.get('cmd') or event.get('command') or event.get('cmd'))
        if not isinstance(command,str): raise ValueError('missing command')
        if denied(command):
            print(json.dumps({'block':True,'reason':'Secret-value output blocked. Use secret-names <file> to inspect variable names with values masked.'})); return 0
        print(json.dumps({'block':False,'reason':'','updated_command':wrap(command)})); return 0
    except Exception:
        print(json.dumps({'block':True,'reason':'Secret guard failed closed; command not run.'})); return 0
if __name__=='__main__': sys.exit(main())
