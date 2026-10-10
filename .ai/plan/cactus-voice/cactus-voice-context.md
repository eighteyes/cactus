# cactus-voice context

**Key files**
- mac/Sources/cactus-mac/: HotKey.swift (Carbon global hotkey, ⌃Space), Panel.swift (sidebar, focus restore), Views.swift (handleKeyPress, row actions), CactusCLI.swift (every cactus call, off main thread, login-shell PATH), Components.swift (Toast, pills).
- scripts/build-mac-app.sh + mac/Resources/Info.plist.in: usage strings go here.
- vsay: ~/.local/bin/vsay -> voice-to-ass; `vsay [-v VOICE] <text|->`, socket /tmp/voice-to-ass.sock, exit non-zero when the daemon is down.
- claude CLI: ~/.local/bin/claude (shell alias adds opus/auto flags; the app must call the binary directly with its own flags).

**Decisions**
- Host is Cactus.app: SFSpeechRecognizer is Swift-only, and the app already holds the hotkey, current row and CLI path.
- Grammar first, model second: the common answers cost nothing and send nothing off the machine.
- The interpreter returns data, never a shell command; the app maps it onto the same calls the keys use, so every refusal (ownership, no-free, cleared) still comes from cli.py.
- Executing actions stay keyboard-only in v1.
