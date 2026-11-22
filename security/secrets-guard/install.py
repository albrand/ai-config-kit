#!/usr/bin/env python3
import datetime, json, os, shutil
home=os.path.expanduser('~'); src=os.path.dirname(os.path.abspath(__file__))
dest=os.path.join(home,'.agent-hooks'); os.makedirs(dest,exist_ok=True)
for name in ('guard.py','secret-names','claude-pretool.sh','codex-pretool.sh','scrub-exec.py'):
    target={'guard.py':'secrets-guard.py','scrub-exec.py':'secrets-scrub-exec.py'}.get(name,name)
    shutil.copy2(os.path.join(src,name),os.path.join(dest,target))
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
