#!/usr/bin/env bash
set -euo pipefail

if (( $# < 3 )); then
  printf '%s\n' "usage: $0 <fast|high|max|audit-high|audit-max|execute-high|execute-max> <workdir> <prompt> [evidence-file ...]" >&2
  exit 64
fi

mode=$1
workdir=$2
prompt=$3
shift 3

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
bin=${OPENCODE_BIN:-$(command -v opencode 2>/dev/null || true)}
config_dir=${OPENCODE_SIDECAR_CONFIG_DIR:-$HOME/.config/opencode-sidecar}
managed_runner=${OPENCODE_MANAGED_RUNNER:-$script_dir/run-managed.mjs}
quality_model=${OPENCODE_QUALITY_MODEL:-zai-coding-plan/glm-5.2}
fast_model=${OPENCODE_FAST_MODEL:-zai-coding-plan/glm-5-turbo}

[[ -n $bin && -x $bin ]] || { printf '%s\n' "opencode executable not found" >&2; exit 69; }
[[ -f $config_dir/opencode.json ]] || { printf '%s\n' "sidecar config not found: $config_dir/opencode.json" >&2; exit 78; }
[[ -x $managed_runner ]] || { printf '%s\n' "managed runner not executable: $managed_runner" >&2; exit 78; }

model=$quality_model
agent=glm-advisor
variant=high

case $mode in
  fast) model=$fast_model; agent=glm-fast; variant="" ;;
  high) ;;
  max) variant=max ;;
  audit-high) agent=glm-audit ;;
  audit-max) agent=glm-audit; variant=max ;;
  execute-high) agent=glm-quality ;;
  execute-max) agent=glm-quality; variant=max ;;
  *) printf '%s\n' "unknown mode: $mode" >&2; exit 64 ;;
esac

if [[ $mode == execute-* ]]; then
  marker="$workdir/.ai-config-kit-sidecar-write-scope"
  if [[ ${OPENCODE_ALLOW_WRITES:-0} != 1 || ! -f $marker ]]; then
    printf '%s\n' "executor mode requires OPENCODE_ALLOW_WRITES=1 and an isolated worktree marker: $marker" >&2
    exit 77
  fi
fi

args=(run "$prompt" --format json --auto --pure --dir "$workdir" -m "$model" --agent "$agent")
[[ -z $variant ]] || args+=(--variant "$variant")
for evidence in "$@"; do args+=(-f "$evidence"); done

managed_args=()
if [[ ${OPENCODE_RETAIN_SESSION:-0} == 1 ]]; then managed_args+=(--retain-session); fi
if [[ -n ${OPENCODE_RUN_DEADLINE_MS:-} ]]; then managed_args+=(--deadline-ms "$OPENCODE_RUN_DEADLINE_MS"); fi
if [[ $mode == execute-* ]]; then managed_args+=(--success-contract structured); else managed_args+=(--success-contract process); fi

if [[ ( -n ${OPENCODE_SESSION_ID:-} || ${OPENCODE_CONTINUE:-0} == 1 || ${OPENCODE_FORK_SESSION:-0} == 1 ) && ${OPENCODE_RETAIN_SESSION:-0} != 1 ]]; then
  printf '%s\n' "same-step continuation requires OPENCODE_RETAIN_SESSION=1" >&2
  exit 64
fi

if [[ -n ${OPENCODE_SESSION_ID:-} ]]; then
  args+=(--session "$OPENCODE_SESSION_ID")
elif [[ ${OPENCODE_CONTINUE:-0} == 1 ]]; then
  args+=(--continue)
fi
if [[ ${OPENCODE_FORK_SESSION:-0} == 1 ]]; then args+=(--fork); fi

export OPENCODE_CONFIG_DIR=$config_dir
export OPENCODE_DISABLE_TERMINAL_TITLE=1
export OPENCODE_DISABLE_CLAUDE_CODE=1
exec "$managed_runner" "${managed_args[@]}" -- "$bin" "${args[@]}"
