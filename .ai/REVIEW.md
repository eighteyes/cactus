# Review: footer keys follow the focused row

1. Seed one row per act and open the TUI against a scratch DB:

       export CACTUS_DB=$(mktemp) CACTUS_POKE=true CACTUS_RECORDS=0
       A=review-me
       cactus ask "review?" --act review --agent $A
       cactus ask "plan?" --act plan --agent $A && cactus plan q2 --step one --step two
       cactus ask "notice" --act notify --agent $A
       cactus ask "chunks" --act data --agent $A -c "one: echo hi"
       cactus ask "confirm?" --confirm --agent $A
       cactus ask "pick" -c a -c b --no-free --agent $A
       cactus run "echo hi" --agent $A --why test
       cactus --tui

2. Walk the rail with `j` and read the footer on each row.

   Pass:
   - review row: `y pass  n fail`
   - run row: `y approve  n deny`
   - plan row: `1-9 Toggle step`
   - data row: `1-9 Copy chunk`, `d Close`
   - notify row: `d Dismiss`
   - `s Skip` present on every row above
   - `--no-free` row: no `i`, and the card hint has no `i type`
   - project keys render as `[` `]`, settings as `?`

   Fail: any row still showing `y Yes  n No`, or `1 1-9`.

3. Throwaway probe that prints the same per act:

       PYTHONPATH=src python .ai/tmp/probe_footer.py
