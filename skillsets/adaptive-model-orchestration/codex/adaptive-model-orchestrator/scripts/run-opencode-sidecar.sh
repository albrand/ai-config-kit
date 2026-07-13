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

bin=${OPENCODE_BIN:-$(command -v opencode 2>/dev/null || true)}
config_dir=${OPENCODE_SIDECAR_CONFIG_DIR:-$HOME/.config/opencode-sidecar}
quality_model=${OPENCODE_QUALITY_MODEL:-zai-coding-plan/glm-5.2}
fast_model=${OPENCODE_FAST_MODEL:-zai-coding-plan/glm-5-turbo}

[[ -n $bin && -x $bin ]] || { printf '%s\n' "opencode executable not found" >&2; exit 69; }
[[ -f $config_dir/opencode.json ]] || { printf '%s\n' "sidecar config not found: $config_dir/opencode.json" >&2; exit 78; }

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

export OPENCODE_CONFIG_DIR=$config_dir
export OPENCODE_DISABLE_TERMINAL_TITLE=1
export OPENCODE_DISABLE_CLAUDE_CODE=1
exec "$bin" "${args[@]}"
