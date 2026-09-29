#!/usr/bin/env python3
"""Render compact global instructions; live-home installation is opt-in."""

from __future__ import annotations

import argparse
import ast
import difflib
import os
import shutil
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="compare live homes; do not write")
    mode.add_argument("--install", action="store_true", help="back up and replace all four live homes")
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--diff-dir", type=Path, help="write unified home-to-proposal diffs")
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
        for target in TARGETS.values():
            if not target.is_file() or target.is_symlink():
                print(f"REFUSE unsafe target: {target}", file=sys.stderr)
                return 2
        stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        for key, target in TARGETS.items():
            backup = target.with_name(f"{target.name}.card21-{stamp}.bak")
            shutil.copy2(target, backup)
            write_atomic(target, outputs[key])
            print(f"INSTALLED {target} (backup {backup})")
        return 0

    for key, content in outputs.items():
        path = args.output_dir / NAMES[key]
        write_atomic(path, content)
        print(f"RENDERED {path} {len(content.encode('utf-8'))} bytes")
        if args.diff_dir:
            before = TARGETS[key].read_text(encoding="utf-8").splitlines(keepends=True)
            after = content.splitlines(keepends=True)
            diff = difflib.unified_diff(
                before,
                after,
                fromfile=f"before/{TARGETS[key].name}",
                tofile=f"after/{NAMES[key]}",
            )
            diff_path = args.diff_dir / f"{key}.diff"
            write_atomic(diff_path, "".join(diff))
            print(f"DIFF {diff_path}")
    print("Live homes were not modified; use --check to compare or --install after approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
