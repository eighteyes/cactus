# Projects pane and project-level disablement

## Goal

Extend the Cactus Textual TUI with a distinct Projects pane and a durable,
per-project Cactus enablement setting.

## TUI

- Add a Projects pane, opened with `Shift+P` (`P`).
- The pane lists known projects, including projects with no currently actionable
  rows, and shows whether Cactus is active or ignored for each one.
- Within the Projects pane:
  - `I` ignores/disables the highlighted project.
  - `A` activates/enables the highlighted project.
  - Navigation and selection return to the normal inbox/project view as
    appropriate.
- Do not let the Projects shortcut or its pane actions fire while a free-text
  input or elaborate-input is focused.
- Enable signposts in agent-facing prose and questions, following
  `~/ai/systemCLAUDE.md`: render the steering letter(s) in backticks followed by
  the rest of the word, such as `P`rojects and `I`gnore.

## Project-level disablement

- Persist whether Cactus is disabled per project.
- Ignoring a project disables Cactus hooks for that project.
- Activating it restores normal hook behavior.
- Provide a CLI escape hatch for a disabled project: `cactus project activate`
  (with `project ignore` and `project status` for symmetry).
- When a hook runs in a disabled project, it must not create, inject, block on,
  or otherwise drive Cactus behavior; it should clearly tell the agent that
  Cactus is disabled for this project and that activation is available from the
  Projects pane.
- Apply this consistently to every Codex plugin hook: SessionStart,
  UserPromptSubmit, PermissionRequest, and Stop.

## Agent ownership

- Require `--agent` for every new agent-owned row. `run` already requires it;
  make `ask` require it too.
- Existing rows and read-only commands remain usable.

## Delivery constraints

- Preserve unrelated dirty worktree changes.
- Add focused tests for state persistence, TUI key routing, and hook/CLI behavior.
- Independently review the resulting diff with the active Claude session before
  committing.
