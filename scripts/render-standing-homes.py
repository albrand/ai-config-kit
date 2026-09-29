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
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import standing_home_lock


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
    "scripts/standing_home_lock.py",
)


def _git(repo_root: Path, *args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def capture_install_sources(repo_root: Path = ROOT) -> Mapping[str, bytes]:
    """Capture all renderer, manifest, and lock inputs once as immutable bytes."""
    sources = {}
    for source in INSTALL_SOURCE_PATHS:
        path = repo_root / source
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"install source is not a regular non-symlink file: {path}")
        sources[source] = path.read_bytes()
    return MappingProxyType(sources)


def assert_install_sources_in_origin_main(
    source_snapshot: Mapping[str, bytes], repo_root: Path = ROOT
) -> tuple[str, Mapping[str, bytes]]:
    """Return fetched main blobs only when they exactly match the captured inputs."""
    if set(source_snapshot) != set(INSTALL_SOURCE_PATHS):
        raise ValueError("install source snapshot is incomplete")
    fetch = subprocess.run(
        ["git", "-C", str(repo_root), "fetch", "--no-tags", "origin", "main:refs/remotes/origin/main"],
        capture_output=True,
        check=False,
    )
    if fetch.returncode != 0:
        raise ValueError(f"git fetch origin/main failed with exit code {fetch.returncode}")

    resolved = _git(repo_root, "rev-parse", "--verify", "refs/remotes/origin/main^{commit}")
    if resolved.returncode != 0:
        raise ValueError(f"could not pin fetched origin/main (exit {resolved.returncode})")
    commit = resolved.stdout.decode("ascii", errors="strict").strip()
    tree = _git(repo_root, "ls-tree", "-r", "-z", commit, "--", *INSTALL_SOURCE_PATHS)
    if tree.returncode != 0:
        raise ValueError(f"could not read pinned origin/main sources (exit {tree.returncode})")

    entries = {}
    for entry in tree.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError(f"unsafe install source in pinned origin/main: {path}")
        entries[path] = oid
    if set(entries) != set(INSTALL_SOURCE_PATHS):
        raise ValueError("pinned origin/main is missing install sources")

    pinned_sources = {}
    for source in INSTALL_SOURCE_PATHS:
        blob = _git(repo_root, "cat-file", "blob", entries[source])
        if blob.returncode != 0:
            raise ValueError(f"could not read pinned install source (exit {blob.returncode})")
        if blob.stdout != source_snapshot[source]:
            raise ValueError(f"install source differs from pinned origin/main: {source}")
        pinned_sources[source] = blob.stdout
    return commit, MappingProxyType(pinned_sources)


def rendered(name: str, sources: Mapping[str, bytes] | None = None) -> str:
    read = (lambda source: sources[source].decode("utf-8")) if sources is not None else None
    if name == "bb":
        baseline = (read("GLOBAL_AGENTS.md") if read else (ROOT / "GLOBAL_AGENTS.md").read_text(encoding="utf-8")).rstrip()
    else:
        baseline = (
            read("proposals/card21/hard-rules.md")
            if read
            else (ROOT / "proposals/card21/hard-rules.md").read_text(encoding="utf-8")
        ).strip()
        typed_source = (
            read("scripts/typed-decisions-sync.py")
            if read
            else (ROOT / "scripts/typed-decisions-sync.py").read_text(encoding="utf-8")
        )
        module = ast.parse(typed_source)
        assignment = next(
            node for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "GLOBAL_BLOCK" for target in node.targets)
        )
        typed_block = ast.literal_eval(assignment.value).strip()
        baseline = f"{baseline}\n\n{typed_block}"
    overlay_path = f"proposals/card21/overlays/{name}.md"
    overlay = (read(overlay_path) if read else (OVERLAYS / f"{name}.md").read_text(encoding="utf-8")).strip()
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


def parse_expected_hashes(text: str, source: str = "fingerprint manifest") -> dict[str, str]:
    rows = re.findall(r"(?m)^\| (Claude|Codex|OpenCode|bb) \| `([0-9a-fA-F]{64})` \|$", text)
    found = {name: digest.lower() for name, digest in rows}
    expected_names = set(HASH_NAMES.values())
    if len(rows) != 4 or set(found) != expected_names:
        raise ValueError(f"expected exactly one fingerprint per home in {source}; found {sorted(found)}")
    return {key: found[name] for key, name in HASH_NAMES.items()}


def load_expected_hashes(path: Path = ROOT / "proposals/card21/live-home-hashes.md") -> dict[str, str]:
    return parse_expected_hashes(path.read_text(encoding="utf-8"), str(path))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rollback_home(
    target: Path,
    original: bytes,
    installed_hash: str,
    backup: Path,
) -> str | None:
    """Restore without overwriting a new path; retain captured inodes for open writers."""
    recovery_dir = None
    captured = None
    restore_path = None
    target_moved = False
    try:
        recovery_dir = Path(tempfile.mkdtemp(prefix=".card21-rollback-", dir=target.parent))
        captured = recovery_dir / "captured"
        # Rename atomically captures the destination's current contents. Unlike
        # a hash-then-replace sequence, this leaves no gap in which a new edit
        # can be silently overwritten.
        try:
            os.rename(target, captured)
        except FileNotFoundError:
            recovery_dir.rmdir()
            return "rollback conflict; target disappeared before atomic capture"
        target_moved = True
        captured_stat = os.stat(captured, follow_symlinks=False)
        if not stat.S_ISREG(captured_stat.st_mode):
            try:
                os.link(captured, target, follow_symlinks=False)
            except OSError as exc:
                return (
                    f"rollback conflict; captured target is not a regular file and "
                    f"could not be restored ({exc}); recovery artifact preserved at {captured}"
                )
            target_moved = False
            return (
                "rollback conflict; target was not a regular file at atomic capture; "
                f"captured inode retained at {captured}"
            )

        if _digest(captured.read_bytes()) != installed_hash:
            try:
                os.link(captured, target, follow_symlinks=False)
            except FileExistsError:
                return (
                    "rollback conflict; target changed before atomic capture and a new target appeared; "
                    f"captured inode retained at {captured}"
                )
            target_moved = False
            return (
                "rollback conflict; target changed after this install replaced it; "
                f"captured inode retained at {captured}"
            )

        with tempfile.NamedTemporaryFile("wb", dir=recovery_dir, delete=False) as tmp:
            tmp.write(original)
            tmp.flush()
            os.fsync(tmp.fileno())
            restore_path = Path(tmp.name)
        shutil.copystat(backup, restore_path, follow_symlinks=False)
        try:
            # Hard-link creation fails atomically if a concurrent writer has
            # recreated target; preserve that edit and both recovery copies.
            os.link(restore_path, target, follow_symlinks=False)
        except FileExistsError:
            return (
                "rollback conflict; a concurrent writer recreated the target; "
                f"captured and restore artifacts preserved at {recovery_dir}"
            )
        target_moved = False
        if _digest(captured.read_bytes()) != installed_hash:
            return (
                "rollback conflict; an open writer changed the captured inode during restore; "
                f"captured inode retained at {captured}"
            )
        restore_path.unlink()
        # Keep captured until every descriptor opened before rename is closed.
        return None
    except Exception as exc:
        if recovery_dir is not None and (target_moved or any(recovery_dir.iterdir())):
            return f"rollback failed ({exc}); recovery artifacts preserved at {recovery_dir}"
        if restore_path is not None and restore_path.exists():
            restore_path.unlink(missing_ok=True)
        if recovery_dir is not None:
            recovery_dir.rmdir()
        return f"rollback failed ({exc})"


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


def _install_homes(
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
            try:
                rollback_error = _rollback_home(
                    target,
                    before[key],
                    installed_hashes[key],
                    backup_paths[key],
                )
            except Exception as rollback_exception:
                rollback_error = f"rollback failed ({rollback_exception})"
            if rollback_error:
                rollback_errors.append(f"{target}: {rollback_error}")
        for path in staged.values():
            try:
                path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                rollback_errors.append(f"staged file cleanup failed for {path}: {cleanup_error}")
        if rollback_errors:
            raise RuntimeError(
                f"install failed ({install_error}); rollback failed: {'; '.join(rollback_errors)}"
            ) from install_error
        raise


def install_homes(
    targets: dict[str, Path],
    outputs: dict[str, str],
    expected_hashes: dict[str, str],
    *,
    stamp: str | None = None,
) -> dict[str, Path]:
    """Serialize direct installs with the global instruction sync writer."""
    with standing_home_lock.exclusive_home_writer():
        return _install_homes(targets, outputs, expected_hashes, stamp=stamp)


def install_from_sources(
    repo_root: Path | None = None,
    targets: dict[str, Path] | None = None,
) -> dict[str, Path]:
    """Install only outputs rendered from the immutable fetched-main snapshot."""
    repo_root = ROOT if repo_root is None else repo_root
    targets = TARGETS if targets is None else targets
    with standing_home_lock.exclusive_home_writer():
        candidate_sources = capture_install_sources(repo_root)
        candidate_outputs = {key: rendered(key, candidate_sources) for key in targets}
        _, approved_sources = assert_install_sources_in_origin_main(candidate_sources, repo_root)
        approved_outputs = {key: rendered(key, approved_sources) for key in targets}
        if approved_outputs != candidate_outputs:
            raise ValueError("rendered install payload differs from pinned origin/main sources")
        manifest = approved_sources["proposals/card21/live-home-hashes.md"].decode("utf-8")
        expected_hashes = parse_expected_hashes(manifest, "pinned origin/main manifest")
        return _install_homes(targets, approved_outputs, expected_hashes)


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

    if args.install:
        try:
            backups = install_from_sources()
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"REFUSE install: {exc}", file=sys.stderr)
            return 2
        for key, target in TARGETS.items():
            print(f"INSTALLED {target} (backup {backups[key]})")
        return 0

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
