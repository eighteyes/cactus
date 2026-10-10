// Style.swift — design tokens for the native, forced-dark cactus sidebar.
// Responsibilities:
// - Colours: cactus green accent (from assets/icon-1024.png), orange for
//   blocking/attention, label/secondary/fill levels over the sidebar material.
// - Type: SF Pro sizes (question 15 semibold, body 13, meta 11), SF Mono for
//   keys, commands and code.
// - Radii (pill 6, choice 8, panel 12) and the SF Symbol per row kind.
// - The behind-window `.sidebar` material view the panel hosts its UI in,
//   with rounded leading corners.
// - Relative age text from a store timestamp.

import AppKit
import SwiftUI

enum Style {
    // MARK: colour
    static let accent = Color(hex: 0x6AE0A8)       // the icon's cactus green
    static let attention = Color(hex: 0xFF9F0A)    // system orange, dark
    static let label = Color.white.opacity(0.88)
    static let secondary = Color.white.opacity(0.55)
    static let tertiary = Color.white.opacity(0.35)
    static let fill = Color.white.opacity(0.06)
    static let fillHover = Color.white.opacity(0.10)
    static let separator = Color.white.opacity(0.08)
    static let selection = accent.opacity(0.25)
    static let error = Color(hex: 0xFF6961)

    // MARK: type
    static let question = Font.system(size: 15, weight: .semibold)
    static let body = Font.system(size: 13)
    static let bodyStrong = Font.system(size: 13, weight: .medium)
    static let meta = Font.system(size: 11)
    static let metaStrong = Font.system(size: 11, weight: .semibold)
    static func mono(_ size: CGFloat = 12, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }

    // MARK: geometry
    static let pillRadius: CGFloat = 6
    static let choiceRadius: CGFloat = 8
    static let panelRadius: CGFloat = 12

    /// SF Symbol for a row: act first (review, plan, run), then answer shape.
    static func symbol(for q: Question) -> String {
        switch q.act {
        case "review": return "checkmark.seal"
        case "plan": return "list.number"
        case "run": return "terminal"
        default: break
        }
        switch q.kind {
        case "multi": return "checklist"
        case "text": return "text.cursor"
        case "confirm": return "questionmark.circle"
        default: return q.choices.isEmpty ? "text.cursor" : "list.bullet"
        }
    }

    /// `5m`, `3h`, `2d` since a store timestamp (`2026-10-09T12:34:56.123456+00:00`).
    static func age(_ timestamp: String?, now: Date = Date()) -> String? {
        guard let timestamp, timestamp.count >= 19 else { return nil }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        guard let date = formatter.date(from: String(timestamp.prefix(19))) else { return nil }
        let seconds = max(0, Int(now.timeIntervalSince(date)))
        if seconds < 60 { return "now" }
        if seconds < 3600 { return "\(seconds / 60)m" }
        if seconds < 86400 { return "\(seconds / 3600)h" }
        return "\(seconds / 86400)d"
    }

    /// The panel's root view: behind-window `.sidebar` material, forced dark,
    /// leading (left) corners rounded, hosting `content` on top.
    static func sidebarBackground(hosting content: NSView) -> NSView {
        let effect = NSVisualEffectView()
        effect.material = .sidebar
        effect.blendingMode = .behindWindow
        effect.state = .active
        effect.appearance = NSAppearance(named: .darkAqua)
        effect.maskImage = leadingCornerMask(radius: panelRadius)
        content.translatesAutoresizingMaskIntoConstraints = false
        effect.addSubview(content)
        NSLayoutConstraint.activate([
            content.leadingAnchor.constraint(equalTo: effect.leadingAnchor),
            content.trailingAnchor.constraint(equalTo: effect.trailingAnchor),
            content.topAnchor.constraint(equalTo: effect.topAnchor),
            content.bottomAnchor.constraint(equalTo: effect.bottomAnchor),
        ])
        return effect
    }

    /// A stretchable mask: left corners rounded, right edge square (it meets
    /// the screen edge).
    private static func leadingCornerMask(radius: CGFloat) -> NSImage {
        let edge = radius * 2 + 1
        let image = NSImage(size: NSSize(width: edge, height: edge), flipped: false) { rect in
            let path = NSBezierPath()
            path.move(to: NSPoint(x: rect.maxX, y: rect.minY))
            path.line(to: NSPoint(x: rect.maxX, y: rect.maxY))
            path.line(to: NSPoint(x: rect.minX + radius, y: rect.maxY))
            path.appendArc(withCenter: NSPoint(x: rect.minX + radius, y: rect.maxY - radius),
                           radius: radius, startAngle: 90, endAngle: 180)
            path.line(to: NSPoint(x: rect.minX, y: rect.minY + radius))
            path.appendArc(withCenter: NSPoint(x: rect.minX + radius, y: rect.minY + radius),
                           radius: radius, startAngle: 180, endAngle: 270)
            path.close()
            NSColor.black.setFill()
            path.fill()
            return true
        }
        image.capInsets = NSEdgeInsets(top: radius, left: radius, bottom: radius, right: radius)
        image.resizingMode = .stretch
        return image
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255
        )
    }
}
