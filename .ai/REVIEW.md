# Review: notify rename + data act (commit 32cc210, branch cactus-v1)

1. Post a data row from a scratch shell:

       CACTUS_POKE=true cactus ask "Backfill queries" --act data -t db --agent me \
         -c "count: SELECT count(*) FROM orders
       WHERE backfilled IS NULL" \
         -c "run: UPDATE orders SET backfilled = now() WHERE backfilled IS NULL"

2. Open `cactus --tui`, focus the row.
   Pass: card shows `1) count` with `| ` body lines under it, footer reads `1-9 copy chunk   d dismiss`.
3. Press `2`.
   Pass: flash `copied 2) run via pbcopy`; paste yields the UPDATE verbatim; row still on the board.
4. `cactus get KEY --json | jq '.[0].answers'`
   Pass: one verdict, `selected: ["run"]`, status `live`.
5. Press `d`, then `u`.
   Pass: row leaves, then returns live with the verdict intact.
6. `cactus ask "x" --act data --agent me` and `--act seen`.
   Pass: both refused, exit 1.
7. Any pre-existing `seen` row in the live DB reads `notify` after any cactus verb runs.
