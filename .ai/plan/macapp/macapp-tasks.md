# macapp — tasks

- [ ] mac/Package.swift, executable target `cactus-mac`, macOS 14+
- [ ] CactusCLI.swift: locate binary, run `feed --json`, `answer`, `clear`; decode JSON
- [ ] Model.swift: Question/Choice structs, cursor diff, poller with two intervals
- [ ] HotKey.swift: Carbon RegisterEventHotKey wrapper, default ⌥Space
- [ ] Panel.swift: nonactivating floating NSPanel, toggle, Esc/focus-loss hide
- [ ] Views.swift: SwiftUI rail + card, keys j/k/digits/Enter/s/c
- [ ] StatusItem.swift: menu-bar count, Quit menu
- [ ] `swift build` clean; `.ai/tmp/macapp_smoke.sh` posts a scratch row against CACTUS_DB and the app lists it
- [ ] REVIEW.md steps
- [ ] commit on branch macapp
