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
        if kind in ('function_call','custom_tool_call','tool_use','tool_call') or name in ('exec_command','Bash','bash','exec'):
            inp=obj.get('input',obj.get('arguments'))
            if isinstance(inp,str):
                try: inp=json.loads(inp)
                except Exception: pass
            def command_fields(x):
                if isinstance(x,dict):
                    for k,v in x.items():
                        if k in ('command','cmd') and isinstance(v,str): yield v
                        elif isinstance(v,(dict,list)): yield from command_fields(v)
                elif isinstance(x,list):
                    for v in x: yield from command_fields(v)
            yield from command_fields(inp)
        # Traverse only known transcript containers, never arbitrary text fields.
        for key in ('payload','content','message','parts','response_item','messages'):
            v=obj.get(key)
            if isinstance(v,(dict,list)): yield from strings(v)
    elif isinstance(obj,list):
        for v in obj: yield from strings(v)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('jsonl'); ap.add_argument('--match',required=True); ap.add_argument('--limit',type=int,default=20); a=ap.parse_args()
    rx=re.compile(a.match,re.I)
    for line in open(a.jsonl,errors='replace'):
        try: obj=json.loads(line)
        except Exception: continue
        for command in strings(obj):
            if rx.search(command):
                print(mask(command)); a.limit-=1
                if a.limit<=0: return
if __name__=='__main__': main()
