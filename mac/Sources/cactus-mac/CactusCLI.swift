// CactusCLI.swift — subprocess bridge to the `cactus` CLI.
// Responsibilities:
// - Resolve the `cactus` binary once, via a login-shell PATH lookup, since a
//   GUI app launched outside a terminal gets a bare PATH.
// - Run `feed`, `answer`, `undo`, and `clear` as subprocesses with `--json`, mirroring
//   the precedent in src/cactus/mcp.py: cli.py stays the only validator.
// - Decode stdout with Codable; a non-zero exit throws with the CLI's own
//   stderr line rather than the process's exit code alone.

import Foundation

struct CactusCLIError: Error, CustomStringConvertible {
    var message: String
    var description: String { message }
}

final class CactusCLI {
    private(set) var binaryPath: String?
    private var resolveError: String?

    init() {
        resolveBinary()
    }

    /// Locate `cactus` once via a login shell, the same way a Terminal
    /// session would see it — launchd/GUI processes do not source the
    /// user's shell rc files, so `Process`'s own PATH is typically bare.
    private func resolveBinary() {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = ["-lc", "command -v cactus"]
        let outPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = Pipe()
        do {
            try process.run()
            process.waitUntilExit()
            let data = outPipe.fileHandleForReading.readDataToEndOfFile()
            let path = String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if let path, !path.isEmpty {
                binaryPath = path
            } else {
                resolveError = "cactus not found on PATH"
            }
        } catch {
            resolveError = "failed to resolve cactus binary: \(error)"
        }
    }

    /// Run `cactus` with the given arguments, returning stdout. Throws with
    /// the CLI's stderr line (its contract for `cactus: ...` messages) if the
    /// process exits non-zero.
    @discardableResult
    private func run(_ arguments: [String]) throws -> Data {
        guard let binaryPath else {
            throw CactusCLIError(message: resolveError ?? "cactus binary not resolved")
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: binaryPath)
        process.arguments = arguments
        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe
        try process.run()
        let outData = outPipe.fileHandleForReading.readDataToEndOfFile()
        let errData = errPipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        if process.terminationStatus != 0 {
            let stderrText = String(data: errData, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let firstLine = stderrText.split(separator: "\n").first.map(String.init)
            throw CactusCLIError(message: firstLine ?? "cactus exited \(process.terminationStatus)")
        }
        return outData
    }

    func feed() async throws -> Feed {
        try await Task.detached(priority: .utility) { [self] in
            let data = try run(["feed", "--json", "-s", "open,live,elaborate,answered"])
            return try JSONDecoder().decode(Feed.self, from: data)
        }.value
    }

    /// `cactus answer KEY [TEXT] [-s LABEL]... [--skip]`.
    func answer(key: String, labels: [String], text: String?, skip: Bool) async throws {
        var arguments = ["answer", key, "--json"]
        for label in labels {
            arguments += ["-s", label]
        }
        if skip {
            arguments.append("--skip")
        }
        if let text, !text.isEmpty {
            arguments += ["--", text]
        }
        _ = try await Task.detached(priority: .utility) { [self] in
            try run(arguments)
        }.value
    }

    /// `cactus undo KEY`: withdraw the latest answer or verdict (reopen).
    func undo(key: String) async throws {
        _ = try await Task.detached(priority: .utility) { [self] in
            try run(["undo", key, "--json"])
        }.value
    }

    func clear(key: String) async throws {
        _ = try await Task.detached(priority: .utility) { [self] in
            try run(["clear", key])
        }.value
    }
}
