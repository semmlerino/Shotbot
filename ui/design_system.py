"""Centralized design system for ShotBot UI consistency.

This module provides a unified design system with consistent colors, typography,
spacing, and component styles following modern UI/UX best practices.
"""

from __future__ import annotations

from collections.abc import Callable

# Standard library imports
from dataclasses import dataclass
from typing import ClassVar, final

from PySide6.QtCore import QObject, Signal


@final
@dataclass
class ColorPalette:
    """Application color palette with semantic naming."""

    # Primary colors
    primary: str = "#2196F3"  # Material Blue - main actions
    primary_hover: str = "#1976D2"
    primary_pressed: str = "#0D47A1"

    # Secondary colors
    secondary: str = "#00BCD4"  # Cyan - highlights
    secondary_hover: str = "#00ACC1"
    secondary_pressed: str = "#00838F"

    # Success/Error/Warning
    success: str = "#4CAF50"
    error: str = "#F44336"
    warning: str = "#FF9800"
    info: str = "#03A9F4"

    # Background colors
    bg_primary: str = "#1E1E1E"  # Main background
    bg_secondary: str = "#252525"  # Card/panel background
    bg_tertiary: str = "#2D2D2D"  # Elevated surfaces

    # Surface colors
    surface: str = "#333333"
    surface_hover: str = "#3D3D3D"
    surface_pressed: str = "#2A2A2A"

    # Text colors (WCAG AA compliant on dark backgrounds)
    text_primary: str = "#FFFFFF"  # 21:1 contrast
    text_secondary: str = "#B0B0B0"  # 7:1 contrast
    text_disabled: str = "#707070"  # 4.5:1 contrast
    text_hint: str = "#808080"  # 5:1 contrast

    # Border colors
    border_default: str = "#404040"
    border_focus: str = "#2196F3"
    border_error: str = "#F44336"

    # Special UI elements
    selection: str = "rgba(33, 150, 243, 0.3)"  # Semi-transparent primary
    overlay: str = "rgba(0, 0, 0, 0.5)"


@final
@dataclass
class Typography:
    """Typography system with consistent sizing and weights."""

    # Font families
    font_family: str = '"Segoe UI", "Roboto", "Helvetica Neue", Arial, sans-serif'
    font_family_mono: str = '"Cascadia Code", "Fira Code", "Consolas", monospace'

    # Font sizes (pixel scale) - base values before UI scale
    size_h1: int = 26
    size_h2: int = 22
    size_h3: int = 20
    size_h4: int = 18
    size_body: int = 16
    size_small: int = 14
    size_tiny: int = 13
    size_extra_tiny: int = 12  # File info, secondary metadata
    size_extra_small: int = 11  # Compact labels, spacers
    size_micro: int = 10  # Monospace paths, logs, technical text

    # Font weights
    weight_light: int = 300
    weight_regular: int = 400
    weight_medium: int = 500
    weight_bold: int = 600

    # Line heights
    line_height_tight: float = 1.2
    line_height_normal: float = 1.5
    line_height_relaxed: float = 1.75


@final
class ScaledTypography:
    """Typography wrapper that applies UI scale to font sizes.

    This class wraps a Typography instance and returns scaled font sizes
    while preserving non-size attributes unchanged. The scale is retrieved
    dynamically from the design system to support runtime changes.
    """

    _base: Typography
    _get_scale: Callable[[], float]

    def __init__(self, base: Typography, get_scale: Callable[[], float]) -> None:
        """Initialize scaled typography.

        Args:
            base: Base Typography instance with unscaled values
            get_scale: Callable that returns current UI scale factor

        """
        self._base = base
        self._get_scale = get_scale

    def _scaled(self, value: int) -> int:
        """Apply scale to a size value."""
        return round(value * self._get_scale())

    # Scaled size properties - return int for type safety
    @property
    def size_h1(self) -> int:
        return self._scaled(self._base.size_h1)

    @property
    def size_h2(self) -> int:
        return self._scaled(self._base.size_h2)

    @property
    def size_h3(self) -> int:
        return self._scaled(self._base.size_h3)

    @property
    def size_h4(self) -> int:
        return self._scaled(self._base.size_h4)

    @property
    def size_body(self) -> int:
        return self._scaled(self._base.size_body)

    @property
    def size_small(self) -> int:
        return self._scaled(self._base.size_small)

    @property
    def size_tiny(self) -> int:
        return self._scaled(self._base.size_tiny)

    @property
    def size_extra_tiny(self) -> int:
        return self._scaled(self._base.size_extra_tiny)

    @property
    def size_extra_small(self) -> int:
        return self._scaled(self._base.size_extra_small)

    @property
    def size_micro(self) -> int:
        return self._scaled(self._base.size_micro)

    # Pass-through properties for non-scaled values
    @property
    def font_family(self) -> str:
        return self._base.font_family

    @property
    def weight_light(self) -> int:
        return self._base.weight_light

    @property
    def weight_regular(self) -> int:
        return self._base.weight_regular

    @property
    def weight_medium(self) -> int:
        return self._base.weight_medium

    @property
    def weight_bold(self) -> int:
        return self._base.weight_bold

    @property
    def line_height_tight(self) -> float:
        return self._base.line_height_tight

    @property
    def line_height_normal(self) -> float:
        return self._base.line_height_normal

    @property
    def line_height_relaxed(self) -> float:
        return self._base.line_height_relaxed


@final
@dataclass
class Spacing:
    """Spacing system using 4px base unit."""

    # Base unit
    unit: int = 4

    # Spacing scale (multiples of base unit)
    xs: int = 4  # 1 unit
    sm: int = 8  # 2 units
    md: int = 16  # 4 units
    lg: int = 24  # 6 units
    xl: int = 32  # 8 units
    xxl: int = 48  # 12 units

    # Component spacing
    button_padding_h: int = 16
    button_padding_v: int = 8
    card_padding: int = 16
    dialog_padding: int = 24

    # Grid spacing
    grid_gap: int = 16
    thumbnail_spacing: int = 12


@final
class DesignSystem(QObject):
    """Central design system with all design tokens."""

    _cleanup_order: ClassVar[int] = 40
    _singleton_description: ClassVar[str] = (
        "Design system with colors, typography, spacing, borders, shadows, and animation"
    )

    # Emitted when UI scale changes, for live preview updates
    scale_changed = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self._ui_scale: float = 1.0  # Default 100% scale
        self._base_typography = Typography()
        self.colors = ColorPalette()
        self.typography = ScaledTypography(
            self._base_typography, lambda: self._ui_scale
        )
        self.spacing = Spacing()

    def set_ui_scale(self, scale: float) -> None:
        """Set UI scale factor for typography.

        Args:
            scale: Scale factor (0.8 to 1.5). Values outside range are clamped.

        """
        new_scale = max(0.8, min(scale, 1.5))
        if new_scale != self._ui_scale:
            self._ui_scale = new_scale
            self.scale_changed.emit(new_scale)

    def get_ui_scale(self) -> float:
        """Get current UI scale factor.

        Returns:
            Current scale factor (0.8 to 1.5)

        """
        return self._ui_scale


def lighten_color(color: str, percent: int = 20) -> str:
    """Lighten a hex color by interpolating toward white.

    Args:
        color: Hex color like '#c0392b'
        percent: Percentage to lighten (0-100), defaults to 20 (for hover states)

    Returns:
        Lightened hex color
    """
    if not color.startswith("#"):
        return color

    hex_color = color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    # Lighten by interpolating toward white (255)
    r = min(255, r + int((255 - r) * percent / 100))
    g = min(255, g + int((255 - g) * percent / 100))
    b = min(255, b + int((255 - b) * percent / 100))

    return f"#{r:02x}{g:02x}{b:02x}"


def darken_color(color: str) -> str:
    """Darken a hex color by 20% (for pressed states)."""
    if color.startswith("#"):
        r = int(int(color[1:3], 16) * 0.8)
        g = int(int(color[3:5], 16) * 0.8)
        b = int(int(color[5:7], 16) * 0.8)
        return f"#{r:02x}{g:02x}{b:02x}"
    return color


def get_tinted_background(
    accent: str, base: str = "#252525", blend: float = 0.12
) -> str:
    """Blend an accent color into a dark base for a subtle tint."""
    if not accent.startswith("#") or not base.startswith("#"):
        return base
    br, bg, bb = int(base[1:3], 16), int(base[3:5], 16), int(base[5:7], 16)
    cr, cg, cb = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
    r = int(br * (1 - blend) + cr * blend)
    g = int(bg * (1 - blend) + cg * blend)
    b = int(bb * (1 - blend) + cb * blend)
    return f"#{r:02x}{g:02x}{b:02x}"


TAB_BAR_STYLESHEET = """
    /* Tab bar - disable focus indicators */
    QTabBar {
        qproperty-drawBase: 0;
    }

    /* Base tab styling - professional proportions */
    QTabBar::tab {
        min-width: 120px;
        font-size: 16px;
        font-weight: 400;
        border: none;
        outline: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
        border-bottom-left-radius: 0px;
        border-bottom-right-radius: 0px;
    }

    /* Disable focus indicators */
    QTabBar::tab:focus {
        outline: none;
        border: none;
    }

    /* Inactive tabs - subtle and recessed */
    QTabBar::tab:!selected {
        background: rgba(50, 50, 50, 1.0);
        color: rgba(180, 180, 180, 1.0);
        padding: 10px 28px 12px 28px;
        margin-top: 4px;
        margin-bottom: 0px;
        margin-left: 0px;
        margin-right: 1px;
        border-top: 2px solid rgba(80, 80, 80, 1.0);
    }

    /* Tab 0 (My Shots) - Blue accent when inactive */
    QTabBar::tab:!selected:first {
        border-top: 2px solid rgba(100, 150, 200, 0.3);
    }

    /* Tab 1 (Other 3DE) - Cyan accent when inactive */
    QTabBar::tab:!selected:middle {
        border-top: 2px solid rgba(80, 180, 190, 0.3);
    }

    /* Tab 2 (Previous Shots) - Purple accent when inactive */
    QTabBar::tab:!selected:last {
        border-top: 2px solid rgba(150, 100, 180, 0.3);
        margin-right: 0px;
    }

    /* Selected tab - elevated, no border, no outline */
    QTabBar::tab:selected {
        background: rgba(65, 65, 65, 1.0);
        color: rgba(240, 240, 240, 1.0);
        padding: 12px 28px 14px 28px;
        margin-top: 0px;
        margin-bottom: -2px;
        margin-left: 0px;
        margin-right: 1px;
        border: 0px solid transparent;
        border-top: 0px solid transparent;
        border-bottom: 0px solid transparent;
        border-left: 0px solid transparent;
        border-right: 0px solid transparent;
        outline: 0px solid transparent;
    }

    /* Override any inherited borders for selected tabs */
    QTabBar::tab:selected:first {
        border: 0px solid transparent;
        outline: 0px solid transparent;
    }

    QTabBar::tab:selected:middle {
        border: 0px solid transparent;
        outline: 0px solid transparent;
    }

    QTabBar::tab:selected:last {
        border: 0px solid transparent;
        outline: 0px solid transparent;
    }

    /* Remove focus indicators from selected tabs */
    QTabBar::tab:selected:focus {
        outline: none;
        border: none;
    }

    QTabBar::tab:selected:first:focus {
        outline: none;
        border: none;
    }

    QTabBar::tab:selected:middle:focus {
        outline: none;
        border: none;
    }

    QTabBar::tab:selected:last:focus {
        outline: none;
        border: none;
    }
"""

# Global instance
design_system = DesignSystem()


def _reset_design_system() -> None:
    """Reset the global design system instance to defaults. Used in tests."""
    import sys

    module = sys.modules[__name__]
    module.design_system = DesignSystem()  # type: ignore[attr-defined]


DesignSystem.reset = classmethod(  # type: ignore[attr-defined]
    lambda cls: _reset_design_system()  # noqa: ARG005
)
