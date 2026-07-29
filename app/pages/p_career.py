import pandas as pd
from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout, QGridLayout,
                              QLabel, QFrame, QStackedWidget, QWidget, QLineEdit,
                              QDialog, QScrollArea)
from PyQt6.QtGui import QFont, QColor, QPainter, QPixmap
from PyQt6.QtCore import Qt, QTimer

from app.widgets.video_bg import VideoBackground
from app.pages.p_calendar import _MenuBar, _caps_label
from app.pages.p_home import _BAND_CSS, _SBAR_H, _statusbar_font
from app.pages.p_season_hub import _big_bike_pixmap
from app.wizard import RAW, CAREER_SLOTS
from src.loader import load_bikes
from src.transfers import objective_for, rating, team_table

# Every UN member state (+ a few common non-member entries), text only — no
# flag assets exist for most of these, so the Nationality row is text-only.
_NATIONALITIES = [
    'Afghanistan', 'Albania', 'Algeria', 'Andorra', 'Angola',
    'Antigua and Barbuda', 'Argentina', 'Armenia', 'Australia', 'Austria',
    'Azerbaijan', 'Bahamas', 'Bahrain', 'Bangladesh', 'Barbados', 'Belarus',
    'Belgium', 'Belize', 'Benin', 'Bhutan', 'Bolivia',
    'Bosnia and Herzegovina', 'Botswana', 'Brazil', 'Brunei', 'Bulgaria',
    'Burkina Faso', 'Burundi', 'Cabo Verde', 'Cambodia', 'Cameroon',
    'Canada', 'Central African Republic', 'Chad', 'Chile', 'China',
    'Colombia', 'Comoros', 'Congo (Republic of the)',
    'Congo (Democratic Republic of the)', 'Costa Rica', 'Croatia', 'Cuba',
    'Cyprus', 'Czech Republic', 'Denmark', 'Djibouti', 'Dominica',
    'Dominican Republic', 'Ecuador', 'Egypt', 'El Salvador',
    'Equatorial Guinea', 'Eritrea', 'Estonia', 'Eswatini', 'Ethiopia',
    'Fiji', 'Finland', 'France', 'Gabon', 'Gambia', 'Georgia', 'Germany',
    'Ghana', 'Greece', 'Grenada', 'Guatemala', 'Guinea', 'Guinea-Bissau',
    'Guyana', 'Haiti', 'Honduras', 'Hungary', 'Iceland', 'India',
    'Indonesia', 'Iran', 'Iraq', 'Ireland', 'Israel', 'Italy',
    'Ivory Coast', 'Jamaica', 'Japan', 'Jordan', 'Kazakhstan', 'Kenya',
    'Kiribati', 'Kosovo', 'Kuwait', 'Kyrgyzstan', 'Laos', 'Latvia',
    'Lebanon', 'Lesotho', 'Liberia', 'Libya', 'Liechtenstein', 'Lithuania',
    'Luxembourg', 'Madagascar', 'Malawi', 'Malaysia', 'Maldives', 'Mali',
    'Malta', 'Marshall Islands', 'Mauritania', 'Mauritius', 'Mexico',
    'Micronesia', 'Moldova', 'Monaco', 'Mongolia', 'Montenegro', 'Morocco',
    'Mozambique', 'Myanmar', 'Namibia', 'Nauru', 'Nepal', 'Netherlands',
    'New Zealand', 'Nicaragua', 'Niger', 'Nigeria', 'North Korea',
    'North Macedonia', 'Norway', 'Oman', 'Pakistan', 'Palau', 'Panama',
    'Papua New Guinea', 'Paraguay', 'Peru', 'Philippines', 'Poland',
    'Portugal', 'Qatar', 'Romania', 'Russia', 'Rwanda',
    'Saint Kitts and Nevis', 'Saint Lucia',
    'Saint Vincent and the Grenadines', 'Samoa', 'San Marino',
    'Sao Tome and Principe', 'Saudi Arabia', 'Senegal', 'Serbia',
    'Seychelles', 'Sierra Leone', 'Singapore', 'Slovakia', 'Slovenia',
    'Solomon Islands', 'Somalia', 'South Africa', 'South Korea',
    'South Sudan', 'Spain', 'Sri Lanka', 'Sudan', 'Suriname', 'Sweden',
    'Switzerland', 'Syria', 'Taiwan', 'Tajikistan', 'Tanzania', 'Thailand',
    'Timor-Leste', 'Togo', 'Tonga', 'Trinidad and Tobago', 'Tunisia',
    'Turkey', 'Turkmenistan', 'Tuvalu', 'Uganda', 'Ukraine',
    'United Arab Emirates', 'United Kingdom', 'United States', 'Uruguay',
    'Uzbekistan', 'Vanuatu', 'Vatican City', 'Venezuela', 'Vietnam',
    'Yemen', 'Zambia', 'Zimbabwe',
]

_BAR_SS = """
    QFrame {{
        background: {bg};
        border: 1px solid {border};
        border-radius: 6px;
    }}
    QLabel {{ background: transparent; border: none; }}
"""


# ── Name entry row (the app's one free-text field) ─────────────────────────────

class _NameRow(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(58)
        self._focused = False
        self._editing = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(16)
        self._lbl = QLabel('NAME')
        self._lbl.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        self._lbl.setFixedWidth(170)
        lay.addWidget(self._lbl)

        self._edit = QLineEdit()
        self._edit.setMaxLength(24)
        self._edit.setPlaceholderText('— press Enter to type —')
        self._edit.setFont(QFont('Segoe UI', 14, QFont.Weight.Bold))
        self._edit.setFrame(False)
        self._edit.setReadOnly(True)
        self._edit.textEdited.connect(self._force_upper)
        lay.addWidget(self._edit, 1)
        self._apply()

    def _force_upper(self, text: str):
        pos = self._edit.cursorPosition()
        self._edit.blockSignals(True)
        self._edit.setText(text.upper())
        self._edit.blockSignals(False)
        self._edit.setCursorPosition(pos)

    def line_edit(self) -> QLineEdit:
        return self._edit

    def set_focused(self, f: bool):
        self._focused = f
        self._apply()

    def set_editing(self, e: bool):
        self._editing = e
        self._edit.setReadOnly(not e)
        self._apply()

    def _apply(self):
        if self._editing:
            bg, border, txt = '#33161f', '#e02840', '#ffffff'
        elif self._focused:
            bg, border, txt = 'rgba(224,40,64,35)', '#e02840', '#ffffff'
        else:
            bg, border, txt = 'rgba(255,255,255,4)', '#222233', '#ffffff'
        self.setStyleSheet(_BAR_SS.format(bg=bg, border=border))
        self._lbl.setStyleSheet(f'color: {txt};')
        self._edit.setStyleSheet(f'color: {txt}; background: transparent; border: none;')


# ── Value row (Age, Nationality, Bike Number) ─────────────────────────────────
# No arrows — Enter opens a selection panel (grid for bike number, scrolling
# list for the other two) instead of cycling in place.

class _StepperRow(QFrame):
    def __init__(self, label: str):
        super().__init__()
        self.setFixedHeight(58)
        self._focused = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(16)
        self._lbl = QLabel(label)
        self._lbl.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        self._lbl.setFixedWidth(170)
        lay.addWidget(self._lbl)

        self._val = QLabel('')
        self._val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._val.setFont(QFont('Consolas', 14, QFont.Weight.Bold))
        lay.addWidget(self._val, 1)
        self._apply()

    def set_value(self, text: str):
        self._val.setText(text)

    def set_focused(self, f: bool):
        self._focused = f
        self._apply()

    def _apply(self):
        if self._focused:
            bg, border, txt = 'rgba(224,40,64,35)', '#e02840', '#ffffff'
        else:
            bg, border, txt = 'rgba(255,255,255,4)', '#222233', '#ffffff'
        self.setStyleSheet(_BAR_SS.format(bg=bg, border=border))
        for w in (self._lbl, self._val):
            w.setStyleSheet(f'color: {txt};')


# ── Confirm row ──────────────────────────────────────────────────────────────

class _ConfirmRow(QFrame):
    def __init__(self, text: str):
        super().__init__()
        self.setFixedHeight(58)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 0)
        self._lbl = QLabel(text)
        self._lbl.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._lbl)
        self.set_state(False, False)

    def set_state(self, enabled: bool, focused: bool):
        # Red only once the cursor is actually on this row — no colour hint
        # while just passing through, even once the name becomes valid.
        if focused and enabled:
            bg, border, txt = '#e02840', '#ff6080', '#ffffff'
        elif focused:
            bg, border, txt = 'rgba(255,255,255,8)', '#555566', '#888899'
        else:
            bg, border, txt = 'rgba(255,255,255,3)', '#1a1a26', '#444455'
        self.setStyleSheet(_BAR_SS.format(bg=bg, border=border))
        self._lbl.setStyleSheet(f'color: {txt}; letter-spacing: 2px;')


# ── Carousel arrow (manufacturer page) ───────────────────────────────────────
# Purely a hint that Left/Right does something — the app disables the mouse, so
# these are never clicked, only mirrored by the key that moves the carousel.

class _CarouselArrow(QLabel):
    def __init__(self, glyph: str):
        super().__init__(glyph)
        self.setFixedSize(48, 96)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(QFont('Segoe UI', 34, QFont.Weight.Bold))
        self.set_lit(False)

    def set_lit(self, lit: bool):
        """Briefly brightened as the matching key is pressed, so the carousel
        acknowledges the input even when two bikes look alike."""
        col = '#ffffff' if lit else '#e02840'
        self.setStyleSheet(f'color: {col}; background: transparent; border: none;')


# ── Career slot row (New/Load slot picker) ──────────────────────────────────

class _SlotRow(QFrame):
    def __init__(self, idx: int):
        super().__init__()
        self.setFixedHeight(34)
        self._focused  = False
        self._occupied = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(12)
        self._num = QLabel(f'{idx + 1:02d}')
        self._num.setFont(QFont('Consolas', 9, QFont.Weight.Bold))
        self._num.setFixedWidth(24)
        lay.addWidget(self._num)

        self._name = QLabel('— empty —')
        self._name.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        lay.addWidget(self._name, 1)

        self._detail = QLabel('')
        self._detail.setFont(QFont('Consolas', 9))
        lay.addWidget(self._detail)
        self._apply()

    def set_rider(self, rider: dict | None):
        self._occupied = rider is not None
        if rider is None:
            self._name.setText('— empty —')
            self._detail.setText('')
        else:
            self._name.setText(str(rider['name']))
            self._detail.setText(f"#{rider['bike_number']}  {rider['manufacturer']}")
        self._apply()

    def set_focused(self, f: bool):
        self._focused = f
        self._apply()

    def _apply(self):
        if self._focused:
            bg, border = 'rgba(224,40,64,35)', '#e02840'
            num, name, detail = '#e02840', '#ffffff', '#ffcccc'
        elif self._occupied:
            bg, border = 'rgba(255,255,255,6)', '#2a2a3a'
            num, name, detail = '#ffffff', '#ffffff', '#888899'
        else:
            bg, border = 'rgba(255,255,255,3)', '#1a1a26'
            num, name, detail = '#555566', '#555566', '#444455'
        self.setStyleSheet(_BAR_SS.format(bg=bg, border=border))
        self._num.setStyleSheet(f'color: {num};')
        self._name.setStyleSheet(f'color: {name};')
        self._detail.setStyleSheet(f'color: {detail};')


# ── List-picker row (Age / Nationality selection panel) ───────────────────────

class _ListItemRow(QFrame):
    def __init__(self, text: str):
        super().__init__()
        self.setFixedHeight(34)
        self._focused = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        self._lbl = QLabel(text)
        self._lbl.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        lay.addWidget(self._lbl)
        self._apply()

    def set_focused(self, f: bool):
        self._focused = f
        self._apply()

    def _apply(self):
        if self._focused:
            bg, border, txt = 'rgba(224,40,64,35)', '#e02840', '#ffffff'
        else:
            bg, border, txt = 'rgba(255,255,255,4)', '#222233', '#ffffff'
        self.setStyleSheet(_BAR_SS.format(bg=bg, border=border))
        self._lbl.setStyleSheet(f'color: {txt};')


# ── Page ─────────────────────────────────────────────────────────────────────

# Manufacturer is deliberately NOT here: it gets a screen of its own after
# CONFIRM (page 3), where the satellite bike can actually be shown.
_FORM_ROWS = ['name', 'age', 'nat', 'bike', 'confirm']
_AGE_MIN, _AGE_MAX, _AGE_DEFAULT = 18, 45, 25
# Fixed box for the bike shot so switching manufacturers never shifts the rows
# below it — the cutouts differ in aspect ratio.
_BIKE_BOX_W, _BIKE_BOX_H, _BIKE_H = 440, 250, 230


class CareerPage(QWizardPage):
    """Create-a-rider entry point: New/Load menu, then a rider-creation form.
    Hands off to the existing CalendarPage once a rider is ready."""

    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('')
        self.setSubTitle('')
        self._vbg = VideoBackground.instance()
        self._vbg.frame_ready.connect(self._on_bg_frame)

        self._bikes_df = load_bikes(RAW)
        self._satellite_manus = list(
            self._bikes_df[self._bikes_df.team_status == 'satellite']['manufacturer'])
        self._nationalities = _NATIONALITIES

        # form state
        self._name       = ''
        self._age        = _AGE_DEFAULT
        self._nat_idx    = 0
        self._manu_idx   = 0
        self._bike_number = 1

        self._menu_focus = 'new'     # 'new' | 'load'
        self._form_focus = 0         # index into _FORM_ROWS
        self.text_entry_active = False
        # None | 'bike' (number grid) | 'age' | 'nat' (scrolling list)
        self._active_picker = None
        self._pick_num    = 1
        self._list_field  = None
        self._list_focus  = 0

        # Slot picker (CAREER_SLOTS profiles) — shared by both New and Load
        self._slot_mode  = 'new'     # 'new' | 'load' — what Enter on a slot does
        self._slot_focus = 0
        self._slots_data: list = [None] * CAREER_SLOTS

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._pages = QStackedWidget()
        self._pages.setStyleSheet('background: transparent;')
        root.addWidget(self._pages)

        # ── Page 0: New / Load menu ───────────────────────────────────────────
        menu_w = QWidget()
        menu_w.setStyleSheet('background: transparent;')
        ml = QVBoxLayout(menu_w)
        ml.setContentsMargins(36, 24, 36, 24)
        ml.addStretch(2)
        m_sub = QLabel('Create a rider of your own, or continue their story')
        m_sub.setFont(QFont('Segoe UI', 18))
        m_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        m_sub.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        ml.addWidget(m_sub)
        ml.addSpacing(20)
        m_center = QHBoxLayout()
        m_center.addStretch(1)
        m_col = QVBoxLayout()
        m_col.setSpacing(12)
        self._mb_new  = _MenuBar('NEW CAREER', 'Create a brand-new rider and start their story')
        self._mb_load = _MenuBar('LOAD CAREER', '')
        m_col.addWidget(self._mb_new)
        m_col.addWidget(self._mb_load)
        m_center.addLayout(m_col, 3)
        m_center.addStretch(1)
        ml.addLayout(m_center)
        ml.addStretch(3)
        self._pages.addWidget(menu_w)

        # ── Page 1: slot picker (CAREER_SLOTS profiles) ───────────────────────
        slot_w = QWidget()
        slot_w.setStyleSheet('background: transparent;')
        sl = QVBoxLayout(slot_w)
        sl.setContentsMargins(36, 24, 36, 24)
        sl.addStretch(1)
        self._slot_hdr = _caps_label('SELECT SLOT', size=9)
        sl.addWidget(self._slot_hdr, 0, Qt.AlignmentFlag.AlignHCenter)
        sl.addSpacing(12)
        s_center = QHBoxLayout()
        s_center.addStretch(1)
        s_col = QVBoxLayout()
        s_col.setSpacing(4)
        self._slot_rows = [_SlotRow(i) for i in range(CAREER_SLOTS)]
        for row in self._slot_rows:
            s_col.addWidget(row)
        s_center.addLayout(s_col, 4)
        s_center.addStretch(1)
        sl.addLayout(s_center)
        sl.addStretch(1)
        self._pages.addWidget(slot_w)

        # ── Page 2: rider-creation form ───────────────────────────────────────
        form_w = QWidget()
        form_w.setStyleSheet('background: transparent;')
        fl = QVBoxLayout(form_w)
        fl.setContentsMargins(36, 24, 36, 24)
        fl.addStretch(2)

        f_hdr = _caps_label('BUILD YOUR RIDER', size=12)
        fl.addWidget(f_hdr, 0, Qt.AlignmentFlag.AlignHCenter)
        fl.addSpacing(22)

        f_center = QHBoxLayout()
        f_center.addStretch(1)
        f_col = QVBoxLayout()
        f_col.setSpacing(12)
        self._name_row    = _NameRow()
        self._age_row     = _StepperRow('AGE')
        self._nat_row     = _StepperRow('NATIONALITY')
        self._bike_row    = _StepperRow('BIKE NUMBER')
        self._confirm_row = _ConfirmRow('CONFIRM  →')
        for w in (self._name_row, self._age_row, self._nat_row, self._bike_row):
            f_col.addWidget(w)
        f_col.addSpacing(10)
        f_col.addWidget(self._confirm_row)
        f_center.addLayout(f_col, 5)
        f_center.addStretch(1)
        fl.addLayout(f_center)
        fl.addStretch(3)
        self._pages.addWidget(form_w)

        # ── Page 3: manufacturer picker (satellite-bike carousel) ─────────────
        manu_w = QWidget()
        manu_w.setStyleSheet('background: transparent;')
        gl = QVBoxLayout(manu_w)
        gl.setContentsMargins(36, 24, 36, 24)
        gl.addStretch(2)

        g_hdr = _caps_label('CHOOSE YOUR MANUFACTURER', size=12)
        gl.addWidget(g_hdr, 0, Qt.AlignmentFlag.AlignHCenter)
        gl.addSpacing(6)

        g_sub = QLabel("You'll ride for their satellite team, not the factory squad")
        g_sub.setFont(QFont('Segoe UI', 11))
        g_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        g_sub.setStyleSheet('color: #888899; background: transparent; border: none;')
        gl.addWidget(g_sub)
        gl.addSpacing(14)

        # Arrows sit either side of the bike and are keyboard-only cues (the
        # whole app is arrow-key driven — nothing here is clickable).
        carousel = QHBoxLayout()
        carousel.setSpacing(18)
        carousel.addStretch(1)
        self._manu_prev = _CarouselArrow('‹')
        carousel.addWidget(self._manu_prev, 0, Qt.AlignmentFlag.AlignVCenter)
        self._manu_bike = QLabel()
        self._manu_bike.setFixedSize(_BIKE_BOX_W, _BIKE_BOX_H)
        self._manu_bike.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._manu_bike.setStyleSheet('background: transparent; border: none;')
        carousel.addWidget(self._manu_bike)
        self._manu_next = _CarouselArrow('›')
        carousel.addWidget(self._manu_next, 0, Qt.AlignmentFlag.AlignVCenter)
        carousel.addStretch(1)
        gl.addLayout(carousel)
        gl.addSpacing(10)

        self._manu_name = QLabel()
        self._manu_name.setFont(QFont('Segoe UI', 22, QFont.Weight.Bold))
        self._manu_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._manu_name.setStyleSheet(
            'color: #ffffff; background: transparent; border: none;'
            ' letter-spacing: 3px;')
        gl.addWidget(self._manu_name)

        self._manu_team = QLabel()
        self._manu_team.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        self._manu_team.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._manu_team.setStyleSheet(
            'color: #888899; background: transparent; border: none;')
        gl.addWidget(self._manu_team)
        gl.addSpacing(20)

        g_center = QHBoxLayout()
        g_center.addStretch(1)
        self._manu_confirm = _ConfirmRow('CONFIRM  →')
        self._manu_confirm.setFixedWidth(420)
        g_center.addWidget(self._manu_confirm)
        g_center.addStretch(1)
        gl.addLayout(g_center)
        gl.addStretch(3)
        self._pages.addWidget(manu_w)

        self._build_picker_panel()
        self._build_list_picker()

        # Bottom status bar — same idiom as the homepage's tile subtitle: a
        # slim black strip parented to the wizard, spanning the full width,
        # captioning whichever row/slot/option is currently focused.
        self._toast = QLabel(self._wiz)
        self._toast.setFont(_statusbar_font())
        self._toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._toast.setStyleSheet(f'background: {_BAND_CSS}; color: #ffffff; border: none;')
        self._toast.hide()
        self._wiz.currentIdChanged.connect(self._sync_toast)

    # ── Floating bike-number picker (dimmed background + number grid) ─────────

    def _build_picker_panel(self):
        self._dim = QWidget(self)
        self._dim.setStyleSheet('background: rgba(0, 0, 6, 185);')
        self._dim.hide()

        self._panel = QFrame(self)
        self._panel.setObjectName('numberPanel')
        self._panel.setStyleSheet(
            '#numberPanel { background: #0e0e15; border: 1px solid #2a2a3a;'
            ' border-radius: 14px; }')
        self._panel.hide()

        pl = QVBoxLayout(self._panel)
        pl.setContentsMargins(24, 20, 24, 20)
        pl.setSpacing(10)
        pl.addWidget(_caps_label('SELECT BIKE NUMBER'), 0, Qt.AlignmentFlag.AlignHCenter)
        pl.addSpacing(6)

        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setSpacing(4)
        self._number_tiles = {}
        for n in range(1, 100):
            r, c = divmod(n - 1, 10)
            tile = QLabel(f'{n:02d}')
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile.setFixedSize(34, 28)
            tile.setFont(QFont('Consolas', 9, QFont.Weight.Bold))
            grid.addWidget(tile, r, c)
            self._number_tiles[n] = tile
        pl.addWidget(grid_w, 0, Qt.AlignmentFlag.AlignHCenter)

    # ── Floating list picker (Age / Nationality) ──────────────────────────────

    def _build_list_picker(self):
        self._list_dim = QWidget(self)
        self._list_dim.setStyleSheet('background: rgba(0, 0, 6, 185);')
        self._list_dim.hide()

        self._list_panel = QFrame(self)
        self._list_panel.setObjectName('listPanel')
        self._list_panel.setStyleSheet(
            '#listPanel { background: #0e0e15; border: 1px solid #2a2a3a;'
            ' border-radius: 14px; }')
        self._list_panel.hide()

        lp = QVBoxLayout(self._list_panel)
        lp.setContentsMargins(24, 20, 24, 20)
        lp.setSpacing(10)
        self._list_hdr = _caps_label('SELECT', size=10)
        lp.addWidget(self._list_hdr, 0, Qt.AlignmentFlag.AlignHCenter)
        lp.addSpacing(6)

        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFixedSize(420, 420)
        self._list_scroll.setStyleSheet(
            'QScrollArea { background: transparent; border: none; }')
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lp.addWidget(self._list_scroll)

        # Options per field, built once. Both containers live inside one
        # QStackedWidget that is set on the scroll area exactly once — calling
        # QScrollArea.setWidget() again (e.g. to swap containers per field)
        # deletes whatever widget was set before it, which was crashing the
        # app the second time a previously-shown field's picker reopened.
        self._list_rows = {
            'age':  [_ListItemRow(str(a)) for a in range(_AGE_MIN, _AGE_MAX + 1)],
            'nat':  [_ListItemRow(n.upper()) for n in self._nationalities],
        }
        self._list_stack = QStackedWidget()
        self._list_stack_index = {}
        for key, rows in self._list_rows.items():
            w = QWidget()
            cl = QVBoxLayout(w)
            cl.setContentsMargins(0, 0, 4, 0)
            cl.setSpacing(3)
            for r in rows:
                cl.addWidget(r)
            cl.addStretch(1)
            self._list_stack_index[key] = self._list_stack.addWidget(w)
        self._list_scroll.setWidget(self._list_stack)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._active_picker == 'bike':
            self._layout_picker()
        elif self._active_picker in ('age', 'nat'):
            self._layout_list_picker()
        if self._toast.isVisible():
            self.place_bottom_overlay()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_toast()

    # ── Bottom status bar (wizard-level overlay) ──────────────────────────────

    def place_bottom_overlay(self):
        """Position + raise the status bar. Also called by the wizard after it
        raises the gap filler, so the bar always stays above it."""
        self._toast.setGeometry(0, self._wiz.height() - _SBAR_H,
                                self._wiz.width(), _SBAR_H)
        self._toast.raise_()

    def _sync_toast(self):
        if self._wiz.currentPage() is self:
            self.place_bottom_overlay()
            self._toast.show()
        else:
            self._toast.hide()

    def _update_toast(self):
        if self.text_entry_active:
            self._toast.setText('TYPE THE NAME, THEN PRESS ENTER TO CONFIRM')
            return
        idx = self._pages.currentIndex()
        if idx == 0:
            if self._menu_focus == 'new':
                text = 'CREATE A BRAND-NEW RIDER AND START THEIR STORY'
            else:
                has_any = any(s is not None for s in self._slots_data)
                text = 'CONTINUE AN EXISTING CAREER' if has_any else 'NO CAREERS SAVED YET'
        elif idx == 1:
            text = ('PICK AN EMPTY SLOT, OR OVERWRITE AN EXISTING ONE' if self._slot_mode == 'new'
                    else 'PICK A SLOT TO CONTINUE THAT CAREER')
        elif idx == 3:
            text = ('ENTER TO CONFIRM · ESC TO GO BACK')
        elif self._active_picker == 'bike':
            text = 'USE THE ARROWS TO BROWSE · ENTER TO PICK · ESC TO CANCEL'
        elif self._active_picker in ('age', 'nat'):
            text = 'USE ↑ / ↓ TO BROWSE · ENTER TO SELECT · ESC TO CANCEL'
        else:
            text = {
                'name':    'TYPE A UNIQUE NAME FOR YOUR RIDER',
                'age':     'PRESS ENTER TO CHOOSE YOUR AGE',
                'nat':     'PRESS ENTER TO CHOOSE YOUR NATIONALITY',
                'bike':    'PRESS ENTER TO PICK A FREE NUMBER (1-3 RESERVED FOR A TOP-3 SEASON FINISH)',
                'confirm': 'PRESS ENTER TO GO ON AND PICK YOUR MANUFACTURER',
            }[_FORM_ROWS[self._form_focus]]
        self._toast.setText(text)

    def _layout_picker(self):
        self._dim.setGeometry(self.rect())
        self._panel.adjustSize()
        pw, ph = self._panel.sizeHint().width(), self._panel.sizeHint().height()
        x = (self.width() - pw) // 2
        y = (self.height() - ph) // 2
        self._panel.setGeometry(x, y, pw, ph)

    def _taken_numbers(self):
        # 1-3 are reserved for a season-end top-3 finish (offered separately
        # from the Standings page) — never pickable at creation time.
        base = self._wiz.df.iloc[:self._wiz._base_rider_count]
        return set(int(n) for n in base['bike_number']) | {1, 2, 3}

    def _open_picker(self):
        self._active_picker = 'bike'
        self._pick_num = self._bike_number
        self._refresh_tiles()
        self._layout_picker()
        self._dim.show()
        self._dim.raise_()
        self._panel.show()
        self._panel.raise_()
        self._update_toast()

    def _close_picker(self):
        self._active_picker = None
        self._dim.hide()
        self._panel.hide()
        self._list_dim.hide()
        self._list_panel.hide()

    def _refresh_tiles(self):
        """Full pass — only for opening the picker; Left/Right/Up/Down use
        the cheap _move_pick_num below (see the Nationality-list lag fix:
        restyling all 99 tiles on every keystroke is the same mistake)."""
        taken = self._taken_numbers()
        for n, tile in self._number_tiles.items():
            self._style_tile(tile, n, taken)

    def _style_tile(self, tile, n: int, taken: set):
        is_taken = n in taken
        is_focus = n == self._pick_num
        if is_focus and not is_taken:
            bg, border, fg = '#e02840', '#ff6080', '#ffffff'
        elif is_focus:                       # focused but taken -> Enter denied
            bg, border, fg = 'rgba(224,40,64,12)', '#552030', '#775566'
        elif is_taken:
            bg, border, fg = 'rgba(255,255,255,2)', '#15151f', '#33333f'
        else:
            bg, border, fg = 'rgba(255,255,255,4)', '#222233', '#ffffff'
        tile.setStyleSheet(
            f'background: {bg}; border: 1px solid {border}; border-radius: 4px; color: {fg};')

    def _move_pick_num(self, new_n: int):
        taken = self._taken_numbers()
        old_n, self._pick_num = self._pick_num, new_n
        self._style_tile(self._number_tiles[old_n], old_n, taken)
        self._style_tile(self._number_tiles[new_n], new_n, taken)

    def _picker_key(self, key: int) -> bool:
        K = Qt.Key
        if key in (K.Key_Left, K.Key_Right, K.Key_Up, K.Key_Down):
            r, c = divmod(self._pick_num - 1, 10)
            if key == K.Key_Left:
                c = (c - 1) % 10
            elif key == K.Key_Right:
                c = (c + 1) % 10
            elif key == K.Key_Up:
                r = (r - 1) % 10
            elif key == K.Key_Down:
                r = (r + 1) % 10
            n = min(r * 10 + c + 1, 99)
            self._move_pick_num(n)
            return True
        if key in (K.Key_Return, K.Key_Enter, K.Key_Space):
            if self._pick_num not in self._taken_numbers():
                self._bike_number = self._pick_num
                self._close_picker()
                self._refresh_form()
            return True
        if key in (K.Key_Escape, K.Key_Backspace):
            self._close_picker()
            self._update_toast()
            return True
        return True   # swallow everything else while the picker is open

    # ── List picker (Age / Nationality) ────────────────────────────────────────

    def _open_list_picker(self, field: str, title: str, current_index: int):
        self._active_picker = field
        self._list_field = field
        self._list_focus = current_index
        self._list_hdr.setText(title)
        self._list_stack.setCurrentIndex(self._list_stack_index[field])
        self._refresh_list_rows()
        self._layout_list_picker()
        self._list_dim.show()
        self._list_dim.raise_()
        self._list_panel.show()
        self._list_panel.raise_()
        self._update_toast()

    def _layout_list_picker(self):
        self._list_dim.setGeometry(self.rect())
        self._list_panel.adjustSize()
        pw, ph = self._list_panel.sizeHint().width(), self._list_panel.sizeHint().height()
        x = (self.width() - pw) // 2
        y = (self.height() - ph) // 2
        self._list_panel.setGeometry(x, y, pw, ph)

    def _refresh_list_rows(self):
        """Full pass — only for opening a picker (≤ once per keypress-free
        action), never on Up/Down: restyling all 196 nationality rows on
        every keystroke is what caused the scroll lag."""
        rows = self._list_rows[self._list_field]
        for i, r in enumerate(rows):
            r.set_focused(i == self._list_focus)
        self._list_scroll.ensureWidgetVisible(rows[self._list_focus], 0, 60)

    def _move_list_focus(self, new_index: int):
        """Cheap Up/Down step — touches only the two rows whose focus
        state actually changed instead of re-styling the whole list."""
        rows = self._list_rows[self._list_field]
        rows[self._list_focus].set_focused(False)
        rows[new_index].set_focused(True)
        self._list_focus = new_index
        self._list_scroll.ensureWidgetVisible(rows[self._list_focus], 0, 60)

    def _list_picker_key(self, key: int) -> bool:
        K = Qt.Key
        rows = self._list_rows[self._list_field]
        if key in (K.Key_Up, K.Key_Down):
            d = -1 if key == K.Key_Up else 1
            self._move_list_focus((self._list_focus + d) % len(rows))
            # Scrolling a value list (age/nationality) isn't
            # discrete navigation — no 'navigate' SFX (see wizard.eventFilter).
            self._wiz.suppress_next_sfx = True
            return True
        if key in (K.Key_Return, K.Key_Enter, K.Key_Space):
            self._commit_list_pick()
            return True
        if key in (K.Key_Escape, K.Key_Backspace):
            self._close_picker()
            self._update_toast()
            return True
        return True   # swallow everything else while the picker is open

    def _commit_list_pick(self):
        field, i = self._list_field, self._list_focus
        if field == 'age':
            self._age = _AGE_MIN + i
        elif field == 'nat':
            self._nat_idx = i
        self._close_picker()
        self._refresh_form()

    # ── Manufacturer page (page 3) ────────────────────────────────────────────

    def _satellite_team(self, manu: str) -> str:
        """The satellite team fielding `manu`, read from the pristine CSV grid
        rather than wiz.df — a career loaded earlier in this session may have
        left its own roster in place (wizard.apply_roster_to_df), and
        _confirm_new_rider resets to that same base grid anyway."""
        base = self._wiz._base_df
        row = base[(base.manufacturer == manu) & (base.team_status == 'satellite')]
        return str(row.iloc[0]['team']) if len(row) else ''

    def _open_manu_page(self):
        self._pages.setCurrentIndex(3)
        self._refresh_manu_page()

    def _refresh_manu_page(self):
        manu = self._satellite_manus[self._manu_idx]
        team = self._satellite_team(manu)
        pix = _big_bike_pixmap(team, height=_BIKE_H) if team else None
        self._manu_bike.setPixmap(pix if pix is not None else QPixmap())
        self._manu_name.setText(manu.upper())
        self._manu_team.setText(team.upper())
        self._manu_confirm.set_state(True, True)
        self._update_toast()

    def _step_manu(self, d: int):
        self._manu_idx = (self._manu_idx + d) % len(self._satellite_manus)
        self._refresh_manu_page()
        # Flash the arrow that was pressed, then settle back.
        arrow = self._manu_prev if d < 0 else self._manu_next
        arrow.set_lit(True)
        QTimer.singleShot(110, lambda: arrow.set_lit(False))

    def _manu_key(self, key: int) -> bool:
        K = Qt.Key
        if key in (K.Key_Left, K.Key_Right):
            self._step_manu(-1 if key == K.Key_Left else 1)
            return True
        if key in (K.Key_Return, K.Key_Enter, K.Key_Space):
            self._confirm_new_rider()
            return True
        if key in (K.Key_Escape, K.Key_Backspace):
            self._pages.setCurrentIndex(2)   # back to the four-field form
            self._refresh_form()
            return True
        return True   # swallow everything else on this page

    # ── Background: shared video + darkening overlay ──────────────────────────

    def _on_bg_frame(self):
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        offset = self.mapTo(self._wiz, self.rect().topLeft())
        self._vbg.paint(p, self, full_size=self._wiz.size(), offset=offset)
        p.fillRect(self.rect(), QColor(0, 0, 8, 190))

    def paint_gap_overlay(self, painter, rect):
        painter.fillRect(rect, QColor(0, 0, 8, 190))

    # ── Wizard flow ───────────────────────────────────────────────────────────

    def initializePage(self):
        self._close_picker()
        self._pages.setCurrentIndex(0)
        self._slots_data = self._wiz.list_career_slots()
        n_used = sum(1 for s in self._slots_data if s is not None)
        if n_used:
            self._mb_load.set_sub(f'{n_used} of {CAREER_SLOTS} career slots saved')
        else:
            self._mb_load.set_sub('No careers saved yet')
        self._menu_focus = 'load' if n_used else 'new'
        self._update_menu_styles()
        self.completeChanged.emit()

    def _update_menu_styles(self):
        has_any = any(s is not None for s in self._slots_data)
        self._mb_new.set_state(self._menu_focus == 'new', True)
        self._mb_load.set_state(self._menu_focus == 'load', has_any)
        self._update_toast()

    def isComplete(self):
        return True

    def nextId(self):
        return self._wiz.ID_CALENDAR

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def handle_key(self, key: int) -> bool:
        if self.text_entry_active:
            return self._name_edit_key(key)
        idx = self._pages.currentIndex()
        if idx == 0:
            return self._menu_key(key)
        if idx == 1:
            return self._slot_picker_key(key)
        if idx == 3:
            return self._manu_key(key)
        if self._active_picker == 'bike':
            return self._picker_key(key)
        if self._active_picker in ('age', 'nat'):
            return self._list_picker_key(key)
        return self._form_key(key)

    def _menu_key(self, key: int) -> bool:
        K = Qt.Key
        if key in (K.Key_Up, K.Key_Down):
            self._menu_focus = 'load' if self._menu_focus == 'new' else 'new'
            self._update_menu_styles()
            return True
        if key in (K.Key_Return, K.Key_Enter, K.Key_Space):
            has_any = any(s is not None for s in self._slots_data)
            if self._menu_focus == 'new':
                self._open_slot_picker('new')
            elif has_any:                    # LOAD — denied when no slot is used
                self._open_slot_picker('load')
            return True
        return False       # Backspace/Escape fall through -> back to Home

    # ── Slot picker (New picks/creates a slot; Load picks an occupied one) ─────

    def _open_slot_picker(self, mode: str):
        self._slot_mode = mode
        self._slots_data = self._wiz.list_career_slots()
        if mode == 'new':
            empty = next((i for i, s in enumerate(self._slots_data) if s is None), None)
            self._slot_focus = empty if empty is not None else 0
        else:
            occupied = next((i for i, s in enumerate(self._slots_data) if s is not None), 0)
            self._slot_focus = occupied
        self._pages.setCurrentIndex(1)
        self._refresh_slots()

    def _refresh_slots(self):
        self._slot_hdr.setText(
            'SELECT SLOT TO CREATE INTO' if self._slot_mode == 'new' else 'SELECT SLOT TO LOAD')
        for i, row in enumerate(self._slot_rows):
            row.set_rider(self._slots_data[i])
            row.set_focused(i == self._slot_focus)
        self._update_toast()

    def _move_slot_focus(self, new_index: int):
        self._slot_rows[self._slot_focus].set_focused(False)
        self._slot_rows[new_index].set_focused(True)
        self._slot_focus = new_index
        self._update_toast()

    def _slot_picker_key(self, key: int) -> bool:
        K = Qt.Key
        if key in (K.Key_Up, K.Key_Down):
            d = -1 if key == K.Key_Up else 1
            self._move_slot_focus((self._slot_focus + d) % CAREER_SLOTS)
            return True
        if key in (K.Key_Return, K.Key_Enter, K.Key_Space):
            self._activate_slot(self._slot_focus)
            return True
        if key in (K.Key_Escape, K.Key_Backspace):
            self._pages.setCurrentIndex(0)   # back to the New/Load menu
            self._update_menu_styles()
            return True
        return True   # swallow everything else while the picker is open

    def _activate_slot(self, i: int):
        rider = self._slots_data[i]
        if self._slot_mode == 'load':
            if rider is None:                # empty slot — nothing to load
                return
            self._wiz.career_slot = i
            self._load_selected_rider(rider)
            return
        # 'new' mode: any slot is pickable; an occupied one needs confirming
        if rider is not None:
            from app.pages.p_home import ExitDialog
            dlg = ExitDialog(
                self._wiz,
                message=f"Slot {i + 1} already has {rider['name']}.\nOverwrite this career?",
                confirm_text='Yes, overwrite')
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
        self._wiz.career_slot = i
        self._start_new_rider()

    def _load_selected_rider(self, rider: dict):
        """Load the slot's grid, not the CSV one — a career several seasons in
        has its own transfers, retirements and called-up rookies (see
        wizard.apply_roster_to_df). `rider` is re-read from the slot by that
        call, which also re-appends them as the last row. ensure_roster() covers
        a career started before roster.json existed by snapshotting the CSV
        grid once, so such a slot still loads."""
        wiz = self._wiz
        wiz.apply_roster_to_df(wiz.ensure_roster())
        wiz.next()

    def _name_edit_key(self, key: int) -> bool:
        K = Qt.Key
        if key in (K.Key_Return, K.Key_Enter):
            self._name = self._name_row.line_edit().text().strip()
            self.text_entry_active = False
            self._name_row.set_editing(False)
            self._form_focus = min(self._form_focus + 1, len(_FORM_ROWS) - 1)
            self._refresh_form()
            return True
        if key == K.Key_Escape:
            self.text_entry_active = False
            self._name_row.line_edit().setText(self._name)
            self._name_row.set_editing(False)
            self._refresh_form()
            return True
        return False

    def _form_key(self, key: int) -> bool:
        K = Qt.Key
        if key in (K.Key_Escape, K.Key_Backspace):
            self._pages.setCurrentIndex(1)   # back to the slot picker
            self._refresh_slots()
            return True
        if key in (K.Key_Up, K.Key_Down):
            step = -1 if key == K.Key_Up else 1
            self._form_focus = (self._form_focus + step) % len(_FORM_ROWS)
            self._refresh_focus()
            return True

        row = _FORM_ROWS[self._form_focus]

        if key in (K.Key_Return, K.Key_Enter, K.Key_Space):
            if row == 'name':
                self._begin_name_edit()
                return True
            if row == 'age':
                self._open_list_picker('age', 'SELECT AGE', self._age - _AGE_MIN)
                return True
            if row == 'nat':
                self._open_list_picker('nat', 'SELECT NATIONALITY', self._nat_idx)
                return True
            if row == 'bike':
                self._open_picker()
                return True
            if row == 'confirm':
                if self._is_valid_name():
                    self._open_manu_page()
                return True

        return False        # unhandled key

    # ── Internal ──────────────────────────────────────────────────────────────

    def _begin_name_edit(self):
        self.text_entry_active = True
        self._name_row.set_editing(True)
        edit = self._name_row.line_edit()
        edit.setText(self._name)
        edit.selectAll()
        edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self._update_toast()

    def _is_valid_name(self) -> bool:
        name = self._name.strip()
        if not name:
            return False
        base = self._wiz.df.iloc[:self._wiz._base_rider_count]
        return name.lower() not in {str(n).lower() for n in base['name']}

    def _refresh_focus(self):
        rows = [self._name_row, self._age_row, self._nat_row, self._bike_row]
        for i, r in enumerate(rows):
            r.set_focused(self._form_focus == i)
        self._confirm_row.set_state(
            self._is_valid_name(), self._form_focus == len(_FORM_ROWS) - 1)
        self._update_toast()

    def _refresh_form(self):
        self._name_row.line_edit().setText(self._name)
        self._age_row.set_value(str(self._age))
        nat = self._nationalities[self._nat_idx]
        self._nat_row.set_value(nat.upper())
        self._bike_row.set_value(f'#{self._bike_number}')
        self._refresh_focus()

    def _start_new_rider(self):
        self._name        = ''
        self._age         = _AGE_DEFAULT
        self._nat_idx     = 0
        self._manu_idx    = 0
        taken = self._taken_numbers()
        self._bike_number = next(n for n in range(1, 100) if n not in taken)
        self._form_focus  = 0
        self._pages.setCurrentIndex(2)
        self._refresh_form()
        self.completeChanged.emit()

    def _confirm_new_rider(self):
        wiz  = self._wiz
        manu = self._satellite_manus[self._manu_idx]
        bike = self._bikes_df[(self._bikes_df.manufacturer == manu)
                               & (self._bikes_df.team_status == 'satellite')].iloc[0]

        wiz.reset_roster_to_base()
        team = wiz.df[(wiz.df.manufacturer == manu)
                      & (wiz.df.team_status == 'satellite')].iloc[0]['team']

        rider = {
            'name': self._name.strip(), 'age': int(self._age),
            'nationality': self._nationalities[self._nat_idx],
            'bike_number': int(self._bike_number), 'manufacturer': manu,
            'team': str(team), 'team_status': 'satellite',
            'rider_braking': 65, 'rider_cornering': 65, 'aggression': 65,
            'tyre_management': 65, 'consistency': 65, 'wet_performance': 80,
            'top_speed': int(bike['top_speed']), 'acceleration': int(bike['acceleration']),
            'bike_braking': int(bike['bike_braking']), 'bike_cornering': int(bike['bike_cornering']),
            'stability': int(bike['stability']),
        }

        wiz.reset_career_progress()
        rider['age_year'] = int(wiz.season_year)   # after the reset to START_YEAR

        # A one-year deal, same as every AI rider gets in 2026, so the first
        # off-season is a real shake-up for the player too. The objective comes
        # from where a rider of their calibre should finish on this bike — which
        # for a debutant on a satellite machine is "see the season out", so the
        # first contract asks nothing beyond turning up. It starts biting once
        # they are quick enough for the target to land inside the top 24.
        rider['contract_from']  = int(wiz.season_year)
        rider['contract_until'] = int(wiz.season_year)
        rider['objective'] = objective_for(team_table(RAW), str(team),
                                           rating(rider), 1)
        rider['misses'] = 0
        # Nothing on disk yet: the slot is only claimed — and its previous
        # rider/save/archive dropped — once this rider's first season actually
        # starts, so quitting during calendar setup leaves the old career
        # untouched. See wizard.commit_pending_career_rider.
        wiz.pending_career_rider = rider
        wiz.df = pd.concat([wiz.df, pd.DataFrame([rider])], ignore_index=True)
        wiz.skip_calendar_menu = True   # fresh rider -> straight into the calendar builder
        wiz.next()
