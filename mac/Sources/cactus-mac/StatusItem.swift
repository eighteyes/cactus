// StatusItem.swift — the menu-bar item.
// Responsibilities:
// - Show the count of open questions as the status item's title, blank when
//   zero.
// - Show a disabled hotkey-failure line (and the defaults override hint) at the
//   top of the menu when the global hotkey could not register.
// - Provide a menu with "Show / hide (⌃Space)" (toggles the panel), "Open at
//   login" (SMAppService.mainApp; the hotkey only works while the app runs),
//   and "Quit".

import AppKit
import Combine
import ServiceManagement

@MainActor
final class StatusItemController {
    private let statusItem: NSStatusItem
    private var cancellable: AnyCancellable?
    private let onToggle: () -> Void
    private let loginItem = NSMenuItem(title: "Open at login", action: #selector(loginPressed), keyEquivalent: "")

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
        loginItem.target = self
        menu.addItem(loginItem)
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        statusItem.menu = menu
        refreshLoginItem()

        cancellable = poller.$questions.sink { [weak self] questions in
            let openCount = questions.filter { $0.status == "open" }.count
            self?.statusItem.button?.title = openCount > 0 ? "\(openCount)" : ""
        }
    }

    @objc private func showPressed() {
        onToggle()
    }

    @objc private func loginPressed() {
        let service = SMAppService.mainApp
        do {
            if service.status == .enabled || service.status == .requiresApproval {
                try service.unregister()
            } else {
                try service.register()
            }
        } catch {
            FileHandle.standardError.write(Data("cactus-mac: open at login: \(error.localizedDescription)\n".utf8))
        }
        refreshLoginItem()
        if service.status == .requiresApproval {
            SMAppService.openSystemSettingsLoginItems()
        }
    }

    private func refreshLoginItem() {
        switch SMAppService.mainApp.status {
        case .enabled:
            loginItem.state = .on
            loginItem.title = "Open at login"
        case .requiresApproval:
            loginItem.state = .mixed
            loginItem.title = "Open at login (approve in System Settings)"
        default:
            loginItem.state = .off
            loginItem.title = "Open at login"
        }
    }
}
