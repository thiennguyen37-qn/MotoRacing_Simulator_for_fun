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
CAREER_DIR   = PROJECT_ROOT / 'data' / 'career'   # career/slot{0..9}/{rider,season_save,history}.json
CAREER_SLOTS = 10
START_YEAR   = 2026
# Modes that run a multi-round season loop (calendar, save/resume, archive)
# as opposed to a one-off session ('random') or a non-race page.
SEASON_MODES = {'championship', 'career'}

# Career only: the five sessions of a race weekend, in order. wiz.session_index
# points at the next one; the Career Hub's "Upcoming session" box names it and
# runs them one at a time, returning to the hub between each.
SESSION_NAMES = ['Practice', 'Qualifying 1', 'Qualifying 2', 'Race 1', 'Race 2']


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
        self._base_rider_count = len(self.df)   # 24 base riders, before any Career rider is appended
        self.circuits_df = load_circuits(RAW)

        # Mode state
        self.mode          = None        # 'random' | 'championship' | 'gallery' | 'soundtrack'
        self.circuit_index = 0
        self.all_race_pts  = []

        # Career only: which session of the current round is up next (0-4, see
        # SESSION_NAMES). The Career Hub runs one session per excursion and
        # returns here between them; in-memory only (reset to 0 at round start),
        # which matches the round-granular season save.
        self.session_index = 0

        # Which of the CAREER_SLOTS (0-9) the current Career session reads/
        # writes — set by CareerPage before any save/history/rider call.
        self.career_slot = None
        # Set by CareerPage right before a freshly-created rider hands off to
        # CalendarPage, so it skips its New/Continue menu (there's obviously
        # no season in progress for a rider that was just created).
        self.skip_calendar_menu = False

        # Random Race weather override — None (roll the dice), 'dry', or 'wet'.
        # Set by WeatherPage (shown after Qualifying, random mode only);
        # championship rounds never visit that page and always roll.
        self.forced_weather = None

        # Championship season order (set by CalendarPage)
        self.season_df   = None
        self.season_year = START_YEAR   # +1 every "Next Season"
        # Finished rounds: [{'circuit': name, 'country': ..., 'races': [df, df]}]
        # where each df holds [name, pos, dnf] — feeds the Results tab
        self.round_results = []

        # Per-circuit state (reset each circuit)
        self.circuit          = None
        self.practice_results = None
        # Career splits Qualifying into two hub excursions (Q1, then Q2); the
        # full run_qualifying() output computed during Q1 is parked here so the
        # Q2 visit can show Q2 + the grid without re-simulating.
        self.quali_result     = None
        self.grid_all_df      = None
        self.race_pts         = []
        self.race_results     = []   # current round's per-race classifications
        self.race_fastest_laps = []  # [(seconds, name), ...] one per race this round

        # Audio — created before pages so SoundtrackPage can receive the reference
        self._audio = AudioManager()
        self._toast = NowPlayingToast(self)
        if hasattr(self._audio, 'track_changed'):
            self._audio.track_changed.connect(self._toast.show_track)

        self._audio_started = False
        self._built = False
        self._windowed = False   # True once dropped out of borderless-fullscreen

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
        from app.pages.p_season_hub    import SeasonHubPage
        from app.pages.p0_circuit      import CircuitPage
        from app.pages.p1_practice     import PracticePage
        from app.pages.p2_qualifying   import QualifyingPage
        from app.pages.p_weather       import WeatherPage
        from app.pages.p3_race         import RacePage
        from app.pages.p4_championship import ChampionshipPage
        from app.pages.p_history       import HistoryPage
        from app.pages.p_career        import CareerPage
        from app.pages.p_gallery       import GalleryPage
        from app.pages.p_soundtrack    import SoundtrackPage

        builders = [
            ('ID_HOME',       'Home',         lambda: HomePage(self)),
            ('ID_CALENDAR',   'Season setup', lambda: CalendarPage(self)),
            ('ID_SEASON_HUB', 'Season hub',   lambda: SeasonHubPage(self)),
            ('ID_CIRCUIT',    'Circuits',     lambda: CircuitPage(self)),
            ('ID_PRACTICE',   'Practice',     lambda: PracticePage(self)),
            ('ID_QUALI',      'Qualifying',   lambda: QualifyingPage(self)),
            ('ID_WEATHER',    'Weather',      lambda: WeatherPage(self)),
            ('ID_RACE',       'Race',         lambda: RacePage(self)),
            ('ID_STANDINGS',  'Standings',    lambda: ChampionshipPage(self)),
            ('ID_HISTORY',    'History',      lambda: HistoryPage(self)),
            ('ID_CAREER',     'Career',       lambda: CareerPage(self)),
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

    def pause_music(self):
        """Silence the background playlist (e.g. a page playing its own
        clip's audio) without touching the user's mute/SFX state."""
        self._audio.pause_music()

    def resume_music(self):
        self._audio.resume_music()

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

    def return_to_hub_after_session(self):
        """Career only: a single weekend session just finished — advance the
        session pointer and walk history back to the Season Hub, which the hub
        excursion (hub -> next() -> session page) sits exactly one page ahead
        of. resume_at_hub() re-reads state so the 'Upcoming session' box shows
        the next session. See SESSION_NAMES / SeasonHubPage.nextId()."""
        self.session_index += 1
        self.return_to_hub()

    def return_to_hub(self):
        """Walk history back to the Season Hub and re-show it. Used both when a
        session completes and when one is abandoned with Esc (which leaves
        session_index untouched, so the same session stays up next)."""
        while self.currentId() not in (self.ID_SEASON_HUB, self.startId()):
            self.back()
        if self.currentId() == self.ID_SEASON_HUB:
            self.currentPage().resume_at_hub()

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

            if getattr(page, 'text_entry_active', False):
                # A page-owned QLineEdit currently holds focus (e.g. Career's
                # Name field) — only Enter/Escape are intercepted (to
                # commit/cancel the edit); every other key passes straight
                # through to Qt's normal focused-widget delivery so typing,
                # backspace, and cursor movement behave like a normal
                # QLineEdit instead of the app's D-pad handle_key() contract
                # or any global shortcut (mute, window-chrome toggle, ...).
                if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
                    if hasattr(page, 'handle_key') and page.handle_key(k):
                        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                            self._audio.play_sfx('select')
                        else:
                            self._audio.play_sfx('back')
                        return True
                return False

            if k == Qt.Key.Key_M:
                self._audio.toggle_mute()
                return True

            # Windows/Meta key: drop borderless-fullscreen down to a decorated,
            # near-full window (with the _ ▢ X controls) so the taskbar and
            # window buttons are reachable; press again to go back.
            if k in (Qt.Key.Key_Meta, Qt.Key.Key_Super_L, Qt.Key.Key_Super_R):
                self._toggle_window_chrome()
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

    # ── Borderless-fullscreen ⇄ decorated window ───────────────────────────────

    def _toggle_window_chrome(self):
        if self._windowed:
            self._enter_fullscreen()
        else:
            self._enter_windowed()

    def _enter_windowed(self):
        """Leave borderless-fullscreen for a normal titled window, sized just
        inside the work area (taskbar visible) and centred, with the standard
        minimise / maximise / close buttons."""
        self._windowed = True
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowSystemMenuHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        avail = QApplication.primaryScreen().availableGeometry()
        mw, mh = int(avail.width() * 0.04), int(avail.height() * 0.05)
        rect = avail.adjusted(mw, mh, -mw, -mh)
        self.showNormal()
        self.setGeometry(rect)
        self.show()            # re-show is required after changing window flags
        self._bring_to_front()

    def _enter_fullscreen(self):
        """Back to the borderless window that covers the whole screen."""
        self._windowed = False
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setGeometry(QApplication.primaryScreen().geometry())
        self.show()
        self._bring_to_front()

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

    def career_slot_dir(self, slot=None):
        """Directory for a career slot (default: the active self.career_slot),
        created on first use."""
        s = self.career_slot if slot is None else slot
        d = CAREER_DIR / f'slot{s}'
        d.mkdir(parents=True, exist_ok=True)
        return d

    def season_save_path(self):
        return self.career_slot_dir() / 'season_save.json' if self.mode == 'career' else SEASON_SAVE

    def history_path(self):
        return self.career_slot_dir() / 'history.json' if self.mode == 'career' else HISTORY_FILE

    def save_season(self):
        """Snapshot the running season (at round granularity) so the player
        can continue after restarting the app. Called explicitly at season
        start, on every round advance and by the Home button — never blindly
        on exit (stale wizard state must not overwrite the file)."""
        if self.mode not in SEASON_MODES or self.season_df is None:
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
        self.season_save_path().write_text(json.dumps(data, default=int), encoding='utf-8')

    def save_next_season_marker(self):
        """After a season ends, remember that the career continues: the next
        launch's CONTINUE opens the calendar for the following year."""
        rounds = len(self.season_df) if self.season_df is not None else len(self.circuits_df)
        data = {'season_complete': True,
                'year': self.season_year + 1,
                'rounds': rounds}
        self.season_save_path().write_text(json.dumps(data), encoding='utf-8')

    def load_season_save(self):
        """Return the saved-season dict, or None if absent/corrupt."""
        path = self.season_save_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            return None

    def clear_season_save(self):
        self.season_save_path().unlink(missing_ok=True)

    def clear_history(self):
        """Wipe the season archive — a New career starts from scratch."""
        self.history_path().unlink(missing_ok=True)

    # ── Career rider profiles (10 slots) ──────────────────────────────────────

    def save_career_rider(self, rider: dict, slot=None):
        path = self.career_slot_dir(slot) / 'rider.json'
        path.write_text(json.dumps(rider, default=int), encoding='utf-8')

    def load_career_rider(self, slot=None):
        """Return the saved custom-rider dict for a slot, or None if absent/corrupt."""
        s = self.career_slot if slot is None else slot
        if s is None:
            return None
        path = CAREER_DIR / f'slot{s}' / 'rider.json'
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            return None

    def clear_career_rider(self, slot=None):
        (self.career_slot_dir(slot) / 'rider.json').unlink(missing_ok=True)

    def list_career_slots(self):
        """Return CAREER_SLOTS entries: the saved rider dict for each slot,
        or None for an empty one — feeds the New/Load slot picker."""
        return [self.load_career_rider(slot=i) for i in range(CAREER_SLOTS)]

    def reset_roster_to_base(self):
        """Drop any previously-appended Career rider, back to the 24 base riders."""
        self.df = self.df.iloc[:self._base_rider_count].reset_index(drop=True)

    def _on_page_changed(self, page_id):
        self.setButtonLayout([])
        QTimer.singleShot(0, self._sync_gap_filler)
