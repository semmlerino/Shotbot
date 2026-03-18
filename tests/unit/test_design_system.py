"""Comprehensive tests for the design system module.

Tests cover color palette, typography, spacing, and utility functions.
"""

from __future__ import annotations

import re

import pytest

from ui.design_system import (
    ColorPalette,
    DesignSystem,
    ScaledTypography,
    Spacing,
    Typography,
    darken_color,
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


class TestDesignSystem:
    """Test the main DesignSystem class."""

    def test_initialization(self) -> None:
        """Test DesignSystem initializes all sub-components."""
        ds = DesignSystem()

        assert isinstance(ds.colors, ColorPalette)
        assert isinstance(ds.typography, ScaledTypography)
        assert isinstance(ds.spacing, Spacing)


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
