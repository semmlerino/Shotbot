"""Comprehensive tests for the design system module.

Tests cover all dataclasses, stylesheet generation, component styles,
and integration with Qt widgets following UNIFIED_TESTING_GUIDE patterns.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLineEdit,
    QListWidget,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSlider,
    QTextEdit,
    QWidget,
)

from ui.design_system import (
    Animation,
    Borders,
    ColorPalette,
    DesignSystem,
    ScaledTypography,
    Shadows,
    Spacing,
    Typography,
    darken_color,
    design_system,
    get_tinted_background,
    lighten_color,
)


# ==============================================================================
# Parameterized constant snapshot test (replaces 5 separate dataclass test classes)
# ==============================================================================


@pytest.mark.parametrize(
    ("component", "attr", "expected"),
    [
        # ColorPalette
        ("colors", "primary", "#2196F3"),
        ("colors", "primary_hover", "#1976D2"),
        ("colors", "primary_pressed", "#0D47A1"),
        ("colors", "secondary", "#00BCD4"),
        ("colors", "success", "#4CAF50"),
        ("colors", "error", "#F44336"),
        ("colors", "warning", "#FF9800"),
        ("colors", "info", "#03A9F4"),
        ("colors", "bg_primary", "#1E1E1E"),
        ("colors", "bg_secondary", "#252525"),
        ("colors", "bg_tertiary", "#2D2D2D"),
        ("colors", "text_primary", "#FFFFFF"),
        ("colors", "text_secondary", "#B0B0B0"),
        ("colors", "text_disabled", "#707070"),
        ("colors", "text_hint", "#808080"),
        # Spacing
        ("spacing", "unit", 4),
        ("spacing", "xs", 4),
        ("spacing", "sm", 8),
        ("spacing", "md", 16),
        ("spacing", "lg", 24),
        ("spacing", "xl", 32),
        ("spacing", "xxl", 48),
        ("spacing", "button_padding_h", 16),
        ("spacing", "button_padding_v", 8),
        ("spacing", "card_padding", 16),
        ("spacing", "dialog_padding", 24),
        ("spacing", "grid_gap", 16),
        ("spacing", "thumbnail_spacing", 12),
        # Borders
        ("borders", "width_thin", 1),
        ("borders", "width_medium", 2),
        ("borders", "width_thick", 3),
        ("borders", "radius_sm", 4),
        ("borders", "radius_md", 6),
        ("borders", "radius_lg", 8),
        ("borders", "radius_xl", 12),
        ("borders", "radius_round", "50%"),
        # Animation
        ("animation", "duration_instant", 100),
        ("animation", "duration_fast", 200),
        ("animation", "duration_normal", 300),
        ("animation", "duration_slow", 500),
    ],
)
def test_design_system_constant_values(component: str, attr: str, expected: object) -> None:
    """Snapshot test: all design system constant values match expected."""
    ds = DesignSystem()
    obj = getattr(ds, component)
    assert getattr(obj, attr) == expected


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
]


class TestAnimation:
    """Test Animation dataclass values."""

    def test_duration_values(self) -> None:
        """Test animation duration values."""
        anim = Animation()
        assert anim.duration_instant == 100
        assert anim.duration_fast == 200
        assert anim.duration_normal == 300
        assert anim.duration_slow == 500

        # Verify progression
        assert (
            anim.duration_instant
            < anim.duration_fast
            < anim.duration_normal
            < anim.duration_slow
        )

    def test_easing_functions(self) -> None:
        """Test easing function strings."""
        anim = Animation()

        # All should be cubic-bezier functions
        assert "cubic-bezier" in anim.ease_in_out
        assert "cubic-bezier" in anim.ease_out
        assert "cubic-bezier" in anim.ease_in
        assert "cubic-bezier" in anim.spring

        # Verify they have 4 numeric parameters
        for easing in [anim.ease_in_out, anim.ease_out, anim.ease_in, anim.spring]:
            match = re.search(r"cubic-bezier\(([\d\.\-\s,]+)\)", easing)
            assert match is not None
            params = match.group(1).split(",")
            assert len(params) == 4


class TestDesignSystem:
    """Test the main DesignSystem class."""

    def test_initialization(self) -> None:
        """Test DesignSystem initializes all sub-components."""
        ds = DesignSystem()

        assert isinstance(ds.colors, ColorPalette)
        assert isinstance(ds.typography, ScaledTypography)
        assert isinstance(ds.spacing, Spacing)
        assert isinstance(ds.borders, Borders)
        assert isinstance(ds.shadows, Shadows)
        assert isinstance(ds.animation, Animation)

    def test_get_stylesheet_structure(self) -> None:
        """Test stylesheet generation produces valid CSS-like structure."""
        ds = DesignSystem()
        stylesheet = ds.get_stylesheet()

        # Should contain key widget selectors
        assert "QWidget {" in stylesheet
        assert "QMainWindow {" in stylesheet
        assert "QPushButton {" in stylesheet
        assert "QLineEdit" in stylesheet
        assert "QLabel {" in stylesheet

        # Should contain color values from palette
        assert ds.colors.bg_primary in stylesheet
        assert ds.colors.text_primary in stylesheet
        assert ds.colors.primary in stylesheet

    def test_get_stylesheet_button_states(self) -> None:
        """Test stylesheet includes all button states."""
        ds = DesignSystem()
        stylesheet = ds.get_stylesheet()

        # Button states
        assert "QPushButton {" in stylesheet
        assert "QPushButton:hover {" in stylesheet
        assert "QPushButton:pressed {" in stylesheet
        assert "QPushButton:disabled {" in stylesheet

        # Special button variants
        assert "QPushButton#primaryButton {" in stylesheet
        assert "QPushButton#successButton {" in stylesheet
        assert "QPushButton#dangerButton {" in stylesheet

    def test_get_stylesheet_uses_design_tokens(self) -> None:
        """Test stylesheet uses values from design tokens."""
        ds = DesignSystem()
        stylesheet = ds.get_stylesheet()

        # Typography values
        assert f"{ds.typography.size_body}px" in stylesheet
        assert f"{ds.typography.weight_medium}" in stylesheet

        # Spacing values
        assert f"{ds.spacing.button_padding_v}px" in stylesheet
        assert f"{ds.spacing.button_padding_h}px" in stylesheet

        # Border values
        assert f"{ds.borders.radius_md}px" in stylesheet
        assert f"{ds.borders.width_thin}px" in stylesheet

    def test_get_component_style_card_variants(self) -> None:
        """Test get_component_style returns correct card styles."""
        ds = DesignSystem()

        # Default card
        default_card = ds.get_component_style("card", "default")
        assert default_card["background-color"] == ds.colors.bg_secondary
        assert ds.colors.border_default in default_card["border"]
        assert f"{ds.borders.radius_lg}px" in default_card["border-radius"]

        # Elevated card
        elevated_card = ds.get_component_style("card", "elevated")
        assert elevated_card["background-color"] == ds.colors.bg_tertiary
        assert elevated_card["box-shadow"] == ds.shadows.md
        assert elevated_card["border"] == "none"

    def test_get_component_style_button_variants(self) -> None:
        """Test get_component_style returns correct button styles."""
        ds = DesignSystem()

        # Primary button
        primary = ds.get_component_style("button", "primary")
        assert primary["background-color"] == ds.colors.primary
        assert primary["color"] == "white"
        assert primary["border"] == "none"

        # Secondary button
        secondary = ds.get_component_style("button", "secondary")
        assert secondary["background-color"] == "transparent"
        assert secondary["color"] == ds.colors.primary
        assert ds.colors.primary in secondary["border"]

        # Success button
        success = ds.get_component_style("button", "success")
        assert success["background-color"] == ds.colors.success

        # Danger button
        danger = ds.get_component_style("button", "danger")
        assert danger["background-color"] == ds.colors.error

    def test_get_component_style_invalid_component(self) -> None:
        """Test get_component_style handles invalid components gracefully."""
        ds = DesignSystem()

        # Invalid component should return empty dict
        result = ds.get_component_style("invalid_component", "default")
        assert result == {}

        # Valid component with invalid variant should return empty dict
        result = ds.get_component_style("card", "invalid_variant")
        assert result == {}

    def test_stylesheet_contains_all_widget_types(self) -> None:
        """Test stylesheet covers all major Qt widget types."""
        ds = DesignSystem()
        stylesheet = ds.get_stylesheet()

        widget_types = [
            "QWidget",
            "QMainWindow",
            "QPushButton",
            "QLineEdit",
            "QTextEdit",
            "QLabel",
            "QGroupBox",
            "QTabWidget",
            "QTabBar",
            "QListWidget",
            "QScrollBar",
            "QStatusBar",
            "QMenuBar",
            "QMenu",
            "QProgressBar",
            "QToolTip",
            "QSlider",
        ]

        for widget in widget_types:
            assert widget in stylesheet, f"Missing styles for {widget}"


class TestQtIntegration:
    """Test design system integration with actual Qt widgets."""

    def test_apply_stylesheet_to_widget(self, qtbot: Any) -> None:
        """Test that stylesheet can be applied to Qt widgets without errors."""
        widget = QWidget()
        qtbot.addWidget(widget)

        stylesheet = design_system.get_stylesheet()
        widget.setStyleSheet(stylesheet)

        # Should not raise any exceptions
        assert widget.styleSheet() == stylesheet

    def test_apply_stylesheet_to_main_window(self, qtbot: Any) -> None:
        """Test stylesheet application to QMainWindow."""
        window = QMainWindow()
        qtbot.addWidget(window)

        stylesheet = design_system.get_stylesheet()
        window.setStyleSheet(stylesheet)

        # Verify it was applied
        assert window.styleSheet() == stylesheet

    def test_complex_widget_hierarchy(self, qtbot: Any) -> None:
        """Test stylesheet with complex widget hierarchy."""
        main_window = QMainWindow()
        qtbot.addWidget(main_window)

        # Create central widget with various child widgets
        central = QWidget()
        main_window.setCentralWidget(central)

        # Add different widget types
        button = QPushButton("Test Button")
        line_edit = QLineEdit("Test Input")
        text_edit = QTextEdit("Test Text")
        list_widget = QListWidget()
        progress_bar = QProgressBar()
        slider = QSlider(Qt.Orientation.Horizontal)

        # Add to parent
        for widget in [button, line_edit, text_edit, list_widget, progress_bar, slider]:
            widget.setParent(central)

        # Apply stylesheet to main window
        main_window.setStyleSheet(design_system.get_stylesheet())

        # All widgets should have the stylesheet applied through inheritance
        assert main_window.styleSheet() != ""


@pytest.mark.parametrize(
    ("size_field", "min_value", "max_value"),
    [
        ("size_h1", 22, 32),
        ("size_body", 14, 20),
        ("size_tiny", 11, 16),
    ],
)
def test_font_sizes_in_range(size_field: str, min_value: int, max_value: int) -> None:
    """Test font sizes are within reasonable ranges."""
    typo = Typography()
    size = getattr(typo, size_field)
    assert min_value <= size <= max_value


def test_stylesheet_is_not_empty() -> None:
    """Test that generated stylesheet has substantial content."""
    ds = DesignSystem()
    stylesheet = ds.get_stylesheet()

    # Should be a substantial stylesheet
    assert len(stylesheet) > 1000

    # Count number of style rules (rough approximation)
    rule_count = stylesheet.count("{")
    assert rule_count > 20  # Should have many rules


def test_stylesheet_valid_css_syntax() -> None:
    """Test stylesheet has valid CSS-like syntax."""
    ds = DesignSystem()
    stylesheet = ds.get_stylesheet()

    # Basic syntax checks
    assert stylesheet.count("{") == stylesheet.count("}")
    assert stylesheet.count("/*") == stylesheet.count("*/")

    # Should not have any template variables left
    assert "self." not in stylesheet
    assert "None" not in stylesheet


def test_all_colors_are_valid_hex_or_rgba() -> None:
    """Test all color values are valid hex or rgba format."""
    palette = ColorPalette()

    hex_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
    rgba_pattern = re.compile(r"^rgba\(\d+,\s*\d+,\s*\d+,\s*[\d.]+\)$")

    for field in dir(palette):
        if not field.startswith("_"):
            value = getattr(palette, field)
            if isinstance(value, str) and (
                field.startswith(("text_", "bg_", "border_"))
                or field
                in [
                    "primary",
                    "secondary",
                    "success",
                    "error",
                    "warning",
                    "info",
                    "surface",
                    "selection",
                    "overlay",
                ]
            ):
                # Should be either hex or rgba
                is_hex = hex_pattern.match(value) is not None
                is_rgba = rgba_pattern.match(value.replace(" ", "")) is not None
                assert is_hex or is_rgba, f"{field}={value} is not valid hex or rgba"


class TestColorUtilities:
    def test_lighten_increases_rgb(self) -> None:
        result = lighten_color("#404040")
        assert int(result[1:3], 16) > 0x40

    def test_lighten_clamps_at_255(self) -> None:
        assert lighten_color("#ffffff") == "#ffffff"

    def test_lighten_passthrough_non_hex(self) -> None:
        assert lighten_color("red") == "red"

    def test_darken_reduces_rgb(self) -> None:
        result = darken_color("#ffffff")
        assert int(result[1:3], 16) < 255

    def test_darken_passthrough_non_hex(self) -> None:
        assert darken_color("red") == "red"

    def test_tint_zero_blend_returns_base(self) -> None:
        assert get_tinted_background("#ff0000", base="#252525", blend=0.0) == "#252525"

    def test_tint_full_blend_returns_accent(self) -> None:
        assert get_tinted_background("#ff0000", base="#000000", blend=1.0) == "#ff0000"

    def test_tint_invalid_accent_returns_base(self) -> None:
        assert get_tinted_background("red", base="#252525") == "#252525"
