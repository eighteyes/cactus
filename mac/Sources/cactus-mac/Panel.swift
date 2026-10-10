// Panel.swift — the floating, non-activating sidebar that hosts the rail+card UI.
// Responsibilities:
// - An NSPanel styled like the TUI (dark, no HUD material): nonactivating, floating, titleless, key-able,
//   joins every Space.
// - Dock to the right edge of the screen under the mouse: full visibleFrame
//   height (menu bar and Dock respected), `width` points wide; slide in/out,
//   no slide under Reduce Motion.
// - toggle() is a three-state hotkey: hidden -> slide in and take key focus;
//   shown but another app active -> take key focus; shown and focused -> hide.
// - Remember the frontmost app when taking focus and reactivate it on hide,
//   unless the user already switched apps themselves.
// - Esc hides (the view handles the text field's Esc first). It stays visible
//   when another app becomes active.
// - Post panelShown/panelHidden so the view can reset its typing mode.

import AppKit
import SwiftUI

extension Notification.Name {
    static let cactusPanelShown = Notification.Name("cactusPanelShown")
    static let cactusPanelHidden = Notification.Name("cactusPanelHidden")
}

final class CactusPanel: NSPanel {
    var onVisibilityChange: ((Bool) -> Void)?

    /// Sidebar width in points.
    let width: CGFloat = 420
    private let slideDuration: TimeInterval = 0.15
    /// The app that was frontmost when the panel last took focus.
    private var previousApp: NSRunningApplication?
    private var hiding = false

    convenience init<Content: View>(rootView: Content) {
        self.init(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 800),
            styleMask: [.nonactivatingPanel, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        self.backgroundColor = NSColor(red: 0x12 / 255, green: 0x12 / 255, blue: 0x12 / 255, alpha: 1)
        self.appearance = NSAppearance(named: .darkAqua)
        self.titleVisibility = .hidden
        self.titlebarAppearsTransparent = true
        self.isMovable = false
        self.level = .floating
        self.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
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

    /// Visible, key, and the app active: keys typed now land here.
    private var isFocused: Bool { isVisible && isKeyWindow && NSApp.isActive }

    func toggle() {
        if !isVisible || hiding {
            showPanel()
        } else if !isFocused {
            takeFocus()
        } else {
            hidePanel()
        }
    }

    private func showPanel() {
        hiding = false
        let screen = screenUnderMouse()
        let shown = dockedFrame(on: screen)
        var start = shown
        start.origin.x = shown.maxX
        if reduceMotion {
            setFrame(shown, display: true)
        } else {
            setFrame(isVisible ? frame : start, display: false)
        }
        takeFocus()
        onVisibilityChange?(true)
        NotificationCenter.default.post(name: .cactusPanelShown, object: self)
        if !reduceMotion {
            NSAnimationContext.runAnimationGroup { context in
                context.duration = slideDuration
                context.timingFunction = CAMediaTimingFunction(name: .easeOut)
                animator().setFrame(shown, display: true)
            }
        }
    }

    private func takeFocus() {
        if let front = NSWorkspace.shared.frontmostApplication,
           front != NSRunningApplication.current {
            previousApp = front
        }
        NSApp.activate(ignoringOtherApps: true)
        makeKeyAndOrderFront(nil)
    }

    func hidePanel() {
        guard isVisible, !hiding else { return }
        // Still active means the user never left: hand focus back. Otherwise
        // they already switched apps, so leave focus where it is.
        // Esc, the status menu and the hotkey all hide through here.
        if NSApp.isActive {
            if let previousApp, previousApp.activate() {
            } else {
                NSApp.deactivate()
            }
        }
        previousApp = nil
        onVisibilityChange?(false)
        NotificationCenter.default.post(name: .cactusPanelHidden, object: self)
        if reduceMotion {
            orderOut(nil)
            return
        }
        hiding = true
        var end = frame
        end.origin.x = frame.maxX
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = slideDuration
            context.timingFunction = CAMediaTimingFunction(name: .easeIn)
            animator().setFrame(end, display: true)
        }, completionHandler: { [weak self] in
            guard let self, self.hiding else { return }
            self.hiding = false
            self.orderOut(nil)
        })
    }

    private var reduceMotion: Bool {
        NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    }

    private func dockedFrame(on screen: NSScreen?) -> NSRect {
        guard let visible = screen?.visibleFrame else { return frame }
        return NSRect(x: visible.maxX - width, y: visible.minY, width: width, height: visible.height)
    }

    private func screenUnderMouse() -> NSScreen? {
        let mouseLocation = NSEvent.mouseLocation
        return NSScreen.screens.first { NSMouseInRect(mouseLocation, $0.frame, false) }
            ?? NSScreen.main
    }
}
