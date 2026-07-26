from pathlib import Path
from PyQt6.QtWidgets import (QWizardPage, QHBoxLayout, QVBoxLayout,
                              QFrame, QLabel, QSizePolicy, QScrollArea,
                              QWidget, QStackedWidget)
from PyQt6.QtGui import (QFont, QPixmap, QPainter, QColor, QPen,
                          QPainterPath, QLinearGradient)
from PyQt6.QtCore import Qt, QRectF, QRect, pyqtSignal, QTimer

from app.widgets.video_bg import VideoBackground

_BIKES_DIR = Path(__file__).parent.parent.parent / 'images' / 'bikes'
_BOX_W  = 340
_RADIUS = 14

_BIKE_IMAGE: dict[str, str] = {
    'Ducati Factory Racing':   'Ducati_Factory.png',
    'Honda Factory Racing':    'Honda_Factory.png',
    'Yamaha Factory Racing':   'Yamaha_Factory.png',
    'Suzuki Factory Racing':   'Suzuki_Factory.png',
    'Kawasaki Factory Racing': 'Kawasaki_Factory.png',
    'BMW Factory Racing':      'BMW_Factory.png',
    'Triumph Factory Racing':  'Triumph_Factory.png',
    'Razor Racing':            'Ducati_Razor.png',
    'Storm Riders':            'Yamaha_Storm.png',
    'Falcon Racing':           'BMW_Falcon.png',
    'Phoenix Motorsport':      'Triumph_Phoenix.png',
    'Inferno Factory':         'Honda_Inferno.png',
}

# Decoded + scaled bike images, cached: the team detail rebuilds on every
# navigation key, and re-reading/scaling the PNG each time made it lag.
_BIKE_PIX_CACHE: dict[str, 'QPixmap | None'] = {}


def _bike_pixmap(team_name: str):
    if team_name in _BIKE_PIX_CACHE:
        return _BIKE_PIX_CACHE[team_name]
    img_file = _BIKE_IMAGE.get(team_name)
    pix = None
    if img_file:
        raw = QPixmap(str(_BIKES_DIR / img_file))
        if not raw.isNull():
            pix = raw.scaledToHeight(180, Qt.TransformationMode.SmoothTransformation)
    _BIKE_PIX_CACHE[team_name] = pix
    return pix


STATS = [
    ('rider_braking',   'Braking',          '#2196F3'),
    ('rider_cornering', 'Cornering',        '#2196F3'),
    ('aggression',      'Aggression',       '#2196F3'),
    ('tyre_management', 'Tyre Management',  '#2196F3'),
    ('wet_performance', 'Wet Performance',  '#2196F3'),
    ('consistency',     'Consistency',      '#2196F3'),
]

BIKE_STATS = [
    ('top_speed',      'Top Speed',    '#2196F3'),
    ('acceleration',   'Acceleration', '#2196F3'),
    ('bike_braking',   'Braking',      '#2196F3'),
    ('bike_cornering', 'Cornering',    '#2196F3'),
    ('stability',      'Stability',    '#2196F3'),
]


# ── Floating card ─────────────────────────────────────────────────────────────

class _Card(QFrame):
    clicked = pyqtSignal()

    def __init__(self, title: str, subtitle: str, accent_hex: str):
        super().__init__()
        self._accent  = QColor(accent_hex)
        self._focused = False
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFixedWidth(_BOX_W)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        pl = QVBoxLayout(self)
        pl.setContentsMargins(32, 32, 32, 36)
        pl.setSpacing(0)

        line = QFrame()
        line.setFixedSize(28, 3)
        line.setStyleSheet(f'background: {accent_hex}; border: none;')
        pl.addWidget(line)
        pl.addSpacing(18)

        lbl_title = QLabel(title)
        lbl_title.setFont(QFont('Segoe UI', 20, QFont.Weight.Bold))
        lbl_title.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        pl.addWidget(lbl_title)
        pl.addSpacing(10)

        lbl_sub = QLabel(subtitle)
        lbl_sub.setFont(QFont('Segoe UI', 10))
        lbl_sub.setStyleSheet('color: #aaaaaa; background: transparent; border: none;')
        lbl_sub.setWordWrap(True)
        pl.addWidget(lbl_sub)

    def set_focused(self, v: bool):
        self._focused = v
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
        path = QPainterPath()
        path.addRoundedRect(rect, _RADIUS, _RADIUS)
        p.fillPath(path, QColor(8, 8, 18, 230 if self._focused else 210))
        border = QColor(self._accent)
        if self._focused:
            border.setAlpha(220)
            p.setPen(QPen(border, 2.0))
        else:
            border.setAlpha(90)
            p.setPen(QPen(border, 1.0))
        p.drawPath(path)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


# ── Stat bar ──────────────────────────────────────────────────────────────────

class _StatBar(QWidget):
    def __init__(self, label: str, value: int, color_hex: str):
        super().__init__()
        self._label = label
        self._value = value
        self._color = QColor(color_hex)
        self._fill  = value / 100.0
        self.setFixedHeight(22)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        label_w, val_w = 150, 38
        bar_x = label_w
        bar_w = w - label_w - val_w - 8

        p.setFont(QFont('Segoe UI', 9))
        p.setPen(QColor(155, 155, 172))
        p.drawText(QRect(0, 0, label_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._label)

        tr = QRectF(bar_x, h / 2 - 4, bar_w, 8)
        tp = QPainterPath(); tp.addRoundedRect(tr, 4, 4)
        p.fillPath(tp, QColor(22, 22, 38))

        fw = max(8.0, bar_w * self._fill)
        fr = QRectF(bar_x, h / 2 - 4, fw, 8)
        fp = QPainterPath(); fp.addRoundedRect(fr, 4, 4)
        g = QLinearGradient(bar_x, 0, bar_x + fw, 0)
        g.setColorAt(0, self._color.darker(145))
        g.setColorAt(1, self._color)
        p.fillPath(fp, g)

        p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        p.setPen(QColor(218, 218, 232))
        p.drawText(QRect(w - val_w, 0, val_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   str(self._value))


# ── Power bar ─────────────────────────────────────────────────────────────────

class _PowerBar(QWidget):
    def __init__(self, score: float):
        super().__init__()
        self._score = score
        self._fill  = score / 100.0
        self.setFixedHeight(34)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        label_w, val_w = 150, 80
        bar_x = label_w
        bar_w = w - label_w - val_w - 8

        p.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        p.setPen(QColor(200, 200, 218))
        p.drawText(QRect(0, 0, label_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   'POWER RATING')

        tr = QRectF(bar_x, h / 2 - 6, bar_w, 12)
        tp = QPainterPath(); tp.addRoundedRect(tr, 6, 6)
        p.fillPath(tp, QColor(22, 22, 38))

        fw = max(12.0, bar_w * self._fill)
        fr = QRectF(bar_x, h / 2 - 6, fw, 12)
        fp = QPainterPath(); fp.addRoundedRect(fr, 6, 6)
        g = QLinearGradient(bar_x, 0, bar_x + fw, 0)
        g.setColorAt(0.0, QColor('#0f6b22'))
        g.setColorAt(0.5, QColor('#22c044'))
        g.setColorAt(1.0, QColor('#5eff7e'))
        p.fillPath(fp, g)

        p.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        p.setPen(QColor('#3ee860'))
        p.drawText(QRect(w - val_w, 0, val_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f'{self._score:.1f} / 100')


# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_scroll_area() -> QScrollArea:
    sa = QScrollArea()
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sa.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    sa.setWidgetResizable(True)
    sa.setStyleSheet(
        'QScrollArea { background: transparent; border: none; }'
        'QScrollBar:vertical { background: transparent; width: 4px; border: none; }'
        'QScrollBar::handle:vertical { background: #252538; border-radius: 2px; }'
        'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }'
    )
    sa.setAutoFillBackground(False)
    sa.viewport().setAutoFillBackground(False)
    sa.viewport().setStyleSheet('background: transparent;')
    return sa


def _make_left_panel(label: str, accent: str) -> tuple[QWidget, QVBoxLayout, QScrollArea]:
    """Returns (outer_widget, list_layout, scroll_area) for the left 3-column."""
    outer = QWidget()
    outer.setAutoFillBackground(False)
    outer.setStyleSheet('background: transparent;')
    lo = QVBoxLayout(outer)
    lo.setContentsMargins(0, 0, 0, 0)
    lo.setSpacing(0)

    hf = QFrame()
    hf.setFixedHeight(52)
    hf.setAutoFillBackground(False)
    hf.setStyleSheet('background: transparent; border: none;')
    hl = QHBoxLayout(hf)
    hl.setContentsMargins(20, 0, 20, 0)
    h_lbl = QLabel(label)
    h_lbl.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
    h_lbl.setStyleSheet(f'color: {accent}; letter-spacing: 2px; background: transparent; border: none;')
    hl.addWidget(h_lbl)
    lo.addWidget(hf)

    hd = QFrame(); hd.setFixedHeight(1)
    hd.setStyleSheet('background: #111122; border: none;')
    lo.addWidget(hd)

    scroll = _make_scroll_area()
    list_cont = QWidget()
    list_cont.setAutoFillBackground(False)
    list_cont.setStyleSheet('background: transparent;')
    list_lay = QVBoxLayout(list_cont)
    list_lay.setContentsMargins(0, 0, 0, 0)
    list_lay.setSpacing(0)
    list_lay.addStretch(1)

    scroll.setWidget(list_cont)
    lo.addWidget(scroll, 1)
    return outer, list_lay, scroll


def _divider() -> QFrame:
    d = QFrame(); d.setFixedHeight(1)
    d.setStyleSheet('background: #181828; border: none;')
    return d


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont('Segoe UI', 8))
    lbl.setStyleSheet('color: #ffffff; letter-spacing: 3px; background: transparent; border: none;')
    return lbl


# ── Rider list item ───────────────────────────────────────────────────────────

class _RiderItem(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, bike_number: int, name: str, team_color: QColor):
        super().__init__()
        self._name  = name
        self._tc    = team_color
        self._tc_lt = QColor(
            min(team_color.red()   + 80, 255),
            min(team_color.green() + 80, 255),
            min(team_color.blue()  + 80, 255),
        )
        self._selected = False
        self.setFixedHeight(50)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(10)

        self._num_lbl = QLabel(f'#{bike_number}')
        self._num_lbl.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        self._num_lbl.setFixedWidth(42)
        self._num_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._num_lbl.setStyleSheet('background: transparent; border: none; color: #555566;')
        lay.addWidget(self._num_lbl)

        nm = QLabel(name.upper())
        nm.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        nm.setStyleSheet('background: transparent; border: none; color: #aaaabc;')
        lay.addWidget(nm, 1)

    def set_selected(self, v: bool):
        self._selected = v
        col = self._tc_lt.name() if v else '#555566'
        self._num_lbl.setStyleSheet(f'background: transparent; border: none; color: {col};')
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        if self._selected:
            p.fillRect(0, 0, w, h, QColor(20, 20, 36))
            p.fillRect(0, 0, 3, h, self._tc)
        else:
            p.fillRect(0, 0, w, h, QColor(7, 7, 16))
        p.setPen(QPen(QColor(18, 18, 30)))
        p.drawLine(0, h - 1, w, h - 1)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._name)
        super().mousePressEvent(e)


# ── Team list item ────────────────────────────────────────────────────────────

class _TeamItem(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, team_name: str, manufacturer: str, team_color: QColor):
        super().__init__()
        self._team     = team_name
        self._tc       = team_color
        self._selected = False
        self.setFixedHeight(58)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 10, 14, 10)
        lay.setSpacing(4)

        self._name_lbl = QLabel(team_name.upper())
        self._name_lbl.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        self._name_lbl.setStyleSheet('background: transparent; border: none; color: #aaaabc;')
        lay.addWidget(self._name_lbl)

        self._manu_lbl = QLabel(manufacturer)
        self._manu_lbl.setFont(QFont('Segoe UI', 8))
        self._manu_lbl.setStyleSheet('background: transparent; border: none; color: #555566;')
        lay.addWidget(self._manu_lbl)

    def set_selected(self, v: bool):
        self._selected = v
        self._name_lbl.setStyleSheet(
            f'background: transparent; border: none; color: {"#ffffff" if v else "#aaaabc"};'
        )
        self._manu_lbl.setStyleSheet(
            f'background: transparent; border: none; color: {"#888899" if v else "#555566"};'
        )
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        if self._selected:
            p.fillRect(0, 0, w, h, QColor(20, 20, 36))
            p.fillRect(0, 0, 3, h, self._tc)
        else:
            p.fillRect(0, 0, w, h, QColor(7, 7, 16))
        p.setPen(QPen(QColor(18, 18, 30)))
        p.drawLine(0, h - 1, w, h - 1)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._team)
        super().mousePressEvent(e)


# ── Rider detail panel ────────────────────────────────────────────────────────

class _RiderDetail(QWidget):
    def __init__(self):
        super().__init__()
        self.setAutoFillBackground(False)
        self.setStyleSheet('background: transparent;')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(48, 48, 48, 48)
        self._outer.setSpacing(0)

        ph = QLabel('← Select a rider')
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setFont(QFont('Segoe UI', 13))
        ph.setStyleSheet('color: #2d2d44; background: transparent; border: none;')
        self._outer.addStretch(1)
        self._outer.addWidget(ph, 0, Qt.AlignmentFlag.AlignCenter)
        self._outer.addStretch(1)

    def load(self, row: dict):
        while self._outer.count():
            item = self._outer.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        cl = self._outer

        n = QLabel(row['name'].upper())
        n.setFont(QFont('Segoe UI', 26, QFont.Weight.Bold))
        n.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        cl.addWidget(n)
        cl.addSpacing(6)

        t = QLabel(f"{row.get('team', '')}  ·  {row.get('manufacturer', '')}")
        t.setFont(QFont('Segoe UI', 13))
        t.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        cl.addWidget(t)
        cl.addSpacing(30)

        # Info row wrapped in QWidget to allow clean setParent(None) on reload
        info_w = QWidget()
        info_w.setStyleSheet('background: transparent;')
        info_lay = QHBoxLayout(info_w)
        info_lay.setSpacing(32)
        info_lay.setContentsMargins(0, 0, 0, 0)
        for key, val in [('BIKE NUMBER', f"#{row.get('bike_number', '?')}"),
                         ('AGE',         str(row.get('age', '?'))),
                         ('NATIONALITY', str(row.get('nationality', '?')))]:
            col = QVBoxLayout()
            col.setSpacing(3)
            vl = QLabel(str(val))
            vl.setFont(QFont('Segoe UI', 16, QFont.Weight.Bold))
            vl.setStyleSheet('color: #ffffff; background: transparent; border: none;')
            kl = QLabel(key)
            kl.setFont(QFont('Segoe UI', 7))
            kl.setStyleSheet('color: #ffffff; letter-spacing: 1px; background: transparent; border: none;')
            col.addWidget(vl)
            col.addWidget(kl)
            info_lay.addLayout(col)
        info_lay.addStretch(1)
        cl.addWidget(info_w)
        cl.addSpacing(38)

        cl.addWidget(_divider())
        cl.addSpacing(28)
        cl.addWidget(_section_label('RIDER STATS'))
        cl.addSpacing(18)

        for col_name, label, color in STATS:
            cl.addWidget(_StatBar(label, int(row.get(col_name, 0)), color))
            cl.addSpacing(10)

        cl.addSpacing(28)
        cl.addWidget(_divider())
        cl.addSpacing(20)

        score = sum(int(row.get(c, 0)) for c, _, _ in STATS) / len(STATS)
        cl.addWidget(_PowerBar(score))
        cl.addSpacing(40)


# ── Team detail panel ─────────────────────────────────────────────────────────

class _TeamDetail(QWidget):
    def __init__(self):
        super().__init__()
        self.setAutoFillBackground(False)
        self.setStyleSheet('background: transparent;')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(48, 48, 48, 48)
        self._outer.setSpacing(0)

        ph = QLabel('← Select a team')
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setFont(QFont('Segoe UI', 13))
        ph.setStyleSheet('color: #2d2d44; background: transparent; border: none;')
        self._outer.addStretch(1)
        self._outer.addWidget(ph, 0, Qt.AlignmentFlag.AlignCenter)
        self._outer.addStretch(1)

    def load(self, team_name: str, manufacturer: str, team_status: str,
             riders: list, bike_row: dict, team_color: QColor):
        while self._outer.count():
            item = self._outer.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        cl = self._outer
        tc_lt = QColor(
            min(team_color.red()   + 60, 255),
            min(team_color.green() + 60, 255),
            min(team_color.blue()  + 60, 255),
        )

        # ── Header (full width) ───────────────────────────────────────────
        n = QLabel(team_name.upper())
        n.setFont(QFont('Segoe UI', 24, QFont.Weight.Bold))
        n.setStyleSheet(f'color: {tc_lt.name()}; background: transparent; border: none;')
        cl.addWidget(n)
        cl.addSpacing(6)

        status_str = 'Factory Team' if team_status == 'factory' else 'Satellite Team'
        t = QLabel(f"{manufacturer}  ·  {status_str}")
        t.setFont(QFont('Segoe UI', 13))
        t.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        cl.addWidget(t)
        cl.addSpacing(22)
        cl.addWidget(_divider())
        cl.addSpacing(22)

        # ── Two-column body ───────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet('background: transparent;')
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(36)

        # LEFT: bike image + riders
        left = QWidget()
        left.setStyleSheet('background: transparent;')
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)

        pix = _bike_pixmap(team_name)
        if pix is not None:
            img_lbl = QLabel()
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_lbl.setStyleSheet('background: transparent; border: none;')
            img_lbl.setPixmap(pix)
            left_lay.addWidget(img_lbl)
            left_lay.addSpacing(20)

        left_lay.addWidget(_section_label('RIDERS'))
        left_lay.addSpacing(12)
        for r in sorted(riders, key=lambda x: x['bike_number']):
            row_w = QWidget()
            row_w.setStyleSheet('background: transparent;')
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(10)
            num = QLabel(f'#{r["bike_number"]}')
            num.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
            num.setFixedWidth(40)
            num.setStyleSheet(f'color: {tc_lt.name()}; background: transparent; border: none;')
            row_lay.addWidget(num)
            nm = QLabel(r['name'].upper())
            nm.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
            nm.setStyleSheet('color: #ccccdd; background: transparent; border: none;')
            row_lay.addWidget(nm, 1)
            left_lay.addWidget(row_w)
            left_lay.addSpacing(6)
        left_lay.addStretch(1)

        # RIGHT: bike specs + power rating
        right = QWidget()
        right.setStyleSheet('background: transparent;')
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        right_lay.addWidget(_section_label('BIKE SPECS'))
        right_lay.addSpacing(16)
        for col_name, label, color in BIKE_STATS:
            right_lay.addWidget(_StatBar(label, int(bike_row.get(col_name, 0)), color))
            right_lay.addSpacing(10)
        right_lay.addSpacing(22)
        right_lay.addWidget(_divider())
        right_lay.addSpacing(18)
        avg = sum(bike_row.get(c, 0) for c, _, _ in BIKE_STATS) / len(BIKE_STATS)
        right_lay.addWidget(_PowerBar(avg))
        right_lay.addStretch(1)

        body_lay.addWidget(left, 4)
        body_lay.addWidget(right, 6)
        cl.addWidget(body)
        cl.addSpacing(40)


# ── Riders 3:7 view ───────────────────────────────────────────────────────────

class _RidersView(QWidget):
    def __init__(self, wiz):
        super().__init__()
        self._wiz     = wiz
        self._items   = {}
        self._current = None
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left_outer, self._list_lay, self._left_scroll = _make_left_panel('RIDERS', '#e02840')
        root.addWidget(left_outer, 3)

        vd = QFrame(); vd.setFixedWidth(1)
        vd.setStyleSheet('background: #111122; border: none;')
        root.addWidget(vd)

        # Each rider's detail is a page in a stack: built once, then switching is
        # just setCurrentWidget (no rebuild / relayout). The rest are warmed in
        # the background so even held-key scrolling stays smooth.
        self._pages: dict = {}
        self._stack = QStackedWidget()
        self._scroll_r = _make_scroll_area()
        self._scroll_r.setWidget(self._stack)
        root.addWidget(self._scroll_r, 7)

    def populate(self):
        if self._items:
            return
        from app.widgets.table_utils import TEAM_COLOR, MANU_COLOR, _DEFAULT_COLOR
        df = self._wiz.df.sort_values('bike_number').reset_index(drop=True)
        for _, row_s in df.iterrows():
            r = row_s.to_dict()
            tc = TEAM_COLOR.get(r.get('team', '')) or MANU_COLOR.get(r.get('manufacturer', ''), _DEFAULT_COLOR)
            item = _RiderItem(int(r['bike_number']), r['name'], tc)
            item.clicked.connect(self._on_select)
            self._list_lay.insertWidget(self._list_lay.count() - 1, item)
            self._items[r['name']] = item
        if df.shape[0] > 0:
            self._on_select(df.iloc[0]['name'])
            self._warm = QTimer(self)
            self._warm.timeout.connect(self._prewarm_step)
            self._warm.start(30)                    # warm the rest while idle

    def reload(self):
        """Throw the cached list away and rebuild it from the wizard's current
        grid.

        populate() is deliberately one-shot, which is all the Gallery needs —
        it always shows the same CSV roster. The Season Hub reuses this view
        inside a career, where every transfer market moves riders between teams
        and calls rookies up, so there the list has to be able to start over."""
        for item in self._items.values():
            item.setParent(None)
            item.deleteLater()
        for page in self._pages.values():
            self._stack.removeWidget(page)
            page.deleteLater()
        self._items, self._pages, self._current = {}, {}, None
        warm = getattr(self, '_warm', None)
        if warm is not None:
            warm.stop()                 # a half-finished prewarm would refill _pages
        self.populate()

    def _page_for(self, name: str) -> QWidget:
        d = self._pages.get(name)
        if d is None:
            d = _RiderDetail()
            row_s = self._wiz.df[self._wiz.df['name'] == name].iloc[0]
            d.load(row_s.to_dict())
            self._stack.addWidget(d)
            self._pages[name] = d
        return d

    def _prewarm_step(self):
        rest = [n for n in self._items if n not in self._pages]
        if rest:
            self._page_for(rest[0])
        else:
            self._warm.stop()

    def _on_select(self, name: str):
        if self._current and self._current in self._items:
            self._items[self._current].set_selected(False)
        self._current = name
        self._items[name].set_selected(True)
        self._stack.setCurrentWidget(self._page_for(name))
        bar = self._scroll_r.verticalScrollBar()
        if bar is not None:
            bar.setValue(0)          # always resume at the top, not the last scroll offset

    def move_selection(self, forward: bool):
        names = list(self._items.keys())
        if not names:
            return
        idx = names.index(self._current) if self._current in names else -1
        new_name = names[(idx + (1 if forward else -1)) % len(names)]
        self._on_select(new_name)
        self._left_scroll.ensureWidgetVisible(self._items[new_name])

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(5, 5, 14, 218))


# ── Teams 3:7 view ────────────────────────────────────────────────────────────

class _TeamsView(QWidget):
    def __init__(self, wiz):
        super().__init__()
        self._wiz     = wiz
        self._items   = {}
        self._current = None
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left_outer, self._list_lay, self._left_scroll = _make_left_panel('TEAMS', '#318CE7')
        root.addWidget(left_outer, 3)

        vd = QFrame(); vd.setFixedWidth(1)
        vd.setStyleSheet('background: #111122; border: none;')
        root.addWidget(vd)

        # Team details are stack pages, built once (see _RidersView).
        self._pages: dict = {}
        self._stack = QStackedWidget()
        self._scroll_r = _make_scroll_area()
        self._scroll_r.setWidget(self._stack)
        root.addWidget(self._scroll_r, 7)

    def populate(self):
        if self._items:
            return
        from app.widgets.table_utils import TEAM_COLOR, _DEFAULT_COLOR
        df = self._wiz.df
        def _team_sort_key(t):
            row = df[df['team'] == t].iloc[0]
            return (row.get('manufacturer', ''), row.get('team_status', '') != 'factory', t)
        team_names = sorted(df['team'].unique(), key=_team_sort_key)
        for team_name in team_names:
            first_row = df[df['team'] == team_name].iloc[0]
            tc   = TEAM_COLOR.get(team_name, _DEFAULT_COLOR)
            manu = first_row.get('manufacturer', '')
            item = _TeamItem(team_name, manu, tc)
            item.clicked.connect(self._on_select)
            self._list_lay.insertWidget(self._list_lay.count() - 1, item)
            self._items[team_name] = item
        if team_names:
            self._on_select(team_names[0])
            self._warm = QTimer(self)
            self._warm.timeout.connect(self._prewarm_step)
            self._warm.start(30)

    def _page_for(self, team_name: str) -> QWidget:
        d = self._pages.get(team_name)
        if d is None:
            from app.widgets.table_utils import TEAM_COLOR, _DEFAULT_COLOR
            df        = self._wiz.df
            team_df   = df[df['team'] == team_name]
            bike_row  = team_df.iloc[0].to_dict()
            stat_cols = [c for c, _, _ in STATS]
            riders    = team_df[['name', 'bike_number'] + stat_cols].to_dict('records')
            tc        = TEAM_COLOR.get(team_name, _DEFAULT_COLOR)
            d = _TeamDetail()
            d.load(team_name=team_name, manufacturer=bike_row.get('manufacturer', ''),
                   team_status=bike_row.get('team_status', ''), riders=riders,
                   bike_row=bike_row, team_color=tc)
            self._stack.addWidget(d)
            self._pages[team_name] = d
        return d

    def _prewarm_step(self):
        rest = [t for t in self._items if t not in self._pages]
        if rest:
            self._page_for(rest[0])
        else:
            self._warm.stop()

    def _on_select(self, team_name: str):
        if self._current and self._current in self._items:
            self._items[self._current].set_selected(False)
        self._current = team_name
        self._items[team_name].set_selected(True)
        self._stack.setCurrentWidget(self._page_for(team_name))
        bar = self._scroll_r.verticalScrollBar()
        if bar is not None:
            bar.setValue(0)          # always resume at the top, not the last scroll offset

    def move_selection(self, forward: bool):
        teams = list(self._items.keys())
        if not teams:
            return
        idx = teams.index(self._current) if self._current in teams else -1
        new_team = teams[(idx + (1 if forward else -1)) % len(teams)]
        self._on_select(new_team)
        self._left_scroll.ensureWidgetVisible(self._items[new_team])

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(5, 5, 14, 218))


# ── Gallery page ──────────────────────────────────────────────────────────────



class GalleryPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self._vbg = VideoBackground.instance()
        self._vbg.frame_ready.connect(self._on_bg_frame)
        self.setTitle('')
        self.setSubTitle('')

        self._stack = QStackedWidget(self)
        self._stack.setAutoFillBackground(False)
        self._stack.setStyleSheet('background: transparent;')

        # ── Index 0: card selection ───────────────────────────────────────────
        cards_w = QWidget()
        cards_w.setAutoFillBackground(False)
        cards_w.setStyleSheet('background: transparent;')
        cw_l = QVBoxLayout(cards_w)
        cw_l.setContentsMargins(0, 0, 0, 0)
        cw_l.addStretch(2)
        row = QHBoxLayout()
        row.addStretch(1)
        self._card_riders = _Card('RIDERS', 'All 24 riders competing in the\n2026 World Championship', '#e02840')
        self._card_teams  = _Card('TEAMS',  '12 constructor teams from 7 manufacturers\nentering the 2026 season', '#318CE7')
        self._card_riders.clicked.connect(self._open_riders)
        self._card_teams.clicked.connect(self._open_teams)
        row.addWidget(self._card_riders)
        row.addSpacing(28)
        row.addWidget(self._card_teams)
        row.addStretch(1)
        cw_l.addLayout(row)
        cw_l.addStretch(3)
        self._stack.addWidget(cards_w)                       # index 0

        # ── Index 1: riders split view ────────────────────────────────────────
        self._riders_view = _RidersView(wiz)
        self._stack.addWidget(self._riders_view)             # index 1

        # ── Index 2: teams split view ─────────────────────────────────────────
        self._teams_view = _TeamsView(wiz)
        self._stack.addWidget(self._teams_view)              # index 2

        self._card_focus = 0  # 0 = Riders, 1 = Teams

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

    def initializePage(self):
        self._stack.setCurrentIndex(0)
        self._card_focus = 0
        self._card_riders.set_focused(True)
        self._card_teams.set_focused(False)
        super().initializePage()

    def handle_key(self, key: int) -> bool:
        idx = self._stack.currentIndex()
        if idx == 0:
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                self._card_focus = 1 - self._card_focus
                self._card_riders.set_focused(self._card_focus == 0)
                self._card_teams.set_focused(self._card_focus == 1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                (self._open_riders if self._card_focus == 0 else self._open_teams)()
                return True
        elif idx in (1, 2):
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                view = self._riders_view if idx == 1 else self._teams_view
                view.move_selection(key == Qt.Key.Key_Down)
                return True
            if key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
                self._stack.setCurrentIndex(0)
                return True
            return True  # consume all other keys to prevent falling through
        return False

    def _open_riders(self):
        self._riders_view.populate()
        self._stack.setCurrentIndex(1)

    def _open_teams(self):
        self._teams_view.populate()
        self._stack.setCurrentIndex(2)

    # ── Background painting ───────────────────────────────────────────────────

    def _on_bg_frame(self):
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        # See HomePage.paintEvent — scale against the wizard's full size so
        # the video lines up with the strip QWizard reserves below the page.
        offset = self.mapTo(self._wiz, self.rect().topLeft())
        self._vbg.paint(p, self, full_size=self._wiz.size(), offset=offset)

    def paint_gap_overlay(self, painter, rect):
        """The Riders/Teams views darken the video with this tint; apply the
        same to the strip QWizard reserves below the page (drawn by _GapFiller)
        so the bottom edge isn't left brighter than the rest."""
        painter.fillRect(rect, QColor(5, 5, 14, 218))

    def nextId(self):
        return -1
