#!/usr/bin/env python3
"""Run a shell command and scrub known secret values and common encodings."""
import base64, os, re, shlex, subprocess, sys
from urllib.parse import quote, quote_plus

ENV_SOURCE = re.compile(r'(?i)^(?:\.env(?:\..*)?|.*\.env)$')

def _strip_shell_comment(value):
    quote=None; escaped=False
    for i,char in enumerate(value):
        if escaped:
            escaped=False; continue
        if char=='\\' and quote!="'":
            escaped=True; continue
        if quote:
            if char==quote: quote=None
        elif char in ('"',"'"):
            quote=char
        elif char=='#' and (i==0 or value[i-1].isspace()):
            return value[:i]
    return value

def _expand_env_value(value, variables):
    pattern=re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:-|-)([^{}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)')
    def replace(match):
        name=match.group(1) or match.group(4)
        current=variables.get(name,'')
        operator=match.group(2)
        if operator and (name not in variables or (operator==':-' and not current)):
            return match.group(3) or ''
        return current
    expanded=pattern.sub(replace,value)
    if '$' in expanded or '`' in expanded or '$(' in value:
        raise ValueError('dynamic env value')
    return expanded

def parse_env(text):
    values=[]; variables=dict(os.environ)
    for line in text.splitlines():
        stripped=line.strip()
        if not stripped or stripped.startswith('#'): continue
        m=re.match(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$",stripped)
        if not m: raise ValueError('unsupported env-file syntax')
        key,raw=m.groups(); raw=_strip_shell_comment(raw).strip()
        quoted=len(raw)>=2 and raw[0]==raw[-1] and raw[0] in "'\""
        if raw[:1] in ("'",'"') and not quoted: raise ValueError('unclosed env-file quote')
        if quoted:
            value=raw[1:-1]
            if raw[0]=='"': value=re.sub(r'\\(["\\$`])',r'\1',value)
            else: value=value.replace("'\\''", "'")
        else:
            words=shlex.split(raw,posix=True)
            if len(words)>1: raise ValueError('ambiguous unquoted env value')
            value=words[0] if words else ''
        if raw[:1]!="'": value=_expand_env_value(value,variables)
        variables[key]=value
        if value and (re.search(r'(TOKEN|SECRET|KEY|PASSWORD|PASS|URI|URL|DSN|DATABASE|CREDENTIAL)',key,re.I) or len(value)>=16):
            values.extend((raw[1:-1] if quoted else value,value))
    return values

def env_mask_paths(command):
    """Find env files sourced by the command and dotenv files in its cwd(s).

    This only tokenizes shell syntax; it never evaluates or sources a file.
    Reading candidate files lets us mask values that the wrapped command or an
    application it launches loads after the scrubber starts.
    """
    lexer=shlex.shlex(command, posix=True, punctuation_chars=';&|')
    lexer.whitespace_split=True
    tokens=list(lexer)
    paths=[]
    directories=[os.getcwd()]
    cwd=os.getcwd()
    for i,token in enumerate(tokens[:-1]):
        if token == 'cd':
            destination=os.path.expanduser(os.path.expandvars(tokens[i+1]))
            if '$' in destination or '`' in destination or destination == '-':
                raise ValueError('dynamic directory before env source')
            cwd=os.path.abspath(destination if os.path.isabs(destination) else os.path.join(cwd,destination))
            directories.append(cwd)
            continue
        if token not in ('.','source'):
            continue
        candidate=os.path.expanduser(os.path.expandvars(tokens[i+1]))
        if not ENV_SOURCE.fullmatch(os.path.basename(candidate)):
            continue
        if '$' in candidate or '`' in candidate:
            raise ValueError('dynamic env source path')
        paths.append(os.path.abspath(candidate if os.path.isabs(candidate) else os.path.join(cwd,candidate)))
    for directory in dict.fromkeys(directories):
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if ENV_SOURCE.fullmatch(entry.name) and entry.is_file():
                        paths.append(os.path.abspath(os.path.join(directory,entry.name)))
        except FileNotFoundError:
            continue
    return paths

def has_hsrpc_ssh(command):
    """Recognize an actual shell command targeting the known SSH alias."""
    pending=[command]; seen=set()
    while pending:
        text=pending.pop()
        if text in seen: continue
        seen.add(text)
        lexer=shlex.shlex(text,posix=True,punctuation_chars=';&|()')
        lexer.whitespace_split=True; lexer.commenters='#'
        tokens=list(lexer); segment=[]
        segments=[]
        for token in tokens:
            if token and all(char in ';&|()' for char in token):
                if segment: segments.append(segment); segment=[]
            else: segment.append(token)
        if segment: segments.append(segment)
        for words in segments:
            while words and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*',words[0]): words=words[1:]
            if not words: continue
            verb=os.path.basename(words[0])
            if verb in ('bash','sh','zsh'):
                for i,word in enumerate(words[:-1]):
                    if word in ('-c','-lc','-ec'): pending.append(words[i+1])
            elif verb=='eval': pending.append(' '.join(words[1:]))
            elif verb in ('command','sudo','nohup','time','env'):
                nested=words[1:]
                while nested and (nested[0].startswith('-') or '=' in nested[0]): nested=nested[1:]
                if nested: pending.append(' '.join(nested))
            elif verb=='ssh':
                options_with_value={'-b','-c','-D','-E','-F','-i','-J','-L','-l','-m','-O','-o','-p','-Q','-R','-S','-W','-w'}
                i=1
                while i<len(words):
                    word=words[i]
                    if word=='--': i+=1; break
                    if not word.startswith('-'): break
                    i+=2 if word in options_with_value else 1
                if i<len(words) and words[i]=='hsrpc-wsl': return True
    return False

def redact(data,secrets):
    candidates=set()
    for secret in secrets:
        if len(secret)<4: continue
        raw=secret.encode(errors='ignore')
        encoded=base64.b64encode(raw).decode('ascii')
        hexed=raw.hex()
        candidates.update((secret,encoded,encoded.rstrip('='),hexed,quote(secret,safe=''),quote_plus(secret,safe='')))
        if len(encoded)>76:
            candidates.add('\n'.join(encoded[i:i+76] for i in range(0,len(encoded),76)))
            candidates.add('\r\n'.join(encoded[i:i+76] for i in range(0,len(encoded),76)))
    for candidate in sorted((v for v in candidates if len(v)>=4),key=len,reverse=True):
        data=data.replace(candidate.encode(errors='ignore'),b'[MASKED]')
    return data

def main():
    if len(sys.argv)<3 or sys.argv[1]!='--':
        print('secret scrubber failed closed',file=sys.stderr); return 2
    command=' '.join(sys.argv[2:]); secrets=[]
    for key,value in os.environ.items():
        if value and re.search(r'(TOKEN|SECRET|KEY|PASSWORD|PASS|URI|URL|DSN|DATABASE|CREDENTIAL)',key,re.I): secrets.append(value)
    paths=[os.path.expanduser('~/pfull/prod.env'),os.path.expanduser('~/pfull/prod-lane.env'),os.path.expanduser('~/.env')]
    try:
        paths.extend(env_mask_paths(command))
    except Exception:
        print('secret scrubber could not inspect sourced env paths; command not run',file=sys.stderr); return 2
    for path in dict.fromkeys(paths):
        try:
            with open(path,errors='replace') as f: secrets.extend(parse_env(f.read()))
        except FileNotFoundError: pass
        except Exception:
            print('secret scrubber could not read an env mask file; command not run',file=sys.stderr); return 2
    if has_hsrpc_ssh(command):
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
