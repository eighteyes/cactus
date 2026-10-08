// Views.swift — SwiftUI rail + card UI for the cactus panel.
// Responsibilities:
// - Left rail: one line per question, `project · key · truncated text`.
// - Right card: full text, context, choices numbered 1-9, recommend
//   preselected and marked with a star; multi rows toggle, text rows (and any
//   row allowing free text) get a field; review rows show the verify block,
//   verdict history, p/f pass/fail; plan rows show steps and take text verdicts;
//   answered rows show the answer and `u` undoes it.
// - Keyboard: j/k move row, digit selects/toggles, Enter submits, s skips,
//   c clears, i types, u undoes, Esc leaves the field then hides (panel).
//   While the text field has focus every shortcut is off.
// - Renders question/context/choice text as plain strings, never Markdown.
// - Shows CactusCLI errors in a footer line.

import SwiftUI

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
                    .frame(width: 190)
                Divider()
                card
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            Divider()
            footer
        }
        .frame(minWidth: 520, minHeight: 360)
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
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 2) {
                ForEach(Array(questions.enumerated()), id: \.element.id) { index, question in
                    railRow(question, isSelected: index == selectedRow)
                        .onTapGesture { selectedRow = index }
                }
                if questions.isEmpty {
                    Text("no open questions")
                        .foregroundStyle(.secondary)
                        .padding(8)
                }
            }
            .padding(6)
        }
    }

    private func railRow(_ question: Question, isSelected: Bool) -> some View {
        let mark = question.isAnswered ? "✓ " : ""
        let line = "\(mark)\(question.projectBasename) · \(question.key) · \(truncate(question.text, 40))"
        return Text(line)
            .font(.system(size: 11, design: .monospaced))
            .lineLimit(1)
            .opacity(question.isAnswered ? 0.5 : 1)
            .padding(.horizontal, 6)
            .padding(.vertical, 3)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(isSelected ? Color.accentColor.opacity(0.25) : Color.clear)
            .cornerRadius(4)
    }

    // MARK: card

    private var card: some View {
        Group {
            if let question = currentQuestion {
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(question.text)
                            .font(.system(size: 14, weight: .semibold))
                            .textSelection(.enabled)
                        if let context = question.context, !context.isEmpty {
                            Text(context)
                                .font(.system(size: 12))
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                        }
                        if let review = question.review {
                            reviewBlock(review)
                        }
                        if !question.steps.isEmpty {
                            stepsBlock(question.steps)
                        }
                        if !question.choices.isEmpty && !question.isAnswered {
                            if question.kind == "multi" {
                                Text("toggle with digits, enter submits all")
                                    .font(.system(size: 10))
                                    .foregroundStyle(.secondary)
                            }
                            VStack(alignment: .leading, spacing: 4) {
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
                                .textFieldStyle(.roundedBorder)
                                .focused($fieldFocused)
                                .onKeyPress(.escape) {
                                    fieldFocused = false
                                    return .handled
                                }
                                .onSubmit { submitText() }
                        }
                    }
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                Text("no open questions")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    private func reviewBlock(_ review: Review) -> some View {
        let rows: [(String, String?)] = [
            ("look at", review.lookAt), ("run", review.runCmd),
            ("pass when", review.passWhen), ("fail when", review.failWhen),
            ("then", review.thenDo),
        ]
        return VStack(alignment: .leading, spacing: 2) {
            ForEach(rows.filter { !($0.1 ?? "").isEmpty }, id: \.0) { row in
                Text("\(row.0): \(row.1 ?? "")")
                    .font(.system(size: 11, design: .monospaced))
                    .textSelection(.enabled)
            }
        }
    }

    private func stepsBlock(_ steps: [Step]) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(steps, id: \.n) { step in
                Text("\(step.done ? "[x]" : "[ ]") \(step.n). \(step.text)")
                    .font(.system(size: 11, design: .monospaced))
                    .textSelection(.enabled)
            }
        }
    }

    private func verdictHistory(_ answers: [Answer]) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("verdicts")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(.secondary)
            ForEach(Array(answers.enumerated()), id: \.offset) { index, answer in
                Text("\(index + 1). \(answer.summary)")
                    .font(.system(size: 11))
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
        return HStack(spacing: 6) {
            Text(question.kind == "multi" ? (isSelected ? "☑" : "☐") : "\(number)")
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 14, alignment: .trailing)
            if isRecommended {
                Text("★").foregroundStyle(.yellow)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(choice.label)
                    .font(.system(size: 12, weight: .medium))
                if !choice.description.isEmpty {
                    Text(choice.description)
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(4)
        .background(isSelected ? Color.accentColor.opacity(0.25) : Color.clear)
        .cornerRadius(4)
        .onTapGesture { selectChoice(at: number - 1) }
    }

    // MARK: footer

    private var footer: some View {
        HStack {
            if let errorMessage {
                Text(errorMessage)
                    .font(.system(size: 11))
                    .foregroundStyle(.red)
                    .lineLimit(1)
            } else if let pollerError = poller.lastError {
                Text(pollerError)
                    .font(.system(size: 11))
                    .foregroundStyle(.red)
                    .lineLimit(1)
            } else {
                Text("j/k move · 1-9 pick · enter submit · i type · p/f pass/fail · u undo · s skip · c clear · esc hide")
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
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
