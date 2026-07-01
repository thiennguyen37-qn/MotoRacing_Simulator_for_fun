from PyQt6.QtWidgets import (QTableWidget, QTableWidgetItem,
                              QStyledItemDelegate, QHeaderView)
from PyQt6.QtGui import QColor, QFont, QBrush, QPen
from PyQt6.QtCore import Qt, QRect, QSize

# ── Team brand colours ────────────────────────────────────────────────────────
TEAM_COLOR: dict[str, QColor] = {
    'Ducati Factory Racing':   QColor('#B31B1B'),
    'Honda Factory Racing':    QColor('#FF0800'),
    'Yamaha Factory Racing':   QColor('#003262'),
    'Suzuki Factory Racing':   QColor('#318CE7'),
    'Kawasaki Factory Racing': QColor(28, 110, 5),
    'BMW Factory Racing':      QColor('#E6E6E6'),
    'Triumph Factory Racing':  QColor('#282828'),
    'Razor Racing':            QColor('#FFBA00'),
    'Falcon Racing':           QColor('#16166B'),
    'Storm Riders':            QColor('#7B2FBE'),
    'Phoenix Motorsport':      QColor('#FFFF00'),
    'Inferno Factory':         QColor('#80FF00'),
}

# ── Manufacturer brand colours — mirrors each factory team's colour ───────────
MANU_COLOR: dict[str, QColor] = {
    'Honda':    QColor('#FF0800'),
    'Ducati':   QColor('#B31B1B'),
    'Yamaha':   QColor('#003262'),
    'Kawasaki': QColor(28, 110, 5),
    'Suzuki':   QColor('#318CE7'),
    'BMW':      QColor('#E6E6E6'),
    'Triumph':  QColor('#282828'),
}
_DEFAULT_COLOR = QColor(38, 38, 58)
_BG = (12, 12, 18)  # #0c0c12


def row_bg(color: QColor) -> QColor:
    """Dark manufacturer-tinted row background — 40 % manufacturer + 60 % base."""
    r = int(_BG[0] * 0.60 + color.red()   * 0.40)
    g = int(_BG[1] * 0.60 + color.green() * 0.40)
    b = int(_BG[2] * 0.60 + color.blue()  * 0.40)
    return QColor(max(r, 16), max(g, 16), max(b, 20))


def _is_time(s: str) -> bool:
    return ':' in s or s.startswith('+') or s in ('—', '---', '–')


# ── Custom delegate ───────────────────────────────────────────────────────────
class _BgDelegate(QStyledItemDelegate):
    """
    Bypasses Qt-stylesheet item-background override.
    Draws a coloured accent bar on the left edge of column 0
    (accent colour stored in Qt.ItemDataRole.UserRole on that item).
    """
    _DIVIDER = QColor(9, 9, 15)
    _PAD     = 12
    _BAR_W   = 5

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        return QSize(hint.width() + self._PAD * 2, hint.height())

    def paint(self, painter, option, index):
        # Background
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        painter.fillRect(option.rect, bg if bg is not None else QBrush(QColor(*_BG)))

        # Left accent bar (column 0 only)
        if index.column() == 0:
            accent = index.data(Qt.ItemDataRole.UserRole)
            if accent is not None:
                bar = QRect(option.rect.left(), option.rect.top(),
                            self._BAR_W, option.rect.height())
                painter.fillRect(bar, accent)

        # Bottom divider
        painter.save()
        painter.setPen(QPen(self._DIVIDER))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()

        # Text
        txt = index.data(Qt.ItemDataRole.DisplayRole)
        if not txt:
            return

        fg      = index.data(Qt.ItemDataRole.ForegroundRole)
        font    = index.data(Qt.ItemDataRole.FontRole)
        align_v = index.data(Qt.ItemDataRole.TextAlignmentRole)
        align   = (Qt.AlignmentFlag(int(align_v)) if align_v is not None
                   else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        left_pad = self._BAR_W + 6 if index.column() == 0 else self._PAD

        painter.save()
        if font:
            painter.setFont(font)
        if fg is not None:
            painter.setPen(QPen(fg.color() if isinstance(fg, QBrush) else fg))
        painter.drawText(
            option.rect.adjusted(left_pad, 0, -self._PAD, 0),
            int(align),
            str(txt),
        )
        painter.restore()


_TABLE_SS = """
    QTableWidget {
        background: #0c0c12;
        border: none;
        outline: none;
    }
    QHeaderView::section {
        background: #0c0c12;
        color: #444455;
        border: none;
        border-bottom: 1px solid #1c1c2c;
        padding: 8px 12px;
        font-family: 'Segoe UI';
        font-size: 9px;
        letter-spacing: 2px;
        text-transform: uppercase;
    }
    QScrollBar:vertical {
        background: #0c0c12;
        width: 6px;
        border: none;
    }
    QScrollBar::handle:vertical {
        background: #2a2a40;
        border-radius: 3px;
        min-height: 20px;
    }
"""


def make_table(headers: list[str]) -> QTableWidget:
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    t.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    t.setAlternatingRowColors(False)
    t.verticalHeader().setVisible(False)
    t.setFont(QFont('Segoe UI', 11))
    t.setShowGrid(False)
    t.verticalHeader().setDefaultSectionSize(42)
    t.horizontalHeader().setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    t.setItemDelegate(_BgDelegate(t))
    t.setStyleSheet(_TABLE_SS)
    return t


def fill_table(
    table: QTableWidget,
    rows: list[list],
    team_col_idx: int | None = 3,   # team name column → TEAM_COLOR lookup
    manu_col_idx: int | None = 4,   # manufacturer column → fallback MANU_COLOR
    num_col_idx:  int | None = 1,
    name_col_idx: int | None = 2,   # rider/entity name → BOLD + UPPERCASE
    stretch_col:  int | None = 3,   # column that expands to fill remaining width
):
    table.setRowCount(len(rows))

    for r, row_data in enumerate(rows):
        color = None
        if team_col_idx is not None and team_col_idx < len(row_data):
            color = TEAM_COLOR.get(str(row_data[team_col_idx]))
        if color is None:
            manu  = str(row_data[manu_col_idx]) if (manu_col_idx is not None and manu_col_idx < len(row_data)) else ''
            color = MANU_COLOR.get(manu, _DEFAULT_COLOR)

        bg      = row_bg(color)
        lighter = QColor(
            min(color.red()   + 80, 255),
            min(color.green() + 80, 255),
            min(color.blue()  + 80, 255),
        )

        for c, val in enumerate(row_data):
            txt  = str(val)
            item = QTableWidgetItem(txt.upper() if (name_col_idx is not None and c == name_col_idx) else txt)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setBackground(QBrush(bg))

            if c == 0:
                item.setData(Qt.ItemDataRole.UserRole, color)
                item.setForeground(QBrush(QColor(220, 220, 235)))
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                item.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))

            elif num_col_idx is not None and c == num_col_idx:
                item.setForeground(QBrush(lighter))
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                item.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))

            elif name_col_idx is not None and c == name_col_idx:
                item.setForeground(QBrush(QColor(235, 235, 248)))
                item.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))

            elif _is_time(txt):
                item.setForeground(QBrush(QColor(210, 210, 228)))
                item.setFont(QFont('Consolas', 10))

            else:
                item.setForeground(QBrush(QColor(160, 160, 180)))
                item.setFont(QFont('Segoe UI', 10))

            table.setItem(r, c, item)

    table.resizeColumnsToContents()
    table.setColumnWidth(0, 56)
    if num_col_idx is not None:
        table.setColumnWidth(num_col_idx, 56)

    hdr = table.horizontalHeader()
    hdr.setStretchLastSection(False)
    if stretch_col is not None and stretch_col < table.columnCount():
        hdr.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
