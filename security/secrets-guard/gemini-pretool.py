#!/usr/bin/env python3
"""Antigravity PreToolUse adapter: deny secret output, otherwise run the command through the scrubber."""
import json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from guard import denied, wrap

def main():
    try:
        event=json.load(sys.stdin)
        call=event['toolCall']; args=call['args']
        key='CommandLine' if 'CommandLine' in args else 'command'
        command=args.get(key)
        if not isinstance(command,str): raise ValueError('missing command')
        if denied(command):
            print(json.dumps({'decision':'deny','reason':'Secret-value output blocked. Use secret-names <file> to inspect names with values masked.'}))
        else:
            # Same as the Claude and Codex adapters: run it wrapped so known secret values are masked; keep the normal confirmation prompt.
            print(json.dumps({'decision':'ask','reason':'Secret guard found no deny rule; the command runs through the secret scrubber. Confirm under normal policy.','overwrite':{key:wrap(command)}}))
        return 0
    except Exception:
        print(json.dumps({'decision':'deny','reason':'Secret guard failed closed; command not run.'}))
        return 0
if __name__=='__main__': sys.exit(main())
