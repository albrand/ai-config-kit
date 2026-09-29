#!/usr/bin/env python3
"""Render compact global instructions; live-home installation is opt-in."""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "proposals/card21/rendered-homes"
OVERLAYS = ROOT / "proposals/card21/overlays"
TARGETS = {
    "claude": Path("~/.claude/CLAUDE.md").expanduser(),
    "codex": Path("~/.codex/AGENTS.md").expanduser(),
    "opencode": Path("~/.config/opencode/AGENTS.md").expanduser(),
    "bb": Path("~/.bb/AGENTS.md").expanduser(),
}
NAMES = {
    "claude": "CLAUDE.md",
    "codex": "codex-AGENTS.md",
    "opencode": "opencode-AGENTS.md",
    "bb": "bb-AGENTS.md",
}
HASH_NAMES = {"claude": "Claude", "codex": "Codex", "opencode": "OpenCode", "bb": "bb"}
INSTALL_SOURCE_PATHS = (
    "GLOBAL_AGENTS.md",
    "proposals/card21/hard-rules.md",
    "proposals/card21/overlays/claude.md",
    "proposals/card21/overlays/codex.md",
    "proposals/card21/overlays/opencode.md",
    "proposals/card21/overlays/bb.md",
    "proposals/card21/live-home-hashes.md",
    "scripts/typed-decisions-sync.py",
    "scripts/render-standing-homes.py",
)


def assert_install_sources_in_origin_main(repo_root: Path = ROOT) -> None:
    """Require every install input and this installer to match fetched origin/main."""
    fetch = subprocess.run(
        ["git", "-C", str(repo_root), "fetch", "--no-tags", "origin", "main:refs/remotes/origin/main"],
        capture_output=True,
        text=True,
        check=False,
    )
    if fetch.returncode != 0:
        detail = fetch.stderr.strip() or fetch.stdout.strip() or f"exit {fetch.returncode}"
        raise ValueError(f"could not refresh origin/main before install: {detail}")

    tracked = subprocess.run(
        [
            "git", "-C", str(repo_root), "ls-tree", "-r", "--name-only",
            "origin/main", "--", *INSTALL_SOURCE_PATHS,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if tracked.returncode != 0:
        detail = tracked.stderr.strip() or tracked.stdout.strip() or f"exit {tracked.returncode}"
        raise ValueError(f"could not inspect origin/main install sources: {detail}")
    tracked_paths = set(tracked.stdout.splitlines())
    if tracked_paths != set(INSTALL_SOURCE_PATHS):
        missing = sorted(set(INSTALL_SOURCE_PATHS) - tracked_paths)
        raise ValueError(f"origin/main does not contain every install source: {missing}")

    for source in INSTALL_SOURCE_PATHS:
        path = repo_root / source
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"install source is not a regular non-symlink file: {path}")

    diff = subprocess.run(
        [
            "git", "-C", str(repo_root), "diff", "--quiet", "--no-ext-diff",
            "--no-textconv", "origin/main", "--", *INSTALL_SOURCE_PATHS,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if diff.returncode == 1:
        raise ValueError("install sources differ from fetched origin/main")
    if diff.returncode != 0:
        detail = diff.stderr.strip() or diff.stdout.strip() or f"exit {diff.returncode}"
        raise ValueError(f"could not compare install sources with origin/main: {detail}")


def rendered(name: str) -> str:
    if name == "bb":
        baseline = (ROOT / "GLOBAL_AGENTS.md").read_text(encoding="utf-8").rstrip()
    else:
        baseline = (ROOT / "proposals/card21/hard-rules.md").read_text(encoding="utf-8").strip()
        module = ast.parse((ROOT / "scripts/typed-decisions-sync.py").read_text(encoding="utf-8"))
        assignment = next(
            node for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "GLOBAL_BLOCK" for target in node.targets)
        )
        typed_block = ast.literal_eval(assignment.value).strip()
        baseline = f"{baseline}\n\n{typed_block}"
    overlay = (OVERLAYS / f"{name}.md").read_text(encoding="utf-8").strip()
    return f"{baseline}\n\n{overlay}\n"


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as tmp:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_path = Path(tmp.name)
    os.replace(temp_path, path)


def load_expected_hashes(path: Path = ROOT / "proposals/card21/live-home-hashes.md") -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    rows = re.findall(r"(?m)^\| (Claude|Codex|OpenCode|bb) \| `([0-9a-fA-F]{64})` \|$", text)
    found = {name: digest.lower() for name, digest in rows}
    expected_names = set(HASH_NAMES.values())
    if len(rows) != 4 or set(found) != expected_names:
        raise ValueError(f"expected exactly one fingerprint per home in {path}; found {sorted(found)}")
    return {key: found[name] for key, name in HASH_NAMES.items()}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _backup_paths(targets: dict[str, Path], stamp: str) -> dict[str, Path]:
    for suffix in range(10000):
        candidate_stamp = stamp if suffix == 0 else f"{stamp}-{suffix}"
        paths = {
            key: target.with_name(f"{target.name}.card21-{candidate_stamp}.bak")
            for key, target in targets.items()
        }
        if all(not path.exists() and not path.is_symlink() for path in paths.values()):
            return paths
    raise ValueError("could not reserve a unique backup set")


def install_homes(
    targets: dict[str, Path],
    outputs: dict[str, str],
    expected_hashes: dict[str, str],
    *,
    stamp: str | None = None,
) -> dict[str, Path]:
    """Install only when every target matches its recorded fingerprint."""
    before: dict[str, bytes] = {}
    for key, target in targets.items():
        if not target.is_file() or target.is_symlink():
            raise ValueError(f"unsafe target: {target}")
        data = target.read_bytes()
        if _digest(data) != expected_hashes[key]:
            raise ValueError(f"fingerprint mismatch: {target}")
        before[key] = data

    backup_paths = _backup_paths(targets, stamp or datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f%z"))
    reserved: list[tuple[str, int]] = []
    staged: dict[str, Path] = {}
    replaced: list[str] = []
    installed_hashes = {key: _digest(outputs[key].encode("utf-8")) for key in targets}
    try:
        # Reserve every backup exclusively before writing any backup or home.
        for key, backup in backup_paths.items():
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            reserved.append((key, fd))
        for key, fd in reserved:
            view = memoryview(before[key])
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
            os.close(fd)
        reserved.clear()
        for key, target in targets.items():
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as tmp:
                tmp.write(outputs[key])
                tmp.flush()
                os.fsync(tmp.fileno())
                staged[key] = Path(tmp.name)
        # Recheck all targets after staging, before any replacement.
        for key, target in targets.items():
            if not target.is_file() or target.is_symlink() or _digest(target.read_bytes()) != expected_hashes[key]:
                raise ValueError(f"fingerprint changed during install preflight: {target}")
        for key, target in targets.items():
            shutil.copystat(target, backup_paths[key], follow_symlinks=False)
            shutil.copystat(target, staged[key], follow_symlinks=False)
        for key, target in targets.items():
            if not target.is_file() or target.is_symlink() or _digest(target.read_bytes()) != expected_hashes[key]:
                raise ValueError(f"fingerprint changed during install: {target}")
            os.replace(staged[key], target)
            del staged[key]
            replaced.append(key)
        return backup_paths
    except Exception as install_error:
        for key, fd in reserved:
            try:
                os.close(fd)
            except OSError:
                pass
            backup_paths[key].unlink(missing_ok=True)
        rollback_errors = []
        for key in reversed(replaced):
            target = targets[key]
            restore_path = None
            try:
                if not target.is_file() or target.is_symlink():
                    rollback_errors.append(
                        f"{target}: rollback conflict; target is not a regular non-symlink file"
                    )
                    continue
                if _digest(target.read_bytes()) != installed_hashes[key]:
                    rollback_errors.append(
                        f"{target}: rollback conflict; target changed after this install replaced it"
                    )
                    continue
                with tempfile.NamedTemporaryFile("wb", dir=target.parent, delete=False) as tmp:
                    tmp.write(before[key])
                    tmp.flush()
                    os.fsync(tmp.fileno())
                    restore_path = Path(tmp.name)
                shutil.copystat(backup_paths[key], restore_path, follow_symlinks=False)
                if not target.is_file() or target.is_symlink():
                    raise RuntimeError("rollback conflict; target is not a regular non-symlink file")
                if _digest(target.read_bytes()) != installed_hashes[key]:
                    raise RuntimeError("rollback conflict; target changed after this install replaced it")
                os.replace(restore_path, target)
            except Exception as rollback_error:
                rollback_errors.append(f"{target}: {rollback_error}")
                if restore_path is not None:
                    restore_path.unlink(missing_ok=True)
        for path in staged.values():
            path.unlink(missing_ok=True)
        if rollback_errors:
            raise RuntimeError(
                f"install failed ({install_error}); rollback failed: {'; '.join(rollback_errors)}"
            ) from install_error
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="compare live homes; do not write")
    mode.add_argument("--install", action="store_true", help="back up and replace all four live homes")
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--diff-dir", type=Path, help="write unified home-to-proposal diffs")
    parser.add_argument(
        "--full-context-diffs",
        action="store_true",
        help="include every unchanged line so the before side is fully reconstructable",
    )
    args = parser.parse_args()

    outputs = {key: rendered(key) for key in TARGETS}
    if args.check:
        mismatches = []
        for key, target in TARGETS.items():
            if not target.is_file() or target.read_text(encoding="utf-8") != outputs[key]:
                mismatches.append(str(target))
            else:
                print(f"MATCH {target}")
        if mismatches:
            print("DIFFERS " + ", ".join(mismatches))
            return 1
        print("PASS all four live homes match the rendered sources")
        return 0

    if args.install:
        try:
            assert_install_sources_in_origin_main()
            backups = install_homes(TARGETS, outputs, load_expected_hashes())
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"REFUSE install: {exc}", file=sys.stderr)
            return 2
        for key, target in TARGETS.items():
            print(f"INSTALLED {target} (backup {backups[key]})")
        return 0

    for key, content in outputs.items():
        path = args.output_dir / NAMES[key]
        write_atomic(path, content)
        print(f"RENDERED {path} {len(content.encode('utf-8'))} bytes")
        if args.diff_dir:
            before = TARGETS[key].read_bytes().decode("utf-8").splitlines(keepends=True)
            after = content.splitlines(keepends=True)
            diff = difflib.unified_diff(
                before,
                after,
                fromfile=f"before/{TARGETS[key].name}",
                tofile=f"after/{NAMES[key]}",
                n=max(len(before), len(after)) if args.full_context_diffs else 3,
            )
            diff_path = args.diff_dir / f"{key}.diff"
            write_atomic(diff_path, "".join(diff))
            print(f"DIFF {diff_path}")
    print("Live homes were not modified; use --check to compare or --install after approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
