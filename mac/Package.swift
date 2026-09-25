// swift-tools-version:5.9
// Package.swift — SwiftPM manifest for the cactus menu-bar app.
// Responsibilities:
// - Declare the `cactus-mac` executable target, macOS 14 minimum.
// - No external dependencies; no strict-concurrency errors under Swift 5 mode.

import PackageDescription

let package = Package(
    name: "cactus-mac",
    platforms: [
        .macOS(.v14)
    ],
    targets: [
        // swift-tools-version 5.9 defaults to the Swift 5 language mode
        // (no strict concurrency checking), so no explicit swiftSettings
        // are needed to avoid strict-concurrency errors.
        .executableTarget(
            name: "cactus-mac"
        )
    ]
)
