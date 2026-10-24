// StatusItem.swift — the menu-bar item.
// Responsibilities:
// - Show the count of open questions as the status item's title, blank when
//   zero.
// - Show a disabled hotkey-failure line (and the defaults override hint) at the
//   top of the menu when the global hotkey could not register.
// - Provide a menu with "Show / hide (⌃Space)" (toggles the panel) and "Quit".

import AppKit
import Combine

@MainActor
final class StatusItemController {
    private let statusItem: NSStatusItem
    private var cancellable: AnyCancellable?
    private let onToggle: () -> Void

    init(poller: Poller, hotKeyFailure: String? = nil, onToggle: @escaping () -> Void) {
        self.onToggle = onToggle
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = ""

        let menu = NSMenu()
        if let hotKeyFailure {
            let failItem = NSMenuItem(title: hotKeyFailure, action: nil, keyEquivalent: "")
            failItem.isEnabled = false
            menu.addItem(failItem)
            let hintItem = NSMenuItem(
                title: "Override: defaults write ai.cactus.mac hotkeyKeyCode/hotkeyModifiers",
                action: nil,
                keyEquivalent: ""
            )
            hintItem.isEnabled = false
            menu.addItem(hintItem)
            menu.addItem(NSMenuItem.separator())
        }
        let showItem = NSMenuItem(
            title: "Show / hide (⌃Space)",
            action: #selector(showPressed),
            keyEquivalent: ""
        )
        showItem.target = self
        menu.addItem(showItem)
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        statusItem.menu = menu

        cancellable = poller.$questions.sink { [weak self] questions in
            let openCount = questions.filter { $0.status == "open" }.count
            self?.statusItem.button?.title = openCount > 0 ? "\(openCount)" : ""
        }
    }

    @objc private func showPressed() {
        onToggle()
    }
}
