"""Focused shell coverage for draft-only Heatmap settings controls."""

from __future__ import annotations

from pathlib import Path


def test_heatmap_ui_has_one_test_action_and_draft_settings_apply_boundary() -> None:
    source = _ui_path().read_text(encoding="utf-8")

    assert '"Test Heatmaps"' in source
    assert '"Restore Heatmap Test"' in source
    assert '"Apply Heatmaps Settings"' in source
    assert '"Isolation"' in source
    assert '"Calibration"' in source
    assert '"Color Scale"' in source
    assert '"Confirm"' not in source
    assert '"Failure"' not in source
    assert "clicked_fn=self._apply_heatmap_settings" in source
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
    assert 'with ui.CollapsableFrame("Calibration", collapsed=True, height=0)' in source
    assert 'with ui.CollapsableFrame("Color Scale", collapsed=True, height=0)' in source
    assert "with ui.VStack(spacing=4, height=0):" in source
    assert "height=0," in source
    assert "self._refresh_heatmap_settings_controls()" not in apply_body
    assert "_queue_heatmap_settings_refresh" not in source


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
