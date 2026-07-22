#!/usr/bin/env python3
"""Workspace resolver: reuse-first, host-neutral, never-creates.

Given an absolute/canonical project path and a structured runtime inventory
(cmux or tmux), decide whether an existing workspace/session already points at
the project and can be REUSED. The resolver never creates a workspace, never
executes a discovered binary, and never serializes environment values.

Decision semantics:
  * exact          cwd == project             -> reuse (strongest signal)
  * inside-project cwd is strictly inside     -> eligible reuse
  * broad-parent   project is strictly inside -> advisory only, NEVER reused
                    cwd (cwd is a broad parent of the project)
  * ties / duplicates                          -> ambiguous (fail closed)

Output decision: reuse | missing | ambiguous | unsupported.
The resolver never creates. It only classifies and recommends.

Inventory input is structured JSON (a parsed adapter output), read from a file
(`--inventory PATH`) or stdin (`--inventory -`). The resolver does NOT run cmux
or tmux; the caller (adapter) supplies the normalized JSON. For cmux every
workspace must carry a full ``workspace_uuid``; malformed rows block the
decision so callers cannot interpret unreadable state as absence. For tmux
there are no workspace UUIDs and the resolver never
invents capabilities tmux does not offer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

SUPPORTED_SURFACES = ("cmux", "tmux")


class ResolverError(Exception):
    """Raised for recoverable, fail-closed conditions."""


def _canonical(raw: str) -> Path:
    """Return a canonical absolute path. Reject relative or traversal input."""
    if raw is None:
        raise ResolverError("path is required")
    p = Path(raw)
    if not p.is_absolute():
        raise ResolverError(f"path must be absolute: {raw!r}")
    if ".." in p.parts:
        raise ResolverError(f"path traversal rejected: {raw!r}")
    return p.resolve(strict=False)


def classify(cwd: str, project: Path) -> str:
    """Classify a workspace cwd against a canonical project path.

    Returns one of: exact, inside-project, broad-parent, none.
    Comparison is filesystem-identity based on resolved paths.
    """
    if not cwd:
        return "none"
    try:
        c = _canonical(cwd)
    except ResolverError:
        return "none"
    if c == project:
        return "exact"
    try:
        c.relative_to(project)
        return "inside-project"
    except ValueError:
        pass
    try:
        project.relative_to(c)
        return "broad-parent"
    except ValueError:
        return "none"


def _is_full_uuid(value: Any) -> bool:
    return isinstance(value, str) and bool(UUID_RE.match(value))


def normalize_cmux_workspaces(raw: Any) -> list[dict[str, Any]]:
    """Normalize a cmux inventory into candidate dicts.

    cmux candidates must carry a full UUID and absolute cwd. Live cmux fields
    (``id``, ``current_directory``, ``title``) and normalized adapter fields are
    accepted. A malformed row blocks the decision rather than being dropped,
    because silently treating unreadable state as absence can create duplicates.
    """
    rows = _coerce_rows(raw)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ResolverError("cmux inventory contains a non-object workspace")
        uuid = row.get("workspace_uuid") or row.get("uuid") or row.get("id")
        if not _is_full_uuid(uuid):
            raise ResolverError(
                "cmux inventory contains a workspace without a full UUID"
            )
        cwd = row.get("cwd") or row.get("current_directory")
        try:
            cwd_canon = _canonical(cwd) if cwd else None
        except ResolverError:
            cwd_canon = None
        if cwd_canon is None:
            raise ResolverError(
                f"cmux inventory workspace {uuid} has no valid absolute cwd"
            )
        out.append({
            "surface": "cmux",
            "workspace_uuid": uuid,
            "name": str(row.get("name") or row.get("title") or ""),
            "cwd": str(cwd_canon) if cwd_canon else None,
        })
    return out


def normalize_tmux_workspaces(raw: Any) -> list[dict[str, Any]]:
    """Normalize a tmux inventory into candidate dicts.

    tmux has no workspace UUIDs and offers no workspace-lifecycle capability;
    this adapter never invents one. Sessions are matched on cwd only.
    """
    rows = _coerce_rows(raw)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ResolverError("tmux inventory contains a non-object session")
        cwd = row.get("cwd")
        try:
            cwd_canon = _canonical(cwd) if cwd else None
        except ResolverError:
            cwd_canon = None
        if cwd is not None and cwd_canon is None:
            continue
        out.append({
            "surface": "tmux",
            "session": str(row.get("session") or row.get("name") or ""),
            "cwd": str(cwd_canon) if cwd_canon else None,
        })
    return out


def _coerce_rows(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("workspaces", "sessions", "rows", "items"):
            if isinstance(raw.get(key), list):
                return raw[key]
        return [raw]
    return []


def resolve(project: Path, workspaces: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Run the reuse decision over an iterable of normalized candidates."""
    exact: list[dict[str, Any]] = []
    inside: list[dict[str, Any]] = []
    advisory: list[str] = []

    for ws in workspaces:
        cwd = ws.get("cwd")
        kind = classify(cwd, project) if cwd else "none"
        annotated = dict(ws)
        annotated["match_type"] = kind
        if kind == "exact":
            exact.append(annotated)
        elif kind == "inside-project":
            inside.append(annotated)
        elif kind == "broad-parent":
            label = ws.get("workspace_uuid") or ws.get("session") or ws.get("name") or "?"
            advisory.append(
                f"broad-parent workspace {label} cwd={cwd} is advisory only; not reused"
            )

    candidates = exact + inside

    if len(exact) == 1:
        return _result("reuse", "exact", exact[0], candidates, advisory)
    if len(exact) > 1:
        return _result("ambiguous", "exact", None, candidates, advisory,
                       reason="multiple exact (cwd==project) workspaces")
    if len(inside) == 1:
        return _result("reuse", "inside-project", inside[0], candidates, advisory)
    if len(inside) > 1:
        return _result("ambiguous", "inside-project", None, candidates, advisory,
                       reason="multiple inside-project workspaces")
    return _result("missing", None, None, candidates, advisory)


def _result(decision: str, match_type: str | None,
            selected: dict[str, Any] | None,
            candidates: list[dict[str, Any]],
            advisory: list[str],
            reason: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "decision": decision,
        "match_type": match_type,
        "selected": selected,
        "candidates": candidates,
        "advisory": advisory,
    }
    if reason:
        out["reason"] = reason
    return out


def load_inventory(text: str, surface: str) -> list[dict[str, Any]]:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ResolverError(f"inventory is not valid JSON: {exc}") from exc
    if surface == "cmux":
        return normalize_cmux_workspaces(obj)
    if surface == "tmux":
        return normalize_tmux_workspaces(obj)
    raise ResolverError(f"unsupported surface {surface!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="resolve-workspace.py",
        description="Decide reuse/missing/ambiguous for an existing workspace "
                    "(never creates, never executes a discovered binary).",
    )
    parser.add_argument("--project", required=True,
                        help="absolute canonical project path")
    parser.add_argument("--surface",
                        help="adapter that produced the inventory")
    parser.add_argument("--inventory", default="-",
                        help="JSON inventory path, or '-' for stdin")
    args = parser.parse_args(argv)

    try:
        project = _canonical(args.project)
    except ResolverError as exc:
        sys.stderr.write(f"blocked: {exc}\n")
        return 2

    surface = args.surface
    text: str
    if args.inventory == "-":
        text = sys.stdin.read()
    else:
        try:
            with open(args.inventory, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            sys.stderr.write(f"blocked: cannot read inventory: {exc}\n")
            return 2

    if surface is None:
        # Infer surface from the JSON payload if omitted.
        try:
            peek = json.loads(text)
        except json.JSONDecodeError as exc:
            sys.stderr.write(f"blocked: inventory is not valid JSON: {exc}\n")
            return 2
        if isinstance(peek, dict) and isinstance(peek.get("surface"), str):
            surface = peek["surface"]
        elif isinstance(peek, dict) and isinstance(peek.get("workspaces"), list):
            surface = "cmux"
        elif isinstance(peek, dict) and isinstance(peek.get("sessions"), list):
            surface = "tmux"
        else:
            surface = "cmux"

    if surface not in SUPPORTED_SURFACES:
        result = {
            "decision": "unsupported",
            "project": str(project),
            "surface": surface,
            "supported_surfaces": list(SUPPORTED_SURFACES),
            "reason": f"no workspace resolver adapter for {surface!r}",
        }
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return 1

    try:
        workspaces = load_inventory(text, surface)
    except ResolverError as exc:
        sys.stderr.write(f"blocked: {exc}\n")
        return 2

    result = resolve(project, workspaces)
    result["project"] = str(project)
    result["surface"] = surface
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0 if result["decision"] == "reuse" else (
        0 if result["decision"] == "missing" else 1
    )


def selftest() -> int:
    """Offline fixture-based self-test. No network, no writes, no binaries."""
    project = _canonical("/tmp/proj")

    def ws(uuid, cwd, name="w"):
        return {"workspace_uuid": uuid, "cwd": cwd, "name": name}

    checks: list[tuple[str, bool, str]] = []

    def case(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    # exact reuse
    r = resolve(project, [ws("00000000-0000-0000-0000-000000000001", str(project))])
    case("exact reuse", r["decision"] == "reuse" and r["match_type"] == "exact",
         r["decision"])

    # inside-project single -> eligible reuse
    r = resolve(project, [ws("00000000-0000-0000-0000-000000000002",
                              str(project / "sub"))])
    case("inside-project reuse", r["decision"] == "reuse"
         and r["match_type"] == "inside-project", r["decision"])

    # broad-parent advisory, never reused -> missing
    r = resolve(project, [ws("00000000-0000-0000-0000-000000000003", "/tmp")])
    case("broad-parent not reused", r["decision"] == "missing"
         and r["advisory"] and "broad-parent" in r["advisory"][0],
         r["decision"])

    # ambiguity: two exact
    r = resolve(project, [
        ws("00000000-0000-0000-0000-000000000004", str(project)),
        ws("00000000-0000-0000-0000-000000000005", str(project)),
    ])
    case("two exact ambiguous", r["decision"] == "ambiguous", r["decision"])

    # ambiguity: two inside-project
    r = resolve(project, [
        ws("00000000-0000-0000-0000-000000000006", str(project / "a")),
        ws("00000000-0000-0000-0000-000000000007", str(project / "b")),
    ])
    case("two inside ambiguous", r["decision"] == "ambiguous", r["decision"])

    # nothing -> missing
    r = resolve(project, [])
    case("empty missing", r["decision"] == "missing", r["decision"])

    # malformed UUID blocks rather than looking like an empty inventory
    try:
        load_inventory(
            json.dumps([{"workspace_uuid": "not-a-uuid", "cwd": str(project)}]),
            "cmux")
        case("malformed uuid blocked", False)
    except ResolverError:
        case("malformed uuid blocked", True)

    # accept the installed cmux JSON shape and uppercase UUIDs
    live_uuid = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    workspaces = load_inventory(json.dumps({"workspaces": [{
        "id": live_uuid,
        "current_directory": str(project),
        "title": "live-shape",
    }]}), "cmux")
    r = resolve(project, workspaces)
    case("live cmux shape", r["decision"] == "reuse"
         and r["selected"]["workspace_uuid"] == live_uuid, r["decision"])

    # duplicate identical exact -> ambiguous (tie)
    r = resolve(project, [
        ws("00000000-0000-0000-0000-000000000001", str(project), "a"),
        ws("00000000-0000-0000-0000-000000000001", str(project), "a-dup"),
    ])
    case("duplicate exact ambiguous", r["decision"] == "ambiguous", r["decision"])

    # relative project rejected
    try:
        _canonical("relative/path")
        case("relative project rejected", False)
    except ResolverError:
        case("relative project rejected", True)

    # traversal rejected
    try:
        _canonical("/tmp/proj/../../etc")
        case("traversal rejected", False)
    except ResolverError:
        case("traversal rejected", True)

    # tmux normalization never invents a UUID
    tmux = normalize_tmux_workspaces(
        {"sessions": [{"session": "s1", "cwd": str(project)}]})
    case("tmux has no workspace_uuid",
         tmux and "workspace_uuid" not in tmux[0], str(tmux))

    try:
        load_inventory("[]", "zellij")
        case("unsupported adapter blocked", False)
    except ResolverError:
        case("unsupported adapter blocked", True)

    failed = 0
    for name, cond, detail in checks:
        failed += 0 if cond else 1
        print(f"[{'ok' if cond else 'FAIL'}] {name}" + (
            f" - {detail}" if detail and not cond else ""))
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
