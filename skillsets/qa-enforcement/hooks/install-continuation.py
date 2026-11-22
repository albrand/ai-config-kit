#!/usr/bin/env python3
"""Install the continuation check and its delivery budget with backups."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def check_target(home, target):
    """Reject links before reading or writing anything in an installed home."""
    try:
        parts = target.relative_to(home).parts
    except ValueError:
        raise RuntimeError(f"Installation target outside intended home: {target}")
    current = home
    for part in (None, *parts):
        if part is not None:
            current = current / part
        if current.is_symlink():
            raise RuntimeError(f"Unexpected symlink target or parent: {current}")


def replace(source, target):
    fd, temporary = tempfile.mkstemp(prefix=".continuation-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(source.read_bytes())
        os.chmod(temporary, stat.S_IMODE(source.stat().st_mode))
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(source, home, backup):
    trust_spec = importlib.util.spec_from_file_location("continuation_command_ownership", source / "hooks/codex-hook-trust.py")
    trust = importlib.util.module_from_spec(trust_spec)
    trust_spec.loader.exec_module(trust)
    pairs = [(source / "hooks/qa-stop-hook.sh", home / ".agent-hooks/qa-stop-hook.sh")]
    pairs.append((source / "hooks/hook-timeouts.py", home / ".agent-hooks/hook-timeouts.py"))
    pairs.append((source / "hooks/codex-hook-trust.py", home / ".agent-hooks/codex-hook-trust.py"))
    check_target(home, pairs[0][1])
    for provider_home in (".agents", ".bb", ".claude", ".codex"):
        root = home / provider_home / "skills/scope-ledger"
        check_target(home, root / "scripts/scope-gate.py")
        if not root.is_dir():
            raise RuntimeError(f"Existing skill home missing: {root}")
        if digest(root / "scripts/scope-gate.py") != digest(source / "shared/scope-ledger/scripts/scope-gate.py"):
            raise RuntimeError(f"Scope helper differs; reconcile before installation: {root}")
        pairs.extend((
            (source / "shared/scope-ledger/SKILL.md", root / "SKILL.md"),
            (source / "shared/scope-ledger/scripts/closeout-stop.py", root / "scripts/closeout-stop.py"),
        ))
        references_dir = root / "references"
        check_target(home, references_dir)
        references_dir.mkdir(parents=True, exist_ok=True)
        for reference in sorted((source / "shared/scope-ledger/references").glob("*.md")):
            target = references_dir / reference.name
            check_target(home, target)
            pairs.append((reference, target))
    manifest = []
    for i, (origin, target) in enumerate(pairs):
        check_target(home, target)
        if not origin.is_file():
            raise RuntimeError(f"Unexpected installation source or symlink target: {origin}, {target}")
        manifest.append({"target": str(target), "source": str(origin), "existed": target.exists(),
                         "before_sha256": digest(target), "after_sha256": digest(origin),
                         "backup": str(backup / str(i))})
    configs = [home / ".claude/settings.json", home / ".codex/hooks.json"]
    for config in configs:
        check_target(home, config)
        if config.exists():
            json.loads(config.read_text())
    trust_config = home / ".codex/config.toml"
    if configs[1].exists():
        check_target(home, trust_config)
        tomllib.loads(trust_config.read_text())
    backup.mkdir(parents=True, exist_ok=False)
    for item in manifest:
        check_target(home, Path(item["target"]))
        if item["existed"]:
            shutil.copy2(item["target"], item["backup"])
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for item in manifest:
        target = Path(item["target"])
        check_target(home, target)
        if digest(target) != item["before_sha256"]:
            raise RuntimeError(f"Concurrent installation detected; backup preserved: {target}")
        replace(Path(item["source"]), target)
        if digest(target) != item["after_sha256"]:
            raise RuntimeError(f"Installation parity failed: {target}")
    env = dict(os.environ, HOME=str(home), HOOK_GATES_DIR=str(home / ".agents/skills"))
    for config in configs:
        check_target(home, config)
    subprocess.run([sys.executable, str(source / "hooks/hook-timeouts.py"), "apply-stop",
                                    *(str(config) for config in configs)], env=env, check=True,
                                   capture_output=True, text=True, timeout=30)
    if configs[1].exists():
        check_target(home, trust_config)
        native = json.loads(configs[1].read_text())
        stop_commands = {hook.get("command", "")
                         for group in native.get("hooks", {}).get("Stop", [])
                         for hook in group.get("hooks", [])
                         if hook.get("type", "command") == "command"
                         and str(hook.get("command", "")).rstrip().endswith("qa-stop-hook.sh")
                         and trust.is_owned_stop_command(hook.get("command", ""), home=str(home))}
        for command in sorted(stop_commands):
            subprocess.run([sys.executable, str(source / "hooks/codex-hook-trust.py"),
                            "--trust", "--only-event", "Stop", "--only-command", command], env=env, check=True,
                           capture_output=True, text=True, timeout=30)
    return {"backup": str(backup), "installed_files": len(manifest), "parity": f"{len(manifest)}/{len(manifest)}"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.source.resolve(), args.home.resolve(), args.backup.resolve())))


if __name__ == "__main__":
    main()
