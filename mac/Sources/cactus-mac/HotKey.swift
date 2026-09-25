// HotKey.swift — global hotkey via Carbon's RegisterEventHotKey.
// Responsibilities:
// - Register one system-wide hotkey with no Accessibility permission needed.
// - Default to ⇧Space (kVK_Space + shiftKey); read an override from
//   UserDefaults keys "hotkeyKeyCode"/"hotkeyModifiers" when present.
// - Invoke its callback on the main thread.

import Carbon
import Foundation

final class HotKey {
    private var hotKeyRef: EventHotKeyRef?
    private var handler: EventHandlerRef?
    private let callback: () -> Void
    private let hotKeyID = EventHotKeyID(signature: OSType(0x6361_6374), id: 1) // 'cact'

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
            : UInt32(shiftKey)

        var eventType = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind: UInt32(kEventHotKeyPressed)
        )

        let selfPtr = Unmanaged.passUnretained(self).toOpaque()
        InstallEventHandler(
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

        RegisterEventHotKey(
            keyCode,
            modifiers,
            hotKeyID,
            GetApplicationEventTarget(),
            0,
            &hotKeyRef
        )
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
