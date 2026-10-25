// StatusItem.swift — the menu-bar item.
// Responsibilities:
// - Show 🌵 as the status item, followed by the count of open questions when
//   there are any.
// - Show a disabled hotkey-failure line (and the Settings hint) at the top of
//   the menu when the global hotkey could not register.
// - Provide a menu with "Show / hide (<shortcut>)" (toggles the panel), "Open
//   at login" (SMAppService.mainApp; the hotkey only works while the app
//   runs), "Settings…" and "Quit". The menu rebuilds each time it opens, so a
//   shortcut changed in Settings shows at once.

import AppKit
import Combine
import ServiceManagement

@MainActor
final class StatusItemController: NSObject, NSMenuDelegate {
    private let statusItem: NSStatusItem
    private var cancellable: AnyCancellable?
    private let hotKey: HotKey
    private let onToggle: () -> Void
    private let onSettings: () -> Void

    init(poller: Poller, hotKey: HotKey, onToggle: @escaping () -> Void, onSettings: @escaping () -> Void) {
        self.hotKey = hotKey
        self.onToggle = onToggle
        self.onSettings = onSettings
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        super.init()
        statusItem.button?.title = "🌵"

        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu
        rebuild(menu)

        cancellable = poller.$questions.sink { [weak self] questions in
            let openCount = questions.filter { $0.status == "open" }.count
            self?.statusItem.button?.title = openCount > 0 ? "🌵 \(openCount)" : "🌵"
        }
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        rebuild(menu)
    }

    private func rebuild(_ menu: NSMenu) {
        menu.removeAllItems()
        if let failure = hotKey.failure {
            let failItem = NSMenuItem(title: failure, action: nil, keyEquivalent: "")
            failItem.isEnabled = false
            menu.addItem(failItem)
            let hintItem = NSMenuItem(title: "Pick another shortcut in Settings…", action: nil, keyEquivalent: "")
            hintItem.isEnabled = false
            menu.addItem(hintItem)
            menu.addItem(NSMenuItem.separator())
        }
        let showItem = NSMenuItem(
            title: "Show / hide (\(HotKey.currentLabel))",
            action: #selector(showPressed),
            keyEquivalent: ""
        )
        showItem.target = self
        menu.addItem(showItem)

        let loginItem = NSMenuItem(title: "Open at login", action: #selector(loginPressed), keyEquivalent: "")
        loginItem.target = self
        switch SMAppService.mainApp.status {
        case .enabled:
            loginItem.state = .on
        case .requiresApproval:
            loginItem.state = .mixed
            loginItem.title = "Open at login (approve in System Settings)"
        default:
            loginItem.state = .off
        }
        menu.addItem(loginItem)

        let settingsItem = NSMenuItem(title: "Settings…", action: #selector(settingsPressed), keyEquivalent: ",")
        settingsItem.target = self
        menu.addItem(settingsItem)
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
    }

    @objc private func showPressed() {
        onToggle()
    }

    @objc private func settingsPressed() {
        onSettings()
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
        if service.status == .requiresApproval {
            SMAppService.openSystemSettingsLoginItems()
        }
    }
}
