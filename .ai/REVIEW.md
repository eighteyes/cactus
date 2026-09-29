# Review: cactus field

Branch cactus-v1. v1: cf3fc73, e5a81cc (strip under the status bar, verified
pass on q359). v2 (in progress): the field moves under the question inside the
card column and becomes a desert simulation. Steps below target v2; on v1 the
strip sits above the footer instead and there is no sky.

## Setup

Run every command from one shell so the env holds.

    export CACTUS_DB=$(mktemp -d)/field.db
    export CACTUS_POKE=true
    export CACTUS_RECORDS=0
    export A=review-field
    cd ~/projects/cactus

Seed rows. Six choice rows so one key can be pressed repeatedly, one confirm
row, one notice, one data row.

    for n in 1 2 3 4 5 6; do
      cactus ask "choice $n" -c "left: l" -c "right: r" --agent $A
    done
    cactus ask "confirm me" --confirm --agent $A
    cactus ask "a notice" --act notify --agent $A
    cactus ask "some data" --act data -c "one: echo 1" --agent $A

Open the surface:

    cactus --tui

## Steps

1. Look inside the "answering" box. The question text sits at the top, the
   scene fills the rest down to a one-line key bar at the bottom of the box.
   Make the terminal taller: the sky grows, the ground stays at the bottom.
   Expect: a speckled sand band, cirrus streaks in braille bunched mid-sky,
   dotted tones from specks at the edges to dense cores, drifting across the
   sky, nothing green yet. Leave it for a minute: the clouds drift, low ones faster and brighter, high ones slower and hazier, and their shapes swell and thin.
   Now and then a flock ripples across in a loose V: far ones as specks, near ones as wide `\_/` `/^\` wingbeats. Flecks that land brighten, then darken as later answers pile on.
2. Read the key bar in the box: "1 left  2 right  i type  s skip ...". The
   bottom Footer shows only global keys (j k [ ] P a ? ` q). Press `1` on
   "choice 1". Expect: a bright green fleck appears at the top, directly
   above where "1" sits in the key bar. It drifts down over about a minute, sways gently with the wind, turns
   darker green when it lands on the ground.
3. Press `1` five more times (rows "choice 2" through "choice 6"). Expect:
   flecks land near the first one, on top of it or beside it, growing an
   uneven pile. Wind spreads them; they do not all stack in one column.
4. Press `y` on "confirm me". Expect: a fleck from the `y` key's footer
   position, left of where `1` sits.
5. Press `d` on "a notice". Expect: a fleck from the `d` key's position.
6. Press `1` on "some data". Expect: one fleck (a copy is an answer).
7. Press `c` on any remaining row. Expect: no fleck.
8. Press `u`. Expect: the row returns; every landed fleck stays.
9. Quit with `q`. Expect: no traceback in the terminal.
10. Relaunch `cactus --tui`. Expect: the same pile (v8 garden; q356's
    session-only is superseded, see below).
11. Teardown mid-fall (the e5a81cc fix). Seed one more row, relaunch, press
    `1` and press `q` while the fleck is still in
    the air. Expect: clean exit, no `NoMatches` traceback. Repeat three
    times; the sky timer in v2 runs constantly, so every quit exercises
    `on_unmount`.

        cactus ask "choice 7" -c "left: l" -c "right: r" --agent $A
        cactus --tui

## v8: puffs, slots, garden

Same setup and env as above.

1. `T`, `j` down to `[shared] sky_engine`, `l` until it reads `'puffs'`.
   Expect: the sky re-bakes. Watch 30 seconds. Expect: separate clouds, not
   an overcast. No cloud slides as a group with the sky; each one creeps
   its own way, some left, some right, some nearly still. A cloud comes in
   as a few dense cores that grow fringes over ~30 s, holds, then thins
   back to cores and goes. Nothing snaps.
2. `j` to `cloud_style`, `l`. Expect: `'bloom'`: bigger, near-still clouds,
   slower unfold. `l` again: `'streaks'`: long thin bands. `l` again:
   back to `'drift'`.
3. `j` to `cloud_drift`, `L`. Expect: clouds visibly faster within 10 s.
   `r`. Expect: reset to 1.5.
4. Slots. `S` then `1`. Expect: flash `saved slot 1`, the overlay's slots
   line reads `1● 2○ ...`. `j` to `sky_engine`, `l` to `'texture'`. Then
   `1`. Expect: flash `recalled slot 1`, engine back to `'puffs'`, clouds
   re-bake. `3`. Expect: flash `slot 3 is empty`. `esc`.
5. `ls ~/.config/cactus/`. Expect: `sky.toml`, `sky-slot-1.toml`.
6. Garden. Answer three rows with `1`, wait for the flecks to land. `q`.
   Expect: `$(dirname "$CACTUS_DB")/garden.json` exists. Relaunch. Expect:
   the same pile. Launch a second `cactus --tui` in another terminal on the
   same `CACTUS_DB`, answer a row there, wait for the landing. Expect: the
   first TUI's pile gains the fleck within a few seconds, flash
   `garden updated`.
7. `~`. Expect: the whole field strip disappears, flash `garden hidden`,
   the card gets the room. Backtick. Expect: only the ground rows and the
   landed blocks show, no sky, flash `pile shown`. Backtick again. Expect:
   gone. `~`. Expect: full field back; backtick now drops a seed again.
8. `q`, relaunch. Expect: the `~` state persists (still hidden if you left
   it hidden).
9. `cactus garden`. Expect: the path and a cell count. `cactus garden
   --clear`. Expect: `cleared <path>`. Relaunch. Expect: an empty field.

## v8b: names, grain, seed wind, charge

10. `T`. Expect: a `saved skies` grid at the top, three per row, every slot
    named (`1 still-bloom` … `9 crisp-dots`). `S`, `2`, type `wisp`,
    enter. Expect: the grid reads `2 wisp`, flash `saved slot 2 as wisp`.
    `2`. Expect: flash `recalled slot 2: wisp`. `S`, `3`, `j`, `k`, esc.
    Expect: cursor unmoved, nothing saved, flash `save cancelled`.
11. `5`, `6`, `7`, `8` in turn, watch 20 s each. Expect: clouds creep, no
    slab of one repeated glyph wider than ~10 cells, no `/` or `\` anywhere
    in the sky, small markers (`, . ' - * # \``) sprinkled through the
    dither. Seeds sway gently, not in a gale, while the clouds creep.
12. Charge. Under `2` (busy-drift), answer a row whose key sits under a
    cloud. Expect: the falling fleck fattens by one cell as it enters the
    cloud; on landing one extra fleck bursts off sideways and up, then
    lands nearby. A fleck that crosses two clouds and a bird bursts three.
    Exploded flecks never burst again.

## Fail

- No field under the question, or the field still sits above the footer.
- Every fleck starts at the right edge regardless of key (the v1 bug).
- Flecks pass through the pile or float above the ground.
- Sky is static for 20 seconds.
- Traceback on quit.
- v8: the whole cloud deck slides sideways in lockstep under `puffs`.
- v8: a cloud pops in or out at full density instead of unfolding.
- v8: a recalled slot does not survive `q` and relaunch.
- v8: two TUIs on one DB show different piles after a landing.
- v8: backtick drops a seed while the field is hidden.
- v8b: a `/` or `\` in the sky; a slot without a name after the installer.
- v8b: an exploded fleck bursts again on landing.

## Teardown

    rm -rf "$(dirname "$CACTUS_DB")"
