# q340 — Remove the monitor stuff: how far?

status: answered
act: ask
kind: choice
thread: durability
agent: 61b93eb6-af33-46a9-ae97-9aa508895e5f
cwd: .
asked at: 2026-09-28T04:39:22.624692+00:00

## Context

docs: text only, no behavior change, hosts that can hold a stream
(webhook relays, library callers) keep working.

mode-too: monitor.py loses the forever loop, tests for --replay/streaming
rewrite, cactus-courier subagent and the jq pipe recipe in SKILL.md break
and need rewriting to a loop of --once calls.

Default if unanswered: docs.

## Options

- docs — strip every Monitor-tool reference (Codex hook, SKILL, README, GROK, DESKTOP); keep the unbounded --monitor stream as a CLI mode  (★●)
- mode-too — also delete the unbounded stream; --monitor always behaves as --once, --once flag becomes a no-op

## Recommendation

docs — high
no host has shown it needs removing; the tool reference is the problem

## Answer

docs
answered at: 2026-09-28T04:48:19.092333+00:00
