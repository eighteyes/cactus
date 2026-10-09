// Panel.swift — the floating, non-activating window that hosts the rail+card UI.
// Responsibilities:
// - An NSPanel styled like the TUI (dark, no HUD material): nonactivating, floating, titleless, key-able.
// - toggle() shows/hides it, centered on the screen under the mouse pointer.
// - Hide on Esc, and (via AppDelegate) when another app becomes active —
//   never on a bare key-status change, which a focus shuffle inside the panel
//   can trigger.
// - Post panelShown/panelHidden so the view can reset its typing mode.

import AppKit
import SwiftUI

extension Notification.Name {
    static let cactusPanelShown = Notification.Name("cactusPanelShown")
    static let cactusPanelHidden = Notification.Name("cactusPanelHidden")
}

final class CactusPanel: NSPanel {
    var onVisibilityChange: ((Bool) -> Void)?

    convenience init<Content: View>(rootView: Content) {
        self.init(
            contentRect: NSRect(x: 0, y: 0, width: 800, height: 460),
            styleMask: [.nonactivatingPanel, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        self.backgroundColor = NSColor(red: 0x12 / 255, green: 0x12 / 255, blue: 0x12 / 255, alpha: 1)
        self.appearance = NSAppearance(named: .darkAqua)
        self.titleVisibility = .hidden
        self.titlebarAppearsTransparent = true
        self.isMovableByWindowBackground = true
        self.level = .floating
        self.hidesOnDeactivate = false
        self.isReleasedWhenClosed = false
        self.contentView = NSHostingView(rootView: rootView)
    }

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    override func cancelOperation(_ sender: Any?) {
        // Esc.
        hidePanel()
    }

    /// Show, centered on the screen holding the mouse pointer, and make key.
    func toggle() {
        if isVisible {
            hidePanel()
        } else {
            showPanel()
        }
    }

    private func showPanel() {
        if let screen = screenUnderMouse() {
            let frame = frame
            let x = screen.frame.midX - frame.width / 2
            let y = screen.frame.midY - frame.height / 2
            setFrameOrigin(NSPoint(x: x, y: y))
        }
        NSApp.activate(ignoringOtherApps: true)
        makeKeyAndOrderFront(nil)
        onVisibilityChange?(true)
        NotificationCenter.default.post(name: .cactusPanelShown, object: self)
    }

    func hidePanel() {
        guard isVisible else { return }
        orderOut(nil)
        // Hand activation back to the app behind, so typing resumes there.
        if NSApp.isActive { NSApp.hide(nil) }
        onVisibilityChange?(false)
        NotificationCenter.default.post(name: .cactusPanelHidden, object: self)
    }

    private func screenUnderMouse() -> NSScreen? {
        let mouseLocation = NSEvent.mouseLocation
        return NSScreen.screens.first { NSMouseInRect(mouseLocation, $0.frame, false) }
            ?? NSScreen.main
    }
}
