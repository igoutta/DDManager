"""Every feature of the plan's parity checklist (P01-P30) maps to tests that exist and always run.

``CHECKLIST`` is the table: an id, then ``tests/<file>::<function>`` node ids.  The checks fail
when an id is missing or unmapped, when a mapped file or function does not exist, when a node is
not a top-level ``test_*`` function, or when it could silently not run (skip / skipif / xfail,
or the ``legacy`` oracle marker, which skips where git history or tkinter is unavailable).
"""

import ast
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent
FORBIDDEN_MARKS = frozenset({"skip", "skipif", "xfail", "legacy"})


def nodes(path: str, *names: str) -> tuple[str, ...]:
    return tuple(f"tests/{path}::{name}" for name in names)


UI = "ui/test_"
SERVICES = "services/test_"
CORE = "core/test_"

CHECKLIST: dict[str, tuple[str, ...]] = {
    # ---------------------------------------------------------------- M4: the main window
    "P01": (
        *nodes(
            f"{UI}parity_gaps.py",
            "test_p01_three_panes_left_to_right_available_load_order_details",
            "test_p01_the_button_column_is_the_six_shared_actions_in_order",
            "test_p01_enable_appends_the_selected_available_mods_and_disable_removes_them",
        ),
        *nodes(
            f"{UI}main_window_smoke.py",
            "test_window_builds_with_the_three_panes_and_a_hidden_health_dock",
        ),
    ),
    "P02": (
        *nodes(
            f"{UI}load_order_model.py",
            "test_drop_emits_move_request_and_leaves_the_model_to_the_controller",
            "test_available_payload_requests_enable",
            "test_mime_data_dedupes_sorts_and_stamps_pid",
            "test_model_matches_core_move_to_over_300_seeded_drops",
        ),
        *nodes(
            f"{UI}available_proxy.py",
            "test_load_order_drop_requests_disable",
            "test_drag_from_a_filtered_view_carries_source_ids",
        ),
        *nodes(
            f"{UI}parity_gaps.py",
            "test_p02_the_drag_badge_is_a_pill_that_grows_with_its_label",
            "test_p02_the_load_order_draws_its_drop_position_as_one_row_line",
        ),
    ),
    "P03": nodes(
        f"{UI}parity_gaps.py",
        "test_p03_both_lists_use_extended_selection",
        "test_p03_shift_selects_a_range_and_ctrl_toggles_single_rows",
    ),
    "P04": (
        *nodes(f"{UI}available_proxy.py", "test_check_state_toggle_emits_toggle_requested"),
        *nodes(f"{UI}parity_gaps.py", "test_p04_activating_an_available_row_enables_it"),
    ),
    "P05": (
        *nodes(
            f"{UI}shortcuts.py",
            "test_expected_global_shortcuts_exist",
            "test_move_actions_are_scoped_to_the_list",
            "test_ctrl_up_key_event_moves_the_selected_row",
            "test_no_duplicate_key_sequence_within_a_context",
        ),
        *nodes(
            f"{UI}parity_gaps.py",
            "test_p05_space_enables_in_available_and_disables_in_the_load_order",
            "test_p05_delete_disables_the_selection_of_the_load_order",
        ),
    ),
    "P06": nodes(
        f"{UI}controller.py",
        "test_guarded_disable_prompts_once_and_respects_no",
        "test_guarded_disable_proceeds_on_yes_and_skips_the_prompt_for_other_mods",
        "test_guarded_undo",
    ),
    # ---------------------------------------------------------------- M5: labels and categories
    "P07": (
        *nodes(
            f"{UI}categories_dialog.py",
            "test_assigning_writes_the_category_and_remembers_it_for_every_identity_key",
            "test_assigning_to_several_mods_at_once_and_a_custom_category",
            "test_unassigning_removes_the_category",
            "test_the_assign_submenu_lists_the_categories_then_unassigned_and_assigns",
            "test_assign_needs_a_selection_and_both_lists_offer_it_in_their_context_menu",
        ),
        *nodes(f"{UI}nickname.py", "test_the_action_opens_the_dialog_for_the_single_selected_mod"),
        "tests/plugins/test_sources.py::test_page_urls",
        "tests/services/test_platform_actions.py::test_open_url_uses_the_injected_opener",
    ),
    "P08": (
        *nodes(
            f"{UI}parity_gaps.py",
            "test_p08_a_row_shows_the_nickname_the_tier_badge_and_the_category",
            "test_p08_a_mod_that_appears_on_disk_is_new_appended_disabled_and_nothing_resorts",
            "test_p08_the_new_pill_changes_what_the_row_paints",
            "test_p08_the_new_pill_expires_after_the_highlight_window_without_a_resort",
            "test_p08_a_scan_that_finds_nothing_new_ends_the_pill_and_its_timer",
        ),
        *nodes(f"{UI}load_order_model.py", "test_data_roles_for_every_column"),
        *nodes(
            f"{CORE}identity.py",
            "test_display_name_rules",
            "test_display_suffix_and_name_with_suffix",
        ),
    ),
    "P09": (
        *nodes(
            f"{UI}available_proxy.py",
            "test_query_is_a_casefolded_token_and",
            "test_tier_and_source_filters",
        ),
        *nodes(f"{UI}main_window_smoke.py", "test_search_box_is_debounced"),
    ),
    "P10": (
        *nodes(
            f"{UI}density.py",
            "test_the_four_canonical_modes_and_their_sizes",
            "test_choosing_a_mode_persists_it_under_its_canonical_key",
            "test_the_load_order_rows_take_the_mode_height_and_icon_size",
            "test_the_available_rows_take_the_mode_height_but_never_less_than_two_lines",
            "test_the_model_asks_for_thumbnails_of_the_mode_size_or_none",
            "test_a_window_opened_on_a_saved_mode_starts_in_it",
        ),
        *nodes(f"{UI}theme.py", "test_density_modes"),
    ),
    "P11": nodes(
        f"{UI}thumbnails.py",
        "test_decodes_and_caches_scaled",
        "test_content_is_sniffed_not_the_extension",
        "test_threaded_decode_returns_to_the_gui_thread",
    ),
    "P12": (
        *nodes(
            f"{UI}categories_dialog.py",
            "test_the_list_shows_every_category_in_editor_order_built_in_ones_marked",
            "test_up_and_down_move_the_selected_row_and_keep_it_selected",
            "test_dragging_a_row_reorders_the_draft_and_save_persists_it",
            "test_set_color_stores_uppercase_hex_starting_from_the_current_color",
            "test_reset_color_drops_the_override",
            "test_add_appends_a_custom_category_with_the_chosen_color",
            "test_rename_moves_the_assignments_color_and_memory_to_the_new_name",
            "test_built_in_categories_can_be_moved_but_not_renamed_or_removed",
            "test_remove_unassigns_its_mods_and_purges_the_memory_after_confirming",
            "test_nothing_is_written_until_save_and_then_it_is_one_change",
            "test_cancel_discards_every_edit",
            "test_after_save_the_rows_tiers_and_colors_follow",
        ),
        *nodes(
            f"{CORE}categories.py",
            "test_apply_changes_rename_then_remove_unassigns_and_purges_memory",
        ),
    ),
    "P13": nodes(
        f"{UI}paths_dialog.py",
        "test_the_editor_has_the_five_legacy_keys_in_legacy_order",
        "test_clear_empties_only_its_own_field",
        "test_auto_fills_each_field_from_a_fresh_detection_without_manual_overrides",
        "test_browse_picks_a_folder_starting_near_the_current_value",
        "test_save_writes_the_five_keys_and_the_last_save_then_rescans_with_them",
        "test_cancel_writes_nothing_and_does_not_rescan",
    ),
    "P14": nodes(
        f"{UI}paths_dialog.py",
        "test_auto_detect_adopts_the_best_mods_folder_and_newest_save_and_shows_the_summary",
        "test_auto_detect_with_nothing_found_explains_and_changes_nothing",
        "test_a_valid_mods_folder_starts_silently",
        "test_without_a_mods_folder_the_first_run_detects_one_and_shows_the_summary_once",
    ),
    "P15": (
        *nodes(
            f"{UI}dialogs.py",
            "test_profile_manager_has_three_tabs",
            "test_profile_manager_lists_the_detected_slot",
        ),
        *nodes(f"{SERVICES}save_slots.py", "test_label_shapes_without_the_oracle"),
        *nodes(f"{SERVICES}profiles.py", "test_import_of_an_exported_document"),
        *nodes(
            f"{UI}controller.py", "test_patch_save_applies_after_confirmation_and_records_paths"
        ),
    ),
    "P16": (
        *nodes(
            f"{SERVICES}save_patch.py",
            "test_apply_patches_backs_up_and_verifies",
            "test_risks_become_required_acknowledgements",
            "test_missing_acknowledgements_block_apply",
        ),
        *nodes(f"{UI}controller.py", "test_patch_save_cancel_never_applies"),
        *nodes(
            f"{UI}dialogs.py",
            "test_patch_preview_requires_every_ack_before_the_primary_button",
        ),
        *nodes(
            f"{UI}patch_targets.py",
            "test_patch_other_file_asks_for_a_file_and_previews_a_patch_of_it",
            "test_cancelling_the_file_picker_patches_nothing",
            "test_a_non_default_filename_requires_its_acknowledgement_in_the_preview",
            "test_the_default_filename_needs_no_such_acknowledgement",
            "test_patch_latest_detected_confirms_the_newest_detected_save_then_previews_it",
            "test_declining_the_confirmation_patches_nothing",
            "test_with_no_detected_save_file_it_explains_and_patches_nothing",
            "test_both_are_tools_menu_items_with_their_own_tooltips_in_every_language",
        ),
    ),
    "P17": (
        *nodes(
            f"{UI}save_code_dialog.py",
            "test_the_text_is_shown_verbatim_and_read_only",
            "test_copy_puts_the_exact_text_on_the_clipboard",
            "test_the_action_builds_the_block_of_the_enabled_mods_in_load_order",
        ),
        *nodes("core/saves/test_applied_text.py", "test_layout_for_plain_names"),
    ),
    "P18": (
        *nodes(
            f"{UI}apply_order_flow.py",
            "test_the_preview_lists_every_folder_old_and_new_and_the_count",
            "test_the_renamer_gets_the_plan_core_computes_for_the_current_order",
            "test_accepting_rekeys_order_enabled_categories_nicknames_and_attempted",
            "test_nicknames_survive_the_rename",
            "test_a_failed_rename_is_reported_with_the_stuck_folders_and_changes_no_state",
        ),
        *nodes(
            f"{CORE}folder_order.py", "test_prefixes_are_monotonic_positions_over_random_orders"
        ),
        *nodes(
            f"{SERVICES}folder_renamer.py",
            "test_swaps_and_chains_work_because_of_the_two_phases",
            "test_a_failed_rollback_reports_the_stuck_folders",
        ),
    ),
    "P19": (
        *nodes(
            f"{UI}backups_tab.py",
            "test_managed_and_legacy_backups_are_listed_newest_first_with_their_details",
            "test_restore_asks_first_and_names_the_file",
            "test_restore_replaces_the_active_save_with_the_selected_backup",
            "test_a_refused_restore_is_reported_and_remembers_nothing",
            "test_open_folder_shows_the_backup_folder_of_the_slot",
        ),
        *nodes(
            f"{SERVICES}backup.py",
            "test_restore_writes_the_backup_and_takes_a_pre_restore_copy",
            "test_restore_of_invalid_bytes_leaves_the_target_untouched",
        ),
    ),
    "P20": (
        *nodes(
            f"{UI}diagnostics_dialog.py",
            "test_the_report_is_shown_verbatim_read_only_and_selectable",
            "test_check_setup_reports_the_facts_of_the_session",
            "test_the_report_matches_the_pure_builder_line_for_line",
            "test_copy_debug_info_copies_the_same_text_without_opening_a_dialog",
        ),
        *nodes(
            f"{CORE}diagnostics.py",
            "test_every_fact_is_rendered",
            "test_lines_are_label_value_pairs",
        ),
    ),
    "P21": (
        *nodes(
            f"{UI}platform_actions.py",
            "test_launch_starts_the_game_with_the_detected_install",
            "test_open_local_mods_shows_the_first_local_mods_folder",
            "test_a_failed_launch_is_a_notice_not_a_crash",
        ),
        *nodes(
            f"{SERVICES}platform_actions.py", "test_windows_launches_through_the_steam_protocol"
        ),
    ),
    "P22": (
        *nodes(
            f"{UI}auto_categorize.py",
            "test_it_assigns_every_confident_suggestion_to_the_unassigned_mods",
            "test_it_uses_the_nickname",
            "test_the_summary_counts_assigned_and_ambiguous",
            "test_it_never_reorders_and_pushes_no_undo_step",
            "test_the_start_up_classifier_assigns_and_remembers_but_never_reorders",
        ),
        *nodes(
            f"{UI}controller.py",
            "test_auto_sort_apply_is_one_undo_command",
            "test_silent_classify_never_reorders",
        ),
        *nodes(
            f"{CORE}sorting.py", "test_no_edges_seeded_weights_are_monotone_and_ties_are_stable"
        ),
    ),
    "P23": nodes(
        f"{UI}nickname.py",
        "test_a_nickname_replaces_the_title_everywhere_the_row_shows_it",
        "test_the_default_display_name_clears_an_existing_nickname",
        "test_the_default_display_name_without_a_nickname_changes_nothing",
        "test_enter_accepts_and_the_text_is_collapsed",
        "test_the_action_opens_the_dialog_for_the_single_selected_mod",
    ),
    "P24": (
        *nodes(
            f"{UI}i18n_parity.py",
            "test_the_key_set_equals_the_english_key_set",
            "test_every_key_has_exactly_the_english_placeholders",
            "test_every_button_of_every_m5_dialog_has_a_tooltip_in_each_language",
        ),
        *nodes(
            f"{UI}retranslate.py",
            "test_every_label_of_the_window_follows_the_language",
            "test_switching_back_to_english_restores_every_text",
            "test_choosing_the_language_action_switches_checks_and_persists_it",
        ),
        *nodes(f"{UI}translator.py", "test_set_language_emits_and_switches"),
    ),
    "P25": (
        *nodes(
            f"{UI}duplicate_warning.py",
            "test_a_pair_with_both_copies_enabled_gets_one_warning_after_the_first_scan",
            "test_the_warning_is_shown_only_once",
            "test_a_long_list_is_cut_at_three_pairs_with_the_rest_counted",
        ),
        *nodes(
            f"{UI}exception_hooks.py",
            "test_uncaught_exception_is_logged_and_shown_once_on_the_gui_thread",
        ),
    ),
    "P26": nodes(
        f"{UI}status_bar.py",
        "test_profile_label_is_shown",
        "test_never_backed_up_shows_never_and_a_known_backup_shows_time_and_age",
        "test_counts_are_rendered_and_clicking_them_opens_the_health_dock",
        "test_transient_messages_never_clobber_permanent_widgets",
    ),
    "P27": (
        *nodes(
            f"{UI}load_order_model.py",
            "test_internal_move_keeps_relative_order_and_persistent_indexes",
            "test_large_permutation_keeps_selection_by_id",
        ),
        *nodes(
            f"{UI}parity_gaps.py",
            "test_p27_the_selection_survives_a_rescan_and_a_renamed_mod_gets_selected",
            "test_p27_a_move_keeps_the_moved_rows_selected",
        ),
    ),
    "P28": nodes(
        f"{UI}theme.py",
        "test_palette_keeps_the_verbatim_legacy_colors",
        "test_apply_theme_sets_fusion_palette_and_stylesheet",
        "test_every_known_tier_has_a_token_and_contrasts_with_panel_and_field",
        "test_render_qss_is_complete",
    ),
    "P29": (
        *nodes(
            f"{UI}legacy_loadout_import.py",
            "test_the_order_is_previewed_and_adopted_as_one_undoable_change",
            "test_nicknames_categories_and_memory_are_applied_after_the_preview",
            "test_declining_the_preview_applies_nothing_at_all",
            "test_a_file_that_is_not_a_loadout_is_refused_with_an_error",
        ),
        *nodes(f"{SERVICES}profiles.py", "test_import_of_a_legacy_loadout"),
    ),
    "P30": (
        *nodes(
            f"{SERVICES}app_paths.py",
            "test_frozen_uses_existing_portable_dir_beside_the_exe",
            "test_source_run_anchors_at_the_repo_root",
            "test_existing_unwritable_portable_dir_is_an_error_and_never_forks_state",
        ),
        *nodes(
            f"{SERVICES}state_repo.py",
            "test_round_trip_keeps_all_22_keys_unknown_keys_and_key_order",
            "test_save_rotates_the_previous_main_into_the_backup",
            "test_corrupt_main_recovers_from_backup_and_is_never_rotated_over_it",
            "test_conflict_when_the_file_changed_underneath",
            "test_failed_write_leaves_the_state_file_untouched",
        ),
        *nodes(f"{UI}controller.py", "test_can_close_flushes_the_pending_state_write"),
        *nodes(
            f"{UI}forget_missing.py",
            "test_absent_mods_are_kept_as_missing_rows_never_pruned",
            "test_confirming_removes_exactly_the_missing_mods_as_one_undoable_change",
        ),
    ),
}

PLAN_IDS = tuple(f"P{number:02d}" for number in range(1, 31))


@cache
def top_level_tests(relative_file: str) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """The ``test_*`` functions defined directly in the module (parsed, not imported)."""
    tree = ast.parse((ROOT / relative_file).read_text(encoding="utf-8"), filename=relative_file)
    return {
        item.name: item
        for item in tree.body
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
        and item.name.startswith("test_")
    }


def marks_of(decorators: list[ast.expr]) -> set[str]:
    """Names of ``pytest.mark.<name>`` decorators (called or not)."""
    names: set[str] = set()
    for decorator in decorators:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Attribute)
            and target.value.attr == "mark"
        ):
            names.add(target.attr)
    return names


def module_marks(relative_file: str) -> set[str]:
    tree = ast.parse((ROOT / relative_file).read_text(encoding="utf-8"))
    for item in tree.body:
        if isinstance(item, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in item.targets
        ):
            values = (
                item.value.elts if isinstance(item.value, ast.List | ast.Tuple) else [item.value]
            )
            return marks_of(list(values))
    return set()


def split(node: str) -> tuple[str, str]:
    path, _, name = node.partition("::")
    return path, name


# ---------------------------------------------------------------------------- the table


def test_the_table_has_exactly_the_ids_of_the_plan_each_with_a_test():
    assert tuple(sorted(CHECKLIST)) == PLAN_IDS
    empty = [pid for pid, mapped in CHECKLIST.items() if not mapped]
    assert empty == [], f"unmapped checklist ids: {empty}"


def test_node_ids_are_well_formed_and_not_repeated():
    for pid, mapped in CHECKLIST.items():
        assert len(set(mapped)) == len(mapped), f"{pid} lists a test twice"
        for node in mapped:
            path, name = split(node)
            assert path.startswith("tests/") and path.endswith(".py"), (pid, node)
            assert name.startswith("test_"), (pid, node)
            assert "::" not in name and "[" not in name, (pid, node)


@pytest.mark.parametrize("pid", PLAN_IDS)
def test_every_mapped_test_exists_and_always_runs(pid):
    problems: list[str] = []
    for node in CHECKLIST[pid]:
        path, name = split(node)
        if not (ROOT / path).is_file():
            problems.append(f"{node}: no such file")
            continue
        found = top_level_tests(path).get(name)
        if found is None:
            problems.append(f"{node}: no top-level function {name!r} in {path}")
            continue
        forbidden = (marks_of(found.decorator_list) | module_marks(path)) & FORBIDDEN_MARKS
        if forbidden:
            problems.append(f"{node}: marked {sorted(forbidden)} (could silently not run)")
    assert problems == [], f"{pid}:\n  " + "\n  ".join(problems)


def test_the_mapped_functions_can_be_imported_from_their_modules():
    """The same check through the import system for the UI tests (collected, so importable)."""
    import importlib

    for mapped in CHECKLIST.values():
        for node in mapped:
            path, name = split(node)
            if not path.startswith("tests/ui/"):
                continue
            module = importlib.import_module(path.removesuffix(".py").replace("/", "."))
            function = getattr(module, name, None)
            assert callable(function), node
            assert function.__module__ == module.__name__, f"{node} is imported, not defined"
