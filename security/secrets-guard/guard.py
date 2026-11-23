#!/usr/bin/env python3
"""Fail-closed PreToolUse command guard. Reads hook JSON on stdin."""
import json, os, re, shlex, sys

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
    if FILES.search(command) and contains_eval(command):
        return True
    if FILES.search(command) and re.search(r'(?is)(?:\bfunction\s+[A-Za-z_][A-Za-z0-9_]*|\b[A-Za-z_][A-Za-z0-9_]*\s*\(\s*\)\s*(?:\{|\()|\balias\s+[A-Za-z_][A-Za-z0-9_]*\s*=)',command):
        return True
    if URI.search(command): return True
    if re.search(r'(?im)(?:^|[;&|]\s*)(?:env|printenv|set|export\s+-p|declare\s+-x)(?:\s*(?:$|[;&|]))', command): return True
    if re.search(r'(?i)(?:os\.environ|process\.env|getenv\s*\()',command) and re.search(r'(?i)(?:print|echo|printf|console\.log|write\s*\()',command) and SENSITIVE.search(command): return True
    # `set -a` is an assignment-export mode, not a shell variable dump.
    if re.search(r'(?<!\S)set\s+-a\s*;\s*(?:\.|source)\s+[^;]+\.env[^;]*;\s*set\s+\+a', command):
        command = re.sub(r'(?<!\S)set\s+-a\s*;\s*(?:\.|source)\s+[^;]+;\s*set\s+\+a', 'source-env-internally', command)
    for text in flatten(command):
        if re.search(r'(?i)(?:console\.log|print|printf|echo)\s*\(?\s*(?:process\.env\.|\$\{?)[A-Z0-9_]*(?:TOKEN|SECRET|KEY|PASSWORD|PASS|URI|URL|DSN|DATABASE|CREDENTIAL)', text): return True
        try: toks=shlex.split(text)
        except ValueError: raise
        if not toks: continue
        words=[t for t in toks if t not in ('2>/dev/null','>/dev/null')]
        for i,t in enumerate(words):
            base=t.rsplit('/',1)[-1]
            if DUMP.fullmatch(t): return True
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

def main():
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
