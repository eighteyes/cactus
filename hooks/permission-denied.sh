#!/usr/bin/env bash
# permission-denied.sh
# PermissionDenied hook: turn an auto-mode denial of a Bash command into a `cactus run` row the human can approve.
# Responsibilities:
#   - stay silent when cactus is not installed or no identity resolves
#   - act only on Bash denials; other tools have no command to re-run
#   - post one row per tool_use_id, deduped through a state file, so a retried denial does not double-post
#   - carry the denial reason as --why and the hook's cwd as --cwd
set -u
command -v cactus >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

# shellcheck source=identity.sh
. "$(dirname "${BASH_SOURCE[0]}")/identity.sh"
agent=$(cactus_resolve_agent)
[ -n "$agent" ] || exit 0

input=$(cat)
tool=$(jq -r '.tool_name // empty' <<<"$input")
[ "$tool" = "Bash" ] || exit 0
cmd=$(jq -r '.tool_input.command // empty' <<<"$input")
[ -n "$cmd" ] || exit 0
id=$(jq -r '.tool_use_id // empty' <<<"$input")
why=$(jq -r '.denial_reason // "denied by permission mode"' <<<"$input")
cwd=$(jq -r '.cwd // empty' <<<"$input")
[ -n "$cwd" ] || cwd=$PWD

# Dedupe on tool_use_id. One line per id; the file is per agent so a new
# session never inherits another's history.
state="${XDG_STATE_HOME:-$HOME/.local/state}/cactus"
mkdir -p "$state" 2>/dev/null || exit 0
seen="$state/denied-$agent"
if [ -n "$id" ]; then
  grep -qxF "$id" "$seen" 2>/dev/null && exit 0
  printf '%s\n' "$id" >>"$seen"
fi

cactus run "$cmd" --agent "$agent" --cwd "$cwd" --why "$why" -t denied >/dev/null 2>&1
exit 0
