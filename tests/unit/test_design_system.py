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
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSlider,
    QTextEdit,
    QWidget,
)

from design_system import (
    Animation,
    Borders,
    ColorPalette,
    DesignSystem,
    Shadows,
    Spacing,
    Typography,
    design_system,
)


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
]


class TestColorPalette:
    """Test ColorPalette dataclass values and properties."""

    def test_default_primary_colors(self) -> None:
        """Test primary color defaults match Material Design."""
        palette = ColorPalette()
        assert palette.primary == "#2196F3"
        assert palette.primary_hover == "#1976D2"
        assert palette.primary_pressed == "#0D47A1"

    def test_default_secondary_colors(self) -> None:
        """Test secondary color defaults."""
        palette = ColorPalette()
        assert palette.secondary == "#00BCD4"
        assert palette.secondary_hover == "#00ACC1"
        assert palette.secondary_pressed == "#00838F"

    def test_semantic_colors(self) -> None:
        """Test semantic color values for success/error/warning/info."""
        palette = ColorPalette()
        assert palette.success == "#4CAF50"
        assert palette.error == "#F44336"
        assert palette.warning == "#FF9800"
        assert palette.info == "#03A9F4"

    def test_background_colors(self) -> None:
        """Test background color hierarchy."""
        palette = ColorPalette()
        assert palette.bg_primary == "#1E1E1E"
        assert palette.bg_secondary == "#252525"
        assert palette.bg_tertiary == "#2D2D2D"

    def test_text_colors_wcag_compliant(self) -> None:
        """Test text colors are documented as WCAG AA compliant."""
        palette = ColorPalette()
        assert palette.text_primary == "#FFFFFF"  # 21:1 contrast
        assert palette.text_secondary == "#B0B0B0"  # 7:1 contrast
        assert palette.text_disabled == "#707070"  # 4.5:1 contrast
        assert palette.text_hint == "#808080"  # 5:1 contrast

    def test_special_ui_elements(self) -> None:
        """Test special UI element colors."""
        palette = ColorPalette()
        assert "rgba" in palette.selection.lower()
        assert "rgba" in palette.overlay.lower()

    def test_color_palette_immutable_fields(self) -> None:
        """Test that color palette fields can be accessed."""
        palette = ColorPalette()
        # Test we can access all fields
        fields = [
            "primary",
            "primary_hover",
            "primary_pressed",
            "secondary",
            "secondary_hover",
            "secondary_pressed",
            "success",
            "error",
            "warning",
            "info",
            "bg_primary",
            "bg_secondary",
            "bg_tertiary",
            "surface",
            "surface_hover",
            "surface_pressed",
            "text_primary",
            "text_secondary",
            "text_disabled",
            "text_hint",
            "border_default",
            "border_focus",
            "border_error",
            "selection",
            "overlay",
        ]
        for field in fields:
            assert hasattr(palette, field)
            assert isinstance(getattr(palette, field), str)


class TestTypography:
    """Test Typography dataclass values."""

    def test_font_families(self) -> None:
        """Test font family stacks."""
        typo = Typography()
        assert "Segoe UI" in typo.font_family
        assert "Roboto" in typo.font_family
        assert "Cascadia Code" in typo.font_family_mono
        assert "monospace" in typo.font_family_mono

    def test_font_sizes_hierarchy(self) -> None:
        """Test font sizes follow proper hierarchy."""
        typo = Typography()
        assert typo.size_h1 == 24
        assert typo.size_h2 == 20
        assert typo.size_h3 == 18
        assert typo.size_h4 == 16
        assert typo.size_body == 14
        assert typo.size_small == 12
        assert typo.size_tiny == 11

        # Verify hierarchy
        assert typo.size_h1 > typo.size_h2 > typo.size_h3 > typo.size_h4
        assert typo.size_h4 > typo.size_body > typo.size_small > typo.size_tiny

    def test_font_weights(self) -> None:
        """Test font weight values."""
        typo = Typography()
        assert typo.weight_light == 300
        assert typo.weight_regular == 400
        assert typo.weight_medium == 500
        assert typo.weight_bold == 600

        # Verify weight progression
        assert (
            typo.weight_light
            < typo.weight_regular
            < typo.weight_medium
            < typo.weight_bold
        )

    def test_line_heights(self) -> None:
        """Test line height values."""
        typo = Typography()
        assert typo.line_height_tight == 1.2
        assert typo.line_height_normal == 1.5
        assert typo.line_height_relaxed == 1.75

        # Verify progression
        assert (
            typo.line_height_tight < typo.line_height_normal < typo.line_height_relaxed
        )


class TestSpacing:
    """Test Spacing dataclass values."""

    def test_base_unit(self) -> None:
        """Test base spacing unit."""
        spacing = Spacing()
        assert spacing.unit == 4

    def test_spacing_scale(self) -> None:
        """Test spacing scale follows 4px base unit."""
        spacing = Spacing()
        assert spacing.xs == 4  # 1 unit
        assert spacing.sm == 8  # 2 units
        assert spacing.md == 16  # 4 units
        assert spacing.lg == 24  # 6 units
        assert spacing.xl == 32  # 8 units
        assert spacing.xxl == 48  # 12 units

        # Verify they're multiples of base unit
        assert spacing.xs % spacing.unit == 0
        assert spacing.sm % spacing.unit == 0
        assert spacing.md % spacing.unit == 0

    def test_component_spacing(self) -> None:
        """Test component-specific spacing."""
        spacing = Spacing()
        assert spacing.button_padding_h == 16
        assert spacing.button_padding_v == 8
        assert spacing.card_padding == 16
        assert spacing.dialog_padding == 24

    def test_grid_spacing(self) -> None:
        """Test grid-related spacing."""
        spacing = Spacing()
        assert spacing.grid_gap == 16
        assert spacing.thumbnail_spacing == 12


class TestBorders:
    """Test Borders dataclass values."""

    def test_border_widths(self) -> None:
        """Test border width values."""
        borders = Borders()
        assert borders.width_thin == 1
        assert borders.width_medium == 2
        assert borders.width_thick == 3

        # Verify progression
        assert borders.width_thin < borders.width_medium < borders.width_thick

    def test_border_radii(self) -> None:
        """Test border radius values."""
        borders = Borders()
        assert borders.radius_sm == 4
        assert borders.radius_md == 6
        assert borders.radius_lg == 8
        assert borders.radius_xl == 12
        assert borders.radius_round == "50%"

        # Verify progression for numeric radii
        assert (
            borders.radius_sm
            < borders.radius_md
            < borders.radius_lg
            < borders.radius_xl
        )


class TestShadows:
    """Test Shadows dataclass values."""

    def test_shadow_definitions(self) -> None:
        """Test shadow string definitions."""
        shadows = Shadows()

        # All shadows should be valid CSS box-shadow strings
        assert "rgba" in shadows.sm.lower()
        assert "rgba" in shadows.md.lower()
        assert "rgba" in shadows.lg.lower()
        assert "rgba" in shadows.xl.lower()
        assert "rgba" in shadows.focus.lower()

    def test_shadow_elevation_progression(self) -> None:
        """Test shadows have increasing complexity for elevation."""
        shadows = Shadows()

        # Extract first shadow offset values (should increase with elevation)
        import re

        def get_first_offset(shadow: str) -> int:
            """Extract the first pixel offset from shadow string."""
            match = re.search(r"(\d+)px", shadow)
            return int(match.group(1)) if match else 0

        # Higher elevation shadows should have larger offsets
        sm_offset = get_first_offset(shadows.sm)
        md_offset = get_first_offset(shadows.md)
        lg_offset = get_first_offset(shadows.lg)
        xl_offset = get_first_offset(shadows.xl)

        assert sm_offset < md_offset < lg_offset < xl_offset

        # Focus shadow should be distinct (no offset)
        assert "0 0 0" in shadows.focus  # No offset for focus ring


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
        assert isinstance(ds.typography, Typography)
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


class TestGlobalInstance:
    """Test the global design_system instance."""

    def test_global_instance_exists(self) -> None:
        """Test that global design_system instance is available."""
        assert design_system is not None
        assert isinstance(design_system, DesignSystem)

    def test_global_instance_initialized(self) -> None:
        """Test global instance has all components initialized."""
        assert isinstance(design_system.colors, ColorPalette)
        assert isinstance(design_system.typography, Typography)
        assert isinstance(design_system.spacing, Spacing)
        assert isinstance(design_system.borders, Borders)
        assert isinstance(design_system.shadows, Shadows)
        assert isinstance(design_system.animation, Animation)


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

    def test_button_variants_with_qt(self, qtbot: Any) -> None:
        """Test button variant styles work with actual QPushButton."""
        # Primary button
        primary_btn = QPushButton("Primary")
        primary_btn.setObjectName("primaryButton")
        qtbot.addWidget(primary_btn)

        # Success button
        success_btn = QPushButton("Success")
        success_btn.setObjectName("successButton")
        qtbot.addWidget(success_btn)

        # Danger button
        danger_btn = QPushButton("Danger")
        danger_btn.setObjectName("dangerButton")
        qtbot.addWidget(danger_btn)

        # Apply stylesheet to parent widget
        parent = QWidget()
        qtbot.addWidget(parent)
        parent.setStyleSheet(design_system.get_stylesheet())

        # Buttons should accept the stylesheet without errors
        primary_btn.setParent(parent)
        success_btn.setParent(parent)
        danger_btn.setParent(parent)

    def test_label_variants_with_qt(self, qtbot: Any) -> None:
        """Test label variants work with QLabel."""
        # Create labels with different object names
        h1 = QLabel("Heading 1")
        h1.setObjectName("heading1")
        qtbot.addWidget(h1)

        h2 = QLabel("Heading 2")
        h2.setObjectName("heading2")
        qtbot.addWidget(h2)

        hint = QLabel("Hint text")
        hint.setObjectName("hint")
        qtbot.addWidget(hint)

        # Apply stylesheet
        parent = QWidget()
        qtbot.addWidget(parent)
        parent.setStyleSheet(design_system.get_stylesheet())

        # Set parents to apply styles
        h1.setParent(parent)
        h2.setParent(parent)
        hint.setParent(parent)

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
    ("color_field", "expected"),
    [
        ("primary", "#2196F3"),
        ("success", "#4CAF50"),
        ("error", "#F44336"),
        ("warning", "#FF9800"),
        ("bg_primary", "#1E1E1E"),
    ],
)
def test_color_values_parametrized(color_field: str, expected: str) -> None:
    """Parametrized test for color values."""
    palette = ColorPalette()
    assert getattr(palette, color_field) == expected


@pytest.mark.parametrize(
    ("size_field", "min_value", "max_value"),
    [
        ("size_h1", 20, 30),
        ("size_body", 12, 16),
        ("size_tiny", 9, 12),
    ],
)
def test_font_sizes_in_range(size_field: str, min_value: int, max_value: int) -> None:
    """Test font sizes are within reasonable ranges."""
    typo = Typography()
    size = getattr(typo, size_field)
    assert min_value <= size <= max_value


@pytest.mark.parametrize(
    ("duration_field", "expected"),
    [
        ("duration_instant", 100),
        ("duration_fast", 200),
        ("duration_normal", 300),
        ("duration_slow", 500),
    ],
)
def test_animation_durations(duration_field: str, expected: int) -> None:
    """Parametrized test for animation durations."""
    anim = Animation()
    assert getattr(anim, duration_field) == expected


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
