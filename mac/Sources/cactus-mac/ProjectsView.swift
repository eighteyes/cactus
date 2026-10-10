// ProjectsView.swift — the projects page (TUI `P`), a list screen in the sidebar.
// Responsibilities:
// - Render the due-ranked project rows ContentView hands it: label, due
//   count, stale count, ignored state, `*` on the pinned one, `▸` on the
//   project the inbox is showing, an accent pill on the selected row.
// - Pure view: selection, keys and every CLI call stay in ContentView.

import SwiftUI

struct ProjectsView: View {
    let rows: [ProjectRow]
    let selected: Int
    let current: String?
    let pinned: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            PageHeader(title: "Projects", detail: pinned.map { "pinned " + ($0 as NSString).lastPathComponent })
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 2) {
                        ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                            line(row, isSelected: index == selected)
                                .id(row.id)
                        }
                        if rows.isEmpty {
                            Text("Nothing due anywhere")
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

    private func line(_ row: ProjectRow, isSelected: Bool) -> some View {
        HStack(spacing: 8) {
            Text(row.project == current ? "▸" : " ")
                .font(Style.mono(11))
                .foregroundStyle(Style.accent)
                .frame(width: 10)
            Text(verbatim: row.basename)
                .font(Style.bodyStrong)
                .foregroundStyle(isSelected ? Style.accent : Style.label)
                .lineLimit(1)
            if row.project == pinned {
                Text("*").font(Style.mono(12, weight: .semibold)).foregroundStyle(Style.accent)
            }
            Spacer(minLength: 0)
            if !row.enabled {
                Text("ignored").font(Style.meta).foregroundStyle(Style.tertiary)
            }
            if row.staleCount > 0 {
                Text("\(row.staleCount) stale").font(Style.meta).foregroundStyle(Style.tertiary)
            }
            Text("\(row.dueCount) due")
                .font(Style.meta)
                .foregroundStyle(row.dueCount > 0 ? Style.attention : Style.secondary)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Style.pillRadius)
                .fill(isSelected ? Style.selection : Color.clear)
        )
    }
}

/// Title line shared by the projects page and the answers view.
struct PageHeader: View {
    let title: String
    var detail: String?

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(verbatim: title)
                .font(Style.metaStrong)
                .foregroundStyle(Style.secondary)
                .textCase(.uppercase)
            Spacer()
            if let detail {
                Text(verbatim: detail)
                    .font(Style.meta)
                    .foregroundStyle(Style.tertiary)
                    .lineLimit(1)
            }
        }
        .padding(.horizontal, 18)
        .padding(.top, 12)
    }
}
