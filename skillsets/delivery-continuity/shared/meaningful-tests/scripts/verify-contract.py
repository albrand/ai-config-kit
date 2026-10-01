#!/usr/bin/env python3
"""Check the installed evidence contract's critical boundaries offline."""
from pathlib import Path
import sys

text = (Path(__file__).resolve().parents[1] / 'SKILL.md').read_text()
required = ('a verdict per goal', 'full workflow cannot be called complete',
            'never bypass a safety-hook block', 'review-only request',
            'honest partial evidence is useful')
missing = [clause for clause in required if clause not in text]
if missing:
    print('Missing evidence boundary:', ', '.join(missing), file=sys.stderr)
    raise SystemExit(1)
print('Per-goal evidence, workflow, authorization and security clauses present.')
