# q397 — rtk proxy grep -n "^GRAVITY\|^SEED_DRAG_THETA\|^LANDING_SECONDS\|^SEED_SPIN_RANGE\|^TICK_SECONDS\|^WIND_COUPLING" src/cactus/field.py; sed -n 58,72p tests/test_field.py; sed -n 1,40p tests/test_puffs.py; rtk proxy grep -n "^def \|^from\|^import" tests/test_puffs.py tests/test_sky.py | head -80

status: answered
act: run
kind: confirm
thread: denied
agent: 275c9c71-be9e-42e8-a2ed-98fbafe29278
cwd: .
asked at: 2026-09-29T20:45:59.185556+00:00

## Context

denied by permission mode

## Options

- approve
- deny

## Answer

approve
answered at: 2026-09-29T20:47:15.323313+00:00

## Result

exit: 0

```
tests/test_sky.py:38:import pytest
tests/test_sky.py:39:from rich.cells import cell_len
tests/test_sky.py:41:from cactus.field import MONO_PLUS
tests/test_sky.py:42:from cactus.sky import (
tests/test_sky.py:64:def _still_config(**overrides) -> GridConfig:
tests/test_sky.py:75:def _tiny_grids(cfg: SkyConfig | None = None, width: int = 2, height: int = 4):
tests/test_sky.py:86:def test_advection_alone_conserves_mass() -> None:
tests/test_sky.py:98:def test_diffusion_is_anisotropic() -> None:
tests/test_sky.py:114:def test_puff_inside_a_band_grows_and_outside_fades() -> None:
tests/test_sky.py:129:def test_shear_moves_bottom_rows_faster_than_top() -> None:
tests/test_sky.py:148:def test_air_d_identity_is_stable_across_ticks_only_resize_rebuilds_it() -> None:
tests/test_sky.py:161:def test_puff_activates_exactly_its_rows_and_neighbours_then_clears() -> None:
tests/test_sky.py:185:def test_inactive_row_far_from_weather_is_never_touched() -> None:
tests/test_sky.py:204:def test_render_uses_at_least_10_distinct_colours() -> None:
tests/test_sky.py:217:def test_frame_time_budget_at_100x20() -> None:
tests/test_sky.py:230:def test_downsample_blank_dither_and_core() -> None:
tests/test_sky.py:247:def test_downsample_mid_density_cell_is_neither_blank_nor_full() -> None:
tests/test_sky.py:255:def test_downsample_fringe_cell_renders_a_speck() -> None:
tests/test_sky.py:263:def test_downsample_colour_follows_the_owning_grids_tone_pair() -> None:
tests/test_sky.py:279:def test_ordered_dither_dot_count_is_monotonic_with_uniform_density() -> None:
tests/test_sky.py:293:def test_braille_bit_order() -> None:
tests/test_sky.py:300:def test_alphabet_glyphs_are_all_single_cell_width() -> None:
tests/test_sky.py:313:def test_overlay_changes_one_key_and_keeps_the_rest() -> None:
tests/test_sky.py:322:def test_overlay_bad_value_raises_naming_the_key() -> None:
tests/test_sky.py:327:def test_overlay_unknown_key_raises_naming_the_key() -> None:
tests/test_sky.py:332:def test_dump_then_load_round_trips(tmp_path) -> None:
tests/test_sky.py:340:def test_load_missing_file_is_defaults(tmp_path) -> None:
tests/test_sky.py:344:def test_dump_of_defaults_has_no_live_lines(tmp_path) -> None:
tests/test_sky.py:359:def test_dump_of_one_changed_key_writes_exactly_that_live_line(tmp_path) -> None:
tests/test_sky.py:377:def test_pile_style_defaults_to_blocks() -> None:
tests/test_sky.py:381:def test_overlay_sets_pile_style() -> None:
tests/test_sky.py:386:def test_overlay_bad_pile_style_raises_naming_the_key() -> None:
tests/test_sky.py:391:def test_dump_then_load_round_trips_pile_style(tmp_path) -> None:
tests/test_sky.py:400:def test_tuning_fields_exposes_pile_style_choices() -> None:
tests/test_sky.py:410:def test_save_slot_then_load_slot_round_trips(tmp_path, monkeypatch) -> None:
tests/test_sky.py:418:def test_load_slot_of_empty_slot_is_none(tmp_path, monkeypatch) -> None:
tests/test_sky.py:423:def test_slot_path_rejects_out_of_range() -> None:
tests/test_sky.py:430:def test_slots_present_reflects_files_on_disk(tmp_path, monkeypatch) -> None:
tests/test_sky.py:442:def test_dump_with_name_round_trips_through_slot_name(tmp_path, monkeypatch) -> None:
tests/test_sky.py:449:def test_slots_reports_none_empty_and_named(tmp_path, monkeypatch) -> None:
tests/test_sky.py:459:def test_slot_with_top_level_name_still_loads(tmp_path, monkeypatch) -> None:
tests/test_sky.py:473:def test_z_is_monotonic_deeper_rows_give_smaller_z() -> None:
tests/test_sky.py:485:def test_rows_at_or_above_the_horizon_are_open_sky() -> None:
tests/test_sky.py:494:def test_rows_above_horizon_render_blank_sky() -> None:
tests/test_sky.py:504:def test_camera_drift_moves_a_near_z_marker_more_than_a_far_z_marker() -> None:
tests/test_sky.py:535:def test_frame_time_budget_at_100x20_with_perspective() -> None:
tests/test_sky.py:548:def test_sky_engine_defaults_to_texture() -> None:
tests/test_sky.py:552:def test_make_sky_texture_returns_texture_sky_behind_the_same_interface() -> None:
tests/test_sky.py:573:def test_both_engines_stay_inside_the_frame_time_budget_at_100x20(engine: str) -> None:
— exit 0 —
```

log: /var/folders/vy/jl7086td5nv4_6ms16c6g1rr0000gn/T/cactus-q397-b_1778ff.log
