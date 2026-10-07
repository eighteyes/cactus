#!/usr/bin/env bash
# frontier.sh
# Codex UserPromptSubmit hook: the mod-mode substitute (50938fc).
# Responsibilities:
#   - inject the mod-mode workflow line and this agent's frontier each user turn
#   - print each row's full latest answer, so an answer reaches Codex here
#   - clear answered one-shot rows, but only the ones printed this turn
#   - stay silent (exit 0) when CACTUS_FRONTIER_HOOK=0, before reading stdin
# Codex has no live pane and no way for an extension to start a turn, so this
# hook does the mod's job on the next prompt; herdr delivery (`cactus deliver`,
# 185e58d) is the only external wake.
# Every bail-out below is a silent exit 0: "Codex never sees the frontier"
# means one of them fired. Check, in order: cactus and jq on PATH, a
# session_id in the payload, project-status not disabled, `cactus list` OK.
set -u

# On by default; CACTUS_FRONTIER_HOOK=0 opts out.
[ "${CACTUS_FRONTIER_HOOK:-1}" = "0" ] && exit 0
input=$(cat)
command -v cactus >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0
# Codex's session_id is the owner: rows posted under another --agent never
# show here and are never cleared by this hook.
agent=$(jq -r '.session_id // empty' <<<"$input")
[ -n "$agent" ] || exit 0

hook_cwd=$(jq -r '.cwd // empty' <<<"$input")
enabled=$(cactus project-status --json --cwd "${hook_cwd:-$PWD}" 2>/dev/null \
  | jq -r 'if .enabled == false then "false" else "true" end' 2>/dev/null)
[ "${enabled:-true}" = "true" ] || exit 0

# -s any includes cleared rows; the jq filters below drop them by status.
# Scope is the cactus process cwd (the hook's), not the payload's `cwd`.
rows=$(cactus list -s any --agent "$agent" --json 2>/dev/null) || exit 0
[ -n "$rows" ] || exit 0
printf '%s\n' "Cactus mod mode (plugin loaded): use --agent $agent on every row; post decisions with cactus ask --no-wait, never arm a background cactus wait. This hook is the nearest Codex equivalent to the mod prompt injection and live pane: it refreshes on each user turn."
# CONTRACT: order is elaborate, answered, open/live, capped at 5. The cleanup
# filter below must build the same list in the same order, or it clears a row
# this turn never printed.
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
# Lost-answer report ("answered, then gone, agent never acted"): the row was
# printed once and cleared in the same hook run. Its answer is in the Codex
# transcript for that turn and in the cleared row (`cactus get KEY`).
# Clear failures are swallowed: a row that fails to clear reprints next turn.
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
