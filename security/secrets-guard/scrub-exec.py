#!/usr/bin/env python3
"""Run a shell command and scrub known secret values and common encodings."""
import base64, os, re, shlex, shutil, subprocess, sys
from urllib.parse import quote, quote_plus

ENV_SOURCE = re.compile(r'(?i)^(?:\.env(?:\..*)?|.*\.env)$')
SHELL_BUILTINS = {'.',':','[','alias','bg','bind','break','builtin','caller','cd','command','compgen','complete',
    'continue','declare','dirs','disown','echo','enable','eval','exec','exit','export','false','fc','fg','getopts',
    'hash','help','history','jobs','kill','let','local','logout','mapfile','popd','printf','pushd','pwd','read',
    'readarray','readonly','return','set','shift','shopt','source','suspend','test','time','times','trap','true',
    'type','typeset','ulimit','umask','unalias','unset','wait','if','then','else','elif','fi','for','while','until',
    'do','done','case','esac','function','select','coproc'}

def _runs_command(word, path=None):
    """Whether the shell may execute word as a command when sourcing the file.

    A word the shell would still expand ($VAR, a glob, brace or tilde) is treated
    as a command, since its expanded name is unknown here.
    """
    return (word in SHELL_BUILTINS or re.search(r'[/$`*?\[\\{~]',word) is not None
            or shutil.which(word,path=path) is not None)

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

def _expand_env_value(value, variables, unknown=None):
    pattern=re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:-|-)([^{}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)')
    def replace(match):
        name=match.group(1) or match.group(4)
        if unknown is not None: unknown(name)
        current=variables.get(name,'')
        operator=match.group(2)
        if operator and (name not in variables or (operator==':-' and not current)):
            return match.group(3) or ''
        return current
    if '$(' in value or '`' in value:
        raise ValueError('dynamic env value')
    expanded=pattern.sub(replace,value)
    if '${' in expanded or '$(' in expanded or '`' in expanded:
        raise ValueError('dynamic env value')
    return expanded

def _fallback_values(raw):
    """Mask a value the parser cannot interpret exactly: the raw text and its long words."""
    raw=raw.strip()
    return [raw]+[word for word in raw.split() if len(word)>=8] if raw else []

def parse_env(text, strict=False, local_names=()):
    """Collect values to mask from dotenv text, line by line.

    Lines that cannot be parsed exactly are masked (raw value plus words of 8+
    characters) instead of failing. Only with strict=True (a file the command
    itself sources) does a dynamic value raise, because its runtime value is unknown.
    In strict mode a reference to a name absent from the environment also raises
    when that name may be set at run time (local_names: names in the command text
    or assigned in another env file), since the shell would expand it there.
    """
    values=[]; variables=dict(os.environ); open_quote=None
    assigned=set()
    def unknown(name):
        # The command may set or overwrite this name before sourcing (even one already in
        # the environment), so its run-time value is unknown unless this file set it first.
        if name in local_names and name not in assigned: raise ValueError('env reference to a run-time variable')
    if not strict: unknown=None
    def expand_value(text):
        return _expand_env_value(text,variables,unknown)
    def dynamic(text):
        if strict: raise ValueError('dynamic env value')
        values.extend(_fallback_values(text))
    def mask(text, expand):
        # Mask the literal text and, where the shell would expand it, the expanded value too.
        values.extend(_fallback_values(text))
        if expand and ('$' in text or '`' in text):
            try: values.extend(_fallback_values(expand_value(text)))
            except ValueError: dynamic(text)
    for line in text.splitlines():
        stripped=line.strip()
        if open_quote:
            # Continuation of a multi-line quoted value, such as a PEM block.
            closing=stripped.find(open_quote)
            body=stripped if closing<0 else stripped[:closing]
            mask(body,open_quote=='"')
            if closing>=0:
                tail=stripped[closing+1:].strip()
                if strict and tail and not tail.startswith('#'):
                    raise ValueError('shell text after quoted value in sourced env file')
                open_quote=None
            continue
        if not stripped or stripped.startswith('#'): continue
        m=re.match(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$",stripped)
        if not m:
            # In a sourced file this is a shell command, not a value: it runs, and its
            # output was never collected for masking.
            if strict and not re.fullmatch(r'export(?:\s+[A-Za-z_][A-Za-z0-9_]*)+',stripped):
                raise ValueError('shell command in sourced env file')
            mask(stripped,True)
            continue
        key,raw=m.groups(); raw=_strip_shell_comment(raw).strip()
        quoted=len(raw)>=2 and raw[0]==raw[-1] and raw[0] in "'\""
        if raw[:1] in ("'",'"') and not quoted:
            if strict and raw.find(raw[0],1)>=0:
                # The quote closes on this line and shell text follows it.
                raise ValueError('shell text after quoted value in sourced env file')
            open_quote=raw[0]
            mask(raw[1:],open_quote=='"')
            continue
        if quoted:
            if strict:
                # X="a" cat "b" also starts and ends with a quote; the shell would run cat.
                try: words=shlex.split(raw,posix=True)
                except ValueError: words=None
                if words is None or len(words)!=1:
                    raise ValueError('shell text after quoted value in sourced env file')
            value=raw[1:-1]
            if raw[0]=='"': value=re.sub(r'\\(["\\$`])',r'\1',value)
            else: value=value.replace("'\\''", "'")
        else:
            if strict and re.search(r'[;&|]',raw):
                raise ValueError('command separator in sourced env value')
            try: words=shlex.split(raw,posix=True)
            except ValueError:
                if strict: raise ValueError('unbalanced quote in sourced env value')
                words=None
            if strict and words and len(words)>1:
                # The shell runs the first non-assignment word after the value as a command.
                rest=[w for w in words[1:]]
                while rest and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*',rest[0]): rest=rest[1:]
                # A word named in the command may be a function or alias it defined first.
                if rest and (rest[0] in local_names or _runs_command(rest[0],variables.get('PATH'))):
                    raise ValueError('sourced env line runs a command')
            if words is None or len(words)>1:
                # Valid dotenv such as NAME=Some Name <addr@example.com>: mask it, never fail.
                values.extend(_fallback_values(raw))
                try: values.extend(_fallback_values(expand_value(raw)))
                except ValueError: dynamic(raw)
                variables[key]=raw; assigned.add(key)
                continue
            value=words[0] if words else ''
        if raw[:1]!="'":
            try: value=expand_value(value)
            except ValueError:
                dynamic(value); variables[key]=value; assigned.add(key); continue
        variables[key]=value; assigned.add(key)
        if value and (re.search(r'(TOKEN|SECRET|KEY|PASSWORD|PASS|URI|URL|DSN|DATABASE|CREDENTIAL)',key,re.I) or len(value)>=16):
            values.extend((raw[1:-1] if quoted else value,value))
    return values

def env_mask_paths(command, sourced=None):
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
        path=os.path.abspath(candidate if os.path.isabs(candidate) else os.path.join(cwd,candidate))
        paths.append(path)
        if sourced is not None: sourced.add(path)
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
    sourced=set()
    try:
        paths.extend(env_mask_paths(command,sourced))
    except Exception:
        print('secret scrubber could not inspect sourced env paths; command not run',file=sys.stderr); return 2
    texts={}
    for path in dict.fromkeys(paths):
        try:
            with open(path,errors='replace') as f: texts[path]=f.read()
        except FileNotFoundError: continue
        except Exception:
            if path in sourced:
                print('secret scrubber could not read a sourced env file; command not run',file=sys.stderr); return 2
    # Names a sourced file may see set at run time: shell-local assignments in the
    # command and assignments in any other env file it may load.
    local_names=set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*',command))
    for text in texts.values():
        local_names.update(re.findall(r'(?m)^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=',text))
    for path,text in texts.items():
        try: secrets.extend(parse_env(text,strict=path in sourced,local_names=local_names))
        except Exception as error:
            # Only a file the command itself sources can reach here. Reasons are fixed
            # strings; anything else is reported generically so no value can leak.
            reason=str(error).replace(' in sourced env file','') if isinstance(error,ValueError) and re.fullmatch(r"[a-z -]+",str(error)) else 'unparseable line'
            print(f'secret scrubber: {reason} in sourced env file {path}; command not run',file=sys.stderr); return 2
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
