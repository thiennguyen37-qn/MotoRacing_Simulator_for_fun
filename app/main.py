import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ['QT_LOGGING_RULES'] = 'qt.multimedia.ffmpeg=false;qt.multimedia=false'

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor, QFont
from PyQt6.QtCore import Qt, QTimer

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

    # Show the loading screen first, then build the (heavy) wizard while the
    # progress bar reflects real init work. The build runs once the event loop
    # is up (so the splash has painted); set_progress repaints synchronously.
    splash = SplashScreen()
    splash.show()

    wizard = MotoWizard()

    def on_built():
        # Reveal the wizard *behind* the still-opaque splash, then let the
        # splash fill to 100% and fade out — a clean crossfade with no gap.
        # Borderless-fullscreen (frameless + full screen geometry) rather than
        # showFullScreen(): the latter fights the topmost fullscreen splash and
        # can end up not covering the whole screen.
        geo = QApplication.primaryScreen().geometry()
        wizard.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        wizard.setGeometry(geo)
        wizard.show()
        splash.raise_()
        splash.complete()

    def on_finished():
        splash.hide()
        wizard.raise_()
        wizard.activateWindow()
        wizard.start_audio()   # music begins only now — home page is visible

    splash.finished.connect(on_finished)
    QTimer.singleShot(60, lambda: wizard.build(progress=splash.set_progress,
                                               done=on_built))

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
