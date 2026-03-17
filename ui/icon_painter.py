"""Shared icon painting utilities for grid view context menus.

Provides a standalone function for creating coloured shaped QIcon objects
used across shot_grid_view, previous_shots_view, and threede_grid_view.
"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def create_icon(icon_type: str, color: str, size: int = 33) -> QIcon:
    """Create a coloured shaped icon for menu items.

    Args:
        icon_type: Icon type - "pin", "folder", "film", "plate", "rocket",
                  "target", "palette", "cube", "play", "clipboard", "note"
        color: Hex colour string (e.g., "#FF6B6B")
        size: Icon size in pixels

    Returns:
        QIcon with the specified shape and colour

    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)

    # Scale factor for drawing
    s = size

    if icon_type == "pin":
        # Pushpin: round head + long needle
        # Head (top circle)
        painter.drawEllipse(int(s * 0.25), int(s * 0.05), int(s * 0.5), int(s * 0.35))
        # Needle body (rectangle)
        painter.drawRect(int(s * 0.42), int(s * 0.35), int(s * 0.16), int(s * 0.4))
        # Needle point (triangle)
        points = [
            QPoint(int(s * 0.42), int(s * 0.75)),
            QPoint(int(s * 0.58), int(s * 0.75)),
            QPoint(int(s * 0.5), int(s * 0.98)),
        ]
        painter.drawPolygon(points)

    elif icon_type == "folder":
        # Open folder with document
        # Back of folder
        painter.drawRoundedRect(
            int(s * 0.05), int(s * 0.2), int(s * 0.9), int(s * 0.65), 3, 3
        )
        # Folder tab
        painter.drawRoundedRect(
            int(s * 0.05), int(s * 0.12), int(s * 0.35), int(s * 0.15), 2, 2
        )
        # Document peeking out (white)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRect(int(s * 0.25), int(s * 0.08), int(s * 0.5), int(s * 0.45))
        # Document lines
        painter.setPen(QPen(QColor(color), 1))
        for i in range(3):
            y = int(s * (0.18 + i * 0.12))
            painter.drawLine(int(s * 0.32), y, int(s * 0.68), y)

    elif icon_type == "film":
        # Clapperboard with diagonal stripes
        # Main board
        painter.drawRect(int(s * 0.05), int(s * 0.25), int(s * 0.9), int(s * 0.7))
        # Clapper top (angled)
        points = [
            QPoint(int(s * 0.05), int(s * 0.25)),
            QPoint(int(s * 0.15), int(s * 0.05)),
            QPoint(int(s * 0.95), int(s * 0.05)),
            QPoint(int(s * 0.95), int(s * 0.25)),
        ]
        painter.drawPolygon(points)
        # Diagonal stripes on clapper (white)
        painter.setBrush(QColor("#FFFFFF"))
        stripe_points = [
            [
                QPoint(int(s * 0.25), int(s * 0.05)),
                QPoint(int(s * 0.35), int(s * 0.05)),
                QPoint(int(s * 0.25), int(s * 0.25)),
                QPoint(int(s * 0.15), int(s * 0.25)),
            ],
            [
                QPoint(int(s * 0.55), int(s * 0.05)),
                QPoint(int(s * 0.65), int(s * 0.05)),
                QPoint(int(s * 0.55), int(s * 0.25)),
                QPoint(int(s * 0.45), int(s * 0.25)),
            ],
            [
                QPoint(int(s * 0.85), int(s * 0.05)),
                QPoint(int(s * 0.95), int(s * 0.05)),
                QPoint(int(s * 0.85), int(s * 0.25)),
                QPoint(int(s * 0.75), int(s * 0.25)),
            ],
        ]
        for stripe in stripe_points:
            painter.drawPolygon(stripe)

    elif icon_type == "plate":
        # Film strip frame with sprocket holes (for viewing footage)
        # Main frame area
        painter.drawRect(int(s * 0.15), int(s * 0.05), int(s * 0.7), int(s * 0.9))
        # Left sprocket strip
        painter.drawRect(int(s * 0.0), int(s * 0.05), int(s * 0.15), int(s * 0.9))
        # Right sprocket strip
        painter.drawRect(int(s * 0.85), int(s * 0.05), int(s * 0.15), int(s * 0.9))
        # Sprocket holes (left side)
        painter.setBrush(QColor("#FFFFFF"))
        for i in range(4):
            y = int(s * (0.12 + i * 0.22))
            painter.drawRoundedRect(
                int(s * 0.03), y, int(s * 0.09), int(s * 0.12), 1, 1
            )
        # Sprocket holes (right side)
        for i in range(4):
            y = int(s * (0.12 + i * 0.22))
            painter.drawRoundedRect(
                int(s * 0.88), y, int(s * 0.09), int(s * 0.12), 1, 1
            )
        # Inner frame (image area) - slightly darker
        painter.setBrush(QColor(color).darker(120))
        painter.drawRect(int(s * 0.22), int(s * 0.15), int(s * 0.56), int(s * 0.7))

    elif icon_type == "rocket":
        # Rocket with nose cone, body, fins, and flame
        painter.setBrush(QColor(color))
        # Nose cone (triangle)
        nose = [
            QPoint(int(s * 0.5), 0),
            QPoint(int(s * 0.3), int(s * 0.25)),
            QPoint(int(s * 0.7), int(s * 0.25)),
        ]
        painter.drawPolygon(nose)
        # Body
        painter.drawRect(int(s * 0.3), int(s * 0.25), int(s * 0.4), int(s * 0.45))
        # Left fin
        fin_left = [
            QPoint(int(s * 0.3), int(s * 0.5)),
            QPoint(int(s * 0.05), int(s * 0.75)),
            QPoint(int(s * 0.3), int(s * 0.7)),
        ]
        painter.drawPolygon(fin_left)
        # Right fin
        fin_right = [
            QPoint(int(s * 0.7), int(s * 0.5)),
            QPoint(int(s * 0.95), int(s * 0.75)),
            QPoint(int(s * 0.7), int(s * 0.7)),
        ]
        painter.drawPolygon(fin_right)
        # Flame (orange/yellow gradient effect)
        painter.setBrush(QColor("#FF6600"))
        flame = [
            QPoint(int(s * 0.35), int(s * 0.7)),
            QPoint(int(s * 0.65), int(s * 0.7)),
            QPoint(int(s * 0.5), int(s * 0.98)),
        ]
        painter.drawPolygon(flame)
        painter.setBrush(QColor("#FFCC00"))
        inner_flame = [
            QPoint(int(s * 0.42), int(s * 0.7)),
            QPoint(int(s * 0.58), int(s * 0.7)),
            QPoint(int(s * 0.5), int(s * 0.88)),
        ]
        painter.drawPolygon(inner_flame)

    elif icon_type == "target":
        # Crosshair/target with lines through center
        # Outer ring
        painter.drawEllipse(int(s * 0.08), int(s * 0.08), int(s * 0.84), int(s * 0.84))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(int(s * 0.2), int(s * 0.2), int(s * 0.6), int(s * 0.6))
        painter.setBrush(QColor(color))
        painter.drawEllipse(int(s * 0.35), int(s * 0.35), int(s * 0.3), int(s * 0.3))
        # Crosshair lines
        painter.setPen(QPen(QColor(color), max(1, int(s * 0.06))))
        painter.drawLine(int(s * 0.5), 0, int(s * 0.5), int(s * 0.3))
        painter.drawLine(int(s * 0.5), int(s * 0.7), int(s * 0.5), s)
        painter.drawLine(0, int(s * 0.5), int(s * 0.3), int(s * 0.5))
        painter.drawLine(int(s * 0.7), int(s * 0.5), s, int(s * 0.5))

    elif icon_type == "palette":
        # Artist palette with thumb hole
        # Main palette shape (bean-like)
        painter.drawEllipse(int(s * 0.05), int(s * 0.15), int(s * 0.9), int(s * 0.7))
        # Thumb hole (cut out)
        painter.setBrush(QColor("#00000000"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.drawEllipse(int(s * 0.12), int(s * 0.55), int(s * 0.2), int(s * 0.22))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        # Paint blobs
        paint_colors = ["#E74C3C", "#3498DB", "#F1C40F", "#2ECC71", "#9B59B6"]
        positions = [(0.35, 0.25), (0.6, 0.22), (0.78, 0.35), (0.7, 0.55), (0.45, 0.5)]
        for c, (px, py) in zip(paint_colors, positions, strict=True):
            painter.setBrush(QColor(c))
            painter.drawEllipse(
                int(s * px), int(s * py), int(s * 0.15), int(s * 0.15)
            )

    elif icon_type == "cube":
        # 3D cube with visible edges
        # Use lighter shade for top and right faces
        base_color = QColor(color)
        light_color = base_color.lighter(130)
        dark_color = base_color.darker(120)
        # Front face
        painter.setBrush(base_color)
        painter.drawRect(int(s * 0.1), int(s * 0.35), int(s * 0.5), int(s * 0.55))
        # Top face (lighter)
        painter.setBrush(light_color)
        top = [
            QPoint(int(s * 0.1), int(s * 0.35)),
            QPoint(int(s * 0.35), int(s * 0.1)),
            QPoint(int(s * 0.85), int(s * 0.1)),
            QPoint(int(s * 0.6), int(s * 0.35)),
        ]
        painter.drawPolygon(top)
        # Right face (darker)
        painter.setBrush(dark_color)
        right = [
            QPoint(int(s * 0.6), int(s * 0.35)),
            QPoint(int(s * 0.85), int(s * 0.1)),
            QPoint(int(s * 0.85), int(s * 0.65)),
            QPoint(int(s * 0.6), int(s * 0.9)),
        ]
        painter.drawPolygon(right)

    elif icon_type == "play":
        # Classic play button - rounded rect with bold triangle
        # Rounded rectangle background
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(
            int(s * 0.02), int(s * 0.02), int(s * 0.96), int(s * 0.96), 4, 4
        )
        # Bold play triangle (white, larger and centered)
        painter.setBrush(QColor("#FFFFFF"))
        play = [
            QPoint(int(s * 0.3), int(s * 0.15)),
            QPoint(int(s * 0.3), int(s * 0.85)),
            QPoint(int(s * 0.85), int(s * 0.5)),
        ]
        painter.drawPolygon(play)

    elif icon_type == "clipboard":
        # Clipboard with checkmark
        # Board
        painter.drawRoundedRect(
            int(s * 0.1), int(s * 0.15), int(s * 0.8), int(s * 0.8), 3, 3
        )
        # Clip at top (metallic)
        painter.setBrush(QColor("#888888"))
        painter.drawRoundedRect(
            int(s * 0.3), int(s * 0.02), int(s * 0.4), int(s * 0.2), 2, 2
        )
        # Checkmark (white)
        painter.setPen(QPen(QColor("#FFFFFF"), max(2, int(s * 0.12))))
        painter.drawLine(
            int(s * 0.25), int(s * 0.55), int(s * 0.42), int(s * 0.75)
        )
        painter.drawLine(
            int(s * 0.42), int(s * 0.75), int(s * 0.75), int(s * 0.35)
        )

    elif icon_type == "note":
        # Sticky note with folded corner
        # Note body
        painter.drawRect(int(s * 0.08), int(s * 0.08), int(s * 0.84), int(s * 0.84))
        # Folded corner (darker)
        painter.setBrush(QColor(color).darker(130))
        fold = [
            QPoint(int(s * 0.65), int(s * 0.08)),
            QPoint(int(s * 0.92), int(s * 0.08)),
            QPoint(int(s * 0.92), int(s * 0.35)),
        ]
        painter.drawPolygon(fold)
        # Lines on note
        painter.setPen(QPen(QColor("#FFFFFF").darker(110), 1))
        for i in range(3):
            y = int(s * (0.35 + i * 0.18))
            painter.drawLine(int(s * 0.18), y, int(s * 0.82), y)

    else:
        # Fallback: simple circle
        painter.drawEllipse(int(s * 0.1), int(s * 0.1), int(s * 0.8), int(s * 0.8))

    _ = painter.end()
    return QIcon(pixmap)
