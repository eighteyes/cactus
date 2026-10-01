#!/usr/bin/env bash
set -u

input=$(cat)
command -v cactus >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0
agent=$(jq -r '.session_id // empty' <<<"$input")
command=$(jq -r '.tool_input.command // empty' <<<"$input")
cwd=$(jq -r '.cwd // empty' <<<"$input")
why=$(jq -r '.tool_input.description // "requires Codex approval"' <<<"$input")
[ -n "$agent" ] && [ -n "$command" ] || exit 0

key=$(cactus run "$command" --no-wait --agent "$agent" --cwd "${cwd:-$PWD}" --why "$why" 2>/dev/null || true)
[ -n "$key" ] || exit 0
jq -nc --arg key "$key" '{hookSpecificOutput:{hookEventName:"PermissionRequest",decision:{behavior:"deny",message:("Cactus approval " + $key + " was opened. Wait for its answer before retrying.")}}}'
