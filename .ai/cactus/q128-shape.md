# q128 — What shape is the record?

status: retired
act: ask
kind: choice
thread: decisionlog
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T04:14:04.284581+00:00

## Context

Each record carries: question, context, options, recommendation, answer (selection, text or skip), who asked, who answered, timestamps. Persistent rows (review/plan) keep their full verdict log.

## Options

- file — one markdown file per question, qN-word.md, rewritten on each answer  (★◐)
- thread — one markdown file per thread, appended
- jsonl — one decisions.jsonl, appended

## Recommendation

file — med
greppable, diffable, one decision per file; reopen/undo rewrites cleanly

## Answer

file
answered at: 2026-09-23T04:14:55.710750+00:00
