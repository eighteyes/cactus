#!/usr/bin/env bash
# pretooluse-wait.sh
# PreToolUse hook on Bash: refuse a foreground `cactus ask|run` that would wait for the human.
# Responsibilities:
#   - stay silent and fast for every Bash call that does not invoke cactus ask/run
#   - allow a waiting ask/run when tool_input.run_in_background is true
#   - match only at command position: drop heredoc bodies and quoted text first
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
case $cmd in *cactus*) ;; *) exit 0 ;; esac

# Reduce the command to the text the shell runs as commands: heredoc bodies
# and quoted strings are data, so a line in them that starts `cactus run` is
# not a call. Expansion is the exception, kept so it still matches: a double-
# quoted string holding $( or a backtick is scanned again on its own, and an
# unquoted heredoc body line keeps the part from its first $( or backtick on.
# A heuristic, not a parser: when unsure it keeps text, and a false block costs
# one rerun where a missed one parks the agent for an hour.
LC_ALL=C
scan_commands() {
  local src=$1 out="" line c n i q span word quoted strip
  local -a pending=() pquoted=() pstrip=()
  local in_body=0 delim="" dquoted=0 dstrip=0 open=""
  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$in_body" = 1 ]; then
      local test=$line
      [ "$dstrip" = 1 ] && test=${test#"${test%%[!$'\t']*}"}
      if [ "$test" = "$delim" ]; then
        if [ "${#pending[@]}" -gt 0 ]; then
          delim=${pending[0]} dquoted=${pquoted[0]} dstrip=${pstrip[0]}
          pending=("${pending[@]:1}") pquoted=("${pquoted[@]:1}") pstrip=("${pstrip[@]:1}")
        else
          in_body=0
        fi
      elif [ "$dquoted" = 0 ] && [[ $line == *'$('* || $line == *'`'* ]]; then
        local a=${line%%'$('*} b=${line%%'`'*}
        [ "${#a}" -lt "${#b}" ] && out+="${line:${#a}}"$'\n' || out+="${line:${#b}}"$'\n'
      fi
      continue
    fi
    n=${#line} i=0
    while [ "$i" -lt "$n" ]; do
      c=${line:i:1}
      if [ -n "$open" ]; then
        # Inside a quote that began on an earlier line.
        if [ "$open" = '"' ] && [ "$c" = '\' ]; then span+=${line:i:2}; i=$((i + 2)); continue; fi
        if [ "$c" = "$open" ]; then
          if [ "$open" = '"' ] && [[ $span == *'$('* || $span == *'`'* ]]; then
            out+=$(scan_commands "$span")
          fi
          open="" span=""
        else
          span+=$c
        fi
        i=$((i + 1)); continue
      fi
      case $c in
        \\) out+=${line:i:2}; i=$((i + 2)); continue ;;
        \'|\") open=$c span=""; i=$((i + 1)); continue ;;
        '#')
          # A comment runs to end of line; its apostrophes open no quote.
          case ${out: -1} in ''|' '|$'\t'|$'\n'|';'|'&'|'|'|'(') break ;; esac ;;
        '<')
          if [ "${line:i:2}" = '<<' ] && [ "${line:i:3}" != '<<<' ]; then
            i=$((i + 2)); strip=0
            [ "${line:i:1}" = '-' ] && { strip=1; i=$((i + 1)); }
            while [ "${line:i:1}" = ' ' ] || [ "${line:i:1}" = $'\t' ]; do i=$((i + 1)); done
            quoted=0 word=""
            while [ "$i" -lt "$n" ]; do
              q=${line:i:1}
              case $q in
                \'|\") quoted=1 ;;
                \\) quoted=1 ;;
                [[:space:]\;\&\|\<\>\(\)]) break ;;
                *) word+=$q ;;
              esac
              i=$((i + 1))
            done
            if [ -n "$word" ]; then
              pending+=("$word") pquoted+=("$quoted") pstrip+=("$strip")
            fi
            out+=' '
            continue
          fi ;;
      esac
      out+=$c; i=$((i + 1))
    done
    if [ -n "$open" ]; then
      span+=$'\n'
      continue
    fi
    out+=$'\n'
    if [ "${#pending[@]}" -gt 0 ]; then
      in_body=1 delim=${pending[0]} dquoted=${pquoted[0]} dstrip=${pstrip[0]}
      pending=("${pending[@]:1}") pquoted=("${pquoted[@]:1}") pstrip=("${pstrip[@]:1}")
    fi
  done <<<"$src"
  printf '%s' "$out"
}
code=$(scan_commands "$cmd")

# `cactus ask|run` at command position: line start or after ; & | ( ` $( and
# optional VAR=val prefixes, with optional global flags before the verb.
nl=$'\n'
sep="(^|[;&|(\`${nl}]|\\$\\()[[:space:]]*"
env='([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*'
re="${sep}${env}cactus([[:space:]]+-[^[:space:]]+)*[[:space:]]+(ask|run)([[:space:]]|\$)"
[[ $code =~ $re ]] || exit 0

# Rows that do not wait. These match the raw $cmd, not $code: one of these
# flags anywhere in the call, even in a quoted string or a second command,
# lets the whole call through. Check here first when a waiting ask slipped by.
[[ $cmd =~ (^|[[:space:]])--no-wait([[:space:]=]|$) ]] && exit 0
[[ $cmd =~ (^|[[:space:]])--no-block([[:space:]]|$) ]] && exit 0
act_re='--act[[:space:]=]+(steer|notify|review|plan|data)([[:space:]]|$)'
[[ $cmd =~ $act_re ]] && exit 0

# Exit 2 is Claude Code's PreToolUse block: the call never runs and stderr
# reaches the agent as the reason.
echo "cactus ask/run waits for the human by default; rerun with run_in_background: true. Its exit wakes you." >&2
exit 2
