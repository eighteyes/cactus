// main.swift — application entry point.
// Responsibilities:
// - Bootstrap NSApplication as a menu-bar-only (.accessory) app, no Dock icon.
// - Own the long-lived pieces: CactusCLI, Poller, the floating Panel, the
//   global HotKey, the StatusItem and the Settings window, wiring them together.
// - The sidebar stays up when another app becomes active; hotkey, status
//   menu and Esc all toggle/hide it through CactusPanel.
// - Run the app.

import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let cli = CactusCLI()
    private var poller: Poller!
    private var panel: CactusPanel!
    private var hotKey: HotKey!
    private var statusItemController: StatusItemController!
    private var settings: SettingsWindowController!

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let poller = Poller(cli: cli)
        self.poller = poller

        let contentView = ContentView(poller: poller, cli: cli) { [weak self] in
            self?.panel.hidePanel()
        }
        let panel = CactusPanel(rootView: contentView)
        panel.onVisibilityChange = { [weak poller] visible in
            poller?.setVisible(visible)
        }
        self.panel = panel

        hotKey = HotKey { [weak panel] in
            panel?.toggle()
        }

        settings = SettingsWindowController(hotKey: hotKey)

        statusItemController = StatusItemController(
            poller: poller,
            hotKey: hotKey,
            onToggle: { [weak panel] in panel?.toggle() },
            onSettings: { [weak self] in self?.settings.show() }
        )

        poller.setVisible(false)
    }
}

let delegate = AppDelegate()
let app = NSApplication.shared
app.delegate = delegate
app.run()
