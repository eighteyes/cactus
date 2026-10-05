# q546 — Start counting visitors before posting anywhere? (GitHub forgets after 14 days)

status: answered
act: ask
kind: choice
thread: dist
agent: 505bd8a7-9dcc-4cd8-933c-1a3e8b898e4f
cwd: .
asked at: 2026-10-05T04:46:42.647531+00:00

## Context

Why this is first:
- You're about to post cactus in places (awesome lists, HN, Reddit). Next week you'll want to know which one sent people.
- GitHub only shows the last 14 days of repo visitors, then deletes them. No site means no other analytics.
- Today: 8 unique visitors in 14 days, 2 stars, 1 referrer (github.com). That's the 'before' number.
- A tiny script saves one line a day to a local CSV, so 'after' can be compared with 'before'.
Without it, every post is a shot in the dark and next week's rerun has nothing to learn from.
Cost: I write it (~12 min of my time, local only, read-only GitHub API). You add one crontab line.

## Files

- /Users/god/projects/cactus/.ai/dist/distributionism-2026-10-04.md

## Options

- do-it — I write the counter script, save the last 14 days, you add the crontab line
+ a 'before' number for every post that follows
+ local only  (★●)
- skip — Skip counting, go straight to the README rewrite (action 5)
+ visible progress today
- no way to tell which post worked
- manual — No script; I just tell you to glance at github.com/eighteyes/cactus/graphs/traffic once a week
+ zero setup
- you must remember, and anything older than 14 days is gone

## Recommendation

do-it — high

## Answer

 wtf why?
answered at: 2026-10-05T05:09:59.154584+00:00
