# q302 — Where does the Swift code live?

status: answered
act: ask
kind: choice
thread: macapp
parent: q297
agent: dd7e2c75-9a5e-4984-aa99-920e53797a41
cwd: .
asked at: 2026-09-25T14:37:31.861663+00:00

## Context

In-repo keeps the cactus --json contract and the app in one diff. Separate repo suits an unsigned .app release cadence that differs from the Python package. Default if unanswered: mac/.

## Options

- mac/ — SwiftPM package inside this repo, versioned with the CLI it shells out to  (★●)
- repo — separate cactus-mac repository, pinned to a cactus version

## Recommendation

mac/ — high
one contract, one diff

## Answer

mac/
answered at: 2026-09-25T16:46:54.103811+00:00
