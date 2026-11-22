#!/usr/bin/env python3
"""Print only masked tool-call commands selected by a case-insensitive filter."""
import argparse, json, re, sys

def mask(s):
    # Keep delimiters and command structure while removing likely values.
    s=re.sub(r'(?i)(://)([^\s\'";|&]+)',r'\1[MASKED]',s)
    s=re.sub(r'([=@])([^\s\'";|&]+)',r'\1[MASKED]',s)
    s=re.sub(r'(?<![A-Za-z0-9_])([:])([^\s\'";|&]+)',r'\1[MASKED]',s)
    s=re.sub(r'[^\s]{16,}', '[MASKED]', s)
    return s

def strings(obj):
    if isinstance(obj,dict):
        kind=obj.get('type'); name=obj.get('name','')
        if kind in ('function_call','tool_use') or name in ('exec_command','Bash','bash'):
            inp=obj.get('input')
            if isinstance(inp,str):
                try: inp=json.loads(inp)
                except Exception: pass
            if isinstance(inp,dict):
                for key in ('command','cmd'):
                    if isinstance(inp.get(key),str): yield inp[key]
        # Traverse only known transcript containers, never arbitrary text fields.
        for key in ('payload','content','message','parts','response_item','messages'):
            v=obj.get(key)
            if isinstance(v,(dict,list)): yield from strings(v)
    elif isinstance(obj,list):
        for v in obj: yield from strings(v)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('jsonl'); ap.add_argument('--match',required=True); a=ap.parse_args()
    rx=re.compile(a.match,re.I)
    for line in open(a.jsonl,errors='replace'):
        try: obj=json.loads(line)
        except Exception: continue
        for command in strings(obj):
            if rx.search(command): print(mask(command))
if __name__=='__main__': main()
