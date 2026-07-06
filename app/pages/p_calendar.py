import random
from pathlib import Path
from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QLabel, QFrame, QStackedWidget, QWidget)
from PyQt6.QtGui import QFont, QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt, QRectF

_IMAGES = Path(__file__).parent.parent.parent / 'images'
# dedicated background wins; falls back to the homepage photo (same as CircuitPage)
_BG = next((p for p in (_IMAGES / 'circuit_bg.jpg', _IMAGES / 'homepage.jpg')
            if p.exists()), None)
_FLAGS = Path(__file__).parent.parent.parent / 'data' / 'flags'

_ISO2 = {
    'Australia': 'au', 'Japan': 'jp', 'Italy': 'it', 'Spain': 'es',
    'Germany': 'de', 'United Kingdom': 'gb', 'Brazil': 'br',
    'Argentina': 'ar', 'Netherlands': 'nl', 'France': 'fr',
    'Portugal': 'pt', 'Thailand': 'th', 'Qatar': 'qa',
}


def _flag_pix(country: str, h: int = 14) -> QPixmap | None:
    p = _FLAGS / f"{_ISO2.get(str(country), '')}.png"
    if not p.exists():
        return None
    return QPixmap(str(p)).scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)


def _caps_label(text: str, size: int = 8, color: str = '#666677') -> QLabel:
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
    def __init__(self, round_no: int):
        super().__init__()
        self.setFixedHeight(32)
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
            num, name, country = '#e02840', '#ffffff', '#cc8899'
        elif self._filled:
            bg, border = 'rgba(255,255,255,6)', '#2a2a3a'
            num, name, country = '#888899', '#eeeeee', '#666677'
        else:
            bg, border = 'rgba(255,255,255,3)', '#1a1a26'
            num, name, country = '#444455', '#444455', '#333344'
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
        self._lbl = QLabel('🎲  RANDOM CALENDAR')
        self._lbl.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._lbl)
        self.set_focused(False)

    def set_focused(self, focused: bool):
        if focused:
            bg, border, txt = 'rgba(255,255,255,16)', '#8888aa', '#ffffff'
        else:
            bg, border, txt = 'rgba(255,255,255,5)', '#2a2a3a', '#aaaabb'
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

        self._country = QLabel(str(circuit['country']).upper())
        self._country.setFont(QFont('Segoe UI', 8))
        lay.addWidget(self._country)

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
                num, name, country, tag = '#553344', '#775566', '#553344', '#884455'
            else:
                bg, border = 'rgba(224,40,64,35)', '#e02840'
                num, name, country, tag = '#e02840', '#ffffff', '#cc8899', '#e02840'
        elif taken:
            bg, border = 'rgba(255,255,255,2)', '#15151f'
            num, name, country, tag = '#33333f', '#3a3a4a', '#2a2a36', '#663344'
        else:
            bg, border = 'rgba(255,255,255,4)', '#222233'
            num, name, country, tag = '#888899', '#dddde8', '#666677', '#666677'
        self.setStyleSheet(_BAR_SS.format(bg=bg, border=border))
        self._num.setStyleSheet(f'color: {num};')
        self._name.setStyleSheet(f'color: {name};')
        self._country.setStyleSheet(f'color: {country}; letter-spacing: 2px;')
        self._tag.setStyleSheet(f'color: {tag};')


# ── Page ──────────────────────────────────────────────────────────────────────

class CalendarPage(QWizardPage):
    """Championship season setup — assign each of the 13 rounds a circuit."""

    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('')
        self.setSubTitle('')
        self._bg_pixmap = QPixmap(str(_BG)) if _BG else QPixmap()

        self._n = len(wiz.circuits_df)
        self._assign: list[int | None] = [None] * self._n
        self._focus       = 0       # 0.._n-1 = slots, _n = RANDOM bar, _n+1 = START bar
        self._picker_open = False
        self._pick_focus  = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        hdr_row = QHBoxLayout()
        hdr = QLabel('SEASON CALENDAR')
        hdr.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        hdr.setStyleSheet('color: #e02840; letter-spacing: 3px; background: transparent; border: none;')
        hdr_row.addWidget(hdr)
        hdr_row.addStretch(1)
        self._progress = QLabel('')
        self._progress.setFont(QFont('Consolas', 10, QFont.Weight.Bold))
        self._progress.setStyleSheet('color: #666677; background: transparent; border: none;')
        hdr_row.addWidget(self._progress)
        root.addLayout(hdr_row)
        root.addSpacing(4)

        sub = QLabel('Arrange the running order of the championship rounds')
        sub.setFont(QFont('Segoe UI', 9))
        sub.setStyleSheet('color: #666677; background: transparent; border: none;')
        root.addWidget(sub)
        root.addSpacing(12)

        div = QFrame()
        div.setFixedHeight(2)
        div.setStyleSheet('background: #1e1e2e; border: none;')
        root.addWidget(div)
        root.addSpacing(16)

        main = QHBoxLayout()
        main.setSpacing(24)

        # ── Left: 13 round slots + start bar ──────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(_caps_label('ROUNDS'))
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

        # ── Right: circuit picker (hint <-> list) ─────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet('background: transparent;')

        # index 0 — hint shown while navigating the slots
        hint_w = QFrame()
        hint_w.setStyleSheet(
            'QFrame { background: rgba(255,255,255,3); border: 1px solid #1a1a26; border-radius: 12px; }'
            'QLabel { background: transparent; border: none; }'
        )
        hint_l = QVBoxLayout(hint_w)
        hint_l.addStretch(1)
        for text, size, color in (
            ('⏎', 26, '#2d2d44'),
            ('ENTER — choose a circuit for the highlighted round', 10, '#555566'),
            ('↑ ↓ — move between rounds', 9, '#444455'),
            ('Each circuit can only be used once', 9, '#444455'),
            ('🎲 RANDOM CALENDAR — shuffle the whole season at once', 9, '#444455'),
        ):
            lbl = QLabel(text)
            lbl.setFont(QFont('Segoe UI', size, QFont.Weight.Bold if size == 10 else QFont.Weight.Normal))
            lbl.setStyleSheet(f'color: {color};')
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint_l.addWidget(lbl)
            hint_l.addSpacing(6)
        hint_l.addStretch(1)
        self._stack.addWidget(hint_w)

        # index 1 — circuit list
        pick_w = QWidget()
        pick_w.setStyleSheet('background: transparent;')
        pick_l = QVBoxLayout(pick_w)
        pick_l.setContentsMargins(0, 0, 0, 0)
        pick_l.setSpacing(4)
        self._pick_hdr = _caps_label('SELECT CIRCUIT')
        pick_l.addWidget(self._pick_hdr)
        pick_l.addSpacing(4)
        self._rows = [_PickRow(i, c) for i, (_, c) in enumerate(wiz.circuits_df.iterrows())]
        for row in self._rows:
            pick_l.addWidget(row)
        pick_l.addStretch(1)
        self._stack.addWidget(pick_w)

        main.addWidget(self._stack, 6)
        root.addLayout(main, 1)

    # ── Background (same idiom as CircuitPage) ────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        if not self._bg_pixmap.isNull():
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            iw, ih = self._bg_pixmap.width(), self._bg_pixmap.height()
            scale = max(self.width() / iw, self.height() / ih)
            w, h = iw * scale, ih * scale
            x, y = (self.width() - w) / 2, (self.height() - h) / 2
            p.drawPixmap(QRectF(x, y, w, h), self._bg_pixmap, QRectF(0, 0, iw, ih))
        p.fillRect(self.rect(), QColor(0, 0, 8, 190))

    # ── Wizard flow ───────────────────────────────────────────────────────────

    def initializePage(self):
        self._wiz.season_df = None
        self._wiz.round_results = []   # fresh season — clear past results
        self._assign = [None] * self._n
        for bar in self._slots:
            bar.set_circuit(None)
        for row in self._rows:
            row.set_taken(None)
        self._picker_open = False
        self._stack.setCurrentIndex(0)
        self._set_focus(0)
        self._refresh_progress()
        self.completeChanged.emit()

    def isComplete(self):
        return all(a is not None for a in self._assign)

    def validatePage(self):
        if not self.isComplete():
            return False
        season = self._wiz.circuits_df.iloc[self._assign].reset_index(drop=True)
        self._wiz.season_df = season
        return True

    def nextId(self):
        return self._wiz.ID_PRACTICE

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def handle_key(self, key: int) -> bool:
        if self._picker_open:
            return self._picker_key(key)
        return self._slots_key(key)

    def _slots_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = -1 if key == Qt.Key.Key_Up else 1
            self._set_focus((self._focus + step) % (self._n + 2))
            return True
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self._focus >= self._n:
            # RANDOM and START sit side by side — hop between them
            self._set_focus(self._n if self._focus == self._n + 1 else self._n + 1)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self._focus == self._n:                    # RANDOM CALENDAR bar
                self._randomize()
                return True
            if self._focus == self._n + 1:                # START bar
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
        return {ci: r + 1 for r, ci in enumerate(self._assign) if ci is not None}

    def _set_focus(self, idx: int):
        self._focus = idx
        for i, bar in enumerate(self._slots):
            bar.set_focused(i == idx)
        self._random.set_focused(idx == self._n)
        self._start.set_state(self.isComplete(), idx == self._n + 1)

    def _set_pick_focus(self, idx: int):
        self._pick_focus = idx
        for i, row in enumerate(self._rows):
            row.set_focused(i == idx)

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
        self._set_pick_focus(start)
        self._stack.setCurrentIndex(1)

    def _close_picker(self):
        self._picker_open = False
        self._stack.setCurrentIndex(0)

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
        nxt = next((i for i in range(self._n) if self._assign[i] is None), self._n + 1)
        self._set_focus(nxt)

    def _randomize(self):
        """Fill every round with a fresh random permutation of the circuits
        (overwrites any manual picks — slots can still be edited afterwards)."""
        order = list(range(self._n))
        random.shuffle(order)
        self._assign = order
        for r, ci in enumerate(order):
            self._slots[r].set_circuit(self._wiz.circuits_df.iloc[ci])
        self._refresh_progress()
        self.completeChanged.emit()
        self._set_focus(self._n + 1)   # jump to START

    def _refresh_progress(self):
        done = sum(1 for a in self._assign if a is not None)
        self._progress.setText(f'{done} / {self._n}')
        self._progress.setStyleSheet(
            f"color: {'#e02840' if done == self._n else '#666677'};"
            'background: transparent; border: none;'
        )
