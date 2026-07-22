# Second Mac Bootstrap (Git-Based, No Credentials Copied)

How to bring up the agent framework on a second Mac from the public Git repo.
The second Mac **pulls** the kit from a public branch and runs explicit
copy/install commands. It must configure its **own** SSH and Tailscale; no auth,
keys, tokens, or credentials are ever copied from the first Mac.

This guide is machine-neutral: replace every `<PLACEHOLDER>` during install and
never commit a populated copy with real values back to the kit.

## Principles

- **Public source only.** The kit lives in a public Git repo. No private mirrors
  or personal folders are referenced.
- **No credentials cross machines.** SSH keys, Tailscale auth keys, provider API
  keys, `~/.ssh`, `~/.config/opencode*`, and any `CMUX_*`/socket-capability
  material are created in place on the second Mac. They are never copied,
  forwarded, or serialized.
- **Explicit commands.** Every install step is a literal command you run and
  review. No background daemons, no broad environment forwarding, no reverse SSH.
- **Idempotent.** Re-running a step is safe.

## 1. Prerequisites (on the second Mac)

```sh
# Verify the required tools are present (install via brew/asdf as needed).
git --version
node --version
python3 --version
```

Install any missing tool with the system package manager. Do not copy binaries
or config from another machine.

## 2. Clone A Reviewed Immutable Revision

```sh
REVIEWED_COMMIT="<PINNED_COMMIT_SHA_FROM_RELEASE_NOTES>"
git clone https://github.com/albrand/ai-config-kit.git ~/projects/agent-config-kit
cd ~/projects/agent-config-kit
git checkout --detach "$REVIEWED_COMMIT"
test "$(git rev-parse HEAD)" = "$REVIEWED_COMMIT"
git status --short                # expect no output
```

Use the commit printed in the operator release/handoff, not a mutable branch.
If the URL requires credentials or the commit does not match exactly, stop.

## 3. Validate Before Activation

```sh
node scripts/validate-codex-skills.cjs
PYTHONDONTWRITEBYTECODE=1 python3 skillsets/native-agent-surfaces/codex/native-agent-surface/scripts/detect-native-surfaces.py --selftest
PYTHONDONTWRITEBYTECODE=1 python3 skillsets/native-agent-surfaces/scripts/install_test.py
PYTHONDONTWRITEBYTECODE=1 python3 skillsets/cmux-hermes-orchestration/scripts/hermes-work-journal.py selftest
PYTHONDONTWRITEBYTECODE=1 python3 skillsets/cmux-hermes-orchestration/scripts/cmux_hermes_test.py
```

Review `git show --stat --oneline HEAD` and the global directives before copying
anything into an agent home. All checks must pass.

## 4. Copy The Framework And Install Skills

Copy only the framework files the second Mac needs. Review each path before
copying.

```sh
# Stable install location for the kit on the new machine.
DEST="$HOME/agent-framework"
mkdir -p "$DEST"

# Copy the kit (docs + skillsets + scripts + adapters). Explicit, no hidden files
# from outside the repo.
cp -R AI_BOOTSTRAP.md FRAMEWORK_MANIFEST.md README.md GLOBAL_AGENTS.md "$DEST"/
cp -R NATIVE_AGENT_SURFACES.md SESSION_JOURNALING.md "$DEST"/ 2>/dev/null || true
cp -R skillsets scripts adapters "$DEST"/

CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$CODEX_HOME/skills" "$HOME/.claude/commands" "$HOME/.local/bin"
```

Native agent surfaces is installed by the preference-aware installer, **not** by
an unconditional skill copy. You must choose an explicit mode first. A missing,
corrupt, or unknown preference fails closed.

```sh
# REQUIRED: choose exactly one. Replace the placeholder before running.
NATIVE_SURFACES_PREFERENCE="<ENABLED|AUTO|DISABLED>"
case "$NATIVE_SURFACES_PREFERENCE" in
  ENABLED|AUTO|DISABLED) mode="$(echo "$NATIVE_SURFACES_PREFERENCE" | tr A-Z a-z)" ;;
  *) echo "Set NATIVE_SURFACES_PREFERENCE to ENABLED, AUTO, or DISABLED." >&2; exit 1 ;;
esac

# Install the versioned bundle + Codex adapter from a hash receipt.
python3 skillsets/native-agent-surfaces/scripts/install.py install --mode "$mode"
python3 skillsets/native-agent-surfaces/scripts/install.py status

detector="$CODEX_HOME/skills/native-agent-surface/scripts/detect-native-surfaces.py"
if [ -x "$detector" ]; then
  ln -sfn "$detector" "$HOME/.local/bin/native-agent-surfaces"
fi
```

cmux + Hermes orchestration and plan-arbiter are **separate and optional**.
Install them only if you have adopted cmux + Hermes; otherwise skip this block.

```sh
# OPTIONAL: cmux (local UI/session transport) + Hermes (remote router).
INSTALL_CMUX_HERMES="<yes|no>"
if [ "$INSTALL_CMUX_HERMES" = "yes" ]; then
  for skill in cmux-hermes-orchestrator plan-arbiter; do
    rsync -a --delete "skillsets/cmux-hermes-orchestration/codex/$skill/" \
      "$CODEX_HOME/skills/$skill/"
  done
  for command in cmux-hermes plan-arbiter; do
    install -m 0600 "skillsets/cmux-hermes-orchestration/claude/commands/$command.md" \
      "$HOME/.claude/commands/$command.md"
  done
  chmod 0755 "$CODEX_HOME/skills/cmux-hermes-orchestrator/scripts/cmux-hermes.py"
  ln -sfn "$CODEX_HOME/skills/cmux-hermes-orchestrator/scripts/cmux-hermes.py" \
    "$HOME/.local/bin/cmux-hermes"
fi

# Refresh the Codex skill index if the router is installed.
if [ -f "$CODEX_HOME/skills/skill-library-router/scripts/refresh-skill-index.cjs" ]; then
  node "$CODEX_HOME/skills/skill-library-router/scripts/refresh-skill-index.cjs"
  node "$CODEX_HOME/skills/skill-library-router/scripts/refresh-skill-index.cjs" --check
fi
```

Do not copy: `.git`, any `journals/`, any `.env`, any local-only notes, or any
file containing credentials.

## 5. Configure The Repo Bootstrap

Point the new machine at its **own** instruction file. Do not copy the first
Mac's `AGENTS.md` wholesale if it carries machine-specific paths.

```sh
# Use the provided template, then edit local paths for THIS machine.
cp adapters/AGENTS.md "$DEST/AGENTS.md"
$EDITOR "$DEST/AGENTS.md"   # set THIS machine's repo roots and validation cmds
```

## 6. Create Local Auth (In Place)

Each machine owns its own credentials. Generate fresh on the second Mac:

```sh
# SSH key for THIS machine only.
ssh-keygen -t ed25519 -C "second-mac" -f "$HOME/.ssh/id_ed25519"
# Register the new public key where needed yourself. Do not copy the first Mac's key.

# Tailscale: log in on THIS machine. Do not reuse another machine's auth key.
# (Install the app, then authenticate interactively.)
```

Never copy `~/.ssh/*`, Tailscale auth keys, provider API keys, or any
`CMUX_SOCKET_CAPABILITY`/`CMUX_*` value from another machine.

## 7. Validate The Installed Runtime

```sh
# Native surfaces detector (manual inspection), only when installed. With
# NATIVE_SURFACES_PREFERENCE=DISABLED, automatic discovery and installation skip.
if command -v native-agent-surfaces >/dev/null 2>&1; then
  native-agent-surfaces --format json | python3 -m json.tool
fi
python3 skillsets/native-agent-surfaces/scripts/install_test.py

# Optional, only when INSTALL_CMUX_HERMES=yes:
if [ "$INSTALL_CMUX_HERMES" = "yes" ]; then
  CMUX_HERMES_TARGET="<LOCAL_SSH_ALIAS>" \
  CMUX_HERMES_ALLOWED_TARGETS="<LOCAL_SSH_ALIAS>" \
    cmux-hermes doctor --target "<LOCAL_SSH_ALIAS>"
  ssh -o BatchMode=yes -- "<LOCAL_SSH_ALIAS>" \
    'sudo -u hermes /usr/local/bin/hermes-work-journal list'
fi
```

The native-surfaces detector self-test must pass before the install is considered
ready; the cmux + Hermes checks apply only when that surface was installed.

## 8. Promote A Reviewed Update

```sh
cd ~/projects/agent-config-kit
NEXT_REVIEWED_COMMIT="<NEW_PINNED_COMMIT_SHA>"
git fetch origin
git diff --stat HEAD "$NEXT_REVIEWED_COMMIT"
git diff HEAD "$NEXT_REVIEWED_COMMIT" -- GLOBAL_AGENTS.md adapters skillsets scripts
# Review the diff, then explicitly promote and repeat steps 3, 4, and 7.
git checkout --detach "$NEXT_REVIEWED_COMMIT"
test "$(git rev-parse HEAD)" = "$NEXT_REVIEWED_COMMIT"
```

## What This Guide Never Does

- Clone a private/authenticated URL as the kit source.
- Copy `~/.ssh`, Tailscale keys, provider tokens, or any `CMUX_*` value.
- Forward the full environment to any remote host.
- Open a reverse SSH tunnel, listener, or daemon.
- Embed real repo URLs, hostnames, or org-specific details — placeholders only.

Resolve all `<PLACEHOLDER>` values during install on the second Mac.
