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
// - Keyboard: j/k move row, digit selects/toggles, Enter submits, s skips,
//   c clears, i types, u undoes, Esc leaves the field then hides (panel).
//   While the text field has focus every shortcut is off.
// - Renders question/context/choice text as plain strings, never Markdown.
// - Key bar docked at the card's bottom, listing keys valid for the focused row.
// - Shows CactusCLI errors in a status line.

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
    @FocusState private var fieldFocused: Bool
    @State private var errorMessage: String?
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
        .onChange(of: selectedRow) { _, _ in resetChoice() }
        .onChange(of: questions) { _, _ in
            if selectedRow >= questions.count {
                selectedRow = max(0, questions.count - 1)
            }
            resetChoice()
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
                                    fieldFocused = false
                                    return .handled
                                }
                                .onSubmit { submitText() }
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
        guard let q else { return [("j/k", "move")] }
        var items: [(String, String)] = []
        if q.isAnswered {
            return [("u", "undo"), ("c", "clear"), ("j/k", "move")]
        }
        if q.act == "review" {
            items += [("p", "pass"), ("f", "fail")]
        } else if q.act == "plan" {
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
        if !q.answers.isEmpty { items.append(("u", "undo")) }
        items += [("j/k", "move"), ("esc", "hide")]
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

    private func resetChoice() {
        let recommended = currentQuestion?.recommend ?? []
        selectedChoice = recommended.first
        toggled = currentQuestion?.kind == "multi" ? Set(recommended) : []
        draft = ""
        fieldFocused = false
    }

    private func truncate(_ text: String, _ limit: Int) -> String {
        let flattened = text.replacingOccurrences(of: "\n", with: " ")
        if flattened.count <= limit { return flattened }
        return String(flattened.prefix(limit - 1)) + "…"
    }

    // MARK: keyboard

    private func handleKeyPress(_ press: KeyPress) -> KeyPress.Result {
        if typing { return .ignored }
        errorMessage = nil
        switch press.key {
        case "j":
            moveRow(1)
            return .handled
        case "k":
            moveRow(-1)
            return .handled
        case .return:
            submitSelection()
            return .handled
        case "s":
            submitSkip()
            return .handled
        case "i":
            guard let question = currentQuestion, showsField(question) else { return .ignored }
            fieldFocused = true
            return .handled
        case "u":
            submitUndo()
            return .handled
        case "p":
            return submitVerdict("pass")
        case "f":
            return submitVerdict("fail")
        case "c":
            submitClear()
            return .handled
        default:
            break
        }
        if let scalar = press.characters.unicodeScalars.first,
           let digit = scalar.properties.numericValue,
           digit >= 1, digit <= 9 {
            selectChoice(at: Int(digit) - 1)
            return .handled
        }
        return .ignored
    }

    private func moveRow(_ delta: Int) {
        guard !questions.isEmpty else { return }
        selectedRow = max(0, min(questions.count - 1, selectedRow + delta))
    }

    private func selectChoice(at index: Int) {
        guard let question = currentQuestion, !question.isAnswered,
              question.choices.indices.contains(index) else { return }
        let label = question.choices[index].label
        if question.kind == "multi" {
            if toggled.contains(label) { toggled.remove(label) } else { toggled.insert(label) }
        } else {
            selectedChoice = label
        }
    }

    private func submitSelection() {
        guard let question = currentQuestion else { return }
        if question.isAnswered { return }
        if question.choices.isEmpty {
            // Text-only row (plan, text): enter opens the field, or records the draft.
            if draft.isEmpty {
                if showsField(question) { fieldFocused = true } else { errorMessage = "nothing to submit" }
            } else {
                submitText()
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
        let text = draft
        run {
            try await cli.answer(key: question.address, labels: labels, text: text, skip: false)
        }
    }

    private func submitText() {
        guard let question = currentQuestion, !draft.isEmpty else { return }
        let text = draft
        draft = ""
        fieldFocused = false
        run {
            try await cli.answer(key: question.address, labels: [], text: text, skip: false)
        }
    }

    /// Review rows only: p/f record the pass or fail verdict by label.
    private func submitVerdict(_ label: String) -> KeyPress.Result {
        guard let question = currentQuestion, question.act == "review", !question.isAnswered,
              question.choices.contains(where: { $0.label == label }) else { return .ignored }
        run {
            try await cli.answer(key: question.address, labels: [label], text: nil, skip: false)
        }
        return .handled
    }

    private func submitUndo() {
        guard let question = currentQuestion else { return }
        guard question.isAnswered || !question.answers.isEmpty else {
            errorMessage = "nothing to undo"
            return
        }
        run {
            try await cli.undo(key: question.address)
        }
    }

    private func submitSkip() {
        guard let question = currentQuestion else { return }
        run {
            try await cli.answer(key: question.address, labels: [], text: nil, skip: true)
        }
    }

    private func submitClear() {
        guard let question = currentQuestion else { return }
        run {
            try await cli.clear(key: question.address)
        }
    }

    private func run(_ operation: @escaping () async throws -> Void) {
        Task {
            do {
                try await operation()
            } catch {
                errorMessage = "\(error)"
            }
        }
    }
}
