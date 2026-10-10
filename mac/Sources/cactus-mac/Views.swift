// Views.swift — SwiftUI rail + card UI for the cactus panel, native macOS sidebar look.
// Responsibilities:
// - Forced-dark native look over the panel's `.sidebar` material: SF Pro text,
//   SF Mono for keys and commands, tokens from Style.swift, pieces from
//   Components.swift.
// - Three pages in the 420pt sidebar: the inbox (rail on top, card below),
//   the projects page (ProjectsView, `P`) and the answers view (AnswersView,
//   `a`); Esc backs out of a page. Keycap footer at the bottom of each.
// - Inbox rail shows one project at a time, as the TUI does: `[`/`]` rotate
//   over enabled projects with open or live rows, newest arrival first; a
//   pin (`*` on the projects page, kept in UserDefaults) scopes it to one.
// - Card: CardHeader, full text, context, files, site, choices numbered
//   1-9 (recommend preselected and starred), the auto-decider's proposal,
//   review verify block, plan steps, verdict history, a live or recorded
//   command result, the `o` file preview, and an answer/hint field.
// - Keys follow tui.py BINDINGS, each gated per row the way its
//   check_action gates it (`allows`), and the footer lists only valid keys.
//   Rows: s c x i y n m e D d A u; agents: p v; commands: C R O; files:
//   f F o; site: w; digits pick, toggle, tick a step or copy a data chunk;
//   projects: [ ] P a; r refreshes. While typing only enter/esc/tab act.
// - Every write goes through a `cactus` verb on CactusCLI, off the main
//   thread; `R` streams `cactus exec` into the card and Esc kills it.
// - Copy (NSPasteboard) and open (NSWorkspace, `open -t`) are local OS
//   actions, not store writes.
// - Renders question/context/choice text as plain strings, never Markdown.
// - Flashes show as a capsule toast above the footer that fades after 2s;
//   CactusCLI errors show there in red until the next key.

import AppKit
import SwiftUI

struct ContentView: View {
    @ObservedObject var poller: Poller
    let cli: CactusCLI
    let onHide: () -> Void

    enum Page { case inbox, projects, answers }
    enum FieldMode { case answer, hint }

    @State private var page: Page = .inbox
    @State private var selectedRow = 0
    @State private var selectedChoice: String?
    @State private var toggled: Set<String> = []
    @State private var draft = ""
    @State private var hint = ""
    @State private var fieldMode: FieldMode = .answer
    @State private var drafts: [String: String] = [:]
    @State private var currentID: String?
    @FocusState private var fieldFocused: Bool
    @State private var errorMessage: String?
    @State private var flash: String?
    @State private var undoStack: [UndoEntry] = []
    @State private var focusAfterReload: String?
    @FocusState private var isFocused: Bool

    // Project scope.
    @State private var currentProject: String?
    @State private var pinned: String? = UserDefaults.standard.string(forKey: ContentView.pinKey)
    @State private var projectIndex = 0

    // Answers view.
    @State private var answersProject: String?
    @State private var answersRows: [Question] = []
    @State private var answersIndex = 0
    @State private var answersExpanded: String?
    @State private var answersLoading = false

    // Row-local modes.
    @State private var several: Set<String> = []
    @State private var filePending: String?
    @State private var previewFor: String?
    @State private var previewLines: [String] = []

    // A running `cactus exec`.
    @State private var execHandle: ExecHandle?
    @State private var execFor: String?
    @State private var execOutput: [String: [String]] = [:]

    static let pinKey = "pinnedProject"

    private var typing: Bool { fieldFocused }

    var body: some View {
        GeometryReader { geometry in
            VStack(spacing: 0) {
                switch page {
                case .inbox:
                    rail
                        .frame(height: geometry.size.height * 0.4)
                    Rectangle().fill(Style.separator).frame(height: 1)
                    card
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .overlay(alignment: .bottom) { toast }
                case .projects:
                    ProjectsView(rows: projectRows, selected: projectIndex,
                                 current: activeProject, pinned: effectivePin)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .overlay(alignment: .bottom) { toast }
                case .answers:
                    AnswersView(project: answersProject, rows: answersRows,
                                selected: answersIndex, expanded: answersExpanded,
                                loading: answersLoading)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .overlay(alignment: .bottom) { toast }
                }
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

    // MARK: project scope

    /// A saved pin counts only while that project is still known.
    private var effectivePin: String? {
        guard let pinned, poller.projects.contains(where: { $0.project == pinned }) else { return nil }
        return pinned
    }

    /// Projects `[`/`]` rotate over: enabled, something open or live, newest
    /// arrival first (the TUI's `_live_projects_rows`).
    private var liveProjects: [ProjectRow] {
        poller.projects
            .filter { $0.enabled && ($0.openCount > 0 || $0.liveCount > 0) }
            .filter { effectivePin == nil || $0.project == effectivePin }
            .sorted { ($0.newestOpen ?? "") > ($1.newestOpen ?? "") }
    }

    /// The project the rail shows.
    private var activeProject: String? {
        if let pin = effectivePin { return pin }
        let live = liveProjects
        if let currentProject, live.contains(where: { $0.project == currentProject }) {
            return currentProject
        }
        return live.first?.project ?? poller.questions.first?.project
    }

    private var questions: [Question] {
        guard let project = activeProject else { return [] }
        return poller.questions.filter { $0.project == project }
    }

    /// Projects page rows: something due, plus the pinned one.
    private var projectRows: [ProjectRow] {
        poller.projects.filter { $0.dueCount > 0 || $0.project == effectivePin }
    }

    private func rotateProject(_ delta: Int) {
        let live = liveProjects
        guard live.count > 1 else {
            flash = effectivePin != nil ? "pinned — unpin with * on P" : "no other project with open rows"
            return
        }
        let index = live.firstIndex(where: { $0.project == activeProject }) ?? 0
        let next = live[(index + delta + live.count) % live.count]
        currentProject = next.project
        selectedRow = 0
        rowChanged()
        flash = next.basename
    }

    // MARK: rail

    private var rail: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(verbatim: activeProject.map { ($0 as NSString).lastPathComponent } ?? "cactus")
                    .font(Style.metaStrong)
                    .foregroundStyle(Style.secondary)
                    .textCase(.uppercase)
                    .lineLimit(1)
                Text(effectivePin != nil ? "pinned" : (liveProjects.count > 1 ? "[ ] switch" : ""))
                    .font(Style.meta)
                    .foregroundStyle(Style.tertiary)
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
        let others = liveProjects.filter { $0.project != activeProject }.reduce(0) { $0 + $1.dueCount }
        return "\(open) open · \(live) live" + (others > 0 ? " · \(others) elsewhere" : "")
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
                        if question.status == "elaborate" {
                            note("waiting on the agent to rewrite · u withdraws")
                        }
                        if !question.files.isEmpty {
                            filesBlock(question)
                        }
                        if let site = question.site {
                            metaLine("site", site)
                        }
                        if let review = question.review {
                            reviewBlock(review)
                        }
                        if !question.steps.isEmpty {
                            stepsBlock(question.steps)
                        }
                        if !question.choices.isEmpty && !question.isAnswered {
                            if several.contains(question.id) {
                                note("pick several (m to go back)")
                            }
                            VStack(alignment: .leading, spacing: 6) {
                                ForEach(Array(question.choices.enumerated()), id: \.element.id) { index, choice in
                                    choiceRow(choice, number: index + 1, question: question)
                                }
                            }
                        }
                        if question.status == "open", let auto = question.auto, let pick = auto.pick {
                            metaLine("auto", "[\(auto.confidence ?? "..")] \(pick)"
                                     + (auto.reason.map { " — \($0)" } ?? "") + " · A accepts")
                        }
                        if !question.answers.isEmpty {
                            verdictHistory(question.answers)
                        }
                        commandOutput(question)
                        if previewFor == question.id {
                            monoBlock(previewLines.isEmpty ? ["…"] : previewLines)
                        }
                        if showsField(question) || fieldMode == .hint {
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

    private func note(_ text: String) -> some View {
        Text(verbatim: text)
            .font(Style.meta)
            .foregroundStyle(Style.attention)
    }

    private func metaLine(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(label)
                .font(Style.metaStrong)
                .foregroundStyle(Style.secondary)
                .frame(width: 52, alignment: .leading)
            Text(verbatim: value)
                .font(Style.meta)
                .foregroundStyle(Style.label)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
    }

    private func filesBlock(_ q: Question) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            ForEach(Array(q.files.enumerated()), id: \.offset) { index, path in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(q.files.count > 1 ? "f\(index + 1)" : "f")
                        .font(Style.mono(10))
                        .foregroundStyle(filePending != nil ? Style.accent : Style.tertiary)
                        .frame(width: 22, alignment: .leading)
                    Text(verbatim: displayPath(path, cwd: q.cwd))
                        .font(Style.mono(11))
                        .foregroundStyle(Style.label)
                        .lineLimit(1)
                        .truncationMode(.head)
                }
            }
        }
    }

    private func displayPath(_ path: String, cwd: String?) -> String {
        if let cwd, path.hasPrefix(cwd + "/") { return String(path.dropFirst(cwd.count + 1)) }
        return path
    }

    /// Live `R` output for this row, else the recorded result's tail.
    @ViewBuilder
    private func commandOutput(_ q: Question) -> some View {
        if let lines = execOutput[q.address] {
            VStack(alignment: .leading, spacing: 4) {
                Text(execFor == q.address ? "running · esc stops" : "output")
                    .font(Style.metaStrong)
                    .foregroundStyle(execFor == q.address ? Style.attention : Style.secondary)
                monoBlock(Array(lines.suffix(30)))
            }
        } else if let result = q.result, let exit = result.exit {
            VStack(alignment: .leading, spacing: 4) {
                Text("exit \(exit)" + (result.log != nil ? " · O opens the log" : ""))
                    .font(Style.metaStrong)
                    .foregroundStyle(exit == 0 ? Style.secondary : Style.error)
                if let tail = result.tail, !tail.isEmpty {
                    monoBlock(Array(tail.suffix(10)))
                }
            }
        }
    }

    private func monoBlock(_ lines: [String]) -> some View {
        Text(verbatim: lines.joined(separator: "\n"))
            .font(Style.mono(11))
            .foregroundStyle(Style.label)
            .fixedSize(horizontal: false, vertical: true)
            .textSelection(.enabled)
            .padding(8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: Style.choiceRadius).fill(Color.black.opacity(0.25)))
    }

    private var fieldText: Binding<String> {
        fieldMode == .hint ? $hint : $draft
    }

    private var answerField: some View {
        TextField("", text: fieldText, prompt: Text(fieldMode == .hint
                                                    ? "What should the agent rewrite? — ↩ to send"
                                                    : "Type an answer — ↩ to send")
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
            .onSubmit {
                if fieldMode == .hint { submitElaborate() } else { submitSelection() }
            }
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

    /// Free text: any open or live row that allows it.
    private func showsField(_ question: Question) -> Bool {
        guard !question.isAnswered, question.status != "elaborate", question.allowFree else { return false }
        return true
    }

    private func choiceRow(_ choice: Choice, number: Int, question: Question) -> some View {
        let toggles = togglesChoices(question)
        return ChoiceRow(
            number: number,
            label: choice.label,
            description: choice.description,
            isRecommended: question.recommend?.contains(choice.label) ?? false,
            isPicked: toggles ? toggled.contains(choice.label) : selectedChoice == choice.label,
            isMulti: toggles,
            onTap: { pressDigit(number) }
        )
    }

    /// Digits toggle rather than submit: a multi row, or a choice row flipped by `m`.
    private func togglesChoices(_ q: Question) -> Bool {
        q.kind == "multi" || several.contains(q.id)
    }

    // MARK: key gating

    /// Row-dependent actions, gated like tui.py's check_action.
    enum Act {
        case skip, clear, close, type, yes, no, several, elaborate, decompose
        case dismiss, auto, poke, visit, copy, run, output, file, preview, site
        case digits, undo
    }

    private func allows(_ act: Act, _ q: Question?) -> Bool {
        guard let q else { return act == .undo && !undoStack.isEmpty }
        if q.status == "elaborate" {
            switch act {
            case .file, .preview: return !q.files.isEmpty
            case .site: return q.site != nil
            case .digits: return filePending != nil
            case .clear, .undo: return true
            case .poke: return q.agent != nil && q.pane != nil
            case .visit: return q.pane != nil
            default: return false
            }
        }
        if q.isAnswered {
            return [.clear, .undo].contains(act) || (act == .visit && q.pane != nil)
        }
        switch act {
        case .skip, .clear: return true
        case .close: return ["review", "plan"].contains(q.act) && q.isPersistent
        case .type: return q.allowFree
        case .yes, .no: return q.kind == "confirm"
        case .several:
            return q.kind == "choice" && q.status == "open" && !q.isPersistent
                && !["data", "run"].contains(q.act) && q.choices.count >= 2
        case .elaborate, .decompose: return ["open", "live"].contains(q.status)
        case .dismiss: return ["notify", "data"].contains(q.act)
        case .auto:
            return q.status == "open" && q.auto?.pick.map { p in q.choices.contains { $0.label == p } } == true
        case .poke: return q.agent != nil && q.pane != nil
        case .visit: return q.pane != nil
        case .copy: return q.command != nil
        case .run: return q.command != nil && ["run", "review"].contains(q.act)
        case .output: return q.result?.log != nil
        case .file, .preview: return !q.files.isEmpty
        case .site: return q.site != nil
        case .undo: return !undoStack.isEmpty
        case .digits:
            if filePending != nil { return true }
            if q.act == "plan" { return !q.steps.isEmpty }
            if q.act == "data" { return !q.choices.isEmpty }
            return ["choice", "multi", "confirm"].contains(q.kind)
        }
    }

    // MARK: footer

    /// Keys valid on the current page and row, the TUI's `_keybar_items`.
    private func keyBarItems() -> [(String, String)] {
        if typing {
            return [("enter", fieldMode == .hint ? "send" : "submit"), ("esc", "leave"), ("tab", "next")]
        }
        switch page {
        case .projects:
            var items: [(String, String)] = [("j/k", "move"), ("enter", "switch"), ("*", "pin"),
                                             ("I", "ignore"), ("A", "activate"), ("p", "poke")]
            items += [("a", "answers"), ("esc", "back")]
            return items
        case .answers:
            return [("j/k", "move"), ("enter", "expand"), ("[ ]", "project"),
                    ("P", "projects"), ("esc", "back")]
        case .inbox:
            break
        }
        if execFor != nil { return [("esc", "stop run"), ("j/k", "move")] }
        if let pending = filePending { return [("1-9", "\(pending) file"), ("esc", "cancel")] }
        let q = currentQuestion
        var items: [(String, String)] = []
        if let q, allows(.digits, q) {
            let count = q.act == "plan" ? q.steps.count : q.choices.count
            let verb = q.act == "plan" ? "step" : q.act == "data" ? "copy"
                : togglesChoices(q) ? "toggle" : "pick"
            items.append(("1-\(max(1, min(count, 9)))", verb))
        }
        if let q, allows(.yes, q) {
            items.append(("y", q.choices.first?.label ?? "yes"))
            items.append(("n", q.choices.dropFirst().first?.label ?? "no"))
        }
        if let q, !q.isAnswered, q.status != "elaborate" { items.append(("enter", "submit")) }
        let gated: [(Act, String, String)] = [
            (.type, "i", "type"), (.auto, "A", "auto"), (.several, "m", several.contains(q?.id ?? "") ? "one" : "several"),
            (.skip, "s", "skip"), (.dismiss, "d", q?.act == "data" ? "close" : "dismiss"),
            (.close, "x", "close"), (.clear, "c", "clear"),
            (.elaborate, "e", "elaborate"), (.decompose, "D", "decompose"),
            (.run, "R", "run"), (.copy, "C", "copy"), (.output, "O", "output"),
            (.file, "f", "view"), (.file, "F", "edit"), (.preview, "o", "preview"),
            (.site, "w", "site"), (.poke, "p", "poke"), (.visit, "v", "visit"),
        ]
        for (act, key, label) in gated where allows(act, q) {
            items.append((key, label))
        }
        if q?.status == "elaborate" {
            items.append(("u", "withdraw"))
        } else if !undoStack.isEmpty {
            items.append(("u", "undo"))
        }
        if liveProjects.count > 1 { items.append(("[ ]", "project")) }
        items += [("P", "projects"), ("a", "answers"), ("j/k/tab", "move"), ("esc", "hide")]
        return items
    }

    private var footer: some View {
        KeycapFooter(items: keyBarItems())
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
    /// one, park the old draft, load the new row's, reset picks and row-local
    /// modes, leave the field. The same row keeps its picks and draft across a poll.
    private func rowChanged() {
        let newID = currentQuestion?.id
        guard newID != currentID else { return }
        if let currentID { drafts[currentID] = draft.isEmpty ? nil : draft }
        currentID = newID
        let recommended = currentQuestion?.recommend ?? []
        selectedChoice = recommended.first
        toggled = currentQuestion?.kind == "multi" ? Set(recommended) : []
        draft = newID.flatMap { drafts[$0] } ?? ""
        filePending = nil
        previewFor = nil
        leaveField()
    }

    /// Typing mode off, key focus back on the panel root.
    private func leaveField() {
        fieldFocused = false
        fieldMode = .answer
        hint = ""
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
        if press.key == .escape { return escape() }
        switch page {
        case .projects: return projectsKey(press)
        case .answers: return answersKey(press)
        case .inbox: return inboxKey(press)
        }
    }

    /// Esc: stop a run, disarm `f`, leave a page; else the panel hides it.
    private func escape() -> KeyPress.Result {
        if let execHandle {
            execHandle.cancel()
            flash = "stopping run"
            return .handled
        }
        if filePending != nil {
            filePending = nil
            return .handled
        }
        if page != .inbox {
            page = .inbox
            return .handled
        }
        return .ignored  // the panel's cancelOperation hides it
    }

    private func inboxKey(_ press: KeyPress) -> KeyPress.Result {
        let ch = press.characters
        // An armed `f`/`F` takes the next digit; any other key disarms it.
        if filePending != nil, digit(of: ch) == nil, ch != "f" || filePending != "view" {
            filePending = nil
        }
        // Shift-Tab arrives as the backtab character on macOS.
        if ch == "\u{19}" {
            moveRow(-1)
            return .handled
        }
        switch press.key {
        case .downArrow: moveRow(1); return .handled
        case .upArrow: moveRow(-1); return .handled
        case .tab: moveRow(press.modifiers.contains(.shift) ? -1 : 1); return .handled
        case .return: submitSelection(); return .handled
        default: break
        }
        let q = currentQuestion
        func gate(_ act: Act, _ action: () -> Void) -> KeyPress.Result {
            guard allows(act, q) else { return unbound(ch) }
            action()
            return .handled
        }
        switch ch {
        case "j": moveRow(1); return .handled
        case "k": moveRow(-1); return .handled
        case "[": rotateProject(-1); return .handled
        case "]": rotateProject(1); return .handled
        case "P": openProjects(); return .handled
        case "a": openAnswers(); return .handled
        case "r": poller.refresh(); flash = "refreshed"; return .handled
        case "u":
            if q?.status == "elaborate", let q {
                perform("withdrew request on \(q.key)") { try await cli.elaborate(key: q.address, .withdraw) }
                return .handled
            }
            popUndo()
            return .handled
        case "s": return gate(.skip) { submitSkip() }
        case "c": return gate(.clear) { submitRetire() }
        case "x": return gate(.close) { submitRetire(verb: "closed") }
        case "d": return gate(.dismiss) { dismiss() }
        case "i": return gate(.type) { fieldMode = .answer; fieldFocused = true }
        case "y": return gate(.yes) { pressDigit(1) }
        case "n": return gate(.no) { pressDigit(2) }
        case "m": return gate(.several) { toggleSeveral() }
        case "e": return gate(.elaborate) { fieldMode = .hint; hint = ""; fieldFocused = true }
        case "D": return gate(.decompose) {
            if let q { perform("asked \(q.key) to decompose") { try await cli.elaborate(key: q.address, .decompose) } }
        }
        case "A": return gate(.auto) { acceptAuto() }
        case "p": return gate(.poke) {
            if let q { perform("poked \(q.pane ?? q.agent ?? q.key)", refresh: false) { try await cli.poke(key: q.address) } }
        }
        case "v": return gate(.visit) { visit() }
        case "C": return gate(.copy) {
            copyToClipboard(q?.command ?? "")
            flash = "copied command"
        }
        case "R": return gate(.run) { if let q { startExec(q) } }
        case "O": return gate(.output) { if let log = q?.result?.log { openPath(log, edit: false) } }
        case "f":
            if filePending == "view" { openAllFiles(); return .handled }
            return gate(.file) { startFileAction("view") }
        case "F": return gate(.file) { startFileAction("edit") }
        case "o": return gate(.preview) { togglePreview() }
        case "w": return gate(.site) { if let site = q?.site, let url = URL(string: site) { NSWorkspace.shared.open(url) } }
        default: break
        }
        if let n = digit(of: ch) {
            return allows(.digits, q) && pressDigit(n) ? .handled : unbound(ch)
        }
        return unbound(ch)
    }

    private func digit(of characters: String) -> Int? {
        guard let scalar = characters.unicodeScalars.first,
              let value = scalar.properties.numericValue,
              value >= 1, value <= 9, characters.count == 1 else { return nil }
        return Int(value)
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

    /// A digit: open an armed file, tick a plan step, copy a data chunk,
    /// toggle a multi (or `m`-flipped) choice, approve/deny a run row, else
    /// submit the choice at once with any typed draft (action_select_choice).
    @discardableResult
    private func pressDigit(_ n: Int) -> Bool {
        guard let question = currentQuestion, !question.isAnswered else { return false }
        if let pending = filePending {
            filePending = nil
            guard question.files.indices.contains(n - 1) else { return false }
            openPath(question.files[n - 1], edit: pending == "edit")
            return true
        }
        if question.act == "plan", let step = question.steps.first(where: { $0.n == n }) {
            toggleStep(question, step)
            return true
        }
        guard question.choices.indices.contains(n - 1) else { return false }
        let choice = question.choices[n - 1]
        if question.act == "data" {
            copyToClipboard(choice.description.isEmpty ? choice.label : choice.description)
            record(question, labels: [choice.label], text: "", message: "copied \(choice.label)")
            return true
        }
        if togglesChoices(question) {
            if toggled.contains(choice.label) { toggled.remove(choice.label) } else { toggled.insert(choice.label) }
            return true
        }
        if question.act == "run" && choice.label == "approve" {
            startExec(question)
            return true
        }
        record(question, labels: [choice.label], text: draft)
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

    /// `m`: flip an open single-choice row to pick-several, or back.
    private func toggleSeveral() {
        guard let q = currentQuestion else { return }
        if several.contains(q.id) {
            several.remove(q.id)
            toggled = []
            flash = "pick one"
        } else {
            several.insert(q.id)
            toggled = Set(q.recommend ?? [])
            flash = "pick several"
        }
    }

    /// Enter, outside the field or in it: the pick(s) plus any typed text.
    private func submitSelection() {
        guard let question = currentQuestion else { return }
        if question.isAnswered || question.status == "elaborate" { return }
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
        if togglesChoices(question) {
            labels = question.choices.map(\.label).filter { toggled.contains($0) }
            if labels.isEmpty && draft.isEmpty {
                errorMessage = "nothing toggled"
                return
            }
        } else if let selectedChoice {
            if question.act == "run" && selectedChoice == "approve" && draft.isEmpty {
                startExec(question)
                return
            }
            labels = [selectedChoice]
        } else if draft.isEmpty {
            errorMessage = "no choice selected"
            return
        } else {
            labels = []
        }
        record(question, labels: labels, text: draft)
    }

    /// Answer the row, push it on the undo stack, drop its draft, reload now.
    private func record(_ question: Question, labels: [String], text: String, message: String? = nil) {
        leaveField()
        run({
            try await cli.answer(key: question.address, labels: labels, text: text, skip: false)
        }) {
            undoStack.append(.answer(address: question.address, key: question.key))
            drafts[question.id] = nil
            several.remove(question.id)
            if currentID == question.id { draft = "" }
            flash = message ?? ("recorded " + (labels.isEmpty ? "text" : labels.joined(separator: ", ")))
            poller.refresh()
        }
    }

    /// `A`: accept the auto-decider's proposal, the same path its digit takes.
    private func acceptAuto() {
        guard let q = currentQuestion, let pick = q.auto?.pick,
              q.choices.contains(where: { $0.label == pick }) else { return }
        if q.act == "run" && pick == "approve" {
            startExec(q)
        } else {
            record(q, labels: [pick], text: draft)
        }
    }

    /// `d`: dismiss a notice; a data row closes like `c`.
    private func dismiss() {
        guard let q = currentQuestion else { return }
        if q.act == "data" {
            submitRetire(verb: "closed")
            return
        }
        leaveField()
        run({
            try await cli.answer(key: q.address, labels: [], text: nil, skip: false, dismiss: true)
        }) {
            undoStack.append(.answer(address: q.address, key: q.key))
            flash = "dismissed \(q.key)"
            poller.refresh()
        }
    }

    /// Enter in the hint field: `cactus elaborate KEY HINT`.
    private func submitElaborate() {
        guard let q = currentQuestion else { return }
        let text = hint
        leaveField()
        perform("asked \(q.key) for a rewrite") { try await cli.elaborate(key: q.address, .hint(text)) }
    }

    private func visit() {
        guard let q = currentQuestion else { return }
        run({
            try await cli.visit(key: q.address)
        }) { raiseError in
            flash = "visited \(q.pane ?? q.key)" + (raiseError.map { " (window not raised: \($0))" } ?? "")
        }
    }

    // MARK: files

    /// `f`/`F`: one file opens at once; several arm the next digit.
    private func startFileAction(_ mode: String) {
        guard let q = currentQuestion else { return }
        if q.files.count == 1 {
            openPath(q.files[0], edit: mode == "edit")
        } else {
            filePending = mode
            flash = "\(mode): 1-\(min(q.files.count, 9))" + (mode == "view" ? ", f for all" : "")
        }
    }

    private func openAllFiles() {
        filePending = nil
        for path in currentQuestion?.files ?? [] { openPath(path, edit: false) }
    }

    /// View opens in the file's default app; edit in the default text editor.
    private func openPath(_ path: String, edit: Bool) {
        guard FileManager.default.fileExists(atPath: path) else {
            errorMessage = "missing: \(path)"
            return
        }
        if edit {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
            process.arguments = ["-t", path]
            do { try process.run() } catch { errorMessage = "\(error)" }
            flash = "editing \((path as NSString).lastPathComponent)"
        } else {
            NSWorkspace.shared.open(URL(fileURLWithPath: path))
            flash = "opened \((path as NSString).lastPathComponent)"
        }
    }

    /// `o`: show or hide the inline preview, fetched off the main thread.
    private func togglePreview() {
        guard let q = currentQuestion else { return }
        if previewFor == q.id {
            previewFor = nil
            return
        }
        previewFor = q.id
        previewLines = []
        run({
            try await cli.preview(key: q.address)
        }) { lines in
            if previewFor == q.id { previewLines = lines }
        }
    }

    // MARK: commands

    /// `R` (and approving a run row): stream `cactus exec` into the card.
    private func startExec(_ q: Question) {
        guard execHandle == nil else {
            flash = "a run is already going — esc stops it"
            return
        }
        leaveField()
        let address = q.address
        execOutput[address] = []
        execFor = address
        execHandle = cli.exec(key: address, onLine: { line in
            var lines = execOutput[address] ?? []
            lines.append(line)
            if lines.count > 400 { lines.removeFirst(lines.count - 400) }
            execOutput[address] = lines
        }, onExit: { failure in
            execHandle = nil
            execFor = nil
            if let failure {
                if failure == "cancelled" { flash = "run stopped" } else { errorMessage = failure }
            } else {
                if q.act == "run" { undoStack.append(.answer(address: address, key: q.key)) }
                flash = q.act == "run" ? "approved and ran \(q.key)" : "ran \(q.key)"
            }
            poller.refresh()
        })
    }

    private func copyToClipboard(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    // MARK: undo, skip, retire

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
            several.remove(question.id)
            flash = "skipped \(question.key)"
            poller.refresh()
        }
    }

    private func submitRetire(verb: String = "retired") {
        guard let question = currentQuestion else { return }
        leaveField()
        run({
            try await cli.retire(key: question.address)
        }) {
            undoStack.append(.retire(address: question.address, key: question.key))
            several.remove(question.id)
            flash = "\(verb) \(question.key)"
            poller.refresh()
        }
    }

    // MARK: projects page

    private func openProjects() {
        page = .projects
        projectIndex = projectRows.firstIndex(where: { $0.project == activeProject }) ?? 0
        leaveField()
    }

    private func projectsKey(_ press: KeyPress) -> KeyPress.Result {
        let ch = press.characters
        let rows = projectRows
        let row = rows.indices.contains(projectIndex) ? rows[projectIndex] : nil
        switch press.key {
        case .downArrow: projectIndex = min(max(rows.count - 1, 0), projectIndex + 1); return .handled
        case .upArrow: projectIndex = max(0, projectIndex - 1); return .handled
        case .return:
            guard let row else { return .handled }
            if let pin = effectivePin, pin != row.project {
                flash = "pinned to \((pin as NSString).lastPathComponent) — * unpins"
                return .handled
            }
            currentProject = row.project
            selectedRow = 0
            page = .inbox
            rowChanged()
            return .handled
        default: break
        }
        switch ch {
        case "j": projectIndex = min(max(rows.count - 1, 0), projectIndex + 1)
        case "k": projectIndex = max(0, projectIndex - 1)
        case "P": page = .inbox
        case "a": openAnswers()
        case "r": poller.refresh(); flash = "refreshed"
        case "*":
            guard let row else { return .handled }
            if effectivePin == row.project {
                setPin(nil)
                flash = "unpinned \(row.basename) — all projects"
            } else {
                flash = (effectivePin != nil ? "moved pin to " : "pinned ") + row.basename
                setPin(row.project)
                currentProject = row.project
                selectedRow = 0
            }
        case "I", "A":
            guard let row else { return .handled }
            let action = ch == "I" ? "ignore" : "activate"
            perform("\(row.basename) — \(ch == "I" ? "ignored" : "active")") {
                try await cli.project(action, path: row.project)
            }
        case "p":
            guard let row else { return .handled }
            run({
                try await cli.project("poke", path: row.project)
            }) { text in
                flash = text.isEmpty ? "poked \(row.basename)" : text
            }
        default:
            return unbound(ch)
        }
        return .handled
    }

    private func setPin(_ project: String?) {
        pinned = project
        if let project {
            UserDefaults.standard.set(project, forKey: Self.pinKey)
        } else {
            UserDefaults.standard.removeObject(forKey: Self.pinKey)
        }
    }

    // MARK: answers view

    private func openAnswers() {
        page = .answers
        leaveField()
        loadAnswers(activeProject ?? poller.projects.first?.project)
    }

    private func loadAnswers(_ project: String?) {
        answersProject = project
        answersRows = []
        answersIndex = 0
        answersExpanded = nil
        guard let project else { return }
        answersLoading = true
        run({
            try await cli.history(project: project)
        }) { rows in
            guard answersProject == project else { return }
            answersRows = rows
            answersLoading = false
        }
    }

    private func answersKey(_ press: KeyPress) -> KeyPress.Result {
        let ch = press.characters
        let count = answersRows.count
        switch press.key {
        case .downArrow: answersIndex = min(max(count - 1, 0), answersIndex + 1); return .handled
        case .upArrow: answersIndex = max(0, answersIndex - 1); return .handled
        case .return:
            if answersRows.indices.contains(answersIndex) {
                let id = answersRows[answersIndex].id
                answersExpanded = answersExpanded == id ? nil : id
            }
            return .handled
        default: break
        }
        switch ch {
        case "j": answersIndex = min(max(count - 1, 0), answersIndex + 1)
        case "k": answersIndex = max(0, answersIndex - 1)
        case "a": page = .inbox
        case "P": openProjects()
        case "r": loadAnswers(answersProject)
        case "[", "]":
            // Every known project: a drained project's history is the point.
            let all = poller.projects.map(\.project)
            guard !all.isEmpty else { return .handled }
            let index = all.firstIndex(of: answersProject ?? "") ?? 0
            let next = all[(index + (ch == "]" ? 1 : -1) + all.count) % all.count]
            loadAnswers(next)
        default:
            return unbound(ch)
        }
        return .handled
    }

    // MARK: running CLI calls

    /// A write with a flash on success and a reload.
    private func perform(_ message: String, refresh: Bool = true,
                         _ operation: @escaping () async throws -> Void) {
        leaveField()
        run(operation) {
            flash = message
            if refresh { poller.refresh() }
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

    private func run<T>(_ operation: @escaping () async throws -> T,
                        onSuccess: @escaping (T) -> Void) {
        Task {
            do {
                let value = try await operation()
                onSuccess(value)
            } catch {
                errorMessage = "\(error)"
            }
        }
    }
}
