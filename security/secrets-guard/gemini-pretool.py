#!/usr/bin/env python3
"""Antigravity/Gemini BeforeTool adapter; deny secret output, otherwise ask."""
import json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from guard import denied

def main():
    try:
        event=json.load(sys.stdin)
        call=event['toolCall']; args=call['args']
        command=args.get('CommandLine') or args.get('command')
        if not isinstance(command,str): raise ValueError('missing command')
        if denied(command):
            print(json.dumps({'decision':'deny','reason':'Secret-value output blocked. Use secret-names <file> to inspect names with values masked.'}))
        else:
            # Preserve the agent's existing permission path; do not auto-allow.
            print(json.dumps({'decision':'ask','reason':'Secret guard found no deny rule; confirm the command under normal policy.'}))
        return 0
    except Exception:
        print(json.dumps({'decision':'deny','reason':'Secret guard failed closed; command not run.'}))
        return 0
if __name__=='__main__': sys.exit(main())
