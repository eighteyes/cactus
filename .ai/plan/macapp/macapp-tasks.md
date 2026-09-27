# macapp — tasks

- [x] mac/Package.swift, executable target `cactus-mac`, macOS 14+
- [x] CactusCLI.swift: locate binary, run `feed --json`, `answer`, `clear`; decode JSON
- [x] Model.swift: Question/Choice structs, cursor diff, poller with two intervals
- [x] HotKey.swift: Carbon RegisterEventHotKey wrapper, default ⇧Space
- [x] Panel.swift: nonactivating floating NSPanel, toggle, Esc/focus-loss hide
- [x] Views.swift: SwiftUI rail + card, keys j/k/digits/Enter/s/c
- [x] StatusItem.swift: menu-bar count, Quit menu
- [x] `swift build` clean; `.ai/tmp/macapp_smoke.sh` posts a scratch row against CACTUS_DB and the app lists it
- [x] REVIEW.md steps
- [x] commit on branch macapp
