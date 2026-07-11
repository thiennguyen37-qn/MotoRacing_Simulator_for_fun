import json
import sys
from pathlib import Path
from PyQt6.QtWidgets import QWizard, QApplication, QDialog, QWidget
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtCore import Qt, QEvent, QTimer

from src.loader import load_riders, load_circuits
from app.audio import AudioManager
from app.widgets.now_playing import NowPlayingToast
from app.widgets.video_bg import VideoBackground

PROJECT_ROOT = Path(__file__).parent.parent
RAW          = PROJECT_ROOT / 'data' / 'raw'
SEASON_SAVE  = PROJECT_ROOT / 'data' / 'season_save.json'
HISTORY_FILE = PROJECT_ROOT / 'data' / 'history.json'
START_YEAR   = 2026


class _GapFiller(QWidget):
    """
    Fills the strip QWizard reserves below the page for its (hidden) button
    row. Full-bleed video pages (Home/Gallery/Soundtrack, identified by their
    `_vbg` attribute) get the same video continued seamlessly into the strip —
    see VideoBackground.paint. Other pages just get a plain dark fill.
    """

    def __init__(self, wizard: 'MotoWizard'):
        super().__init__(wizard)
        self._wizard = wizard
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        page = self._wizard.currentPage()
        vbg = getattr(page, '_vbg', None)
        if vbg is not None:
            offset = self.mapTo(self._wizard, self.rect().topLeft())
            vbg.paint(p, self, full_size=self._wizard.size(), offset=offset)
        overlay = getattr(page, 'paint_gap_overlay', None)
        if overlay is not None:
            overlay(p, self.rect())


class MotoWizard(QWizard):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('MotoRacing Simulator')
        self.setMinimumSize(1060, 680)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowSystemMenuHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint
        )

        # Data
        self.df          = load_riders(RAW)
        self.circuits_df = load_circuits(RAW)

        # Mode state
        self.mode          = None        # 'random' | 'championship' | 'gallery' | 'soundtrack'
        self.circuit_index = 0
        self.all_race_pts  = []

        # Championship season order (set by CalendarPage)
        self.season_df   = None
        self.season_year = START_YEAR   # +1 every "Next Season"
        # Finished rounds: [{'circuit': name, 'country': ..., 'races': [df, df]}]
        # where each df holds [name, pos, dnf] — feeds the Results tab
        self.round_results = []

        # Per-circuit state (reset each circuit)
        self.circuit          = None
        self.practice_results = None
        self.grid_all_df      = None
        self.race_pts         = []
        self.race_results     = []   # current round's per-race classifications

        # Audio — created before pages so SoundtrackPage can receive the reference
        self._audio = AudioManager()
        self._toast = NowPlayingToast(self)
        if hasattr(self._audio, 'track_changed'):
            self._audio.track_changed.connect(self._toast.show_track)

        self._audio_started = False
        self._built = False

    # ── Page build (drives the loading bar) ────────────────────────────────────

    def build(self, progress=None, done=None):
        """Build the (heavy) pages synchronously, reporting progress before
        each one. `progress` should paint immediately (SplashScreen.set_progress
        uses repaint()); we deliberately never run the event loop mid-build,
        so the half-constructed video/map widgets are never re-entered."""
        def report(frac, label=''):
            if progress:
                progress(frac, label)

        report(0.12, 'Loading modules')
        from app.pages.p_home          import HomePage
        from app.pages.p_calendar      import CalendarPage      # pulls in the map stack
        from app.pages.p0_circuit      import CircuitPage
        from app.pages.p1_practice     import PracticePage
        from app.pages.p2_qualifying   import QualifyingPage
        from app.pages.p3_race         import RacePage
        from app.pages.p4_championship import ChampionshipPage
        from app.pages.p_history       import HistoryPage
        from app.pages.p_gallery       import GalleryPage
        from app.pages.p_soundtrack    import SoundtrackPage

        builders = [
            ('ID_HOME',       'Home',         lambda: HomePage(self)),
            ('ID_CALENDAR',   'Season setup', lambda: CalendarPage(self)),
            ('ID_CIRCUIT',    'Circuits',     lambda: CircuitPage(self)),
            ('ID_PRACTICE',   'Practice',     lambda: PracticePage(self)),
            ('ID_QUALI',      'Qualifying',   lambda: QualifyingPage(self)),
            ('ID_RACE',       'Race',         lambda: RacePage(self)),
            ('ID_STANDINGS',  'Standings',    lambda: ChampionshipPage(self)),
            ('ID_HISTORY',    'History',      lambda: HistoryPage(self)),
            ('ID_GALLERY',    'Gallery',      lambda: GalleryPage(self)),
            ('ID_SOUNDTRACK', 'Soundtrack',   lambda: SoundtrackPage(self, self._audio)),
        ]
        for i, (attr, label, make) in enumerate(builders):
            report(0.18 + 0.75 * i / len(builders), label)
            setattr(self, attr, self.addPage(make()))

        report(0.96, 'Finishing up')
        self._finalize()
        if done:
            done()

    def _finalize(self):
        # NOTE: IndependentPages is deliberately NOT set — the championship
        # loops Practice -> ... -> Standings -> Practice, and with that option
        # revisited pages would never run initializePage again (stale data).
        self.setButtonText(QWizard.WizardButton.NextButton,   'Continue →')
        self.setButtonText(QWizard.WizardButton.FinishButton, 'Finish')
        self.setButtonText(QWizard.WizardButton.BackButton,   '← Back')
        self.setButtonText(QWizard.WizardButton.CancelButton, 'Exit')

        self.setMaximumSize(16_777_215, 16_777_215)

        # QWizard reserves a strip at the bottom for its button row — even with
        # setButtonLayout([]) the row stays 0-height but the space (and its
        # lighter default background) remains, showing as a stray gray bar.
        # This continues the current page's own background into that strip.
        self._gap_filler = _GapFiller(self)
        VideoBackground.instance().frame_ready.connect(self._gap_filler.update)

        self.currentIdChanged.connect(self._on_page_changed)
        self._on_page_changed(self.ID_HOME)

        self.setCursor(Qt.CursorShape.BlankCursor)
        QApplication.instance().installEventFilter(self)
        self._built = True

    def start_audio(self):
        """Begin playback — called once the splash has faded and the home page
        is actually on screen (not while the window is still hidden behind the
        splash), so the music doesn't start ~1s early."""
        if not self._audio_started:
            self._audio_started = True
            self._audio.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._sync_gap_filler)

    def _sync_gap_filler(self):
        # a resize can be scheduled before build() creates the filler
        if not getattr(self, '_built', False):
            return
        page = self.currentPage()
        if page is None:
            self._gap_filler.hide()
            return
        # page.geometry() is in its parent's coordinates; on pages with a
        # title, QWizard's header banner sits above that parent, so map the
        # page bottom into wizard coordinates to place the filler correctly.
        y = page.mapTo(self, page.rect().bottomLeft()).y() + 1
        h = self.height() - y
        if h <= 0:
            self._gap_filler.hide()
            return
        self._gap_filler.setGeometry(0, y, self.width(), h)
        self._gap_filler.show()
        self._gap_filler.raise_()
        # a page may own a bottom overlay (e.g. the home status bar) that must
        # sit above the gap filler
        place = getattr(page, 'place_bottom_overlay', None)
        if place is not None:
            place()
        self._toast.raise_()   # keep the now-playing toast above everything

    def reject(self):
        pass  # prevent Escape from closing the wizard

    def accept(self):
        """Finishing any mode returns to the home page — the app only exits
        via the EXIT bar or the window close button."""
        self.restart()
        self.page(self.ID_HOME).initializePage()

    def eventFilter(self, obj, event):
        # keep the gap filler glued to the page bottom whenever QWizard
        # relayouts the page (maximize, header appearing, etc.)
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move) and obj is self.currentPage():
            self._sync_gap_filler()

        if event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseMove,
            QEvent.Type.Wheel,
        ):
            return True
        if event.type() == QEvent.Type.KeyPress and self.isActiveWindow():
            page = self.currentPage()
            k = event.key()

            if k == Qt.Key.Key_M:
                self._audio.toggle_mute()
                return True

            if hasattr(page, 'handle_key') and page.handle_key(k):
                if k in (Qt.Key.Key_Up, Qt.Key.Key_Down,
                         Qt.Key.Key_Left, Qt.Key.Key_Right):
                    self._audio.play_sfx('navigate')
                elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter,
                            Qt.Key.Key_Space):
                    self._audio.play_sfx('select')
                elif k in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
                    self._audio.play_sfx('back')
                return True

            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if page and page.isComplete():
                    self._audio.play_sfx('select')
                    if page.nextId() == -1:
                        self.accept()
                    else:
                        self.next()
                    return True
            elif k in (Qt.Key.Key_Backspace, Qt.Key.Key_Escape):
                if self.currentId() != self.startId():
                    self._audio.play_sfx('back')
                    self.back()
                    return True
        return False

    def _bring_to_front(self):
        """Force the borderless-fullscreen window above the current foreground
        app. A plain raise_()/activateWindow() from a background process is
        reduced by Windows' foreground lock to a taskbar flash, so on Windows
        attach to the foreground thread's input queue to bypass it."""
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        if sys.platform == 'win32':
            try:
                import ctypes
                from ctypes import wintypes
                u = ctypes.windll.user32
                u.GetForegroundWindow.restype = wintypes.HWND
                u.GetWindowThreadProcessId.restype = wintypes.DWORD
                u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, wintypes.LPDWORD]
                u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
                u.SetForegroundWindow.argtypes = [wintypes.HWND]
                u.BringWindowToTop.argtypes = [wintypes.HWND]
                hwnd     = wintypes.HWND(int(self.winId()))
                fg       = u.GetForegroundWindow()
                own_tid  = u.GetWindowThreadProcessId(hwnd, None)
                fg_tid   = u.GetWindowThreadProcessId(fg, None) if fg else 0
                if fg_tid and fg_tid != own_tid:
                    u.AttachThreadInput(fg_tid, own_tid, True)
                    u.BringWindowToTop(hwnd)
                    u.SetForegroundWindow(hwnd)
                    u.AttachThreadInput(fg_tid, own_tid, False)
                else:
                    u.BringWindowToTop(hwnd)
                    u.SetForegroundWindow(hwnd)
            except Exception:
                pass
        QApplication.processEvents()   # let the window paint before the dialog

    def closeEvent(self, event):
        # NOTE: no auto-save here. Every field the season save captures only
        # changes at round boundaries, where an explicit save already fires
        # (season start, round advance, the Home button). Saving on exit used
        # to clobber the pending-next-season marker with stale wizard state.

        # Bring the borderless-fullscreen window to the front first. Closing
        # from the taskbar while another app (e.g. VS Code) is focused would
        # otherwise pop the confirmation over that app, with the simulator still
        # hidden behind it.
        self._bring_to_front()

        from app.pages.p_home import ExitDialog
        if ExitDialog(self).exec() == QDialog.DialogCode.Accepted:
            event.accept()
        else:
            event.ignore()

    # ── Season save / resume ──────────────────────────────────────────────────

    def save_season(self):
        """Snapshot the running championship (at round granularity) so the
        player can continue after restarting the app. Called explicitly at
        season start, on every round advance and by the Home button — never
        blindly on exit (stale wizard state must not overwrite the file)."""
        if self.mode != 'championship' or self.season_df is None:
            return
        data = {
            'year':          self.season_year,
            'rounds':        len(self.season_df),
            'circuit_index': self.circuit_index,
            'calendar':      [str(n) for n in self.season_df['circuit_name']],
            'all_race_pts':  [df.to_dict('records') for df in self.all_race_pts],
            'round_results': [
                {'circuit': str(rd['circuit']), 'country': str(rd['country']),
                 'races': [df.to_dict('records') for df in rd['races']]}
                for rd in self.round_results],
        }
        SEASON_SAVE.write_text(json.dumps(data, default=int), encoding='utf-8')

    def save_next_season_marker(self):
        """After a season ends, remember that the career continues: the next
        launch's CONTINUE opens the calendar for the following year."""
        rounds = len(self.season_df) if self.season_df is not None else len(self.circuits_df)
        data = {'season_complete': True,
                'year': self.season_year + 1,
                'rounds': rounds}
        SEASON_SAVE.write_text(json.dumps(data), encoding='utf-8')

    @staticmethod
    def load_season_save():
        """Return the saved-season dict, or None if absent/corrupt."""
        if not SEASON_SAVE.exists():
            return None
        try:
            return json.loads(SEASON_SAVE.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def clear_season_save():
        SEASON_SAVE.unlink(missing_ok=True)

    @staticmethod
    def clear_history():
        """Wipe the championship archive — a New career starts from scratch."""
        HISTORY_FILE.unlink(missing_ok=True)

    def _on_page_changed(self, page_id):
        self.setButtonLayout([])
        QTimer.singleShot(0, self._sync_gap_filler)
