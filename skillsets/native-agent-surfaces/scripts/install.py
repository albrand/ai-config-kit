#!/usr/bin/env python3
"""Preference-aware, model-agnostic global installer for native-agent-surfaces.

Stdlib-only, POSIX v1. Honors XDG_CONFIG_HOME, XDG_DATA_HOME, and CODEX_HOME
(defaults: ~/.config, ~/.local/share, ~/.codex). The installer never serializes
environment values into the receipt; it records resolved install paths only.

Preference resolution: an explicit --mode flag wins and is persisted; otherwise
the mode is read from XDG_CONFIG_HOME/ai-config-kit/preferences.json. A missing,
corrupt, or unknown preference fails closed for install/uninstall.

Run `install.py install --help`, `status`, or `uninstall`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BUNDLE_NAME = "native-agent-surfaces"
PREF_KEY = BUNDLE_NAME.replace("-", "_")  # native_agent_surfaces
MANIFEST_FILENAME = "bundle-manifest.json"
PREF_SCHEMA_VERSION = 1
RECEIPT_SCHEMA_VERSION = 1
INSTALLER_VERSION = 1
VALID_MODES = ("enabled", "auto", "disabled")
SUPPORTED_HOSTS = ("cmux", "tmux", "zellij")
CODEX_ADAPTER_SKILL = "native-agent-surface"


class InstallerError(Exception):
    """Installer failure. The message contains no secret material."""


# --------------------------------------------------------------------------- #
# Paths / environment
# --------------------------------------------------------------------------- #
def _home_default(sub: str) -> str:
    return str(Path(os.path.expanduser("~")) / sub)


def resolve_dirs() -> tuple[Path, Path, Path]:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or _home_default(".config"))
    data_home = Path(os.environ.get("XDG_DATA_HOME") or _home_default(".local/share"))
    codex_home = Path(os.environ.get("CODEX_HOME") or _home_default(".codex"))
    return config_home, data_home, codex_home


def kit_config_dir(config_home: Path) -> Path:
    return config_home / "ai-config-kit"


def pref_file(config_home: Path) -> Path:
    return kit_config_dir(config_home) / "preferences.json"


def bundle_config_dir(config_home: Path) -> Path:
    return kit_config_dir(config_home) / BUNDLE_NAME


def receipt_file(config_home: Path) -> Path:
    return bundle_config_dir(config_home) / "install-receipt.json"


def canonical_target(data_home: Path) -> Path:
    return data_home / "ai-config-kit" / BUNDLE_NAME


def codex_adapter_target(codex_home: Path) -> Path:
    return codex_home / "skills" / CODEX_ADAPTER_SKILL


def default_source_root() -> Path:
    # scripts/install.py -> ../  == skillsets/native-agent-surfaces/
    return Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Atomic IO + hashing
# --------------------------------------------------------------------------- #
def _atomic_write_bytes(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, data: object, mode: int = 0o644) -> None:
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    _atomic_write_bytes(path, text.encode("utf-8"), mode)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_hash(items) -> str:
    """Deterministic tree hash over sorted (rel, sha256) pairs."""
    h = hashlib.sha256()
    for rel, digest in sorted(items):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(digest.encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _backup_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return path.with_name(f"{path.name}.bak.{stamp}")


# --------------------------------------------------------------------------- #
# Preferences (fail closed)
# --------------------------------------------------------------------------- #
def read_preference(config_home: Path) -> str:
    """Return the configured mode or raise InstallerError (fail closed)."""
    path = pref_file(config_home)
    if not path.is_file():
        raise InstallerError(
            f"preference file missing: {path}. Create it or pass "
            f"'--mode <{'|'.join(VALID_MODES)}>'. A missing preference is "
            "never treated as consent."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallerError(f"preference file corrupt: {path}: {exc}")
    if not isinstance(data, dict):
        raise InstallerError(f"preference file corrupt: {path}: not a JSON object")
    if data.get("schema_version") != PREF_SCHEMA_VERSION:
        raise InstallerError(
            f"preference file corrupt: {path}: unsupported schema_version "
            f"{data.get('schema_version')!r}"
        )
    entry = data.get(PREF_KEY)
    if not isinstance(entry, dict):
        raise InstallerError(
            f"preference unknown: {path}: missing '{PREF_KEY}' entry"
        )
    mode = entry.get("mode")
    if mode not in VALID_MODES:
        raise InstallerError(
            f"preference unknown: {path}: mode {mode!r} not one of {VALID_MODES}"
        )
    return mode


def write_preference(config_home: Path, mode: str) -> None:
    if mode not in VALID_MODES:
        raise InstallerError(f"invalid mode {mode!r}")
    path = pref_file(config_home)
    data: dict = {}
    if path.is_file():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InstallerError(
                f"preference file corrupt: {path}: {exc}; refusing to replace it"
            ) from exc
        if not isinstance(parsed, dict):
            raise InstallerError(
                f"preference file corrupt: {path}: not a JSON object; "
                "refusing to replace it"
            )
        schema = parsed.get("schema_version")
        if schema != PREF_SCHEMA_VERSION:
            raise InstallerError(
                f"preference file corrupt: {path}: unsupported schema_version "
                f"{schema!r}; refusing to replace it"
            )
        data = parsed
    data["schema_version"] = PREF_SCHEMA_VERSION
    entry = dict(data.get(PREF_KEY) or {})
    entry["mode"] = mode
    if mode != "auto":
        entry.pop("audit_reason", None)
    data[PREF_KEY] = entry
    _atomic_write_json(path, data, mode=0o600)


# --------------------------------------------------------------------------- #
# Manifest + receipt
# --------------------------------------------------------------------------- #
def load_manifest(source_root: Path) -> dict:
    mpath = source_root / MANIFEST_FILENAME
    if not mpath.is_file():
        raise InstallerError(f"bundle manifest missing: {mpath}")
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise InstallerError(f"bundle manifest corrupt: {mpath}: {exc}")
    for key in ("schema_version", "bundle_version", "bundle_name",
                "adapter_contract", "knowledge_payload", "adapters"):
        if key not in manifest:
            raise InstallerError(f"bundle manifest missing field '{key}'")
    if manifest["bundle_name"] != BUNDLE_NAME:
        raise InstallerError(
            f"bundle manifest name mismatch: {manifest['bundle_name']!r}"
        )
    if (not isinstance(manifest["knowledge_payload"], list)
            or not manifest["knowledge_payload"]):
        raise InstallerError("bundle manifest knowledge_payload must be a non-empty list")
    codex = manifest["adapters"].get("codex") if isinstance(manifest["adapters"], dict) else None
    if not isinstance(codex, dict) or not isinstance(codex.get("payload"), list):
        raise InstallerError("bundle manifest has no valid Codex adapter")
    return manifest


def _safe_payload_path(root: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise InstallerError(f"unsafe payload path: {rel!r}")
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise InstallerError(f"payload path escapes source root: {rel!r}") from exc
    return path


def collect_knowledge_payload(source_root: Path, manifest: dict):
    payload = []
    for entry in manifest["knowledge_payload"]:
        if not isinstance(entry, dict):
            raise InstallerError("knowledge payload entries must be objects")
        source_rel = entry.get("source")
        target_rel = entry.get("target")
        src = _safe_payload_path(source_root, source_rel)
        _safe_payload_path(Path("/payload-root"), target_rel)
        if not src.is_file():
            raise InstallerError(f"payload source missing: {src}")
        payload.append((target_rel, src))
    return payload


def collect_codex_payload(source_root: Path, manifest: dict):
    adapter = manifest["adapters"]["codex"]
    skill_dir = _safe_payload_path(source_root, adapter.get("source_dir"))
    payload = []
    for rel in adapter["payload"]:
        src = _safe_payload_path(skill_dir, rel)
        if not src.is_file():
            raise InstallerError(f"Codex adapter source missing: {src}")
        payload.append((rel, src))
    return payload


def read_receipt(config_home: Path):
    path = receipt_file(config_home)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return None


def _managed_hashes(receipt, target_key: str) -> dict:
    if not receipt:
        return {}
    files = receipt.get("targets", {}).get(target_key, {}).get("files", {})
    out = {}
    for rel, meta in files.items():
        if isinstance(meta, dict):
            out[rel] = meta.get("hash")
    return out


# --------------------------------------------------------------------------- #
# Interactive / host gating (auto mode)
# --------------------------------------------------------------------------- #
def tty_check() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError, OSError):
        return False


def supported_host_present() -> str | None:
    for host in SUPPORTED_HOSTS:
        if shutil.which(host):
            return host
    return None


# --------------------------------------------------------------------------- #
# Install target
# --------------------------------------------------------------------------- #
def _install_target(target_root: Path, payload, executable: set, *,
                    backup_conflicts: bool, managed_hashes: dict) -> dict:
    """Copy payload into target_root. Returns {rel: {hash, bytes}}.

    Idempotent: a target whose current hash equals the source hash is a no-op
    (no mtime churn). A differing target is overwritten only when it is a
    managed, unmodified file we own. Unmanaged or customized files block unless
    backup_conflicts moves them aside first.
    """
    target_root.mkdir(parents=True, exist_ok=True)
    backup_root = _backup_path(target_root) if backup_conflicts else None
    installed: dict[str, dict] = {}
    for rel, src in payload:
        dst = target_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        src_bytes = src.read_bytes()
        src_hash = sha256_bytes(src_bytes)
        if dst.exists() and dst.is_file():
            cur_hash = sha256_file(dst)
            if cur_hash == src_hash:
                installed[rel] = {"hash": src_hash, "bytes": len(src_bytes)}
                continue
            owned = managed_hashes.get(rel)
            if owned is not None and owned == cur_hash:
                _atomic_write_bytes(dst, src_bytes)
                if rel in executable:
                    os.chmod(dst, 0o755)
                installed[rel] = {"hash": src_hash, "bytes": len(src_bytes)}
                continue
            if backup_conflicts:
                bak = backup_root / rel
                bak.parent.mkdir(parents=True, exist_ok=True)
                os.replace(dst, bak)
                _atomic_write_bytes(dst, src_bytes)
                if rel in executable:
                    os.chmod(dst, 0o755)
                installed[rel] = {"hash": src_hash, "bytes": len(src_bytes)}
                continue
            raise InstallerError(
                f"conflict at {dst}: existing file is unmanaged or customized. "
                "Re-run with --backup-conflicts to move it aside before install."
            )
        else:
            _atomic_write_bytes(dst, src_bytes)
            if rel in executable:
                os.chmod(dst, 0o755)
            installed[rel] = {"hash": src_hash, "bytes": len(src_bytes)}
    return installed


def _preflight_target(target_root: Path, payload, *,
                      backup_conflicts: bool, managed_hashes: dict) -> None:
    """Detect every conflict before either install target is mutated."""
    for rel, src in payload:
        dst = target_root / rel
        if not dst.exists():
            continue
        if not dst.is_file():
            raise InstallerError(f"conflict at {dst}: target is not a regular file")
        current = sha256_file(dst)
        source = sha256_file(src)
        if current == source or managed_hashes.get(rel) == current or backup_conflicts:
            continue
        raise InstallerError(
            f"conflict at {dst}: existing file is unmanaged or customized. "
            "Re-run with --backup-conflicts to move it aside before install."
        )


def _prune_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    root = root.resolve()
    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        d = Path(dirpath)
        if d == root:
            continue
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass
    try:
        if root.exists() and not any(root.iterdir()):
            root.rmdir()
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_install(args) -> int:
    config_home, data_home, codex_home = resolve_dirs()
    source_root = Path(args.source_root).resolve()
    manifest = load_manifest(source_root)
    knowledge_payload = collect_knowledge_payload(source_root, manifest)
    codex_payload = collect_codex_payload(source_root, manifest)

    if args.mode:
        mode = args.mode
        write_preference(config_home, mode)
    else:
        mode = read_preference(config_home)  # fail closed

    audit_reason = None
    if mode == "disabled":
        print("disabled: preference persisted; nothing installed or removed")
        return 0
    if mode == "auto":
        if not tty_check():
            audit_reason = ("auto: skipped (not an interactive TTY session; "
                            "stdin/stdout must both be a TTY)")
            print(audit_reason)
            return 0
        host = supported_host_present()
        if not host:
            audit_reason = ("auto: skipped (no supported interactive host "
                            f"present: {list(SUPPORTED_HOSTS)})")
            print(audit_reason)
            return 0
        audit_reason = f"auto: installed (interactive TTY and host '{host}' present)"

    executable = set(manifest.get("executable", []))
    canon_root = canonical_target(data_home)
    adapter_root = codex_adapter_target(codex_home)
    receipt = read_receipt(config_home)

    canonical_managed = _managed_hashes(receipt, "canonical")
    codex_managed = _managed_hashes(receipt, "codex_adapter")
    _preflight_target(canon_root, knowledge_payload,
                      backup_conflicts=args.backup_conflicts,
                      managed_hashes=canonical_managed)
    _preflight_target(adapter_root, codex_payload,
                      backup_conflicts=args.backup_conflicts,
                      managed_hashes=codex_managed)

    canon_installed = _install_target(
        canon_root, knowledge_payload, executable,
        backup_conflicts=args.backup_conflicts,
        managed_hashes=canonical_managed,
    )
    adapter_installed = _install_target(
        adapter_root, codex_payload, executable,
        backup_conflicts=args.backup_conflicts,
        managed_hashes=codex_managed,
    )

    src_tree = tree_hash(
        [(f"knowledge/{rel}", sha256_file(src)) for rel, src in knowledge_payload]
        + [(f"adapters/codex/{rel}", sha256_file(src)) for rel, src in codex_payload]
    )
    new_receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "bundle_name": BUNDLE_NAME,
        "bundle_version": manifest["bundle_version"],
        "manifest_schema_version": manifest["schema_version"],
        "installer_version": INSTALLER_VERSION,
        "source_tree_hash": src_tree,
        "mode": mode,
        "installed_at": _now_iso(),
        "targets": {
            "canonical": {"root": str(canon_root), "files": canon_installed},
            "codex_adapter": {"root": str(adapter_root), "files": adapter_installed},
        },
    }
    if audit_reason:
        new_receipt["audit_reason"] = audit_reason
    _atomic_write_json(receipt_file(config_home), new_receipt, mode=0o600)

    print(f"installed native-agent-surfaces bundle v{manifest['bundle_version']} "
          f"(mode={mode})")
    if audit_reason:
        print(audit_reason)
    print(f"  canonical: {canon_root}")
    print(f"  codex:     {adapter_root}")
    return 0


def cmd_status(args) -> int:
    config_home, _data_home, _codex_home = resolve_dirs()
    ppath = pref_file(config_home)
    pref_mode = None
    if ppath.is_file():
        try:
            pref_mode = read_preference(config_home)
            pref_state = "ok"
        except InstallerError as exc:
            pref_state = f"corrupt/unknown ({exc})"
    else:
        pref_state = "missing"

    print(f"preference: {ppath}")
    print(f"  state: {pref_state}")
    print(f"  mode:  {pref_mode}")

    rpath = receipt_file(config_home)
    rec = read_receipt(config_home)
    print(f"receipt: {rpath}")
    if not rec:
        print("  status: not installed")
    else:
        print(f"  bundle_version:   {rec.get('bundle_version')}")
        print(f"  mode:             {rec.get('mode')}")
        print(f"  installed_at:     {rec.get('installed_at')}")
        print(f"  source_tree_hash: {rec.get('source_tree_hash')}")
        if rec.get("audit_reason"):
            print(f"  audit_reason:     {rec.get('audit_reason')}")
        for key in ("canonical", "codex_adapter"):
            tgt = rec.get("targets", {}).get(key, {})
            root = tgt.get("root", "")
            files = tgt.get("files", {})
            present = sum(1 for rel in files if (Path(root) / rel).exists())
            print(f"  {key:13}: {root} ({present}/{len(files)} files present)")
    return 0


def cmd_uninstall(args) -> int:
    config_home, data_home, codex_home = resolve_dirs()
    # Uninstall is governed by the receipt (ownership), not by the preference
    # mode: removing only hash-matched, receipt-owned artifacts is already safe.
    rec = read_receipt(config_home)
    if not rec:
        write_preference(config_home, "disabled")
        print("no managed install receipt found; preference set to disabled")
        return 0

    if (rec.get("schema_version") != RECEIPT_SCHEMA_VERSION
            or rec.get("bundle_name") != BUNDLE_NAME):
        raise InstallerError("uninstall blocked: receipt identity or schema is invalid")
    targets = rec.get("targets", {})
    expected_roots = {
        "canonical": canonical_target(data_home).resolve(),
        "codex_adapter": codex_adapter_target(codex_home).resolve(),
    }
    for key in ("canonical", "codex_adapter"):
        tgt = targets.get(key, {})
        if not isinstance(tgt, dict) or not isinstance(tgt.get("files"), dict):
            raise InstallerError(f"uninstall blocked: invalid receipt target {key!r}")
        root_raw = tgt.get("root")
        if not isinstance(root_raw, str) or not Path(root_raw).is_absolute():
            raise InstallerError(f"uninstall blocked: invalid receipt root for {key!r}")
        root = Path(root_raw).resolve()
        if root != expected_roots[key]:
            raise InstallerError(
                f"uninstall blocked: receipt root for {key!r} is outside the "
                "configured install target"
            )
        files = tgt.get("files", {})
        for rel, meta in files.items():
            dst = _safe_payload_path(root, rel)
            if not dst.exists():
                continue
            cur = sha256_file(dst) if dst.is_file() else None
            owned = meta.get("hash") if isinstance(meta, dict) else None
            if (not isinstance(owned, str) or len(owned) != 64
                    or any(ch not in "0123456789abcdef" for ch in owned)):
                raise InstallerError(
                    f"uninstall blocked: invalid receipt hash for {key}/{rel}"
                )
            if cur != owned:
                raise InstallerError(
                    f"uninstall blocked: {dst} was modified after install "
                    f"(receipt {owned}, current {cur}). Restore the managed "
                    "file or reclaim it manually before uninstall."
                )

    removed = 0
    for key in ("canonical", "codex_adapter"):
        tgt = targets.get(key, {})
        root = expected_roots[key]
        files = tgt.get("files", {})
        for rel in files:
            dst = _safe_payload_path(root, rel)
            if dst.exists():
                try:
                    dst.unlink()
                except OSError as exc:
                    raise InstallerError(f"failed to remove {dst}: {exc}")
                removed += 1
        _prune_empty_dirs(root)

    try:
        receipt_file(config_home).unlink()
    except OSError:
        pass
    write_preference(config_home, "disabled")
    print(f"uninstalled native-agent-surfaces ({removed} file(s) removed)")
    print("preference persisted as disabled")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="install.py",
        description="Preference-aware, model-agnostic installer for "
                    "native-agent-surfaces (POSIX v1).",
    )
    p.add_argument("--source-root", default=None,
                   help="skillset source root containing bundle-manifest.json "
                        "(default: the bundled skillset root)")
    sub = p.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install", help="install the bundle and adapter")
    install.add_argument("--mode", choices=VALID_MODES, default=None,
                         help="preference mode; an explicit flag wins and is "
                              "persisted. enabled=always install; auto=install "
                              "only on an interactive TTY with a supported host; "
                              "disabled=persist preference, install/remove nothing")
    install.add_argument("--backup-conflicts", action="store_true",
                         help="move conflicting unmanaged/customized target "
                              "files to a timestamped sibling backup before install")
    status = sub.add_parser("status", help="print preference and install state")
    status.add_argument("--mode", choices=VALID_MODES, default=None,
                        help=argparse.SUPPRESS)
    uninstall = sub.add_parser("uninstall", help="remove receipt-owned artifacts")
    uninstall.add_argument("--mode", choices=VALID_MODES, default=None,
                           help=argparse.SUPPRESS)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.source_root:
        args.source_root = str(default_source_root())
    try:
        if args.command == "install":
            return cmd_install(args)
        if args.command == "status":
            return cmd_status(args)
        if args.command == "uninstall":
            return cmd_uninstall(args)
    except InstallerError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
