// Views.swift — SwiftUI rail + card UI for the cactus panel, native macOS sidebar look.
// Responsibilities:
// - Forced-dark native look over the panel's `.sidebar` material: SF Pro text,
//   SF Mono for keys and commands, tokens from Style.swift, pieces from
//   Components.swift.
// - Stacked for the 420pt sidebar: rail on top (40%), card below, keycap
//   footer at the bottom. Rail: project header with open/live counts, then
//   one RailRow per question (accent pill on the active one). Card:
//   CardHeader, full text, context, choices numbered 1-9, recommend
//   preselected and starred; multi rows toggle, text rows (and any row
//   allowing free text) get a field; review rows show the verify block,
//   verdict history, p/f pass/fail; plan rows show steps and take text
//   verdicts; answered rows show the answer and `u` undoes it.
// - Keyboard: j/k, arrows, Tab/Shift-Tab move row (Tab also from the field,
//   keeping its draft); a digit on a single-choice/confirm row submits at
//   once (auto-advance, as the TUI), toggles on a multi, ticks a plan step;
//   Enter submits; every submit reloads and keeps the cursor index, so the
//   next open row slides under it; s skips, c retires, i types, u pops the session undo
//   stack; Esc leaves the field, a second Esc hides. While typing only
//   enter/esc/tab act. An unbound key flashes `no key X here`.
// - Drafts are kept per row; hiding the panel ends typing mode.
// - Renders question/context/choice text as plain strings, never Markdown.
// - Footer lists only the keys valid for the focused row.
// - Flashes show as a capsule toast above the footer that fades after 2s;
//   CactusCLI errors show there in red until the next key.

import AppKit
import SwiftUI

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
        GeometryReader { geometry in
            VStack(spacing: 0) {
                rail
                    .frame(height: geometry.size.height * 0.4)
                Rectangle().fill(Style.separator).frame(height: 1)
                card
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .overlay(alignment: .bottom) { toast }
                Rectangle().fill(Style.separator).frame(height: 1)
                footer
            }
        }
        .font(Style.body)
        .foregroundStyle(Style.label)
        .environment(\.colorScheme, .dark)
        .frame(minWidth: 380, minHeight: 440)
        .focusable()
        .focusEffectDisabled()
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
        .task(id: flash) {
            // The flash toast fades after 2s; a newer flash restarts the clock.
            guard flash != nil else { return }
            try? await Task.sleep(for: .seconds(2))
            if !Task.isCancelled {
                withAnimation(.easeOut(duration: 0.25)) { flash = nil }
            }
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
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(verbatim: currentQuestion?.projectBasename ?? "cactus")
                    .font(Style.metaStrong)
                    .foregroundStyle(Style.secondary)
                    .textCase(.uppercase)
                    .lineLimit(1)
                Spacer()
                Text(countsLine)
                    .font(Style.meta)
                    .foregroundStyle(Style.tertiary)
            }
            .padding(.horizontal, 18)
            .padding(.top, 12)
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 2) {
                        ForEach(Array(questions.enumerated()), id: \.element.id) { index, question in
                            RailRow(question: question, meta: railMeta(question),
                                    isSelected: index == selectedRow)
                                .id(question.id)
                                .onTapGesture { selectedRow = index }
                        }
                        if questions.isEmpty {
                            Text("No open questions")
                                .font(Style.body)
                                .foregroundStyle(Style.secondary)
                                .padding(10)
                        }
                    }
                    .padding(.horizontal, 10)
                    .padding(.bottom, 8)
                }
                .onChange(of: selectedRow) { _, _ in
                    if let id = currentQuestion?.id { proxy.scrollTo(id) }
                }
            }
        }
    }

    private var countsLine: String {
        let open = questions.filter { $0.status == "open" }.count
        let live = questions.filter { $0.status == "live" }.count
        return "\(open) open · \(live) live"
    }

    /// The rail row's secondary line: act, answer shape, status.
    private func railMeta(_ q: Question) -> String {
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
        else if q.status == "answered" { parts.append("answered") }
        if let age = Style.age(q.updatedAt) { parts.append(age) }
        return parts.joined(separator: " · ")
    }

    // MARK: card

    private var card: some View {
        Group {
            if let question = currentQuestion {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        CardHeader(question: question)
                        Text(verbatim: question.text)
                            .font(Style.question)
                            .foregroundStyle(Style.label)
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                        if let context = question.context, !context.isEmpty {
                            Text(verbatim: context)
                                .font(Style.body)
                                .foregroundStyle(Style.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                                .textSelection(.enabled)
                        }
                        if let review = question.review {
                            reviewBlock(review)
                        }
                        if !question.steps.isEmpty {
                            stepsBlock(question.steps)
                        }
                        if !question.choices.isEmpty && !question.isAnswered {
                            VStack(alignment: .leading, spacing: 6) {
                                ForEach(Array(question.choices.enumerated()), id: \.element.id) { index, choice in
                                    choiceRow(choice, number: index + 1, question: question)
                                }
                            }
                        }
                        if !question.answers.isEmpty {
                            verdictHistory(question.answers)
                        }
                        if showsField(question) {
                            answerField
                        }
                    }
                    .padding(.horizontal, 18)
                    .padding(.top, 14)
                    .padding(.bottom, 40)  // room for the toast
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                VStack(spacing: 8) {
                    Image(systemName: "tray")
                        .font(.system(size: 28))
                        .foregroundStyle(Style.tertiary)
                    Text("No open questions")
                        .foregroundStyle(Style.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    private var answerField: some View {
        TextField("", text: $draft, prompt: Text("Type an answer — ↩ to send")
            .foregroundStyle(Style.tertiary))
            .textFieldStyle(.plain)
            .font(Style.body)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(
                RoundedRectangle(cornerRadius: Style.pillRadius)
                    .fill(Color.black.opacity(0.25))
            )
            .overlay(
                RoundedRectangle(cornerRadius: Style.pillRadius)
                    .stroke(fieldFocused ? Style.accent.opacity(0.8) : Style.separator,
                            lineWidth: fieldFocused ? 2 : 1)
            )
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

    private func reviewBlock(_ review: Review) -> some View {
        let rows: [(String, String?)] = [
            ("Look at", review.lookAt), ("Run", review.runCmd),
            ("Pass", review.passWhen), ("Fail", review.failWhen),
            ("Then", review.thenDo),
        ]
        return VStack(alignment: .leading, spacing: 6) {
            ForEach(rows.filter { !($0.1 ?? "").isEmpty }, id: \.0) { row in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(row.0)
                        .font(Style.metaStrong)
                        .foregroundStyle(Style.secondary)
                        .frame(width: 52, alignment: .leading)
                    Text(verbatim: row.1 ?? "")
                        .font(row.0 == "Run" ? Style.mono(12) : Style.body)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: Style.choiceRadius).fill(Style.fill))
    }

    private func stepsBlock(_ steps: [Step]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(steps, id: \.n) { step in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: step.done ? "checkmark.circle.fill" : "circle")
                        .foregroundStyle(step.done ? Style.accent : Style.tertiary)
                    Text("\(step.n)")
                        .font(Style.mono(11))
                        .foregroundStyle(Style.secondary)
                    Text(verbatim: step.text)
                        .foregroundStyle(step.done ? Style.secondary : Style.label)
                        .strikethrough(step.done, color: Style.tertiary)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }
            }
        }
    }

    private func verdictHistory(_ answers: [Answer]) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Verdicts")
                .font(Style.metaStrong)
                .foregroundStyle(Style.secondary)
            ForEach(Array(answers.enumerated()), id: \.offset) { index, answer in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("\(index + 1)")
                        .font(Style.mono(11))
                        .foregroundStyle(Style.tertiary)
                    Text(verbatim: answer.summary)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }
            }
        }
    }

    /// Free text: any open or live row that allows it, and a plan/text row always.
    private func showsField(_ question: Question) -> Bool {
        guard !question.isAnswered, question.allowFree else { return false }
        return true
    }

    private func choiceRow(_ choice: Choice, number: Int, question: Question) -> some View {
        let isMulti = question.kind == "multi"
        return ChoiceRow(
            number: number,
            label: choice.label,
            description: choice.description,
            isRecommended: question.recommend?.contains(choice.label) ?? false,
            isPicked: isMulti ? toggled.contains(choice.label) : selectedChoice == choice.label,
            isMulti: isMulti,
            onTap: { selectChoice(at: number - 1) }
        )
    }

    // MARK: footer

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

    private var footer: some View {
        KeycapFooter(items: keyBarItems(currentQuestion))
            .padding(.horizontal, 18)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: toast

    @ViewBuilder
    private var toast: some View {
        if let message = errorMessage ?? poller.lastError {
            Toast(message: message, isError: true)
                .padding(.bottom, 8)
        } else if let flash {
            Toast(message: flash)
                .padding(.bottom, 8)
                .transition(.opacity)
        }
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
