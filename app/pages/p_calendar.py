import random
import pandas as pd
from pathlib import Path
from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QLabel, QFrame, QStackedWidget, QWidget)
from PyQt6.QtGui import QFont, QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt, QTimer

from app.widgets.video_bg import VideoBackground
from app.widgets.world_map import WorldMapWidget

_FLAGS = Path(__file__).parent.parent.parent / 'data' / 'flags'

_ISO2 = {
    'Australia': 'au', 'Japan': 'jp', 'Italy': 'it', 'Spain': 'es',
    'Germany': 'de', 'United Kingdom': 'gb', 'Brazil': 'br',
    'Argentina': 'ar', 'Netherlands': 'nl', 'France': 'fr',
    'Portugal': 'pt', 'Thailand': 'th', 'Qatar': 'qa',
}


def _flag_pix(country: str, w: int = 22, h: int = 14) -> QPixmap | None:
    """Force every flag into the same w×h box (ignoring its native aspect
    ratio) so the list reads as one uniform size — flag art varies from
    ~1.5:1 to 2.5:1, so scaling to a fixed height alone left wide flags
    (UK, Australia, Qatar) overflowing their fixed-width container and
    getting clipped/shifted instead."""
    p = _FLAGS / f"{_ISO2.get(str(country), '')}.png"
    if not p.exists():
        return None
    return QPixmap(str(p)).scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)


def _caps_label(text: str, size: int = 8, color: str = '#ffffff') -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont('Segoe UI', size, QFont.Weight.Bold))
    lbl.setStyleSheet(f'color: {color}; letter-spacing: 3px; background: transparent; border: none;')
    return lbl


_BAR_SS = """
    QFrame {{
        background: {bg};
        border: 1px solid {border};
        border-radius: 6px;
    }}
    QLabel {{ background: transparent; border: none; }}
"""


# ── Round slot bar (left column) ──────────────────────────────────────────────

class _SlotBar(QFrame):
    def __init__(self, round_no: int, height: int = 32):
        super().__init__()
        self.setFixedHeight(height)
        self._focused = False
        self._filled  = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(12)

        self._num = QLabel(f'{round_no:02d}')
        self._num.setFont(QFont('Consolas', 10, QFont.Weight.Bold))
        self._num.setFixedWidth(24)
        lay.addWidget(self._num)

        self._flag = QLabel()
        self._flag.setFixedWidth(22)
        self._flag.setVisible(False)
        lay.addWidget(self._flag)

        self._name = QLabel('— select circuit —')
        self._name.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        lay.addWidget(self._name, 1)

        self._country = QLabel('')
        self._country.setFont(QFont('Segoe UI', 8))
        lay.addWidget(self._country)

        self._apply()

    def set_focused(self, v: bool):
        self._focused = v
        self._apply()

    def set_row_height(self, height: int):
        self.setFixedHeight(height)

    def set_circuit(self, circuit):
        """circuit: pandas row or None (empty slot)."""
        if circuit is None:
            self._filled = False
            self._name.setText('— select circuit —')
            self._country.setText('')
            self._flag.setVisible(False)
        else:
            self._filled = True
            self._name.setText(str(circuit['circuit_name']))
            self._country.setText(str(circuit['country']).upper())
            pix = _flag_pix(circuit['country'])
            if pix:
                self._flag.setPixmap(pix)
                self._flag.setVisible(True)
        self._apply()

    def _apply(self):
        if self._focused:
            bg, border = 'rgba(224,40,64,35)', '#e02840'
            num, name, country = '#e02840', '#ffffff', '#ffffff'
        elif self._filled:
            bg, border = 'rgba(255,255,255,6)', '#2a2a3a'
            num, name, country = '#ffffff', '#ffffff', '#ffffff'
        else:
            bg, border = 'rgba(255,255,255,3)', '#1a1a26'
            num, name, country = '#ffffff', '#ffffff', '#ffffff'
        self.setStyleSheet(_BAR_SS.format(bg=bg, border=border))
        self._num.setStyleSheet(f'color: {num};')
        self._name.setStyleSheet(f'color: {name};')
        self._country.setStyleSheet(f'color: {country}; letter-spacing: 2px;')


# ── Random-calendar bar (always available) ────────────────────────────────────

class _RandomBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(34)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        self._lbl = QLabel('RANDOM CALENDAR')
        self._lbl.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._lbl)
        self.set_focused(False)

    def set_focused(self, focused: bool):
        if focused:
            bg, border, txt = 'rgba(255,255,255,16)', '#8888aa', '#ffffff'
        else:
            bg, border, txt = 'rgba(255,255,255,5)', '#2a2a3a', '#ffffff'
        self.setStyleSheet(_BAR_SS.format(bg=bg, border=border))
        self._lbl.setStyleSheet(f'color: {txt}; letter-spacing: 2px;')


# ── Start-season bar (below the slots) ────────────────────────────────────────

class _StartBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(34)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        self._lbl = QLabel('START SEASON  →')
        self._lbl.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._lbl)
        self.set_state(False, False)

    def set_state(self, enabled: bool, focused: bool):
        if enabled and focused:
            bg, border, txt = '#e02840', '#ff6080', '#ffffff'
        elif enabled:
            bg, border, txt = 'rgba(224,40,64,20)', '#993020', '#ff7766'
        elif focused:
            bg, border, txt = 'rgba(255,255,255,8)', '#555566', '#888899'
        else:
            bg, border, txt = 'rgba(255,255,255,3)', '#1a1a26', '#444455'
        self.setStyleSheet(_BAR_SS.format(bg=bg, border=border))
        self._lbl.setStyleSheet(f'color: {txt}; letter-spacing: 2px;')


# ── New / Continue menu bar (championship entry) ──────────────────────────────

class _MenuBar(QFrame):
    def __init__(self, title: str, sub: str):
        super().__init__()
        self.setFixedHeight(64)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 10, 22, 10)
        lay.setSpacing(3)
        self._ttl = QLabel(title)
        self._ttl.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        self._sub = QLabel(sub)
        self._sub.setFont(QFont('Segoe UI', 9))
        lay.addWidget(self._ttl)
        lay.addWidget(self._sub)
        self.set_state(False, True)

    def set_sub(self, text: str):
        self._sub.setText(text)

    def set_state(self, focused: bool, enabled: bool):
        # solid fills — the video behind made translucent bars hard to read
        if focused and enabled:
            bg, border, ttl, sub = '#33161f', '#e02840', '#ffffff', '#ffffff'
        elif focused:                                     # focused but disabled
            bg, border, ttl, sub = '#20202a', '#555566', '#666677', '#444455'
        elif enabled:
            bg, border, ttl, sub = '#191922', '#222233', '#ffffff', '#ffffff'
        else:                                             # disabled
            bg, border, ttl, sub = '#14141c', '#1a1a26', '#3a3a4a', '#2a2a36'
        self.setStyleSheet(_BAR_SS.format(bg=bg, border=border))
        self._ttl.setStyleSheet(f'color: {ttl}; letter-spacing: 2px;')
        self._sub.setStyleSheet(f'color: {sub};')


# ── Season-length selector (compact, sits beside the ROUNDS caps) ─────────────

class _RoundsBar(QFrame):
    def __init__(self, value: int):
        super().__init__()
        self.setFixedHeight(24)
        self._value   = value
        self._focused = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)
        self._left  = QLabel('◀')
        self._val   = QLabel('')
        self._right = QLabel('▶')
        for lbl, w in ((self._left, 12), (self._val, 24), (self._right, 12)):
            lbl.setFixedWidth(w)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._left.setFont(QFont('Segoe UI', 8))
        self._right.setFont(QFont('Segoe UI', 8))
        self._val.setFont(QFont('Consolas', 10, QFont.Weight.Bold))
        lay.addWidget(self._left)
        lay.addWidget(self._val)
        lay.addWidget(self._right)
        self._apply()

    def set_value(self, v: int):
        self._value = v
        self._apply()

    def set_focused(self, f: bool):
        self._focused = f
        self._apply()

    def _apply(self):
        self._val.setText(f'{self._value}')
        if self._focused:
            bg, border, arrows, val = 'rgba(224,40,64,35)', '#e02840', '#ff8899', '#ffffff'
        else:
            bg, border, arrows, val = 'rgba(255,255,255,4)', '#222233', '#ffffff', '#ffffff'
        self.setStyleSheet(_BAR_SS.format(bg=bg, border=border))
        self._left.setStyleSheet(f'color: {arrows};')
        self._right.setStyleSheet(f'color: {arrows};')
        self._val.setStyleSheet(f'color: {val};')


# ── Circuit row (right column picker) ─────────────────────────────────────────

class _PickRow(QFrame):
    def __init__(self, idx: int, circuit):
        super().__init__()
        self.setFixedHeight(34)
        self._focused = False
        self._taken   = None    # round number that owns this circuit, or None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(12)

        self._num = QLabel(f'{idx + 1:02d}')
        self._num.setFont(QFont('Consolas', 9))
        self._num.setFixedWidth(22)
        lay.addWidget(self._num)

        self._flag = QLabel()
        self._flag.setFixedWidth(22)
        pix = _flag_pix(circuit['country'])
        if pix:
            self._flag.setPixmap(pix)
        lay.addWidget(self._flag)

        self._name = QLabel(str(circuit['circuit_name']))
        self._name.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        lay.addWidget(self._name, 1)

        self._tag = QLabel('')
        self._tag.setFont(QFont('Consolas', 8, QFont.Weight.Bold))
        self._tag.setFixedWidth(30)
        self._tag.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._tag)

        self._apply()

    def set_focused(self, v: bool):
        self._focused = v
        self._apply()

    def set_taken(self, round_no: int | None):
        self._taken = round_no
        self._tag.setText(f'R{round_no:02d}' if round_no is not None else '')
        self._apply()

    def _apply(self):
        taken = self._taken is not None
        if self._focused:
            if taken:   # focusable but Enter is denied — muted red
                bg, border = 'rgba(224,40,64,12)', '#552030'
                num, name, tag = '#553344', '#775566', '#884455'
            else:
                bg, border = 'rgba(224,40,64,35)', '#e02840'
                num, name, tag = '#e02840', '#ffffff', '#e02840'
        elif taken:
            bg, border = 'rgba(255,255,255,2)', '#15151f'
            num, name, tag = '#33333f', '#3a3a4a', '#663344'
        else:
            bg, border = 'rgba(255,255,255,4)', '#222233'
            num, name, tag = '#ffffff', '#ffffff', '#ffffff'
        self.setStyleSheet(_BAR_SS.format(bg=bg, border=border))
        self._num.setStyleSheet(f'color: {num};')
        self._name.setStyleSheet(f'color: {name};')
        self._tag.setStyleSheet(f'color: {tag};')


# ── Page ──────────────────────────────────────────────────────────────────────

class CalendarPage(QWizardPage):
    """Championship season setup — assign each of the 13 rounds a circuit."""

    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('')
        self.setSubTitle('')
        # shared, always-running video background (same player as the homepage,
        # so it just carries on — never restarts)
        self._vbg = VideoBackground.instance()
        self._vbg.frame_ready.connect(self._on_bg_frame)

        self._n = len(wiz.circuits_df)      # available circuits (= max rounds)
        self._rounds = self._n              # season length, user-selectable 1.._n
        self._assign: list[int | None] = [None] * self._n
        # focus token: 'len' | slot index (0.._rounds-1) | 'random' | 'start'
        self._focus       = 'len'
        self._picker_open = False
        self._pick_focus  = 0
        self._resume      = False
        self._new_career  = False           # NEW pressed; wipe deferred to START
        self._menu_focus  = 'new'           # 'new' | 'cont' (menu phase)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._pages = QStackedWidget()      # 0 = New/Continue menu, 1 = calendar
        self._pages.setStyleSheet('background: transparent;')
        outer.addWidget(self._pages)

        # ── Page 0: New / Continue menu ───────────────────────────────────────
        menu_w = QWidget()
        menu_w.setStyleSheet('background: transparent;')
        ml = QVBoxLayout(menu_w)
        ml.setContentsMargins(36, 24, 36, 24)
        ml.addStretch(2)
        m_sub = QLabel('Start a new championship or continue where you left off')
        m_sub.setFont(QFont('Segoe UI', 18))
        m_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        m_sub.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        ml.addWidget(m_sub)
        ml.addSpacing(20)
        m_center = QHBoxLayout()
        m_center.addStretch(1)
        m_col = QVBoxLayout()
        m_col.setSpacing(12)
        self._mb_new  = _MenuBar('NEW CHAMPIONSHIP',
                                 'Fresh career from 2026 — resets the championship history')
        self._mb_cont = _MenuBar('CONTINUE', '')
        m_col.addWidget(self._mb_new)
        m_col.addWidget(self._mb_cont)
        m_center.addLayout(m_col, 3)
        m_center.addStretch(1)
        ml.addLayout(m_center)
        ml.addStretch(3)
        self._pages.addWidget(menu_w)

        # ── Page 1: the season calendar itself ────────────────────────────────
        cal_w = QWidget()
        cal_w.setStyleSheet('background: transparent;')
        self._pages.addWidget(cal_w)

        # ── Page 2: nothing at all ────────────────────────────────────────────
        # Career resumes without asking anything (see initializePage), and the
        # jump to the Season Hub is deferred by one event-loop tick — this page
        # is what that tick shows, so neither the menu nor a stale calendar
        # flashes on the way through.
        blank = QWidget()
        blank.setStyleSheet('background: transparent;')
        self._pages.addWidget(blank)
        self._blank_index = self._pages.indexOf(blank)

        root = QVBoxLayout(cal_w)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(0)

        # ── Header row: description + progress (no big red title) ────────────
        hdr_row = QHBoxLayout()
        sub = QLabel('Arrange the running order of the championship rounds')
        sub.setFont(QFont('Segoe UI', 9))
        sub.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        hdr_row.addWidget(sub)
        hdr_row.addStretch(1)
        self._progress = QLabel('')
        self._progress.setFont(QFont('Consolas', 10, QFont.Weight.Bold))
        self._progress.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        hdr_row.addWidget(self._progress)
        root.addLayout(hdr_row)
        root.addSpacing(12)

        div = QFrame()
        div.setFixedHeight(2)
        div.setStyleSheet('background: #1e1e2e; border: none;')
        root.addWidget(div)
        root.addSpacing(16)

        main = QHBoxLayout()
        main.setSpacing(24)

        # ── Left: season length + round slots + action bars ──────────────────
        left = QVBoxLayout()
        left.setSpacing(4)
        caps_row = QHBoxLayout()
        caps_row.addWidget(_caps_label('ROUNDS'))
        caps_row.addStretch(1)
        caps_row.addWidget(_caps_label('SEASON LENGTH'))
        self._len_bar = _RoundsBar(self._rounds)
        caps_row.addSpacing(8)
        caps_row.addWidget(self._len_bar)
        left.addLayout(caps_row)
        left.addSpacing(4)

        self._slots = [_SlotBar(i + 1) for i in range(self._n)]
        for bar in self._slots:
            left.addWidget(bar)

        left.addSpacing(8)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._random = _RandomBar()
        self._start  = _StartBar()
        actions.addWidget(self._random, 1)
        actions.addWidget(self._start, 1)
        left.addLayout(actions)
        left.addStretch(1)
        main.addLayout(left, 5)

        # right half stays empty — the video shows through; the circuit picker
        # opens as a floating panel above a dimmed page (see _open_picker)
        main.addStretch(6)
        root.addLayout(main, 1)

        self._build_picker_panel(wiz)

    # ── Floating circuit picker (dimmed background + list | map panel) ─────────

    def _build_picker_panel(self, wiz):
        # full-page dim layer that pushes the calendar into the background
        self._dim = QWidget(self)
        self._dim.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._dim.setStyleSheet('background: rgba(0, 0, 6, 185);')
        self._dim.hide()

        self._panel = QFrame(self)
        self._panel.setObjectName('pickerPanel')
        self._panel.setStyleSheet(
            '#pickerPanel { background: #0e0e15; border: 1px solid #2a2a3a;'
            ' border-radius: 14px; }')
        self._panel.hide()

        pl = QHBoxLayout(self._panel)
        pl.setContentsMargins(24, 20, 24, 20)
        pl.setSpacing(22)

        # left: header + circuit list
        left = QVBoxLayout()
        left.setSpacing(4)
        self._pick_hdr = _caps_label('SELECT CIRCUIT')
        left.addWidget(self._pick_hdr)
        left.addSpacing(6)
        self._rows = [_PickRow(i, c) for i, (_, c) in enumerate(wiz.circuits_df.iterrows())]
        for row in self._rows:
            left.addWidget(row)
        left.addStretch(1)
        pl.addLayout(left, 8)

        # right: world map + circuit stats (same idiom as the Random Race page)
        right = QVBoxLayout()
        right.setSpacing(8)
        map_frame = QFrame()
        map_frame.setStyleSheet(
            'QFrame { background: #0e0e14; border: 1px solid #1e1e2e; border-radius: 12px; }')
        mf_l = QVBoxLayout(map_frame)
        mf_l.setContentsMargins(5, 5, 5, 5)
        self._map = WorldMapWidget()
        mf_l.addWidget(self._map)
        right.addWidget(map_frame, 1)

        info = QFrame()
        info.setStyleSheet(
            'QFrame { background: rgba(255,255,255,4); border: 1px solid #1e1e2e; border-radius: 12px; }'
            'QLabel { background: transparent; border: none; }')
        info_row = QHBoxLayout(info)
        info_row.setContentsMargins(18, 10, 18, 10)
        info_row.setSpacing(26)
        self._stat_labels = {}
        for key in ('LENGTH', 'CORNERS', 'STRAIGHT'):
            col = QVBoxLayout()
            col.setSpacing(2)
            k_lbl = QLabel(key)
            k_lbl.setFont(QFont('Segoe UI', 7, QFont.Weight.Bold))
            k_lbl.setStyleSheet('color: #ffffff; letter-spacing: 2px;')
            v_lbl = QLabel('—')
            v_lbl.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
            v_lbl.setStyleSheet('color: #ffffff;')
            col.addWidget(k_lbl)
            col.addWidget(v_lbl)
            self._stat_labels[key] = v_lbl
            info_row.addLayout(col)
        info_row.addStretch(1)
        right.addWidget(info)
        pl.addLayout(right, 12)

        # matplotlib repaints are expensive — debounce like the Random Race page
        self._pending_country = None
        self._map_timer = QTimer(self)
        self._map_timer.setSingleShot(True)
        self._map_timer.setInterval(180)
        self._map_timer.timeout.connect(
            lambda: self._pending_country and self._map.highlight(self._pending_country))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_picker()

    def _layout_picker(self):
        self._dim.setGeometry(self.rect())
        self._panel.setGeometry(self.rect().adjusted(42, 26, -42, -26))

    # ── Background: shared video + darkening overlay ──────────────────────────

    def _on_bg_frame(self):
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        # scale against the wizard's full size so the video lines up with the
        # reserved strip below the page — see VideoBackground.paint
        offset = self.mapTo(self._wiz, self.rect().topLeft())
        self._vbg.paint(p, self, full_size=self._wiz.size(), offset=offset)
        p.fillRect(self.rect(), QColor(0, 0, 8, 190))

    def paint_gap_overlay(self, painter, rect):
        """Continue the darkening tint into the strip below the page (see
        _GapFiller) so the video doesn't jump to full brightness there."""
        painter.fillRect(rect, QColor(0, 0, 8, 190))

    # ── Wizard flow ───────────────────────────────────────────────────────────

    def initializePage(self):
        """Entered from Home (championship): show the New / Continue menu.
        Career skips the menu entirely — see _init_career below."""
        self._resume = False
        self._new_career = False
        if getattr(self._wiz, 'skip_calendar_menu', False):
            # A rider was just created in Career — there's obviously no
            # season in progress yet, so the New/Continue choice would be
            # meaningless. Go straight to building the calendar.
            self._wiz.skip_calendar_menu = False
            self._enter_calendar()
            return
        self._save = self._wiz.load_season_save()
        if self._wiz.mode == 'career':
            self._init_career()
            return
        # NEW's wording is fixed now that career never shows this menu — see
        # the _MenuBar built in __init__.
        if self._save and self._save.get('season_complete'):
            self._mb_cont.set_sub(
                f"Start the {self._save['year']} season — set up the calendar")
        elif self._save:
            self._mb_cont.set_sub(
                f"Resume the {self._save['year']} season — "
                f"round {self._save['circuit_index'] + 1} of {self._save['rounds']}")
        else:
            self._mb_cont.set_sub('No season in progress')
        self._menu_focus = 'cont' if self._save else 'new'
        self._update_menu_styles()
        self._close_picker()
        self._pages.setCurrentIndex(0)
        self.completeChanged.emit()

    def _init_career(self):
        """Career has no New/Continue choice: a slot holds exactly one career,
        so loading it can only mean "carry on with it" — there is nothing to
        pick between. Resume the save (an in-progress round, or a finished
        season's calendar setup for the following year, both handled by
        _resume_season), and if the slot has no season save at all — a rider
        created but never taken through calendar setup — build the calendar for
        a first season instead.

        The resume is deferred by a tick: _resume_season ends in wiz.next(),
        which must not run inside the page change that is still initialising
        this page."""
        self._close_picker()
        if not self._save:
            # Same footing as a brand-new rider: back to START_YEAR with no
            # in-memory state left over from another slot's career.
            self._wiz.reset_career_progress()
            self._rounds = self._n
            self._enter_calendar()
            return
        self._pages.setCurrentIndex(self._blank_index)
        self.completeChanged.emit()
        QTimer.singleShot(0, self._auto_resume)

    def _auto_resume(self):
        # Only the page the wizard is actually on may navigate — a tick that
        # lands after the player has left must not drag them forward.
        if self._wiz.currentPage() is self:
            self._resume_season()

    def _update_menu_styles(self):
        self._mb_new.set_state(self._menu_focus == 'new', True)
        self._mb_cont.set_state(self._menu_focus == 'cont', bool(self._save))

    def _start_new_career(self):
        """NEW: back to 2026 — but nothing is wiped yet. The history and any
        old save are only destroyed when the new season actually STARTS, so
        closing the app during calendar setup loses nothing."""
        from app.wizard import START_YEAR
        wiz = self._wiz
        wiz.season_year = START_YEAR
        self._new_career = True
        self._rounds = self._n          # fresh career defaults to a full calendar
        self._enter_calendar()

    def begin_followup_season(self):
        """Called by Standings' Next Season — year already advanced; go
        straight to the calendar, keeping the chosen season length."""
        self._resume = False
        self._new_career = False
        self._enter_calendar()

    def _enter_calendar(self):
        wiz = self._wiz
        wiz.season_df = None
        wiz.round_results = []          # fresh season — clear past results
        wiz.season_complete = False     # setting up a season clears the "finished" summary state
        # A season that was abandoned mid-way (NEW pressed over an in-progress
        # season) or whose finish path left these untouched must not leak its
        # circuit/round-in-progress state into the new season — otherwise
        # SeasonHubPage._build_live_rounds_detail reconstructs a phantom round
        # from the stale wiz.race_results + wiz.circuit and the brand-new
        # season opens with the old season's standings still showing. Mirrors
        # the clearing reset_career_progress/begin_next_season_setup/
        # _mark_season_complete already do for their own callers.
        wiz.circuit_index      = 0
        wiz.session_index      = 0
        wiz.all_race_pts       = []
        wiz.race_pts           = []
        wiz.race_results       = []
        wiz.race_fastest_laps  = []
        wiz.circuit            = None
        wiz.practice_results   = None
        wiz.quali_result       = None
        wiz.grid_all_df        = None
        wiz.weekend_weather    = None
        wiz.gp_recap_dismissed_for = None
        # Every route into a new season funnels through here — the hub's "TO
        # NEXT SEASON" card (via begin_next_season_setup/begin_followup_season)
        # AND CONTINUE picking up a season-complete marker after a restart
        # (_resume_season). The rider's birthday hangs off this call for that
        # reason: it used to sit inside begin_next_season_setup(), so a career
        # advanced via Home -> CONTINUE — which never touches that method —
        # aged the season but never the rider.
        wiz.sync_rider_age()
        self._assign = [None] * self._n
        for bar in self._slots:
            bar.set_circuit(None)
        for row in self._rows:
            row.set_taken(None)
        self._apply_rounds()
        self._close_picker()
        self._pages.setCurrentIndex(1)
        self._set_focus('len')
        self._refresh_progress()
        self.completeChanged.emit()

    def isComplete(self):
        return all(self._assign[i] is not None for i in range(self._rounds))

    def validatePage(self):
        if self._resume:               # state already loaded from the save file
            self._resume = False
            return True
        if not self.isComplete():
            return False
        picks = self._assign[:self._rounds]
        season = self._wiz.circuits_df.iloc[picks].reset_index(drop=True)
        self._wiz.season_df = season
        if self._new_career:
            # the point of no return — only now does NEW wipe the archive
            self._wiz.clear_history()
            self._new_career = False
        # Career's equivalent: a rider created into an occupied slot only
        # replaces its previous occupant here, one step before their Season Hub
        # opens — not back when CREATE was pressed.
        self._wiz.commit_pending_career_rider()
        self._wiz.save_season()        # starting fresh replaces any old save
        return True

    def nextId(self):
        if self._wiz.mode == 'career':
            return self._wiz.ID_SEASON_HUB
        return self._wiz.ID_PRACTICE

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def handle_key(self, key: int) -> bool:
        if self._pages.currentIndex() == self._blank_index:
            return True     # career resume in flight — swallow the tick's keys
        if self._pages.currentIndex() == 0:
            return self._menu_key(key)
        if self._picker_open:
            return self._picker_key(key)
        return self._slots_key(key)

    def _menu_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._menu_focus = 'cont' if self._menu_focus == 'new' else 'new'
            self._update_menu_styles()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self._menu_focus == 'new':
                self._start_new_career()
            elif self._save:                 # CONTINUE — denied when no save
                self._resume_season()
            return True
        return False       # Backspace/Escape fall through -> back to Home

    def _nav_order(self) -> list:
        return ['len'] + list(range(self._rounds)) + ['random', 'start']

    def _slots_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            order = self._nav_order()
            step = -1 if key == Qt.Key.Key_Up else 1
            i = order.index(self._focus) if self._focus in order else 0
            self._set_focus(order[(i + step) % len(order)])
            return True
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            if self._focus == 'len':                       # season length 1.._n
                delta = -1 if key == Qt.Key.Key_Left else 1
                self._set_rounds(self._rounds + delta)
                return True
            if self._focus in ('random', 'start'):         # side-by-side hop
                self._set_focus('random' if self._focus == 'start' else 'start')
                return True
            return False
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self._focus == 'len':
                return True                                # ← → adjust; Enter no-op
            if self._focus == 'random':
                self._randomize()
                return True
            if self._focus == 'start':
                if self.isComplete():
                    self._wiz.next()
                return True                                # deny while incomplete
            self._open_picker()
            return True
        return False       # Backspace/Escape fall through -> wizard.back()

    def _picker_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = -1 if key == Qt.Key.Key_Up else 1
            self._set_pick_focus((self._pick_focus + step) % self._n)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._pick_current()
            return True
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
            self._close_picker()
            return True
        return True    # swallow everything else while the picker is open

    # ── Internal ──────────────────────────────────────────────────────────────

    def _round_of(self) -> dict:
        """circuit index -> round number (1-based) currently owning it."""
        return {ci: r + 1 for r, ci in enumerate(self._assign[:self._rounds])
                if ci is not None}

    def _set_rounds(self, r: int):
        r = max(1, min(self._n, r))
        if r == self._rounds:
            return
        self._rounds = r
        # drop assignments that fell outside the shortened season
        for i in range(r, self._n):
            if self._assign[i] is not None:
                self._assign[i] = None
                self._slots[i].set_circuit(None)
        self._apply_rounds()
        self._refresh_progress()
        self.completeChanged.emit()

    def _apply_rounds(self):
        self._len_bar.set_value(self._rounds)
        for i, bar in enumerate(self._slots):
            bar.setVisible(i < self._rounds)
        self._start.set_state(self.isComplete(), self._focus == 'start')

    def _set_focus(self, token):
        # Only touch the slot bar that lost focus and the one that gained it
        # — restyling all of them on every arrow-key press (up to 13) is what
        # made this screen laggy.
        old = self._focus
        self._focus = token
        if isinstance(old, int) and 0 <= old < len(self._slots):
            self._slots[old].set_focused(False)
        if isinstance(token, int) and 0 <= token < len(self._slots):
            self._slots[token].set_focused(True)
        self._len_bar.set_focused(token == 'len')
        self._random.set_focused(token == 'random')
        self._start.set_state(self.isComplete(), token == 'start')

    def _resume_season(self):
        """Load the saved season into the wizard and jump straight to the
        current round — career: whichever session was up next when the app
        last closed, not always Practice (see the session_index restore
        below); championship/random always resume at Practice."""
        wiz  = self._wiz
        data = self._save or wiz.load_season_save()
        if not data:
            return
        self._new_career = False
        if data.get('season_complete'):
            # Career continues with a fresh calendar for the following year.
            # The marker is deliberately KEPT on disk: if the app closes
            # before START SEASON, Continue must still be offered — starting
            # the season overwrites this file with the real save anyway.
            wiz.season_year = int(data['year'])
            self._rounds = max(1, min(self._n, int(data['rounds'])))
            self._enter_calendar()
            return
        by_name = {str(c['circuit_name']): i
                   for i, (_, c) in enumerate(wiz.circuits_df.iterrows())}
        try:
            picks = [by_name[n] for n in data['calendar']]
        except KeyError:            # circuit renamed/removed -> save unusable
            wiz.clear_season_save()
            self._save = None
            if wiz.mode == 'career':
                # no menu to fall back on in career (see _init_career) — set up
                # a calendar for this year instead of dead-ending on a blank page
                self._enter_calendar()
                return
            self._menu_focus = 'new'
            self._update_menu_styles()
            return
        wiz.season_complete = False   # resuming an in-progress season, not a finished one
        wiz.season_df     = wiz.circuits_df.iloc[picks].reset_index(drop=True)
        wiz.season_year   = int(data['year'])
        wiz.circuit_index = int(data['circuit_index'])
        wiz.all_race_pts  = [pd.DataFrame(r) for r in data['all_race_pts']]
        wiz.round_results = [
            {'circuit': rd['circuit'], 'country': rd['country'],
             'races': [pd.DataFrame(x) for x in rd['races']],
             # .get(): saves written before lap_records was persisted resume
             # as None rather than crashing (their records are unrecoverable).
             'lap_records': rd.get('lap_records')}
            for rd in data['round_results']]

        # In-progress round (career): restore exactly which session is up
        # next and whatever that round has produced so far, so resuming after
        # e.g. Race 1 lands back on Race 2 instead of restarting the weekend
        # at Practice. .get() defaults keep older saves (written before these
        # keys existed) loading fine as a fresh round. See wiz.save_season /
        # SeasonHubPage.initializePage.
        def _df_or_none(records):
            return pd.DataFrame(records) if records else None

        wiz.session_index    = int(data.get('session_index', 0))
        wiz.weekend_weather  = data.get('weekend_weather')
        wiz.practice_results = _df_or_none(data.get('practice_results'))
        quali = data.get('quali_result')
        if quali:
            q1, q2, adv, nq, grid = quali
            wiz.quali_result = (_df_or_none(q1), _df_or_none(q2), list(adv),
                               _df_or_none(nq), _df_or_none(grid))
        else:
            wiz.quali_result = None
        wiz.grid_all_df  = _df_or_none(data.get('grid_all_df'))
        wiz.race_pts     = [pd.DataFrame(r) for r in data.get('race_pts', [])]
        wiz.race_results = [pd.DataFrame(r) for r in data.get('race_results', [])]
        wiz.race_fastest_laps = [tuple(x) for x in data.get('race_fastest_laps', [])]
        # PracticePage/QualifyingPage/RacePage all read wiz.circuit directly
        # (only PracticePage's own initializePage sets it, from a fresh visit)
        # — a mid-round resume that skips straight back to Qualifying/Race
        # needs it set here instead.
        wiz.circuit = (wiz.season_df.iloc[wiz.circuit_index]
                       if wiz.circuit_index < len(wiz.season_df) else None)

        self._rounds = max(1, min(self._n, int(data['rounds'])))
        self._resume = True
        wiz.next()

    def _set_pick_focus(self, idx: int):
        old = self._pick_focus
        self._pick_focus = idx
        if 0 <= old < len(self._rows):
            self._rows[old].set_focused(False)
        self._rows[idx].set_focused(True)
        # stats update instantly; the map follows once the cursor rests
        c = self._wiz.circuits_df.iloc[idx]
        self._stat_labels['LENGTH'].setText(f"{c['lap_length_km']} km")
        self._stat_labels['CORNERS'].setText(str(int(c['corners'])))
        self._stat_labels['STRAIGHT'].setText(f"{int(c['straight_length_m'])} m")
        self._pending_country = str(c['country'])
        self._map_timer.start()

    def _open_picker(self):
        self._picker_open = True
        r = self._focus
        self._pick_hdr.setText(f'ROUND {r + 1:02d}  —  SELECT CIRCUIT')
        taken = self._round_of()
        for ci, row in enumerate(self._rows):
            row.set_taken(taken.get(ci))
        # focus the slot's current circuit, else the first free one
        cur = self._assign[r]
        if cur is not None:
            start = cur
        else:
            start = next((ci for ci in range(self._n) if ci not in taken), 0)
        self._layout_picker()
        self._dim.show()
        self._dim.raise_()
        self._panel.show()
        self._panel.raise_()
        self._set_pick_focus(start)

    def _close_picker(self):
        self._picker_open = False
        self._map_timer.stop()
        self._panel.hide()
        self._dim.hide()

    def _pick_current(self):
        ci = self._pick_focus
        if ci in self._round_of():        # taken (including by this round) -> deny
            return
        r = self._focus
        self._assign[r] = ci
        self._slots[r].set_circuit(self._wiz.circuits_df.iloc[ci])
        self._close_picker()
        self._refresh_progress()
        self.completeChanged.emit()
        # advance to the next empty round; land on START when all are filled
        nxt = next((i for i in range(self._rounds) if self._assign[i] is None), 'start')
        self._set_focus(nxt)

    def _randomize(self):
        """Fill the season with a random draw of distinct circuits
        (overwrites any manual picks — slots can still be edited afterwards)."""
        picks = random.sample(range(self._n), self._rounds)
        self._assign = [None] * self._n
        for r, ci in enumerate(picks):
            self._assign[r] = ci
            self._slots[r].set_circuit(self._wiz.circuits_df.iloc[ci])
        self._refresh_progress()
        self.completeChanged.emit()
        self._set_focus('start')

    def _refresh_progress(self):
        done = sum(1 for a in self._assign[:self._rounds] if a is not None)
        self._progress.setText(f'{done} / {self._rounds}')
        self._progress.setStyleSheet(
            f"color: {'#e02840' if done == self._rounds else '#ffffff'};"
            'background: transparent; border: none;'
        )
