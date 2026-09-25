// Model.swift — Codable mirrors of `cactus feed --json`, plus the poller.
// Responsibilities:
// - Decode Choice, Question, Cursor, Feed from the CLI's JSON shape.
// - Ignore unknown fields, treat absent optional fields as nil.
// - Poller: ObservableObject that re-polls CactusCLI.feed() on a timer,
//   0.5s while a panel is visible and 5s while hidden, only publishing a
//   fresh `questions` array when the feed's cursor actually moved.

import Foundation

struct Choice: Codable, Identifiable, Hashable {
    var label: String
    var description: String

    var id: String { label }
}

struct Question: Codable, Identifiable, Hashable {
    var id: Int
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

    enum CodingKeys: String, CodingKey {
        case id, key, ref, project, text, context, kind, act, status, choices
        case recommend, confidence
        case recommendWhy = "recommend_why"
        case chosen, blocked, thread, parent, agent
    }

    /// Recommend is emitted by the store as either a bare label (single-select
    /// rows) or a list (multi rows); normalize both into an array so the UI
    /// only ever handles one shape.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
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
    }

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

    private func tick() {
        Task {
            do {
                let feed = try await cli.feed()
                lastError = nil
                if feed.cursor != lastCursor {
                    lastCursor = feed.cursor
                    questions = feed.questions
                }
            } catch {
                lastError = "\(error)"
            }
        }
    }
}
