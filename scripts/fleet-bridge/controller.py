#!/usr/bin/env python3
"""Install and inspect a task-scoped, user-owned local fleet scheduler."""
import argparse
import hashlib
import importlib.util
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def bindings(path):
    spec = importlib.util.spec_from_file_location('fleet_bridge_monitor', HERE / 'monitor.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = module.configure(path)
    scheduler = config.get('scheduler')
    if not isinstance(scheduler, dict):
        raise ValueError('Explicit scheduler bindings required')
    label = scheduler.get('label')
    if not isinstance(label, str) or not label.startswith('local.agent-config-kit.fleet.') or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789.-' for c in label):
        raise ValueError('Invalid task-scoped scheduler label')
    interval = scheduler.get('intervalSeconds')
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 60:
        raise ValueError('Scheduler interval must be at least 60 seconds')
    return module, config, label


def artifact_digest():
    return hashlib.sha256(b''.join((HERE / name).read_bytes() for name in ['monitor.py', 'controller.py', 'README.md'])).hexdigest()


def run_once(path, observe_only=False):
    monitor, config, label = bindings(path)
    try:
        result = monitor.run(mutate=not observe_only)
    except Exception as failure:
        write_json(monitor.ROOT / 'scheduler-last-failure.json', {'at': time.time(), 'label': label,
                   'artifactSha256': artifact_digest(), 'errorType': type(failure).__name__})
        raise
    receipt = {'label': label, 'at': time.time(), 'artifactSha256': artifact_digest(),
               'mode': 'observe' if observe_only else 'continue', 'result': result}
    write_json(monitor.ROOT / 'scheduler-last-run.json', receipt)
    print(json.dumps({'label': label, 'artifactSha256': receipt['artifactSha256'],
                      'status': result.get('status', 'OBSERVED'),
                      'states': {k: v['state'] for k, v in result.get('targets', {}).items()},
                      'allComplete': result.get('allComplete'),
                      'nudgesThisRun': sum('nudgeReceipt' in t for t in result.get('targets', {}).values())}))
    return receipt


def stage(path, install_root):
    monitor, config, label = bindings(path)
    if sys.platform != 'darwin':
        raise ValueError('This scheduler adapter requires macOS; run is portable on POSIX')
    # Immutable versioned copies make a running scheduler independent of worktrees.
    digest = artifact_digest()
    destination = install_root / digest
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ['monitor.py', 'controller.py', 'README.md']:
        source = HERE / name
        target = destination / name
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ValueError('Immutable installed artifact differs: ' + name)
        if not target.exists():
            shutil.copyfile(source, target)
            target.chmod(0o600)
    monitor.ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    logs = monitor.ROOT / 'logs'
    logs.mkdir(exist_ok=True, mode=0o700)
    for name in ['stdout.log', 'stderr.log']:
        log = logs / name
        log.touch(mode=0o600, exist_ok=True)
        log.chmod(0o600)
    plist = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
    values = {'Label': label, 'ProgramArguments': [sys.executable, str(destination / 'controller.py'), 'run', '--config', str(path)],
              'WorkingDirectory': str(destination), 'StartInterval': config['scheduler']['intervalSeconds'],
              'RunAtLoad': True, 'ProcessType': 'Background',
              'EnvironmentVariables': {'PATH': config['scheduler'].get('path', '/usr/bin:/bin:/usr/sbin:/sbin')},
              'StandardOutPath': str(logs / 'stdout.log'), 'StandardErrorPath': str(logs / 'stderr.log')}
    expected = plistlib.dumps(values)
    if plist.exists() and plist.read_bytes() != expected:
        previous_path = monitor.ROOT / 'installation.json'
        previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
        prior_values = plistlib.loads(plist.read_bytes())
        old_command = str(Path(previous.get('installPath', '/unowned')) / 'controller.py')
        if previous.get('label') != label or previous.get('plist') != str(plist) or old_command not in prior_values.get('ProgramArguments', []):
            raise ValueError('A different scheduler already owns this label; do not overwrite it')
        loaded = subprocess.run(['launchctl', 'print', 'gui/' + str(os.getuid()) + '/' + label], capture_output=True, text=True)
        if loaded.returncode == 0:
            raise ValueError('Unload only this owned scheduler before changing its installed version')
        shutil.copyfile(plist, monitor.ROOT / ('scheduler-' + previous['artifactSha256'] + '.plist.bak'))
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(expected)
    plist.chmod(0o600)
    receipt = {'label': label, 'artifactSha256': digest, 'installPath': str(destination), 'plist': str(plist),
               'config': str(path), 'stagedAt': time.time(), 'activated': False,
               'files': {name: hashlib.sha256((destination / name).read_bytes()).hexdigest() for name in ['monitor.py', 'controller.py']}}
    write_json(monitor.ROOT / 'installation.json', receipt)
    print(json.dumps(receipt))
    return receipt


def activate(path):
    monitor, _, label = bindings(path)
    installation = json.loads((monitor.ROOT / 'installation.json').read_text())
    plist = Path(installation['plist'])
    actual = plistlib.loads(plist.read_bytes())
    if actual.get('Label') != label or actual.get('ProgramArguments', [])[-1:] != [str(path)]:
        raise ValueError('Installed scheduler binding mismatch')
    for name, digest in installation['files'].items():
        if hashlib.sha256((Path(installation['installPath']) / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Installed artifact parity failed: ' + name)
    domain = 'gui/' + str(os.getuid())
    existing = subprocess.run(['launchctl', 'print', domain + '/' + label], capture_output=True, text=True)
    if existing.returncode == 0:
        raise ValueError('Scheduler is already loaded; never bootstrap a duplicate')
    result = subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('launchctl bootstrap refused: ' + result.stderr.strip())
    installation.update({'activated': True, 'activatedAt': time.time()})
    write_json(monitor.ROOT / 'installation.json', installation)
    print(json.dumps({'label': label, 'activated': True, 'artifactSha256': installation['artifactSha256']}))


def status(path):
    monitor, _, label = bindings(path)
    process = subprocess.run(['launchctl', 'print', 'gui/' + str(os.getuid()) + '/' + label], capture_output=True, text=True)
    last = monitor.ROOT / 'scheduler-last-run.json'
    receipt = json.loads(last.read_text()) if last.exists() else None
    state = {'label': label, 'loaded': process.returncode == 0, 'lastRun': receipt,
             'launchctlMetadata': [line.strip() for line in process.stdout.splitlines() if any(line.strip().startswith(key) for key in ['state =', 'runs =', 'last exit code =', 'pid ='])]}
    print(json.dumps(state))
    return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['stage', 'run', 'activate', 'status'])
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--install-root', type=Path, default=Path.home() / '.local/share/agent-config-kit/fleet-bridge')
    parser.add_argument('--observe-only', action='store_true')
    args = parser.parse_args()
    config_path = args.config.resolve(strict=True)
    if args.action == 'stage':
        stage(config_path, args.install_root.resolve())
    elif args.action == 'run':
        run_once(config_path, args.observe_only)
    elif args.action == 'activate':
        activate(config_path)
    else:
        status(config_path)
