# q539 — test "${HERDR_ENV:-}" = 1 && herdr agent list && printf '\n--- changed auto-decider files ---\n' && git diff -- src/cactus/rank.py src/cactus/decide.py src/cactus/clef_serve.py src/cactus/store.py src/cactus/tui.py src/cactus/cli.py tests/test_rank.py tests/test_tui.py && printf '\n--- committed auto-decider history ---\n' && git log --oneline --all --decorate -20 -- src/cactus/rank.py src/cactus/decide.py src/cactus/clef_serve.py && printf '\n--- plan status ---\n' && rg -n -i "status|done|complete|implemented|phase|auto-decider" .ai/plan/auto-decider --glob '*.md'

status: answered
act: run
kind: confirm
agent: 01a10a5d-7895-7a11-92ab-78c340e9eaae
cwd: .
asked at: 2026-10-05T04:41:58.546596+00:00

## Context

May I inspect the active Herdr agent session and the repository's local auto-decider changes to verify whether the feature has landed?

## Options

- approve
- deny

## Answer

approve
answered at: 2026-10-05T04:42:54.587422+00:00

## Result

exit: 0

```
     def _flash_field(self, message: str | None) -> None:
diff --git a/tests/test_tui.py b/tests/test_tui.py
index 3d5eda6..3352944 100644
--- a/tests/test_tui.py
+++ b/tests/test_tui.py
@@ -2943,3 +2943,36 @@ async def test_empty_flipped_submit_is_refused(store: Store, project: str) -> No
         await pilot.pause()
         assert app.flash
     assert store.get(q.key, project=project).status == "open"
+
+
+async def test_tui_answer_queues_no_pending_seed(store: Store, project: str) -> None:
+    store.ask(
+        "pick one", project=project, cwd=project, agent=AGENT,
+        kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
+    )
+    app = CactusApp(store, project=project)
+    async with app.run_test() as pilot:
+        await pilot.pause()
+        await pilot.press("1")
+        await pilot.pause()
+        assert len(app.world.seeds) == 1
+        assert garden.pending_count(store.path) == 0
+
+
+async def test_inline_field_claims_pending_seeds_and_caps(store: Store, project: str) -> None:
+    from cactus.fieldproc import PENDING_SEED_CAP
+
+    app = CactusApp(store, project=project)
+    async with app.run_test() as pilot:
+        await pilot.pause()
+        base = len(app.world.seeds)
+        garden.add_pending(store.path, 3)
+        app._sky_reload_last = None
+        app._field_tick()
+        assert len(app.world.seeds) == base + 3
+        assert garden.pending_count(store.path) == 0
+
+        garden.add_pending(store.path, PENDING_SEED_CAP + 5)
+        app._sky_reload_last = None
+        app._field_tick()
+        assert garden.pending_count(store.path) == 5

--- committed auto-decider history ---
985c413 Decider backends: clef-flash beside strands-decider; cactus decider start/status/stop
905fee6 Auto-decider core: rank gate, strands-decider client, auto_* columns

--- plan status ---
.ai/plan/auto-decider/auto-decider-plan.md:1:# auto-decider
— exit 0 —
```

log: /var/folders/vy/jl7086td5nv4_6ms16c6g1rr0000gn/T/cactus-q539-nopcd1po.log
