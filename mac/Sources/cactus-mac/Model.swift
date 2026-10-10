// Model.swift — Codable mirrors of `cactus feed --json`, plus the poller.
// Responsibilities:
// - Decode Choice, Answer, Review, Step, Question, Cursor, Feed from the CLI's
//   JSON shape (including allow_free, the verdict log, verify block, steps).
// - Ignore unknown fields, treat absent optional fields as nil.
// - AutoPick, RunResult (the row's `auto` and `result` blocks), ProjectRow
//   (`cactus projects --json`).
// - Poller: ObservableObject that re-polls CactusCLI.feed() on a timer,
//   0.5s while a panel is visible and 5s while hidden, only publishing a
//   fresh `questions` array (and re-reading `projects`) when the feed's
//   cursor actually moved.

import Foundation

struct Choice: Codable, Identifiable, Hashable {
    var label: String
    var description: String

    var id: String { label }
}

struct Answer: Codable, Hashable {
    var selected: [String]
    var text: String?
    var skipped: Bool
    var createdAt: String?

    enum CodingKeys: String, CodingKey {
        case selected, text, skipped
        case createdAt = "created_at"
    }

    /// `label — text`, `skipped`, or whichever part exists.
    var summary: String {
        if skipped { return "skipped" }
        let labels = selected.joined(separator: ", ")
        switch (labels.isEmpty, text?.isEmpty ?? true) {
        case (false, false): return "\(labels) — \(text ?? "")"
        case (false, true): return labels
        default: return text ?? ""
        }
    }
}

struct Review: Codable, Hashable {
    var lookAt: String?
    var runCmd: String?
    var passWhen: String?
    var failWhen: String?
    var thenDo: String?

    enum CodingKeys: String, CodingKey {
        case lookAt = "look_at", runCmd = "run_cmd"
        case passWhen = "pass_when", failWhen = "fail_when", thenDo = "then_do"
    }
}

struct Step: Codable, Hashable {
    var n: Int
    var text: String
    var done: Bool
}

/// The auto-decider's proposal: accepted with `A`, never applied on its own.
struct AutoPick: Codable, Hashable {
    var pick: String?
    var confidence: String?
    var reason: String?
}

/// A `run`/review row's captured command outcome.
struct RunResult: Codable, Hashable {
    var exit: Int?
    var tail: [String]?
    var log: String?
}

/// One row of `cactus projects --json`.
struct ProjectRow: Codable, Identifiable, Hashable {
    var project: String
    var enabled: Bool
    var openCount: Int
    var liveCount: Int
    var dueCount: Int
    var staleCount: Int
    var newestOpen: String?
    var lastActivity: String?

    var id: String { project }
    var basename: String { (project as NSString).lastPathComponent }

    enum CodingKeys: String, CodingKey {
        case project, enabled
        case openCount = "open_count", liveCount = "live_count"
        case dueCount = "due_count", staleCount = "stale_count"
        case newestOpen = "newest_open", lastActivity = "last_activity"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        project = try c.decode(String.self, forKey: .project)
        // SQLite hands `enabled` back as 0/1.
        if let flag = try? c.decode(Bool.self, forKey: .enabled) {
            enabled = flag
        } else {
            enabled = (try c.decodeIfPresent(Int.self, forKey: .enabled) ?? 1) != 0
        }
        openCount = try c.decodeIfPresent(Int.self, forKey: .openCount) ?? 0
        liveCount = try c.decodeIfPresent(Int.self, forKey: .liveCount) ?? 0
        dueCount = try c.decodeIfPresent(Int.self, forKey: .dueCount) ?? 0
        staleCount = try c.decodeIfPresent(Int.self, forKey: .staleCount) ?? 0
        newestOpen = try c.decodeIfPresent(String.self, forKey: .newestOpen)
        lastActivity = try c.decodeIfPresent(String.self, forKey: .lastActivity)
    }
}

struct Question: Codable, Identifiable, Hashable {
    var key: String
    var ref: String?
    var project: String
    var text: String
    var context: String?
    var kind: String
    var act: String
    var status: String
    var choices: [Choice]
    var recommend: [String]?
    var confidence: String?
    var recommendWhy: String?
    var chosen: String?
    var blocked: Bool?
    var thread: String?
    var parent: String?
    var agent: String?
    var allowFree: Bool = true
    var updatedAt: String?
    var answers: [Answer] = []
    var review: Review?
    var steps: [Step] = []
    var cwd: String?
    var pane: String?
    var session: String?
    var files: [String] = []
    var site: String?
    var auto: AutoPick?
    var result: RunResult?

    /// Feed rows carry no rowid; `ref` (`LABEL:qN`) is unique across projects,
    /// `key` alone is unique only within one.
    var id: String { ref ?? key }

    enum CodingKeys: String, CodingKey {
        case key, ref, project, text, context, kind, act, status, choices
        case recommend, confidence
        case recommendWhy = "recommend_why"
        case chosen, blocked, thread, parent, agent
        case allowFree = "allow_free"
        case updatedAt = "updated_at"
        case answers, review, steps
        case cwd, pane, session, files, site, auto, result
    }

    /// Recommend is emitted by the store as either a bare label (single-select
    /// rows) or a list (multi rows); normalize both into an array so the UI
    /// only ever handles one shape.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try c.decode(String.self, forKey: .key)
        ref = try c.decodeIfPresent(String.self, forKey: .ref)
        project = try c.decode(String.self, forKey: .project)
        text = try c.decode(String.self, forKey: .text)
        context = try c.decodeIfPresent(String.self, forKey: .context)
        kind = try c.decode(String.self, forKey: .kind)
        act = try c.decode(String.self, forKey: .act)
        status = try c.decode(String.self, forKey: .status)
        choices = try c.decodeIfPresent([Choice].self, forKey: .choices) ?? []
        if let list = try? c.decode([String].self, forKey: .recommend) {
            recommend = list
        } else if let single = try? c.decode(String.self, forKey: .recommend) {
            recommend = [single]
        } else {
            recommend = nil
        }
        confidence = try c.decodeIfPresent(String.self, forKey: .confidence)
        recommendWhy = try c.decodeIfPresent(String.self, forKey: .recommendWhy)
        chosen = try c.decodeIfPresent(String.self, forKey: .chosen)
        blocked = try c.decodeIfPresent(Bool.self, forKey: .blocked)
        thread = try c.decodeIfPresent(String.self, forKey: .thread)
        parent = try c.decodeIfPresent(String.self, forKey: .parent)
        agent = try c.decodeIfPresent(String.self, forKey: .agent)
        allowFree = try c.decodeIfPresent(Bool.self, forKey: .allowFree) ?? true
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt)
        answers = try c.decodeIfPresent([Answer].self, forKey: .answers) ?? []
        review = try c.decodeIfPresent(Review.self, forKey: .review)
        steps = try c.decodeIfPresent([Step].self, forKey: .steps) ?? []
        cwd = try c.decodeIfPresent(String.self, forKey: .cwd)
        pane = try c.decodeIfPresent(String.self, forKey: .pane)
        session = try c.decodeIfPresent(String.self, forKey: .session)
        files = try c.decodeIfPresent([String].self, forKey: .files) ?? []
        site = try c.decodeIfPresent(String.self, forKey: .site)
        auto = try c.decodeIfPresent(AutoPick.self, forKey: .auto)
        result = try c.decodeIfPresent(RunResult.self, forKey: .result)
    }

    /// Persistent rows (review, plan, data) stay `live` and take repeated verdicts.
    var isPersistent: Bool { ["review", "plan", "data"].contains(act) }
    var isAnswered: Bool { status == "answered" }
    /// The row's command: a review's or run row's `run_cmd`.
    var command: String? {
        guard let cmd = review?.runCmd, !cmd.isEmpty else { return nil }
        return cmd
    }
    /// Address a row by `LABEL:qN` so a bare key can't collide across projects.
    var address: String { ref ?? key }

    /// Basename of `project`, for the rail's `project · key · text` line.
    var projectBasename: String {
        (project as NSString).lastPathComponent
    }
}

struct Cursor: Codable, Equatable {
    var maxId: Int?
    var maxUpdated: String?
    var count: Int?

    enum CodingKeys: String, CodingKey {
        case maxId = "max_id"
        case maxUpdated = "max_updated"
        case count
    }
}

struct Feed: Codable {
    var cursor: Cursor
    var questions: [Question]
}

@MainActor
final class Poller: ObservableObject {
    @Published var questions: [Question] = []
    @Published var projects: [ProjectRow] = []
    @Published var lastError: String?

    private var timer: Timer?
    private var lastCursor: Cursor?
    private let cli: CactusCLI

    init(cli: CactusCLI) {
        self.cli = cli
    }

    /// Start polling at the given interval, replacing any existing timer.
    func start(interval: TimeInterval) {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
            guard let self else { return }
            Task { @MainActor in
                self.tick()
            }
        }
        timer?.tolerance = interval * 0.2
        tick()
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    /// Called on panel visibility change: 0.5s while shown, 5s while hidden.
    func setVisible(_ visible: Bool) {
        start(interval: visible ? 0.5 : 5.0)
    }

    /// Poll now, outside the timer: after the app's own write.
    func refresh() {
        tick()
    }

    private func tick() {
        Task {
            do {
                let feed = try await cli.feed()
                lastError = nil
                if feed.cursor != lastCursor {
                    lastCursor = feed.cursor
                    projects = try await cli.projects()
                    questions = feed.questions
                }
            } catch {
                lastError = "\(error)"
            }
        }
    }
}
