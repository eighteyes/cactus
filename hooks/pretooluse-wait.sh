#!/usr/bin/env bash
# pretooluse-wait.sh
# PreToolUse hook on Bash: refuse a foreground `cactus ask|run` that would wait for the human.
# Responsibilities:
#   - stay silent and fast for every Bash call that does not invoke cactus ask/run
#   - allow a waiting ask/run when tool_input.run_in_background is true
#   - allow --no-wait, --no-block and the acts that never wait (steer notify review plan data)
#   - otherwise exit 2 with a stderr message telling the agent to background the call
set -u
input=$(cat)

# Fast path: no jq work unless the payload even mentions cactus.
case $input in *cactus*) ;; *) exit 0 ;; esac
command -v jq >/dev/null 2>&1 || exit 0

[ "$(jq -r '.tool_name // empty' <<<"$input")" = "Bash" ] || exit 0
[ "$(jq -r '.tool_input.run_in_background // false' <<<"$input")" = "true" ] && exit 0
cmd=$(jq -r '.tool_input.command // empty' <<<"$input")

# `cactus ask|run` at command position: line start or after ; & | ( ` $( and
# optional VAR=val prefixes, with optional global flags before the verb.
nl=$'\n'
sep="(^|[;&|(\`${nl}]|\\$\\()[[:space:]]*"
env='([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*'
re="${sep}${env}cactus([[:space:]]+-[^[:space:]]+)*[[:space:]]+(ask|run)([[:space:]]|\$)"
[[ $cmd =~ $re ]] || exit 0

# Rows that do not wait.
[[ $cmd =~ (^|[[:space:]])--no-wait([[:space:]=]|$) ]] && exit 0
[[ $cmd =~ (^|[[:space:]])--no-block([[:space:]]|$) ]] && exit 0
act_re='--act[[:space:]=]+(steer|notify|review|plan|data)([[:space:]]|$)'
[[ $cmd =~ $act_re ]] && exit 0

echo "cactus ask/run waits for the human by default; rerun with run_in_background: true. Its exit wakes you." >&2
exit 2
