// HotKey.swift — global hotkey via Carbon's RegisterEventHotKey.
// Responsibilities:
// - Register one system-wide hotkey with no Accessibility permission needed.
// - Default to ⌃Space (kVK_Space + controlKey); read an override from
//   UserDefaults keys "hotkeyKeyCode"/"hotkeyModifiers" when present.
// - Invoke its callback on the main thread.
// - Re-register live with a new combo (`update`), persisting it to the same
//   defaults keys; `suspend`/`resume` free the combo while Settings records one.
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

    static let defaultKeyCode = UInt32(kVK_Space)
    static let defaultModifiers = UInt32(controlKey)

    /// The combo in effect: the defaults override, else ⌃Space.
    static var current: (keyCode: UInt32, modifiers: UInt32) {
        let defaults = UserDefaults.standard
        let keyCode = defaults.object(forKey: "hotkeyKeyCode") != nil
            ? UInt32(defaults.integer(forKey: "hotkeyKeyCode")) : defaultKeyCode
        let modifiers = defaults.object(forKey: "hotkeyModifiers") != nil
            ? UInt32(defaults.integer(forKey: "hotkeyModifiers")) : defaultModifiers
        return (keyCode, modifiers)
    }

    /// "⌃Space" for the combo in effect.
    static var currentLabel: String {
        describe(keyCode: current.keyCode, modifiers: current.modifiers)
    }

    /// Save a new combo and register it in place of the old one.
    func update(keyCode: UInt32, modifiers: UInt32) {
        let defaults = UserDefaults.standard
        if keyCode == Self.defaultKeyCode && modifiers == Self.defaultModifiers {
            defaults.removeObject(forKey: "hotkeyKeyCode")
            defaults.removeObject(forKey: "hotkeyModifiers")
        } else {
            defaults.set(Int(keyCode), forKey: "hotkeyKeyCode")
            defaults.set(Int(modifiers), forKey: "hotkeyModifiers")
        }
        unregister()
        register()
    }

    /// Release the combo so a key recorder can receive it.
    func suspend() {
        unregister()
    }

    /// Register the saved combo again after `suspend`.
    func resume() {
        unregister()
        register()
    }

    private func register() {
        let (keyCode, modifiers) = Self.current

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
        return out + (keyNames[Int(keyCode)] ?? "key \(keyCode)")
    }

    /// ANSI virtual key codes to labels, for the menu and Settings.
    static let keyNames: [Int: String] = {
        var names: [Int: String] = [
            kVK_Space: "Space", kVK_Return: "Return", kVK_Tab: "Tab",
            kVK_Escape: "Esc", kVK_Delete: "Delete", kVK_ForwardDelete: "⌦",
            kVK_LeftArrow: "←", kVK_RightArrow: "→", kVK_UpArrow: "↑", kVK_DownArrow: "↓",
            kVK_Home: "Home", kVK_End: "End", kVK_PageUp: "PgUp", kVK_PageDown: "PgDn",
            kVK_ANSI_Grave: "`", kVK_ANSI_Minus: "-", kVK_ANSI_Equal: "=",
            kVK_ANSI_LeftBracket: "[", kVK_ANSI_RightBracket: "]", kVK_ANSI_Backslash: "\\",
            kVK_ANSI_Semicolon: ";", kVK_ANSI_Quote: "'", kVK_ANSI_Comma: ",",
            kVK_ANSI_Period: ".", kVK_ANSI_Slash: "/",
        ]
        let letters: [(Int, String)] = [
            (kVK_ANSI_A, "A"), (kVK_ANSI_B, "B"), (kVK_ANSI_C, "C"), (kVK_ANSI_D, "D"),
            (kVK_ANSI_E, "E"), (kVK_ANSI_F, "F"), (kVK_ANSI_G, "G"), (kVK_ANSI_H, "H"),
            (kVK_ANSI_I, "I"), (kVK_ANSI_J, "J"), (kVK_ANSI_K, "K"), (kVK_ANSI_L, "L"),
            (kVK_ANSI_M, "M"), (kVK_ANSI_N, "N"), (kVK_ANSI_O, "O"), (kVK_ANSI_P, "P"),
            (kVK_ANSI_Q, "Q"), (kVK_ANSI_R, "R"), (kVK_ANSI_S, "S"), (kVK_ANSI_T, "T"),
            (kVK_ANSI_U, "U"), (kVK_ANSI_V, "V"), (kVK_ANSI_W, "W"), (kVK_ANSI_X, "X"),
            (kVK_ANSI_Y, "Y"), (kVK_ANSI_Z, "Z"),
            (kVK_ANSI_0, "0"), (kVK_ANSI_1, "1"), (kVK_ANSI_2, "2"), (kVK_ANSI_3, "3"),
            (kVK_ANSI_4, "4"), (kVK_ANSI_5, "5"), (kVK_ANSI_6, "6"), (kVK_ANSI_7, "7"),
            (kVK_ANSI_8, "8"), (kVK_ANSI_9, "9"),
        ]
        for (code, label) in letters { names[code] = label }
        let fkeys = [kVK_F1, kVK_F2, kVK_F3, kVK_F4, kVK_F5, kVK_F6, kVK_F7, kVK_F8,
                     kVK_F9, kVK_F10, kVK_F11, kVK_F12]
        for (i, code) in fkeys.enumerated() { names[code] = "F\(i + 1)" }
        return names
    }()

    /// F1-F12 may stand alone; every other key needs a modifier.
    static func isFunctionKey(_ keyCode: UInt32) -> Bool {
        (keyNames[Int(keyCode)] ?? "").range(of: "^F[0-9]+$", options: .regularExpression) != nil
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
            self.hotKeyRef = nil
        }
        if let handler {
            RemoveEventHandler(handler)
            self.handler = nil
        }
        isRegistered = false
    }
}
