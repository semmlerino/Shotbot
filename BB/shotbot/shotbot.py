#!/usr/bin/env python3
"""ShotBot - VFX Shot Launcher

A PySide6 GUI application for browsing shots and launching applications
in shot context.
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from main_window import MainWindow


def main():
    """Main entry point."""
    # Create application
    app = QApplication(sys.argv)

    # Set application info
    app.setApplicationName("ShotBot")
    app.setOrganizationName("VFX")

    # Set dark theme
    app.setStyle("Fusion")

    # Dark palette
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette()

    # Window colors
    palette.setColor(QPalette.ColorRole.Window, QColor(35, 35, 35))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)

    # Base colors (for input widgets)
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(35, 35, 35))

    # Text colors
    palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)

    # Button colors
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)

    # Highlight colors
    palette.setColor(QPalette.ColorRole.Highlight, QColor(13, 115, 119))
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)

    # Disabled colors
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor(127, 127, 127),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(127, 127, 127)
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(127, 127, 127),
    )

    app.setPalette(palette)

    # Create and show main window
    window = MainWindow()
    window.show()

    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
