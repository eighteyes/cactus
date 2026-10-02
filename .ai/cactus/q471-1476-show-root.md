# q471 — Root toggles sky / birds / cactus: new 'show' panel first on the T page

status: answered
act: steer
kind: choice
thread: show-toggles
agent: 0f4be69e-67e5-485b-a467-0d31810683ad
cwd: .
asked at: 2026-10-02T21:19:42.492924+00:00

## Context

Plan: show_sky / show_birds / show_cactus, "on"/"off" choice levers.

sky off: sky stops advancing and draws blank; hides sky_engine, perspective,
cloud_fade, clouds, projection, wind shear, tone, far/mid/near panels.
birds off: no spawns, flocks aloft cleared; hides birds panel.
cactus off: hides seeds + pile panels (behaviour: see sibling row).

## Files

- /Users/god/projects/cactus/src/cactus/sky.py

## Options

- panel — three on/off keys in sky.toml, first T panel
+ saved slots carry them
+ hiding other T panels falls out of tuning_visible  (doing)
- settings — tui.json toggles on the settings page
- T overlay would read tui settings to hide panels

## Answer

panel
answered at: 2026-10-02T22:00:15.199920+00:00
