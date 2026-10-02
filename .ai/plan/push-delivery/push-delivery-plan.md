# push-delivery plan

Rule (q462): delivery lives in the receiving client. The webhook map is already
client-declared, so it grows into a per-agent delivery map.

1 map    ~/.config/cactus/poke-webhooks.json entries: webhook (today's shapes) or {"herdr": true}
2 cli    `cactus deliver herdr|webhook URL|off --agent ID` writes/removes the caller's own entry; no db change
3 answer poke_webhook_if_mapped -> delivers herdr entries too: `herdr agent prompt {pane}` with the row's pane
4 hooks  Codex session-start, inside herdr, runs `cactus deliver herdr --agent ID`
5 docs   WEBHOOK_SETUP.md -> delivery; CLAUDE.md q430 "herdr agents are not auto-poked" -> "unless registered"
6 tests  map parse, deliver verb, herdr delivery under an inert transport

Mod sessions register nothing (the mod pulls). Approved q481/q483. Grade B.
