import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor, QFont
from PyQt6.QtCore import Qt

from app.wizard import MotoWizard
from app.splash import SplashScreen


def _dark_palette():
    p = QPalette()
    BG   = QColor(28, 28, 35)
    SURF = QColor(38, 38, 48)
    ALT  = QColor(48, 48, 60)
    TXT  = QColor(220, 220, 230)
    ACC  = QColor(220, 40, 60)
    p.setColor(QPalette.ColorRole.Window,          BG)
    p.setColor(QPalette.ColorRole.WindowText,      TXT)
    p.setColor(QPalette.ColorRole.Base,            SURF)
    p.setColor(QPalette.ColorRole.AlternateBase,   ALT)
    p.setColor(QPalette.ColorRole.Text,            TXT)
    p.setColor(QPalette.ColorRole.Button,          SURF)
    p.setColor(QPalette.ColorRole.ButtonText,      TXT)
    p.setColor(QPalette.ColorRole.Highlight,       ACC)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.Link,            ACC)
    p.setColor(QPalette.ColorRole.ToolTipBase,     SURF)
    p.setColor(QPalette.ColorRole.ToolTipText,     TXT)
    return p


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setPalette(_dark_palette())
    app.setFont(QFont('Segoe UI', 10))

    wizard = MotoWizard()

    splash = SplashScreen()
    splash.finished.connect(wizard.show)
    splash.show()
    splash.start()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
