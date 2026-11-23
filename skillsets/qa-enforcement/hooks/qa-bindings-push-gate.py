#!/usr/bin/python3
"""PreToolUse stage (Claude Code + Codex via coordinator-hook-pretool.sh), added 2026-11-06.

Denies `git push` and `gh pr create` from a worktree of shoc-frontend-new or
shoc-backend when the commit being pushed (HEAD, or the refspec's source)
carries a bound QA scenario whose test is not there: a live, automated
scenario with binding.status "draft" or "ready" and a binding.file that is
missing from the commit, or that never names the scenario the way the runner
matches it (@QAS-... in a test name or xUnit DisplayName, qaCase("QAS-...") in
Playwright). It is the agent-side copy of the repos' pre-push check and of the
CI qa-gate's BOUND_TEST_MISSING, so `--no-verify` and worktrees whose git
hooks are not installed cannot skip it.

Self-contained: it reads the commit with git (4 calls), not the repo's own
script, so branches cut before that script existed are checked too.
  exit 0, no stdout = allow; exit 2 + JSON deny on stdout + reason on stderr = deny.
Fails OPEN, with a note on stderr, only when the repository or commit cannot
be read; the CI qa-gate still enforces the rule.
"""
import json
import os
import re
import shlex
import subprocess
import sys

CONFIG = "qa/qa.config.json"
SCENARIO_TAG = re.compile(r"@(QAS-[0-9A-HJKMNP-TV-Z]{6})\b")
QA_CASE_CALL = re.compile(r"""qaCase\(\s*["'](QAS-[0-9A-HJKMNP-TV-Z]{6})["']\s*\)""")
CONTROL = {";", "&&", "||", "|", "&", "(", ")", "\n", "|&", ";;"}
WRAPPERS = {"env", "command", "nohup", "time", "exec", "nice"}
PUSH_VALUE_OPTS = {"--repo", "-o", "--push-option", "--receive-pack", "--exec", "--signed"}
SHOWN = 12


class Unreadable(Exception):
    pass


class QaDataError(Exception):
    """A QA config or scenario file the check cannot use: deny, unlike a git failure."""


def qa_json(text, name):
    try:
        value = json.loads(text)
    except ValueError as error:
        raise QaDataError(f"{name} is not valid JSON ({error})")
    if not isinstance(value, dict):
        raise QaDataError(f"{name} must be a JSON object")
    if "scenarios" in value and not isinstance(value["scenarios"], list):
        raise QaDataError(f"{name} has a scenarios field that is not a list")
    for i, s in enumerate(value.get("scenarios") or []):
        if not isinstance(s, dict):
            raise QaDataError(f"{name} has scenario {i} that is not an object")
    return value


def git(cwd, args, data=None):
    r = subprocess.run(["git", *args], cwd=cwd, input=data, capture_output=True, timeout=8)
    if r.returncode != 0:
        raise Unreadable(f"git {' '.join(args[:3])} failed in {cwd}")
    return r.stdout


# --- what the command pushes, and from where -------------------------------

def tokens(command):
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
    lex.whitespace_split = True
    lex.commenters = "#"
    return list(lex)


def segments(command):
    seg = []
    for tok in tokens(command.replace("\\\n", " ").replace("\n", " ; ")):
        if tok in CONTROL:
            if seg:
                yield seg
            seg = []
        else:
            seg.append(tok)
    if seg:
        yield seg


def strip_prefix(seg):
    i = 0
    while i < len(seg) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[i]) or seg[i] in WRAPPERS):
        i += 1
    return seg[i:]


def resolve(base, d):
    return os.path.normpath(os.path.join(base, os.path.expanduser(d)))


def pushes(command, cwd, depth=0):
    """(directory, [source refs or None for HEAD]) for each push-shaped segment."""
    out = []
    here = cwd
    for raw in segments(command):
        seg = strip_prefix(raw)
        if not seg:
            continue
        head = os.path.basename(seg[0])
        if head in ("cd", "pushd") and len(seg) > 1 and not seg[1].startswith("-"):
            here = resolve(here, seg[1])
        elif head in ("sh", "bash", "zsh") and depth < 3:
            # -c alone or in a cluster (-lc, -ec); the script is the next word
            i = next((k for k, w in enumerate(seg[1:], 1) if re.match(r"^-[A-Za-z]*c[A-Za-z]*$", w)), 0)
            if i and i + 1 < len(seg):
                out += pushes(seg[i + 1], here, depth + 1)
        elif head == "eval" and depth < 3:
            out += pushes(" ".join(seg[1:]), here, depth + 1)
        elif head == "git":
            out += git_push(seg[1:], here)
        elif head == "gh" and seg[1:3] == ["pr", "create"]:
            out.append((here, [None]))
    return out


def git_push(args, here):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-C" and i + 1 < len(args):
            here = resolve(here, args[i + 1])
            i += 2
        elif args[i] in ("-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(args):
            i += 2
        else:
            i += 1
    if i >= len(args) or args[i] != "push":
        return []
    rest, positional, delete = args[i + 1:], [], False
    j = 0
    while j < len(rest):
        a = rest[j]
        if a in ("-d", "--delete"):
            delete = True
        elif a in PUSH_VALUE_OPTS and j + 1 < len(rest):
            j += 1
        elif not a.startswith("-"):
            positional.append(a)
        j += 1
    if delete:
        return []
    sources = []
    for spec in positional[1:]:
        src = spec.lstrip("+").split(":", 1)[0]
        if spec.lstrip("+").startswith(":"):
            continue  # ":branch" deletes
        sources.append(src or None)
    return [(here, sources or [None])]


# --- the check, on a commit --------------------------------------------------

def files_at(cwd, commit, files):
    wanted = [f for f in dict.fromkeys(files) if "\n" not in f]
    out = {}
    if not wanted:
        return out
    raw = git(cwd, ["cat-file", "--batch"], "".join(f"{commit}:{f}\n" for f in wanted).encode())
    at = 0
    for f in wanted:
        end = raw.index(b"\n", at)
        header = raw[at:end].decode().split(" ")
        at = end + 1
        if len(header) == 3 and header[1] == "blob":
            size = int(header[2])
            out[f] = raw[at:at + size].decode("utf-8", "replace")
            at += size + 1
        else:
            out[f] = None
            if len(header) == 3 and header[2].isdigit():
                at += int(header[2]) + 1
    return out


def needs_bound_test(s):
    b = s.get("binding") or {}
    if (s.get("lifecycle") or {}).get("retired") or b.get("runner") == "manual" or s.get("layer") == "manual":
        return False
    return b.get("status") in ("draft", "ready") and isinstance(b.get("file"), str) and b["file"].strip() != ""


def violations(cwd, commit):
    config = files_at(cwd, commit, [CONFIG]).get(CONFIG)
    if config is None:
        return 0, []  # no QA config on this commit: nothing to check
    config_data = qa_json(config, CONFIG)
    if not isinstance(config_data, dict):
        raise QaDataError(f"{CONFIG} must be a JSON object")
    if "artifacts" not in config_data:
        paths = config_data.get("paths")
        scenarios_path = paths.get("scenarios") if isinstance(paths, dict) else None
        if isinstance(scenarios_path, str) and scenarios_path.strip():
            return 0, []  # foreign QA framework opts in through its paths layout
        raise QaDataError(f"{CONFIG} has no artifacts.scenarios")
    folder = (config_data.get("artifacts") or {}).get("scenarios")
    if not isinstance(folder, str) or not folder.strip():
        raise QaDataError(f"{CONFIG} has no artifacts.scenarios")
    folder = folder.rstrip("/")
    names = [n for n in git(cwd, ["ls-tree", "--name-only", commit, f"{folder}/"]).decode().split("\n") if n.endswith(".json")]
    scenarios = [s for n, t in files_at(cwd, commit, names).items() if t is not None for s in qa_json(t, n).get("scenarios", [])]
    bound = [s for s in scenarios if isinstance(s, dict) and needs_bound_test(s)]
    texts = files_at(cwd, commit, [s["binding"]["file"].strip() for s in bound])
    ids = {f: (None if t is None else set(SCENARIO_TAG.findall(t)) | set(QA_CASE_CALL.findall(t))) for f, t in texts.items()}
    found = []
    for s in bound:
        f = s["binding"]["file"].strip()
        if ids.get(f) is None:
            found.append(f"{s['id']} ({s['binding']['status']}): {f} does not exist in the commit")
        elif s["id"] not in ids[f]:
            found.append(f"{s['id']} ({s['binding']['status']}): {f} never names @{s['id']}")
    return len(bound), found


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}))
    print(reason, file=sys.stderr)
    sys.exit(2)


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    # The same fields ship-gate.py reads for Claude Code and Codex payloads.
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    command = tool_input.get("command") or tool_input.get("cmd") or payload.get("command")
    if isinstance(command, list):  # an argv, e.g. ["bash", "-lc", "git push"]
        command = " ".join(shlex.quote(str(c)) for c in command)
    if not isinstance(command, str) or not re.search(r"\bpush\b|\bpr\s+create\b", command):
        return
    cwd = payload.get("cwd") or payload.get("working_directory") or tool_input.get("workdir") or os.getcwd()
    try:
        targets = pushes(command, cwd)
    except ValueError:  # unbalanced quotes: read it as one push from cwd if it looks like one
        targets = [(cwd, [None])] if re.search(r"\bgit\b.*\bpush\b|\bgh\s+pr\s+create\b", command) else []
    problems = []
    for here, sources in targets:
        try:
            common = git(here, ["rev-parse", "--path-format=absolute", "--git-common-dir"]).decode().strip()
        except (Unreadable, OSError, subprocess.SubprocessError):
            if os.path.isdir(here):
                continue  # not a git repository: not ours
            print(f"[qa-bindings] could not read {here}; allowing this push UNCHECKED; run node scripts/qa-check-bindings.mjs --commit HEAD before pushing.", file=sys.stderr)
            continue
        # The committed QA config is the opt-in boundary; keep this shared
        # hook portable instead of embedding private checkout paths.
        repo = os.path.basename(os.path.realpath(here)) or "repository"
        for src in sources:
            try:
                ref = src or "HEAD"
                commit = git(here, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]).decode().strip()
            except Unreadable:
                if src is None:
                    raise
                commit = git(here, ["rev-parse", "--verify", "HEAD^{commit}"]).decode().strip()
                ref = "HEAD"
            try:
                checked, found = violations(here, commit)
            except QaDataError as error:
                checked, found = None, [f"{error}; fix the file and commit it"]
            if found:
                problems.append((repo, ref, commit, checked, found))
    if not problems:
        return
    lines = []
    for repo, ref, commit, checked, found in problems:
        if checked is None:
            lines.append(f"{repo} {ref} ({commit[:10]}): its QA files cannot be checked:")
        else:
            lines.append(f"{repo} {ref} ({commit[:10]}): {len(found)} of {checked} bound QA scenario(s) have no test:")
        lines += [f"  - {v}" for v in found[:SHOWN]]
        if len(found) > SHOWN:
            lines.append(f"  ... and {len(found) - SHOWN} more (run: node scripts/qa-check-bindings.mjs --commit {commit[:10]})")
    deny(
        "[qa-bindings] Push denied: a bound QA scenario's test is missing (the CI qa-gate blocks this as BOUND_TEST_MISSING). "
        + " ".join(lines)
        + " Fix each one: add the test to that file with the id the runner matches (@QAS-... in the test name, "
        'qaCase("QAS-...") in Playwright, DisplayName = "@QAS-... ..." in xUnit) and commit it; or, until it is written, '
        'set binding.status to "awaiting-implementation", binding.file to null and binding.awaiting to the branch, PR or '
        "ticket that delivers it. --no-verify does not skip this check."
    )


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:  # the repository or commit could not be read
        print(f"[qa-bindings] could not check bound QA tests ({type(error).__name__}: {error}); allowing this push UNCHECKED; run node scripts/qa-check-bindings.mjs --commit HEAD before pushing.", file=sys.stderr)
        sys.exit(0)
