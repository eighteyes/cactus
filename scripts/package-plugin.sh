#!/usr/bin/env bash
# package-plugin.sh — build the Claude Desktop plugin bundle.
#
# Responsibilities:
# - Zip the plugin tree (.claude-plugin manifest, .mcp.json, server launcher,
#   hooks, skills, src) with the manifest at the archive root, which is what
#   Claude Desktop's plugin installer requires.
# - Name the archive dist/cactus-<version>.plugin from plugin.json's version.
# - Leave out bin/: Claude Desktop refuses a plugin with a top-level bin/.
# - Leave out everything else that is not part of the plugin: caches, the Codex
#   plugin copy, demo assets, working notes, git metadata.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$root"

version=$(python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])')
out="dist/cactus-${version}.plugin"
mkdir -p dist
rm -f "$out"

zip -q -r "$out" \
  .claude-plugin/plugin.json \
  .mcp.json \
  server \
  hooks \
  skills \
  src/cactus \
  README.md \
  LICENSE \
  -x '*/__pycache__/*' '*.pyc' '*.db' '*.db-wal' '*.db-shm' '.DS_Store'

echo "$out"
unzip -l "$out" | tail -1
