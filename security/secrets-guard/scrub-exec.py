#!/usr/bin/env python3
"""Run a shell command and exact-value scrub captured stdout/stderr."""
import os, re, shlex, subprocess, sys

def parse_env(text):
    values=[]
    for line in text.splitlines():
        m=re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$",line)
        if not m: continue
        key,value=m.groups(); value=value.strip()
        if len(value)>1 and value[0]==value[-1] and value[0] in "'\"": value=value[1:-1]
        if value and (re.search(r'(TOKEN|SECRET|KEY|PASSWORD|PASS|URI|URL|DSN|DATABASE|CREDENTIAL)',key,re.I) or len(value)>=16): values.append(value)
    return values

def redact(data,secrets):
    for secret in sorted(set((v for v in secrets if len(v)>=4)),key=len,reverse=True):
        data=data.replace(secret.encode(errors='ignore'),b'[MASKED]')
    return data

def main():
    if len(sys.argv)<3 or sys.argv[1]!='--':
        print('secret scrubber failed closed',file=sys.stderr); return 2
    command=' '.join(sys.argv[2:]); secrets=[]
    for key,value in os.environ.items():
        if value and re.search(r'(TOKEN|SECRET|KEY|PASSWORD|PASS|URI|URL|DSN|DATABASE|CREDENTIAL)',key,re.I): secrets.append(value)
    paths=[os.path.expanduser('~/pfull/prod.env'),os.path.expanduser('~/pfull/prod-lane.env'),os.path.expanduser('~/.env')]
    for path in paths:
        try:
            with open(path,errors='replace') as f: secrets.extend(parse_env(f.read()))
        except FileNotFoundError: pass
    if re.search(r'\bssh\s+hsrpc-wsl\b',command):
        # Fetch the known remote env file into process memory only; never stream it to the terminal.
        try:
            p=subprocess.run(['ssh','hsrpc-wsl','cat ~/pfull/prod.env'],capture_output=True,text=True,timeout=8)
            if p.returncode!=0:
                print('secret scrubber could not load remote masks; command not run',file=sys.stderr); return 2
            secrets.extend(parse_env(p.stdout))
        except Exception:
            print('secret scrubber could not load remote masks; command not run',file=sys.stderr); return 2
    try: p=subprocess.run(command,shell=True,capture_output=True)
    except Exception:
        print('secret scrubber could not execute command',file=sys.stderr); return 2
    out=redact(p.stdout,secrets); err=redact(p.stderr,secrets)
    sys.stdout.buffer.write(out); sys.stderr.buffer.write(err)
    return p.returncode
if __name__=='__main__': sys.exit(main())
