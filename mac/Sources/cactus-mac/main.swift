// main.swift — application entry point.
// Responsibilities:
// - Bootstrap NSApplication as a menu-bar-only (.accessory) app, no Dock icon.
// - Own the long-lived pieces: CactusCLI, Poller, the floating Panel, the
//   global HotKey, and the StatusItem, wiring them together.
// - Run the app.

import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let cli = CactusCLI()
    private var poller: Poller!
    private var panel: CactusPanel!
    private var hotKey: HotKey!
    private var statusItemController: StatusItemController!

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let poller = Poller(cli: cli)
        self.poller = poller

        let contentView = ContentView(poller: poller, cli: cli) { [weak self] in
            self?.panel.orderOut(nil)
        }
        let panel = CactusPanel(rootView: contentView)
        panel.onVisibilityChange = { [weak poller] visible in
            poller?.setVisible(visible)
        }
        self.panel = panel

        hotKey = HotKey { [weak panel] in
            panel?.toggle()
        }

        statusItemController = StatusItemController(poller: poller) { [weak panel] in
            panel?.toggle()
        }

        poller.setVisible(false)
    }
}

let delegate = AppDelegate()
let app = NSApplication.shared
app.delegate = delegate
app.run()
