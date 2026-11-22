#!/usr/bin/env python3
import datetime, json, os, shutil
home=os.path.expanduser('~'); src=os.path.dirname(os.path.abspath(__file__))
dest=os.path.join(home,'.agent-hooks'); os.makedirs(dest,exist_ok=True)
for name in ('guard.py','secret-names','claude-pretool.sh','codex-pretool.sh','scrub-exec.py','gemini-pretool.py'):
    target={'guard.py':'secrets-guard.py','scrub-exec.py':'secrets-scrub-exec.py'}.get(name,name)
    shutil.copy2(os.path.join(src,name),os.path.join(dest,target))
shutil.copy2(os.path.join(src,'guard.py'),os.path.join(dest,'guard.py'))
for config, provider, command in [
    (os.path.join(home,'.claude/settings.json'),'claude','/bin/sh '+os.path.join(dest,'claude-pretool.sh')),
    (os.path.join(home,'.codex/hooks.json'),'codex','/bin/sh '+os.path.join(dest,'codex-pretool.sh')),
]:
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    shutil.copy2(config,config+'.'+stamp+'.bak')
    data=json.load(open(config))
    hooks=data.setdefault('hooks',{})
    entries=hooks.setdefault('PreToolUse',[])
    entries[:] = [e for e in entries if not any(h.get('command','').endswith('/'+provider+'-pretool.sh') for h in e.get('hooks',[]))]
    entries.append({'matcher':'Bash','hooks':[{'type':'command','command':command}]})
    tmp=config+'.tmp'; open(tmp,'w').write(json.dumps(data,indent=2)+'\n'); os.replace(tmp,config)

# Antigravity ACP reads global named hooks from ~/.gemini/config/hooks.json.
gconfig=os.path.join(home,'.gemini/config/hooks.json')
stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
shutil.copy2(gconfig,gconfig+'.'+stamp+'.bak')
gd=json.load(open(gconfig))
gd['secrets-guard']={'BeforeTool':[{'matcher':'run_command','hooks':[{'type':'command','command':'/usr/bin/python3 '+os.path.join(dest,'gemini-pretool.py'),'timeout':5}]}]}
tmp=gconfig+'.tmp'; open(tmp,'w').write(json.dumps(gd,indent=2)+'\n'); os.replace(tmp,gconfig)

# OpenCode discovers plugins from this global directory.
plugin_dir=os.path.join(home,'.config/opencode/plugin'); os.makedirs(plugin_dir,exist_ok=True)
plugin=os.path.join(plugin_dir,'secrets-guard.js')
if os.path.exists(plugin): shutil.copy2(plugin,plugin+'.'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.bak')
shutil.copy2(os.path.join(src,'opencode-plugin.js'),plugin)
