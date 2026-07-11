from pathlib import Path
import io
import urllib.request
import warnings

import numpy as np
from shapely.ops import unary_union
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
import matplotlib.image as mpimg

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt, QThread, pyqtSignal

_GEOJSON  = Path(__file__).parent.parent.parent / 'data' / 'world_countries.geojson'
_FLAG_DIR = Path(__file__).parent.parent.parent / 'data' / 'flags'
_FLAG_CDN = 'https://flagcdn.com/w320/{code}.png'

BG        = '#0a0a0f'
OCEAN     = '#0d1117'
LAND      = '#1c1c28'
BORDER    = '#3a3a52'
HIGHLIGHT = '#e02840'

_SKIP_TYPES = {'Dependency', 'Disputed', 'Indeterminate', 'Sovereignty'}

# EPSG:3857 (Web Mercator) world extents in metres.
# x: full ±180° longitude.  y: ±72.7° lat — fills a 1.667:1 canvas exactly.
_WX = (-20_037_508, 20_037_508)
_WY = (-12_000_000, 12_000_000)

_flag_cache: dict[str, np.ndarray | None] = {}


# ── helpers ───────────────────────────────────────────────────────────────────

def _shapely_to_mpl_path(geom) -> MplPath:
    verts, codes = [], []

    def _ring(coords):
        c = list(coords)
        verts.extend(c)
        codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(c) - 2) + [MplPath.CLOSEPOLY])

    if geom.geom_type == 'Polygon':
        _ring(geom.exterior.coords)
        for i in geom.interiors:
            _ring(i.coords)
    elif geom.geom_type == 'MultiPolygon':
        for p in geom.geoms:
            _ring(p.exterior.coords)
            for i in p.interiors:
                _ring(i.coords)

    return MplPath(np.array(verts, dtype=float), codes)


def _fetch_flag(iso2: str):
    iso2 = iso2.lower()
    if iso2 in _flag_cache:          # short-circuit — None means "known bad, don't retry"
        return _flag_cache[iso2]
    _FLAG_DIR.mkdir(parents=True, exist_ok=True)
    disk = _FLAG_DIR / f'{iso2}.png'
    if disk.exists():
        try:
            img = mpimg.imread(str(disk))
            _flag_cache[iso2] = img
            return img
        except Exception:
            disk.unlink(missing_ok=True)  # corrupted — delete and re-download below
    try:
        resp = urllib.request.urlopen(_FLAG_CDN.format(code=iso2), timeout=6)
        disk.write_bytes(resp.read())
        img = mpimg.imread(str(disk))
        _flag_cache[iso2] = img
        return img
    except Exception:
        _flag_cache[iso2] = None
        return None


# ── background loader ─────────────────────────────────────────────────────────

class _Loader(QThread):
    ready = pyqtSignal(object)

    def run(self):
        import geopandas as gpd
        world = gpd.read_file(str(_GEOJSON))
        world = world[~world['TYPE'].isin(_SKIP_TYPES)].copy()
        # Reproject to Web Mercator: conformal projection that preserves
        # local shapes — countries no longer appear horizontally stretched.
        world = world.to_crs('EPSG:3857')
        # Simplify coastlines: the canvas is tiny and every circuit view is
        # padded to ≥~2 km/px, so a ~2.5 km tolerance is sub-pixel yet drops a
        # lot of vertices — every map redraw is noticeably cheaper.
        world['geometry'] = world.geometry.simplify(2500, preserve_topology=False)
        self.ready.emit(world)


# ── widget ────────────────────────────────────────────────────────────────────

class WorldMapWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._world       = None
        self._names: list[str]      = []
        self._iso2_map: dict[str,str] = {}
        self._collection  = None
        self._active      = None
        self._pending     = None
        self._label       = None
        self._flag_ims:    list = []
        self._flag_artists: list = []
        self._geom_cache:  dict = {}   # country → (union_geom, total_bounds)

        self._fig = Figure(figsize=(6, 3.6), dpi=100)
        self._fig.patch.set_facecolor(BG)
        self._ax  = self._fig.add_axes([0, 0, 1, 1])
        self._ax.set_facecolor(OCEAN)
        self._ax.set_axis_off()

        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setStyleSheet('background: transparent;')

        self._loading_lbl = QLabel('Loading map…')
        self._loading_lbl.setFont(QFont('Segoe UI', 10))
        self._loading_lbl.setStyleSheet('color: #444;')
        self._loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._loading_lbl)
        layout.addWidget(self._canvas)
        self._canvas.hide()

        self._loader = _Loader()
        self._loader.ready.connect(self._on_loaded)
        self._loader.start()

    # ── data ready ────────────────────────────────────────────────────────────

    def _on_loaded(self, world):
        # Build iso2 map; ISO_A2 is '-99' for some countries (e.g. France) —
        # fall back to ISO_A2_EH which is always populated.
        self._iso2_map = {
            admin: (a2 if a2 != '-99' else eh)
            for admin, a2, eh
            in zip(world['ADMIN'], world['ISO_A2'], world['ISO_A2_EH'])
        }

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            self._world = world.explode(index_parts=False).reset_index(drop=True)
            # Drop sub-pixel outlying islands to cut the path count (fewer paths
            # → faster redraws), but always keep each country's main landmass so
            # every circuit's country can still be highlighted.
            areas   = self._world.geometry.area
            max_adm = areas.groupby(self._world['ADMIN']).transform('max')
            self._world = self._world[(areas > 5e8) | (areas >= max_adm)].reset_index(drop=True)

        self._names = self._world['ADMIN'].tolist()

        self._world.plot(ax=self._ax, color=LAND, edgecolor=BORDER, linewidth=0.6)
        self._collection = self._ax.collections[0] if self._ax.collections else None

        self._ax.set_xlim(*_WX)
        self._ax.set_ylim(*_WY)
        # EPSG:3857: x and y both in metres → aspect='equal' renders shapes
        # correctly (conformal projection).  adjustable='box' keeps the country
        # well-sized in the view; the dark figure background looks like ocean.
        self._ax.set_aspect('equal', adjustable='datalim')

        self._label = self._ax.text(
            0, 0, '', color='#ffffff', fontsize=9, fontweight='bold',
            ha='center', va='center', zorder=10,
            bbox=dict(boxstyle='round,pad=0.3',
                      facecolor='#111', alpha=0.75, edgecolor='none')
        )
        self._label.set_visible(False)

        self._canvas.draw()
        self._loading_lbl.hide()
        self._canvas.show()

        if self._pending:
            self.highlight(self._pending)
            self._pending = None

    # ── flag drawing ──────────────────────────────────────────────────────────

    def _clear_flags(self):
        for im in self._flag_ims:
            try: im.remove()
            except Exception: pass
        for a in self._flag_artists:
            try: a.remove()
            except Exception: pass
        self._flag_ims.clear()
        self._flag_artists.clear()

    def _draw_flag(self, country_name: str) -> bool:
        iso2 = self._iso2_map.get(country_name, '')
        if not iso2 or iso2 == '-99':
            return False

        flag_img = _fetch_flag(iso2)
        if flag_img is None:
            return False

        rows = self._world[self._world['ADMIN'] == country_name]
        if rows.empty:
            return False

        if country_name in self._geom_cache:
            union_geom, b = self._geom_cache[country_name]
        else:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                areas     = rows.geometry.area
                max_area  = areas.max()
                main_geom = rows.loc[areas.idxmax(), 'geometry']
                dists     = rows.geometry.apply(lambda g: main_geom.distance(g))
                rows = rows[(areas >= max_area * 0.001) & (dists < 1_000_000)]

            if rows.empty:
                return False

            union_geom = unary_union(list(rows.geometry))
            b          = rows.geometry.total_bounds
            self._geom_cache[country_name] = (union_geom, b)

        bw, bh = b[2] - b[0], b[3] - b[1]
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2

        img_h, img_w = flag_img.shape[:2]
        img_aspect   = img_w / img_h

        # Small countries (< 600 km span): stretch flag to fill bbox so every
        # stripe colour is visible.  Cover mode would make the flag far wider
        # than the country, pushing narrow stripes entirely outside the polygon
        # (e.g. Qatar's white stripe disappears with cover).
        # Large countries: cover mode preserves the flag's native aspect ratio.
        if max(bw, bh) < 600_000:
            fw, fh = bw, bh
        elif bw / bh >= img_aspect:
            fw, fh = bw, bw / img_aspect
        else:
            fw, fh = bh * img_aspect, bh

        im = self._ax.imshow(
            flag_img,
            extent=[cx - fw/2, cx + fw/2, cy - fh/2, cy + fh/2],
            aspect='auto', origin='upper',
            zorder=4, alpha=0.88, interpolation='bilinear',
        )

        mpl_path = _shapely_to_mpl_path(union_geom)

        clip = PathPatch(mpl_path, transform=self._ax.transData,
                         facecolor='none', edgecolor='none', visible=False)
        self._ax.add_patch(clip)
        im.set_clip_path(clip)

        outline = PathPatch(mpl_path, transform=self._ax.transData,
                            facecolor='none', edgecolor=BORDER,
                            linewidth=0.8, zorder=5)
        self._ax.add_patch(outline)

        self._flag_ims.append(im)
        self._flag_artists.extend([clip, outline])
        return True

    # ── public ────────────────────────────────────────────────────────────────

    def highlight(self, country_name: str):
        if self._world is None:
            self._pending = country_name
            return

        self._active = country_name

        if self._collection is not None:
            self._collection.set_facecolor(LAND)

        self._clear_flags()
        flag_ok = self._draw_flag(country_name)

        if not flag_ok:
            colors = [HIGHLIGHT if n == country_name else LAND for n in self._names]
            if self._collection is not None:
                self._collection.set_facecolor(colors)

        # Zoom to the country's largest polygon (mainland).
        rows = self._world[self._world['ADMIN'] == country_name]
        if not rows.empty:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                main = rows.loc[[rows.geometry.area.idxmax()]]

            b   = main.geometry.total_bounds   # metres
            pad = self._pad(b)
            self._ax.set_xlim(b[0] - pad, b[2] + pad)
            self._ax.set_ylim(b[1] - pad, b[3] + pad)

            self._label.set_position(((b[0]+b[2])/2, (b[1]+b[3])/2))
            self._label.set_text(country_name)
            self._label.set_visible(True)

        self._canvas.draw_idle()

    def reset(self):
        self._active = None
        self._clear_flags()
        if self._collection is not None:
            self._collection.set_facecolor(LAND)
        if self._label:
            self._label.set_visible(False)
        self._ax.set_xlim(*_WX)
        self._ax.set_ylim(*_WY)
        self._canvas.draw_idle()

    @staticmethod
    def _pad(b):
        # b is in projected metres (EPSG:3857).
        # Tighter padding → country fills more of the screen → flag details visible.
        span = max(b[2] - b[0], b[3] - b[1])
        if span < 600_000:    return 500_000   # small: Qatar, Netherlands
        if span < 3_000_000:  return span * 0.6   # medium: Portugal, Germany, Spain
        return span * 0.2                          # large: Australia, Brazil
