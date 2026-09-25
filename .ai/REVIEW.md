# Review: cactus-mac spike (branch macapp)

1. Build:

       cd mac && swift build

   Pass: `Build complete!`, no errors.
2. Post a scratch row against a scratch DB in one shell, then launch the app from the same shell so it inherits `CACTUS_DB`:

       export CACTUS_DB=$(mktemp) CACTUS_POKE=true CACTUS_RECORDS=0
       cactus ask "Pick one" -c "a: first" -c "b: second" --recommend b --confidence high --why t --agent me
       ./.build/debug/cactus-mac &

   Pass: menu-bar item shows `1`.
3. Press ⌥Space.
   Pass: floating panel appears on the screen under the mouse; rail lists `cactus · q1 · Pick one`; card shows `1) a`, `2) b ★`, with `b` preselected.
4. Press `1`, then Enter.
   Pass: row leaves the rail, menu-bar title goes blank; `cactus get q1 --json | jq '.[0].answer.selected'` prints `["a"]`.
5. Press ⌥Space with the panel open, then again.
   Pass: hides, then shows. Esc also hides. Clicking another app hides it.
6. Post a second row, open the panel, press `s`.
   Pass: row skipped; `cactus get q2 --json | jq '.[0].answer.skipped'` is `true`.
7. Post a third row, press `c`.
   Pass: row leaves the rail; `cactus get q3 --json | jq '.[0].status'` is `cleared`.
8. Answer a row from the TUI while the panel is open, then press a digit + Enter on the same row in the panel.
   Pass: footer shows the CLI's already-answered line; nothing overwritten.
9. Quit from the menu-bar item. `trash "$CACTUS_DB"`.
