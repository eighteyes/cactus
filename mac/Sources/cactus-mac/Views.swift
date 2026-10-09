// Views.swift — SwiftUI rail + card UI for the cactus panel, styled like the TUI.
// Responsibilities:
// - Theme: the TUI's resolved Textual colours (read from a rendered SVG), monospace.
// - Left rail: fixed 4-line blocks (key, text, kind line), `▸` and a blue fill
//   on the active one, a project header above. Right card: rounded accent
//   border titled `answering  KEY`, `project:key`, then full text, context, choices numbered 1-9, recommend
//   preselected and marked with a star; multi rows toggle, text rows (and any
//   row allowing free text) get a field; review rows show the verify block,
//   verdict history, p/f pass/fail; plan rows show steps and take text verdicts;
//   answered rows show the answer and `u` undoes it.
// - Keyboard: j/k, arrows, Tab/Shift-Tab move row (Tab also from the field,
//   keeping its draft); a digit on a single-choice/confirm row submits at
//   once (auto-advance, as the TUI), toggles on a multi, ticks a plan step;
//   Enter submits; every submit reloads and keeps the cursor index, so the
//   next open row slides under it; s skips, c retires, i types, u pops the session undo
//   stack; Esc leaves the field, a second Esc hides. While typing only
//   enter/esc/tab act. An unbound key flashes `no key X here`.
// - Drafts are kept per row; hiding the panel ends typing mode.
// - Renders question/context/choice text as plain strings, never Markdown.
// - Key bar docked at the card's bottom, listing keys valid for the focused row.
// - Shows CactusCLI errors in a status line.

import AppKit
import SwiftUI

/// Colours lifted from the TUI's rendered SVG (.ai/tmp/mac-design/tui-0.svg).
enum Theme {
    static let card = Color(hex: 0x121212)      // card / app background
    static let rail = Color(hex: 0x272727)      // rail background
    static let panel = Color(hex: 0x242F38)     // project head, status bar
    static let selected = Color(hex: 0x0178D4)  // active rail block
    static let selectedText = Color(hex: 0xDDEDF9)
    static let accent = Color(hex: 0xFFA62B)    // card border, title, project name
    static let text = Color(hex: 0xE0E0E0)
    static let muted = Color(hex: 0xA8A8A8)
    static func mono(_ size: CGFloat = 12, bold: Bool = false) -> Font {
        .system(size: size, weight: bold ? .bold : .regular, design: .monospaced)
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

struct ContentView: View {
    @ObservedObject var poller: Poller
    let cli: CactusCLI
    let onHide: () -> Void

    @State private var selectedRow = 0
    @State private var selectedChoice: String?
    @State private var toggled: Set<String> = []
    @State private var draft = ""
    @State private var drafts: [String: String] = [:]
    @State private var currentID: String?
    @FocusState private var fieldFocused: Bool
    @State private var errorMessage: String?
    @State private var flash: String?
    @State private var undoStack: [UndoEntry] = []
    @State private var focusAfterReload: String?
    @FocusState private var isFocused: Bool

    private var questions: [Question] { poller.questions }
    private var typing: Bool { fieldFocused }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                rail
                    .frame(width: 250)
                    .background(Theme.rail)
                card
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            statusBar
        }
        .font(Theme.mono())
        .foregroundStyle(Theme.text)
        .background(Theme.card)
        .frame(minWidth: 760, minHeight: 440)
        .focusable()
        .focused($isFocused)
        .onAppear { isFocused = true }
        .onKeyPress(action: handleKeyPress)
        .onChange(of: selectedRow) { _, _ in rowChanged() }
        .onChange(of: questions) { _, _ in
            if let address = focusAfterReload,
               let index = questions.firstIndex(where: { $0.address == address }) {
                focusAfterReload = nil
                selectedRow = index
            }
            if selectedRow >= questions.count {
                selectedRow = max(0, questions.count - 1)
            }
            rowChanged()
        }
        .onReceive(NotificationCenter.default.publisher(for: .cactusPanelHidden)) { _ in
            leaveField()
        }
        .onReceive(NotificationCenter.default.publisher(for: .cactusPanelShown)) { _ in
            leaveField()
        }
    }

    // MARK: rail

    private var rail: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(currentQuestion?.projectBasename ?? "cactus")
                .foregroundStyle(Theme.accent)
                .lineLimit(1)
                .padding(.horizontal, 8)
                .frame(maxWidth: .infinity, minHeight: 20, alignment: .leading)
                .background(Theme.panel)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(questions.enumerated()), id: \.element.id) { index, question in
                        railRow(question, isSelected: index == selectedRow)
                            .onTapGesture { selectedRow = index }
                    }
                    if questions.isEmpty {
                        Text("no open questions")
                            .foregroundStyle(Theme.muted)
                            .padding(8)
                    }
                }
            }
        }
    }

    /// One fixed-height block: `▸ key`, text, kind line (the TUI's QuestionBlock).
    private func railRow(_ question: Question, isSelected: Bool) -> some View {
        let marker = isSelected ? "▸" : " "
        return VStack(alignment: .leading, spacing: 0) {
            Text("\(marker) \(question.key)")
            Text("  " + truncate(question.text, 28))
            Text("  " + truncate(kindLine(question), 28))
            Spacer(minLength: 0)
        }
        .font(Theme.mono(12, bold: isSelected))
        .lineLimit(1)
        .foregroundStyle(isSelected ? Theme.selectedText : Theme.muted)
        .opacity(question.isAnswered ? 0.6 : 1)
        .padding(.horizontal, 8)
        .frame(maxWidth: .infinity, minHeight: 64, maxHeight: 64, alignment: .topLeading)
        .background(isSelected ? Theme.selected : Color.clear)
        .contentShape(Rectangle())
    }

    private func kindLine(_ q: Question) -> String {
        let shape: String
        if q.act == "plan" {
            shape = "\(q.steps.filter(\.done).count)/\(q.steps.count) steps"
        } else if q.kind == "choice" {
            shape = "\(q.choices.count) choices"
        } else if q.kind == "multi" {
            shape = "\(q.choices.count) choices · multi"
        } else if q.kind == "confirm" {
            shape = q.choices.isEmpty ? "yes / no" : q.choices.map(\.label).joined(separator: " / ")
        } else {
            shape = "text"
        }
        var parts = [q.act, shape]
        if q.status == "live" { parts.append("live") }
        else if q.status == "elaborate" { parts.append("wants more") }
        if q.status == "open" { parts.append(q.blocked == true ? "BLOCKING" : "not blocking") }
        return parts.joined(separator: " · ")
    }

    // MARK: card

    private var card: some View {
        VStack(alignment: .leading, spacing: 0) {
            cardBody
            keyBar
        }
        .padding(.top, 8)
        .overlay(
            RoundedRectangle(cornerRadius: 6).stroke(Theme.accent, lineWidth: 1)
        )
        .overlay(alignment: .topLeading) {
            Text(cardTitle)
                .foregroundStyle(Theme.accent)
                .padding(.horizontal, 4)
                .background(Theme.card)
                .offset(x: 10, y: -9)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 10)
    }

    private var cardTitle: String {
        currentQuestion.map { "answering  \($0.key)" } ?? "answering"
    }

    private var cardBody: some View {
        Group {
            if let question = currentQuestion {
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("\(question.projectBasename):\(question.key)")
                            .foregroundStyle(Theme.muted)
                        Text(question.text)
                            .textSelection(.enabled)
                        if let context = question.context, !context.isEmpty {
                            Text(context)
                                .foregroundStyle(Theme.muted)
                                .textSelection(.enabled)
                        }
                        if let review = question.review {
                            reviewBlock(review)
                        }
                        if !question.steps.isEmpty {
                            stepsBlock(question.steps)
                        }
                        if !question.choices.isEmpty && !question.isAnswered {
                            VStack(alignment: .leading, spacing: 2) {
                                ForEach(Array(question.choices.enumerated()), id: \.element.id) { index, choice in
                                    choiceRow(choice, number: index + 1, question: question)
                                }
                            }
                        }
                        if !question.answers.isEmpty {
                            verdictHistory(question.answers)
                        }
                        if showsField(question) {
                            TextField("type an answer, enter submits", text: $draft)
                                .textFieldStyle(.plain)
                                .padding(4)
                                .background(Theme.rail)
                                .focused($fieldFocused)
                                .onKeyPress(.escape) {
                                    leaveField()
                                    return .handled
                                }
                                .onKeyPress(.tab) {
                                    moveRow(NSEvent.modifierFlags.contains(.shift) ? -1 : 1)
                                    return .handled
                                }
                                .onSubmit { submitSelection() }
                        }
                    }
                    .padding(.horizontal, 16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                Text("no open questions")
                    .foregroundStyle(Theme.muted)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    private func reviewBlock(_ review: Review) -> some View {
        let rows: [(String, String?)] = [
            ("look at", review.lookAt), ("run", review.runCmd),
            ("pass", review.passWhen), ("fail", review.failWhen),
            ("then", review.thenDo),
        ]
        return VStack(alignment: .leading, spacing: 0) {
            ForEach(rows.filter { !($0.1 ?? "").isEmpty }, id: \.0) { row in
                Text("  " + row.0.padding(toLength: 8, withPad: " ", startingAt: 0) + (row.1 ?? ""))
                    .textSelection(.enabled)
            }
        }
    }

    private func stepsBlock(_ steps: [Step]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(steps, id: \.n) { step in
                Text("  \(step.n))  \(step.done ? "[x]" : "[ ]") \(step.text)")
                    .textSelection(.enabled)
            }
        }
    }

    private func verdictHistory(_ answers: [Answer]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("verdicts").foregroundStyle(Theme.muted)
            ForEach(Array(answers.enumerated()), id: \.offset) { index, answer in
                Text("  \(index + 1). \(answer.summary)")
                    .textSelection(.enabled)
            }
        }
    }

    /// Free text: any open or live row that allows it, and a plan/text row always.
    private func showsField(_ question: Question) -> Bool {
        guard !question.isAnswered, question.allowFree else { return false }
        return true
    }

    private func choiceRow(_ choice: Choice, number: Int, question: Question) -> some View {
        let isRecommended = question.recommend?.contains(choice.label) ?? false
        let isSelected = question.kind == "multi"
            ? toggled.contains(choice.label) : selectedChoice == choice.label
        let box = question.kind == "multi" ? (isSelected ? "[x]" : "[ ]") : (isSelected ? "●" : " ")
        var line = "\(number))  \(box) \(choice.label)"
        if isRecommended { line += " ★" }
        if !choice.description.isEmpty { line += "  — \(choice.description)" }
        return Text(line)
            .padding(.vertical, 1)
            .background(isSelected ? Theme.selected.opacity(0.35) : Color.clear)
            .contentShape(Rectangle())
            .onTapGesture { selectChoice(at: number - 1) }
    }

    // MARK: key bar

    /// Keys valid for the focused row, the TUI's `_keybar_items` in miniature.
    private func keyBarItems(_ q: Question?) -> [(String, String)] {
        if typing { return [("enter", "submit"), ("esc", "leave"), ("tab", "next")] }
        guard let q else { return [("j/k", "move")] }
        var items: [(String, String)] = []
        if q.isAnswered {
            return [("u", "undo"), ("c", "clear"), ("j/k/tab", "move")]
        }
        if q.act == "review" {
            items += [("p", "pass"), ("f", "fail")]
        } else if q.act == "plan" {
            if !q.steps.isEmpty { items.append(("1-\(min(q.steps.count, 9))", "step")) }
            items.append(("i", "note"))
        } else if q.kind == "multi" {
            items.append(("1-\(max(q.choices.count, 1))", "toggle"))
            items.append(("enter", "submit"))
        } else if !q.choices.isEmpty {
            items.append(("1-\(q.choices.count)", "pick"))
            items.append(("enter", "submit"))
        } else {
            items.append(("enter", "submit"))
        }
        if q.allowFree && q.act != "plan" { items.append(("i", "type")) }
        items += [("s", "skip"), ("c", "clear")]
        if !undoStack.isEmpty { items.append(("u", "undo")) }
        items += [("j/k/tab", "move"), ("esc", "hide")]
        return items
    }

    private var keyBar: some View {
        Text(keyBarItems(currentQuestion).map { "\($0.0) \($0.1)" }.joined(separator: "  "))
            .foregroundStyle(Theme.muted)
            .lineLimit(1)
            .padding(.horizontal, 16)
            .padding(.vertical, 4)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: status bar

    private var statusBar: some View {
        let open = questions.filter { $0.status == "open" }.count
        let live = questions.filter { $0.status == "live" }.count
        return HStack {
            if let message = errorMessage ?? poller.lastError {
                Text(message).foregroundStyle(.red).lineLimit(1)
            } else if let flash {
                Text(flash).foregroundStyle(Theme.accent).lineLimit(1)
            } else {
                Text("\(open) open · \(live) live").lineLimit(1)
            }
            Spacer()
        }
        .padding(.horizontal, 8)
        .frame(height: 20)
        .background(Theme.panel)
    }

    // MARK: state helpers

    private var currentQuestion: Question? {
        guard questions.indices.contains(selectedRow) else { return nil }
        return questions[selectedRow]
    }

    /// On a row move or a feed change: when the focused row is a different
    /// one, park the old draft, load the new row's, reset picks, leave the
    /// field. The same row keeps its picks and draft across a poll.
    private func rowChanged() {
        let newID = currentQuestion?.id
        guard newID != currentID else { return }
        if let currentID { drafts[currentID] = draft.isEmpty ? nil : draft }
        currentID = newID
        let recommended = currentQuestion?.recommend ?? []
        selectedChoice = recommended.first
        toggled = currentQuestion?.kind == "multi" ? Set(recommended) : []
        draft = newID.flatMap { drafts[$0] } ?? ""
        leaveField()
    }

    /// Typing mode off, key focus back on the panel root.
    private func leaveField() {
        fieldFocused = false
        isFocused = true
    }

    private func truncate(_ text: String, _ limit: Int) -> String {
        let flattened = text.replacingOccurrences(of: "\n", with: " ")
        if flattened.count <= limit { return flattened }
        return String(flattened.prefix(limit - 1)) + "…"
    }

    // MARK: keyboard

    /// One undoable action from this session, newest last (the TUI's undo stack).
    enum UndoEntry {
        var address: String {
            switch self {
            case let .answer(address, _), let .retire(address, _), let .step(address, _, _, _):
                return address
            }
        }

        case answer(address: String, key: String)
        case retire(address: String, key: String)
        case step(address: String, key: String, n: Int, wasDone: Bool)

        var label: String {
            switch self {
            case let .answer(_, key): return "answer on \(key)"
            case let .retire(_, key): return "retire of \(key)"
            case let .step(_, key, n, _): return "step \(n) on \(key)"
            }
        }
    }

    private func handleKeyPress(_ press: KeyPress) -> KeyPress.Result {
        // While typing the field's own handlers take esc and tab; the rest is text.
        if typing { return .ignored }
        if press.modifiers.contains(.command) || press.modifiers.contains(.control) {
            return .ignored
        }
        errorMessage = nil
        flash = nil
        // Shift-Tab arrives as the backtab character on macOS.
        if press.characters == "\u{19}" {
            moveRow(-1)
            return .handled
        }
        switch press.key {
        case .downArrow:
            moveRow(1)
            return .handled
        case .upArrow:
            moveRow(-1)
            return .handled
        case .tab:
            moveRow(press.modifiers.contains(.shift) ? -1 : 1)
            return .handled
        case .return:
            submitSelection()
            return .handled
        case .escape:
            return .ignored  // the panel's cancelOperation hides it
        default:
            break
        }
        let ch = press.characters
        switch ch {
        case "j":
            moveRow(1)
            return .handled
        case "k":
            moveRow(-1)
            return .handled
        case "s":
            submitSkip()
            return .handled
        case "i":
            guard let question = currentQuestion, showsField(question) else { return unbound(ch) }
            fieldFocused = true
            return .handled
        case "u":
            popUndo()
            return .handled
        case "p", "f":
            return submitVerdict(ch == "p" ? "pass" : "fail") ? .handled : unbound(ch)
        case "c":
            submitRetire()
            return .handled
        default:
            break
        }
        if let scalar = ch.unicodeScalars.first,
           let digit = scalar.properties.numericValue,
           digit >= 1, digit <= 9 {
            return pressDigit(Int(digit)) ? .handled : unbound(ch)
        }
        return unbound(ch)
    }

    /// Flash why a key did nothing, the TUI's gated-key flash.
    private func unbound(_ characters: String) -> KeyPress.Result {
        let printable = characters.unicodeScalars.allSatisfy { $0.value > 0x20 && $0.value < 0xF700 }
        let name = characters == " " ? "space" : (printable && !characters.isEmpty ? characters : "that")
        flash = "no key \(name) here"
        return .handled
    }

    private func moveRow(_ delta: Int) {
        guard !questions.isEmpty else { return }
        selectedRow = max(0, min(questions.count - 1, selectedRow + delta))
        // Same row (an edge): still leave the field so the keys navigate.
        leaveField()
    }

    /// A digit: tick a plan step, toggle a multi choice, else submit the
    /// choice at once with any typed draft (the TUI's action_select_choice).
    private func pressDigit(_ n: Int) -> Bool {
        guard let question = currentQuestion, !question.isAnswered else { return false }
        if question.act == "plan", let step = question.steps.first(where: { $0.n == n }) {
            toggleStep(question, step)
            return true
        }
        guard question.choices.indices.contains(n - 1) else { return false }
        if question.kind == "multi" {
            selectChoice(at: n - 1)
        } else {
            record(question, labels: [question.choices[n - 1].label], text: draft)
        }
        return true
    }

    private func toggleStep(_ question: Question, _ step: Step) {
        let entry = UndoEntry.step(address: question.address, key: question.key,
                                   n: step.n, wasDone: step.done)
        run({
            try await cli.setStep(key: question.address, n: step.n, done: !step.done)
        }) {
            undoStack.append(entry)
            flash = "step \(step.n) \(step.done ? "undone" : "done")"
            poller.refresh()
        }
    }

    private func selectChoice(at index: Int) {
        guard let question = currentQuestion, !question.isAnswered,
              question.choices.indices.contains(index) else { return }
        let label = question.choices[index].label
        if question.kind == "multi" {
            if toggled.contains(label) { toggled.remove(label) } else { toggled.insert(label) }
        } else {
            record(question, labels: [label], text: draft)
        }
    }

    /// Enter, outside the field or in it: the pick(s) plus any typed text.
    private func submitSelection() {
        guard let question = currentQuestion else { return }
        if question.isAnswered { return }
        if question.choices.isEmpty {
            // Text-only row (plan, text): enter opens the field, or records the draft.
            if draft.isEmpty {
                if showsField(question) { fieldFocused = true } else { errorMessage = "nothing to submit" }
            } else {
                record(question, labels: [], text: draft)
            }
            return
        }
        let labels: [String]
        if question.kind == "multi" {
            labels = question.choices.map(\.label).filter { toggled.contains($0) }
            if labels.isEmpty && draft.isEmpty {
                errorMessage = "nothing toggled"
                return
            }
        } else if let selectedChoice {
            labels = [selectedChoice]
        } else if draft.isEmpty {
            errorMessage = "no choice selected"
            return
        } else {
            labels = []
        }
        record(question, labels: labels, text: draft)
    }

    /// Review rows only: p/f record pass or fail with any typed text.
    private func submitVerdict(_ label: String) -> Bool {
        guard let question = currentQuestion, question.act == "review", !question.isAnswered,
              question.choices.contains(where: { $0.label == label }) else { return false }
        record(question, labels: [label], text: draft)
        return true
    }

    /// Answer the row, push it on the undo stack, drop its draft, reload now.
    private func record(_ question: Question, labels: [String], text: String) {
        leaveField()
        run({
            try await cli.answer(key: question.address, labels: labels, text: text, skip: false)
        }) {
            undoStack.append(.answer(address: question.address, key: question.key))
            drafts[question.id] = nil
            if currentID == question.id { draft = "" }
            flash = "recorded " + (labels.isEmpty ? "text" : labels.joined(separator: ", "))
            poller.refresh()
        }
    }

    /// `u`: pop the newest session action and reverse it, whatever row is
    /// selected; an entry whose reversal fails (row purged, already undone)
    /// is skipped, like the TUI's action_undo.
    private func popUndo() {
        Task {
            while let entry = undoStack.popLast() {
                do {
                    try await undo(entry)
                    flash = "undid \(entry.label)"
                    focusAfterReload = entry.address
                    poller.refresh()
                    return
                } catch {
                    continue
                }
            }
            flash = "nothing to undo"
        }
    }

    private func undo(_ entry: UndoEntry) async throws {
        switch entry {
        case let .answer(address, _):
            try await cli.undo(key: address)
        case let .retire(address, _):
            try await cli.retire(key: address, undo: true)
        case let .step(address, _, n, wasDone):
            try await cli.setStep(key: address, n: n, done: wasDone)
        }
    }

    private func submitSkip() {
        guard let question = currentQuestion else { return }
        leaveField()
        run({
            try await cli.answer(key: question.address, labels: [], text: nil, skip: true)
        }) {
            undoStack.append(.answer(address: question.address, key: question.key))
            flash = "skipped \(question.key)"
            poller.refresh()
        }
    }

    private func submitRetire() {
        guard let question = currentQuestion else { return }
        leaveField()
        run({
            try await cli.retire(key: question.address)
        }) {
            undoStack.append(.retire(address: question.address, key: question.key))
            flash = "retired \(question.key)"
            poller.refresh()
        }
    }

    private func run(_ operation: @escaping () async throws -> Void,
                     onSuccess: (() -> Void)? = nil) {
        Task {
            do {
                try await operation()
                onSuccess?()
            } catch {
                errorMessage = "\(error)"
            }
        }
    }
}
