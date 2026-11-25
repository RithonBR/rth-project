# -*- coding: utf-8 -*-
import os
import datetime
import tempfile

from qgis.PyQt.QtCore import (
    Qt, QDate, QThread, pyqtSignal, QThreadPool
)
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QDateEdit,
    QFrame, QScrollArea, QWidget, QCheckBox,
    QRadioButton, QButtonGroup, QSizePolicy, QApplication,
    QTabWidget
)
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsGeometry, QgsRasterLayer
)

# ── Compat Qt5/Qt6: QFrame enums movidos para sub-namespaces no Qt6 ──────────
try:
    _FRAME_STYLED  = QFrame.Shape.StyledPanel
    _FRAME_HLINE   = QFrame.Shape.HLine
    _FRAME_VLINE   = QFrame.Shape.VLine
    _FRAME_NOFRAME = QFrame.Shape.NoFrame
    _FRAME_SUNKEN  = QFrame.Shadow.Sunken
    _FRAME_RAISED  = QFrame.Shadow.Raised
except AttributeError:
    _FRAME_STYLED  = QFrame.StyledPanel
    _FRAME_HLINE   = QFrame.HLine
    _FRAME_VLINE   = QFrame.VLine
    _FRAME_NOFRAME = QFrame.NoFrame
    _FRAME_SUNKEN  = QFrame.Sunken
    _FRAME_RAISED  = QFrame.Raised

# ── Constantes de coleção ─────────────────────────────────────────────────────
_COL_S2_BDC = 'S2_L2A-1'
_COL_LS_BDC = 'landsat-2'
_COL_S2_PC  = 'sentinel-2-l2a'
_COL_LS_PC  = 'landsat-c2-l2'

_BANDS = {
    'RGB': {
        _COL_S2_BDC: ('B04', 'B03', 'B02'),
        _COL_LS_BDC: ('red', 'green', 'blue'),
        _COL_S2_PC:  ('B04', 'B03', 'B02'),
        _COL_LS_PC:  ('red', 'green', 'blue'),
    },
    'NIR_SWIR_RED': {
        _COL_S2_BDC: ('B08', 'B11', 'B04'),
        _COL_LS_BDC: ('nir08', 'swir16', 'red'),
        _COL_S2_PC:  ('B08', 'B11', 'B04'),
        _COL_LS_PC:  ('nir08', 'swir16', 'red'),
    },
}

_MARCOS = [
    ('Brasil — 31/07/2019', '2019-07-31'),
    ('EUDR — 31/12/2020',   '2020-12-31'),
    ('Personalizado / Custom', None),
]

_SLOT_LABELS = [
    '1 — Histórico (5 anos antes do marco) / Historical (5 yr before cutoff)',
    '2 — Antes do Marco / Before Cutoff',
    '3 — Pré-Desmatamento (1 ano antes) / Pre-Deforestation (1 yr before)',
    '4 — Pós-Marco / After Cutoff',
    '5 — Mais Recente / Latest Available',
]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _bbox_from_layer(layer):
    """Retorna [minx, miny, maxx, maxy] em WGS84 da seleção ou da camada inteira.
    Returns [minx, miny, maxx, maxy] in WGS84 from selection or whole layer."""
    wgs84    = QgsCoordinateReferenceSystem('EPSG:4326')
    selected = layer.selectedFeatures()
    if selected:
        from qgis.core import QgsGeometry
        geoms = [f.geometry() for f in selected
                 if f.geometry() and not f.geometry().isNull()]
        if geoms:
            union = geoms[0]
            for g in geoms[1:]:
                union = union.combine(g)
            ext = union.boundingBox()
        else:
            ext = layer.extent()
    else:
        ext = layer.extent()

    src_crs = layer.crs()
    if src_crs.authid() != 'EPSG:4326':
        t   = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
        ext = t.transformBoundingBox(ext)

    # Margem proporcional de 8% da extensão (mínimo 0.001°) — enquadra o polígono com zoom
    # Proportional 8% margin (minimum 0.001°) — frames the polygon with zoom
    dx       = ext.xMaximum() - ext.xMinimum()
    dy       = ext.yMaximum() - ext.yMinimum()
    margin_x = max(dx * 0.08, 0.001)
    margin_y = max(dy * 0.08, 0.001)
    return [
        round(ext.xMinimum() - margin_x, 6),
        round(ext.yMinimum() - margin_y, 6),
        round(ext.xMaximum() + margin_x, 6),
        round(ext.yMaximum() + margin_y, 6),
    ]


def _geom_to_rings_wgs84(layer):
    """Extrai anéis WGS84 (exterior) das feições selecionadas na camada.
    Extracts WGS84 exterior rings from selected features in the layer."""
    selected = layer.selectedFeatures()
    if not selected:
        return None
    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    t     = QgsCoordinateTransform(layer.crs(), wgs84, QgsProject.instance())
    rings = []
    for feat in selected:
        geom = QgsGeometry(feat.geometry())
        if not geom or geom.isNull():
            continue
        geom.transform(t)
        if geom.isMultipart():
            for poly in geom.asMultiPolygon():
                for ring in poly:
                    rings.append([(pt.x(), pt.y()) for pt in ring])
        else:
            for ring in geom.asPolygon():
                rings.append([(pt.x(), pt.y()) for pt in ring])
    return rings or None


def _date_str(d):
    return d.toString('yyyy-MM-dd')


def _add_months(date_str, months):
    dt    = datetime.date.fromisoformat(date_str)
    year  = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    import calendar
    day   = min(dt.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day).isoformat()


def _add_days(date_str, days):
    return (datetime.date.fromisoformat(date_str)
            + datetime.timedelta(days=days)).isoformat()


def _today():
    return datetime.date.today().isoformat()


def _search_slot(bbox, slot_idx, marco_str, deforest_str, cloud_max, use_brazil):
    """Faz a busca STAC para um dos 5 slots.
    Makes the STAC search for one of the 5 slots."""
    from core.rth_stac_api import search_stac, search_stac_pc

    s2_col = _COL_S2_BDC if use_brazil else _COL_S2_PC
    ls_col = _COL_LS_BDC if use_brazil else _COL_LS_PC
    today  = _today()

    if slot_idx == 0:
        center   = _add_months(marco_str, -60)
        d_ini    = _add_months(center, -4)
        d_fim    = _add_months(center,  4)
        sort_asc = False
    elif slot_idx == 1:
        d_ini    = _add_months(marco_str, -12)
        d_fim    = _add_days(marco_str, -1)
        sort_asc = False
    elif slot_idx == 2:
        center   = _add_months(deforest_str, -12)
        d_ini    = _add_months(center, -4)
        d_fim    = _add_months(center,  4)
        sort_asc = False
    elif slot_idx == 3:
        d_ini    = _add_days(marco_str, 1)
        d_fim    = _add_months(marco_str, 12)
        sort_asc = True
    else:
        d_ini    = _add_months(today, -6)
        d_fim    = today
        sort_asc = False

    def _coverage_ratio(feature):
        # Fração [0..1] do bbox da AOI coberta pela geometria real da cena.
        # Sentinel-2 no limite do swath orbital gera imagens com faixa NoData
        # que renderiza como preto; selecionar a cena com maior cobertura
        # evita esse artefato sem depender de nenhum pacote externo (usa QGIS).
        try:
            from qgis.core import QgsGeometry, QgsRectangle, QgsPointXY
            geom_json = feature.get('geometry') or {}
            gtype     = geom_json.get('type', '')
            coords    = geom_json.get('coordinates', [])
            if gtype == 'Polygon':
                rings      = [[QgsPointXY(c[0], c[1]) for c in ring] for ring in coords]
                scene_geom = QgsGeometry.fromPolygonXY(rings)
            elif gtype == 'MultiPolygon':
                polys      = [[[QgsPointXY(c[0], c[1]) for c in ring] for ring in poly]
                               for poly in coords]
                scene_geom = QgsGeometry.fromMultiPolygonXY(polys)
            else:
                return 0.5
            if not scene_geom or scene_geom.isEmpty():
                return 0.5
            minx, miny, maxx, maxy = bbox
            aoi_geom = QgsGeometry.fromRect(QgsRectangle(minx, miny, maxx, maxy))
            inter    = scene_geom.intersection(aoi_geom)
            if not inter or inter.isEmpty():
                return 0.0
            aoi_area = aoi_geom.area()
            return min(1.0, inter.area() / aoi_area) if aoi_area > 0 else 0.5
        except Exception:
            return 0.5

    def _pick(features, asc):
        if not features:
            return None
        if asc:
            features = sorted(
                features,
                key=lambda f: f.get('properties', {}).get('datetime', ''))

        def _score(f):
            cov   = _coverage_ratio(f)
            cloud = float((f.get('properties') or {}).get('eo:cloud_cover') or 0)
            return (cov, -cloud)

        return max(features, key=_score)

    _MIN_COV = 0.40  # cobertura mínima da AOI para aceitar a cena Sentinel-2

    for col in (s2_col, ls_col):
        try:
            if use_brazil:
                feats, _ = search_stac(col, bbox, d_ini, d_fim, cloud_max)
            else:
                feats, _, _, _ = search_stac_pc(col, bbox, d_ini, d_fim, cloud_max)
        except Exception:
            feats = []

        feat = _pick(feats, sort_asc)
        if feat is None:
            continue
        # Para Sentinel-2 rejeita cenas com cobertura insuficiente da AOI e
        # tenta Landsat (swath mais largo, menos suscetível a OP cortada).
        # Para Landsat aceita qualquer cobertura — é o último recurso.
        if col == ls_col or _coverage_ratio(feat) >= _MIN_COV:
            return feat, col

    return None, None


# ──────────────────────────────────────────────────────────────────────────────
# Thread de busca sequencial (5 slots)
# Sequential search thread (5 slots)
# ──────────────────────────────────────────────────────────────────────────────

class _SlotSearchThread(QThread):
    slot_done  = pyqtSignal(int, object, object)  # idx, feature|None, col_id|None
    all_done   = pyqtSignal()
    slot_error = pyqtSignal(int, str)

    def __init__(self, bbox, marco_str, deforest_str, cloud_max, use_brazil, parent=None):
        super().__init__(parent)
        self._bbox       = bbox
        self._marco      = marco_str
        self._deforest   = deforest_str
        self._cloud_max  = cloud_max
        self._use_brazil = use_brazil
        self._cancelled  = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for i in range(5):
            if self._cancelled:
                break
            try:
                feat, col = _search_slot(
                    self._bbox, i, self._marco, self._deforest,
                    self._cloud_max, self._use_brazil)
                self.slot_done.emit(i, feat, col)
            except Exception as e:
                self.slot_error.emit(i, str(e))
        self.all_done.emit()


# ──────────────────────────────────────────────────────────────────────────────
# Fallback: busca a mesma cena Sentinel-2 no Element84 quando PC falha
# Fallback: search same Sentinel-2 scene on Element84 when PC fails
# ──────────────────────────────────────────────────────────────────────────────

class _PcFallbackThread(QThread):
    """Três tentativas em cascata quando PC falha:
      1. Busca no Element84 por ID exato
      2. Busca no Element84 por bbox + data (filtra pelo tile MGRS)
      3. Constrói feature sintético com URLs S3 públicas do bucket sentinel-cogs

    Three cascading attempts when PC fails:
      1. Element84 search by exact scene ID
      2. Element84 search by bbox + date (filtered by MGRS tile)
      3. Build synthetic feature with public S3 URLs from sentinel-cogs bucket
    """

    found     = pyqtSignal(object, str, str)  # aws_feature, col_id, comp_key
    not_found = pyqtSignal(str, str, str)     # reason, col_id, comp_key

    _E84_SEARCH = 'https://earth-search.aws.element84.com/v1/search'

    def __init__(self, feature, col_id, comp_key, parent=None):
        super().__init__(parent)
        self._feature  = feature
        self._scene_id = feature.get('id', '')
        self._col_id   = col_id
        self._comp_key = comp_key

    # ── Tentativa 1: busca por ID exato ──────────────────────────────────────
    def _search_by_id(self):
        import json, urllib.request
        payload = json.dumps({
            'collections': ['sentinel-2-l2a'],
            'ids':         [self._scene_id],
            'limit':       1,
        }).encode('utf-8')
        req = urllib.request.Request(
            self._E84_SEARCH, data=payload,
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            method='POST')
        if not req.full_url.startswith(('https://', 'http://')):
            return None
        with urllib.request.urlopen(req, timeout=20) as resp:  # nosec B310
            feats = json.loads(resp.read().decode('utf-8')).get('features', [])
        return feats[0] if feats else None

    # ── Tentativa 2: busca por bbox + data, filtra pelo tile MGRS ────────────
    def _search_by_location(self):
        import json, urllib.request
        from datetime import date as _date, timedelta

        bbox   = self._feature.get('bbox', [])
        dt_str = self._feature.get('properties', {}).get('datetime', '')[:10]
        if not bbox or len(bbox) < 4 or not dt_str:
            return None

        # Extrai tile MGRS do ID (ex: T48QTD de S2B_MSIL2A_..._T48QTD_...)
        # Extract MGRS tile from ID (e.g. T48QTD from S2B_MSIL2A_..._T48QTD_...)
        tile = None
        for part in self._scene_id.split('_'):
            if len(part) == 6 and part.startswith('T') and part[1:3].isdigit():
                tile = part
                break

        try:
            d = _date(int(dt_str[:4]), int(dt_str[5:7]), int(dt_str[8:10]))
            date_range = '{}/{}'.format(
                (d - timedelta(days=1)).isoformat(),
                (d + timedelta(days=1)).isoformat())
        except (ValueError, IndexError):
            return None

        payload = json.dumps({
            'collections': ['sentinel-2-l2a'],
            'bbox':        bbox,
            'datetime':    date_range,
            'limit':       10,
        }).encode('utf-8')
        req = urllib.request.Request(
            self._E84_SEARCH, data=payload,
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            method='POST')
        if not req.full_url.startswith(('https://', 'http://')):
            return None
        with urllib.request.urlopen(req, timeout=20) as resp:  # nosec B310
            feats = json.loads(resp.read().decode('utf-8')).get('features', [])

        if tile:
            # Prefere cena do mesmo tile / Prefer scene from the same tile
            for f in feats:
                if tile in f.get('id', ''):
                    return f
        return feats[0] if feats else None

    # ── Tentativa 3: feature sintético com S3 direto ─────────────────────────
    def _build_s3_feature(self):
        """Constrói URLs S3 públicas do bucket sentinel-cogs a partir do ID.
        Builds public S3 URLs from the sentinel-cogs bucket using the scene ID.

        Estrutura: s3://sentinel-cogs/sentinel-s2-l2a-cogs/{zone}/{lat}/{grid}/{year}/{month}/{scene_id}/{band}.tif
        """
        # Parseia o ID: S2B_MSIL2A_20250209T033819_R061_T48QTD_20250209T071508
        # Parse ID:     S2B_MSIL2A_20250209T033819_R061_T48QTD_20250209T071508
        parts = self._scene_id.split('_')
        mgrs_tile = None
        dt_part   = None
        for part in parts:
            if len(part) == 6 and part.startswith('T') and part[1:3].isdigit():
                mgrs_tile = part                         # T48QTD
            if len(part) == 15 and part[0].isdigit() and 'T' in part:
                dt_part = part                           # 20250209T033819

        if not mgrs_tile or not dt_part:
            return None

        zone     = mgrs_tile[1:3]           # '48'
        lat_band = mgrs_tile[3]             # 'Q'
        grid_sq  = mgrs_tile[4:6]           # 'TD'
        year     = dt_part[:4]              # '2025'
        month    = str(int(dt_part[4:6]))   # '2'  (sem zero à esquerda / no leading zero)

        base = 's3://sentinel-cogs/sentinel-s2-l2a-cogs/{}/{}/{}/{}/{}/{}'.format(
            zone, lat_band, grid_sq, year, month, self._scene_id)

        bands  = ['B01', 'B02', 'B03', 'B04', 'B05', 'B06', 'B07',
                  'B08', 'B8A', 'B09', 'B11', 'B12', 'SCL']
        assets = {b: {'href': '{}/{}.tif'.format(base, b)} for b in bands}

        return {
            'id':         self._scene_id,
            'type':       'Feature',
            'bbox':       self._feature.get('bbox'),
            'geometry':   self._feature.get('geometry'),
            'properties': self._feature.get('properties', {}),
            'assets':     assets,
        }

    def run(self):
        # 1. ID exato no E84 / Exact ID on E84
        try:
            feat = self._search_by_id()
            if feat:
                self.found.emit(feat, self._col_id, self._comp_key)
                return
        except Exception:
            pass

        # 2. Bbox + data no E84 / Bbox + date on E84
        try:
            feat = self._search_by_location()
            if feat:
                self.found.emit(feat, self._col_id, self._comp_key)
                return
        except Exception:
            pass

        # 3. Feature sintético S3 / Synthetic S3 feature
        feat = self._build_s3_feature()
        if feat:
            self.found.emit(feat, self._col_id, self._comp_key)
            return

        self.not_found.emit(
            'Cena indisponível no Element84 e no S3 direto / '
            'Scene unavailable on Element84 and direct S3',
            self._col_id, self._comp_key)


# ──────────────────────────────────────────────────────────────────────────────
# Cartão de slot (uma composição por instância)
# Slot card (one composition per instance)
# ──────────────────────────────────────────────────────────────────────────────

class _SlotCard(QFrame):
    """Cartão de um slot para uma composição específica.
    Card for a slot of a specific composition."""

    # Sinal emite feature, col_id, comp_key (uma composição, não lista)
    download_requested = pyqtSignal(object, object, str)

    def __init__(self, slot_idx, label_text, comp_key, parent=None):
        super().__init__(parent)
        self._slot_idx    = slot_idx
        self._comp_key    = comp_key
        self._feature     = None
        self._col_id      = None
        self._cancel_flag = [False]

        self.setFrameShape(_FRAME_STYLED)
        self.setFrameShadow(_FRAME_RAISED)
        self.setStyleSheet(
            'QFrame{background:#f8f9fa;border:1px solid #dadce0;border-radius:6px;}')
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(10, 8, 10, 8)

        lbl_title = QLabel(label_text)
        f = QFont()
        f.setBold(True)
        f.setPointSize(9)
        lbl_title.setFont(f)
        lbl_title.setWordWrap(True)
        lbl_title.setStyleSheet('color:#202124; background:transparent; border:none;')
        root.addWidget(lbl_title)

        row = QHBoxLayout()
        row.setSpacing(10)

        # Thumbnail: mostra a região buscada (recortada no bbox)
        # Thumbnail: shows the searched region (clipped to bbox)
        self._thumb = QLabel()
        self._thumb.setFixedSize(120, 90)
        self._thumb.setAlignment(Qt.AlignCenter)
        self._thumb.setStyleSheet(
            'background:#e8eaed; border:1px solid #bdc1c6; border-radius:4px;')
        self._thumb.setText('—')
        row.addWidget(self._thumb)

        info_col = QVBoxLayout()
        info_col.setSpacing(4)

        self._lbl_info = QLabel('—')
        self._lbl_info.setWordWrap(True)
        self._lbl_info.setStyleSheet(
            'font-size:10px; color:#5f6368; background:transparent; border:none;')
        info_col.addWidget(self._lbl_info)

        self._lbl_sat = QLabel('')
        self._lbl_sat.setStyleSheet(
            'font-size:10px; font-weight:bold; color:#1a73e8;'
            'background:transparent; border:none;')
        info_col.addWidget(self._lbl_sat)

        info_col.addStretch()

        self._btn_dl = QPushButton('⬇  Baixar / Download')
        self._btn_dl.setMinimumHeight(30)
        self._btn_dl.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-size:11px;'
            'font-weight:bold;border-radius:5px;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        self._btn_dl.setEnabled(False)
        self._btn_dl.clicked.connect(self._on_download)
        info_col.addWidget(self._btn_dl)

        row.addLayout(info_col)
        root.addLayout(row)

    def set_searching(self):
        self._thumb.setText('⏳')
        self._lbl_info.setText('Buscando... / Searching...')
        self._lbl_sat.setText('')
        self._btn_dl.setEnabled(False)

    def set_result(self, feature, col_id, aoi_bbox, poly_rings=None):
        """Preenche o cartão com o resultado e carrega thumbnail recortado no AOI.
        Se poly_rings fornecido, sobrepõe o contorno do polígono sobre o thumbnail.
        Fills the card with the result and loads AOI-clipped thumbnail.
        If poly_rings provided, overlays polygon outline on the thumbnail."""
        self._cancel_flag = [False]
        self._feature     = feature
        self._col_id      = col_id

        if feature is None:
            self._thumb.setText('✗')
            self._lbl_info.setText('Nenhuma imagem encontrada. / No image found.')
            self._lbl_sat.setText('')
            self._btn_dl.setEnabled(False)
            return

        props    = feature.get('properties', {})
        dt_str   = props.get('datetime', '')[:10]
        clouds   = props.get('eo:cloud_cover')
        clouds_s = '{:.0f}%'.format(clouds) if clouds is not None else '—'

        sat_label = ('Sentinel-2'
                     if ('sentinel-2' in col_id.lower() or col_id.startswith('S2'))
                     else 'Landsat')

        self._lbl_info.setText(
            'Data / Date: {}\nNuvens / Clouds: {}'.format(dt_str, clouds_s))
        self._lbl_sat.setText(sat_label)
        self._btn_dl.setEnabled(True)

        # Thumbnail recortado no bbox da AOI com bandas da composição correta,
        # mais o contorno do polígono selecionado sobreposto.
        # AOI-bbox clipped thumbnail using bands of the correct composition,
        # plus the selected polygon outline overlaid.
        band_tuple = _BANDS.get(self._comp_key, {}).get(col_id)
        if band_tuple and aoi_bbox:
            try:
                from core.rth_aoi_thumb import load_aoi_thumb_async
                load_aoi_thumb_async(
                    feature, col_id, band_tuple, aoi_bbox,
                    self._thumb, self._cancel_flag, w=120, h=90,
                    overlay_rings=poly_rings)
                return
            except Exception:
                pass
        # Fallback: thumbnail padrão do STAC / Fallback: default STAC thumbnail
        from core.rth_thumbnail import load_thumbnail_async
        load_thumbnail_async(feature, self._thumb, self._cancel_flag)

    def set_error(self, msg):
        self._thumb.setText('✗')
        self._lbl_info.setText('Erro: {} / Error: {}'.format(msg, msg))
        self._lbl_sat.setText('')
        self._btn_dl.setEnabled(False)

    def cancel_thumb(self):
        self._cancel_flag[0] = True

    def _on_download(self):
        if self._feature is not None and self._col_id is not None:
            self.download_requested.emit(self._feature, self._col_id, self._comp_key)


# ──────────────────────────────────────────────────────────────────────────────
# Dialog principal
# Main dialog
# ──────────────────────────────────────────────────────────────────────────────

class DeforestationMonitorDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface                   = iface
        self._thread                 = None
        self._cards_rgb              = []
        self._cards_nir              = []
        self._last_bbox              = None
        self._poly_rings             = None   # anéis WGS84 do polígono selecionado / WGS84 rings of selected polygon
        self._connected_layer        = None   # camada com sinal selectionChanged conectado / layer with selectionChanged connected
        self._layer_signals_connected = False  # flag de conexão do sinal currentLayerChanged
        self._output_dir             = tempfile.gettempdir()
        self._dl_download_rows       = []     # linhas de download na aba Downloads / download rows in the Downloads tab
        self._dl_threads             = []     # referências às threads ativas (evita GC) / active thread references (avoid GC)
        self._fallback_threads       = []     # threads de fallback PC→E84 (evita GC) / PC→E84 fallback threads (avoid GC)
        self._build_ui()

    # ── Construção da UI ──────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle('RTH Monitor de Desmatamento / Deforestation Monitor')
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint |
            Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint
        )
        self.setMinimumSize(860, 560)

        root = QHBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Painel esquerdo: configurações (fundo escuro) ──────────────────────
        left = QWidget()
        left.setFixedWidth(290)
        left.setObjectName('leftPanel')
        # Fundo escuro; QLabel/RadioButton/CheckBox herdam a cor via seletor CSS
        # Dark background; QLabel/RadioButton/CheckBox inherit colour via CSS selector
        left.setStyleSheet("""
            #leftPanel { background: #3d4045; }
            #leftPanel QLabel {
                color: #d4d6d9; background: transparent; border: none;
            }
            #leftPanel QRadioButton { color: #d4d6d9; background: transparent; }
            #leftPanel QCheckBox    { color: #d4d6d9; background: transparent; }
        """)

        self._left_layout = QVBoxLayout(left)
        self._left_layout.setSpacing(6)
        self._left_layout.setContentsMargins(14, 14, 14, 14)
        self._root = self._left_layout  # _sep() usa esta referência

        lbl_title = QLabel('Monitor de Desmatamento\n/ Deforestation Monitor')
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet(
            'font-size:13px; font-weight:bold;'
            'color:#e8eaed; background:transparent; border:none;')
        self._left_layout.addWidget(lbl_title)

        self._sep()

        # ── Campos em layout vertical (label acima, widget abaixo) ────────────
        # Vertical field layout: label on top, widget below

        def _flabel(text):
            """Label de campo em estilo discreto / Subtle field label."""
            lbl = QLabel(text)
            lbl.setStyleSheet(
                'font-size:10px; color:#9aa0a6;'
                'background:transparent; border:none;')
            return lbl

        # Localização: fixo Brasil/INPE — PC removido a pedido
        # Location: fixed to Brazil/INPE — PC removed on request
        lbl_loc = _flabel('Localização / Location')
        self._left_layout.addWidget(lbl_loc)
        self._rb_brazil = QRadioButton('Brasil  (INPE/BDC)')
        self._rb_brazil.setChecked(True)
        self._rb_global = QRadioButton('Global  (PC)  —  Em breve / Coming soon')
        self._rb_global.setEnabled(False)
        self._rb_global.setStyleSheet('color: #888888; font-style: italic;')
        self._loc_group = QButtonGroup(self)
        self._loc_group.addButton(self._rb_brazil, 0)
        self._loc_group.addButton(self._rb_global, 1)
        self._left_layout.addWidget(self._rb_brazil)
        self._left_layout.addWidget(self._rb_global)

        # Marco temporal
        self._left_layout.addWidget(_flabel('Marco Temporal / Cutoff Date'))
        self._combo_marco = QComboBox()
        self._combo_marco.setMinimumHeight(28)
        for lbl_text, _ in _MARCOS:
            self._combo_marco.addItem(lbl_text)
        self._combo_marco.currentIndexChanged.connect(self._on_marco_changed)
        self._left_layout.addWidget(self._combo_marco)

        # Data personalizada (oculta por padrão / hidden by default)
        self._lbl_marco_custom = _flabel('Data Personalizada / Custom Date')
        self._lbl_marco_custom.setVisible(False)
        self._left_layout.addWidget(self._lbl_marco_custom)
        self._date_marco_custom = QDateEdit()
        self._date_marco_custom.setDisplayFormat('dd/MM/yyyy')
        self._date_marco_custom.setCalendarPopup(True)
        self._date_marco_custom.setDate(QDate(2019, 7, 31))
        self._date_marco_custom.setMinimumHeight(28)
        self._date_marco_custom.setVisible(False)
        self._left_layout.addWidget(self._date_marco_custom)

        # Data do desmatamento
        self._left_layout.addWidget(_flabel('Data do Desmatamento / Deforestation Date'))
        self._date_deforest = QDateEdit()
        self._date_deforest.setDisplayFormat('dd/MM/yyyy')
        self._date_deforest.setCalendarPopup(True)
        self._date_deforest.setDate(QDate.currentDate().addYears(-1))
        self._date_deforest.setMinimumHeight(28)
        self._left_layout.addWidget(self._date_deforest)

        # PRODES — lê a data do desmatamento direto do atributo da camada selecionada
        # PRODES — reads deforestation date directly from the selected feature's attribute
        self._chk_prodes = QCheckBox('Camada / Layer')
        self._chk_prodes.setChecked(False)
        self._chk_prodes.toggled.connect(self._on_prodes_toggled)
        self._left_layout.addWidget(self._chk_prodes)

        self._lbl_prodes_col = _flabel('Coluna de Data / Date Column')
        self._lbl_prodes_col.setVisible(False)
        self._left_layout.addWidget(self._lbl_prodes_col)

        self._combo_prodes_col = QComboBox()
        self._combo_prodes_col.setMinimumHeight(28)
        self._combo_prodes_col.setVisible(False)
        self._left_layout.addWidget(self._combo_prodes_col)

        # Composição
        self._left_layout.addWidget(_flabel('Composição / Composition'))
        comp_row = QHBoxLayout()
        comp_row.setSpacing(6)
        self._chk_rgb      = QCheckBox('RGB')
        self._chk_nir_swir = QCheckBox('NIR-SWIR-RED')
        self._chk_rgb.setChecked(True)
        self._chk_rgb.stateChanged.connect(self._on_comp_changed)
        self._chk_nir_swir.stateChanged.connect(self._on_comp_changed)
        comp_row.addWidget(self._chk_rgb)
        comp_row.addWidget(self._chk_nir_swir)
        comp_row.addStretch()
        self._left_layout.addLayout(comp_row)

        # Filtro de nuvens
        self._left_layout.addWidget(_flabel('Filtro de Nuvens / Cloud Filter'))
        self._spin_cloud = QSpinBox()
        self._spin_cloud.setMinimum(0)
        self._spin_cloud.setMaximum(100)
        self._spin_cloud.setValue(30)
        self._spin_cloud.setSuffix('  %')
        self._spin_cloud.setMinimumHeight(28)
        self._left_layout.addWidget(self._spin_cloud)

        self._sep()

        self._lbl_layer = QLabel('Camada ativa: — / Active layer: —')
        self._lbl_layer.setStyleSheet(
            'font-size:10px; color:#9aa0a6; background:transparent; border:none;')
        self._lbl_layer.setWordWrap(True)
        self._lbl_layer.setAlignment(Qt.AlignCenter)
        self._left_layout.addWidget(self._lbl_layer)

        self._btn_search = QPushButton('🔍  Buscar Imagens / Search Images')
        self._btn_search.setMinimumHeight(42)
        self._btn_search.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;'
            'font-size:12px;border-radius:6px;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#555;color:#999;}'
        )
        self._btn_search.setEnabled(False)  # habilitado somente quando há seleção / enabled only when there is a selection
        self._btn_search.clicked.connect(self._on_search)
        self._left_layout.addWidget(self._btn_search)

        self._lbl_status = QLabel('')
        self._lbl_status.setAlignment(Qt.AlignCenter)
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setStyleSheet(
            'font-size:10px; color:#9aa0a6; background:transparent; border:none;')
        self._left_layout.addWidget(self._lbl_status)

        self._left_layout.addStretch()

        # Separador vertical entre os painéis / Vertical separator between panels
        vsep = QFrame()
        vsep.setFrameShape(_FRAME_VLINE)
        vsep.setFrameShadow(_FRAME_SUNKEN)
        root.addWidget(left)
        root.addWidget(vsep)

        # ── Painel direito: abas de resultados ────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(0)
        right_layout.setContentsMargins(8, 8, 8, 8)

        self._tab_widget = QTabWidget()

        for comp_key, cards_list, tab_label in [
            ('RGB',          self._cards_rgb, 'RGB'),
            ('NIR_SWIR_RED', self._cards_nir, 'NIR-SWIR-RED'),
        ]:
            tab_content = self._build_cards_tab(comp_key, cards_list)
            self._tab_widget.addTab(tab_content, tab_label)

        # Aba de acompanhamento de downloads / Downloads tracking tab
        self._tab_widget.addTab(self._build_downloads_tab(), 'Downloads')
        self._dl_tab_idx = self._tab_widget.count() - 1

        right_layout.addWidget(self._tab_widget)
        root.addWidget(right, 1)

        # Sincroniza visibilidade inicial das abas com os checkboxes
        self._on_comp_changed()

    def _build_cards_tab(self, comp_key, cards_list):
        """Cria aba com 5 cartões em grid 2×2 + 5º na coluna esquerda abaixo.
        Creates tab with 5 cards: 2×2 grid + 5th below in left column."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(_FRAME_NOFRAME)

        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(8)
        grid.setContentsMargins(8, 8, 8, 8)

        # Posições (linha, coluna) para os 5 cartões:
        # Slots 0-3 em grade 2×2; slot 4 abaixo na coluna esquerda (igual tamanho)
        # (row, col) positions for 5 cards:
        # Slots 0-3 in 2×2 grid; slot 4 below in left column (same size)
        positions = [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0)]

        cards_list.clear()
        for i, label in enumerate(_SLOT_LABELS):
            card = _SlotCard(i, label, comp_key)
            card.download_requested.connect(self._on_download_requested)
            cards_list.append(card)
            row, col = positions[i]
            grid.addWidget(card, row, col)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(3, 1)
        scroll.setWidget(container)
        return scroll

    def _build_downloads_tab(self):
        """Monta a aba de acompanhamento de downloads com scroll, botão limpar e rows.
        Builds the downloads tracking tab with scroll area, clear button and rows."""
        from qgis.PyQt.QtWidgets import QScrollArea

        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setSpacing(4)
        outer_layout.setContentsMargins(8, 8, 8, 8)

        # Botão limpar concluídos / Clear completed button
        btn_clear = QPushButton('🗑  Limpar Concluídos / Clear Completed')
        btn_clear.setMinimumHeight(28)
        btn_clear.setStyleSheet(
            'QPushButton{background:#6c757d;color:white;font-size:10px;'
            'border-radius:4px;padding:0 8px;}'
            'QPushButton:hover{background:#545b62;}')
        btn_clear.clicked.connect(self._clear_completed_dl)
        outer_layout.addWidget(btn_clear)

        # Scroll area com as linhas de download / Scroll area with download rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(_FRAME_NOFRAME)

        self._dl_inner = QWidget()
        self._dl_layout = QVBoxLayout(self._dl_inner)
        self._dl_layout.setSpacing(4)
        self._dl_layout.setContentsMargins(0, 0, 0, 0)

        # Label de estado vazio / Empty-state label
        self._dl_empty = QLabel(
            'Nenhum download em andamento.\n'
            'Clique em "⬇ Baixar / Download" em uma cena para iniciar.\n\n'
            'No active downloads.\n'
            'Click "⬇ Baixar / Download" on a scene card to start.')
        self._dl_empty.setAlignment(Qt.AlignCenter)
        self._dl_empty.setWordWrap(True)
        self._dl_empty.setStyleSheet(
            'color:#888; font-size:11px; padding:20px; background:transparent;')
        self._dl_layout.addWidget(self._dl_empty)
        self._dl_layout.addStretch()

        scroll.setWidget(self._dl_inner)
        outer_layout.addWidget(scroll, 1)
        return outer

    def _sep(self):
        # Barra horizontal de 1px visível no fundo escuro
        # 1px horizontal bar visible on dark background
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet('background:#55585d; border:none;')
        self._root.addWidget(line)

    # ── Visibilidade das abas por composição ──────────────────────────────────

    def _on_comp_changed(self):
        """Mostra/oculta abas conforme composições selecionadas.
        Shows/hides tabs based on selected compositions."""
        rgb_on = self._chk_rgb.isChecked()
        nir_on = self._chk_nir_swir.isChecked()
        # Garante ao menos uma aba visível mesmo se nada estiver marcado
        # Ensures at least one tab is visible even if nothing is checked
        show_rgb = rgb_on or (not rgb_on and not nir_on)
        show_nir = nir_on
        try:
            self._tab_widget.setTabVisible(0, show_rgb)
            self._tab_widget.setTabVisible(1, show_nir)
        except AttributeError:
            # Qt < 5.15 não tem setTabVisible / Qt < 5.15 has no setTabVisible
            self._tab_widget.setTabEnabled(0, show_rgb)
            self._tab_widget.setTabEnabled(1, show_nir)

    # ── Marco temporal ────────────────────────────────────────────────────────

    def _on_marco_changed(self, idx):
        is_custom = (idx == 2)
        self._lbl_marco_custom.setVisible(is_custom)
        self._date_marco_custom.setVisible(is_custom)

    def _marco_date_str(self):
        idx = self._combo_marco.currentIndex()
        _, fixed = _MARCOS[idx]
        return fixed if fixed else _date_str(self._date_marco_custom.date())

    def _on_prodes_toggled(self, checked):
        """Ativa/desativa modo PRODES: desabilita data manual e mostra seletor de coluna.
        Activates/deactivates PRODES mode: disables manual date, shows column selector."""
        self._date_deforest.setEnabled(not checked)
        self._lbl_prodes_col.setVisible(checked)
        self._combo_prodes_col.setVisible(checked)
        if checked:
            self._populate_prodes_cols()

    def _populate_prodes_cols(self):
        """Popula o combo com os campos da camada ativa e pré-seleciona Image_date.
        Populates the combo with active layer fields and pre-selects Image_date."""
        self._combo_prodes_col.clear()
        try:
            layer = self.iface.activeLayer()
        except RuntimeError:
            return
        if layer is None or not isinstance(layer, QgsVectorLayer):
            return
        for field in layer.fields():
            self._combo_prodes_col.addItem(field.name())
        for i in range(self._combo_prodes_col.count()):
            if self._combo_prodes_col.itemText(i).lower() == 'image_date':
                self._combo_prodes_col.setCurrentIndex(i)
                break

    def _date_from_prodes(self, layer, col_name):
        """Lê e normaliza para ISO yyyy-MM-dd a data PRODES da primeira feição selecionada.
        Reads and normalises the PRODES date from the first selected feature to ISO yyyy-MM-dd."""
        selected = layer.selectedFeatures()
        if not selected:
            return None
        col_idx = layer.fields().indexOf(col_name)
        if col_idx < 0:
            return None
        val = selected[0].attributes()[col_idx]
        if val is None:
            return None
        val_str = str(val).strip()
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d', '%d-%m-%Y'):
            try:
                return datetime.datetime.strptime(val_str[:10], fmt).date().isoformat()
            except ValueError:
                continue
        try:
            if hasattr(val, 'toPyDate'):
                return val.toPyDate().isoformat()
        except Exception:
            pass
        return val_str[:10] if len(val_str) >= 10 else None

    def _update_search_state(self, *args):
        """Habilita Buscar somente quando há feição selecionada numa camada polígono.
        Enables Search only when a feature is selected in a polygon layer."""
        try:
            layer = self.iface.activeLayer()
        except RuntimeError:
            layer = None
        if layer is None:
            self._btn_search.setEnabled(False)
            self._lbl_layer.setText('Nenhuma camada polígono ativa / No active polygon layer')
            return
        is_poly = (isinstance(layer, QgsVectorLayer) and
                   QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PolygonGeometry)
        try:
            has_sel = is_poly and layer.selectedFeatureCount() > 0
        except RuntimeError:
            has_sel = False

        # Não muda o estado do botão enquanto a busca está rodando
        # Does not change button state while the search is running
        if not (self._thread and self._thread.isRunning()):
            self._btn_search.setEnabled(has_sel)

        if not is_poly:
            self._lbl_layer.setText(
                'Nenhuma camada polígono ativa / No active polygon layer')
        elif not has_sel:
            self._lbl_layer.setText(
                '{} — selecione ao menos 1 feição / select at least 1 feature'.format(
                    layer.name()))
        else:
            n = layer.selectedFeatureCount()
            self._lbl_layer.setText(
                '{} — {} feição(ões) selecionada(s) / feature(s) selected'.format(
                    layer.name(), n))

    def _reconnect_layer_signals(self, _=None):
        """Desconecta da camada anterior e reconecta à camada ativa atual.
        Disconnects from previous layer and reconnects to current active layer.
        Usa try/except RuntimeError para camadas cujo objeto C++ foi deletado pelo QGIS.
        Uses try/except RuntimeError for layers whose C++ object was deleted by QGIS."""
        if self._connected_layer is not None:
            try:
                self._connected_layer.selectionChanged.disconnect(self._update_search_state)
            except (RuntimeError, Exception):
                pass  # objeto C++ deletado ou sinal já desconectado / C++ object deleted or signal already disconnected
        layer = self.iface.activeLayer()
        self._connected_layer = layer
        if layer is not None:
            try:
                layer.selectionChanged.connect(self._update_search_state)
            except Exception:
                pass
        self._update_search_state()
        if self._chk_prodes.isChecked():
            self._populate_prodes_cols()

    def _update_layer_label(self):
        self._update_search_state()

    # ── Eventos de show ───────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if not self._layer_signals_connected:
            self.iface.currentLayerChanged.connect(self._reconnect_layer_signals)
            self._layer_signals_connected = True
        self._reconnect_layer_signals()

    # ── Busca ─────────────────────────────────────────────────────────────────

    def _on_search(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer) or \
                QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
            self._status_error(
                'Ative uma camada polígono primeiro. / Activate a polygon layer first.')
            return

        if layer.selectedFeatureCount() == 0:
            self._status_error(
                'Selecione ao menos 1 feição na camada antes de buscar. / '
                'Select at least 1 feature in the layer before searching.')
            return

        # Salva os anéis WGS84 do polígono selecionado para sobrepor nas thumbnails
        # Saves WGS84 rings of selected polygon for overlay on thumbnails
        self._poly_rings = _geom_to_rings_wgs84(layer)

        if not self._chk_rgb.isChecked() and not self._chk_nir_swir.isChecked():
            self._status_error(
                'Selecione ao menos uma composição. / Select at least one composition.')
            return

        if self._thread and self._thread.isRunning():
            self._thread.cancel()
            self._thread.wait()

        for card in self._cards_rgb + self._cards_nir:
            card.cancel_thumb()
            card.set_searching()

        try:
            self._last_bbox = _bbox_from_layer(layer)
        except Exception as e:
            self._status_error('Erro na bbox: {} / Bbox error: {}'.format(e, e))
            return

        marco_str = self._marco_date_str()
        if self._chk_prodes.isChecked():
            col_name     = self._combo_prodes_col.currentText()
            deforest_str = self._date_from_prodes(layer, col_name)
            if deforest_str is None:
                self._status_error(
                    'Coluna PRODES "{}" sem data válida na feição selecionada. / '
                    'PRODES column "{}" has no valid date in the selected feature.'.format(
                        col_name, col_name))
                return
        else:
            deforest_str = _date_str(self._date_deforest.date())
        cloud_max    = self._spin_cloud.value()
        use_brazil   = True   # Monitor sempre usa INPE/BDC / Monitor always uses INPE/BDC

        self._btn_search.setEnabled(False)
        self._lbl_status.setStyleSheet(
            'font-size:10px; color:#9aa0a6; background:transparent; border:none;')
        self._lbl_status.setText('Buscando 5 imagens... / Searching 5 images...')

        self._thread = _SlotSearchThread(
            self._last_bbox, marco_str, deforest_str, cloud_max, use_brazil,
            parent=self)
        self._thread.slot_done.connect(self._on_slot_done)
        self._thread.slot_error.connect(self._on_slot_error)
        self._thread.all_done.connect(self._on_all_done)
        self._thread.start()

    def _on_slot_done(self, slot_idx, feature, col_id):
        """Preenche os cartões de ambas as abas com o mesmo resultado.
        Fills cards in both tabs with the same result (composition differs)."""
        if not (0 <= slot_idx < 5):
            return
        bbox  = self._last_bbox
        rings = self._poly_rings
        if slot_idx < len(self._cards_rgb):
            self._cards_rgb[slot_idx].set_result(feature, col_id, bbox, rings)
        if slot_idx < len(self._cards_nir):
            self._cards_nir[slot_idx].set_result(feature, col_id, bbox, rings)

    def _on_slot_error(self, slot_idx, msg):
        if not (0 <= slot_idx < 5):
            return
        if slot_idx < len(self._cards_rgb):
            self._cards_rgb[slot_idx].set_error(msg)
        if slot_idx < len(self._cards_nir):
            self._cards_nir[slot_idx].set_error(msg)

    def _on_all_done(self):
        self._lbl_status.setStyleSheet(
            'font-size:10px; color:#81c784; background:transparent; border:none;')
        self._lbl_status.setText('Busca concluída. / Search complete.')
        # Reabilita o botão somente se ainda houver seleção ativa
        # Re-enables button only if there is still an active selection
        self._update_search_state()

    def _status_error(self, msg):
        self._lbl_status.setStyleSheet(
            'font-size:10px; color:#ff6b6b; background:transparent; border:none;')
        self._lbl_status.setText(msg)

    # ── Gestão da aba Downloads ───────────────────────────────────────────────

    def _update_dl_tab_label(self):
        """Atualiza o texto da aba Downloads com contagem de itens ativos /
        Update Downloads tab text with active item count."""
        active = sum(1 for r in self._dl_download_rows if not r.is_done())
        total  = len(self._dl_download_rows)
        if active:
            label = 'Downloads ● ({})'.format(active)
        elif total:
            label = 'Downloads ({})'.format(total)
        else:
            label = 'Downloads'
        self._tab_widget.setTabText(self._dl_tab_idx, label)

    def _on_dl_row_removed(self, row):
        """Remove a linha da lista interna ao ser fechada pelo usuário /
        Remove row from internal list when closed by the user."""
        if row in self._dl_download_rows:
            self._dl_download_rows.remove(row)
        self._update_dl_tab_label()
        if not self._dl_download_rows:
            self._dl_empty.setVisible(True)

    def _clear_completed_dl(self):
        """Remove todas as linhas concluídas ou canceladas /
        Remove all completed or cancelled rows."""
        done = [r for r in self._dl_download_rows if r.is_done()]
        for row in done:
            self._dl_download_rows.remove(row)
            row.setParent(None)
            row.deleteLater()
        self._update_dl_tab_label()
        if not self._dl_download_rows:
            self._dl_empty.setVisible(True)

    # ── Download ──────────────────────────────────────────────────────────────

    def _on_download_requested(self, feature, col_id, comp_key):
        """Inicia download da composição do cartão clicado e acompanha na aba Downloads.
        Starts download for the clicked card's composition and tracks it in the Downloads tab."""
        try:
            from core.rth_dialog_actions import _DownloadRow
            from core.rth_downloader import DownloadThread
        except ImportError as e:
            self.iface.messageBar().pushMessage(
                'RTH Monitor',
                'Módulo de download não disponível: {} / Download module not available: {}'.format(
                    e, e),
                level=Qgis.MessageLevel.Critical, duration=5)
            return

        band_tuple = _BANDS.get(comp_key, {}).get(col_id)
        if band_tuple is None:
            self.iface.messageBar().pushMessage(
                'RTH Monitor',
                'Composição {} não disponível para {}. / Composition {} not available for {}.'.format(
                    comp_key, col_id, comp_key, col_id),
                level=Qgis.MessageLevel.Warning, duration=4)
            return

        # Monta título do row com satélite, data e composição / Build row title with satellite, date, composition
        props     = feature.get('properties', {})
        dt_str    = props.get('datetime', '')[:10]
        sat_label = ('S2' if ('sentinel-2' in col_id.lower() or col_id.startswith('S2'))
                     else 'LS')
        title     = '{} · {} · {}'.format(sat_label, dt_str, comp_key)

        # Cria a linha de download na aba Downloads / Create download row in Downloads tab
        self._dl_empty.setVisible(False)
        row = _DownloadRow(title, self._dl_inner)
        row.row_removed.connect(self._on_dl_row_removed)
        self._dl_layout.insertWidget(0, row)   # mais recente no topo / newest on top
        self._dl_download_rows.append(row)

        # clip_bbox recorta o download à AOI do talhão (igual à miniatura) /
        # clip_bbox clips the download to the talhão AOI (same as the thumbnail)
        thread = DownloadThread(
            [feature], col_id, comp_key, self._output_dir,
            band_tuple=band_tuple, clip_bbox=self._last_bbox)
        thread.layer_ready.connect(self._on_layer_ready)
        thread.finished_sig.connect(lambda _: self._update_dl_tab_label())

        # Captura o último erro e exibe na barra quando o download falhar —
        # ajuda a diagnosticar falhas silenciosas / Capture last error and show
        # in the bar on failure — helps diagnose silent failures
        _last_err = ['']

        def _friendly_err(raw):
            """Traduz códigos HTTP conhecidos para mensagens amigáveis /
            Translate known HTTP codes to friendly messages."""
            if 'response code: 409' in raw:
                return ('Planetary Computer — conflito na assinatura SAS (409). '
                        'Tente novamente em instantes. / '
                        'Planetary Computer — SAS signing conflict (409). '
                        'Try again in a moment.')
            if 'response code: 403' in raw:
                return ('Acesso negado ao asset (403). Token SAS pode ter expirado. '
                        'Tente novamente. / '
                        'Asset access denied (403). SAS token may have expired. '
                        'Try again.')
            if 'response code: 429' in raw:
                return ('Muitas requisições ao Planetary Computer (429). '
                        'Aguarde alguns segundos e tente novamente. / '
                        'Too many requests to Planetary Computer (429). '
                        'Wait a few seconds and try again.')
            if 'response code: 503' in raw or 'response code: 502' in raw:
                return ('Serviço Planetary Computer indisponível temporariamente. '
                        'Tente novamente. / '
                        'Planetary Computer temporarily unavailable. Try again.')
            return raw

        def _capture_err(msg, is_err, _le=_last_err):
            if is_err:
                _le[0] = msg

        def _report_on_fail(count, _le=_last_err, _f=feature, _ci=col_id, _ck=comp_key):
            if count == 0:
                raw = (_le[0] or
                       'Erro desconhecido — verifique GDAL e rede / '
                       'Unknown error — check GDAL and network')
                # Se for PC Sentinel-2 com erro HTTP → tenta fallback Element84
                # If PC Sentinel-2 HTTP error → try Element84 fallback
                is_pc_s2_http = (
                    _ci == _COL_S2_PC and
                    ('response code: 4' in raw or 'response code: 5' in raw)
                )
                if is_pc_s2_http:
                    code = (raw.split('response code: ')[-1][:3]
                            if 'response code:' in raw else '?')
                    self.iface.messageBar().pushMessage(
                        'RTH Monitor',
                        'PC falhou ({}) — tentando AWS Element84... / '
                        'PC failed ({}) — trying AWS Element84...'.format(code, code),
                        level=Qgis.MessageLevel.Info, duration=5)
                    self._start_pc_fallback(_f, _ci, _ck)
                else:
                    err_msg = _friendly_err(raw)
                    self.iface.messageBar().pushMessage(
                        'RTH Monitor — Download',
                        err_msg[:300],
                        level=Qgis.MessageLevel.Warning, duration=14)

        thread.progress_sig.connect(_capture_err)
        thread.finished_sig.connect(_report_on_fail)

        row.attach_thread(thread)
        thread.start()
        self._dl_threads.append(thread)   # evita GC prematuro / prevent premature GC

        self._update_dl_tab_label()
        # Muda para aba Downloads para o usuário acompanhar / Switch to Downloads tab
        self._tab_widget.setCurrentIndex(self._dl_tab_idx)

    # ── Fallback PC → Element84 ────────────────────────────────────────────────

    def _start_pc_fallback(self, feature, col_id, comp_key):
        """Inicia busca em cascata (E84 por ID → E84 por bbox → S3 direto) como fallback ao PC.
        Starts cascading search (E84 by ID → E84 by bbox → direct S3) as PC fallback."""
        t = _PcFallbackThread(feature, col_id, comp_key, self)
        t.found.connect(self._on_fallback_found)
        t.not_found.connect(self._on_fallback_not_found)
        t.finished.connect(lambda th=t: self._fallback_threads.remove(th)
                           if th in self._fallback_threads else None)
        self._fallback_threads.append(t)
        t.start()

    def _on_fallback_found(self, aws_feature, col_id, comp_key):
        """Inicia download da cena encontrada no Element84.
        Starts download for the scene found on Element84."""
        self.iface.messageBar().pushMessage(
            'RTH Monitor',
            'Cena encontrada no Element84 — iniciando download via AWS... / '
            'Scene found on Element84 — starting AWS download...',
            level=Qgis.MessageLevel.Success, duration=5)
        self._on_download_requested(aws_feature, col_id, comp_key)

    def _on_fallback_not_found(self, reason, col_id, comp_key):
        """Exibe erro quando a cena não é encontrada no Element84 nem no PC.
        Shows error when scene not found on Element84 or PC."""
        self.iface.messageBar().pushMessage(
            'RTH Monitor — Download',
            'PC e Element84 falharam. {} / PC and Element84 both failed. {}'.format(
                reason, reason),
            level=Qgis.MessageLevel.Critical, duration=12)

    def _on_layer_ready(self, path, name, feature):
        """Adiciona camada baixada ao projeto QGIS.
        Adds downloaded layer to the QGIS project."""
        try:
            from core.rth_layer_utils import apply_rgb_renderer, collapse_layer
        except ImportError:
            apply_rgb_renderer = None
            collapse_layer     = None

        layer = QgsRasterLayer(path, name)
        if not layer.isValid():
            self.iface.messageBar().pushMessage(
                'RTH Monitor',
                'Camada inválida após download: {} / Invalid layer after download: {}'.format(
                    name, name),
                level=Qgis.MessageLevel.Warning, duration=4)
            return

        if apply_rgb_renderer:
            try:
                apply_rgb_renderer(layer)
            except Exception:
                pass

        QgsProject.instance().addMapLayer(layer)

        if collapse_layer:
            try:
                collapse_layer(layer)
            except Exception:
                pass

        self.iface.messageBar().pushMessage(
            'RTH Monitor',
            'Camada adicionada: {} / Layer added: {}'.format(name, name),
            level=Qgis.MessageLevel.Success, duration=4)

    # ── Limpeza ao fechar ─────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._thread and self._thread.isRunning():
            self._thread.cancel()
            self._thread.wait()
        for card in self._cards_rgb + self._cards_nir:
            card.cancel_thumb()
        # Cancela downloads ativos na aba Downloads / Cancel active downloads in Downloads tab
        for row in list(self._dl_download_rows):
            try:
                row.cancel_if_running()
            except RuntimeError:
                pass  # widget C++ já deletado / C++ widget already deleted
        # Encerra threads de fallback PC→E84 ainda em andamento / Stop any running PC→E84 fallback threads
        for t in list(self._fallback_threads):
            try:
                t.quit()
                t.wait(500)
            except RuntimeError:
                pass
        # Desconecta sinais de camada para evitar referências mortas
        # Disconnects layer signals to avoid dangling references
        if self._layer_signals_connected:
            try:
                self.iface.currentLayerChanged.disconnect(self._reconnect_layer_signals)
            except Exception:
                pass
            self._layer_signals_connected = False
        if self._connected_layer is not None:
            try:
                self._connected_layer.selectionChanged.disconnect(self._update_search_state)
            except (RuntimeError, Exception):
                pass
        super().closeEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# Tool
# ──────────────────────────────────────────────────────────────────────────────

class DeforestationMonitorTool:

    def __init__(self, iface):
        self.iface = iface
        self._dlg  = None

    def run(self):
        if self._dlg is None:
            self._dlg = DeforestationMonitorDialog(
                self.iface, parent=self.iface.mainWindow())
        self._dlg._update_search_state()
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
