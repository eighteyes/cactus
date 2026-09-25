// Views.swift — SwiftUI rail + card UI for the cactus panel.
// Responsibilities:
// - Left rail: one line per question, `project · key · truncated text`.
// - Right card: full text, context, choices numbered 1-9, recommend
//   preselected and marked with a star.
// - Keyboard: j/k move row, digit selects a choice, Enter submits, s skips,
//   c clears, Esc hides (handled by the panel itself).
// - Renders question/context/choice text as plain strings, never Markdown.
// - Shows CactusCLI errors in a footer line.

import SwiftUI

struct ContentView: View {
    @ObservedObject var poller: Poller
    let cli: CactusCLI
    let onHide: () -> Void

    @State private var selectedRow = 0
    @State private var selectedChoice: String?
    @State private var errorMessage: String?
    @FocusState private var isFocused: Bool

    private var questions: [Question] { poller.questions }

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
        let line = "\(question.projectBasename) · \(question.key) · \(truncate(question.text, 40))"
        return Text(line)
            .font(.system(size: 11, design: .monospaced))
            .lineLimit(1)
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
                        if !question.choices.isEmpty {
                            VStack(alignment: .leading, spacing: 4) {
                                ForEach(Array(question.choices.enumerated()), id: \.element.id) { index, choice in
                                    choiceRow(choice, number: index + 1, question: question)
                                }
                            }
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

    private func choiceRow(_ choice: Choice, number: Int, question: Question) -> some View {
        let isRecommended = question.recommend?.contains(choice.label) ?? false
        let isSelected = selectedChoice == choice.label
        return HStack(spacing: 6) {
            Text("\(number)")
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
        .onTapGesture { selectedChoice = choice.label }
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
                Text("j/k move · 1-9 select · enter submit · s skip · c clear · esc hide")
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
        selectedChoice = currentQuestion?.recommend?.first
    }

    private func truncate(_ text: String, _ limit: Int) -> String {
        let flattened = text.replacingOccurrences(of: "\n", with: " ")
        if flattened.count <= limit { return flattened }
        return String(flattened.prefix(limit - 1)) + "…"
    }

    // MARK: keyboard

    private func handleKeyPress(_ press: KeyPress) -> KeyPress.Result {
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
        guard let question = currentQuestion, question.choices.indices.contains(index) else { return }
        selectedChoice = question.choices[index].label
    }

    private func submitSelection() {
        guard let question = currentQuestion else { return }
        guard let label = selectedChoice else {
            errorMessage = "no choice selected"
            return
        }
        run {
            try await cli.answer(key: question.key, label: label, text: nil, skip: false)
        }
    }

    private func submitSkip() {
        guard let question = currentQuestion else { return }
        run {
            try await cli.answer(key: question.key, label: nil, text: nil, skip: true)
        }
    }

    private func submitClear() {
        guard let question = currentQuestion else { return }
        run {
            try await cli.clear(key: question.key)
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
