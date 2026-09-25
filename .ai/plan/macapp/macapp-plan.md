# macapp — native macOS popup for the cactus inbox

Decision q297: swift-native. A menu-bar app with a global hotkey that raises a
floating panel listing open rows and answers them.

## Shape

- SwiftPM executable target, no Xcode project, no signing, no packaging.
- Menu-bar `NSStatusItem` with the open-row count as its title.
- Global hotkey through Carbon `RegisterEventHotKey` (no Accessibility grant).
  Default `⇧Space` (q303, pending); rebindable later via UserDefaults.
- Floating `NSPanel` (`.nonactivatingPanel`, `.hudWindow`), toggles on the
  hotkey, dismisses on `Esc` or focus loss.
- Rail: one line per actionable row across all projects, `project · key · text`.
- Card: text, context, choices numbered 1-9, recommend preselected.
- Keys: `j`/`k` move, digit selects, `Enter` submits, `s` skip, `c` clear,
  `Esc` hide.

## Data path (q304)

Read: `cactus feed --json` polled every 0.5s while the panel is visible,
every 5s while hidden. Compare `cursor` before re-rendering.
Write: `cactus answer KEY --json` with `-l LABEL`, `--text`, or `--skip`;
`cactus clear KEY`. cli.py stays the only validator. Surface its stderr line
on the card when it exits non-zero.

## Out of scope for the spike

review/plan/data verdict entry, poke, free-text on choice rows, notifications,
signing, Homebrew cask, hotkey preference UI.

## Location

`mac/` inside this repo (q302, pending). Pinned to the `cactus` binary on PATH.
