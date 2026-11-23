#!/usr/bin/env python3
import datetime, json, os, shutil, sys
import hashlib, re, tomllib

def codex_hook_hash(command, matcher, timeout=600):
    identity={'event_name':'pre_tool_use',
              'hooks':[{'type':'command','command':command,'timeout':timeout,'async':False}],
              'matcher':matcher}
    canonical=json.dumps(identity,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    return 'sha256:'+hashlib.sha256(canonical.encode()).hexdigest()

def trust_codex_hooks(home, registrations):
    """Trust only guard registrations, matching Codex's hook fingerprint."""
    hooks_path=os.path.join(home,'.codex/hooks.json')
    config_path=os.path.join(home,'.codex/config.toml')
    if not os.path.isfile(config_path):
        raise RuntimeError('Codex config.toml is missing; refusing an untrusted guard registration')
    text=open(config_path).read()
    for group_index,hook_index,command,matcher,timeout in registrations:
        key='%s:pre_tool_use:%d:%d' % (hooks_path,group_index,hook_index)
        digest=codex_hook_hash(command,matcher,timeout)
        header='[hooks.state."%s"]' % key
        block=re.compile(re.escape(header)+r'\n(?:(?!\[).*(?:\n|$))*')
        stanza=header+'\ntrusted_hash = "%s"\nenabled = true\n\n' % digest
        text=block.sub(stanza,text,count=1) if block.search(text) else text.rstrip('\n')+'\n\n'+stanza
    tomllib.loads(text)
    backup=config_path+'.'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.bak'
    shutil.copy2(config_path,backup)
    temp=config_path+'.tmp'
    with open(temp,'w') as f: f.write(text)
    os.replace(temp,config_path)
home=os.path.expanduser('~'); src=os.path.dirname(os.path.abspath(__file__))
dest=os.path.join(home,'.agent-hooks'); os.makedirs(dest,exist_ok=True)
cursor_only='--cursor-only' in sys.argv[1:]
if not cursor_only and os.path.exists(os.path.join(home,'.codex/hooks.json')) and not os.path.isfile(os.path.join(home,'.codex/config.toml')):
    raise SystemExit('Codex config.toml is missing; refusing an untrusted guard registration')
if not cursor_only and os.path.exists(os.path.join(home,'.codex/hooks.json')):
    try:
        with open(os.path.join(home,'.codex/config.toml'),'rb') as f: tomllib.load(f)
    except Exception:
        raise SystemExit('Codex config.toml is invalid; refusing an untrusted guard registration')
if cursor_only:
    names=('guard.py','cursor-pretool.py')
else:
    names=('guard.py','secret-names','claude-pretool.sh','codex-pretool.sh','scrub-exec.py','gemini-pretool.py','cursor-pretool.py')
for name in names:
    target={'guard.py':'secrets-guard.py','scrub-exec.py':'secrets-scrub-exec.py'}.get(name,name)
    shutil.copy2(os.path.join(src,name),os.path.join(dest,target))
shutil.copy2(os.path.join(src,'guard.py'),os.path.join(dest,'guard.py'))
if not cursor_only:
    for config, provider, command in [
        (os.path.join(home,'.claude/settings.json'),'claude','/bin/sh '+os.path.join(dest,'claude-pretool.sh')),
        (os.path.join(home,'.codex/hooks.json'),'codex','/bin/sh '+os.path.join(dest,'codex-pretool.sh')),
    ]:
        stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        shutil.copy2(config,config+'.'+stamp+'.bak')
        data=json.load(open(config))
        hooks=data.setdefault('hooks',{})
        entries=hooks.setdefault('PreToolUse',[])
        registrations=[]; found_guard=False
        for group_index,entry in enumerate(entries):
            if entry.get('matcher')!='Bash': continue
            for hook_index,hook in enumerate(entry.get('hooks',[])):
                if hook.get('command','').endswith('/'+provider+'-pretool.sh'):
                    found_guard=True
                    replacement={'type':'command','command':command}
                    entry['hooks'][hook_index]=replacement
                    if provider=='codex': registrations.append((group_index,hook_index,command,'Bash',600))
        if not found_guard:
            entries.append({'matcher':'Bash','hooks':[{'type':'command','command':command}]})
            if provider=='codex': registrations.append((len(entries)-1,0,command,'Bash',600))
        tmp=config+'.tmp'; open(tmp,'w').write(json.dumps(data,indent=2)+'\n'); os.replace(tmp,config)
        if provider=='codex':
            trust_codex_hooks(home,registrations)

# Antigravity ACP reads global named hooks from ~/.gemini/config/hooks.json. Its tool event is
# PreToolUse; BeforeTool is the Gemini CLI name, which Antigravity never fires.
if not cursor_only:
    gconfig=os.path.join(home,'.gemini/config/hooks.json')
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    shutil.copy2(gconfig,gconfig+'.'+stamp+'.bak')
    gd=json.load(open(gconfig))
    # Migrate an earlier BeforeTool registration of this adapter under any hook name.
    for hook_name,events in list(gd.items()):
        if not isinstance(events,dict) or not isinstance(events.get('BeforeTool'),list): continue
        kept=[e for e in events['BeforeTool'] if 'gemini-pretool.py' not in json.dumps(e)]
        if kept: events['BeforeTool']=kept
        else: del events['BeforeTool']
        if not events: del gd[hook_name]
    gd['secrets-guard']={'PreToolUse':[{'matcher':'run_command','hooks':[{'type':'command','command':'/usr/bin/python3 '+os.path.join(dest,'gemini-pretool.py'),'timeout':5}]}]}
    tmp=gconfig+'.tmp'; open(tmp,'w').write(json.dumps(gd,indent=2)+'\n'); os.replace(tmp,gconfig)

# OpenCode discovers plugins from this global directory.
if not cursor_only:
    plugin_dir=os.path.join(home,'.config/opencode/plugin'); os.makedirs(plugin_dir,exist_ok=True)
    plugin=os.path.join(plugin_dir,'secrets-guard.js')
    if os.path.exists(plugin): shutil.copy2(plugin,plugin+'.'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.bak')
    shutil.copy2(os.path.join(src,'opencode-plugin.js'),plugin)

# Cursor CLI's ACP server honors user hooks in ~/.cursor/hooks.json.
cursor_config=os.path.join(home,'.cursor/hooks.json')
cursor_stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
shutil.copy2(cursor_config,cursor_config+'.'+cursor_stamp+'.bak')
cd=json.load(open(cursor_config))
hooks=cd.setdefault('hooks',{})
entries=hooks.setdefault('beforeShellExecution',[])
command='python3 '+os.path.join(dest,'cursor-pretool.py')
entries[:]=[entry for entry in entries if entry.get('command')!=command]
entries.append({'command':command,'failClosed':True})
tmp=cursor_config+'.tmp'; open(tmp,'w').write(json.dumps(cd,indent=2)+'\n'); os.replace(tmp,cursor_config)

# Running sessions read hooks once at start; list those that predate the hook files. Kills nothing.
# copy2 keeps the source mtime, and a session that started before the registrations finished has no
# hook loaded, so stamp the hook scripts only now, after every registration was written.
if not cursor_only:
    for hook in ('claude-pretool.sh','codex-pretool.sh','gemini-pretool.py'):
        os.utime(os.path.join(dest,hook),None)
    sys.path.insert(0,src)
    import guard
    guard.check_sessions(hooks_dir=dest)
