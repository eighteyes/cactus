#!/usr/bin/env bash
set -u

input=$(cat)
command -v cactus >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0
agent=$(jq -r '.session_id // empty' <<<"$input")
[ -n "$agent" ] || exit 0

hook_cwd=$(jq -r '.cwd // empty' <<<"$input")
enabled=$(cactus project-status --json --cwd "${hook_cwd:-$PWD}" 2>/dev/null \
  | jq -r 'if .enabled == false then "false" else "true" end' 2>/dev/null)
[ "${enabled:-true}" = "true" ] || exit 0

rows=$(cactus list -s any --agent "$agent" --json 2>/dev/null) || exit 0
[ -n "$rows" ] || exit 0
printf '%s\n' "Cactus mod mode (plugin loaded): use --agent $agent on every row; post decisions with cactus ask --no-wait, never arm a background cactus wait. This hook is the nearest Codex equivalent to the mod prompt injection and live pane: it refreshes on each user turn."
jq -r --arg agent "$agent" '
  [ .[] | select(.status == "elaborate") ] as $elaborate |
  [ .[] | select(.status == "answered") ] as $answered |
  [ .[] | select(.status == "open" or .status == "live") ] as $open |
  ($elaborate + $answered + $open) as $all |
  if ($all | length) == 0 then empty else
    "cactus frontier (--agent \($agent)):",
    ($all[:5][] |
      "  \(.key) \(.status) \(.word // (.text | .[0:60]))" +
      (if (.answers | length) > 0 then
        (.answers[-1] as $answer |
          if $answer.skipped then " — skipped; use the stated default"
          else " — answer: " +
            (($answer.selected // []) | join(", ")) +
            (if ($answer.text // "") == "" then "" else
              (if (($answer.selected // []) | length) > 0 then " — " else "" end) + $answer.text
             end)
          end)
       else "" end)),
    "  \($elaborate | length) to elaborate, \($answered | length) answered to act on and clear, \($open | length) open",
    (if ($open | length) > 0 then "  Codex has no wake-up from idle: answers surface here on your next turn. If the next step needs one now, block: cactus get KEY --wait --timeout 300 --json" else empty end)
  end
' <<<"$rows"

# Match the pane mod's automatic cleanup as closely as Codex's lifecycle
# allows.  Persistent review/plan/data rows remain until the agent records its
# follow-up; other settled rows are cleared after their full answer has been
# injected above.  A hook cannot start an idle Codex turn, so this happens on
# the next UserPromptSubmit boundary (or immediately when optional Herdr
# delivery wakes the session).
# Only rows the frontier above printed: it shows the first five, so a row
# past that has not had its answer injected yet and must survive this turn.
jq -r '
  ([ .[] | select(.status == "elaborate") ] +
   [ .[] | select(.status == "answered") ] +
   [ .[] | select(.status == "open" or .status == "live") ])[:5][]
  | select(.status == "answered")
  | select(.act != "review" and .act != "plan" and .act != "data")
  | .key
' <<<"$rows" | while IFS= read -r key; do
  [ -n "$key" ] || continue
  cactus clear "$key" --agent "$agent" >/dev/null 2>&1 || true
done
