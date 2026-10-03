# q455 — Which inputs does the pane need?

status: answered
act: ask
kind: multi
thread: mod
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T18:15:39.243471+00:00

## Context

Now: a box shows only on rows with allow_free, or multi rows; never on data rows.
q451 answered works from the pane; q452 picked plan (step ticks, run button) - not started.

Modfolder: ~/ai/mods/cactus-pane, linked at ~/.claude/mods.

Default if unanswered: verdict + keys.

## Files

- /Users/god/ai/mods/cactus-pane/hooks/register.tsx

## Options

- verdict — text box on review/plan/data rows for a typed verdict
+ today those rows get none (data) or only via allow_free  (★◐)
- every — a text box on every answerable row, always shown
+ type a note beside any pick
- --no-free rows still refuse text
- keys — number hotkeys 1-9 for choices, s skip, i jump to text
+ answer without tab-walking
- needs focus (ctrl+x tab or /cactus-pane)  (★◐)

## Recommendation

verdict, keys — med
the TUI is key-driven; review/plan need typed verdicts

## Answer

all, just provide parity
answered at: 2026-10-02T18:16:20.440232+00:00
