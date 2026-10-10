// CactusCLI.swift — subprocess bridge to the `cactus` CLI.
// Responsibilities:
// - Resolve the `cactus` binary and the login shell's PATH once, since a GUI
//   app launched outside a terminal gets a bare PATH; every child runs with
//   that PATH so cactus can find herdr, git and kitten.
// - Run every verb the panel needs (feed, projects, history, answer, undo,
//   retire, plan, elaborate, poke, visit, project, preview) as a subprocess
//   off the main thread, mirroring src/cactus/mcp.py: cli.py stays the only
//   validator and the only thing that touches the store.
// - Stream `cactus exec` line by line into a callback, cancellable (kill).
// - Decode stdout with Codable; a non-zero exit throws with the CLI's own
//   stderr line. Exit 3 ("no match") is an empty result where a verb allows it.

import Foundation

struct CactusCLIError: Error, CustomStringConvertible {
    var message: String
    var description: String { message }
}

/// A running `cactus exec`; `cancel()` kills the process.
final class ExecHandle {
    fileprivate let process: Process
    fileprivate(set) var cancelled = false

    fileprivate init(process: Process) {
        self.process = process
    }

    func cancel() {
        cancelled = true
        if process.isRunning { process.terminate() }
    }
}

final class CactusCLI {
    private(set) var binaryPath: String?
    private var resolveError: String?
    private var loginPath: String?

    init() {
        resolveBinary()
    }

    /// Locate `cactus` and the PATH once via a login shell, the same way a
    /// Terminal session would see them.
    private func resolveBinary() {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = ["-lc", "command -v cactus; printf '%s\\n' \"$PATH\""]
        let outPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = Pipe()
        do {
            try process.run()
            process.waitUntilExit()
            let data = outPipe.fileHandleForReading.readDataToEndOfFile()
            let lines = (String(data: data, encoding: .utf8) ?? "")
                .split(separator: "\n").map(String.init)
            if lines.count >= 2 {
                binaryPath = lines[0]
                loginPath = lines[1]
            } else if lines.count == 1, lines[0].hasPrefix("/"), !lines[0].contains(":") {
                binaryPath = lines[0]
            } else {
                resolveError = "cactus not found on PATH"
            }
        } catch {
            resolveError = "failed to resolve cactus binary: \(error)"
        }
    }

    private func makeProcess(_ arguments: [String]) throws -> Process {
        guard let binaryPath else {
            throw CactusCLIError(message: resolveError ?? "cactus binary not resolved")
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: binaryPath)
        process.arguments = arguments
        var env = ProcessInfo.processInfo.environment
        if let loginPath { env["PATH"] = loginPath }
        process.environment = env
        return process
    }

    /// Run `cactus` with the given arguments, returning stdout. Throws with
    /// the CLI's stderr line if the process exits non-zero; exit 3 returns
    /// stdout when `noMatchOK`.
    @discardableResult
    private func run(_ arguments: [String], noMatchOK: Bool = false) throws -> Data {
        let process = try makeProcess(arguments)
        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe
        try process.run()
        let outData = outPipe.fileHandleForReading.readDataToEndOfFile()
        let errData = errPipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        let status = process.terminationStatus
        if status == 3 && noMatchOK { return outData }
        if status != 0 {
            let stderrText = String(data: errData, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let firstLine = stderrText.split(separator: "\n").first.map(String.init)
            throw CactusCLIError(message: firstLine ?? "cactus exited \(status)")
        }
        return outData
    }

    /// `run` off the main thread.
    @discardableResult
    private func call(_ arguments: [String], noMatchOK: Bool = false) async throws -> Data {
        try await Task.detached(priority: .userInitiated) { [self] in
            try run(arguments, noMatchOK: noMatchOK)
        }.value
    }

    func feed() async throws -> Feed {
        let data = try await call(["feed", "--json", "-s", "open,live,elaborate"], noMatchOK: true)
        return try JSONDecoder().decode(Feed.self, from: data)
    }

    func projects() async throws -> [ProjectRow] {
        let data = try await call(["projects", "--json"])
        return try JSONDecoder().decode([ProjectRow].self, from: data)
    }

    /// `cactus history --project P`: answered/cleared rows, newest verdict first.
    func history(project: String) async throws -> [Question] {
        let data = try await call(["history", "--project", project, "--json"], noMatchOK: true)
        if data.isEmpty { return [] }
        return try JSONDecoder().decode([Question].self, from: data)
    }

    /// `cactus answer KEY [TEXT] [-s LABEL]... [--skip | --dismiss]`.
    func answer(key: String, labels: [String], text: String?, skip: Bool,
                dismiss: Bool = false) async throws {
        var arguments = ["answer", key, "--json"]
        for label in labels {
            arguments += ["-s", label]
        }
        if dismiss {
            arguments.append("--dismiss")
        } else if skip {
            arguments.append("--skip")
        }
        if let text, !text.isEmpty {
            arguments += ["--", text]
        }
        try await call(arguments)
    }

    /// `cactus undo KEY`: withdraw the latest answer or verdict (reopen).
    func undo(key: String) async throws {
        try await call(["undo", key, "--json"])
    }

    /// `cactus retire KEY` (the human's clear, no ownership gate), or
    /// `--undo` to restore it.
    func retire(key: String, undo: Bool = false) async throws {
        try await call(["retire", key, "--json"] + (undo ? ["--undo"] : []))
    }

    /// `cactus plan KEY --done N` / `--undone N`: tick or untick a 1-based step.
    func setStep(key: String, n: Int, done: Bool) async throws {
        try await call(["plan", key, done ? "--done" : "--undone", String(n), "--json"])
    }

    enum ElaborateMode { case hint(String), decompose, withdraw }

    /// `cactus elaborate KEY [HINT] | --decompose | --withdraw`.
    func elaborate(key: String, _ mode: ElaborateMode) async throws {
        var arguments = ["elaborate", key, "--json"]
        switch mode {
        case let .hint(text): if !text.isEmpty { arguments += ["--", text] }
        case .decompose: arguments.append("--decompose")
        case .withdraw: arguments.append("--withdraw")
        }
        try await call(arguments)
    }

    /// `cactus poke KEY`: nudge the row's owner at its pane.
    func poke(key: String) async throws {
        try await call(["poke", key, "--json"])
    }

    /// `cactus visit KEY`; returns the window-raise failure, if any.
    func visit(key: String) async throws -> String? {
        let data = try await call(["visit", key, "--json"])
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        return object?["raise_error"] as? String
    }

    /// `cactus project {activate,ignore,poke} --cwd PROJECT`; returns stdout text.
    @discardableResult
    func project(_ action: String, path: String) async throws -> String {
        let data = try await call(["project", action, "--cwd", path])
        return String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    /// `cactus preview KEY`: the `o` block, diff vs HEAD else head per file.
    func preview(key: String) async throws -> [String] {
        let data = try await call(["preview", key, "--json"])
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        return object?["lines"] as? [String] ?? []
    }

    /// `cactus exec KEY`, streamed: each output line reaches `onLine` on the
    /// main actor; `onExit` gets nil on success, else the error line.
    func exec(key: String,
              onLine: @escaping @MainActor (String) -> Void,
              onExit: @escaping @MainActor (String?) -> Void) -> ExecHandle? {
        let process: Process
        do {
            process = try makeProcess(["exec", key])
        } catch {
            Task { @MainActor in onExit("\(error)") }
            return nil
        }
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        let handle = ExecHandle(process: process)
        let buffer = LineBuffer()
        pipe.fileHandleForReading.readabilityHandler = { file in
            let data = file.availableData
            if data.isEmpty {
                file.readabilityHandler = nil
                return
            }
            for line in buffer.feed(data) {
                Task { @MainActor in onLine(line) }
            }
        }
        process.terminationHandler = { proc in
            pipe.fileHandleForReading.readabilityHandler = nil
            let rest = pipe.fileHandleForReading.readDataToEndOfFile()
            var lines = buffer.feed(rest)
            if let tail = buffer.flush() { lines.append(tail) }
            let status = proc.terminationStatus
            let message: String? = handle.cancelled ? "cancelled"
                : (status == 0 ? nil : (lines.last(where: { $0.hasPrefix("cactus:") })
                                        ?? "cactus exec exited \(status)"))
            Task { @MainActor in
                for line in lines { onLine(line) }
                onExit(message)
            }
        }
        do {
            try process.run()
        } catch {
            Task { @MainActor in onExit("\(error)") }
            return nil
        }
        return handle
    }
}

/// Splits a byte stream into complete UTF-8 lines across reads.
private final class LineBuffer: @unchecked Sendable {
    private var pending = Data()
    private let lock = NSLock()

    func feed(_ data: Data) -> [String] {
        lock.lock()
        defer { lock.unlock() }
        pending.append(data)
        var lines: [String] = []
        while let range = pending.firstRange(of: Data([0x0A])) {
            let lineData = pending.subdata(in: pending.startIndex..<range.lowerBound)
            lines.append(String(decoding: lineData, as: UTF8.self))
            pending.removeSubrange(pending.startIndex..<range.upperBound)
        }
        return lines
    }

    func flush() -> String? {
        lock.lock()
        defer { lock.unlock() }
        guard !pending.isEmpty else { return nil }
        let line = String(decoding: pending, as: UTF8.self)
        pending.removeAll()
        return line
    }
}
