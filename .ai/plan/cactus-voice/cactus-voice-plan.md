# cactus-voice

Objective (q635, human, 2026-10-10): answer the cactus inbox by voice. Hear with Apple speech recognition, speak with `vsay`. Transcript goes through a fixed grammar first; anything it can't parse goes to Claude, which turns it into one cactus command; `vsay` speaks a short result and the next question.

**Host:** Cactus.app (forks q-host). Apple speech recognition is a Swift API (`SFSpeechRecognizer`), the app already owns a global hotkey, the sidebar, the current row and every cactus verb. No second process.

**Loop**

    hotkey down -> listen (SFSpeechRecognizer, on-device) -> hotkey up -> final transcript
    -> grammar (Voice/Grammar.swift, pure, tested)            -> Command
    -> no match -> interpreter (claude -p, haiku)            -> Command (validated)
    -> confirm gate (destructive commands only)
    -> run through the existing CactusCLI call path (same as the keys)
    -> speak: vsay -v VOICE "<result>. <next question>"

**Grammar** (current row is implicit; a `qN` names another row in the current project)

| say | does |
|---|---|
| "one" … "nine", "pick two", "answer q12 three" | pick choice N (auto-advances like the digit key) |
| "answer q12 red", "red" | pick the choice whose label matches (case-folded, exact then unique prefix) |
| "pass" / "fail" | review verdict (y / n) |
| "yes" / "no" | confirm rows |
| "type <words>", "say <words>" | free-text answer |
| "skip", "undo", "next", "previous", "back" | s, u, ↓, ↑ |
| "read", "read q12", "again" | speak that row |
| "what's next", "how many" | speak due count and the next row's title |
| "done step two", "tick two" | plan step toggle |
| "stop", "cancel", "never mind" | drop the transcript, speak nothing |

Numbers accept words and digits ("two", "2", "to"/"too" only right after "pick"/"answer"). Matching is on the final transcript only, never partials.

**Interpreter** (no grammar match)
- `claude -p --model claude-haiku-4-5 --output-format json` with a fixed system prompt, the transcript, and the current row's JSON (key, text, choices, act) plus the titles of the project's other open rows. No tools.
- It must return one JSON object: `{"verb": ..., "key": ..., "selected": [...], "text": ..., "say": "..."}`. Allowed verbs: answer, skip, undo, verdict, step, read, next, previous, none.
- The app validates: verb on the list, key exists, labels are real choices. Invalid or `none` -> speak "didn't catch that" and do nothing.
- Never `retire`, `exec`, run-row approve, poke, or anything outside the list, whatever the model says.

**Confirm gate:** a command that executes something (approve on a `run` row, `R`) is never voice-driven in v1: speak "that one needs the keyboard". (fork q-confirm)

**Speaking**
- One `vsay` at a time; a new utterance kills the previous `vsay` process.
- Result first, then the next row: "Answered red. Next: q14, which storage engine. One, sqlite. Two, postgres."
- Long text: speak the title and at most four choice labels; descriptions never.
- Voice: `CACTUS_VOICE` env / app setting, default the daemon's default.
- If the daemon is down (`vsay` exits non-zero), fall back to a toast; never `say(1)` silently.

**Activation:** hold-to-talk (fork q-activation). While held the sidebar shows a listening pill with the live partial transcript; release ends it. Esc while listening cancels.

**Permissions:** first use asks for Microphone and Speech Recognition (Info.plist `NSMicrophoneUsageDescription`, `NSSpeechRecognitionUsageDescription`). Denied -> toast with the System Settings path, voice key disabled.

**Privacy:** `requiresOnDeviceRecognition = true` (fork q-ondevice). The interpreter sends the transcript and the current project's open row text to Anthropic through the user's own `claude` login; the grammar path sends nothing anywhere.

**Out of v1:** wake word, continuous listening, reading whole review/run output aloud, voice on the phone board.

**Done:** grammar unit-tested (Swift test target or a table-driven check run by `swift test`); a scripted walk feeding transcripts (no mic) through grammar -> CLI against a scratch DB; one human walk with the real mic.
