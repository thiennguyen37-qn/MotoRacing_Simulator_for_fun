from pathlib import Path
from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QLabel, QFrame, QListWidget, QListWidgetItem,
                              QSizePolicy, QWidget)
from PyQt6.QtGui import QFont, QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt, QSize, QRectF, QTimer

from app.widgets.world_map import WorldMapWidget

_IMAGES = Path(__file__).parent.parent.parent / 'images'
# dedicated background wins; falls back to the homepage photo
_BG = next((p for p in (_IMAGES / 'circuit_bg.jpg', _IMAGES / 'homepage.jpg')
            if p.exists()), None)


def _caps_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
    lbl.setStyleSheet('color: #666677; letter-spacing: 3px; background: transparent; border: none;')
    return lbl


class CircuitPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('')
        self.setSubTitle('')
        self._bg_pixmap = QPixmap(str(_BG)) if _BG else QPixmap()

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 28, 36, 28)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QLabel('SELECT CIRCUIT')
        hdr.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        hdr.setStyleSheet('color: #e02840; letter-spacing: 3px; background: transparent; border: none;')
        root.addWidget(hdr)
        root.addSpacing(4)

        sub = QLabel('Choose the circuit for this race weekend')
        sub.setFont(QFont('Segoe UI', 9))
        sub.setStyleSheet('color: #666677; background: transparent; border: none;')
        root.addWidget(sub)
        root.addSpacing(12)

        div = QFrame()
        div.setFixedHeight(2)
        div.setStyleSheet('background: #1e1e2e; border: none;')
        root.addWidget(div)
        root.addSpacing(20)

        main = QHBoxLayout()
        main.setSpacing(20)

        # ── Left: circuit list ────────────────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(_caps_label('CIRCUITS'))

        self._list = QListWidget()
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setStyleSheet("""
            QListWidget {
                background: rgba(255,255,255,4);
                border: 1px solid #1e1e2e;
                border-radius: 12px;
                outline: none;
                padding: 6px;
            }
            QListWidget::item {
                border-radius: 8px;
                margin: 2px 4px;
                border: 1px solid transparent;
            }
            QListWidget::item:selected {
                background: rgba(224,40,64,40);
                border: 1px solid #e02840;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 4px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: #2a2a40;
                border-radius: 2px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        for i, (_, c) in enumerate(wiz.circuits_df.iterrows()):
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 54))
            self._list.addItem(item)

            row_w = QWidget()
            row_w.setStyleSheet('background: transparent;')
            rl = QHBoxLayout(row_w)
            rl.setContentsMargins(14, 0, 12, 0)
            rl.setSpacing(14)

            num = QLabel(f'{i + 1:02d}')
            num.setFont(QFont('Consolas', 10))
            num.setStyleSheet('color: #ffffff; background: transparent; border: none;')
            num.setFixedWidth(22)
            rl.addWidget(num)

            texts = QVBoxLayout()
            texts.setSpacing(1)
            name = QLabel(c['circuit_name'])
            name.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
            name.setStyleSheet('color: #eeeeee; background: transparent; border: none;')
            texts.addWidget(name)
            country = QLabel(str(c['country']).upper())
            country.setFont(QFont('Segoe UI', 8))
            country.setStyleSheet('color: #aaaabb; letter-spacing: 2px; background: transparent; border: none;')
            texts.addWidget(country)
            rl.addLayout(texts, 1)

            self._list.setItemWidget(item, row_w)

        self._list.currentRowChanged.connect(self._on_select)
        left.addWidget(self._list)
        main.addLayout(left, 1)

        # ── Right: world map + stats ──────────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(8)

        map_frame = QFrame()
        map_frame.setStyleSheet(
            'QFrame { background: #0e0e14; border: 1px solid #1e1e2e; border-radius: 12px; }')
        mf_l = QVBoxLayout(map_frame)
        mf_l.setContentsMargins(10, 10, 10, 10)
        self._map = WorldMapWidget()
        self._map.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        mf_l.addWidget(self._map)
        right.addWidget(map_frame, 1)

        # Circuit info bar below map — Ignored width so long circuit/country
        # names can't push the layout (map) wider
        info_frame = QFrame()
        info_frame.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        info_frame.setStyleSheet(
            'QFrame { background: rgba(255,255,255,4); border: 1px solid #1e1e2e; border-radius: 12px; }'
            'QLabel { background: transparent; border: none; }'
        )
        info_row = QHBoxLayout(info_frame)
        info_row.setContentsMargins(22, 14, 22, 14)
        info_row.setSpacing(36)

        self._stat_labels = {}
        for key in ['Circuit', 'Country', 'Length', 'Corners', 'Straight']:
            col = QVBoxLayout()
            col.setSpacing(3)
            k_lbl = QLabel(key.upper())
            k_lbl.setFont(QFont('Segoe UI', 7, QFont.Weight.Bold))
            k_lbl.setStyleSheet('color: #666677; letter-spacing: 2px;')
            v_lbl = QLabel('—')
            v_lbl.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
            v_lbl.setStyleSheet('color: #ffffff;')
            col.addWidget(k_lbl)
            col.addWidget(v_lbl)
            self._stat_labels[key] = v_lbl
            info_row.addLayout(col)

        info_row.addStretch()
        right.addWidget(info_frame)

        main.addLayout(right, 2)
        root.addLayout(main, 1)

        # Debounce map redraws: matplotlib repaint is expensive, so while the
        # user scrolls quickly only the stats update; the map follows once the
        # selection rests for a moment.
        self._pending_country = None
        self._map_timer = QTimer(self)
        self._map_timer.setSingleShot(True)
        self._map_timer.setInterval(180)
        self._map_timer.timeout.connect(self._update_map)

        # Select first item
        self._list.setCurrentRow(0)

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

    def _update_map(self):
        if self._pending_country:
            self._map.highlight(self._pending_country)

    def _on_select(self, idx):
        if idx < 0:
            return
        c = self._wiz.circuits_df.iloc[idx]

        # Map redraw is deferred (see _map_timer)
        self._pending_country = c['country']
        self._map_timer.start()

        # Update stat bar
        self._stat_labels['Circuit'].setText(c['circuit_name'])
        self._stat_labels['Country'].setText(c['country'])
        self._stat_labels['Length'].setText(f"{c['lap_length_km']} km")
        self._stat_labels['Corners'].setText(str(int(c['corners'])))
        self._stat_labels['Straight'].setText(f"{int(c['straight_length_m'])} m")

    def validatePage(self):
        idx = self._list.currentRow()
        self._wiz.circuit       = self._wiz.circuits_df.iloc[idx]
        self._wiz.circuit_index = idx
        self._wiz.practice_results = None
        self._wiz.grid_all_df      = None
        self._wiz.race_pts         = []
        return True

    def nextId(self):
        return self._wiz.ID_PRACTICE
