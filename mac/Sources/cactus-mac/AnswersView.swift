// AnswersView.swift — the answers view (TUI `a`), a list screen in the sidebar.
// Responsibilities:
// - Render one project's history (`cactus history`) newest verdict first:
//   key, verdict column, question text; the selected line takes the accent
//   pill and, when expanded, shows full text, context and every verdict.
// - Verdict column: the latest answer's `label — text`, except a cleared
//   row always reads `cleared` (the TUI rule).
// - Pure view: selection, expansion, rotation and loading stay in ContentView.

import SwiftUI

struct AnswersView: View {
    let project: String?
    let rows: [Question]
    let selected: Int
    let expanded: String?
    let loading: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            PageHeader(title: "Answers · " + ((project as NSString?)?.lastPathComponent ?? "—"),
                       detail: "[ ] project")
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 2) {
                        ForEach(Array(rows.enumerated()), id: \.element.id) { index, q in
                            line(q, isSelected: index == selected)
                                .id(q.id)
                        }
                        if rows.isEmpty {
                            Text(loading ? "Loading…" : "No answers in this project")
                                .foregroundStyle(Style.secondary)
                                .padding(10)
                        }
                    }
                    .padding(.horizontal, 10)
                    .padding(.bottom, 8)
                }
                .onChange(of: selected) { _, _ in
                    if rows.indices.contains(selected) { proxy.scrollTo(rows[selected].id) }
                }
            }
        }
    }

    static func verdict(_ q: Question) -> String {
        if q.status == "cleared" { return "cleared" }
        return q.answers.last?.summary ?? ""
    }

    private func line(_ q: Question, isSelected: Bool) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(verbatim: q.key)
                    .font(Style.mono(10))
                    .foregroundStyle(Style.secondary)
                    .frame(width: 38, alignment: .leading)
                Text(verbatim: Self.verdict(q))
                    .font(Style.bodyStrong)
                    .foregroundStyle(isSelected ? Style.accent : Style.label)
                    .lineLimit(1)
                    .frame(width: 110, alignment: .leading)
                Text(verbatim: q.text.replacingOccurrences(of: "\n", with: " "))
                    .foregroundStyle(Style.secondary)
                    .lineLimit(1)
                Spacer(minLength: 0)
            }
            if expanded == q.id {
                detail(q)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Style.pillRadius)
                .fill(isSelected ? Style.selection : Color.clear)
        )
    }

    private func detail(_ q: Question) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(verbatim: q.text)
                .foregroundStyle(Style.label)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if let context = q.context, !context.isEmpty {
                Text(verbatim: context)
                    .foregroundStyle(Style.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
            ForEach(Array(q.answers.enumerated()), id: \.offset) { index, answer in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("\(index + 1)").font(Style.mono(11)).foregroundStyle(Style.tertiary)
                    Text(verbatim: answer.summary)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                    if let age = Style.age(answer.createdAt) {
                        Text(verbatim: age).font(Style.meta).foregroundStyle(Style.tertiary)
                    }
                }
            }
        }
        .padding(.leading, 46)
        .padding(.bottom, 4)
    }
}
