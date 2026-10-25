// SettingsWindow.swift — the Settings window (menu bar → Settings…, ⌘,).
// Responsibilities:
// - Record a new global shortcut: click the field, press a combo, Esc cancels.
//   Needs a modifier unless the key is F1-F12. The hotkey is suspended while
//   recording so the old combo reaches the recorder instead of the panel.
// - Apply it live through HotKey.update and show the result (or why it failed).
// - Reset to ⌃Space.

import AppKit
import Carbon
import SwiftUI

@MainActor
final class SettingsModel: ObservableObject {
    @Published var label = HotKey.currentLabel
    @Published var recording = false
    @Published var message: String?

    private let hotKey: HotKey
    private var monitor: Any?

    init(hotKey: HotKey) {
        self.hotKey = hotKey
        message = hotKey.failure
    }

    func startRecording() {
        guard !recording else { return }
        recording = true
        message = "Press the new shortcut. Esc cancels."
        hotKey.suspend()
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            self?.handle(event)
            return nil
        }
    }

    func reset() {
        stopRecording()
        apply(keyCode: HotKey.defaultKeyCode, modifiers: HotKey.defaultModifiers)
    }

    private func handle(_ event: NSEvent) {
        let keyCode = UInt32(event.keyCode)
        let flags = event.modifierFlags
        var modifiers: UInt32 = 0
        if flags.contains(.control) { modifiers |= UInt32(controlKey) }
        if flags.contains(.option) { modifiers |= UInt32(optionKey) }
        if flags.contains(.shift) { modifiers |= UInt32(shiftKey) }
        if flags.contains(.command) { modifiers |= UInt32(cmdKey) }

        if keyCode == UInt32(kVK_Escape) && modifiers == 0 {
            stopRecording()
            hotKey.resume()
            message = hotKey.failure
            return
        }
        let onlyShift = modifiers == UInt32(shiftKey)
        if (modifiers == 0 || onlyShift) && !HotKey.isFunctionKey(keyCode) {
            message = "Add ⌃, ⌥ or ⌘ (or use F1-F12)."
            return
        }
        stopRecording()
        apply(keyCode: keyCode, modifiers: modifiers)
    }

    private func apply(keyCode: UInt32, modifiers: UInt32) {
        hotKey.update(keyCode: keyCode, modifiers: modifiers)
        label = HotKey.currentLabel
        message = hotKey.failure ?? "Saved. \(label) toggles the panel."
    }

    private func stopRecording() {
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
        recording = false
    }

    func windowClosed() {
        if recording {
            stopRecording()
            hotKey.resume()
        }
    }
}

struct SettingsView: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Shortcut").font(.headline)
            HStack {
                Button(action: model.startRecording) {
                    Text(model.recording ? "Recording…" : model.label)
                        .frame(minWidth: 140)
                }
                Button("Reset to ⌃Space", action: model.reset)
            }
            Text(model.message ?? "Click the shortcut to change it.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(20)
        .frame(width: 340, alignment: .leading)
    }
}

@MainActor
final class SettingsWindowController: NSObject, NSWindowDelegate {
    private let model: SettingsModel
    private var window: NSWindow?

    init(hotKey: HotKey) {
        model = SettingsModel(hotKey: hotKey)
    }

    func show() {
        if window == nil {
            let w = NSWindow(contentViewController: NSHostingController(rootView: SettingsView(model: model)))
            w.title = "Cactus Settings"
            w.styleMask = [.titled, .closable]
            w.isReleasedWhenClosed = false
            w.delegate = self
            w.center()
            window = w
        }
        model.label = HotKey.currentLabel
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }

    func windowWillClose(_ notification: Notification) {
        model.windowClosed()
    }
}
