#!/usr/bin/env python3
"""Export only the maintained package as canonical bytes from an exact commit."""
import argparse
import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = ('monitor.py', 'controller.py', 'test_workflow.py', 'README.md', 'export-review.py')


def export(commit):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Use an exact full commit SHA')
    repo = HERE.parent.parent
    resolved = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', '--show-toplevel'], text=True).strip()
    if Path(resolved).resolve() != repo.resolve():
        raise ValueError('Package must be inside its owning repository')
    records = []
    for name in FILES:
        relative = 'scripts/fleet-bridge/' + name
        raw = subprocess.check_output(['git', '-C', str(repo), 'show', commit + ':' + relative])
        records.append({'path': relative, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                        'encoding': 'base64', 'data': base64.b64encode(raw).decode('ascii')})
    return {'schemaVersion': 1, 'commit': commit, 'files': records}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.commit), ensure_ascii=True, separators=(',', ':')))
