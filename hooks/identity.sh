#!/usr/bin/env bash
# identity.sh
# Resolve the cactus --agent value for the current pane; sourced by every hook.
# Responsibilities:
#   - prefer the pane's claude session token via c100-identity, then herdr agent get
#   - fall back to CACTUS_AGENT
#   - print nothing when no identity resolves, so callers can test emptiness

# cactus_resolve_agent: echo the agent id, or nothing.
cactus_resolve_agent() {
  local agent=""
  if [ -n "${HERDR_PANE_ID:-}" ] && command -v herdr >/dev/null 2>&1; then
    # A conversation id is the identity on purpose: it rotates on `claude
    # --resume`, so a stale row goes unowned rather than delivered to whoever
    # sits in the pane next. c100-identity resolves the same tiers; stdout only,
    # its disagreement warning goes to stderr.
    if command -v c100-identity >/dev/null 2>&1; then
      agent=$(c100-identity --resolve 2>/dev/null)
    else
      agent=$(herdr agent get "$HERDR_PANE_ID" 2>/dev/null \
        | jq -r '.result.agent | (.tokens.claude_session_id // .agent_session.value) // empty' 2>/dev/null)
    fi
  fi
  if [ -z "$agent" ] && [ -n "${CACTUS_AGENT:-}" ]; then
    agent="$CACTUS_AGENT"
  fi
  printf '%s' "$agent"
}
