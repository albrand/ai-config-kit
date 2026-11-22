#!/usr/bin/env python3
"""Fail-closed PreToolUse command guard. Reads hook JSON on stdin."""
import json, re, shlex, sys

SENSITIVE = re.compile(r'(TOKEN|SECRET|KEY|PASSWORD|PASS|URI|URL|DSN|DATABASE|CREDENTIAL)', re.I)
URI = re.compile(r'(?i)\b(?:mongodb(?:\+srv)?|neo4j\+s|postgres(?:ql)?|mysql|redis)://[^\s\'"<>]*:[^\s\'"<>]*@')
FILES = re.compile(r'(?i)(?:\.env[^/\s]*|[^/\s]*\.env|credentials?(?:\.json)?|id_(?:rsa|ed25519)|\.netrc|\.npmrc|\.pypirc|\.aws/credentials|Aura[^/]*credentials[^/]*)')
DUMP = re.compile(r'(?i)^(?:env|printenv|set|export\s+-p|declare\s+-x)$')
READERS = {'cat','head','tail','less','grep','egrep','fgrep','sed','awk','strings','xxd'}
WRAPPERS = {'ssh','bash','sh','eval','command','sudo','env'}

def flatten(cmd):
    # Recurse through common shell payload forms; preserve parser errors for fail-closed decision.
    out=[]; pending=[cmd]
    while pending:
        s=pending.pop(); out.append(s)
        try: toks=shlex.split(s, posix=True)
        except ValueError: raise
        for i,t in enumerate(toks[:-1]):
            if (t in ('-c','-lc','-ec') or t=='eval') and i+1<len(toks): pending.append(toks[i+1])
        # ssh host command payload begins after destination
        if toks and toks[0]=='ssh' and len(toks)>2: pending.append(' '.join(toks[2:]))
    return out

def denied(command):
    if URI.search(command): return True
    if re.search(r'(?im)(?:^|[;&|]\s*)(?:env|printenv|set|export\s+-p|declare\s+-x)(?:\s*(?:$|[;&|]))', command): return True
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
        if re.search(r'\bbb\s+(?:variable|variables|settings|config)\b',joined) and re.search(r'\b(show|list|get|dump|print|view)\b',joined): return True
        if re.search(r'\bvercel\s+env\s+(?:pull|ls)\b',joined) and not re.search(r'>\s*[^\s]+',text): return True
        if re.search(r'\bgit\s+config\s+--get(?:-all)?\s+(?:credential\.helper|credential\.\w+)',joined): return True
    return False

def main():
    try:
        event=json.load(sys.stdin); tool_input=event.get('tool_input',{})
        command=(tool_input.get('command') or tool_input.get('cmd') or event.get('command') or event.get('cmd'))
        if not isinstance(command,str): raise ValueError('missing command')
        if denied(command):
            print(json.dumps({'block':True,'reason':'Secret-value output blocked. Use secret-names <file> to inspect variable names with values masked.'})); return 0
        print(json.dumps({'block':False,'reason':''})); return 0
    except Exception:
        print(json.dumps({'block':True,'reason':'Secret guard failed closed; command not run.'})); return 0
if __name__=='__main__': sys.exit(main())
