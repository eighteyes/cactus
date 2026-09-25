// Panel.swift — the floating, non-activating window that hosts the rail+card UI.
// Responsibilities:
// - An NSPanel styled as a HUD: nonactivating, floating, titleless, key-able.
// - toggle() shows/hides it, centered on the screen under the mouse pointer.
// - Hide on Esc and on losing key status, so it behaves like a popover.

import AppKit
import SwiftUI

final class CactusPanel: NSPanel {
    var onVisibilityChange: ((Bool) -> Void)?

    convenience init<Content: View>(rootView: Content) {
        self.init(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 360),
            styleMask: [.nonactivatingPanel, .hudWindow, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
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

    override func resignKey() {
        super.resignKey()
        hidePanel()
    }

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
    }

    private func hidePanel() {
        orderOut(nil)
        onVisibilityChange?(false)
    }

    private func screenUnderMouse() -> NSScreen? {
        let mouseLocation = NSEvent.mouseLocation
        return NSScreen.screens.first { NSMouseInRect(mouseLocation, $0.frame, false) }
            ?? NSScreen.main
    }
}
