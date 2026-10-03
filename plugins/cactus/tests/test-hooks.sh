#!/usr/bin/env bash
# Exercise the Codex hook substitute against an isolated Cactus inbox.
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../../.." && pwd)
scratch_dir=$(mktemp -d)
trap 'rm -rf "$scratch_dir"' EXIT

export CACTUS_DB="$scratch_dir/s.db"
export CACTUS_POKE=true
export CACTUS_RECORDS=0

agent=codex-hook-test
key=$(cd "$repo_root" && cactus ask 'Choose the test path' \
  -c fast -c safe --no-wait --agent "$agent")

input=$(jq -nc --arg agent "$agent" --arg cwd "$repo_root" \
  '{session_id:$agent,cwd:$cwd}')
frontier=$(cd "$repo_root" && printf '%s\n' "$input" \
  | bash plugins/cactus/hooks/frontier.sh)

grep -F 'Cactus mod mode (plugin loaded)' <<<"$frontier"
grep -F "$key open Choose the test path" <<<"$frontier"

cd "$repo_root"
cactus answer "$key" -s safe >/dev/null
frontier=$(printf '%s\n' "$input" | bash plugins/cactus/hooks/frontier.sh)
grep -F "$key answered Choose the test path — answer: safe" <<<"$frontier"

if ! cactus list -s any --agent "$agent" --json | jq -e --arg key "$key" \
  'any(.[]; .key == $key and .status == "cleared")' >/dev/null; then
  printf '%s\n' 'expected hook to auto-clear the answered row' >&2
  exit 1
fi

if cactus feed --json --agent "$agent" --here >/dev/null 2>&1; then
  printf '%s\n' 'expected cleared row to leave the active feed' >&2
  exit 1
fi

skip_key=$(cactus ask 'Skip uses the declared default' -c default --no-wait \
  --agent "$agent")
cactus answer "$skip_key" --skip >/dev/null
frontier=$(printf '%s\n' "$input" | bash plugins/cactus/hooks/frontier.sh)
grep -F "$skip_key answered Skip uses the declared default — skipped; use the stated default" \
  <<<"$frontier"
cactus list -s any --agent "$agent" --json | jq -e --arg key "$skip_key" \
  'any(.[]; .key == $key and .status == "cleared")' >/dev/null

# The pane mod leaves persistent review/plan/data rows for an explicit agent
# follow-up.  The Codex boundary hook must retain that distinction too.
review_key=$(cactus ask 'Review the test decision' --act review --no-wait \
  --agent "$agent")
cactus answer "$review_key" pass >/dev/null
frontier=$(printf '%s\n' "$input" | bash plugins/cactus/hooks/frontier.sh)
grep -F "$review_key live Review the test decision — answer: pass" <<<"$frontier"
cactus list -s any --agent "$agent" --json | jq -e --arg key "$review_key" \
  'any(.[]; .key == $key and .status == "live" and (.answers | length) == 1)' >/dev/null

printf '%s\n' 'cactus Codex hook test passed'
