#!/usr/bin/env bash
set -euo pipefail

if (( $# < 4 )); then
  printf '%s\n' "usage: $0 <sol|terra|luna|model-id> <high|xhigh|max|ultra> <workdir> <prompt>" >&2
  exit 64
fi

family=$1
effort=$2
workdir=$3
prompt=$4
bin=${CODEX_PEER_BIN:-$(command -v codex 2>/dev/null || true)}

case $family in
  sol) model=${CODEX_SOL_MODEL:-gpt-5.6-sol} ;;
  terra) model=${CODEX_TERRA_MODEL:-gpt-5.6-terra} ;;
  luna) model=${CODEX_LUNA_MODEL:-gpt-5.6-luna} ;;
  *) model=$family ;;
esac

case $effort in high|xhigh|max|ultra) ;; *) printf '%s\n' "unsupported effort: $effort" >&2; exit 64 ;; esac
[[ -n $bin && -x $bin ]] || { printf '%s\n' "codex executable not found" >&2; exit 69; }

contract="You are an independent read-only peer. Do not invoke an external sidecar, edit files, or perform external mutations. Challenge the bounded conclusion using current source evidence. Return only load-bearing findings and stop when answered."

exec "$bin" exec --ephemeral --json --skip-git-repo-check -C "$workdir" \
  -s read-only -m "$model" -c "model_reasoning_effort=\"$effort\"" \
  -c 'approval_policy="never"' "$contract

$prompt"
