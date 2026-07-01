from pathlib import Path
from PyQt6.QtWidgets import (QWizardPage, QHBoxLayout, QVBoxLayout,
                              QFrame, QLabel, QSizePolicy, QScrollArea,
                              QWidget, QStackedWidget, QPushButton)
from PyQt6.QtGui import (QFont, QPixmap, QPainter, QColor, QPen,
                          QPainterPath, QLinearGradient)
from PyQt6.QtCore import Qt, QRectF, QRect, pyqtSignal

_BG     = Path(__file__).parent.parent.parent / 'images' / 'homepage.jpg'
_BOX_W  = 340
_RADIUS = 14

STATS = [
    ('rider_braking',   'Braking',       '#e02840'),
    ('rider_cornering', 'Cornering',     '#2196F3'),
    ('aggression',      'Aggression',    '#FF5722'),
    ('tyre_management', 'Tyre Mgmt',     '#4CAF50'),
    ('wet_performance', 'Wet Perf.',     '#00BCD4'),
    ('consistency',     'Consistency',   '#9C27B0'),
]


# ── Floating card ─────────────────────────────────────────────────────────────

class _Card(QFrame):
    clicked = pyqtSignal()

    def __init__(self, title: str, subtitle: str, accent_hex: str):
        super().__init__()
        self._accent  = QColor(accent_hex)
        self._hovered = False
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFixedWidth(_BOX_W)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

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

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
        path = QPainterPath()
        path.addRoundedRect(rect, _RADIUS, _RADIUS)
        p.fillPath(path, QColor(8, 8, 18, 230 if self._hovered else 210))
        border = QColor(self._accent)
        border.setAlpha(160 if self._hovered else 90)
        p.setPen(QPen(border, 1.5 if self._hovered else 1.0))
        p.drawPath(path)

    def enterEvent(self, e):
        self._hovered = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovered = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


# ── Stat bar ──────────────────────────────────────────────────────────────────

class _StatBar(QWidget):
    _MIN, _MAX = 70, 99

    def __init__(self, label: str, value: int, color_hex: str):
        super().__init__()
        self._label = label
        self._value = value
        self._color = QColor(color_hex)
        self._fill  = (value - self._MIN) / (self._MAX - self._MIN)
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


# ── Rider list item ───────────────────────────────────────────────────────────

class _RiderItem(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, bike_number: int, name: str, team_color: QColor):
        super().__init__()
        self._name   = name
        self._tc     = team_color
        self._tc_lt  = QColor(
            min(team_color.red()   + 80, 255),
            min(team_color.green() + 80, 255),
            min(team_color.blue()  + 80, 255),
        )
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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
        elif self.underMouse():
            p.fillRect(0, 0, w, h, QColor(14, 14, 26))
        else:
            p.fillRect(0, 0, w, h, QColor(7, 7, 16))
        p.setPen(QPen(QColor(18, 18, 30)))
        p.drawLine(0, h - 1, w, h - 1)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._name)
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
        # setParent(None) detaches immediately (synchronous), unlike deleteLater()
        while self._outer.count():
            item = self._outer.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        cl = self._outer

        # Rider name
        n = QLabel(row['name'].upper())
        n.setFont(QFont('Segoe UI', 26, QFont.Weight.Bold))
        n.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        cl.addWidget(n)
        cl.addSpacing(6)

        # Team / manufacturer
        t = QLabel(f"{row.get('team', '')}  ·  {row.get('manufacturer', '')}")
        t.setFont(QFont('Segoe UI', 10))
        t.setStyleSheet('color: #555566; background: transparent; border: none;')
        cl.addWidget(t)
        cl.addSpacing(30)

        # Info row — wrapped in QWidget so setParent(None) removes all child labels
        info_w = QWidget()
        info_w.setStyleSheet('background: transparent;')
        info_lay = QHBoxLayout(info_w)
        info_lay.setSpacing(32)
        info_lay.setContentsMargins(0, 0, 0, 0)
        for key, val in [('#',    f"#{row.get('bike_number', '?')}"),
                         ('AGE',  str(row.get('age', '?'))),
                         ('FROM', str(row.get('nationality', '?')))]:
            col = QVBoxLayout()
            col.setSpacing(3)
            vl = QLabel(str(val))
            vl.setFont(QFont('Segoe UI', 16, QFont.Weight.Bold))
            vl.setStyleSheet('color: #ffffff; background: transparent; border: none;')
            kl = QLabel(key)
            kl.setFont(QFont('Segoe UI', 7))
            kl.setStyleSheet('color: #333344; letter-spacing: 1px; background: transparent; border: none;')
            col.addWidget(vl)
            col.addWidget(kl)
            info_lay.addLayout(col)
        info_lay.addStretch(1)
        cl.addWidget(info_w)
        cl.addSpacing(38)

        d1 = QFrame(); d1.setFixedHeight(1)
        d1.setStyleSheet('background: #181828; border: none;')
        cl.addWidget(d1)
        cl.addSpacing(28)

        sh = QLabel('RIDER STATS')
        sh.setFont(QFont('Segoe UI', 8))
        sh.setStyleSheet('color: #2d2d44; letter-spacing: 3px; background: transparent; border: none;')
        cl.addWidget(sh)
        cl.addSpacing(18)

        for col_name, label, color in STATS:
            val = int(row.get(col_name, 70))
            cl.addWidget(_StatBar(label, val, color))
            cl.addSpacing(10)

        cl.addSpacing(28)

        d2 = QFrame(); d2.setFixedHeight(1)
        d2.setStyleSheet('background: #181828; border: none;')
        cl.addWidget(d2)
        cl.addSpacing(20)

        avg  = sum(int(row.get(c, 70)) for c, _, _ in STATS) / len(STATS)
        score = (avg - 70) / (99 - 70) * 100
        cl.addWidget(_PowerBar(score))
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

        # ── Left panel ────────────────────────────────────────────────────────
        left_outer = QWidget()
        left_outer.setAutoFillBackground(False)
        left_outer.setStyleSheet('background: transparent;')
        lo = QVBoxLayout(left_outer)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        hf = QFrame()
        hf.setFixedHeight(52)
        hf.setAutoFillBackground(False)
        hf.setStyleSheet('background: transparent; border: none;')
        hl = QHBoxLayout(hf)
        hl.setContentsMargins(20, 0, 20, 0)
        h_lbl = QLabel('RIDERS')
        h_lbl.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        h_lbl.setStyleSheet('color: #e02840; letter-spacing: 2px; background: transparent; border: none;')
        hl.addWidget(h_lbl)
        lo.addWidget(hf)

        hd = QFrame(); hd.setFixedHeight(1)
        hd.setStyleSheet('background: #111122; border: none;')
        lo.addWidget(hd)

        scroll_l = QScrollArea()
        scroll_l.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_l.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_l.setWidgetResizable(True)
        scroll_l.setStyleSheet(
            'QScrollArea { background: transparent; border: none; }'
            'QScrollBar:vertical { background: transparent; width: 4px; border: none; }'
            'QScrollBar::handle:vertical { background: #252538; border-radius: 2px; }'
            'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }'
        )
        scroll_l.setAutoFillBackground(False)
        scroll_l.viewport().setAutoFillBackground(False)
        scroll_l.viewport().setStyleSheet('background: transparent;')

        list_cont = QWidget()
        list_cont.setAutoFillBackground(False)
        list_cont.setStyleSheet('background: transparent;')
        self._list_lay = QVBoxLayout(list_cont)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(0)
        self._list_lay.addStretch(1)

        scroll_l.setWidget(list_cont)
        lo.addWidget(scroll_l, 1)
        root.addWidget(left_outer, 3)

        # ── Divider ───────────────────────────────────────────────────────────
        vd = QFrame(); vd.setFixedWidth(1)
        vd.setStyleSheet('background: #111122; border: none;')
        root.addWidget(vd)

        # ── Right panel ───────────────────────────────────────────────────────
        self._detail = _RiderDetail()

        scroll_r = QScrollArea()
        scroll_r.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_r.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_r.setWidgetResizable(True)
        scroll_r.setStyleSheet(
            'QScrollArea { background: transparent; border: none; }'
            'QScrollBar:vertical { background: transparent; width: 4px; border: none; }'
            'QScrollBar::handle:vertical { background: #252538; border-radius: 2px; }'
            'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }'
        )
        scroll_r.setWidget(self._detail)
        scroll_r.setAutoFillBackground(False)
        scroll_r.viewport().setAutoFillBackground(False)
        scroll_r.viewport().setStyleSheet('background: transparent;')
        root.addWidget(scroll_r, 7)

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

    def _on_select(self, name: str):
        if self._current and self._current in self._items:
            self._items[self._current].set_selected(False)
        self._current = name
        self._items[name].set_selected(True)
        row_s = self._wiz.df[self._wiz.df['name'] == name].iloc[0]
        self._detail.load(row_s.to_dict())

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(5, 5, 14, 218))


# ── Gallery page ──────────────────────────────────────────────────────────────

class GalleryPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz       = wiz
        self._bg_pixmap = QPixmap(str(_BG)) if _BG.exists() else QPixmap()
        self._bg_cache  = QPixmap()
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
        row.addWidget(self._card_riders)
        row.addSpacing(28)
        row.addWidget(self._card_teams)
        row.addStretch(1)
        cw_l.addLayout(row)
        cw_l.addStretch(3)
        self._stack.addWidget(cards_w)   # index 0

        # ── Index 1: riders split view ────────────────────────────────────────
        riders_w = QWidget()
        riders_w.setAutoFillBackground(False)
        riders_w.setStyleSheet('background: transparent;')
        rw_l = QVBoxLayout(riders_w)
        rw_l.setContentsMargins(0, 0, 0, 0)
        rw_l.setSpacing(0)

        top_bar = QFrame()
        top_bar.setFixedHeight(46)
        top_bar.setAutoFillBackground(False)
        top_bar.setStyleSheet('background: transparent; border: none;')
        tb_l = QHBoxLayout(top_bar)
        tb_l.setContentsMargins(16, 0, 0, 0)
        btn_back = QPushButton('← Gallery')
        btn_back.setFont(QFont('Segoe UI', 9))
        btn_back.setStyleSheet(
            'QPushButton { background: transparent; color: #444455; border: none; padding: 4px 8px; }'
            'QPushButton:hover { color: #aaaacc; }'
        )
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        tb_l.addWidget(btn_back)
        tb_l.addStretch(1)
        rw_l.addWidget(top_bar)

        sep = QFrame(); sep.setFixedHeight(1)
        sep.setStyleSheet('background: #0e0e1e; border: none;')
        rw_l.addWidget(sep)

        self._riders_view = _RidersView(wiz)
        rw_l.addWidget(self._riders_view, 1)
        self._stack.addWidget(riders_w)  # index 1

        # ── Page layout ───────────────────────────────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

    def _open_riders(self):
        self._riders_view.populate()
        self._stack.setCurrentIndex(1)

    # ── Background painting ───────────────────────────────────────────────────

    def _rescale(self):
        if self._bg_pixmap.isNull() or self.width() < 2 or self.height() < 2:
            return
        dpr = self.devicePixelRatio()
        self._bg_cache = self._bg_pixmap.scaled(
            int(self.width() * dpr), int(self.height() * dpr),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._bg_cache.setDevicePixelRatio(dpr)
        self.update()

    def resizeEvent(self, event):
        self._rescale()
        super().resizeEvent(event)

    def showEvent(self, event):
        self._rescale()
        super().showEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        if not self._bg_cache.isNull():
            dpr = self.devicePixelRatio()
            x = int((self.width()  - self._bg_cache.width()  / dpr) / 2)
            y = int((self.height() - self._bg_cache.height() / dpr) / 2)
            p.drawPixmap(x, y, self._bg_cache)

    def nextId(self):
        return -1
