"""The shells the heredoc oracles measure (test-heredoc-words.py, test-ship-matrix.py), all required (Hermes 2026-10-07,
kit-never-block-pr-merge r12, r13): a missing one would let a green run skip that shell's reading, so each test exits 1
naming it. Each shell is identified as what actually runs: zsh, bash (and whether POSIX mode is on) or ksh from the
shell's own variables; otherwise (dash, busybox) the resolved binary's name, its package version where dpkg or rpm can
tell, and always a hash of the binary.
Usage: shell_oracle.py [shell...]   prints the identity of each (default: the three required shells)"""
import hashlib
import os
import shutil
import subprocess
import sys

SHELLS = ("/bin/bash", "/bin/zsh", "/bin/sh")
PROBE = ('if [ -n "${ZSH_VERSION:-}" ]; then echo "zsh $ZSH_VERSION"; '
         'elif [ -n "${BASH_VERSION:-}" ]; then case ":${SHELLOPTS:-}:" in '
         '*:posix:*) echo "bash $BASH_VERSION, POSIX mode";; *) echo "bash $BASH_VERSION";; esac; '
         'elif [ -n "${KSH_VERSION:-}" ]; then echo "ksh $KSH_VERSION"; fi')


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
    real = os.path.realpath(s)
    r = subprocess.run([s, "-c", PROBE], capture_output=True, text=True, timeout=10)
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
