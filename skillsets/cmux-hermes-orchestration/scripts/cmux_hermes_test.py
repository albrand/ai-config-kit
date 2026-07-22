#!/usr/bin/env python3
"""Offline unit-style tests for the cmux-hermes broker.

Uses fake cmux/ssh/git/tailscale/hermes binaries in a temp dir. Never contacts a
provider or the network. Run from the skillset root:

    python3 scripts/cmux_hermes_test.py
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import uuid as uuidlib
from contextlib import redirect_stdout
from pathlib import Path


def load_broker():
    here = Path(__file__).resolve().parent
    broker_path = here.parent / "codex" / "cmux-hermes-orchestrator" / "scripts" / "cmux-hermes.py"
    spec = importlib.util.spec_from_file_location("cmux_hermes_broker", broker_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def write_fake(binpath: Path, body: str) -> None:
    binpath.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    os.chmod(binpath, 0o755)


def setup_fakes(env: dict[str, str]) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="cmux-hermes-test-"))
    bindir = tmp / "bin"
    bindir.mkdir()

    ssh = bindir / "ssh"
    write_fake(ssh, textwrap.dedent("""\
        import sys, json, os, shlex, re
        argv = sys.argv[1:]
        # Broker sends one shell-quoted remote command after ssh options/target.
        argv = shlex.split(argv[-1])
        if argv[:4] == ["sudo", "-n", "-u", "hermes"]:
            argv = argv[4:]
        if argv and argv[0] == "env":
            argv.pop(0)
        while argv and re.match(r"^[A-Z_][A-Z0-9_]*=", argv[0]):
            argv.pop(0)
        cmd = argv
        if cmd[:2] == ["id", "-un"]:
            print("hermes"); sys.exit(0)
        if cmd[:1] == ["tmux"]:
            sub = cmd[1]
            if sub == "has-session":
                sys.exit(0 if os.environ.get("FAKE_TMUX_EXISTS", "1") == "1" else 1)
            if sub == "new-session":
                print("created"); sys.exit(0)
            if sub == "list-panes":
                sys.exit(0 if os.environ.get("FAKE_TMUX_CHILDREN", "0") == "0" else 0)
            if sub == "detach-client":
                sys.exit(0)
        if "sessions" in cmd and "export" in cmd:
            rows = json.loads(os.environ.get("FAKE_USAGE_JSON", "[]"))
            sid = cmd[cmd.index("--session-id") + 1] if "--session-id" in cmd else None
            for row in rows:
                if sid is None or str(row.get("id") or row.get("session_id")) == sid:
                    print(json.dumps(row))
            sys.exit(0)
        if cmd[:2] == ["sh", "-c"]:
            data = sys.stdin.buffer.read().decode("utf-8", "replace")
            print("HERMES-OUT for: " + data[:40] + "\nSession ID: s1"); sys.exit(0)
        if cmd[:1] == ["true"]:
            sys.exit(0)
        print("fake-ssh-unhandled: " + " ".join(cmd)); sys.exit(1)
    """))

    cmux = bindir / "cmux"
    write_fake(cmux, textwrap.dedent("""\
        import sys, os, json, uuid
        a = sys.argv[1:]
        state_path = os.environ.get("FAKE_CMUX_STATE")

        def load():
            if state_path and os.path.exists(state_path):
                try:
                    with open(state_path) as fh:
                        data = json.load(fh)
                    return data if isinstance(data, list) else []
                except Exception:
                    return []
            return []

        def save(rows):
            if state_path:
                tmp = state_path + ".tmp"
                with open(tmp, "w") as fh:
                    json.dump(rows, fh)
                os.replace(tmp, state_path)

        if "list-workspaces" in a or ("--id-format" in a and "tree" in a):
            rows = [] if os.environ.get("FAKE_CMUX_HIDE_INVENTORY") == "1" else load()
            print(json.dumps({"workspaces": rows}))
            sys.exit(0)
        if a[:1] == ["new-workspace"]:
            cwd = os.getcwd()
            name = "w"
            it = iter(a[1:])
            for tok in it:
                if tok == "--cwd":
                    cwd = next(it, None)
                elif tok == "--name":
                    name = next(it, None)
                elif tok == "--focus":
                    next(it, None)
            u = str(uuid.uuid4())
            rows = load()
            rows.append({"workspace_uuid": u, "name": name, "cwd": cwd})
            save(rows)
            print(u)
            sys.exit(0)
        if a[:1] == ["close-workspace"]:
            target = None
            it = iter(a[1:])
            for tok in it:
                if tok == "--workspace":
                    target = next(it, None)
            rows = [r for r in load() if r.get("workspace_uuid") != target]
            save(rows)
            sys.exit(0)
        if a[:1] == ["send"]:
            sys.stdout.write(a[-1])
            sys.exit(0)
        print("fake-cmux-unhandled: " + " ".join(a)); sys.exit(1)
    """))

    git = bindir / "git"
    write_fake(git, textwrap.dedent("""\
        import sys, os
        a = sys.argv[1:]
        # support -C <repo> prefix
        repo = "."
        if a[:1] == ["-C"]:
            repo = a[1]; a = a[2:]
        if a[:2] == ["rev-parse", "--is-inside-work-tree"]:
            print("true"); sys.exit(0)
        if a[:2] == ["rev-parse", "--verify"]:
            sys.exit(0)
        if a[:2] == ["worktree", "add"]:
            wt = a[-2]
            os.makedirs(wt, exist_ok=True)
            print("created " + wt); sys.exit(0)
        if a[:2] == ["status", "--porcelain"]:
            sys.exit(0)  # clean
        if a[:2] == ["branch", "--merged"]:
            if os.environ.get("FAKE_MERGED", "0") == "1":
                print(a[-1] if a else "")
            sys.exit(0)
        if a[:2] == ["worktree", "remove"]:
            sys.exit(0)
        if a[:1] == ["branch"]:
            sys.exit(0)
        print("fake-git-unhandled: " + " ".join(a)); sys.exit(1)
    """))

    ts = bindir / "tailscale"
    write_fake(ts, 'import sys; print("ok"); sys.exit(0)\n')

    env.update({
        "SSH_BIN": str(ssh),
        "CMUX_BIN": str(cmux),
        "GIT_BIN": str(git),
        "TAILSCALE_BIN": str(ts),
        "PATH": f"{bindir}:/usr/bin:/bin",
        "CMUX_HERMES_TARGET": "vps-fake",
        "CMUX_HERMES_ALLOWED_TARGETS": "vps-fake",
        "CMUX_HERMES_STATE_DIR": str(tmp / "state"),
        "FAKE_CMUX_STATE": str(tmp / "cmux-state.json"),
    })
    return tmp


RESULTS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, cond, detail))
    status = "ok" if cond else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" - {detail}"
    print(line)


def main() -> int:
    broker = load_broker()
    base_env = dict(os.environ)
    tmp = setup_fakes(base_env)
    repo = tmp / "repo"
    repo.mkdir()

    os.environ.update(base_env)

    def fake_remote_run(target, command, stdin=None, timeout=None):
        cmd = list(command)
        rc, out = 0, b""
        if cmd[:2] == ["id", "-un"]:
            out = b"hermes\n"
        elif "sessions" in cmd and "export" in cmd:
            rows = json.loads(os.environ.get("FAKE_USAGE_JSON", "[]"))
            sid = cmd[cmd.index("--session-id") + 1] if "--session-id" in cmd else None
            chosen = [r for r in rows if sid is None or str(r.get("id") or r.get("session_id")) == sid]
            out = ("\n".join(json.dumps(r) for r in chosen) + ("\n" if chosen else "")).encode()
        elif "sh" in cmd and "-c" in cmd:
            out = b"HERMES-OUT\nSession ID: s1\n"
        elif cmd[:2] == ["tmux", "has-session"]:
            rc = 0
        return subprocess.CompletedProcess(cmd, rc, out, b"")

    broker.remote_run = fake_remote_run
    broker.assert_tailnet_target = lambda target: {
        "target": target,
        "effective_hostname": "100.64.0.10",
        "peer": "fake.tailnet",
        "tailscale_ips": ["100.64.0.10"],
    }

    # doctor (token-free)
    rc = broker.main(["doctor"])
    check("doctor exits 0", rc == 0, f"rc={rc}")

    # path safety
    for bad in ["relative/path", "../escape", "foo/../../bar"]:
        try:
            broker.safe_abs_path(bad)
            check(f"reject unsafe path {bad}", False, "not rejected")
        except broker.BrokerError:
            check(f"reject unsafe path {bad}", True)

    check("accept absolute path", str(broker.safe_abs_path("/tmp/x")).startswith("/") and "x" in str(broker.safe_abs_path("/tmp/x")))

    try:
        broker.remote_argv("-oProxyCommand=bad", ["id", "-un"])
        check("reject ssh option injection", False)
    except broker.BrokerError:
        check("reject ssh option injection", True)
    ssh_argv = broker.remote_argv("vps-fake", ["id", "-un"])
    check("ssh forwarding disabled", "ForwardAgent=no" in ssh_argv and
          "ClearAllForwardings=yes" in ssh_argv)

    symlink_root = repo / ".cmux-hermes-worktrees"
    symlink_root.symlink_to(tmp / "outside", target_is_directory=True)
    rc = broker.main(["lane", str(repo), "--base", "main", "--slug", "escape", "--dry-run"])
    check("reject symlinked worktree root", rc == 2, f"rc={rc}")
    symlink_root.unlink()

    # advisor without opt-in must be blocked
    rc = broker.main(["advisor", "--model", "gpt-x", "--prompt-file", __file__])
    check("advisor without --yes blocked", rc == 2, f"rc={rc}")

    # advisor with unsafe model must be blocked
    rc = broker.main(["advisor", "--yes", "--model", "bad model$"])
    check("advisor unsafe model blocked", rc == 2, f"rc={rc}")

    # advisor stays fail-closed because installed Hermes exposes -q via argv.
    os.environ["FAKE_USAGE_JSON"] = json.dumps([
        {"id": "s1", "billing_provider": "p", "model": "m", "input_tokens": 10, "output_tokens": 5},
    ])
    rc = broker.main(["advisor", "--yes", "--model", "gpt-x", "--prompt-file", __file__])
    check("advisor opt-in remains capability-blocked", rc == 2, f"rc={rc}")

    # exact-session usage grouping
    rows = [
        {"id": "root", "parent_session_id": None, "billing_provider": "p", "model": "m", "input_tokens": 1, "output_tokens": 1},
        {"id": "c1", "parent_session_id": "root", "billing_provider": "p", "model": "m", "input_tokens": 2, "output_tokens": 2},
        {"id": "c2", "parent_session_id": "c1", "billing_provider": "q", "model": "n", "input_tokens": 4, "output_tokens": 4},
    ]
    grouped = broker.recursive_usage.__wrapped__ if hasattr(broker.recursive_usage, "__wrapped__") else None
    # call through fake ssh by setting env and using the real path:
    os.environ["FAKE_USAGE_JSON"] = json.dumps(rows)
    res = broker.recursive_usage("vps-fake", "root")
    scoped = res["scoped_rows"]
    check("usage scopes exact session", scoped == 1, f"scoped={scoped}")
    check("usage groups provider", set(res["grouped"].keys()) == {"p/m"})

    # lane dry-run validates without creating
    rc = broker.main(["lane", str(repo), "--base", "main", "--slug", "feat-x", "--dry-run"])
    check("lane dry-run exits 0", rc == 0, f"rc={rc}")

    # lane create
    lane_out = io.StringIO()
    with redirect_stdout(lane_out):
        rc = broker.main(["lane", str(repo), "--base", "main", "--slug", "feat-y",
                          "--task-id", "task-feat-y"])
    check("lane create exits 0", rc == 0, f"rc={rc}")
    lane = json.loads(lane_out.getvalue())
    capability_file = lane["owner_capability_file"]
    persisted = broker.load_manifest("task-feat-y")
    check("owner capability not persisted", "owner_capability" not in persisted)
    wt = repo / ".cmux-hermes-worktrees" / "feat-y"
    check("lane created worktree", wt.exists(), str(wt))

    wrong_capability = broker.capabilities_dir() / "cap-wrong"
    wrong_capability.write_text("x" * 40, encoding="utf-8")
    os.chmod(wrong_capability, 0o600)
    rc = broker.main(["close", "--task", "task-feat-y",
                      "--owner-capability-file", str(wrong_capability)])
    check("wrong owner capability blocked", rc == 2, f"rc={rc}")
    rc = broker.main(["close", "--task", "task-feat-y",
                      "--owner-capability-file", capability_file])
    check("correct owner capability accepted", rc == 0, f"rc={rc}")

    rc = broker.main(["lane", str(repo), "--base", "main", "--slug", "invalid-id",
                      "--task-id", "../bad"])
    check("invalid task id blocked before side effects", rc == 2 and
          not (repo / ".cmux-hermes-worktrees" / "invalid-id").exists(), f"rc={rc}")
    rc = broker.main(["lane", str(repo), "--base", "main", "--slug", "collision",
                      "--task-id", "task-feat-y"])
    check("task id collision blocked before side effects", rc == 2 and
          not (repo / ".cmux-hermes-worktrees" / "collision").exists(), f"rc={rc}")

    # one-owner lock enforcement on a random task
    try:
        broker._enforce_single_owner(
            "task-doesnotexist", str(broker.capabilities_dir() / "missing")
        )
        check("enforce owner lock missing", False)
    except broker.BrokerError:
        check("enforce owner lock missing", True)

    # tasks listing
    rc = broker.main(["tasks"])
    check("tasks list exits 0", rc == 0)

    # send to explicit UUID
    rc = broker.main(["send", "--workspace", "11111111-1111-1111-1111-111111111111",
                      "--surface", "22222222-2222-2222-2222-222222222222",
                      "--message", "hello"])
    check("send explicit uuid exits 0", rc == 0, f"rc={rc}")
    rc = broker.main(["send", "--workspace", "11111111-1111-1111-1111-111111111111",
                      "--surface", "22222222-2222-2222-2222-222222222222",
                      "--message=--workspace=attacker"])
    check("send dash-prefixed text safely", rc == 0, f"rc={rc}")

    # send with bad uuid blocked
    rc = broker.main(["send", "--workspace", "not-a-uuid", "--surface",
                      "22222222-2222-2222-2222-222222222222", "--message", "x"])
    check("send bad uuid blocked", rc == 2, f"rc={rc}")

    # recursive usage with no session still works
    res2 = broker.recursive_usage("vps-fake", None)
    check("usage all rows", res2["scoped_rows"] == 3, f"scoped={res2['scoped_rows']}")

    # --- workspace reuse decision (pure, structured inventory) -------------
    def set_cmux(rows):
        with open(os.environ["FAKE_CMUX_STATE"], "w") as fh:
            json.dump(rows, fh)

    def get_cmux():
        try:
            with open(os.environ["FAKE_CMUX_STATE"]) as fh:
                return json.load(fh)
        except Exception:
            return []

    proj = tmp / "proj"
    proj.mkdir()
    proj_c = str(proj.resolve())

    inv = [{"workspace_uuid": str(uuidlib.uuid4()), "cwd": proj_c, "name": "w"}]
    r = broker.resolve_cmux_workspace(Path(proj_c), inv)
    check("resolve exact reuse", r["decision"] == "reuse"
          and r["match_type"] == "exact", str(r["decision"]))

    inv = [{"workspace_uuid": str(uuidlib.uuid4()), "cwd": str(proj / "sub")}]
    r = broker.resolve_cmux_workspace(Path(proj_c), inv)
    check("resolve inside-project reuse", r["decision"] == "reuse"
          and r["match_type"] == "inside-project", str(r["decision"]))

    inv = [{"workspace_uuid": str(uuidlib.uuid4()), "cwd": str(tmp)}]
    r = broker.resolve_cmux_workspace(Path(proj_c), inv)
    check("resolve broad-parent not reused", r["decision"] == "missing"
          and bool(r["advisory"]), str(r["decision"]))

    inv = [{"workspace_uuid": str(uuidlib.uuid4()), "cwd": proj_c},
           {"workspace_uuid": str(uuidlib.uuid4()), "cwd": proj_c}]
    r = broker.resolve_cmux_workspace(Path(proj_c), inv)
    check("resolve ambiguity exact", r["decision"] == "ambiguous", str(r["decision"]))

    try:
        broker.parse_cmux_inventory(
            json.dumps({"workspaces": [{"workspace_uuid": "bad", "cwd": proj_c}]}))
        malformed_uuid_blocked = False
    except broker.BrokerError:
        malformed_uuid_blocked = True
    check("parse blocks malformed uuid", malformed_uuid_blocked)
    try:
        broker.parse_cmux_inventory(
            json.dumps({"workspaces": [{"workspace_uuid": str(uuidlib.uuid4()),
                                        "cwd": "relative"}]}))
        malformed_path_blocked = False
    except broker.BrokerError:
        malformed_path_blocked = True
    check("parse blocks relative cwd", malformed_path_blocked)

    live_shape_uuid = str(uuidlib.uuid4()).upper()
    parsed = broker.parse_cmux_inventory(json.dumps({"workspaces": [{
        "id": live_shape_uuid,
        "current_directory": proj_c,
        "title": "live-shape",
    }]}))
    check("parse live cmux schema and uppercase UUID",
          len(parsed) == 1
          and parsed[0]["workspace_uuid"] == live_shape_uuid
          and parsed[0]["cwd"] == proj_c,
          str(parsed))

    # --- workspace ensure create (empty inventory) -------------------------
    set_cmux([])
    out = io.StringIO()
    with redirect_stdout(out):
        rc = broker.main(["workspace", "ensure", "--cwd", str(proj), "--name", "ws-ensure"])
    ensure = json.loads(out.getvalue())
    check("ensure creates when missing", rc == 0 and ensure["origin"] == "created", f"rc={rc}")

    # --- ensure reuses exact (now present) ----------------------------------
    out = io.StringIO()
    with redirect_stdout(out):
        rc = broker.main(["workspace", "ensure", "--cwd", str(proj), "--name", "ws-ensure2"])
    ensure = json.loads(out.getvalue())
    check("ensure reuses exact", rc == 0 and ensure["origin"] == "reused", f"rc={rc}")

    # --- failed post-create validation rolls back only the new workspace ---
    set_cmux([])
    os.environ["FAKE_CMUX_HIDE_INVENTORY"] = "1"
    try:
        rc = broker.main(["workspace", "ensure", "--cwd", str(proj),
                          "--name", "ws-hidden-after-create"])
    finally:
        os.environ.pop("FAKE_CMUX_HIDE_INVENTORY", None)
    check("post-create validation failure blocked", rc == 2, f"rc={rc}")
    check("unvalidated created workspace rolled back", get_cmux() == [],
          str(get_cmux()))

    # --- ensure ambiguity blocked (TOCTOU recheck also ambiguous) ----------
    set_cmux([
        {"workspace_uuid": str(uuidlib.uuid4()), "cwd": str(proj), "name": "a"},
        {"workspace_uuid": str(uuidlib.uuid4()), "cwd": str(proj), "name": "b"},
    ])
    rc = broker.main(["workspace", "ensure", "--cwd", str(proj), "--name", "ws-amb"])
    check("ensure ambiguity blocked", rc == 2, f"rc={rc}")

    # --- lane reuses a pre-existing exact workspace ------------------------
    set_cmux([])
    reuse_slug = "reuse-lane"
    reuse_wt = str((repo / ".cmux-hermes-worktrees" / reuse_slug).resolve())
    seed_uuid = str(uuidlib.uuid4())
    set_cmux([{"workspace_uuid": seed_uuid, "cwd": reuse_wt, "name": "preexisting"}])
    out = io.StringIO()
    with redirect_stdout(out):
        rc = broker.main(["lane", str(repo), "--base", "main",
                          "--slug", reuse_slug, "--task-id", "task-reuse"])
    check("lane reuse exits 0", rc == 0, f"rc={rc}")
    lane2 = json.loads(out.getvalue())
    check("lane reused existing workspace",
          lane2.get("workspace_origin") == "reused"
          and lane2.get("created_workspace") is False,
          str(lane2.get("workspace_origin")))

    # --- cancel preserves a reused workspace -------------------------------
    cap2 = lane2["owner_capability_file"]
    rc = broker.main(["cancel", "--task", "task-reuse", "--owner-capability-file", cap2])
    check("cancel reused workspace exits 0", rc == 0, f"rc={rc}")
    after = get_cmux()
    check("reused workspace preserved after cancel",
          any(w.get("workspace_uuid") == seed_uuid for w in after), str(len(after)))

    # --- read-only resolve subcommand ---------------------------------------
    set_cmux([{"workspace_uuid": seed_uuid, "cwd": proj_c, "name": "w"}])
    out = io.StringIO()
    with redirect_stdout(out):
        rc = broker.main(["resolve", proj_c])
    rr = json.loads(out.getvalue())
    check("resolve subcommand reuses", rc == 0 and rr["decision"] == "reuse", str(rr["decision"]))

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
