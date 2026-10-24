// HotKey.swift — global hotkey via Carbon's RegisterEventHotKey.
// Responsibilities:
// - Register one system-wide hotkey with no Accessibility permission needed.
// - Default to ⌃Space (kVK_Space + controlKey); read an override from
//   UserDefaults keys "hotkeyKeyCode"/"hotkeyModifiers" when present.
// - Invoke its callback on the main thread.
// - Keep the OSStatus of both Carbon calls: expose `isRegistered` and a human
//   `failure` string (key rendered from the real keyCode/modifiers), and log
//   a failure to stderr.

import Carbon
import Foundation

final class HotKey {
    private var hotKeyRef: EventHotKeyRef?
    private var handler: EventHandlerRef?
    private let callback: () -> Void
    private let hotKeyID = EventHotKeyID(signature: OSType(0x6361_6374), id: 1) // 'cact'

    /// True when both the event handler and the hotkey registered.
    private(set) var isRegistered = false
    /// Human-readable reason registration failed, nil when it succeeded.
    private(set) var failure: String?

    init(callback: @escaping () -> Void) {
        self.callback = callback
        register()
    }

    deinit {
        unregister()
    }

    private func register() {
        let defaults = UserDefaults.standard
        let keyCode: UInt32 = defaults.object(forKey: "hotkeyKeyCode") != nil
            ? UInt32(defaults.integer(forKey: "hotkeyKeyCode"))
            : UInt32(kVK_Space)
        let modifiers: UInt32 = defaults.object(forKey: "hotkeyModifiers") != nil
            ? UInt32(defaults.integer(forKey: "hotkeyModifiers"))
            : UInt32(controlKey)

        var eventType = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind: UInt32(kEventHotKeyPressed)
        )

        let selfPtr = Unmanaged.passUnretained(self).toOpaque()
        let installStatus = InstallEventHandler(
            GetApplicationEventTarget(),
            { _, eventRef, userData in
                guard let userData, let eventRef else { return noErr }
                var receivedID = EventHotKeyID()
                GetEventParameter(
                    eventRef,
                    EventParamName(kEventParamDirectObject),
                    EventParamType(typeEventHotKeyID),
                    nil,
                    MemoryLayout<EventHotKeyID>.size,
                    nil,
                    &receivedID
                )
                let hotKey = Unmanaged<HotKey>.fromOpaque(userData).takeUnretainedValue()
                if receivedID.id == hotKey.hotKeyID.id {
                    DispatchQueue.main.async {
                        hotKey.callback()
                    }
                }
                return noErr
            },
            1,
            &eventType,
            selfPtr,
            &handler
        )

        let registerStatus = RegisterEventHotKey(
            keyCode,
            modifiers,
            hotKeyID,
            GetApplicationEventTarget(),
            0,
            &hotKeyRef
        )

        failure = Self.failureMessage(
            installStatus: installStatus,
            registerStatus: registerStatus,
            keyCode: keyCode,
            modifiers: modifiers
        )
        isRegistered = failure == nil
        if let failure {
            FileHandle.standardError.write(Data("cactus-mac: hotkey: \(failure)\n".utf8))
        }
    }

    /// Render a key combo like "⌃Space" from Carbon modifiers and a virtual key code.
    static func describe(keyCode: UInt32, modifiers: UInt32) -> String {
        var out = ""
        if modifiers & UInt32(controlKey) != 0 { out += "⌃" }
        if modifiers & UInt32(optionKey) != 0 { out += "⌥" }
        if modifiers & UInt32(shiftKey) != 0 { out += "⇧" }
        if modifiers & UInt32(cmdKey) != 0 { out += "⌘" }
        let names: [Int: String] = [
            kVK_Space: "Space", kVK_Return: "Return", kVK_Tab: "Tab",
            kVK_Escape: "Esc", kVK_Delete: "Delete",
        ]
        return out + (names[Int(keyCode)] ?? "key \(keyCode)")
    }

    /// Failure text for the two Carbon statuses, nil when both are noErr.
    static func failureMessage(installStatus: OSStatus, registerStatus: OSStatus,
                               keyCode: UInt32, modifiers: UInt32) -> String? {
        let combo = describe(keyCode: keyCode, modifiers: modifiers)
        if installStatus != noErr {
            return "\(combo) handler not installed (\(installStatus))"
        }
        if registerStatus == OSStatus(eventHotKeyExistsErr) {
            return "\(combo) is taken by another app (\(registerStatus))"
        }
        if registerStatus != noErr {
            return "\(combo) could not be registered (\(registerStatus))"
        }
        return nil
    }

    private func unregister() {
        if let hotKeyRef {
            UnregisterEventHotKey(hotKeyRef)
        }
        if let handler {
            RemoveEventHandler(handler)
        }
    }
}
