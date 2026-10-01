#!/usr/bin/env python3
"""Check the installed delivery contract's critical boundaries offline."""
from pathlib import Path
import sys

text = (Path(__file__).resolve().parents[1] / 'SKILL.md').read_text()
required = (
    'Reuse authorization already given',
    'continue useful independent authorized work',
    'never bypass it or route around',
    'Already-running sessions may cache old directives',
    'a failed goal stays FAIL',
)
missing = [clause for clause in required if clause not in text]
if missing:
    print('Missing delivery boundary:', ', '.join(missing), file=sys.stderr)
    raise SystemExit(1)
print('Delivery authorization, security, propagation and evidence clauses present.')
