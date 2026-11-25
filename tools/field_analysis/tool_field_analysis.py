# -*- coding: utf-8 -*-
"""
tool_field_analysis.py

Análise Rápida do Talhão — busca cenas Sentinel-2 via STAC, recorta ao talhão
e calcula índices de vegetação (NDVI, EVI, SAVI, MSAVI, NDWI ou personalizado).

Quick Field Analysis — searches Sentinel-2 scenes via STAC, clips to the field
polygon extent, and computes vegetation indices.
"""

import os
import re
import tempfile
import urllib.parse
import urllib.request

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QComboBox, QFrame, QGroupBox, QWidget, QScrollArea,
    QApplication, QMessageBox, QListWidget, QListWidgetItem,
    QProgressDialog, QFileDialog, QLineEdit, QCheckBox,
    QDateEdit, QSpinBox, QToolButton,
)
from qgis.PyQt.QtCore import Qt, QDate, QThread, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPixmap
from qgis.core import (
    Qgis, QgsProject, QgsRasterLayer,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsSingleBandPseudoColorRenderer, QgsColorRampShader,
    QgsRasterShader, QgsRasterBandStats,
)

# RTH core — available via sys.path set in RTH PROJECT.py
from core.rth_stac_api import search_stac
from core.rth_band_resolver import find_asset_key
from core.rth_layer_utils import collapse_layer

# ── Dependency check ──────────────────────────────────────────────────────────
try:
    import numpy as np
    from osgeo import gdal as _gdal_check  # noqa: F401
    _DEPS_OK = True
    _DEPS_MSG = ''
except ImportError as _e:
    _DEPS_OK = False
    _DEPS_MSG = str(_e)
    np = None

# ── Sentinel-2 collections ────────────────────────────────────────────────────
_COLLECTIONS = [
    ('S2_L2A-1',         'Sentinel-2 L2A — INPE/BDC (Brasil)'),          # padrão / default
    ('S2-16D-2',         'Sentinel-2 16D Cube — INPE/BDC (Brasil)'),
    ('sentinel-2-l2a',   'Sentinel-2 L2A — Planetary Computer (Global)'),
]

# ── Band variable → Sentinel-2 asset name ─────────────────────────────────────
_BAND_VARS = {
    'nir':      'B08',   # NIR broad 10 m
    'red':      'B04',   # Red 10 m
    'green':    'B03',   # Green 10 m
    'blue':     'B02',   # Blue 10 m
    'swir1':    'B11',   # SWIR-1 20 m
    'swir2':    'B12',   # SWIR-2 20 m
    'rededge':  'B05',   # Red-edge-1 20 m
    'rededge2': 'B06',   # Red-edge-2 20 m
    'rededge3': 'B07',   # Red-edge-3 20 m
    'nir2':     'B8A',   # Narrow NIR 20 m
}

# ── Predefined index definitions ──────────────────────────────────────────────
_INDEX_DEFS = {
    'NDVI': {
        'label':   'NDVI  —  (NIR − RED) / (NIR + RED)',
        'vars':    ['nir', 'red'],
        'formula': '(nir - red) / (nir + red)',
        'vmin': -1.0, 'vmax': 1.0,
    },
    'EVI': {
        'label':   'EVI  —  2.5 × (NIR−RED) / (NIR + 6×RED − 7.5×BLUE + 1)',
        'vars':    ['nir', 'red', 'blue'],
        'formula': '2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1)',
        'vmin': -1.0, 'vmax': 1.0,
    },
    'SAVI': {
        'label':   'SAVI  —  1.5 × (NIR − RED) / (NIR + RED + 0.5)',
        'vars':    ['nir', 'red'],
        'formula': '1.5 * (nir - red) / (nir + red + 0.5)',
        'vmin': -1.5, 'vmax': 1.5,
    },
    'MSAVI': {
        'label':   'MSAVI  —  (2×NIR+1 − √((2×NIR+1)²−8×(NIR−RED))) / 2',
        'vars':    ['nir', 'red'],
        'formula': '(2*nir + 1 - np.sqrt(np.maximum(0, (2*nir+1)**2 - 8*(nir-red)))) / 2',
        'vmin': -1.0, 'vmax': 1.0,
    },
    'NDWI': {
        'label':   'NDWI  —  (GREEN − NIR) / (GREEN + NIR)',
        'vars':    ['green', 'nir'],
        'formula': '(green - nir) / (green + nir)',
        'vmin': -1.0, 'vmax': 1.0,
    },
    'Custom': {
        'label':   'Personalizado / Custom',
        'vars':    [],
        'formula': '',
        'vmin': -1.0, 'vmax': 1.0,
    },
}

_NODATA = -9999.0


# ── GDAL / computation helpers ────────────────────────────────────────────────

def _init_gdal():
    """Configure GDAL for remote COG access via vsicurl."""
    try:
        from osgeo import gdal
    except ImportError:
        return None
    gdal.SetConfigOption('GDAL_HTTP_UNSAFESSL',          'YES')
    gdal.SetConfigOption('GDAL_HTTP_TIMEOUT',            '60')
    gdal.SetConfigOption('CPL_VSIL_CURL_USE_CACHE',      'YES')
    gdal.SetConfigOption('CPL_VSIL_CURL_CACHE_SIZE',     '128000000')
    gdal.SetConfigOption('GDAL_DISABLE_READDIR_ON_OPEN', 'EMPTY_DIR')
    return gdal


def _resolve(href):
    try:
        from core.rth_pc_auth import resolve_href
        return resolve_href(href)
    except Exception:
        return href


def _scene_utm(feature):
    try:
        from core.rth_utm_utils import detect_regional_utm
        bbox = feature.get('bbox', [])
        if len(bbox) >= 4:
            lon = (bbox[0] + bbox[2]) / 2.0
            lat = (bbox[1] + bbox[3]) / 2.0
            epsg, _, _, _ = detect_regional_utm(lon, lat)
            return 'EPSG:{}'.format(epsg)
    except Exception:
        pass
    return 'EPSG:4326'


def _bbox_from_layer(layer, selected_only=False):
    """Return [min_lon, min_lat, max_lon, max_lat] in WGS84."""
    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    crs   = layer.crs()
    ext   = None  # always initialised so the checks below are safe

    if selected_only and layer.selectedFeatureCount() > 0:
        from qgis.core import QgsRectangle
        for feat in layer.selectedFeatures():
            geom = feat.geometry()
            if geom is None or geom.isNull():
                continue
            bb = geom.boundingBox()
            if bb is None or bb.isNull():
                continue
            if ext is None:
                ext = QgsRectangle(bb)   # defensive copy — combineExtentWith is void/in-place
            else:
                ext.combineExtentWith(bb)  # modifies ext in-place; return value is None, not captured

    # Fall back to full-layer extent when no (valid) selection was built
    if ext is None or ext.isNull():
        ext = layer.extent()

    if ext is None or ext.isNull():
        raise ValueError('Nenhuma extensão válida encontrada na camada / No valid extent found in layer')

    if crs != wgs84:
        xf  = QgsCoordinateTransform(crs, wgs84, QgsProject.instance())
        ext = xf.transformBoundingBox(ext)

    return [
        round(ext.xMinimum(), 6),
        round(ext.yMinimum(), 6),
        round(ext.xMaximum(), 6),
        round(ext.yMaximum(), 6),
    ]


def _bbox_from_geometry(geom, src_crs):
    """Return [min_lon, min_lat, max_lon, max_lat] from a single QgsGeometry."""
    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    ext = geom.boundingBox()
    if src_crs != wgs84:
        xf = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
        ext = xf.transformBoundingBox(ext)
    return [
        round(ext.xMinimum(), 6),
        round(ext.yMinimum(), 6),
        round(ext.xMaximum(), 6),
        round(ext.yMaximum(), 6),
    ]


def _poly_wkt_in_crs(layer, selected_only, target_crs_str):
    """Return WKT of the layer polygon (union if multiple) reprojected to target_crs_str."""
    from qgis.core import QgsGeometry
    target = QgsCoordinateReferenceSystem(target_crs_str)
    src    = layer.crs()

    if selected_only and layer.selectedFeatureCount() > 0:
        geoms = [f.geometry() for f in layer.selectedFeatures()]
    else:
        geoms = [f.geometry() for f in layer.getFeatures()]

    if not geoms:
        return None

    poly = QgsGeometry.unaryUnion(geoms) if len(geoms) > 1 else QgsGeometry(geoms[0])
    if poly.isEmpty():
        return None

    if src != target:
        xf = QgsCoordinateTransform(src, target, QgsProject.instance())
        poly.transform(xf)

    return poly.asWkt()


def _write_cutline(poly_wkt, target_crs_str):
    """Persist polygon WKT to a temp GeoPackage for use as GDAL cutline. Returns path."""
    import tempfile
    from osgeo import ogr, osr

    epsg     = int(target_crs_str.split(':')[1])
    tmp_path = os.path.join(tempfile.gettempdir(),
                            'rth_cutline_{}.gpkg'.format(os.getpid()))
    drv = ogr.GetDriverByName('GPKG')
    if os.path.exists(tmp_path):
        drv.DeleteDataSource(tmp_path)

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)

    ds  = drv.CreateDataSource(tmp_path)
    lyr = ds.CreateLayer('cutline', srs=srs, geom_type=ogr.wkbMultiPolygon)
    ft  = ogr.Feature(lyr.GetLayerDefn())
    ft.SetGeometry(ogr.CreateGeometryFromWkt(poly_wkt))
    lyr.CreateFeature(ft)
    ds.FlushCache()
    ds = None
    return tmp_path


def _clip_band(feature, band_name, bbox_wgs84, gdal, target_crs, cutline_path=None):
    """Download-free clip of one Sentinel-2 COG band to bbox. Returns MEM dataset.

    If cutline_path is given the output is also masked to the polygon shape
    (pixels outside the polygon are set to nodata).
    """
    assets = feature.get('assets', {})
    key    = find_asset_key(assets, band_name)
    if key is None:
        return None

    href = _resolve(assets[key]['href'])
    url  = '/vsicurl/' + href

    warp_kw = dict(
        format='MEM',
        outputBounds=[bbox_wgs84[0], bbox_wgs84[1], bbox_wgs84[2], bbox_wgs84[3]],
        outputBoundsSRS='EPSG:4326',
        dstSRS=target_crs,
        resampleAlg='bilinear',
        multithread=True,
    )
    if cutline_path:
        warp_kw['cutlineDSName'] = cutline_path
        warp_kw['dstNodata']     = _NODATA

    opts = gdal.WarpOptions(**warp_kw)
    return gdal.Warp('', url, options=opts)


def _ds_to_array(ds):
    """Read band 1 as float32, normalise S2 reflectance (DN 0-10000 → 0-1)."""
    band = ds.GetRasterBand(1)
    nd   = band.GetNoDataValue()
    arr  = band.ReadAsArray().astype('float32')
    if nd is not None:
        arr[arr == nd] = float('nan')
    if np.nanmax(arr) > 2.0:          # S2 DN, not already 0-1
        arr = arr / 10000.0
    return arr


def _match_shape(arr, ref_shape):
    """Resample arr to ref_shape using bilinear (numpy-only fallback)."""
    if arr.shape == ref_shape:
        return arr
    try:
        from scipy.ndimage import zoom
        zr = ref_shape[0] / arr.shape[0]
        zc = ref_shape[1] / arr.shape[1]
        return zoom(arr, (zr, zc), order=1).astype('float32')
    except ImportError:
        # numpy-only nearest-neighbour
        rows, cols = ref_shape
        ri = (np.arange(rows) * arr.shape[0] / rows).astype(int)
        ci = (np.arange(cols) * arr.shape[1] / cols).astype(int)
        return arr[np.ix_(ri, ci)].astype('float32')


def _eval_formula(formula, band_dict):
    """Safely evaluate a band-math formula with numpy in namespace."""
    safe = re.sub(r'[^a-zA-Z0-9_.+\-*/()^\s,]', '', formula)
    ns   = {'np': np, '__builtins__': {}}
    ns.update(band_dict)
    try:
        result = eval(safe, ns)  # nosec: local QGIS plugin, user controls their own machine
        return np.asarray(result, dtype='float32')
    except Exception as e:
        raise ValueError('Erro na fórmula / Formula error: {}'.format(e))


def _write_tiff(arr, gt, proj, output_path):
    """Write float32 GeoTIFF with LZW compression and nodata = -9999."""
    from osgeo import gdal
    rows, cols = arr.shape
    driver = gdal.GetDriverByName('GTiff')
    ds_out = driver.Create(
        output_path, cols, rows, 1, gdal.GDT_Float32,
        options=['COMPRESS=LZW', 'BIGTIFF=IF_SAFER'])
    ds_out.SetGeoTransform(gt)
    ds_out.SetProjection(proj)
    band = ds_out.GetRasterBand(1)
    band.SetNoDataValue(_NODATA)
    out = np.where(np.isnan(arr), _NODATA, arr).astype('float32')
    band.WriteArray(out)
    ds_out.FlushCache()
    del ds_out


def _apply_pseudocolor(layer, vmin, vmax):
    """Apply RdYlGn pseudocolor ramp (red=low, green=high)."""
    from qgis.core import QgsStyle
    shader_fn = QgsColorRampShader()
    shader_fn.setColorRampType(QgsColorRampShader.Interpolated)
    shader_fn.setClassificationMode(QgsColorRampShader.Continuous)

    ramp = QgsStyle.defaultStyle().colorRamp('RdYlGn')
    if ramp:
        n     = 12
        steps = [i / n for i in range(n + 1)]
        items = []
        for t in steps:
            val = vmin + t * (vmax - vmin)
            items.append(QgsColorRampShader.ColorRampItem(val, ramp.color(t), '{:.2f}'.format(val)))
    else:
        mid = (vmin + vmax) / 2.0
        items = [
            QgsColorRampShader.ColorRampItem(vmin, QColor('#d73027'), '{:.2f}'.format(vmin)),
            QgsColorRampShader.ColorRampItem(mid,  QColor('#ffffbf'), '{:.2f}'.format(mid)),
            QgsColorRampShader.ColorRampItem(vmax, QColor('#1a9850'), '{:.2f}'.format(vmax)),
        ]

    shader_fn.setColorRampItemList(items)
    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(shader_fn)

    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, raster_shader)
    layer.setRenderer(renderer)
    layer.triggerRepaint()


# ── Thumbnail helpers ─────────────────────────────────────────────────────────

def _find_thumbnail_url(feature):
    """Return thumbnail/preview URL from STAC feature assets, or None."""
    assets = feature.get('assets', {})
    for key in ('rendered_preview', 'thumbnail', 'overview', 'visual_thumbnail', 'preview'):
        if key in assets:
            href = assets[key].get('href', '')
            if href:
                return href
    for key, asset in assets.items():
        roles = asset.get('roles', [])
        if 'thumbnail' in roles or 'overview' in roles:
            href = asset.get('href', '')
            if href:
                return href
    return None


class _ThumbFetcher(QThread):
    """Downloads a thumbnail image in the background."""

    loaded = pyqtSignal(bytes)
    failed = pyqtSignal()

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self._url = url

    def run(self):
        try:
            if urllib.parse.urlparse(self._url).scheme not in ('http', 'https'):
                self.failed.emit()
                return
            req = urllib.request.Request(
                self._url, headers={'User-Agent': 'QGIS-RTH-FieldAnalysis/1.0'}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:  # nosec B310
                data = resp.read()
            self.loaded.emit(data)
        except Exception:
            self.failed.emit()


def _parse_s2_id(scene_id):
    """Extract (sensing_date, mgrs_tile, suffix) from a Sentinel-2 scene ID.

    Example: 'S2B_MSIL2A_20260503T132229_N0512_R038_T23LMH_20260503T154032'
    → ('2026-05-03', '23LMH', '23LMH_20260503T154032')
    Falls back to ('', '', scene_id) if the pattern is not recognised.
    """
    parts = scene_id.split('_')
    for i, p in enumerate(parts):
        if re.match(r'^T[0-9]{2}[A-Z]{3}$', p):          # e.g. T23LMH
            mgrs      = p[1:]                              # 23LMH
            suffix    = '_'.join(parts[i:])[1:]            # 23LMH_20260503T154032
            # sensing date is in the 3rd segment: 20260503T132229
            raw_date  = parts[2] if len(parts) > 2 else ''
            s_date    = '{}-{}-{}'.format(raw_date[:4], raw_date[4:6], raw_date[6:8]) if len(raw_date) >= 8 else ''
            return s_date, mgrs, suffix
    # Non-S2 or unrecognised — return raw ID as suffix
    return '', '', scene_id


# ── Dialog ────────────────────────────────────────────────────────────────────

class FieldAnalysisDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._thumb_fetcher: _ThumbFetcher | None = None

        self.setWindowTitle('RTH — Índices de Vegetação em Talhão / Vegetation Indices in Field')
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(580)
        self.setMinimumHeight(700)
        self.setMaximumHeight(920)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        root = QVBoxLayout(container)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────────
        lbl_t = QLabel('Índices de Vegetação em Talhão / Vegetation Indices in Field')
        lbl_t.setAlignment(Qt.AlignCenter)
        lbl_t.setStyleSheet('font-size:13px;font-weight:bold;')
        root.addWidget(lbl_t)

        lbl_s = QLabel(
            'Selecione o talhão, busque cenas Sentinel-2 e compute índices de vegetação sem download.\n'
            'Select a field polygon, search Sentinel-2, and compute indices directly from COG — no full download.')
        lbl_s.setAlignment(Qt.AlignCenter)
        lbl_s.setStyleSheet('color:#666;font-size:10px;')
        lbl_s.setWordWrap(True)
        root.addWidget(lbl_s)

        if not _DEPS_OK:
            lbl_dep = QLabel('⚠  Dependências ausentes / Missing deps: numpy, gdal — ' + _DEPS_MSG)
            lbl_dep.setWordWrap(True)
            lbl_dep.setStyleSheet(
                'color:#b71c1c;background:#ffebee;border:1px solid #e57373;'
                'border-radius:3px;padding:4px;font-size:10px;')
            root.addWidget(lbl_dep)

        root.addWidget(self._sep())

        # ── Talhão ────────────────────────────────────────────────────────────
        grp_field = QGroupBox('Talhão / Field Polygon')
        gl_f = QGridLayout()
        gl_f.setContentsMargins(8, 6, 8, 8)
        gl_f.setSpacing(6)
        gl_f.setColumnStretch(1, 1)

        gl_f.addWidget(QLabel('Camada ativa / Active layer:'), 0, 0)
        self.lbl_active_layer = QLabel('—')
        self.lbl_active_layer.setStyleSheet('font-weight:bold;font-size:11px;')
        self.lbl_active_layer.setWordWrap(True)
        gl_f.addWidget(self.lbl_active_layer, 0, 1)

        lbl_poly_hint = QLabel(
            'Selecione um ou mais polígonos na camada ativa antes de buscar. '
            'Se nenhum selecionado, usa todos os polígonos da camada.\n'
            'Select one or more polygons in the active layer. '
            'If none selected, uses all layer polygons.')
        lbl_poly_hint.setStyleSheet('color:#666;font-size:9px;')
        lbl_poly_hint.setWordWrap(True)
        gl_f.addWidget(lbl_poly_hint, 1, 0, 1, 2)

        grp_field.setLayout(gl_f)
        root.addWidget(grp_field)

        # ── Busca / Search ────────────────────────────────────────────────────
        grp_search = QGroupBox('Busca de Imagem Sentinel-2 / Scene Search')
        gl_s = QGridLayout()
        gl_s.setContentsMargins(8, 6, 8, 8)
        gl_s.setSpacing(6)
        gl_s.setColumnStretch(1, 1)

        gl_s.addWidget(QLabel('Coleção / Collection:'), 0, 0)
        self.combo_coll = QComboBox()
        for cid, clabel in _COLLECTIONS:
            self.combo_coll.addItem(clabel, cid)
        gl_s.addWidget(self.combo_coll, 0, 1)

        gl_s.addWidget(QLabel('Data inicial / From:'), 1, 0)
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addDays(-90))
        self.date_from.setDisplayFormat('yyyy-MM-dd')
        gl_s.addWidget(self.date_from, 1, 1)

        gl_s.addWidget(QLabel('Data final / To:'), 2, 0)
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setDisplayFormat('yyyy-MM-dd')
        gl_s.addWidget(self.date_to, 2, 1)

        gl_s.addWidget(QLabel('Nuvem máx. / Max cloud:'), 3, 0)
        self.spin_cloud = QSpinBox()
        self.spin_cloud.setRange(0, 100)
        self.spin_cloud.setValue(20)
        self.spin_cloud.setSuffix(' %')
        gl_s.addWidget(self.spin_cloud, 3, 1)

        btn_search = QPushButton('Buscar Cenas / Search Scenes')
        btn_search.setStyleSheet(
            'QPushButton{background:#0277bd;color:white;border-radius:4px;'
            'border:none;padding:5px 10px;font-weight:bold;}'
            'QPushButton:hover{background:#01579b;}')
        btn_search.clicked.connect(self._on_search)
        gl_s.addWidget(btn_search, 4, 0, 1, 2)

        # Scene list + thumbnail preview side by side
        scene_row = QHBoxLayout()
        scene_row.setContentsMargins(0, 0, 0, 0)
        scene_row.setSpacing(6)

        self.list_scenes = QListWidget()
        self.list_scenes.setMinimumHeight(120)
        self.list_scenes.setMaximumHeight(190)
        self.list_scenes.setToolTip('Selecione uma cena / Select a scene')
        self.list_scenes.currentItemChanged.connect(self._on_scene_selected)
        scene_row.addWidget(self.list_scenes, 1)

        self._thumb_label = QLabel('Sem prévia\nNo preview')
        self._thumb_label.setFixedSize(200, 140)
        self._thumb_label.setAlignment(Qt.AlignCenter)
        self._thumb_label.setWordWrap(True)
        self._thumb_label.setStyleSheet(
            'background:#1a1a1a;border:1px solid #444;border-radius:3px;'
            'color:#888;font-size:9px;')
        scene_row.addWidget(self._thumb_label, 0)

        scene_container = QWidget()
        scene_container.setLayout(scene_row)
        gl_s.addWidget(scene_container, 5, 0, 1, 2)

        self.lbl_status = QLabel('Clique em Buscar para encontrar cenas / Click Search to find scenes')
        self.lbl_status.setStyleSheet('color:#666;font-size:10px;')
        gl_s.addWidget(self.lbl_status, 6, 0, 1, 2)

        grp_search.setLayout(gl_s)
        root.addWidget(grp_search)

        # ── Bandas (colapsável / collapsible) ─────────────────────────────────
        self._btn_bands = QToolButton()
        self._btn_bands.setCheckable(True)
        self._btn_bands.setChecked(False)
        self._btn_bands.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._btn_bands.setSizePolicy(
            self._btn_bands.sizePolicy().horizontalPolicy(),
            self._btn_bands.sizePolicy().verticalPolicy())
        self._btn_bands.setStyleSheet(
            'QToolButton{border:1px solid #bbb;border-radius:3px;padding:3px 6px;'
            'background:#f5f5f5;font-weight:bold;font-size:10px;text-align:left;}'
            'QToolButton:checked{background:#e3f2fd;}')
        self._btn_bands.toggled.connect(self._toggle_bands)
        self._btn_bands.setText('▶  Bandas utilizadas / Bands used')
        root.addWidget(self._btn_bands)

        self._wgt_bands = QWidget()
        bands_grid = QGridLayout(self._wgt_bands)
        bands_grid.setContentsMargins(8, 4, 8, 4)
        bands_grid.setSpacing(3)
        bands_grid.addWidget(QLabel('<b>Variável</b>'), 0, 0)
        bands_grid.addWidget(QLabel('<b>Banda S-2</b>'), 0, 1)
        bands_grid.addWidget(QLabel('<b>Resolução</b>'), 0, 2)
        _band_rows = [
            ('nir',      'B08', '10 m'),
            ('red',      'B04', '10 m'),
            ('green',    'B03', '10 m'),
            ('blue',     'B02', '10 m'),
            ('swir1',    'B11', '20 m'),
            ('swir2',    'B12', '20 m'),
            ('rededge',  'B05', '20 m'),
            ('rededge2', 'B06', '20 m'),
            ('rededge3', 'B07', '20 m'),
            ('nir2',     'B8A', '20 m'),
        ]
        for r, (var, band, res) in enumerate(_band_rows, start=1):
            bands_grid.addWidget(QLabel(var),  r, 0)
            bands_grid.addWidget(QLabel(band), r, 1)
            bands_grid.addWidget(QLabel(res),  r, 2)
        self._wgt_bands.setStyleSheet(
            'QWidget{background:#fafafa;border:1px solid #ddd;border-radius:3px;}'
            'QLabel{border:none;font-size:10px;padding:1px 4px;}')
        self._wgt_bands.setVisible(False)
        root.addWidget(self._wgt_bands)

        # ── Índice ────────────────────────────────────────────────────────────
        grp_idx = QGroupBox('Índice de Vegetação / Vegetation Index')
        gl_i = QGridLayout()
        gl_i.setContentsMargins(8, 6, 8, 8)
        gl_i.setSpacing(6)
        gl_i.setColumnStretch(1, 1)

        gl_i.addWidget(QLabel('Índice / Index:'), 0, 0)
        self.combo_index = QComboBox()
        for key, defn in _INDEX_DEFS.items():
            self.combo_index.addItem(defn['label'], key)
        self.combo_index.currentIndexChanged.connect(self._on_index_changed)
        gl_i.addWidget(self.combo_index, 0, 1)

        self.lbl_formula = QLabel('Fórmula / Formula:')
        self.edit_formula = QLineEdit()
        self.edit_formula.setPlaceholderText('Ex: (nir - red) / (nir + red)')
        self.lbl_hint = QLabel(
            'Variáveis / Variables: nir, red, green, blue, swir1, swir2, '
            'rededge, rededge2, rededge3, nir2  ·  Use np. para funções numpy / for numpy functions')
        self.lbl_hint.setStyleSheet(
            'color:#555;font-size:9px;background:#f5f5f5;border-radius:3px;padding:3px;')
        self.lbl_hint.setWordWrap(True)
        gl_i.addWidget(self.lbl_formula,  1, 0)
        gl_i.addWidget(self.edit_formula, 1, 1)
        gl_i.addWidget(self.lbl_hint,     2, 0, 1, 2)

        grp_idx.setLayout(gl_i)
        root.addWidget(grp_idx)

        # ── Saída ─────────────────────────────────────────────────────────────
        grp_out = QGroupBox('Saída / Output')
        gl_o = QGridLayout()
        gl_o.setContentsMargins(8, 6, 8, 8)
        gl_o.setSpacing(6)
        gl_o.setColumnStretch(1, 1)

        gl_o.addWidget(QLabel('Arquivo de saída / Output file:'), 0, 0)
        row_out = QHBoxLayout()
        row_out.setContentsMargins(0, 0, 0, 0)
        self.edit_output = QLineEdit()
        self.edit_output.setPlaceholderText('(vazio = pasta temporária / empty = temp folder)')
        row_out.addWidget(self.edit_output)
        btn_browse = QPushButton('...')
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._browse_output)
        row_out.addWidget(btn_browse)
        gl_o.addLayout(row_out, 0, 1)

        gl_o.addWidget(QLabel('Nome da camada / Layer name:'), 1, 0)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText('NDVI_Talhao')
        gl_o.addWidget(self.edit_name, 1, 1)

        self.chk_load = QCheckBox('Carregar no QGIS após / Load in QGIS after')
        self.chk_load.setChecked(True)
        self.chk_load.setStyleSheet('font-size:10px;')
        gl_o.addWidget(self.chk_load, 2, 0, 1, 2)

        grp_out.setLayout(gl_o)
        root.addWidget(grp_out)

        # ── Info note ─────────────────────────────────────────────────────────
        lbl_note = QLabel(
            'ℹ  Apenas a região do talhão é lida — sem download da cena completa (COG via vsicurl).\n'
            '   Requer conexão com internet. Planetary Computer: sem autenticação necessária.\n'
            '   Only the field region is read — no full scene download (COG via vsicurl).\n'
            '   Requires internet. Planetary Computer: no authentication needed.')
        lbl_note.setStyleSheet(
            'font-size:9px;color:#555;background:#fffde7;border:1px solid #f9a825;'
            'border-radius:3px;padding:5px;')
        lbl_note.setWordWrap(True)
        root.addWidget(lbl_note)

        # ── Buttons (pinned outside scroll) ───────────────────────────────────
        outer.addWidget(self._sep())
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 6, 12, 12)

        self.btn_run = QPushButton('Gerar Índice / Generate Index')
        self.btn_run.setMinimumHeight(38)
        self.btn_run.setStyleSheet(
            'QPushButton{background:#2e7d32;color:white;font-weight:bold;'
            'font-size:12px;border-radius:5px;border:none;}'
            'QPushButton:hover{background:#1b5e20;}'
            'QPushButton:disabled{background:#4a7a4b;color:#aaa;}')
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)

        btn_close = QPushButton('Fechar / Close')
        btn_close.setMinimumHeight(38)
        btn_close.setStyleSheet(
            'QPushButton{background:#616161;color:white;border:none;border-radius:5px;}'
            'QPushButton:hover{background:#424242;}')
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)

        outer.addLayout(btn_row)

        self._on_index_changed()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _sep(self):
        ln = QFrame()
        ln.setFrameShape(QFrame.HLine)
        ln.setFrameShadow(QFrame.Sunken)
        return ln

    def _toggle_bands(self, checked):
        self._wgt_bands.setVisible(checked)
        self._btn_bands.setText(
            ('▼' if checked else '▶') + '  Bandas utilizadas / Bands used')

    def _on_index_changed(self):
        is_custom = (self.combo_index.currentData() == 'Custom')
        self.lbl_formula.setVisible(is_custom)
        self.edit_formula.setVisible(is_custom)
        self.lbl_hint.setVisible(is_custom)
        # Keep auto-generated name in sync with the selected index
        current  = self.edit_name.text().strip()
        new_key  = self.combo_index.currentData() or ''
        if current and new_key:
            for key in _INDEX_DEFS:
                if re.match(r'^' + re.escape(key) + r'_', current):
                    self.edit_name.setText(new_key + current[len(key):])
                    break

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Salvar índice / Save index', '', 'GeoTIFF (*.tif)')
        if path:
            if not path.lower().endswith('.tif'):
                path += '.tif'
            self.edit_output.setText(path)

    # ── Thumbnail ─────────────────────────────────────────────────────────────

    def _on_scene_selected(self, current, _previous):
        if current is None:
            self._thumb_label.setPixmap(QPixmap())
            self._thumb_label.setText('Sem prévia\nNo preview')
            return

        feature = current.data(Qt.UserRole)
        if feature is None:
            return

        thumb_url = _find_thumbnail_url(feature)
        if not thumb_url:
            self._thumb_label.setPixmap(QPixmap())
            self._thumb_label.setText('Sem prévia\nNo preview')
            return

        self._thumb_label.setText('Carregando…\nLoading…')
        self._thumb_label.setPixmap(QPixmap())

        if self._thumb_fetcher and self._thumb_fetcher.isRunning():
            self._thumb_fetcher.loaded.disconnect()
            self._thumb_fetcher.failed.disconnect()
            self._thumb_fetcher.quit()
            self._thumb_fetcher.wait(1000)

        self._thumb_fetcher = _ThumbFetcher(thumb_url, self)
        self._thumb_fetcher.loaded.connect(self._on_thumb_loaded)
        self._thumb_fetcher.failed.connect(self._on_thumb_failed)
        self._thumb_fetcher.start()

    def _on_thumb_loaded(self, data: bytes):
        px = QPixmap()
        if px.loadFromData(data):
            scaled = px.scaled(
                self._thumb_label.width() - 4,
                self._thumb_label.height() - 4,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self._thumb_label.setPixmap(scaled)
            self._thumb_label.setText('')
        else:
            self._thumb_label.setText('Sem prévia\nNo preview')

    def _on_thumb_failed(self):
        self._thumb_label.setPixmap(QPixmap())
        self._thumb_label.setText('Sem prévia\nNo preview')

    # ── Search ────────────────────────────────────────────────────────────────

    def _active_poly_layer(self):
        """Return (layer, selected_only) from the active QGIS layer, or (None, False)."""
        layer = self.iface.activeLayer()
        if layer is None or not hasattr(layer, 'selectedFeatures'):
            return None, False
        selected_only = layer.selectedFeatureCount() > 0
        return layer, selected_only

    def _on_search(self):
        layer, selected_only = self._active_poly_layer()
        if layer is None:
            QMessageBox.warning(self, 'RTH',
                'Selecione uma camada de polígonos no painel de camadas.\n'
                'Select a polygon layer in the layer panel.')
            return

        self.lbl_active_layer.setText(
            '{}{}'.format(layer.name(),
                          ' ({} selecionado(s) / selected)'.format(layer.selectedFeatureCount())
                          if selected_only else ''))

        bbox      = _bbox_from_layer(layer, selected_only)
        coll_id   = self.combo_coll.currentData()
        date_ini  = self.date_from.date().toString('yyyy-MM-dd')
        date_fim  = self.date_to.date().toString('yyyy-MM-dd')
        cloud_max = self.spin_cloud.value()

        self.list_scenes.clear()
        self.lbl_status.setText('Buscando cenas... / Searching scenes...')
        QApplication.processEvents()

        try:
            features, _ = search_stac(coll_id, bbox, date_ini, date_fim, cloud_max)
        except Exception as e:
            self.lbl_status.setText('Erro / Error: {}'.format(str(e)[:100]))
            QMessageBox.critical(self, 'RTH',
                'Erro ao buscar cenas / Error searching scenes:\n\n{}'.format(str(e)))
            return

        self._features = features

        if not features:
            self.lbl_status.setText(
                'Nenhuma cena encontrada. Tente ampliar o período ou aumentar o limite de nuvens.\n'
                'No scenes found. Try expanding the date range or increasing the cloud limit.')
            return

        for feat in features:
            props     = feat.get('properties', {})
            cloud     = props.get('eo:cloud_cover')
            cloud_str = '{:.1f}%'.format(cloud) if cloud is not None else '?%'
            scene_id  = feat.get('id', 'unknown')
            s_date, mgrs, _suffix = _parse_s2_id(scene_id)
            # Fallback date from datetime property if parse failed
            if not s_date:
                s_date = (props.get('datetime') or '')[:10]
            label = '{}   ☁ {}   {}'.format(s_date, cloud_str, mgrs or scene_id[:20])
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, feat)
            self.list_scenes.addItem(item)

        self.list_scenes.setCurrentRow(0)
        self.lbl_status.setText('{} cena(s) encontrada(s) — selecione uma / scene(s) found — select one'.format(
            len(features)))

        # Auto-fill layer name from first scene: INDEX_mgrs_suffix
        if not self.edit_name.text().strip():
            idx_key = self.combo_index.currentData()
            first_id = features[0].get('id', '')
            _, mgrs0, suffix0 = _parse_s2_id(first_id)
            if suffix0:
                self.edit_name.setText('{}_{}'.format(idx_key, suffix0))
            else:
                dt0 = (features[0].get('properties', {}).get('datetime') or '')[:10].replace('-', '')
                self.edit_name.setText('{}_{}'.format(idx_key, dt0))

    # ── Run / compute ─────────────────────────────────────────────────────────

    def _on_run(self):
        if not _DEPS_OK:
            QMessageBox.critical(self, 'RTH',
                'numpy e/ou gdal não disponíveis.\nnumpy and/or gdal not available.')
            return

        layer, selected_only = self._active_poly_layer()
        if layer is None:
            QMessageBox.warning(self, 'RTH',
                'Selecione uma camada de polígonos na camada ativa.\n'
                'Select a polygon layer as the active layer.')
            return
        self.lbl_active_layer.setText(
            '{}{}'.format(layer.name(),
                          ' ({} selecionado(s) / selected)'.format(layer.selectedFeatureCount())
                          if selected_only else ''))

        sel_item = self.list_scenes.currentItem()
        if sel_item is None:
            QMessageBox.warning(self, 'RTH',
                'Selecione uma cena na lista.\nSelect a scene from the list.')
            return

        feature   = sel_item.data(Qt.UserRole)
        index_key = self.combo_index.currentData()
        defn      = _INDEX_DEFS[index_key]

        if index_key == 'Custom':
            formula = self.edit_formula.text().strip()
            if not formula:
                QMessageBox.warning(self, 'RTH', 'Digite uma fórmula personalizada.\nEnter a custom formula.')
                return
            vmin, vmax = defn['vmin'], defn['vmax']
        else:
            formula    = defn['formula']
            vmin, vmax = defn['vmin'], defn['vmax']

        base_output = self.edit_output.text().strip()
        base_name   = self.edit_name.text().strip()
        scene_id    = feature.get('id', 'scene')
        _, _, suffix0 = _parse_s2_id(scene_id)
        if not suffix0:
            suffix0 = (feature.get('properties', {}).get('datetime') or '')[:10].replace('-', '')

        # Multi-feature mode: one output per selected polygon when > 1 selected
        multi = selected_only and layer.selectedFeatureCount() > 1
        poly_feats  = list(layer.selectedFeatures()) if multi else None
        n_steps     = len(poly_feats) if multi else 1
        layer_crs   = layer.crs()

        progress = QProgressDialog(
            'Calculando {}... / Computing {}...'.format(index_key, index_key),
            None, 0, n_steps, self)
        progress.setWindowTitle('RTH — Análise do Talhão')
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        self.btn_run.setEnabled(False)
        QApplication.processEvents()

        results = []   # list of (result_path, layer_name)
        errors  = []

        try:
            if not multi:
                # Single computation — whole layer or single selected feature
                if base_output:
                    out = base_output if base_output.lower().endswith('.tif') else base_output + '.tif'
                else:
                    out = os.path.join(
                        tempfile.gettempdir(),
                        'rth_{}_{}.tif'.format(index_key, re.sub(r'[^\w]', '_', scene_id[:20])))
                name = base_name or '{}_{}'.format(index_key, suffix0) or index_key
                bbox = _bbox_from_layer(layer, selected_only)
                try:
                    result_path = self._compute(
                        feature, index_key, formula, bbox, out, layer, selected_only)
                    results.append((result_path, name))
                except Exception as e:
                    errors.append(str(e))
                progress.setValue(1)
            else:
                # One output per selected polygon
                for i, pfeat in enumerate(poly_feats):
                    if progress.wasCanceled():
                        break
                    feat_sfx = '_{}'.format(i + 1)
                    if base_output:
                        base = base_output[:-4] if base_output.lower().endswith('.tif') else base_output
                        out = base + feat_sfx + '.tif'
                    else:
                        out = os.path.join(
                            tempfile.gettempdir(),
                            'rth_{}_{}_{}.tif'.format(
                                index_key, re.sub(r'[^\w]', '_', scene_id[:20]), i + 1))
                    name = (base_name + feat_sfx) if base_name else \
                           '{}_{}{}' .format(index_key, suffix0, feat_sfx)
                    geom = pfeat.geometry()
                    bbox = _bbox_from_geometry(geom, layer_crs)
                    try:
                        result_path = self._compute(
                            feature, index_key, formula, bbox, out,
                            single_geom=geom, single_geom_crs=layer_crs)
                        results.append((result_path, name))
                    except Exception as e:
                        errors.append('Polígono {}: {}'.format(i + 1, str(e)))
                    progress.setValue(i + 1)
                    QApplication.processEvents()
        finally:
            progress.close()
            self.btn_run.setEnabled(True)

        # Load results into QGIS
        load_ok = 0
        load_fail = []
        if self.chk_load.isChecked():
            for result_path, layer_name in results:
                rlayer = QgsRasterLayer(result_path, layer_name)
                if rlayer.isValid():
                    QgsProject.instance().addMapLayer(rlayer)
                    collapse_layer(rlayer)
                    # Use actual computed min/max so the color ramp fits the data
                    stats = rlayer.dataProvider().bandStatistics(
                        1,
                        QgsRasterBandStats.Min | QgsRasterBandStats.Max,
                        rlayer.extent(), 0)
                    r_min = stats.minimumValue
                    r_max = stats.maximumValue
                    if r_min < r_max:
                        _apply_pseudocolor(rlayer, r_min, r_max)
                    else:
                        _apply_pseudocolor(rlayer, vmin, vmax)
                    load_ok += 1
                else:
                    load_fail.append(result_path)
            if load_ok:
                self.iface.messageBar().pushMessage(
                    'RTH Talhão',
                    '{} {} gerado(s) e carregado(s) / generated and loaded'.format(load_ok, index_key),
                    level=Qgis.MessageLevel.Success, duration=6)
            for fp in load_fail:
                errors.append('Falha ao carregar / Failed to load QGIS layer:\n{}'.format(fp))
        else:
            for result_path, _ in results:
                self.iface.messageBar().pushMessage(
                    'RTH Talhão',
                    '{} salvo / saved: {}'.format(index_key, result_path),
                    level=Qgis.MessageLevel.Info, duration=5)

        if errors:
            QMessageBox.critical(self, 'RTH — Análise do Talhão',
                'Erro(s) / Error(s):\n\n' + '\n'.join(errors[:5]))

    def _compute(self, feature, index_key, formula, bbox_wgs84, output_path,
                 layer=None, selected_only=False,
                 single_geom=None, single_geom_crs=None):
        """Clip Sentinel-2 bands to bbox, mask to polygon shape, evaluate formula.

        Pass single_geom (QgsGeometry) + single_geom_crs to mask a single feature
        without going through the full layer iteration.
        """
        gdal = _init_gdal()
        if gdal is None:
            raise RuntimeError('GDAL não disponível / GDAL not available')

        target_crs = _scene_utm(feature)

        # Build cutline mask from the field polygon so pixels outside are nodata
        cutline_path = None
        if single_geom is not None:
            try:
                target = QgsCoordinateReferenceSystem(target_crs)
                src    = single_geom_crs or QgsCoordinateReferenceSystem('EPSG:4326')
                from qgis.core import QgsGeometry as _QgsGeometry
                g = _QgsGeometry(single_geom)   # copy
                if src != target:
                    xf = QgsCoordinateTransform(src, target, QgsProject.instance())
                    g.transform(xf)
                if not g.isEmpty():
                    cutline_path = _write_cutline(g.asWkt(), target_crs)
            except Exception:
                cutline_path = None
        elif layer is not None:
            try:
                poly_wkt = _poly_wkt_in_crs(layer, selected_only, target_crs)
                if poly_wkt:
                    cutline_path = _write_cutline(poly_wkt, target_crs)
            except Exception:
                cutline_path = None   # mask unavailable — fall back to bbox only

        # Determine which band variables the formula needs
        if index_key == 'Custom':
            needed = [v for v in _BAND_VARS if re.search(r'\b' + v + r'\b', formula)]
            if not needed:
                raise ValueError(
                    'Nenhuma variável de banda reconhecida na fórmula.\n'
                    'No recognized band variable found in formula.\n'
                    'Use: {}'.format(', '.join(_BAND_VARS.keys())))
        else:
            needed = _INDEX_DEFS[index_key]['vars']

        # Clip each band from the remote COG (with polygon mask if available)
        datasets  = {}
        ref_gt    = None
        ref_proj  = None
        ref_shape = None

        try:
            for var in needed:
                QApplication.processEvents()
                ds = _clip_band(feature, _BAND_VARS[var], bbox_wgs84, gdal,
                                target_crs, cutline_path)
                if ds is None:
                    raise ValueError(
                        'Banda {} ({}) não encontrada na cena selecionada.\n'
                        'Band {} ({}) not found in the selected scene.\n'
                        'A cena pode não cobrir a área do talhão ou usar nomes de asset diferentes.\n'
                        'The scene may not cover the field area or use different asset names.'.format(
                            _BAND_VARS[var], var, _BAND_VARS[var], var))
                if ref_gt is None:
                    ref_gt    = ds.GetGeoTransform()
                    ref_proj  = ds.GetProjection()
                    ref_shape = (ds.RasterYSize, ds.RasterXSize)
                datasets[var] = ds

            # Read as normalised float32 arrays, resample if shapes differ (e.g. 20 m bands)
            arrays = {}
            for var, ds in datasets.items():
                arr = _ds_to_array(ds)
                arrays[var] = _match_shape(arr, ref_shape)

            # Evaluate index formula
            result = _eval_formula(formula, arrays)

            # Write result
            _write_tiff(result, ref_gt, ref_proj, output_path)

        finally:
            for ds in datasets.values():
                del ds
            # Clean up temp cutline file
            if cutline_path and os.path.exists(cutline_path):
                try:
                    os.remove(cutline_path)
                except OSError:
                    pass

        return output_path

    def closeEvent(self, event):
        if self._thumb_fetcher and self._thumb_fetcher.isRunning():
            self._thumb_fetcher.quit()
            self._thumb_fetcher.wait(2000)
        super().closeEvent(event)


# ── Tool class ────────────────────────────────────────────────────────────────

class FieldAnalysisTool:

    def __init__(self, iface):
        self.iface   = iface
        self._dialog = None

    def run(self):
        if self._dialog is None or not self._dialog.isVisible():
            self._dialog = FieldAnalysisDialog(self.iface)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
