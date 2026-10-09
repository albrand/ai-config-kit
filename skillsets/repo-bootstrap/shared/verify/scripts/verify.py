#!/usr/bin/env python3
"""verify: one command that decides whether a change works, the same way in every repo.

A repo describes its checks once in `.verify/config.json` (written by `init`). Every agent, every
human and the self-hosted runner then run the same thing:

  verify.py doctor   [repo] [--online] [--json]   audit any repo (new or legacy): what is missing
  verify.py init     [repo] [--write]             detect the stack and propose .verify/config.json
  verify.py run      [repo] [--stages a,b] [--strict] [--base REF] [--post-status]
  verify.py status   [repo] [--sha SHA]           last result for a commit (local artifact + forge)
  verify.py serve    --repo PATH|OWNER/NAME [...] [--once]   self-hosted runner (no GitHub Actions)
  verify.py weaken-check [repo] [--base REF]      fail when a change skips, deletes or loosens tests
  verify.py mutation-targets [repo] [--base REF]  changed source files to mutate
  verify.py eval-score --dataset D --predictions P [--thresholds T]   score non-deterministic output
  verify.py housekeep [repo] [--apply]            list (and with --apply, do) safe repo cleanup
  verify.py hook                                  PostToolUse note after a merge/deploy (never blocks)

Stages, in order: static, unit, integration, journeys, evals, rehearsal (per change); mutation
(scheduled); postdeploy (after a deploy). A stage is pass, fail, missing (no command and no `na`
reason), na (declared not applicable, with a reason) or untouched (path-filtered and not touched).
Only all-pass-or-na is green. `missing` is never green: it reports NOT VERIFIED.

Strict mode (the runner always uses it): a required env var that is absent FAILS the stage instead
of letting the suite skip itself, and a suite that reports more skipped tests than `max_skipped`
fails. Results are advisory commit statuses; nothing here blocks a merge or a deploy.
Python 3.9+ standard library only.
"""
from __future__ import annotations

import argparse
import fcntl
import fnmatch
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
CONFIG = Path(".verify/config.json")
RUNS = Path(".verify/runs")
PER_CHANGE = ["static", "unit", "integration", "journeys", "evals", "rehearsal"]
ALL_STAGES = PER_CHANGE + ["mutation", "postdeploy"]
DEFAULT_MAX_SKIPPED = {"integration": 0, "journeys": 0, "evals": 0}
DISK_FLOOR_GB = 20
STATUS_PREFIX = "verify"
RUNNER_HOME = Path(os.environ.get("VERIFY_RUNNER_HOME", "~/.cache/verify-runner")).expanduser()
FORGE_TOKENS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
# Runner jobs run PR code. They get these variables from the runner's environment and nothing else.
JOB_ENV_KEEP = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ", "USER", "LOGNAME", "SHELL", "NVM_DIR", "VOLTA_HOME",
                "PYENV_ROOT", "BUN_INSTALL", "PNPM_HOME", "CARGO_HOME", "RUSTUP_HOME", "DOTNET_ROOT", "GOPATH",
                "GOMODCACHE", "PLAYWRIGHT_BROWSERS_PATH")
# Toolchains under $HOME that jobs may read (and run). Everything else under /Users stays unreadable.
TOOLCHAIN_DIRS = (".nvm", ".volta", ".fnm", ".local/share/fnm", ".bun", ".deno", ".cargo", ".rustup", ".pyenv", ".rbenv",
                  ".asdf", ".local/share/mise", ".local/share/pnpm", "Library/pnpm", ".dotnet", "go/pkg/mod", ".sdkman",
                  "Library/Caches/ms-playwright", ".cache/ms-playwright")
TOOLCHAIN_SECRETS = (".cargo/credentials", ".cargo/credentials.toml")
SANDBOX_EXEC = "/usr/bin/sandbox-exec"

# ---------------------------------------------------------------- helpers


def kill_group(proc):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            return
        try:
            proc.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            continue


def sh(cmd, cwd=None, env=None, timeout=None, merge=True):
    """Run a command (list or shell string) in its own process group; return (rc, output).

    A timeout kills the whole group, so dev servers and browsers started by a test die with it.
    merge=False returns stdout only (for output that gets parsed).
    """
    try:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, shell=isinstance(cmd, str), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT if merge else subprocess.PIPE, text=True,
                             errors="replace", start_new_session=True)
    except (FileNotFoundError, NotADirectoryError) as e:
        return 127, str(e)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(p)
        out, _ = p.communicate()
        return 124, (out or "") + f"\n[verify] timed out after {timeout}s"
    return p.returncode, out or ""


def git(repo, *args, timeout=60, env=None):
    rc, out = sh(["git", "-C", str(repo), *args], env=env, timeout=timeout, merge=False)
    return out.strip() if rc == 0 else ""


def repo_root(path=".", allow_bare=False):
    root = git(path, "rev-parse", "--show-toplevel")
    if root:
        return Path(root)
    if allow_bare and git(path, "rev-parse", "--is-bare-repository") == "true":
        return Path(path).expanduser().resolve()
    sys.exit(f"[verify] not a git work tree: {path}")


def slug_of(url):
    m = re.search(r"github\.com[^:/]*[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url or "")
    return m.group(1) if m else None


def forge_slug(repo):
    return slug_of(git(repo, "remote", "get-url", "origin"))


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_hours(iso):
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600
    except (AttributeError, ValueError):
        return 0.0


def free_gb(path):
    return shutil.disk_usage(path).free / 1e9


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def tracked_files(repo, ref="HEAD"):
    out = git(repo, "ls-tree", "-r", "--name-only", ref, timeout=120)
    return out.splitlines() if out else []


def read_blobs(repo, ref, paths, limit=400_000):
    """Read many files at `ref` in one `git cat-file --batch`: works on bare repos and needs no checkout."""
    paths = [p for p in dict.fromkeys(paths) if "\n" not in p]
    if not paths:
        return {}
    p = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    out, _ = p.communicate("".join(f"{ref}:{x}\n" for x in paths).encode(), timeout=600)
    res, i = {}, 0
    for path in paths:
        nl = out.find(b"\n", i)
        if nl < 0:
            break
        header = out[i:nl].decode(errors="replace")
        i = nl + 1
        parts = header.split()
        if len(parts) != 3 or not parts[2].isdigit():
            continue  # "<name> missing" / "ambiguous"
        size = int(parts[2])
        if parts[1] == "blob":
            res[path] = out[i:i + min(size, limit)].decode(errors="replace")
        i += size + 1
    return res


def stage_env(base_env, _spec=None):
    """Stage commands never see forge tokens. A stage's `env` list only names variables it requires."""
    return {k: v for k, v in base_env.items() if k not in FORGE_TOKENS}


def wrapped(cmd, wrap):
    """`cmd` (shell string or argv) run under the `wrap` prefix (the sandbox), or as is without one."""
    if not wrap:
        return cmd
    return [*wrap, "/bin/sh", "-c", cmd] if isinstance(cmd, str) else [*wrap, *cmd]


def redact(text, secrets):
    for s in secrets:
        text = text.replace(s, "***")
    return text


# ---------------------------------------------------------------- detection

TEST_RE = re.compile(r"(\.(test|spec)\.[cm]?[jt]sx?$|(^|/)test_[^/]+\.py$|_test\.(py|go)$|Tests?\.cs$|(^|/)__tests__/)")
TEST_PATH_RE = re.compile(TEST_RE.pattern + r"|(^|/)(tests?|e2e|journeys|spec)/")
INTEG_RE = re.compile(r"integration|\.int\.|(^|/)it/", re.I)
E2E_RE = re.compile(r"(^|/)(e2e|playwright|journeys|cypress)/|\.e2e\.|\.journey\.", re.I)
# A journey fakes the backend when it uses a mock server, or answers the app's own API itself (route.fulfill
# on an /api/, tRPC or GraphQL route). Routing that only continues or aborts requests (an allow-list of
# origins, blocking third parties) still reaches the real backend. Component tests may mock freely.
MOCK_SERVER_RE = re.compile(r"\bsetupServer\(|from ['\"]msw|\bnock\(|cy\.intercept\([^)]*,\s*\{|cy\.intercept\([^)]*fixture")
ROUTE_ARG_RE = re.compile(r"\.route\(\s*([^,]{1,200}),")
OWN_API_RE = re.compile(r"/api/|trpc|graphql", re.I)
COMPONENT_TEST_RE = re.compile(r"(^|/)component/|\.ct\.[cm]?[jt]sx?$|\.component\.(spec|test)\.", re.I)


def fakes_backend(text):
    if MOCK_SERVER_RE.search(text):
        return True
    if ".fulfill(" not in text:
        return False
    for m in ROUTE_ARG_RE.finditer(text):
        arg = m.group(1).strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", arg):      # a variable: read what it was set to
            v = re.search(rf"\b(?:const|let|var)\s+{re.escape(arg)}\s*=\s*([^;]{{1,300}})", text)
            arg = v.group(1) if v else ""
        if OWN_API_RE.search(arg.replace("\\", "")):
            return True
    return False
ENV_SKIP_RE = re.compile(
    r"skip:\s*!|\.skipIf\(|(describe|it|test)\.skip\(\s*!|pytest\.mark\.skipif|\.skip\(\s*!?process\.env|"
    r"if\s*\(\s*!process\.env\.[A-Z0-9_]+\s*\)\s*(return|test\.skip|this\.skip)")
BACKGROUND_RE = re.compile(r"(^|/)(cron|crons|queue|queues|worker|workers|jobs?|backfill|pipeline|ingest\w*|processor|consumers?|outbox|sync)(/|\.|-|_)", re.I)
LLM_DEPS = re.compile(r"^(openai|@anthropic-ai/sdk|ai|@ai-sdk/.+|langchain|@langchain/.+|anthropic|cohere-ai|@google/generative-ai|ollama|groq-sdk|@mistralai/.+)$")
LLM_PY = re.compile(r"^\s*(from|import)\s+(openai|anthropic|langchain|litellm|google\.generativeai|cohere|mistralai)\b", re.M)
SRC_EXT = re.compile(r"\.(ts|tsx|js|jsx|mjs|cjs|py|cs|go|rb|java|kt)$")
NODE_PM = [("pnpm-lock.yaml", "pnpm run", "pnpm install --frozen-lockfile"),
           ("yarn.lock", "yarn", "yarn install --frozen-lockfile"),
           ("bun.lock", "bun run", "bun install --frozen-lockfile"),
           ("bun.lockb", "bun run", "bun install --frozen-lockfile"),
           ("package-lock.json", "npm run", "npm ci")]


UI_DEPS = {"next", "react", "vue", "svelte", "@sveltejs/kit", "@angular/core", "electron", "vite", "nuxt", "astro",
           "@remix-run/react", "solid-js", "react-native", "expo"}
SERVICE_DEPS = {"express", "hono", "@nestjs/core", "fastify", "koa", "@hapi/hapi"}
SERVICE_PY = re.compile(r"\b(fastapi|flask|django|starlette|aiohttp)\b", re.I)


def detect(repo, ref="HEAD"):
    repo = Path(repo)
    files = tracked_files(repo, ref)
    fset = set(files)
    tests = [f for f in files if TEST_RE.search(f)]
    e2e_files = [f for f in files if E2E_RE.search(f) and SRC_EXT.search(f)]
    wf = [f for f in files if f.startswith(".github/workflows/")]
    py = [f for f in files if f.endswith(".py")][:400]
    manifests = [f for f in ("package.json", "pyproject.toml", "requirements.txt", str(CONFIG)) if f in fset]
    blobs = read_blobs(repo, ref, manifests + tests + e2e_files + wf + py)
    text = lambda rel: blobs.get(rel, "")
    d = {"repo": str(repo), "ref": ref, "stacks": [], "commands": {}, "setup": None, "files": len(files)}
    try:
        pkg = json.loads(text("package.json")) if "package.json" in fset else {}
    except ValueError:
        pkg = {}
    scripts = pkg.get("scripts", {}) if pkg else {}
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})} if pkg else {}
    if pkg:
        d["stacks"].append("node")
        run, setup = next(((r, s) for lock, r, s in NODE_PM if lock in fset), ("npm run", "npm install"))
        d["setup"] = setup

        def pick(*names):
            return next((n for n in names if n in scripts), None)

        static = [n for n in ("lint", "typecheck", "type-check", "check:types", "format:check") if n in scripts]
        if static:
            d["commands"]["static"] = " && ".join(f"{run} {n}" for n in static)
        if "build" in scripts:
            d["commands"]["build"] = f"{run} build"
        unit = pick("test:unit", "test")
        if unit:
            d["commands"]["unit"] = f"{run} {unit}"
        integ = sorted(n for n in scripts if n.startswith("test:integration"))
        if integ:
            d["commands"]["integration"] = " && ".join(f"{run} {n}" for n in integ)
        e2e = pick("test:journeys", "test:e2e", "e2e")
        if e2e:
            d["commands"]["journeys"] = f"{run} {e2e}"
        for k in ("next", "react", "vue", "svelte", "@angular/core", "electron", "express", "hono", "@nestjs/core", "vite"):
            if k in deps:
                d["stacks"].append(k)
        if "@playwright/test" in deps:
            d["stacks"].append("playwright")
        if any(k.startswith("@stryker-mutator/") for k in deps):
            d["stacks"].append("stryker")
            d["commands"]["mutation"] = f"{run} test:mutation" if "test:mutation" in scripts else "npx stryker run"
    if fset & {"pyproject.toml", "requirements.txt", "setup.py", "setup.cfg"}:
        d["stacks"].append("python")
        d["commands"].setdefault("static", "ruff check .")
        d["commands"].setdefault("unit", "pytest -q")
    if any(f.endswith((".sln", ".csproj")) for f in files):
        d["stacks"].append("dotnet")
        d["commands"].setdefault("static", "dotnet build --nologo -warnaserror")
        d["commands"].setdefault("unit", "dotnet test --nologo")
    if "go.mod" in fset:
        d["stacks"].append("go")
        d["commands"].setdefault("static", "go vet ./...")
        d["commands"].setdefault("unit", "go test ./...")
    if fset & {"vercel.json", "vercel.ts"}:
        d["stacks"].append("vercel")
    if "pubspec.yaml" in fset:
        d["stacks"].append("flutter")
    pytext = text("pyproject.toml") + text("requirements.txt")
    d["has_ui"] = bool(UI_DEPS & set(deps)) or "pubspec.yaml" in fset or any(f.endswith((".razor", ".cshtml", ".vue", ".svelte")) for f in files)
    d["has_service"] = bool(SERVICE_DEPS & set(deps)) or bool(SERVICE_PY.search(pytext)) \
        or any(re.search(r"(^|/)Controllers/.+\.cs$", f) for f in files) or "next" in deps
    d["tests"] = {
        "total": len(tests),
        "integration": sum(1 for f in tests if INTEG_RE.search(f)),
        "e2e": sum(1 for f in files if E2E_RE.search(f) and re.search(r"\.(spec|test|journey)\.[cm]?[jt]sx?$", f)),
    }
    d["e2e_mocking_files"] = [f for f in e2e_files if not COMPONENT_TEST_RE.search(f) and fakes_backend(text(f))][:20]
    d["env_gated_skip_files"] = sum(1 for f in tests if ENV_SKIP_RE.search(text(f)))
    d["background_paths"] = sorted({m.group(0).strip("/._-") for f in files if SRC_EXT.search(f) and not TEST_RE.search(f)
                                     for m in [BACKGROUND_RE.search(f)] if m})[:15]
    d["llm"] = any(LLM_DEPS.match(k) for k in deps) or any(LLM_PY.search(text(f)[:20_000]) for f in py)
    d["evals"] = sorted({"/".join(f.split("/")[:2]) for f in files if re.search(r"(^|/)(evals?|golden)(/|\.)", f, re.I)})[:10]
    wf_text = "\n".join(text(f) for f in wf)
    d["ci"] = {
        "workflows": len(wf),
        "runs_tests": bool(re.search(r"\b(test|pytest|vitest|jest|go test|dotnet test)\b", wf_text)),
        "runs_integration": bool(re.search(r"integration", wf_text, re.I)),
        "runs_e2e": bool(re.search(r"playwright|e2e|cypress|journeys", wf_text, re.I)),
    }
    try:
        d["config"] = json.loads(text(str(CONFIG))) if str(CONFIG) in fset else None
    except ValueError:
        d["config"] = None
    d["has_config"] = d["config"] is not None
    d["mutation_config"] = "stryker" in d["stacks"] or any(re.search(r"stryker\.(conf|config)|mutmut", f) for f in files) \
        or "[tool.mutmut]" in pytext
    if "[tool.mutmut]" in pytext or "mutmut" in pytext:
        d["commands"].setdefault("mutation", "mutmut run")
    d["agents_md"] = [f for f in ("AGENTS.md", "CLAUDE.md", ".bb/AGENTS.md") if f in fset]
    return d


# ---------------------------------------------------------------- init

def proposal(d):
    c = d["commands"]

    def stage(cmd, todo=None, **kw):
        s = {"run": cmd, **{k: v for k, v in kw.items() if v is not None}}
        if not cmd and todo:
            s["todo"] = todo
        return s

    cfg = {"version": 1}
    if d.get("setup"):
        cfg["setup"] = d["setup"]
    cfg["stages"] = {
        "static": stage(" && ".join(x for x in (c.get("static"), c.get("build")) if x) or None,
                        todo="lint + typecheck + build"),
        "unit": stage(c.get("unit"), todo="fast tests of the logic users depend on"),
        "integration": stage(c.get("integration"), todo="real database/queue tests; see templates/README.md#integration",
                             env=[], max_skipped=0),
        "journeys": stage(c.get("journeys"), todo="users walking through the running app; see templates/journeys",
                          max_skipped=0) if c.get("journeys") or d.get("has_ui") or d.get("has_service")
        else {"run": None, "na": "no user interface or network service detected"},
        "evals": stage(None, todo="LLM features found: build an eval set; see templates/evals") if d["llm"]
        else {"run": None, "na": "no LLM features detected"},
        "rehearsal": stage(None, todo="read-only dry run of data-moving code on production-shaped data",
                           paths=[f"**/{p}/**" for p in d["background_paths"][:6]]) if d["background_paths"]
        else {"run": None, "na": "no background processing detected"},
        "mutation": stage(c.get("mutation"), todo="see templates/mutation", schedule="nightly", min_score=60),
        "postdeploy": stage(None, todo="health + @smoke journeys against the deployed URL; see templates/postdeploy"),
    }
    return cfg


# ---------------------------------------------------------------- forge (GitHub REST; no Actions involved)

# The runner's forge calls on a loaded host: gh can take over a minute to start, so a call gets FORGE_TIMEOUT and
# one retry, drawn from a ForgeBudget shared by one serve tick. A retried post whose first try was accepted adds a
# second record for the context; the combined status (what forge_status and the hook read) shows only the latest
# per context, so the state is the same. Interactive callers (`run --post-status`, the hook, doctor) keep one
# short try.
FORGE_TIMEOUT, FORGE_ATTEMPTS, FORGE_BUDGET = 120, 2, 600


class ForgeBudget:
    """The long-limit forge waits one serve tick may spend. A call gets FORGE_TIMEOUT and FORGE_ATTEMPTS while what
    is left covers that worst case; after that it gets the callee's short single try, as interactive callers do. So
    however many posts and reads a tick makes, the long limit adds at most FORGE_BUDGET seconds of waiting to it."""

    def __init__(self, seconds=None, clock=time.monotonic):
        self.left, self.clock = FORGE_BUDGET if seconds is None else seconds, clock

    def call(self, fn, *args):
        """fn(*args, timeout, attempts) on the long limit, or fn(*args) with its own short defaults."""
        if self.left < FORGE_TIMEOUT * FORGE_ATTEMPTS:
            return fn(*args)
        start = self.clock()
        try:
            return fn(*args, FORGE_TIMEOUT, FORGE_ATTEMPTS)
        finally:
            self.left -= self.clock() - start


def forge_status(slug, sha, timeout=20, attempts=1):
    """{context: {state, at}} for the commit, or None when the forge can't be read (auth, network)."""
    for _ in range(attempts):
        rc, out = sh(["gh", "api", f"repos/{slug}/commits/{sha}/status",
                      "--jq", "[.statuses[]|{(.context): {state: .state, at: .updated_at}}]|add // {}"],
                     timeout=timeout, merge=False)
        if rc == 0:
            break
    if rc != 0:
        return None
    try:
        return json.loads(out or "{}") or {}
    except ValueError:
        return None


GH_STATE = {"pass": "success", "na": "success", "untouched": "success", "fail": "failure",
            "missing": "error", "not-verified": "error", "pending": "pending"}


UNSANDBOXED_PR = "unsandboxed PR job: its code could rewrite the verifier, so a pass is not trusted"


def capped_post(post):
    """`post` for a PR job run with --unsandboxed: nothing stops its code from rewriting a pinned verifier file
    between stages, so no status it reports, per stage or overall, is ever green; a pass is reported as missing
    with the reason. Fail stays fail. (PR code with host access could also post a status itself with the host's
    forge credentials; that is the risk --unsandboxed accepts on a disposable machine.)"""
    def capped(context, state, description):
        if GH_STATE.get(state) == "success":
            return post(context, "missing", f"{state}, not trusted: {UNSANDBOXED_PR}; {description}")
        return post(context, state, description)
    return capped


def post_status(slug, sha, context, state, description, timeout=30, attempts=1):
    """Commit statuses are a plain REST call: they work with GitHub Actions disabled or unpaid."""
    for _ in range(attempts):
        rc, out = sh(["gh", "api", "-X", "POST", f"repos/{slug}/statuses/{sha}", "-f", f"state={GH_STATE[state]}",
                      "-f", f"context={context}", "-f", f"description={description[:139]}"], timeout=timeout)
        if rc == 0:
            break
    if rc != 0:
        print(f"[verify] could not post {context} to {slug}@{sha[:9]}: {out.strip()[-300:]}", file=sys.stderr, flush=True)
    return rc == 0


# ---------------------------------------------------------------- doctor

def doctor(repo, online=False, ref="HEAD"):
    d = detect(repo, ref)
    cfg = read_json(Path(repo) / CONFIG) or d["config"]
    f = []

    def add(sev, area, msg, fix):
        f.append({"severity": sev, "area": area, "finding": msg, "fix": re.sub(r"\btemplates/", f"{TEMPLATES}/", fix)})

    if not cfg:
        add("high", "contract", "no .verify/config.json: nothing defines 'done' for this repo", "verify.py init --write, then fill the todo stages")
    else:
        for name in PER_CHANGE:
            s = cfg.get("stages", {}).get(name, {})
            if not s.get("run") and not s.get("na"):
                add("high" if name in ("unit", "integration", "journeys") else "medium", name,
                    f"stage '{name}' has no command and no na reason", s.get("todo") or "add a command or an explicit na reason")
    t = d["tests"]
    if t["total"] == 0:
        add("high", "unit", "no test files found", "start with tests for the most-used user flow")
    if t["integration"] == 0 and d["background_paths"]:
        add("high", "integration", "background processing but no integration tests", "test the processing against a real database container")
    if t["e2e"] == 0 and d["has_ui"]:
        add("high", "journeys", "no end-to-end journeys: nothing exercises frontend + backend together as a user", "templates/journeys")
    elif t["e2e"] == 0 and d["has_service"]:
        add("medium", "journeys", "no API journeys: no test drives the running service the way a client does", "templates/journeys/README.md#api")
    if d["e2e_mocking_files"]:
        add("high", "journeys", f"{len(d['e2e_mocking_files'])} e2e files answer the app's own API themselves, so they don't prove the backend works: "
            + ", ".join(d["e2e_mocking_files"][:5]), "move faked-API specs to component tests; journeys must hit the real backend (blocking third parties is fine)")
    if d["env_gated_skip_files"]:
        add("medium", "integration", f"{d['env_gated_skip_files']} test files skip themselves when an env var is missing",
            "run them in strict mode with the env provided; keep max_skipped: 0")
    if d["llm"] and not d["evals"]:
        add("high", "evals", "LLM features but no eval set: output quality is unmeasured", "templates/evals")
    if d["background_paths"] and not ((cfg or {}).get("stages", {}).get("rehearsal", {}) or {}).get("run"):
        add("medium", "rehearsal", f"data-moving code ({', '.join(d['background_paths'][:4])}) has no dry run on production-shaped data",
            "add a read-only dry-run command; see templates/README.md#rehearsal")
    if not d["mutation_config"]:
        add("low", "mutation", "no mutation testing: test strength is unknown", "templates/mutation")
    if not d["agents_md"]:
        add("low", "standards", "no AGENTS.md: agents get no repo-specific rules", "templates/AGENTS.repo.md")
    slug = forge_slug(repo)
    if online and slug:
        rc, out = sh(["gh", "run", "list", "-R", slug, "--limit", "20", "--json", "conclusion"], timeout=30, merge=False)
        if rc == 0:
            concl = [r.get("conclusion") for r in json.loads(out or "[]")]
            if concl and all(c in ("failure", "startup_failure", "cancelled", "") for c in concl):
                add("high", "ci", f"the last {len(concl)} GitHub Actions runs all failed: CI gives no signal", "use the self-hosted runner (verify.py serve)")
        sha = git(repo, "rev-parse", ref)
        st = forge_status(slug, sha)
        if st is None:
            add("medium", "ci", f"cannot read commit statuses for {slug} with the current gh auth", "check `gh auth status` for an account that can see the repo")
        elif STATUS_PREFIX not in st:
            add("medium", "ci", f"HEAD {sha[:9]} has no '{STATUS_PREFIX}' status from the runner", "register the repo with verify.py serve")
    elif not slug and not d["ci"]["workflows"]:
        add("medium", "ci", "no forge remote and no CI: only local runs decide done", "run verify.py run --strict before every handoff")
    order = {"high": 0, "medium": 1, "low": 2}
    f.sort(key=lambda x: order[x["severity"]])
    return {"detected": d, "findings": f}


# ---------------------------------------------------------------- run

SKIP_PATTERNS = [r"^#\s*skip(?:ped)?\s+(\d+)", r"(\d+)\s+skipped", r"\bskipped\s+(\d+)", r"Skipped:\s+(\d+)", r"skipped[:=]\s*(\d+)"]


def skipped_count(output):
    n = 0
    for pat in SKIP_PATTERNS:
        for m in re.finditer(pat, output, re.M | re.I):
            n = max(n, int(m.group(1)))
    return n


def changed_paths(repo, base, env=None):
    if not base:
        return None
    mb = git(repo, "merge-base", base, "HEAD", env=env)
    out = git(repo, "diff", "--name-only", f"{mb or base}...HEAD", env=env)
    return out.splitlines()


def touched(paths, globs):
    if paths is None or not globs:
        return True
    return any(fnmatch.fnmatch(p, g) or fnmatch.fnmatch(p, g.replace("**/", "")) for p in paths for g in globs)


def wait_ready(url, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 - URL comes from the repo's own config
                if r.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def run_stage(repo, name, spec, strict, paths, env, wrap=None, withheld=()):
    """Run one stage. Every command the repo controls goes through `wrap` (the runner's sandbox).
    `withheld`: secrets the runner keeps from PR jobs; a stage that needs one is not verified here."""
    res = {"stage": name, "started": now()}
    if spec.get("na"):
        return {**res, "status": "na", "detail": spec["na"]}
    if not spec.get("run"):
        return {**res, "status": "missing", "detail": spec.get("todo", "no command")}
    if not touched(paths, spec.get("paths")):
        return {**res, "status": "untouched", "detail": "no changed path matches " + ", ".join(spec["paths"])}
    if wrap and spec.get("unconfined"):
        return {**res, "status": "missing", "detail": "needs an unconfined host, so the runner's sandbox can't run it: "
                + str(spec["unconfined"]) + "; run it locally with verify.py run"}
    senv = stage_env(env, spec)
    missing = [k for k in spec.get("env", []) if not senv.get(k)]
    secret = [k for k in missing if k in withheld]
    if secret:
        return {**res, "status": "missing", "detail": "needs values the runner keeps from PR jobs: " + ", ".join(secret)
                + "; run it locally or on a --branch job"}
    if missing:
        if strict:
            return {**res, "status": "fail", "detail": "missing required env: " + ", ".join(missing)}
        return {**res, "status": "missing", "detail": "env not set locally: " + ", ".join(missing)}
    started = None
    try:
        if spec.get("services"):
            rc, out = sh(wrapped(spec["services"], wrap), cwd=repo, env=senv, timeout=spec.get("services_timeout", 600))
            if rc != 0:
                return {**res, "status": "fail", "detail": "services failed to start", "tail": out[-3000:]}
        if spec.get("base_url"):
            rc, out = sh(wrapped(spec["base_url"], wrap), cwd=repo, env=senv, timeout=600, merge=False)
            url = out.strip().splitlines()[-1] if rc == 0 and out.strip() else ""
            if not url.startswith("http"):
                return {**res, "status": "fail", "detail": "could not resolve base_url", "tail": out[-2000:]}
            senv["BASE_URL"] = url
        if spec.get("start"):
            started = subprocess.Popen(wrapped(spec["start"], wrap), cwd=repo, env=senv, shell=not wrap,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        if spec.get("ready_url") and not wait_ready(spec["ready_url"], spec.get("ready_timeout", 240)):
            return {**res, "status": "fail", "detail": f"app never became ready at {spec['ready_url']}"}
        t0 = time.time()
        rc, out = sh(wrapped(spec["run"], wrap), cwd=repo, env=senv, timeout=spec.get("timeout", 3600))
        skipped = skipped_count(out)
        limit = spec.get("max_skipped", DEFAULT_MAX_SKIPPED.get(name))
        status = "pass" if rc == 0 else "fail"
        detail = f"exit {rc} in {int(time.time() - t0)}s"
        if status == "pass" and strict and limit is not None and skipped > limit:
            status, detail = "fail", f"{skipped} tests skipped (max {limit}): a skipped test proves nothing"
        return {**res, "status": status, "detail": detail, "skipped": skipped, "tail": out[-4000:]}
    finally:
        if started is not None:
            kill_group(started)
        if spec.get("stop"):
            sh(wrapped(spec["stop"], wrap), cwd=repo, env=senv, timeout=300)


def overall(results):
    states = [r["status"] for r in results]
    if "fail" in states:
        return "fail"
    if "missing" in states:
        return "not-verified"
    return "pass"


def execute(repo, cfg, stages, strict, paths, env, post=None, wrap=None, secrets=(), deadline=None, withheld=(),
            reuse=None):
    """Run `stages` in order; return (verdict, results, posted). `post(context, state, description)` reports
    each stage; `secrets` are masked in everything returned or printed. A stage in `reuse` takes that result
    instead of running (the runner's, for this exact commit)."""
    posted, results = True, []
    for name in stages:
        if name in (reuse or {}):
            r = reuse[name]
            results.append(r)
            print(f"[verify] {name:<11} {r['status']:<10} {r.get('detail', '')}", flush=True)
            if post:
                posted &= post(f"{STATUS_PREFIX}/{name}", r["status"], r.get("detail", ""))
            continue
        spec = cfg.get("stages", {}).get(name) or {"run": None, "todo": "stage not declared"}
        if post:
            posted &= post(f"{STATUS_PREFIX}/{name}", "pending", "running")
        left = int(deadline - time.time()) if deadline else None
        if left is not None and left <= 0:
            r = {"stage": name, "started": now(), "status": "fail", "detail": "job time limit reached before this stage"}
        else:
            if left is not None:
                spec = {**spec, "timeout": min(spec.get("timeout", 3600), left)}
            r = run_stage(repo, name, spec, strict, paths, env, wrap, withheld)
        r = {k: redact(v, secrets) if isinstance(v, str) else v for k, v in r.items()}
        results.append(r)
        print(f"[verify] {name:<11} {r['status']:<10} {r.get('detail', '')}", flush=True)
        if r["status"] == "fail" and r.get("tail"):
            print("\n".join("    " + line for line in r["tail"].splitlines()[-25:]), flush=True)
        if post:
            posted &= post(f"{STATUS_PREFIX}/{name}", r["status"], r.get("detail", ""))
    return overall(results), results, posted


def summary(verdict, results, note=""):
    return f"{verdict}{note}: " + ", ".join(f"{r['stage']}={r['status']}" for r in results)


def linked_artifact_path(repo, sha, leaf=True):
    """The first of .verify, .verify/runs and (with `leaf`) the artifact that is a symlink, or None. A linked parent,
    tracked or not, would send the artifact outside the repo; write_artifact replaces a linked leaf safely."""
    for rel in (RUNS.parent, RUNS, *([RUNS / f"{sha}.json"] if leaf else [])):
        if (repo / rel).is_symlink():
            return rel
    return None


def write_artifact(runs, name, art):
    """Write runs/name by atomic replace: a symlink planted at that path is replaced, never followed."""
    runs.mkdir(parents=True, exist_ok=True)
    tmp = runs / f".{name}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(art, indent=1))
    os.replace(tmp, runs / name)


def worktree_changes(repo):
    """`git status` lines for how the worktree differs from HEAD, or None when git can't tell. Plain status trusts
    the index: assume-unchanged and skip-worktree bits, a stale or lying fsmonitor, and a same-size edit under
    core.trustctime=false or core.checkStat=minimal all hide a change. A throwaway index read from HEAD has no
    bits and no stat data, so status hashes every tracked file."""
    with tempfile.TemporaryDirectory(prefix="verify-index-") as d:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(d) / "index")}
        base = ["git", "-C", str(repo), "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false"]
        rc, out = sh([*base, "read-tree", "HEAD"], env=env, timeout=60, merge=False)
        if rc == 0:
            rc, out = sh([*base, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"],
                         env=env, timeout=300, merge=False)
    return out.splitlines() if rc == 0 else None


def runner_result(repo, sha):
    """(artifact, why not): the runner's result for exactly this commit, when it can stand in for running here.
    Read from the runner's own files on this host, never from forge statuses, which anyone with push access can
    post. It must be for this tree as committed (the runner's merge with its base was a no-op, so `checked` is
    this SHA), sandboxed and strict, run with this tree's own verifier and config, and the worktree must be clean."""
    slug = forge_slug(repo)
    art = read_json(RUNNER_HOME / "runs" / slug.replace("/", "__") / f"{sha}.json") if slug else None
    if not art or art.get("sha") != sha:
        return None, "the runner has no result for this commit"
    if art.get("checked") != sha:
        return None, (f"the runner checked this commit merged with {art.get('base') or 'its base'}; "
                      "merge or rebase on it so the runner's result covers this tree")
    if art.get("sandboxed") is not True or art.get("strict") is not True:
        return None, "the runner's result is not from a sandboxed strict job"
    if art.get("edited") != [] or art.get("config_edited") is not False:  # absent or malformed: unknown
        return None, "this commit edits the verifier or config, which the runner replaced with its base's copy"
    link = linked_artifact_path(repo, sha)
    if link:
        return None, f"{link} is a symlink, so the artifact path leaves the repo"
    own = f"?? {(RUNS / f'{sha}.json').as_posix()}"  # this command's own artifact for HEAD, from an earlier run
    changes = worktree_changes(repo)
    if changes is None:
        return None, "git could not compare the worktree with HEAD"
    dirty = [e for e in changes if e != own]
    if dirty:
        return None, f"the worktree has uncommitted or untracked files ({dirty[0].strip()})"
    return art, ""


def cmd_run(args):
    repo = repo_root(args.repo)
    cfg = read_json(repo / CONFIG)
    if not cfg:
        sys.exit("[verify] no .verify/config.json; run: verify.py init --write")
    stages = args.stages.split(",") if args.stages else PER_CHANGE
    sha = git(repo, "rev-parse", "HEAD")
    paths = changed_paths(repo, args.base)
    env = {**os.environ, "VERIFY_STRICT": "1" if args.strict else "0", "VERIFY_SHA": sha}
    if args.strict:
        env.setdefault("CI", "1")
    slug = forge_slug(repo) if args.post_status else None
    if args.post_status and not slug:
        print("[verify] --post-status: no GitHub origin; results stay local", file=sys.stderr)
    post = (lambda context, state, desc: post_status(slug, sha, context, state, desc)) if slug else None
    reuse, runner = {}, None
    if args.strict and not args.fresh:
        runner, why = runner_result(repo, sha)
        if runner:
            mark = f"runner, {runner.get('at', '?')}, base {str(runner.get('base_sha'))[:9]}"
            reuse = {r["stage"]: {**r, "source": "runner", "detail": f"{r.get('detail', '')} ({mark})"}
                     for r in runner.get("stages", []) if r.get("stage") in stages and r.get("status") in ("pass", "fail", "na")}
            print(f"[verify] reusing the runner's sandboxed result for {sha[:9]}: {', '.join(reuse) or 'nothing'};"
                  " the rest runs here. --fresh runs everything here", flush=True)
        else:
            print(f"[verify] runner: {why}; running every stage here", flush=True)
    verdict, results, posted = execute(repo, cfg, stages, args.strict, paths, env, post, reuse=reuse)
    results = [r if r.get("source") else {**r, "source": "local"} for r in results]
    art = {"sha": sha, "at": now(), "strict": args.strict, "base": args.base, "verdict": verdict, "stages": results}
    if reuse:
        art["runner"] = {k: runner.get(k) for k in ("at", "base", "base_sha", "checked", "kind", "label")}
    link = linked_artifact_path(repo, sha, leaf=False)
    if link:
        print(f"[verify] not writing the artifact: {link} is a symlink and would send it outside the repo")
    else:
        write_artifact(repo / RUNS, f"{sha}.json", art)
    if post:
        posted &= post(STATUS_PREFIX, verdict, summary(verdict, results))
    label = {"pass": "PASS", "fail": "FAIL", "not-verified": "NOT VERIFIED"}[verdict]
    print(f"[verify] {label} for {sha[:9]} -> {RUNS / (sha + '.json')}")
    if verdict == "fail" and any(r["status"] == "fail" and r.get("source") == "runner" for r in results):
        print("[verify] a failed stage is the runner's result for this commit; --fresh reruns it here")
    if not posted:
        return 3
    return 0 if verdict == "pass" else 1


def cmd_status(args):
    repo = repo_root(args.repo)
    sha = args.sha or git(repo, "rev-parse", "HEAD")
    art = read_json(repo / RUNS / f"{sha}.json")
    slug = forge_slug(repo)
    st = forge_status(slug, sha) if slug else None
    print(json.dumps({"sha": sha, "local": art and {"verdict": art["verdict"], "at": art["at"]},
                      "forge": None if st is None else {k: v for k, v in st.items() if k.startswith(STATUS_PREFIX)}}, indent=1))
    return 0


# ---------------------------------------------------------------- serve (self-hosted runner)
#
# The runner owns its own mirror clone per repo under RUNNER_HOME and a throwaway clone per job.
# It never writes to, fetches into, or adds worktrees to anyone's checkout.
#
# A job runs code from a PR, so the PR is untrusted:
# - What runs comes from the base branch's .verify/config.json, read from the mirror before any PR code exists on disk.
#   The files its commands run (the config's `verifier` paths) come from the base branch too, written into the job's
#   checkout from the mirror, and the sandbox lets nothing in the job write, replace or rename them. A PR still
#   controls its own code, tests and manifests; weaken-check is the control for tests.
# - Every repo-controlled command runs in an OS sandbox (macOS sandbox-exec). It can't read /Users, /Volumes, /tmp,
#   /var/folders or RUNNER_HOME, except its own job dir and toolchains. It can only write its job dir. It can't reach
#   the keychain, the ssh-agent, the Docker socket, or any port that was listening on the host when the job started.
# - The environment is an allowlist plus owner env files, minus forge tokens. Network egress stays open (setup
#   and journeys need it), so a PR job gets no secrets: only `<slug>.pr.env`, values every PR author may read.
#   `<slug>.env` (secrets) reaches only owner-chosen branch jobs. Forks get neither.
# - Changed paths are computed before PR code runs; afterwards the runner runs no git in the job dir. It posts
#   statuses and writes the artifact itself, and masks env-file values in both.
# - With no supported sandbox, the runner refuses to run jobs unless started with --unsandboxed.
# Left open: host services that start after the port snapshot, and processes a job daemonizes.


def sbpl(p):
    return '"' + str(p).replace("\\", "\\\\").replace('"', '\\"') + '"'


def sandbox_profile(job, home, runner_home, allow_read=(), deny_ports=(), pinned=()):
    """macOS sandbox profile for one job. Later rules win, so each allow-back follows the deny it narrows.
    `pinned`: verifier paths in the job's checkout; nothing the job runs may write, replace or rename them or the
    directories above them, so setup or an earlier stage can't swap the helper a later stage runs."""
    home, job, runner_home = (Path(x).resolve() for x in (home, job, runner_home))
    reads = [home / d for d in TOOLCHAIN_DIRS if (home / d).exists()] + [Path(p).expanduser().resolve() for p in allow_read]
    rules = ["(version 1)", "(allow default)",
             "(deny file-read-data (subpath \"/Users\") (subpath \"/Volumes\") (subpath \"/private/tmp\")"
             f" (subpath \"/private/var/folders\") (subpath {sbpl(home)}) (subpath {sbpl(runner_home)}))"]
    if reads:
        rules.append("(allow file-read-data " + " ".join(f"(subpath {sbpl(p)})" for p in reads) + ")")
    rules += ["(deny file-read-data " + " ".join(f"(literal {sbpl(home / s)})" for s in TOOLCHAIN_SECRETS) + ")",
              f"(allow file-read-data (subpath {sbpl(job)}))",
              "(deny file-write* (subpath \"/\"))",
              f"(allow file-write* (subpath {sbpl(job)}) (subpath \"/dev\"))",
              "(deny mach-lookup (global-name \"com.apple.SecurityServer\") (global-name \"com.apple.securityd.xpc\"))",
              "(deny network-outbound (remote unix-socket (subpath \"/Users\")) (remote unix-socket (subpath \"/private/tmp\"))"
              " (remote unix-socket (subpath \"/private/var/folders\")) (remote unix-socket (subpath \"/private/var/run\")))",
              "(allow network-outbound (remote unix-socket (path-literal \"/private/var/run/mDNSResponder\"))"
              f" (remote unix-socket (subpath {sbpl(job)})))"]
    if deny_ports:
        rules.append("(deny network-outbound " + " ".join(f"(remote ip \"*:{p}\")" for p in sorted(deny_ports)) + ")")
    work = job / "repo"
    guarded = set()
    for rel in pinned:
        guarded.add(f"(subpath {sbpl(work / rel)})")
        for up in (work / rel).parents:
            guarded.add(f"(literal {sbpl(up)})")
            if up == work:
                break
    if guarded:
        rules.append("(deny file-write* " + " ".join(sorted(guarded)) + ")")
    return "\n".join(rules) + "\n"


def host_listen_ports():
    """TCP ports listening on this host right now (bb, browsers' debug ports, databases...); None if unknown."""
    rc, out = sh(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fn"], timeout=60, merge=False)
    if rc not in (0, 1):
        return None
    return {int(m.group(1)) for m in re.finditer(r"^n.*:(\d+)$", out, re.M)}


def sandbox_wrap(job, args, pinned=()):
    """argv prefix that sandboxes a job's commands, [] when --unsandboxed, None when no sandbox is available."""
    if args.unsandboxed:
        return []
    if sys.platform != "darwin" or not Path(SANDBOX_EXEC).exists():
        return None
    ports = host_listen_ports()
    if ports is None:
        return None
    ports -= set(args.allow_host_port or [])
    return [SANDBOX_EXEC, "-p", sandbox_profile(job, Path.home(), RUNNER_HOME, args.allow_read or [], ports, pinned)]


def job_env_file(slug, pr, fork):
    """(values, withheld names) for a job. PR code can send anything it sees over the network, so a PR
    job gets only `<slug>.pr.env`: values the owner accepts every PR author can read. Secrets in
    `<slug>.env` reach only owner-chosen branch jobs, which run merged code. Forks get neither."""
    base = RUNNER_HOME / "env" / slug.replace("/", "__")
    shared = load_env_file(base.with_name(base.name + ".pr.env"))
    secret = load_env_file(base.with_name(base.name + ".env"))
    if fork:
        return {}, set(shared) | set(secret)
    if pr:
        return shared, set(secret) - set(shared)
    return {**shared, **secret}, set()


def job_env(job, env_file, sha):
    env = {k: v for k, v in os.environ.items() if k in JOB_ENV_KEEP}
    if "PLAYWRIGHT_BROWSERS_PATH" not in env:
        for d in ("Library/Caches/ms-playwright", ".cache/ms-playwright"):
            if (Path.home() / d).is_dir():
                env["PLAYWRIGHT_BROWSERS_PATH"] = str(Path.home() / d)
                break
    home = job / "home"
    env.update({k: v for k, v in env_file.items() if k not in FORGE_TOKENS})
    env.update({"HOME": str(home), "TMPDIR": str(job / "tmp"), "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_CACHE_HOME": str(home / ".cache"), "XDG_DATA_HOME": str(home / ".local/share"),
                "CI": "1", "VERIFY_STRICT": "1", "VERIFY_SHA": sha})
    return env

def load_env_file(path):
    env = {}
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                if k.startswith("export "):
                    k = k[len("export "):].strip()
                env[k] = v.strip().strip("'\"")
    except OSError:
        pass
    return env


def resolve_target(spec):
    """--repo accepts OWNER/NAME or a local checkout path (read only: its origin URL is all we use)."""
    p = Path(spec).expanduser()
    if p.exists():
        url = git(p, "remote", "get-url", "origin")
        return slug_of(url), url
    if re.fullmatch(r"[\w.-]+/[\w.-]+", spec):
        return spec, f"https://github.com/{spec}.git"
    return None, None


def ensure_mirror(slug, url):
    m = RUNNER_HOME / "mirrors" / (slug.replace("/", "__") + ".git")
    if not m.exists():
        m.parent.mkdir(parents=True, exist_ok=True)
        rc, out = sh(["git", "clone", "--mirror", "--quiet", url, str(m)], timeout=3600)
        if rc != 0:
            raise RuntimeError(f"mirror clone failed: {out.strip()[-300:]}")
    else:
        rc, out = sh(["git", "-C", str(m), "fetch", "--quiet", "--prune", "origin"], timeout=1800)
        if rc != 0:
            raise RuntimeError(f"mirror fetch failed: {out.strip()[-300:]}")
    return m


def pending_jobs(slug, mirror, args):
    selected = getattr(args, "pr", None)
    if selected is not None:
        if type(selected) is not int or selected < 1 or args.branch:
            raise RuntimeError("--pr needs a positive PR number and cannot be combined with --branch")
        command = ["gh", "pr", "view", str(selected), "-R", slug,
                   "--json", "number,state,headRefOid,baseRefName,isCrossRepository"]
    else:
        command = ["gh", "pr", "list", "-R", slug, "--state", "open", "--limit", "50",
                   "--json", "number,headRefOid,baseRefName,isCrossRepository"]
    rc, out = sh(command, timeout=60, merge=False)
    if rc != 0:
        raise RuntimeError(f"cannot read PRs for {slug} with the current gh auth: {out.strip()[-200:]}")
    prs = json.loads(out or "[]")
    if selected is not None:
        if not isinstance(prs, dict) or type(prs.get("number")) is not int or prs["number"] != selected \
                or prs.get("state") != "OPEN":
            raise RuntimeError(f"{slug} PR #{selected}: response does not identify that open PR; not running")
        prs = [prs]
    jobs = []
    for p in prs:
        if not isinstance(p, dict):
            continue
        label, head, base = f"PR #{p.get('number')}", p.get("headRefOid"), p.get("baseRefName")
        fork = p.get("isCrossRepository") is not False  # unknown counts as a fork
        if fork and not args.allow_forks:
            print(f"[serve] {slug} {label}: from a fork, skipped (--allow-forks to opt in; forks never get the env file)")
            continue
        if not (isinstance(head, str) and re.fullmatch(r"[0-9a-f]{40}", head)) or not branch_head(mirror, base):
            print(f"[serve] {slug} {label}: head or base branch missing or unknown; not running", flush=True)
            continue
        jobs.append((head, base, label, fork, "pr"))
    for b in args.branch or []:
        sha = branch_head(mirror, b)
        if sha:
            jobs.append((sha, None, b, False, "branch"))
    return jobs


def branch_head(mirror, name):
    """The head SHA of branch `name` in the mirror, or "" for anything that is not a plain existing branch."""
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", name) or ".." in name \
            or name.startswith(("-", "/")) or name.endswith(("/", ".lock")):
        return ""
    return git(mirror, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}^{{commit}}")


def trusted_config(mirror, sha, base, ref=None, since=None):
    """(config, note): a PR runs its base branch's config (at commit `ref`), so it can't change what is checked. A
    branch job (an owner-chosen branch, no base) runs its own. The note names an edit the PR made since `since`,
    where it left the base branch, so a later change on the base is not blamed on the PR."""
    ref = ref or (f"refs/heads/{base}" if base else sha)
    try:
        cfg = json.loads(git(mirror, "show", f"{ref}:{CONFIG}") or "null")
    except ValueError:
        cfg = None
    if not base or not cfg:
        return cfg, ""
    try:
        mine = json.loads(git(mirror, "show", f"{sha}:{CONFIG}") or "null")
    except ValueError:
        mine = "unreadable"
    try:
        then = json.loads(git(mirror, "show", f"{since}:{CONFIG}") or "null") if since else cfg
    except ValueError:
        then = "unreadable"
    return cfg, ("" if mine == then else f" (ran {base}'s config, not this PR's edit)")


def verifier_paths(cfg):
    """The config's `verifier`: repo-relative files or directories its stage commands run (helper scripts, suite
    lists, policy). A PR job runs the base branch's copy of each, so a PR can't change how it is checked; a change to
    the verifier is checked once it is on the base branch. Raises ValueError for anything but plain relative paths."""
    raw = cfg.get("verifier") or []
    if not isinstance(raw, list):
        raise ValueError("verifier must be a list of repo-relative paths")
    paths = []
    for p in raw:
        parts = p.rstrip("/").split("/") if isinstance(p, str) else []
        if not parts or p.startswith("/") or "\\" in p or parts[0] == ".git" \
                or any(x in ("", ".", "..") for x in parts):
            raise ValueError(f"verifier path {p!r} is not a plain repo-relative path")
        paths.append("/".join(parts))
    return paths


def pin_verifier(mirror, ref, sha, work, paths, since=None):
    """Replace each verifier path in the PR checkout `work` with its copy at `ref`, read from the mirror (no git runs
    in the job dir). A directory is replaced whole, so the PR can add nothing under it. Runs before any PR code, and
    never follows a link the PR planted: a path whose directory is a symlink in the PR is refused.
    Returns (error, paths the PR edited since `since`, where it left the base branch)."""
    work = Path(work).resolve()
    edited = []
    for rel in paths:
        listing = subprocess.run(["git", "-C", str(mirror), "ls-tree", "-r", "-z", "--full-tree", ref, "--", rel],
                                 capture_output=True, timeout=120)
        entries = []
        for item in listing.stdout.decode("utf-8", "surrogateescape").split("\0"):
            if "\t" in item:
                meta, path = item.split("\t", 1)
                mode, kind, obj = meta.split()
                if path == rel or path.startswith(rel + "/"):
                    entries.append((mode, kind, obj, path))
        if listing.returncode or not entries:
            return f"verifier path {rel} is not on the base branch", edited
        for mode, kind, _, path in entries:
            if kind != "blob" or mode not in ("100644", "100755"):
                return f"verifier path {path} is not a regular file on the base branch", edited
        cur = work
        for part in rel.split("/")[:-1]:
            cur = cur / part
            if cur.is_symlink() or (cur.exists() and not cur.is_dir()):
                return f"{cur.relative_to(work)} is not a plain directory in this PR; the verifier can't be pinned", edited
        target = work / rel
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        for mode, _, obj, path in entries:
            dest = work / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            if os.path.commonpath([work, dest.parent.resolve()]) != str(work):
                return f"verifier path {path} resolves outside the checkout", edited
            data = subprocess.run(["git", "-C", str(mirror), "cat-file", "blob", obj], capture_output=True,
                                  check=True, timeout=120).stdout
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o755 if mode == "100755" else 0o644)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        if git(mirror, "rev-parse", "--verify", "--quiet", f"{sha}:{rel}") != \
                git(mirror, "rev-parse", "--verify", "--quiet", f"{since or ref}:{rel}"):
            edited.append(rel)
    return "", edited


GIT_NO_HOST_CONFIG = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def job_git_env(job):
    """Env for git in a PR job dir: no host global, system or XDG git config, so a PR's .gitattributes can't select
    a merge driver or filter the host defines (git-lfs included), and no host hook, signing or credential helper
    applies. GIT_* from the host is dropped too."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_NO_HOST_CONFIG, HOME=str(job / "home"), XDG_CONFIG_HOME=str(job / "home" / ".config"),
               GIT_TERMINAL_PROMPT="0")
    return env


def run_job(slug, mirror, sha, base, label, args, post=None, fork=False, kind="pr", budget=None):
    """Run one job. Every job is a PR job (no secrets, base branch's config) unless it is a `branch` job
    whose SHA is, right now, the head of the owner-listed branch named by `label`. Its posts draw on `budget`,
    the serve tick's, or a fresh one."""
    budget = budget or ForgeBudget()
    post = post or (lambda context, state, desc: budget.call(post_status, slug, sha, context, state, desc))
    jobs = RUNNER_HOME / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    if free_gb(jobs) < DISK_FLOOR_GB:
        print(f"[serve] disk below {DISK_FLOOR_GB} GB free; not starting {label}")
        return "skipped"
    trusted = kind == "branch" and base is None and not fork and bool(sha) and branch_head(mirror, label) == sha
    if kind == "branch" and not trusted:
        print(f"[serve] {slug} {label}: {sha[:9]} is not the head of an owner-listed branch; not running", flush=True)
        return "error"
    base_sha = None if trusted else branch_head(mirror, base)
    if not trusted and not base_sha:
        print(f"[serve] {slug} {label}: PR base branch {base!r} is missing or unknown; not running", flush=True)
        return "error"
    if not trusted:
        kind = "pr"
    # A PR is checked merged into this base commit, the one its verifier is pinned from, so a branch that predates
    # a base change (a new suite and its registry entry) is not failed by the skew. Edits count from the fork point.
    since = (git(mirror, "merge-base", sha, base_sha) or None) if base_sha else None
    cfg, note = trusted_config(mirror, sha, None if trusted else base, base_sha, since)
    config_edited = bool(note)
    if not cfg:
        post(STATUS_PREFIX, "missing", f"no .verify/config.json on {base} yet; merge one there first" if base
             else "no .verify/config.json in this commit")
        return "done"
    try:
        pinned = [] if trusted else verifier_paths(cfg)
    except ValueError as e:
        return "done" if post(STATUS_PREFIX, "fail", f"{base}'s config: {e}") else "error"
    job = Path(tempfile.mkdtemp(prefix=f"{slug.split('/')[-1]}-{sha[:9]}-", dir=jobs)).resolve()
    work = job / "repo"
    try:
        wrap = sandbox_wrap(job, args, pinned)
        if wrap is None:
            print(f"[serve] {slug} {label}: no OS sandbox here (macOS sandbox-exec, plus lsof for the port snapshot);"
                  " not running PR code. Use a disposable machine with --unsandboxed to accept host access.", flush=True)
            return "error"
        unsandboxed_pr = not trusted and not wrap
        if unsandboxed_pr:
            post = capped_post(post)
        (job / "home").mkdir()
        (job / "tmp").mkdir()
        genv = None if trusted else job_git_env(job)
        rc, _ = sh(["git", "clone", "--quiet", "--no-local", "--no-checkout", str(mirror), str(work)], env=genv,
                   timeout=900)
        rc = rc or sh(["git", "-C", str(work), "checkout", "--quiet", "--detach", sha], env=genv, timeout=900)[0]
        if rc != 0:
            print(f"[serve] {slug} {label}: cannot check out {sha[:9]}")
            return "error"
        if base_sha:  # genv: no host git config, so no host hook, signing, merge driver or filter runs here
            rc, out = sh(["git", "-C", str(work), "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                          "-c", "user.name=verify runner", "-c", "user.email=verify-runner@localhost",
                          "merge", "--quiet", "--no-ff", "--no-edit", base_sha], env=genv, timeout=900)
            if rc != 0:
                print(f"[serve] {slug} {label}: {sha[:9]} does not merge into {base} at {base_sha[:9]}:\n{out[-2000:]}",
                      flush=True)
                return "done" if post(STATUS_PREFIX, "missing", f"not checked: conflicts with {base} at {base_sha[:9]};"
                                      f" merge or rebase on {base}") else "error"
        checked = git(work, "rev-parse", "HEAD", env=genv)
        # Last git call in the job dir: after PR code runs, its hooks and config could run unsandboxed.
        paths = None if trusted else changed_paths(work, base_sha, genv)
        try:
            problem, edited = pin_verifier(mirror, base_sha, sha, work, pinned, since) if pinned else ("", [])
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            problem, edited = f"cannot pin {base}'s verifier: {e}", []
        if problem:
            print(f"[serve] {slug} {label}: {problem}; not running", flush=True)
            return "done" if post(STATUS_PREFIX, "fail", problem) else "error"
        if edited:
            note += f" (ran {base}'s verifier, not this PR's edit of {', '.join(edited)})"
        env_file, withheld = job_env_file(slug, pr=not trusted, fork=fork)
        dropped = sorted(k for k in env_file if k in FORGE_TOKENS)
        if dropped:
            print(f"[serve] {slug}: env file sets {', '.join(dropped)}; forge tokens never reach jobs", flush=True)
        secrets = sorted({v for v in env_file.values() if len(v) >= 4}, key=len, reverse=True)
        env = job_env(job, env_file, sha)
        if not trusted:  # git in a stage starts with no host config either (the sandbox, not this, contains PR code)
            env.update(GIT_NO_HOST_CONFIG)
        deadline = time.time() + cfg.get("timeout", 7200)
        if cfg.get("setup"):
            post(STATUS_PREFIX, "pending", "setup")
            rc, out = sh(wrapped(cfg["setup"], wrap), cwd=work, env=stage_env(env),
                         timeout=cfg.get("setup_timeout", 1800))
            if rc != 0:
                print(f"[serve] {slug} {label} setup failed (exit {rc}):\n{redact(out[-3000:], secrets)}", flush=True)
                return "done" if post(STATUS_PREFIX, "fail", f"setup failed (exit {rc}); output is in the runner log") else "error"
        print(f"[serve] {slug} {label} {sha[:9]} running" + (f", merged into {base} at {base_sha[:9]}" if base_sha else ""),
              flush=True)
        stages = list(PER_CHANGE)
        if trusted and (cfg.get("stages", {}).get("mutation") or {}).get("run"):
            stages.append("mutation")
        verdict, results, posted = execute(work, cfg, stages, True, paths, env, post, wrap, secrets, deadline,
                                           withheld - set(FORGE_TOKENS))
        if unsandboxed_pr and GH_STATE.get(verdict) == "success":
            verdict, note = "missing", note + f" ({UNSANDBOXED_PR})"  # the artifact records what the status says
        dest = RUNNER_HOME / "runs" / slug.replace("/", "__")
        dest.mkdir(parents=True, exist_ok=True)
        art = {"sha": sha, "at": now(), "strict": True, "kind": kind, "label": label, "base": base, "fork": fork,
               "sandboxed": bool(wrap), "checked": checked, "base_sha": base_sha, "edited": edited,
               "config_edited": config_edited, "verdict": verdict, "stages": results}
        (dest / f"{sha}.json").write_text(json.dumps(art, indent=1))
        posted &= post(STATUS_PREFIX, verdict, summary(verdict, results, note))
        return "done" if posted else "error"
    finally:
        shutil.rmtree(job, ignore_errors=True)


def serve_repo(spec, args, budget=None):
    slug, url = resolve_target(spec)
    if not slug:
        print(f"[serve] {spec}: not a GitHub repo path or OWNER/NAME")
        return 1
    RUNNER_HOME.mkdir(parents=True, exist_ok=True)
    lock = open(RUNNER_HOME / f"{slug.replace('/', '__')}.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"[serve] {slug}: another runner holds the lock")
        lock.close()
        return 0
    try:
        mirror = ensure_mirror(slug, url)
        errors = done = 0
        budget = budget or ForgeBudget()
        for sha, base, label, fork, kind in pending_jobs(slug, mirror, args):
            if done >= args.max_jobs:
                break
            st = budget.call(forge_status, slug, sha)
            if st is None:
                print(f"[serve] {slug} {label}: cannot read statuses (auth or network); not running", flush=True)
                errors += 1
                continue
            mine = st.get(STATUS_PREFIX)
            stale = bool(mine) and mine.get("state") == "pending" and age_hours(mine.get("at")) > args.stale_hours
            if mine and not stale and sha not in (args.rerun or []):
                continue
            outcome = run_job(slug, mirror, sha, base, label, args, fork=fork, kind=kind, budget=budget)
            errors += outcome == "error"
            done += outcome == "done"
        return 1 if errors else 0
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def cmd_serve(args):
    while True:
        rc = 0
        budget = ForgeBudget()  # one per tick, shared by every repo's reads and every job's posts
        for r in args.repo:
            try:
                rc |= serve_repo(r, args, budget)
            except Exception as e:  # one broken repo must not stop the others
                print(f"[serve] {r}: {e}", flush=True)
                rc = 1
        if args.once:
            return rc
        time.sleep(args.interval)


# ---------------------------------------------------------------- weaken-check

ADDED_SKIP = re.compile(r"\b(describe|it|test)\.(skip|only|todo|fixme)\b|\bx(it|describe)\(|\bskip:\s*(true|!)|\.skipIf\(|"
                        r"pytest\.mark\.(skip|xfail)|@unittest\.skip|\[(Fact|Theory)\(Skip\s*=|t\.Skip\(|test\.fixme\(")
ASSERT = re.compile(r"\b(expect\(|assert[A-Z_.(]|assert\s|Assert\.|should\.|\.toBe|\.toEqual|\.toMatch|require\.)")
EXPECTED = re.compile(r"\.(toBe|toEqual|toStrictEqual|toMatch|toHaveLength|toContain|toHaveBeenCalledTimes)\(|"
                      r"assert(Equal|\.equal|\.strictEqual|\.deepEqual|\.deepStrictEqual)|Assert\.(Equal|AreEqual)")
DIFF_HDR = re.compile(r"^diff --git a/(.+?) b/(.+)$")


def weaken_findings(diff_text):
    """Findings for a unified diff: added skips, deleted test files, net-removed assertions, changed expectations."""
    findings, cur, in_hunk = [], None, False
    removed_assert, added_assert, minus, deleted = {}, {}, {}, set()
    for line in diff_text.splitlines():
        m = DIFF_HDR.match(line)
        if m:
            cur, in_hunk = m.group(2), False
            continue
        if cur is None or not TEST_PATH_RE.search(cur):
            continue
        if not in_hunk:
            if line.startswith("deleted file mode"):
                deleted.add(cur)
                findings.append(f"{cur}: deletes a test file")
            if line.startswith("@@"):
                in_hunk = True
            continue
        if line.startswith("@@"):
            continue
        body = line[1:]
        if line.startswith("+"):
            if ADDED_SKIP.search(body):
                findings.append(f"{cur}: adds a skip/only/todo: {body.strip()[:120]}")
            if ASSERT.search(body):
                added_assert[cur] = added_assert.get(cur, 0) + 1
            if EXPECTED.search(body):
                key = EXPECTED.split(body)[0].strip()
                old = minus.get(cur, {}).get(key)
                if old is not None and old != body.strip():
                    findings.append(f"{cur}: changes an expected value: '{old[:80]}' -> '{body.strip()[:80]}'")
        elif line.startswith("-"):
            if ASSERT.search(body):
                removed_assert[cur] = removed_assert.get(cur, 0) + 1
            if EXPECTED.search(body):
                minus.setdefault(cur, {})[EXPECTED.split(body)[0].strip()] = body.strip()
    for f, n in removed_assert.items():
        net = n - added_assert.get(f, 0)
        if net > 0 and f not in deleted:
            findings.append(f"{f}: removes {net} more assertions than it adds")
    return findings


def cmd_weaken(args):
    repo = repo_root(args.repo)
    mb = git(repo, "merge-base", args.base, "HEAD") or args.base
    diff = git(repo, "diff", "--unified=0", f"{mb}...HEAD", timeout=120)
    findings = weaken_findings(diff)
    log = git(repo, "log", "--format=%B", f"{mb}..HEAD")
    m = re.search(r"^test-change-reason:\s*(.+)$", log, re.M | re.I)
    reason = os.environ.get("VERIFY_TEST_CHANGE_REASON") or (m.group(1).strip() if m else "")
    for x in findings:
        print(f"[weaken-check] {x}")
    if findings and not reason:
        print("[weaken-check] FAIL: tests were weakened. Fix the code instead, or state why the test itself was wrong "
              "in a commit line 'test-change-reason: <why>' (or VERIFY_TEST_CHANGE_REASON).")
        return 1
    print(f"[weaken-check] allowed with stated reason: {reason}" if findings
          else "[weaken-check] PASS: no skipped, deleted or loosened tests")
    return 0


def cmd_mutation_targets(args):
    repo = repo_root(args.repo)
    paths = changed_paths(repo, args.base) or []
    print("\n".join(p for p in paths if SRC_EXT.search(p) and not TEST_PATH_RE.search(p) and (repo / p).exists()))
    return 0


# ---------------------------------------------------------------- eval-score (non-deterministic output)

def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _correct(expected, output):
    if isinstance(expected, dict):
        if "any_of" in expected:
            return output in expected["any_of"]
        if "contains" in expected:
            return all(str(x).lower() in str(output).lower() for x in expected["contains"])
        if "not_contains" in expected:
            return not any(str(x).lower() in str(output).lower() for x in expected["not_contains"])
    return output == expected


def eval_score(dataset, predictions, thresholds=None):
    """Score repeated predictions against a labelled dataset.

    dataset rows: {id, expected, [human]}; prediction rows: {id, output, [judge]}. `expected` is an exact
    label or {"any_of": [...]}, {"contains": [...]}, {"not_contains": [...]}. Each id may have k samples.
    pass_at_1 = mean per-sample accuracy. pass_all_k = share of cases where every sample is correct:
    the consistency a user sees day to day. Per-label precision/recall for label outputs.
    `judge` (bool, from an LLM judge) vs `human` (bool label) gives the judge's TPR/TNR, so a judge is
    trusted only after it agrees with people.
    """
    th = thresholds or {}
    exp = {str(r["id"]): r for r in dataset}
    by_id = {}
    for p in predictions:
        by_id.setdefault(str(p["id"]), []).append(p)
    per_label, samples, all_ok, missing = {}, [], [], []
    for cid, row in exp.items():
        preds = by_id.get(cid, [])
        if not preds:
            missing.append(cid)
            continue
        oks = [_correct(row["expected"], p.get("output")) for p in preds]
        samples.extend(oks)
        all_ok.append(all(oks))
        if isinstance(row["expected"], str):
            st = per_label.setdefault(row["expected"], {"tp": 0, "fn": 0, "fp": 0})
            st["tp"] += sum(oks)
            st["fn"] += len(oks) - sum(oks)
            for p, good in zip(preds, oks):
                if not good and isinstance(p.get("output"), str):
                    per_label.setdefault(p["output"], {"tp": 0, "fn": 0, "fp": 0})["fp"] += 1
    labels = {}
    for lab, st in per_label.items():
        labels[lab] = {"precision": st["tp"] / (st["tp"] + st["fp"]) if st["tp"] + st["fp"] else None,
                       "recall": st["tp"] / (st["tp"] + st["fn"]) if st["tp"] + st["fn"] else None,
                       "n": st["tp"] + st["fn"]}
    pairs = [(bool(p["judge"]), bool(exp[str(p["id"])]["human"])) for p in predictions
             if "judge" in p and str(p["id"]) in exp and "human" in exp[str(p["id"])]]
    judge = None
    if pairs:
        tp = sum(j and h for j, h in pairs)
        fn = sum(not j and h for j, h in pairs)
        tn = sum(not j and not h for j, h in pairs)
        fp = sum(j and not h for j, h in pairs)
        judge = {"n": len(pairs), "tpr": tp / (tp + fn) if tp + fn else None, "tnr": tn / (tn + fp) if tn + fp else None}
    res = {"cases": len(exp), "missing_predictions": missing,
           "pass_at_1": sum(samples) / len(samples) if samples else 0.0,
           "pass_all_k": sum(all_ok) / len(all_ok) if all_ok else 0.0,
           "labels": labels, "judge": judge}
    fails = []
    if missing:
        fails.append(f"{len(missing)} cases have no prediction")
    for key in ("pass_at_1", "pass_all_k"):
        if key in th and res[key] < th[key]:
            fails.append(f"{key} {res[key]:.3f} < {th[key]}")
    for lab, lt in (th.get("labels") or {}).items():
        got = labels.get(lab)
        for metric in ("precision", "recall"):
            val = None if got is None else got[metric]
            if metric in lt and (val is None or val < lt[metric]):
                fails.append(f"{lab} {metric} {val} < {lt[metric]}")
    if judge and "judge_min" in th:
        for metric in ("tpr", "tnr"):
            if judge[metric] is not None and judge[metric] < th["judge_min"]:
                fails.append(f"judge {metric} {judge[metric]:.2f} < {th['judge_min']}: the judge is not trustworthy yet")
    res["failures"] = fails
    return res


def cmd_eval_score(args):
    th = read_json(args.thresholds, {}) if args.thresholds else {}
    res = eval_score(load_jsonl(args.dataset), load_jsonl(args.predictions), th)
    print(json.dumps(res, indent=1))
    return 1 if res["failures"] else 0


# ---------------------------------------------------------------- housekeep

PROTECTED_BRANCHES = {"main", "master", "develop", "dev", "staging", "release", "production"}


def housekeep(repo):
    repo = Path(repo)
    items = []
    default = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") or "origin/main"
    current = git(repo, "branch", "--show-current")
    for b in git(repo, "branch", "--merged", default, "--format=%(refname:short)").splitlines():
        b = b.strip()
        if b and b not in PROTECTED_BRANCHES and b != current:
            items.append({"kind": "merged-branch", "target": b, "safe_apply": True, "why": f"fully merged into {default}"})
    for block in git(repo, "worktree", "list", "--porcelain").split("\n\n"):
        fields = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        path = fields.get("worktree")
        if not path or Path(path).resolve() == repo.resolve():
            continue
        if not Path(path).exists():
            items.append({"kind": "stale-worktree", "target": path, "safe_apply": True, "why": "directory is gone (git worktree prune)"})
        else:
            dirty = git(Path(path), "status", "--porcelain")
            items.append({"kind": "worktree", "target": path, "safe_apply": False,
                          "why": "uncommitted changes: keep" if dirty else "clean: its owner decides"})
    for line in git(repo, "ls-tree", "-r", "-l", "HEAD", timeout=120).splitlines():
        meta, _, f = line.partition("\t")
        size = meta.split()[-1]
        size = int(size) if size.isdigit() else 0
        if size > 5_000_000:
            items.append({"kind": "large-tracked-file", "target": f, "safe_apply": False, "why": f"{size / 1e6:.1f} MB in git"})
        if re.search(r"(\.tsbuildinfo|\.eslintcache|\.cspellcache|\.DS_Store|\.log)$", f):
            items.append({"kind": "tracked-cache", "target": f, "safe_apply": False, "why": "generated file tracked in git: untrack and gitignore it"})
    for u in git(repo, "ls-files", "--others", "--exclude-standard", "--directory").splitlines():
        if re.search(r"(^|/)(evidence|tmp|scratch|handoff|\.local-evidence)", u, re.I) or re.search(r"\d{4}-\d{2}-\d{2}.*\.md$", u):
            items.append({"kind": "untracked-scratch", "target": u, "safe_apply": False, "why": "agent scratch/report in the repo: move it out or delete it"})
    return items


def cmd_housekeep(args):
    repo = repo_root(args.repo)
    items = housekeep(repo)
    for it in items:
        print(f"[housekeep] {it['kind']:<19} {it['target']}  ({it['why']}){'' if it['safe_apply'] else '  [manual]'}")
    if not args.apply:
        print(f"[housekeep] {len(items)} items; dry run. --apply only deletes merged branches (git branch -d) "
              "and prunes records of worktrees whose directory is gone.")
        return 0
    for it in items:
        if it["kind"] == "merged-branch":
            sh(["git", "-C", str(repo), "branch", "-d", it["target"]])  # -d refuses unmerged and checked-out branches
    if any(it["kind"] == "stale-worktree" for it in items):
        sh(["git", "-C", str(repo), "worktree", "prune"])
    print("[housekeep] applied the safe items; [manual] items need their owner")
    return 0


# ---------------------------------------------------------------- hook (PostToolUse for Claude Code and Codex; advisory)

SHIP_RE = re.compile(r"\bgh\s+pr\s+merge\b|\bvercel\b[^;&|]*(--prod\b|--target[= ]production|\bpromote\b)|"
                     r"\bgit\b[^;&|]*\bpush\b[^;&|]*\b(main|master|develop|release|production)\b")


def cmd_hook(_args):
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    tool_input = payload.get("tool_input") or {}
    cmd = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(cmd, list):
        cmd = " ".join(map(str, cmd))
    if not cmd or not SHIP_RE.search(cmd):
        return 0
    root = git(payload.get("cwd") or os.getcwd(), "rev-parse", "--show-toplevel")
    # Only repos that adopted verify get a note; elsewhere the hook stays silent (doctor covers them),
    # so it never adds a report-and-stop prompt to sessions in repos that have no definition of done.
    if not root or not (Path(root) / CONFIG).exists():
        return 0
    slug = forge_slug(root)
    sha = None
    m = re.search(r"gh\s+pr\s+merge\s+(\d+)", cmd)
    if m and slug:
        rc, out = sh(["gh", "pr", "view", m.group(1), "-R", slug, "--json", "headRefOid", "--jq", ".headRefOid"], timeout=8, merge=False)
        sha = out.strip() if rc == 0 and out.strip() else None
    sha = sha or git(root, "rev-parse", "HEAD")
    st = forge_status(slug, sha, timeout=8) if slug else None
    local = read_json(Path(root) / RUNS / f"{sha}.json") or {}
    verdict = ((st or {}).get(STATUS_PREFIX) or {}).get("state") or local.get("verdict") or "none"
    if verdict in ("success", "pass"):
        note = f"[verify] {sha[:9]} verify result: pass."
    else:
        note = (f"[verify] {sha[:9]} verify result: {verdict}. This never blocks merges or deploys. Run "
                f"`python3 {Path(__file__).resolve()} run {root} --strict` now, fix what fails, and report the "
                "result per stage; a stage you could not run is NOT VERIFIED, with the reason.")
    if re.search(r"\bvercel\b|\bdeploy\b", cmd):
        note += " After a deploy, also run the postdeploy stage: `verify.py run . --stages postdeploy --strict`."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note}}))
    return 0


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(prog="verify.py", description="One definition of done for any repo.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("doctor")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("--ref", default="HEAD", help="audit this commit/branch (works in bare repos)")
    p.add_argument("--online", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("init")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("run")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("--stages")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--base")
    p.add_argument("--post-status", action="store_true")
    p.add_argument("--fresh", action="store_true",
                   help="run every stage here, even ones the runner already checked for this exact commit")
    p = sub.add_parser("status")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("--sha")
    p = sub.add_parser("serve")
    p.add_argument("--repo", action="append", required=True, help="OWNER/NAME or a checkout path (read only)")
    targets = p.add_mutually_exclusive_group()
    targets.add_argument("--branch", action="append", help="also verify this branch head (e.g. develop)")
    targets.add_argument("--pr", type=int, help="only verify this open PR; refuses a mismatched response")
    p.add_argument("--once", action="store_true")
    p.add_argument("--interval", type=int, default=300)
    p.add_argument("--max-jobs", type=int, default=2)
    p.add_argument("--stale-hours", type=float, default=3.0)
    p.add_argument("--rerun", action="append", help="SHA to run again even if it has a result")
    p.add_argument("--allow-forks", action="store_true")
    p.add_argument("--allow-read", action="append", help="extra path jobs may read (a shared toolchain or browser cache)")
    p.add_argument("--allow-host-port", action="append", type=int,
                   help="host port jobs may reach (a test database the owner runs); all others listening are denied")
    p.add_argument("--unsandboxed", action="store_true",
                   help="no OS sandbox: PR code gets host access, so the runner never posts a pass for a PR job (the code itself could still post one with the host's credentials). Only on a disposable machine")
    for name in ("weaken-check", "mutation-targets"):
        p = sub.add_parser(name)
        p.add_argument("repo", nargs="?", default=".")
        p.add_argument("--base", default="origin/HEAD")
    p = sub.add_parser("eval-score")
    p.add_argument("--dataset", required=True)
    p.add_argument("--predictions", required=True)
    p.add_argument("--thresholds")
    p = sub.add_parser("housekeep")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("--apply", action="store_true")
    sub.add_parser("hook")
    args = ap.parse_args(argv)
    if args.cmd == "doctor":
        rep = doctor(repo_root(args.repo, allow_bare=True), args.online, args.ref)
        rep["detected"].pop("config", None)
        if args.json:
            print(json.dumps(rep, indent=1))
        else:
            d = rep["detected"]
            print(f"[doctor] {d['repo']}@{d['ref']}: stacks={','.join(d['stacks']) or '?'} tests={d['tests']} "
                  f"ui={d['has_ui']} service={d['has_service']} llm={d['llm']} config={d['has_config']}")
            for x in rep["findings"]:
                print(f"  {x['severity']:<6} {x['area']:<11} {x['finding']}\n         fix: {x['fix']}")
            print(f"[doctor] {len(rep['findings'])} findings")
        return 1 if any(x["severity"] == "high" for x in rep["findings"]) else 0
    if args.cmd == "init":
        repo = repo_root(args.repo)
        text = json.dumps(proposal(detect(repo)), indent=2) + "\n"
        if not args.write:
            print(text)
            return 0
        if (repo / CONFIG).exists():
            sys.exit(f"[verify] {CONFIG} exists; edit it instead")
        (repo / CONFIG).parent.mkdir(parents=True, exist_ok=True)
        (repo / CONFIG).write_text(text)
        (repo / ".verify" / ".gitignore").write_text("runs/\n")
        print(f"[verify] wrote {CONFIG}; give every 'todo' stage a command or an 'na' reason")
        return 0
    return {"run": cmd_run, "status": cmd_status, "serve": cmd_serve, "weaken-check": cmd_weaken,
            "mutation-targets": cmd_mutation_targets, "eval-score": cmd_eval_score, "housekeep": cmd_housekeep,
            "hook": cmd_hook}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
