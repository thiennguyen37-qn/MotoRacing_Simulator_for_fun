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

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QStackedWidget
from PyQt6.QtGui import QFont, QPixmap, QPainter
from PyQt6.QtCore import Qt, QThread, QTimer, QRectF, QCoreApplication, pyqtSignal

# Single high-res capture used by fly_to()'s pan/zoom — its figure-inches
# width (6, see Figure(figsize=...) below) times this DPI.
_FLY_CAPTURE_DPI = 480
# Extra fractional padding added around highlight()'s normal (tight) zoom for
# fly_to()'s landing — a full-screen transition needs more breathing room
# around the destination than the small Calendar/Circuit map panel does, so
# this is applied on top of _pad() rather than changing it (which those pages
# still rely on for their own, tighter zoom).
_FLY_END_PAD_MULT = 0.7
# Border/outline linewidths for the flight capture. A matplotlib linewidth is
# a FIXED physical thickness baked into the capture PNG, but fly_to() crops a
# small part of that PNG and stretches it to fill the screen — magnifying the
# baked line right along with everything else. (That's a physical enlargement,
# so a higher capture DPI makes the line crisper but NOT thinner.) The factor
# depends on how far apart the pair is: a far pair like Japan->Qatar zooms in
# ~4-5x on landing, a near pair barely at all — so a single baked linewidth
# can't read the same at every zoom. It looked heavy through the zoom-in and
# then snapped thin the moment highlight() took over with a live (screen-space)
# render, most visibly on far-apart pairs.
#
# So the capture linewidth is computed PER FLIGHT (see _fly_linewidths) so the
# most zoomed-in frame of THAT flight renders its borders at
# _FLY_TARGET_BORDER_PX — the weight the live canvas draws — making the bitmap
# overlay hand off to highlight() seamlessly, with no frame ever thicker than
# the live view (the wider middle of the flight just reads a touch fainter).
# The constants below are only a fallback for when the screen size / flight
# boxes aren't known.
_FLY_BORDER_LW  = 0.13
_FLY_OUTLINE_LW = 0.2
_FLY_OUTLINE_RATIO = _FLY_OUTLINE_LW / _FLY_BORDER_LW   # keep the highlight outline proportionally heavier
_FLY_TARGET_BORDER_PX = 2.7    # on-screen border weight the flight lands on (live canvas plots at linewidth 0.6)
_FLY_FIG_W_IN = 6              # _capture_flight_png's figure width in inches (see its figsize)


def _fly_linewidths(view_w: float, wide_w: float, screen_w_px: float) -> tuple:
    """(border_lw, outline_lw) in points for _capture_flight_png so that the
    tightest flight frame — a view `view_w` data-units wide, cropped out of a
    capture spanning `wide_w` data-units and stretched to `screen_w_px` — draws
    its borders at ~_FLY_TARGET_BORDER_PX on screen.

    A line of L points is L/72 inch = L*wide_w/(72*_FLY_FIG_W_IN) data-units
    thick in the capture; shown at screen_w_px/view_w px per data-unit that is
    L*wide_w*screen_w_px/(72*_FLY_FIG_W_IN*view_w) px on screen. Solving that
    for the target thickness gives the linewidth below. `view_w` is the
    NARROWEST view of the flight (min of start/end box), so no frame ends up
    thicker than the target."""
    if wide_w <= 0 or view_w <= 0 or screen_w_px <= 0:
        return _FLY_BORDER_LW, _FLY_OUTLINE_LW
    border = _FLY_TARGET_BORDER_PX * 72.0 * _FLY_FIG_W_IN * view_w / (wide_w * screen_w_px)
    return border, border * _FLY_OUTLINE_RATIO

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


# ── background fly_to() capture ───────────────────────────────────────────────
# Free functions (no `self`) so the capture can run on a worker thread without
# touching WorldMapWidget's own Figure/Axes/canvas — those stay the main
# thread's alone, so a background capture can't race a concurrent highlight().

def _draw_flag_on(ax, world, iso2_map: dict, country_name: str,
                  outline_lw: float = _FLY_OUTLINE_LW) -> None:
    """Draw `country_name`'s flag, clipped to its shape, onto `ax` — the same
    look as WorldMapWidget._draw_flag, standalone so _capture_flight_png can
    build a throwaway Figure for a background capture."""
    iso2 = iso2_map.get(country_name, '')
    if not iso2 or iso2 == '-99':
        return
    flag_img = _fetch_flag(iso2)
    if flag_img is None:
        return
    rows = world[world['ADMIN'] == country_name]
    if rows.empty:
        return
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        areas     = rows.geometry.area
        max_area  = areas.max()
        main_geom = rows.loc[areas.idxmax(), 'geometry']
        dists     = rows.geometry.apply(lambda g: main_geom.distance(g))
        rows = rows[(areas >= max_area * 0.001) & (dists < 1_000_000)]
    if rows.empty:
        return
    union_geom = unary_union(list(rows.geometry))
    b          = rows.geometry.total_bounds

    bw, bh = b[2] - b[0], b[3] - b[1]
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    img_h, img_w = flag_img.shape[:2]
    img_aspect   = img_w / img_h
    if max(bw, bh) < 600_000:
        fw, fh = bw, bh
    elif bw / bh >= img_aspect:
        fw, fh = bw, bw / img_aspect
    else:
        fw, fh = bh * img_aspect, bh

    im = ax.imshow(
        flag_img, extent=[cx - fw/2, cx + fw/2, cy - fh/2, cy + fh/2],
        aspect='auto', origin='upper', zorder=4, alpha=0.88,
        interpolation='bilinear',
    )
    mpl_path = _shapely_to_mpl_path(union_geom)
    clip = PathPatch(mpl_path, transform=ax.transData,
                     facecolor='none', edgecolor='none', visible=False)
    ax.add_patch(clip)
    im.set_clip_path(clip)
    outline = PathPatch(mpl_path, transform=ax.transData,
                        facecolor='none', edgecolor=BORDER,
                        linewidth=outline_lw, zorder=5)
    ax.add_patch(outline)


def _fit_box_aspect(box: tuple, aspect: float) -> tuple:
    """Expand `box` (x0,x1,y0,y1), centred, along whichever axis is too
    narrow so its width/height ratio becomes exactly `aspect`. Used to make
    every box in a fly_to() flight match the real screen aspect — see
    WorldMapWidget._flight_boxes for why that matters."""
    x0, x1, y0, y1 = box
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if w / h < aspect:
        new_w = h * aspect
        return (cx - new_w / 2, cx + new_w / 2, y0, y1)
    new_h = w / aspect
    return (x0, x1, cy - new_h / 2, cy + new_h / 2)


def _capture_flight_png(world, iso2_map: dict, box: tuple,
                        from_country: str, to_country: str, dpi: int,
                        border_lw: float = _FLY_BORDER_LW,
                        outline_lw: float = _FLY_OUTLINE_LW) -> bytes:
    """Render `box` (x0,x1,y0,y1) with both countries flagged, to PNG bytes —
    builds its own throwaway Figure/Axes so it's safe to call from a
    background thread (see _FlyCaptureThread).

    The figure's own aspect ratio is derived from `box` itself (rather than a
    fixed shape) so the render can't stretch the geometry to fit a canvas
    shaped differently from the box being captured — WorldMapWidget's own
    interactive canvas avoids this via set_aspect('equal', ...), which isn't
    available on this throwaway one-off Figure."""
    box_aspect = (box[1] - box[0]) / (box[3] - box[2])
    fig = Figure(figsize=(_FLY_FIG_W_IN, _FLY_FIG_W_IN / box_aspect), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(OCEAN)
    ax.set_axis_off()
    world.plot(ax=ax, color=LAND, edgecolor=BORDER, linewidth=border_lw)
    _draw_flag_on(ax, world, iso2_map, from_country, outline_lw)
    _draw_flag_on(ax, world, iso2_map, to_country, outline_lw)
    ax.set_xlim(box[0], box[1])
    ax.set_ylim(box[2], box[3])
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, facecolor=fig.get_facecolor())
    return buf.getvalue()


class _FlyCaptureThread(QThread):
    """Renders fly_to()'s wide-view capture off the main thread, via the free
    functions above — kicked off ahead of time by preload_fly() so the
    capture is normally already done by the time the player actually
    triggers fly_to(), instead of blocking the UI while it renders."""

    ready = pyqtSignal(tuple, bytes, tuple)   # (key, png_bytes, box)

    def __init__(self, key, world, iso2_map, box, from_country, to_country, dpi,
                 border_lw=_FLY_BORDER_LW, outline_lw=_FLY_OUTLINE_LW):
        super().__init__()
        self._key = key
        self._world = world
        self._iso2_map = iso2_map
        self._box = box
        self._from = from_country
        self._to = to_country
        self._dpi = dpi
        self._border_lw = border_lw
        self._outline_lw = outline_lw

    def run(self):
        png = _capture_flight_png(self._world, self._iso2_map, self._box,
                                  self._from, self._to, self._dpi,
                                  self._border_lw, self._outline_lw)
        self.ready.emit(self._key, png, self._box)


class _FlyOverlay(QWidget):
    """Displays a crop of a single pre-rendered high-res map capture, scaled
    to fill the widget — used by fly_to() so its pan/zoom animation is a cheap
    per-frame QPainter blit instead of a full matplotlib re-render (redrawing
    the whole vector world map on every tick was what made the pan stutter)."""

    def __init__(self):
        super().__init__()
        self._pixmap: QPixmap | None = None
        self._data_box = None     # (x0, x1, y0, y1) the pixmap covers, EPSG:3857 m
        self._view_box = None     # current (x0, x1, y0, y1) sub-rect to show

    def set_image(self, pixmap: QPixmap, data_box: tuple):
        self._pixmap = pixmap
        self._data_box = data_box
        self._view_box = data_box
        self.update()

    def set_view(self, x0: float, x1: float, y0: float, y1: float):
        self._view_box = (x0, x1, y0, y1)
        self.update()

    def paintEvent(self, event):
        if self._pixmap is None or self._data_box is None or self._view_box is None:
            return
        dx0, dx1, dy0, dy1 = self._data_box
        vx0, vx1, vy0, vy1 = self._view_box
        w, h = self._pixmap.width(), self._pixmap.height()
        # Data y increases north/up; pixmap rows increase downward — flip.
        px0 = (vx0 - dx0) / (dx1 - dx0) * w
        px1 = (vx1 - dx0) / (dx1 - dx0) * w
        py0 = (dy1 - vy1) / (dy1 - dy0) * h
        py1 = (dy1 - vy0) / (dy1 - dy0) * h
        source = QRectF(px0, py0, px1 - px0, py1 - py0)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(QRectF(self.rect()), self._pixmap, source)


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
        self._fly_timer: QTimer | None = None
        self._fly_active = False
        self._fly_cache: dict | None = None            # {'key','pixmap','box'} — see preload_fly
        self._fly_capture_thread: _FlyCaptureThread | None = None
        self._fly_end_box: tuple | None = None          # current flight's landing box — see fly_to/fly_skip

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

        # Three pages, one visible at a time: loading text, the interactive
        # matplotlib canvas (normal highlight()/reset() use), and the fly-to
        # overlay (a cheap pixmap blit swapped in only during fly_to()'s
        # animation, then swapped back out).
        self._fly_overlay = _FlyOverlay()
        self._pages = QStackedWidget()
        self._pages.addWidget(self._loading_lbl)   # 0
        self._pages.addWidget(self._canvas)        # 1
        self._pages.addWidget(self._fly_overlay)    # 2

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._pages)

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
        self._pages.setCurrentWidget(self._canvas)

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

    def highlight(self, country_name: str, box: tuple | None = None):
        """Zoom to `country_name`, drawing its flag. `box` overrides the
        normal tight _pad()-based zoom with a caller-supplied (x0,x1,y0,y1) —
        used by fly_to() to land exactly on the wider framing its animation
        eased into, instead of snapping to the tighter default the instant it
        finishes."""
        if self._world is None:
            self._pending = country_name
            return

        self._pages.setCurrentWidget(self._canvas)   # in case fly_to() left the overlay showing
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

            b = main.geometry.total_bounds   # metres
            if box is not None:
                x0, x1, y0, y1 = box
            else:
                pad = self._pad(b)
                x0, x1, y0, y1 = b[0] - pad, b[2] + pad, b[1] - pad, b[3] + pad
            self._ax.set_xlim(x0, x1)
            self._ax.set_ylim(y0, y1)

            self._label.set_position(((b[0]+b[2])/2, (b[1]+b[3])/2))
            self._label.set_text(country_name)
            self._label.set_visible(True)

        self._canvas.draw_idle()

    def _country_box(self, country_name: str):
        """(x0, x1, y0, y1) padded view bounds for a country's mainland
        polygon, in EPSG:3857 metres — the same box highlight() zooms to.
        None if the country isn't in the loaded geometry."""
        rows = self._world[self._world['ADMIN'] == country_name]
        if rows.empty:
            return None
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            main = rows.loc[[rows.geometry.area.idxmax()]]
        b = main.geometry.total_bounds
        pad = self._pad(b)
        return (b[0] - pad, b[2] + pad, b[1] - pad, b[3] + pad)

    @staticmethod
    def _expand_box(box: tuple, extra_frac: float) -> tuple:
        x0, x1, y0, y1 = box
        w, h = x1 - x0, y1 - y0
        dw, dh = w * extra_frac / 2, h * extra_frac / 2
        return (x0 - dw, x1 + dw, y0 - dh, y1 + dh)

    def _screen_aspect(self) -> float:
        """This widget's current width/height — falls back to a plausible
        widescreen ratio if it hasn't been given real geometry yet (shouldn't
        normally happen: preload_fly()/fly_to() run once the app's already
        showing its normal window)."""
        w, h = self.width(), self.height()
        return w / h if w > 0 and h > 0 else 16 / 9

    def _flight_boxes(self, from_country: str, to_country: str):
        """(start_box, end_box, wide_box) for fly_to()/preload_fly() — end_box
        is highlight()'s normal destination zoom widened by _FLY_END_PAD_MULT
        (a full-screen transition needs more breathing room than the small
        map panel's tight zoom), and wide_box is the box, padded further, that
        contains both — the widest extent shown at any point in the flight.

        All three are then fit to this widget's actual screen aspect ratio
        (_fit_box_aspect). That's not just cosmetic centring: fly_to()'s
        per-frame view is a *linear interpolation* of these boxes' raw edges,
        and that interpolation only keeps a constant width/height ratio at
        every intermediate frame if the boxes it's between already share one
        — otherwise the map visibly stretches/squashes through the pan
        (countries reading tall-and-thin partway through the flight, which is
        exactly what was happening before this).

        None if either country isn't in the loaded geometry."""
        start_box = self._country_box(from_country)
        end_tight = self._country_box(to_country)
        if start_box is None or end_tight is None:
            return None
        end_box = self._expand_box(end_tight, _FLY_END_PAD_MULT)
        wx0, wx1 = min(start_box[0], end_box[0]), max(start_box[1], end_box[1])
        wy0, wy1 = min(start_box[2], end_box[2]), max(start_box[3], end_box[3])
        wpad = max(wx1 - wx0, wy1 - wy0) * 0.18
        wide_box = (wx0 - wpad, wx1 + wpad, wy0 - wpad, wy1 + wpad)

        aspect = self._screen_aspect()
        start_box = _fit_box_aspect(start_box, aspect)
        end_box   = _fit_box_aspect(end_box, aspect)
        wide_box  = _fit_box_aspect(wide_box, aspect)
        return start_box, end_box, wide_box

    def _flight_linewidths(self, start_box, end_box, wide_box) -> tuple:
        """Per-flight (border_lw, outline_lw) for the capture — tuned to this
        flight's tightest view so its borders land at the live canvas's own
        weight instead of thickening on the zoom-in (see _fly_linewidths)."""
        view_w = min(start_box[1] - start_box[0], end_box[1] - end_box[0])
        wide_w = wide_box[1] - wide_box[0]
        return _fly_linewidths(view_w, wide_w, self.width())

    def preload_fly(self, from_country: str, to_country: str):
        """Kick off fly_to()'s expensive wide-view capture in the BACKGROUND,
        ahead of the player actually pressing the button — call this as soon
        as the destination is known (e.g. when a recap screen naming it
        appears). By the time fly_to() actually runs, the capture is usually
        already sitting in _fly_cache and the animation starts immediately;
        otherwise fly_to() falls back to rendering it synchronously itself.
        A no-op if the map data or either country isn't ready yet, or if this
        exact (from, to) pair is already cached or being captured."""
        if self._world is None or from_country not in self._names or to_country not in self._names:
            return
        key = (from_country, to_country)
        if self._fly_cache is not None and self._fly_cache['key'] == key:
            return
        if self._fly_capture_thread is not None and self._fly_capture_thread.isRunning():
            if self._fly_capture_thread._key == key:
                return
            self._fly_capture_thread.wait()   # let the stale one finish; its result is just ignored below
        boxes = self._flight_boxes(from_country, to_country)
        if boxes is None:
            return
        start_box, end_box, wide_box = boxes
        border_lw, outline_lw = self._flight_linewidths(start_box, end_box, wide_box)
        th = _FlyCaptureThread(key, self._world, self._iso2_map, wide_box,
                               from_country, to_country, _FLY_CAPTURE_DPI,
                               border_lw, outline_lw)
        th.ready.connect(self._on_fly_captured)
        self._fly_capture_thread = th
        th.start()

    def _on_fly_captured(self, key: tuple, png_bytes: bytes, box: tuple):
        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes, 'PNG')
        self._fly_cache = {'key': key, 'pixmap': pixmap, 'box': box}

    def fly_to(self, from_country: str, to_country: str, on_done=None,
              duration_ms: int = 2200):
        """Animate the camera from `from_country` to `to_country`: zoom out to
        a view wide enough to hold both (their flags both visible at once),
        hold there briefly, then zoom into the destination — like a map
        app's "fly to" transition. Ends in the exact state highlight(
        to_country) would leave (single flag, label, but framed by the wider
        landing box the animation eased into — see _flight_boxes). Calls
        on_done() once finished, or immediately with an instant highlight()
        if the map data or either country isn't available yet.

        Uses preload_fly()'s cached capture if it's ready (near-zero delay);
        otherwise renders it synchronously here, after forcing the
        highlight(from_country) below to actually paint first so the
        (blocking) wait reads as a deliberate pause, not a freeze.

        fly_skip() cuts an in-progress animation straight to that same end
        state, for a player-triggered skip."""
        if (self._world is None or self._fly_active
                or from_country not in self._names or to_country not in self._names):
            self.highlight(to_country)
            if on_done:
                on_done()
            return

        boxes = self._flight_boxes(from_country, to_country)
        if boxes is None:
            self.highlight(to_country)
            if on_done:
                on_done()
            return
        start_box, end_box, wide_box = boxes
        self._fly_end_box = end_box   # so fly_skip() lands with the same framing

        # Snap the (still-visible) canvas to the departure country first —
        # a cache miss below takes a beat to render, and showing
        # "from_country" zoomed in during that beat reads as a deliberate
        # pause, not a hang.
        self.highlight(from_country)

        key = (from_country, to_country)
        if self._fly_cache is not None and self._fly_cache['key'] == key:
            pixmap, capture_box = self._fly_cache['pixmap'], self._fly_cache['box']
        else:
            QCoreApplication.processEvents()   # actually paint the highlight() above before blocking
            border_lw, outline_lw = self._flight_linewidths(start_box, end_box, wide_box)
            png = _capture_flight_png(self._world, self._iso2_map, wide_box,
                                      from_country, to_country, _FLY_CAPTURE_DPI,
                                      border_lw, outline_lw)
            pixmap = QPixmap()
            pixmap.loadFromData(png, 'PNG')
            capture_box = wide_box
        self._fly_cache = None

        self._active = to_country
        if self._collection is not None:
            self._collection.set_facecolor(LAND)
        self._clear_flags()
        self._draw_flag(from_country)
        self._draw_flag(to_country)
        if self._label:
            self._label.set_visible(False)

        self._fly_overlay.set_image(pixmap, capture_box)
        self._fly_overlay.set_view(*start_box)
        self._pages.setCurrentWidget(self._fly_overlay)

        # Three phases of duration_ms: zoom out to the wide view, hold there
        # (both flags visible), then zoom into the destination.
        phases = [
            (start_box, wide_box, duration_ms * 0.30),
            (wide_box,  wide_box, duration_ms * 0.25),
            (wide_box,  end_box,  duration_ms * 0.45),
        ]
        state = {'phase': 0, 'elapsed': 0.0}

        def _tick():
            state['elapsed'] += 16
            box_from, box_to, dur = phases[state['phase']]
            frac = min(1.0, state['elapsed'] / max(dur, 1))
            e = 1 - (1 - frac) ** 3   # ease-out cubic
            x0 = box_from[0] + (box_to[0] - box_from[0]) * e
            x1 = box_from[1] + (box_to[1] - box_from[1]) * e
            y0 = box_from[2] + (box_to[2] - box_from[2]) * e
            y1 = box_from[3] + (box_to[3] - box_from[3]) * e
            self._fly_overlay.set_view(x0, x1, y0, y1)
            if frac >= 1.0:
                state['phase'] += 1
                state['elapsed'] = 0.0
                if state['phase'] >= len(phases):
                    self._fly_timer.stop()
                    self._fly_active = False
                    self.highlight(to_country, box=end_box)   # lands framed exactly like the animation's last frame
                    if on_done:
                        on_done()

        self._fly_active = True
        self._fly_timer = QTimer(self)
        self._fly_timer.setInterval(16)
        self._fly_timer.timeout.connect(_tick)
        self._fly_timer.start()

    def fly_skip(self, to_country: str, on_done=None):
        """Cut an in-progress fly_to() straight to its end state."""
        if self._fly_timer is not None:
            self._fly_timer.stop()
        was_active = self._fly_active
        self._fly_active = False
        if was_active:
            self.highlight(to_country, box=self._fly_end_box)
            if on_done:
                on_done()

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
