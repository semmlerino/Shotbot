"""Centralized design system for ShotBot UI consistency.

This module provides a unified design system with consistent colors, typography,
spacing, and component styles following modern UI/UX best practices.
"""

from __future__ import annotations

from collections.abc import Callable

# Standard library imports
from dataclasses import dataclass
from typing import final

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
@dataclass
class Borders:
    """Border styles and radii."""

    # Border widths
    width_thin: int = 1
    width_medium: int = 2
    width_thick: int = 3

    # Border radii
    radius_sm: int = 4
    radius_md: int = 6
    radius_lg: int = 8
    radius_xl: int = 12
    radius_round: str = "50%"


@final
@dataclass
class Shadows:
    """Box shadow definitions for elevation."""

    # Elevation levels
    sm: str = "0 1px 3px rgba(0, 0, 0, 0.12), 0 1px 2px rgba(0, 0, 0, 0.24)"
    md: str = "0 3px 6px rgba(0, 0, 0, 0.15), 0 2px 4px rgba(0, 0, 0, 0.12)"
    lg: str = "0 10px 20px rgba(0, 0, 0, 0.15), 0 3px 6px rgba(0, 0, 0, 0.10)"
    xl: str = "0 15px 25px rgba(0, 0, 0, 0.15), 0 5px 10px rgba(0, 0, 0, 0.05)"

    # Focus shadow
    focus: str = "0 0 0 3px rgba(33, 150, 243, 0.4)"


@final
@dataclass
class Animation:
    """Animation timing and easing functions."""

    # Durations (ms)
    duration_instant: int = 100
    duration_fast: int = 200
    duration_normal: int = 300
    duration_slow: int = 500

    # Easing functions
    ease_in_out: str = "cubic-bezier(0.4, 0, 0.2, 1)"
    ease_out: str = "cubic-bezier(0.0, 0, 0.2, 1)"
    ease_in: str = "cubic-bezier(0.4, 0, 1, 1)"

    # Spring animation for bounce effect
    spring: str = "cubic-bezier(0.68, -0.55, 0.265, 1.55)"


@final
class DesignSystem(QObject):
    """Central design system with all design tokens."""

    # Emitted when UI scale changes, for live preview updates
    scale_changed = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self._ui_scale: float = 1.0  # Default 100% scale
        self._base_typography = Typography()
        self.colors = ColorPalette()
        self.typography = ScaledTypography(self._base_typography, lambda: self._ui_scale)
        self.spacing = Spacing()
        self.borders = Borders()
        self.shadows = Shadows()
        self.animation = Animation()

    def get_stylesheet(self) -> str:
        """Generate the main application stylesheet."""
        return f"""
        /* ===== Global Styles ===== */
        QWidget {{
            background-color: {self.colors.bg_primary};
            color: {self.colors.text_primary};
            font-family: {self.typography.font_family};
            font-size: {self.typography.size_body}px;
        }}

        /* ===== Main Window ===== */
        QMainWindow {{
            background-color: {self.colors.bg_primary};
        }}

        /* ===== Buttons ===== */
        QPushButton {{
            background-color: {self.colors.surface};
            color: {self.colors.text_primary};
            border: {self.borders.width_thin}px solid {self.colors.border_default};
            border-radius: {self.borders.radius_md}px;
            padding: {self.spacing.button_padding_v}px {self.spacing.button_padding_h}px;
            font-weight: {self.typography.weight_medium};
            min-height: 32px;
        }}

        QPushButton:hover {{
            background-color: {self.colors.surface_hover};
            border-color: {self.colors.primary};
        }}

        QPushButton:pressed {{
            background-color: {self.colors.surface_pressed};
        }}

        QPushButton:disabled {{
            background-color: {self.colors.bg_secondary};
            color: {self.colors.text_disabled};
            border-color: {self.colors.border_default};
        }}

        /* Primary button style */
        QPushButton#primaryButton {{
            background-color: {self.colors.primary};
            color: white;
            border: none;
        }}

        QPushButton#primaryButton:hover {{
            background-color: {self.colors.primary_hover};
        }}

        QPushButton#primaryButton:pressed {{
            background-color: {self.colors.primary_pressed};
        }}

        /* Success button style */
        QPushButton#successButton {{
            background-color: {self.colors.success};
            color: white;
            border: none;
        }}

        /* Danger button style */
        QPushButton#dangerButton {{
            background-color: {self.colors.error};
            color: white;
            border: none;
        }}

        /* ===== Input Fields ===== */
        QLineEdit, QTextEdit {{
            background-color: {self.colors.bg_secondary};
            color: {self.colors.text_primary};
            border: {self.borders.width_thin}px solid {self.colors.border_default};
            border-radius: {self.borders.radius_sm}px;
            padding: {self.spacing.sm}px;
            selection-background-color: {self.colors.primary};
        }}

        QLineEdit:focus, QTextEdit:focus {{
            border-color: {self.colors.border_focus};
            outline: none;
        }}

        QLineEdit:disabled, QTextEdit:disabled {{
            background-color: {self.colors.bg_tertiary};
            color: {self.colors.text_disabled};
        }}

        /* ===== Labels ===== */
        QLabel {{
            color: {self.colors.text_primary};
            background-color: transparent;
        }}

        QLabel#heading1 {{
            font-size: {self.typography.size_h1}px;
            font-weight: {self.typography.weight_bold};
            color: {self.colors.text_primary};
        }}

        QLabel#heading2 {{
            font-size: {self.typography.size_h2}px;
            font-weight: {self.typography.weight_medium};
            color: {self.colors.text_primary};
        }}

        QLabel#heading3 {{
            font-size: {self.typography.size_h3}px;
            font-weight: {self.typography.weight_medium};
            color: {self.colors.text_secondary};
        }}

        QLabel#hint {{
            font-size: {self.typography.size_small}px;
            color: {self.colors.text_hint};
            font-style: italic;
        }}

        /* ===== Group Boxes ===== */
        QGroupBox {{
            background-color: {self.colors.bg_secondary};
            border: {self.borders.width_thin}px solid {self.colors.border_default};
            border-radius: {self.borders.radius_md}px;
            margin-top: {self.spacing.md}px;
            padding-top: {self.spacing.md}px;
            font-weight: {self.typography.weight_medium};
        }}

        QGroupBox::title {{
            subcontrol-origin: margin;
            left: {self.spacing.md}px;
            padding: 0 {self.spacing.sm}px;
            color: {self.colors.text_primary};
            background-color: {self.colors.bg_secondary};
        }}

        /* ===== Tab Widget ===== */
        QTabWidget::pane {{
            background-color: {self.colors.bg_secondary};
            border: {self.borders.width_thin}px solid {self.colors.border_default};
            border-radius: {self.borders.radius_md}px;
        }}

        QTabBar::tab {{
            background-color: {self.colors.surface};
            color: {self.colors.text_secondary};
            padding: {self.spacing.lg}px {self.spacing.xxl}px;
            margin-right: {self.spacing.xs}px;
            border-top-left-radius: {self.borders.radius_md}px;
            border-top-right-radius: {self.borders.radius_md}px;
            font-size: {self.typography.size_h3}px;
            font-weight: {self.typography.weight_medium};
        }}

        QTabBar::tab:selected {{
            background-color: {self.colors.bg_secondary};
            color: {self.colors.text_primary};
            border-bottom: {self.borders.width_medium}px solid {self.colors.primary};
        }}

        QTabBar::tab:hover {{
            background-color: {self.colors.surface_hover};
            color: {self.colors.text_primary};
        }}

        /* ===== List Widget ===== */
        QListWidget {{
            background-color: {self.colors.bg_secondary};
            border: {self.borders.width_thin}px solid {self.colors.border_default};
            border-radius: {self.borders.radius_md}px;
            padding: {self.spacing.sm}px;
            outline: none;
        }}

        QListWidget::item {{
            padding: {self.spacing.sm}px;
            border-radius: {self.borders.radius_sm}px;
        }}

        QListWidget::item:selected {{
            background-color: {self.colors.primary};
            color: white;
        }}

        QListWidget::item:hover {{
            background-color: {self.colors.surface_hover};
        }}

        /* ===== Scroll Bars ===== */
        QScrollBar:vertical {{
            background-color: {self.colors.bg_secondary};
            width: 12px;
            border-radius: 6px;
        }}

        QScrollBar::handle:vertical {{
            background-color: {self.colors.surface};
            border-radius: 6px;
            min-height: 20px;
        }}

        QScrollBar::handle:vertical:hover {{
            background-color: {self.colors.surface_hover};
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}

        /* ===== Status Bar ===== */
        QStatusBar {{
            background-color: {self.colors.bg_tertiary};
            color: {self.colors.text_secondary};
            border-top: {self.borders.width_thin}px solid {self.colors.border_default};
        }}

        /* ===== Menu Bar ===== */
        QMenuBar {{
            background-color: {self.colors.bg_secondary};
            color: {self.colors.text_primary};
            border-bottom: {self.borders.width_thin}px solid {self.colors.border_default};
        }}

        QMenuBar::item:selected {{
            background-color: {self.colors.surface_hover};
        }}

        QMenu {{
            background-color: {self.colors.bg_tertiary};
            border: {self.borders.width_thin}px solid {self.colors.border_default};
            border-radius: {self.borders.radius_md}px;
            padding: {self.spacing.xs}px;
        }}

        QMenu::item {{
            padding: {self.spacing.sm}px {self.spacing.md}px;
            border-radius: {self.borders.radius_sm}px;
        }}

        QMenu::item:selected {{
            background-color: {self.colors.primary};
            color: white;
        }}

        /* ===== Progress Bar ===== */
        QProgressBar {{
            background-color: {self.colors.bg_secondary};
            border: {self.borders.width_thin}px solid {self.colors.border_default};
            border-radius: {self.borders.radius_sm}px;
            height: 20px;
            text-align: center;
            color: {self.colors.text_primary};
        }}

        QProgressBar::chunk {{
            background-color: {self.colors.primary};
            border-radius: {self.borders.radius_sm}px;
        }}

        /* ===== Tooltips ===== */
        QToolTip {{
            background-color: {self.colors.bg_tertiary};
            color: {self.colors.text_primary};
            border: {self.borders.width_thin}px solid {self.colors.border_default};
            border-radius: {self.borders.radius_sm}px;
            padding: {self.spacing.sm}px;
        }}

        /* ===== Sliders ===== */
        QSlider::groove:horizontal {{
            background-color: {self.colors.bg_tertiary};
            height: 4px;
            border-radius: 2px;
        }}

        QSlider::handle:horizontal {{
            background-color: {self.colors.primary};
            width: 16px;
            height: 16px;
            margin: -6px 0;
            border-radius: 8px;
        }}

        QSlider::handle:horizontal:hover {{
            background-color: {self.colors.primary_hover};
        }}
        """

    def get_component_style(
        self,
        component: str,
        variant: str = "default",
    ) -> dict[str, str]:
        """Get style dictionary for specific component variants."""
        styles = {
            "card": {
                "default": {
                    "background-color": self.colors.bg_secondary,
                    "border": f"{self.borders.width_thin}px solid {self.colors.border_default}",
                    "border-radius": f"{self.borders.radius_lg}px",
                    "padding": f"{self.spacing.card_padding}px",
                },
                "elevated": {
                    "background-color": self.colors.bg_tertiary,
                    "box-shadow": self.shadows.md,
                    "border": "none",
                    "border-radius": f"{self.borders.radius_lg}px",
                    "padding": f"{self.spacing.card_padding}px",
                },
            },
            "button": {
                "primary": {
                    "background-color": self.colors.primary,
                    "color": "white",
                    "border": "none",
                    "font-weight": str(self.typography.weight_medium),
                },
                "secondary": {
                    "background-color": "transparent",
                    "color": self.colors.primary,
                    "border": f"{self.borders.width_thin}px solid {self.colors.primary}",
                },
                "success": {
                    "background-color": self.colors.success,
                    "color": "white",
                    "border": "none",
                },
                "danger": {
                    "background-color": self.colors.error,
                    "color": "white",
                    "border": "none",
                },
            },
        }

        return styles.get(component, {}).get(variant, {})

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


# Global instance
design_system = DesignSystem()
