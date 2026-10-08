"""The shells the heredoc oracles measure (test-heredoc-words.py, test-ship-matrix.py), all required (Hermes 2026-10-07,
kit-never-block-pr-merge r12, r13): a missing one would let a green run skip that shell's reading, so each test exits 1
naming it. dash is required because it is /bin/sh on Debian and Ubuntu and reads $'...' differently from the others.
Each shell is identified as what actually runs: zsh, bash (and whether POSIX mode is on) or ksh from the shell's own
variables; otherwise (dash, busybox) the resolved binary's name, its package version where dpkg or rpm can tell, and
always a hash of the binary.
Usage: shell_oracle.py [shell...]   prints the identity of each (default: the four required shells)"""
import atexit
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

SHELLS = ("/bin/bash", "/bin/zsh", "/bin/sh", "/bin/dash")
PROBE = ('if [ -n "${ZSH_VERSION:-}" ]; then echo "zsh $ZSH_VERSION"; '
         'elif [ -n "${BASH_VERSION:-}" ]; then case ":${SHELLOPTS:-}:" in '
         '*:posix:*) echo "bash $BASH_VERSION, POSIX mode";; *) echo "bash $BASH_VERSION";; esac; '
         'elif [ -n "${KSH_VERSION:-}" ]; then echo "ksh $KSH_VERSION"; fi')


SHELL_STATE = ("ZSH_VERSION", "BASH_VERSION", "KSH_VERSION", "SHELLOPTS", "BASHOPTS", "BASH_ENV", "ENV",
               "POSIXLY_CORRECT", "IFS", "CDPATH")


EMPTY = tempfile.mkdtemp(prefix="shell-oracle-home-")  # HOME and ZDOTDIR for every probe and measured run
atexit.register(shutil.rmtree, EMPTY, True)


def shell_env():
    """The environment the oracles measure the shells in: this one, without variables that would change how a shell
    reads a script or which shell it claims to be (an inherited SHELLOPTS=posix switches bash to POSIX mode, BASH_ENV
    runs a file first), and with HOME and ZDOTDIR at an empty directory, so no user startup file runs: zsh sources
    ~/.zshenv even under -c, and one that sets RC_QUOTES reads 'a''b' as a'b (Hermes 2026-10-07 r15). The locale
    and the rest stay, as in the agents' own shells. /etc/zshenv, which zsh always reads, is outside this control."""
    env = {k: v for k, v in os.environ.items() if k not in SHELL_STATE}
    env.update(HOME=EMPTY, ZDOTDIR=EMPTY)
    return env


def package_version(real):
    """The distribution package owning the binary, where the host can say (dash reports no version itself)."""
    for query in (["dpkg-query", "-S", real], ["rpm", "-qf", real]):
        if shutil.which(query[0]):
            r = subprocess.run(query, capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                pkg = r.stdout.split(":")[0].strip() if query[0] == "dpkg-query" else r.stdout.strip()
                if query[0] == "dpkg-query":
                    v = subprocess.run(["dpkg-query", "-W", "-f=${Version}", pkg], capture_output=True, text=True,
                                       timeout=10).stdout.strip()
                    return f"package {pkg} {v}".strip()
                return f"package {pkg}"
    return "no package version available"


def identify(s):
    """The probe runs with an environment of its own, so the version variables it reads are the ones the shell sets
    itself: an inherited ZSH_VERSION, BASH_VERSION or KSH_VERSION would name the wrong shell, and an inherited
    SHELLOPTS would switch bash's options (Hermes 2026-10-07 r14). HOME and ZDOTDIR point at an empty directory, so
    no user startup file runs."""
    real = os.path.realpath(s)
    env = {"PATH": "/usr/bin:/bin", "HOME": EMPTY, "ZDOTDIR": EMPTY, "LC_ALL": "C"}
    r = subprocess.run([s, "-c", PROBE], capture_output=True, text=True, timeout=10, env=env, cwd=EMPTY)
    if r.returncode:
        sys.exit(f"BAD required shell {s} does not run: rc {r.returncode}")
    name = r.stdout.strip()
    if not name:
        name = f"{os.path.basename(real)} (reports no version itself, {package_version(real)})"
    with open(real, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()[:16]
    return f"{s}{' -> ' + real if real != s else ''} is {name}, sha256 {digest}"


def shell_versions(shells=SHELLS):
    missing = [s for s in shells if not os.access(s, os.X_OK)]
    if missing:
        sys.exit(f"BAD required shell missing: {', '.join(missing)}; the oracle needs all of {', '.join(shells)}")
    return "; ".join(identify(s) for s in shells)


if __name__ == "__main__":
    print(shell_versions(tuple(sys.argv[1:]) or SHELLS).replace("; ", "\n"))
