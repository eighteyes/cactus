// Components.swift — reusable native-style pieces for the cactus panel.
// Responsibilities:
// - RailRow: kind symbol, one-line title, secondary meta line, accent pill
//   selection, orange dot on a blocking row.
// - CardHeader: kind symbol, mono key, project, age.
// - ChoiceRow: full-width rounded row, mono number badge, label, secondary
//   description, star for recommended, checkmark when picked/toggled.
// - KeycapFooter: wrapping keycap chips (mono glyph + label).
// - Toast: small capsule status message.
// - FlowLayout: left-to-right wrapping layout the footer uses.
// All text is plain strings, never Markdown.

import SwiftUI

struct RailRow: View {
    let question: Question
    let meta: String
    let isSelected: Bool

    private var isBlocking: Bool { question.status == "open" && question.blocked == true }

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: Style.symbol(for: question))
                .font(.system(size: 13))
                .foregroundStyle(isSelected ? Style.accent : Style.secondary)
                .frame(width: 18)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                Text(verbatim: question.text.replacingOccurrences(of: "\n", with: " "))
                    .font(Style.body)
                    .foregroundStyle(isSelected ? Style.accent : Style.label)
                    .lineLimit(1)
                HStack(spacing: 4) {
                    Text(verbatim: question.key).font(Style.mono(10))
                    Text(verbatim: meta).font(Style.meta)
                }
                .foregroundStyle(Style.secondary)
                .lineLimit(1)
            }
            Spacer(minLength: 0)
            if isBlocking {
                Circle()
                    .fill(Style.attention)
                    .frame(width: 7, height: 7)
                    .padding(.top, 5)
                    .help("blocking")
            }
        }
        .opacity(question.isAnswered ? 0.55 : 1)
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Style.pillRadius)
                .fill(isSelected ? Style.selection : Color.clear)
        )
        .contentShape(Rectangle())
    }
}

struct CardHeader: View {
    let question: Question

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: Style.symbol(for: question))
                .foregroundStyle(Style.accent)
            Text(verbatim: question.key)
                .font(Style.mono(11, weight: .semibold))
                .foregroundStyle(Style.label)
            Text(verbatim: question.projectBasename)
                .lineLimit(1)
            if let age = Style.age(question.updatedAt) {
                Text("·")
                Text(verbatim: age)
            }
            Spacer(minLength: 0)
            if question.status == "open" && question.blocked == true {
                Text("blocking")
                    .font(Style.metaStrong)
                    .foregroundStyle(Style.attention)
            }
        }
        .font(Style.meta)
        .foregroundStyle(Style.secondary)
    }
}

struct ChoiceRow: View {
    let number: Int
    let label: String
    let description: String
    let isRecommended: Bool
    let isPicked: Bool
    let isMulti: Bool
    let onTap: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Text("\(number)")
                .font(Style.mono(11, weight: .semibold))
                .foregroundStyle(isPicked ? Color.black : Style.label)
                .frame(width: 20, height: 20)
                .background(
                    RoundedRectangle(cornerRadius: 5)
                        .fill(isPicked ? Style.accent : Style.fillHover)
                )
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 5) {
                    Text(verbatim: label)
                        .font(Style.bodyStrong)
                        .foregroundStyle(Style.label)
                    if isRecommended {
                        Image(systemName: "star.fill")
                            .font(.system(size: 10))
                            .foregroundStyle(Style.accent)
                            .help("recommended")
                    }
                }
                if !description.isEmpty {
                    Text(verbatim: description)
                        .font(Style.meta)
                        .foregroundStyle(Style.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 0)
            if isPicked {
                Image(systemName: isMulti ? "checkmark.square.fill" : "checkmark")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Style.accent)
                    .padding(.top, 3)
            } else if isMulti {
                Image(systemName: "square")
                    .font(.system(size: 12))
                    .foregroundStyle(Style.tertiary)
                    .padding(.top, 3)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Style.choiceRadius)
                .fill(isPicked ? Style.accent.opacity(0.12) : Style.fill)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Style.choiceRadius)
                .stroke(isPicked ? Style.accent.opacity(0.5) : Color.clear, lineWidth: 1)
        )
        .contentShape(Rectangle())
        .onTapGesture(perform: onTap)
    }
}

struct KeycapFooter: View {
    /// (glyph, label) pairs, e.g. ("enter", "submit").
    let items: [(String, String)]

    var body: some View {
        FlowLayout(spacing: 6, lineSpacing: 6) {
            ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                HStack(spacing: 4) {
                    Text(verbatim: glyph(item.0))
                        .font(Style.mono(10, weight: .semibold))
                        .foregroundStyle(Style.label)
                        .padding(.horizontal, 5)
                        .frame(minWidth: 18, minHeight: 17)
                        .background(
                            RoundedRectangle(cornerRadius: 4)
                                .fill(Style.fillHover)
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 4)
                                .stroke(Style.separator, lineWidth: 1)
                        )
                    Text(verbatim: item.1)
                        .font(Style.meta)
                        .foregroundStyle(Style.secondary)
                }
                .fixedSize()
            }
        }
    }

    /// Mac keycap glyphs for the named keys; the rest pass through.
    private func glyph(_ key: String) -> String {
        switch key {
        case "enter": return "↩"
        case "esc": return "esc"
        case "tab": return "⇥"
        case "j/k/tab": return "j k ⇥"
        case "j/k": return "j k"
        default: return key
        }
    }
}

struct Toast: View {
    let message: String
    var isError = false

    var body: some View {
        Text(verbatim: message)
            .font(Style.meta)
            .foregroundStyle(isError ? Style.error : Style.label)
            .lineLimit(2)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(Capsule().fill(Color.black.opacity(0.55)))
            .overlay(Capsule().stroke(Style.separator, lineWidth: 1))
    }
}

/// Lays children left to right, wrapping to a new line when the width runs out.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6
    var lineSpacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(width: proposal.width ?? .infinity, subviews: subviews)
        let height = rows.map(\.height).reduce(0, +) + lineSpacing * CGFloat(max(rows.count - 1, 0))
        let width = rows.map(\.width).max() ?? 0
        return CGSize(width: proposal.width ?? width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(width: bounds.width, subviews: subviews) {
            var x = bounds.minX
            for index in row.indices {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(at: CGPoint(x: x, y: y + (row.height - size.height) / 2),
                                      proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + lineSpacing
        }
    }

    private struct Row {
        var indices: [Int] = []
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    private func arrange(width: CGFloat, subviews: Subviews) -> [Row] {
        var rows: [Row] = []
        var current = Row()
        for index in subviews.indices {
            let size = subviews[index].sizeThatFits(.unspecified)
            let needed = current.indices.isEmpty ? size.width : current.width + spacing + size.width
            if needed > width && !current.indices.isEmpty {
                rows.append(current)
                current = Row()
            }
            current.width = current.indices.isEmpty ? size.width : current.width + spacing + size.width
            current.height = max(current.height, size.height)
            current.indices.append(index)
        }
        if !current.indices.isEmpty { rows.append(current) }
        return rows
    }
}
