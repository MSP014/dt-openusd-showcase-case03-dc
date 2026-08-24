# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Focused shell coverage for draft-only Heatmap settings controls."""

from __future__ import annotations

from pathlib import Path


def test_heatmap_ui_has_one_test_action_and_draft_settings_apply_boundary() -> None:
    source = _ui_path().read_text(encoding="utf-8")

    assert '"Test Heatmaps"' in source
    assert '"Restore Heatmap Test"' in source
    assert '"Freeze Heatmap Presentation"' not in source
    assert '"Resume Heatmap Presentation"' not in source
    assert '"Apply Heatmaps Settings"' in source
    assert '"Isolation"' in source
    assert '"X-Ray Overlay"' in source
    assert '"Calibration"' in source
    assert '"Color Scale"' in source
    assert '"Confirm"' not in source
    assert '"Failure"' not in source
    assert "clicked_fn=self._apply_heatmap_settings" in source
    assert "toggle_heatmap_test_presentation_writes" not in source
    assert "def _heatmap_settings_from_draft" in source
    assert "format_dtrs_status_block(" in source
    assert "carb.log_warn(" in source
    assert '"TEST HEATMAPS"' in source
    assert '"APPLY HEATMAP SETTINGS"' in source


def test_heatmap_sections_start_collapsed_and_apply_preserves_the_draft() -> None:
    source = _ui_path().read_text(encoding="utf-8")
    window_source = _window_path().read_text(encoding="utf-8")
    apply_body = source.split("    def _apply_heatmap_settings", 1)[1].split(
        "    def _heatmap_settings_from_draft",
        1,
    )[0]
    heatmaps_section = window_source.split(
        '                    "Heatmaps",',
        1,
    )[
        1
    ].split("                self._build_config_section(", 1,)[0]

    assert "collapsed=True" in heatmaps_section
    assert 'with ui.CollapsableFrame("Isolation", collapsed=True, height=0)' in source
    assert (
        'with ui.CollapsableFrame("X-Ray Overlay", collapsed=True, height=0)' in source
    )
    assert 'with ui.CollapsableFrame("Calibration", collapsed=True, height=0)' in source
    assert 'with ui.CollapsableFrame("Color Scale", collapsed=True, height=0)' in source
    assert 'with ui.CollapsableFrame("Clamps", collapsed=True, height=0)' in source
    assert "with ui.VStack(spacing=4, height=0):" in source
    assert "height=0," in source
    assert "self._refresh_heatmap_settings_controls()" not in apply_body
    assert "_queue_heatmap_settings_refresh" not in source


def test_view_starts_with_visualization_as_its_only_expanded_section() -> None:
    source = _window_path().read_text(encoding="utf-8")
    view_tab = source.split("    def _build_view_tab", 1)[1].split(
        "    def _build_server_appearance_controls",
        1,
    )[0]

    assert view_tab.index('"Visualization"') < view_tab.index('"Server Appearance"')
    visualization = view_tab.split('"Visualization"', 1)[1].split(
        '"Server Appearance"',
        1,
    )[0]
    assert "collapsed=False" in visualization
    assert view_tab.count("collapsed=True") == 5


def test_heatmap_controls_follow_catalog_readiness_and_gpu_hierarchy() -> None:
    source = _ui_path().read_text(encoding="utf-8")

    assert "catalog is not None and catalog.ready" in source
    assert "self._heatmap_test_button.enabled = False" in source
    assert "button.enabled = ready" in source
    assert '"Heatmap Settings will load after the production stage is ready."' in source
    assert "selector.parent_label" in source
    assert "ui.Spacer(width=indent)" in source
    assert "heatmap_xray_overlay_groups_snapshot()" in source
    assert "xray_overlay_group_ids" in source


def test_color_scale_ui_uses_hex_draft_feedback_without_runtime_callbacks() -> None:
    source = _ui_path().read_text(encoding="utf-8")
    feedback_body = source.split(
        "    def _refresh_heatmap_color_scale_draft",
        1,
    )[
        1
    ].split("    def _heatmap_color_scale_draft_feedback", 1)[0]

    assert '"hex": ui.SimpleStringModel' in source
    assert 'ui.StringField(model=models["hex"]' in source
    assert "ui.Rectangle(" in source
    assert "with ui.HStack(height=20, spacing=8):" in source
    assert "color_scale_settings_from_draft" in source
    assert "RGB " not in source
    assert "_controller" not in feedback_body


def _ui_path() -> Path:
    return (
        Path(__file__).parents[2]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "msp"
        / "dtrs"
        / "ui"
        / "heatmaps.py"
    )


def _window_path() -> Path:
    return _ui_path().with_name("window.py")
