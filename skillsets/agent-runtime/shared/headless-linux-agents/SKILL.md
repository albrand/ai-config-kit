---
name: headless-linux-agents
description: >
  Use when a coding agent on a headless Linux box or VPS FAILS — every shell
  command denied, "setting up uid map: Permission denied", a sandbox or bwrap
  error, a login that hangs with no code printed, EACCES on a global npm
  install, or a daemon that dies when SSH disconnects. Host policy masquerading
  as agent bugs.
verify: ssh {{REMOTE_HOST}} 'sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null; ls /etc/apparmor.d/codex-bwrap'
verified: 2026-08-12
---

# Agents on a headless Linux host

## Ubuntu 24.04 blocks the sandbox, so every command fails

Symptom: every shell command the agent runs fails with

```
bwrap: setting up uid map: Permission denied
```

Cause: Ubuntu 24.04 sets `kernel.apparmor_restrict_unprivileged_userns=1`, which
blocks unprivileged user namespaces. Codex sandboxes every command inside its own
vendored bubblewrap, so nothing runs. The sysctls that usually matter
(`unprivileged_userns_clone`, `max_user_namespaces`) look fine, which sends you
down the wrong path.

Fix — scope it to the one binary rather than weakening the machine:

```
# /etc/apparmor.d/codex-bwrap
abi <abi/4.0>,
include <tunables/global>

profile codex-bwrap /usr/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/codex-resources/bwrap flags=(unconfined) {
  userns,
  include if exists <local/codex-bwrap>
}
```

Then `sudo apparmor_parser -r /etc/apparmor.d/codex-bwrap`. The path carries no
version, so it survives agent upgrades.

The two alternatives are worse: turning the sysctl off machine-wide, or disabling
the agent's sandbox entirely. Reverting is deleting the file and reloading
apparmor.

## Authenticate with device flow, never a callback

`codex login` starts a callback server on the host's own localhost, which nothing
else can reach. Use `codex login --device-auth`, which prints a code to enter at
a URL from any browser.

Its output is **buffered when stdout is not a TTY** — run it under
`stdbuf -oL -eL` or the code never appears and it looks like a hang.

Have the human enter the code themselves; the secret then never passes through
the agent.

## Installing

- The agent's own `provider-cli install` runs unprivileged and fails with EACCES
  on `/usr/lib/node_modules`. Install with `sudo npm i -g …` instead.
- A daemon installed as a **systemd user service dies when the SSH session ends**.
  `sudo loginctl enable-linger <user>` — without it the machine shows connected,
  then immediately disconnected.
- Native modules (`node-pty`) need `build-essential` and `python3`.
