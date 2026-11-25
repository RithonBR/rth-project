# -*- coding: utf-8 -*-
"""
tool_stack_ml — RTH Stack de Imagem ML / Stack Image ML

Permite ao usuário selecionar bandas Sentinel-2 e índices de vegetação de uma
cena STAC e gerar um GeoTIFF multi-banda empilhado, pronto para uso em modelos
de Machine Learning.

Allows the user to select Sentinel-2 bands and vegetation indices from a STAC
scene and produce a stacked multi-band GeoTIFF ready for Machine Learning models.
"""

import os
import json
import tempfile

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QComboBox, QFrame, QGroupBox, QCheckBox,
    QApplication, QListWidget, QListWidgetItem,
    QProgressDialog, QFileDialog, QLineEdit, QInputDialog,
    QDateEdit, QSpinBox, QScrollArea, QWidget, QSizePolicy, QSplitter,
)
from qgis.PyQt.QtCore import Qt, QDate, QThread, pyqtSignal, QSettings, QSize, QByteArray
from qgis.PyQt.QtGui import QIcon, QPixmap
from qgis.core import Qgis, QgsProject, QgsRasterLayer

from core.rth_stac_api import search_stac, search_stac_pc, _route_for, STAC_PC, get_bbox_from_canvas
from tools.field_analysis.tool_field_analysis import (
    _clip_band, _init_gdal, _scene_utm, _parse_s2_id,
    _ds_to_array, _match_shape, _NODATA, _DEPS_OK, _DEPS_MSG, _resolve,
    _BAND_VARS,
)

# ── Qt5/Qt6 compat ────────────────────────────────────────────────────────────
try:
    _ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
    _ALIGN_LEFT   = Qt.AlignmentFlag.AlignLeft
    _KEEP_ASPECT  = Qt.AspectRatioMode.KeepAspectRatio
    _SMOOTH       = Qt.TransformationMode.SmoothTransformation
except AttributeError:
    _ALIGN_CENTER = Qt.AlignCenter
    _ALIGN_LEFT   = Qt.AlignLeft
    _KEEP_ASPECT  = Qt.KeepAspectRatio
    _SMOOTH       = Qt.SmoothTransformation

# ── Sentinel-2 bands available in L2A ────────────────────────────────────────
_S2_BANDS = [
    ('B01', 'B01 — Aerossol Costeiro / Coastal Aerosol (60m)'),
    ('B02', 'B02 — Azul / Blue (10m)'),
    ('B03', 'B03 — Verde / Green (10m)'),
    ('B04', 'B04 — Vermelho / Red (10m)'),
    ('B05', 'B05 — Red-Edge 1 (20m)'),
    ('B06', 'B06 — Red-Edge 2 (20m)'),
    ('B07', 'B07 — Red-Edge 3 (20m)'),
    ('B08', 'B08 — NIR Largo / Broad NIR (10m)'),
    ('B8A', 'B8A — NIR Estreito / Narrow NIR (20m)'),
    ('B09', 'B09 — Vapor d\'Água / Water Vapour (60m)'),
    ('B11', 'B11 — SWIR-1 (20m)'),
    ('B12', 'B12 — SWIR-2 (20m)'),
]

# ── Vegetation index definitions for stacking ─────────────────────────────────
_STACK_INDICES = {
    'NDVI': {
        'label':   'NDVI — (NIR−RED)/(NIR+RED)',
        'vars':    ['nir', 'red'],
        'formula': '(nir - red) / (nir + red)',
    },
    'EVI': {
        'label':   'EVI — 2.5×(NIR−RED)/(NIR+6×RED−7.5×BLUE+1)',
        'vars':    ['nir', 'red', 'blue'],
        'formula': '2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1)',
    },
    'SAVI': {
        'label':   'SAVI — 1.5×(NIR−RED)/(NIR+RED+0.5)',
        'vars':    ['nir', 'red'],
        'formula': '1.5 * (nir - red) / (nir + red + 0.5)',
    },
    'NDWI': {
        'label':   'NDWI — (GREEN−NIR)/(GREEN+NIR)',
        'vars':    ['green', 'nir'],
        'formula': '(green - nir) / (green + nir)',
    },
    'GCVI': {
        'label':   'GCVI — (NIR/GREEN)−1',
        'vars':    ['nir', 'green'],
        'formula': '(nir / (green + 1e-9)) - 1',
    },
    'SR': {
        'label':   'SR — NIR/RED',
        'vars':    ['nir', 'red'],
        'formula': 'nir / (red + 1e-9)',
    },
}

_RTH_STACK_PRESET = {
    'bands':   ['B01', 'B02', 'B03', 'B04', 'B05', 'B06',
                'B07', 'B08', 'B8A', 'B09', 'B11', 'B12'],
    'indices': ['NDVI', 'EVI', 'SAVI', 'NDWI', 'GCVI', 'SR'],
}

_SETTINGS_PRESETS = 'rth_project/stack_ml/presets'

_COLLECTIONS = [
    ('S2_L2A-1',       'Sentinel-2 L2A — INPE/BDC (Brasil)'),
    ('sentinel-2-l2a', 'Sentinel-2 L2A — Planetary Computer (Global)'),
]


def _safe_res(bbox_wgs84, max_px=4096, min_res=10.0):
    """Compute output resolution so neither axis exceeds max_px pixels."""
    import math
    lat_avg  = (bbox_wgs84[1] + bbox_wgs84[3]) / 2.0
    width_m  = abs(bbox_wgs84[2] - bbox_wgs84[0]) * 111_319 * math.cos(math.radians(lat_avg))
    height_m = abs(bbox_wgs84[3] - bbox_wgs84[1]) * 110_574
    x_res = max(min_res, width_m  / max_px)
    y_res = max(min_res, height_m / max_px)
    return x_res, y_res


def _thumb_url(feature):
    """Extract the best available thumbnail URL from a STAC feature."""
    assets = feature.get('assets', {})
    for key in ('thumbnail', 'rendered_preview', 'overview', 'visual_preview', 'preview'):
        a = assets.get(key)
        if a and isinstance(a, dict) and a.get('href'):
            return a['href']
    for link in feature.get('links', []):
        if link.get('rel') in ('thumbnail', 'preview', 'overview'):
            href = link.get('href')
            if href:
                return href
    return None


# ── Thumbnail loader ──────────────────────────────────────────────────────────

class _ThumbLoaderML(QThread):
    ready = pyqtSignal(int, object)   # (row_index, raw_bytes or None)

    def __init__(self, items, parent=None):
        # items: list of (row_index, url)
        super().__init__(parent)
        self._items = items

    def run(self):
        import urllib.request
        for row, url in self._items:
            if not url:
                self.ready.emit(row, None)
                continue
            try:
                req = urllib.request.Request(
                    url, headers={'User-Agent': 'RTH-Plugin/1.0'})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = resp.read()
                self.ready.emit(row, data)
            except Exception:
                self.ready.emit(row, None)


# ── STAC search thread ────────────────────────────────────────────────────────

class _StacSearchThread(QThread):
    result = pyqtSignal(list)
    error  = pyqtSignal(str)

    def __init__(self, params, parent=None):
        super().__init__(parent)
        self._p = params

    def run(self):
        try:
            p = self._p
            endpoint, _ = _route_for(p['coll_id'])
            if endpoint == STAC_PC:
                features, _, _, _ = search_stac_pc(
                    p['coll_id'], p['bbox'], p['date_ini'], p['date_fim'],
                    p['cloud_max'])
            else:
                features, _ = search_stac(
                    p['coll_id'], p['bbox'], p['date_ini'], p['date_fim'],
                    p['cloud_max'])
            self.result.emit(features)
        except Exception as e:
            self.error.emit(str(e))


# ── Stack build thread ────────────────────────────────────────────────────────

class _StackBuildThread(QThread):
    progress = pyqtSignal(int, int, str)
    done     = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, feature, bbox, bands, indices, out_path,
                 custom_indices=None, parent=None):
        super().__init__(parent)
        self._feature        = feature
        self._bbox           = bbox
        self._bands          = bands
        self._indices        = indices
        self._out_path       = out_path
        self._custom_indices = custom_indices or {}
        self._cancel         = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            import numpy as np
            gdal = _init_gdal()
            if gdal is None:
                self.error.emit('GDAL não disponível / GDAL not available')
                return

            target_crs = _scene_utm(self._feature)
            x_res, y_res = _safe_res(self._bbox)

            all_index_defs_early = {**_STACK_INDICES, **self._custom_indices}
            index_needed_vars = set()
            for idx_key in self._indices:
                defn_e = all_index_defs_early.get(idx_key)
                if defn_e:
                    for v in defn_e.get('vars', []):
                        index_needed_vars.add(v)

            var_to_band = {v: _BAND_VARS[v] for v in index_needed_vars if v in _BAND_VARS}
            raw_band_set = set(self._bands)
            var_band_set = set(var_to_band.values())
            all_s2_keys  = raw_band_set | var_band_set

            total_steps = len(all_s2_keys) + len(self._indices)
            step = 0

            clipped = {}
            ref_gt = ref_proj = ref_shape = None

            for s2_key in all_s2_keys:
                if self._cancel:
                    self.error.emit('Cancelado / Cancelled')
                    return
                self.progress.emit(step, total_steps,
                    'Baixando banda / Downloading band {}…'.format(s2_key))
                ds = _clip_band(self._feature, s2_key, self._bbox,
                                gdal, target_crs, None,
                                xRes=x_res, yRes=y_res)
                if ds is None:
                    clipped[s2_key] = None
                    step += 1
                    continue
                if ref_gt is None:
                    ref_gt    = ds.GetGeoTransform()
                    ref_proj  = ds.GetProjection()
                    ref_shape = (ds.RasterYSize, ds.RasterXSize)
                clipped[s2_key] = (ds, None, ref_gt, ref_proj, ref_shape)
                step += 1

            if ref_gt is None:
                self.error.emit(
                    'Nenhuma banda pôde ser baixada para a área selecionada. / '
                    'No band could be downloaded for the selected area.')
                return

            arrays = {}
            for s2_key, val in clipped.items():
                if val is None:
                    arrays[s2_key] = None
                    continue
                ds  = val[0]
                arr = _match_shape(_ds_to_array(ds), ref_shape)
                arrays[s2_key] = arr
                del ds

            tmp_dir    = tempfile.mkdtemp(prefix='rth_stack_')
            tiff_paths = []

            for s2_key in self._bands:
                if self._cancel:
                    self.error.emit('Cancelado / Cancelled')
                    return
                arr = arrays.get(s2_key)
                if arr is None:
                    continue
                tmp_path = os.path.join(tmp_dir, '{}.tif'.format(s2_key))
                _write_band_tiff(arr, ref_gt, ref_proj, tmp_path, gdal)
                tiff_paths.append((tmp_path, s2_key))

            all_index_defs = {**_STACK_INDICES, **self._custom_indices}

            for idx_key in self._indices:
                if self._cancel:
                    self.error.emit('Cancelado / Cancelled')
                    return
                defn = all_index_defs.get(idx_key)
                if defn is None:
                    step += 1
                    continue
                self.progress.emit(step, total_steps,
                    'Calculando índice / Computing index {}…'.format(idx_key))

                idx_vars = {}
                ok = True
                for v in defn['vars']:
                    s2_key = var_to_band.get(v)
                    if s2_key is None or arrays.get(s2_key) is None:
                        ok = False
                        break
                    idx_vars[v] = arrays[s2_key]

                if not ok:
                    step += 1
                    continue

                try:
                    formula  = defn['formula']
                    local_ns = {**idx_vars, 'np': np}
                    result   = eval(formula, {'__builtins__': {}}, local_ns)   # noqa: S307
                    result   = result.astype('float32')
                except Exception:
                    step += 1
                    continue

                tmp_path = os.path.join(tmp_dir, '{}.tif'.format(idx_key))
                _write_band_tiff(result, ref_gt, ref_proj, tmp_path, gdal)
                tiff_paths.append((tmp_path, idx_key))
                step += 1

            if not tiff_paths:
                self.error.emit(
                    'Nenhuma banda ou índice disponível para empilhar. / '
                    'No band or index available to stack.')
                return

            self.progress.emit(total_steps, total_steps,
                'Empilhando bandas / Stacking bands…')

            paths_only = [p for p, _ in tiff_paths]
            vrt_path   = os.path.join(tmp_dir, 'stack.vrt')
            vrt_opts   = gdal.BuildVRTOptions(separate=True)
            vrt_ds     = gdal.BuildVRT(vrt_path, paths_only, options=vrt_opts)
            if vrt_ds is None:
                self.error.emit('Falha ao criar VRT / Failed to create VRT')
                return
            del vrt_ds

            tr_opts = gdal.TranslateOptions(
                format='GTiff',
                creationOptions=['COMPRESS=LZW', 'BIGTIFF=IF_SAFER', 'INTERLEAVE=BAND'],
            )
            gdal.Translate(self._out_path, vrt_path, options=tr_opts)

            ds_out = gdal.Open(self._out_path, 1)
            if ds_out:
                for i, (_, label) in enumerate(tiff_paths, start=1):
                    b = ds_out.GetRasterBand(i)
                    if b:
                        b.SetDescription(label)
                del ds_out

            self.done.emit(self._out_path)

        except Exception as e:
            self.error.emit('Erro / Error: {}'.format(e))


def _write_band_tiff(arr, gt, proj, output_path, gdal):
    """Write single-band float32 GeoTIFF with LZW compression."""
    import numpy as np
    rows, cols = arr.shape
    driver = gdal.GetDriverByName('GTiff')
    ds = driver.Create(output_path, cols, rows, 1, gdal.GDT_Float32,
                       options=['COMPRESS=LZW'])
    ds.SetGeoTransform(gt)
    ds.SetProjection(proj)
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(_NODATA)
    b.WriteArray(np.where(np.isnan(arr), _NODATA, arr).astype('float32'))
    ds.FlushCache()
    del ds


# ── Dialog ────────────────────────────────────────────────────────────────────

class StackMLDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface           = iface
        self._features       = []
        self._search_thread  = None
        self._build_thread   = None
        self._progress_dlg   = None
        self._thumb_loader   = None
        self._custom_indices = {}

        self.setWindowTitle('RTH Stack de Imagem ML / Stack Image ML')
        self.setMinimumWidth(1160)
        self.setMinimumHeight(640)
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        except AttributeError:
            self.setAttribute(Qt.WA_QuitOnClose, False)

        self._build_ui()
        self._load_presets_combo()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # ── Title (full width) ────────────────────────────────────────────────
        lbl = QLabel('🛰  RTH Stack de Imagem ML / Stack Image ML')
        lbl.setAlignment(_ALIGN_CENTER)
        lbl.setStyleSheet(
            'font-size:14px; font-weight:bold; color:#0f9d58;'
            'padding:8px; background:#f1faf5; border-radius:6px;')
        root.addWidget(lbl)

        # ── Main content: horizontal splitter ─────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)

        # ═══════════════════════════════════════════
        # LEFT PANEL — controls (scrollable)
        # ═══════════════════════════════════════════
        left_inner = QWidget()
        left_lay   = QVBoxLayout(left_inner)
        left_lay.setSpacing(8)
        left_lay.setContentsMargins(4, 4, 4, 4)

        # Search group
        grp_search = QGroupBox('Busca de Cenas / Scene Search')
        grp_search.setStyleSheet(
            'QGroupBox{font-weight:bold; font-size:10px;'
            'border:1px solid #d0e8d8; border-radius:6px; margin-top:8px;}'
            'QGroupBox::title{subcontrol-origin:margin; left:10px; padding:0 4px;}')
        lay_search = QVBoxLayout(grp_search)
        lay_search.setSpacing(6)
        lay_search.setContentsMargins(10, 14, 10, 10)

        row_coll = QHBoxLayout()
        row_coll.addWidget(QLabel('Coleção / Collection:'))
        self._combo_coll = QComboBox()
        for cid, clabel in _COLLECTIONS:
            self._combo_coll.addItem(clabel, cid)
        self._combo_coll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row_coll.addWidget(self._combo_coll)
        lay_search.addLayout(row_coll)

        row_dates = QHBoxLayout()
        row_dates.addWidget(QLabel('Início / Start:'))
        self._date_ini = QDateEdit()
        self._date_ini.setCalendarPopup(True)
        self._date_ini.setDate(QDate.currentDate().addMonths(-6))
        self._date_ini.setDisplayFormat('yyyy-MM-dd')
        row_dates.addWidget(self._date_ini)
        row_dates.addWidget(QLabel('→ Fim / End:'))
        self._date_fim = QDateEdit()
        self._date_fim.setCalendarPopup(True)
        self._date_fim.setDate(QDate.currentDate())
        self._date_fim.setDisplayFormat('yyyy-MM-dd')
        row_dates.addWidget(self._date_fim)
        lay_search.addLayout(row_dates)

        row_cloud = QHBoxLayout()
        row_cloud.addStretch()
        row_cloud.addWidget(QLabel('☁  Nuvens Máx. / Max Cloud:'))
        self._spin_cloud = QSpinBox()
        self._spin_cloud.setRange(0, 100)
        self._spin_cloud.setValue(20)
        self._spin_cloud.setSuffix('  %')
        self._spin_cloud.setMinimumWidth(70)
        row_cloud.addWidget(self._spin_cloud)
        row_cloud.addStretch()
        lay_search.addLayout(row_cloud)

        btn_search = QPushButton('🔍  Buscar Cenas / Search Scenes')
        btn_search.setMinimumHeight(34)
        btn_search.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;'
            'font-size:11px;border-radius:5px;}'
            'QPushButton:hover{background:#1558b0;}')
        btn_search.clicked.connect(self._on_search)
        lay_search.addWidget(btn_search)
        left_lay.addWidget(grp_search)

        self._sep_left(left_lay)

        # Preset selector
        row_preset = QHBoxLayout()
        row_preset.addWidget(QLabel('Preset:'))
        self._combo_preset = QComboBox()
        self._combo_preset.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._combo_preset.currentIndexChanged.connect(self._on_preset_selected)
        row_preset.addWidget(self._combo_preset)
        btn_save_preset = QPushButton('💾')
        btn_save_preset.setToolTip('Salvar Preset / Save Preset')
        btn_save_preset.setFixedWidth(32)
        btn_save_preset.clicked.connect(self._on_save_preset)
        row_preset.addWidget(btn_save_preset)
        btn_del_preset = QPushButton('🗑')
        btn_del_preset.setToolTip('Excluir / Delete')
        btn_del_preset.setFixedWidth(32)
        btn_del_preset.clicked.connect(self._on_delete_preset)
        row_preset.addWidget(btn_del_preset)
        left_lay.addLayout(row_preset)

        # Band selection
        grp_bands = QGroupBox('Bandas Sentinel-2 / Sentinel-2 Bands')
        grp_bands.setStyleSheet(
            'QGroupBox{font-size:10px; font-weight:bold;'
            'border:1px solid #ddd; border-radius:5px; margin-top:6px;}'
            'QGroupBox::title{subcontrol-origin:margin; left:8px; padding:0 4px;}')
        lay_bands = QGridLayout(grp_bands)
        lay_bands.setSpacing(3)
        lay_bands.setContentsMargins(8, 12, 8, 8)
        self._chk_bands = {}
        for i, (key, label) in enumerate(_S2_BANDS):
            chk = QCheckBox(key)
            chk.setToolTip(label)
            lay_bands.addWidget(chk, i // 4, i % 4)
            self._chk_bands[key] = chk
        left_lay.addWidget(grp_bands)

        # Index selection
        grp_idx = QGroupBox('Índices de Vegetação / Vegetation Indices')
        grp_idx.setStyleSheet(
            'QGroupBox{font-size:10px; font-weight:bold;'
            'border:1px solid #ddd; border-radius:5px; margin-top:6px;}'
            'QGroupBox::title{subcontrol-origin:margin; left:8px; padding:0 4px;}')
        lay_idx = QVBoxLayout(grp_idx)
        lay_idx.setSpacing(4)
        lay_idx.setContentsMargins(8, 12, 8, 8)

        self._idx_grid_widget = QWidget()
        self._idx_grid        = QGridLayout(self._idx_grid_widget)
        self._idx_grid.setSpacing(3)
        self._idx_grid.setContentsMargins(0, 0, 0, 0)
        self._chk_indices = {}
        for i, (key, defn) in enumerate(_STACK_INDICES.items()):
            chk = QCheckBox(defn['label'])
            self._idx_grid.addWidget(chk, i // 2, i % 2)
            self._chk_indices[key] = chk
        lay_idx.addWidget(self._idx_grid_widget)

        self._btn_add_idx = QPushButton(
            '➕  Adicionar Índice Personalizado / Add Custom Index')
        self._btn_add_idx.setStyleSheet(
            'QPushButton{color:#1a73e8; border:1px solid #1a73e8;'
            'border-radius:4px; padding:3px 8px; font-size:10px;}'
            'QPushButton:hover{background:#e8f0fe;}'
            'QPushButton:disabled{color:#bbb; border-color:#ddd; background:transparent;}')
        self._btn_add_idx.clicked.connect(self._on_add_custom_index)
        lay_idx.addWidget(self._btn_add_idx)
        left_lay.addWidget(grp_idx)

        self._sep_left(left_lay)

        # Download area
        row_clip = QHBoxLayout()
        row_clip.addWidget(QLabel('Download:'))
        self._combo_clip = QComboBox()
        self._combo_clip.addItem('Cena Completa / Full Scene', 'scene')
        self._combo_clip.addItem('Canvas (visível / visible)', 'canvas')
        self._combo_clip.addItem('Camada Ativa / Active Layer', 'layer')
        self._combo_clip.setCurrentIndex(0)
        self._combo_clip.setToolTip(
            'Cena Completa: usa o bbox da cena STAC — baixa a imagem inteira. / '
            'Full Scene: uses the STAC scene bbox — downloads the complete image.')
        row_clip.addWidget(self._combo_clip)
        left_lay.addLayout(row_clip)

        # Output path
        row_out = QHBoxLayout()
        row_out.addWidget(QLabel('Saída / Output:'))
        self._edit_out = QLineEdit()
        self._edit_out.setPlaceholderText('Output .tif path…')
        row_out.addWidget(self._edit_out)
        btn_browse = QPushButton('…')
        btn_browse.setFixedWidth(28)
        btn_browse.clicked.connect(self._on_browse)
        row_out.addWidget(btn_browse)
        left_lay.addLayout(row_out)

        # Run button
        self._btn_run = QPushButton('▶  Empilhar Imagem / Stack Image')
        self._btn_run.setMinimumHeight(42)
        self._btn_run.setStyleSheet(
            'QPushButton{background:#0f9d58;color:white;font-weight:bold;'
            'font-size:13px;border-radius:6px;}'
            'QPushButton:hover{background:#0b7842;}'
            'QPushButton:disabled{background:#aaa;}')
        self._btn_run.clicked.connect(self._on_run)
        left_lay.addWidget(self._btn_run)
        left_lay.addStretch()

        if not _DEPS_OK:
            self._btn_run.setEnabled(False)

        # Wrap left panel in scroll area
        left_scroll = QScrollArea()
        left_scroll.setWidget(left_inner)
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(560)
        left_scroll.setMaximumWidth(680)
        left_scroll.setStyleSheet('QScrollArea{border:none;}')
        splitter.addWidget(left_scroll)

        # ═══════════════════════════════════════════
        # RIGHT PANEL — scene thumbnails (black)
        # ═══════════════════════════════════════════
        right_widget = QWidget()
        right_widget.setStyleSheet('background:#000000;')
        right_lay = QVBoxLayout(right_widget)
        right_lay.setSpacing(6)
        right_lay.setContentsMargins(10, 8, 10, 8)

        self._lbl_scenes_count = QLabel('Cenas / Scenes:')
        self._lbl_scenes_count.setStyleSheet(
            'color:#ffffff; font-weight:bold; font-size:11px;'
            'background:transparent; padding:2px 0;')
        right_lay.addWidget(self._lbl_scenes_count)

        self._list_scenes = QListWidget()
        self._list_scenes.setIconSize(QSize(160, 120))
        self._list_scenes.setStyleSheet(
            'QListWidget{'
            '  background:#000000; color:#ffffff;'
            '  border:1px solid #222222; border-radius:4px;'
            '}'
            'QListWidget::item{'
            '  color:#ffffff; padding:6px 8px;'
            '  border-bottom:1px solid #1a1a1a;'
            '}'
            'QListWidget::item:selected{'
            '  background:#0d3320; color:#00e676;'
            '}'
            'QListWidget::item:hover{'
            '  background:#111111;'
            '}')
        right_lay.addWidget(self._list_scenes, stretch=1)

        self._lbl_status = QLabel('')
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setAlignment(_ALIGN_LEFT)
        self._lbl_status.setStyleSheet(
            'color:#aaaaaa; font-size:10px; background:transparent; padding:2px 0;')
        right_lay.addWidget(self._lbl_status)

        splitter.addWidget(right_widget)
        splitter.setSizes([620, 460])

        root.addWidget(splitter, stretch=1)

        if not _DEPS_OK:
            self._lbl_status.setStyleSheet('color:#ff5252; font-size:10px; background:transparent;')
            self._lbl_status.setText(_DEPS_MSG)

    def _sep(self, layout):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

    def _sep_left(self, layout):
        """Thin separator for the left panel."""
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet('color:#cccccc;')
        layout.addWidget(line)

    # ── Preset management ─────────────────────────────────────────────────────

    def _load_presets_combo(self):
        self._combo_preset.blockSignals(True)
        self._combo_preset.clear()
        self._combo_preset.addItem('RTH Stack (padrão / default)', _RTH_STACK_PRESET)
        for name, data in self._user_presets().items():
            self._combo_preset.addItem(name, data)
        self._combo_preset.addItem('— Personalizado / Custom —', None)
        self._combo_preset.blockSignals(False)
        self._on_preset_selected(self._combo_preset.currentIndex())

    def _user_presets(self):
        raw = QSettings().value(_SETTINGS_PRESETS, '{}')
        try:
            return json.loads(raw) if isinstance(raw, str) else {}
        except Exception:
            return {}

    def _save_user_presets(self, presets):
        QSettings().setValue(_SETTINGS_PRESETS, json.dumps(presets))

    def _on_preset_selected(self, idx):
        data      = self._combo_preset.itemData(idx)
        is_custom = data is None

        # Custom index button only makes sense when user controls checkboxes freely
        self._btn_add_idx.setEnabled(is_custom)

        if is_custom:
            for chk in self._chk_bands.values():
                chk.setEnabled(True)
            for chk in self._chk_indices.values():
                chk.setEnabled(True)
        else:
            for key, chk in self._chk_bands.items():
                chk.setChecked(key in data.get('bands', []))
                chk.setEnabled(False)
            for key, chk in self._chk_indices.items():
                is_preset_idx = key in _STACK_INDICES
                chk.setChecked(key in data.get('indices', []) if is_preset_idx else False)
                chk.setEnabled(False)

    def _on_save_preset(self):
        bands   = [k for k, c in self._chk_bands.items()   if c.isChecked()]
        indices = [k for k, c in self._chk_indices.items() if c.isChecked()]
        if not bands and not indices:
            self._status('Selecione ao menos uma banda ou índice. / '
                         'Select at least one band or index.')
            return
        name, ok = QInputDialog.getText(
            self, 'Salvar Preset / Save Preset',
            'Nome do preset / Preset name:')
        if not ok or not name.strip():
            return
        presets = self._user_presets()
        presets[name.strip()] = {'bands': bands, 'indices': indices}
        self._save_user_presets(presets)
        self._load_presets_combo()
        self._status('Preset "{}" salvo. / Preset "{}" saved.'.format(name, name))

    def _on_delete_preset(self):
        idx  = self._combo_preset.currentIndex()
        name = self._combo_preset.currentText()
        data = self._combo_preset.itemData(idx)
        if data is _RTH_STACK_PRESET or data is None:
            self._status('Não é possível excluir o preset padrão. / '
                         'Cannot delete the default preset.')
            return
        presets = self._user_presets()
        presets.pop(name, None)
        self._save_user_presets(presets)
        self._load_presets_combo()
        self._status('Preset "{}" excluído. / Preset "{}" deleted.'.format(name, name))

    # ── Custom index ──────────────────────────────────────────────────────────

    _FORMULA_VARS_HINT = (
        u'Variáveis disponíveis / Available variables:\n'
        u'  blue (B02), green (B03), red (B04)\n'
        u'  rededge1 (B05), rededge2 (B06), rededge3 (B07)\n'
        u'  nir (B08), nir_narrow (B8A)\n'
        u'  swir1 (B11), swir2 (B12)\n'
        u'  np  (numpy)\n'
        u'\nExemplos / Examples:\n'
        u'  NDMI : (nir - swir1) / (nir + swir1)\n'
        u'  NBR  : (nir - swir2) / (nir + swir2)\n'
        u'  NDRE : (nir - rededge1) / (nir + rededge1)\n'
        u'  CLG  : (nir / green) - 1'
    )

    def _on_add_custom_index(self):
        name, ok = QInputDialog.getText(
            self,
            'Nome do Índice / Index Name',
            'Nome curto (ex: NDMI, NBR) / Short name (e.g. NDMI, NBR):')
        if not ok or not name.strip():
            return
        key = name.strip().upper().replace(' ', '_')

        if key in _STACK_INDICES or key in self._custom_indices:
            self._status(
                'Índice "{}" já existe. / Index "{}" already exists.'.format(key, key))
            return

        formula, ok = QInputDialog.getText(
            self,
            'Fórmula / Formula — {}'.format(key),
            self._FORMULA_VARS_HINT + '\n\nFórmula / Formula:')
        if not ok or not formula.strip():
            return
        formula = formula.strip()

        from tools.field_analysis.tool_field_analysis import _BAND_VARS
        used_vars = [v for v in _BAND_VARS if v in formula]
        if not used_vars:
            self._status(
                u'Nenhuma variável de banda reconhecida na fórmula. / '
                u'No recognised band variable in formula. '
                u'Use: {}'.format(', '.join(_BAND_VARS.keys())))
            return

        try:
            import numpy as np
            dummy  = {v: np.ones((4, 4), dtype='float32') for v in used_vars}
            result = eval(formula, {'__builtins__': {}}, {**dummy, 'np': np})   # noqa: S307
            if not hasattr(result, 'shape'):
                raise ValueError('Formula must return an array / Fórmula deve retornar array')
        except Exception as ex:
            self._status(
                u'Fórmula inválida: {} / Invalid formula: {}'.format(ex, ex))
            return

        label = '{} — {}'.format(key, formula[:40])
        defn  = {'label': label, 'vars': used_vars, 'formula': formula}
        self._custom_indices[key] = defn

        n_existing = len(self._chk_indices)
        cols_idx   = 2
        row        = n_existing // cols_idx
        col        = n_existing % cols_idx
        chk = QCheckBox(label)
        chk.setChecked(True)
        self._idx_grid.addWidget(chk, row, col)
        self._chk_indices[key] = chk

        current_data = self._combo_preset.currentData()
        chk.setEnabled(current_data is None)

        self._status(
            u'Índice "{}" adicionado. / Index "{}" added.'.format(key, key))

    # ── Scene search ──────────────────────────────────────────────────────────

    def _on_search(self):
        if self._search_thread and self._search_thread.isRunning():
            return

        # Search always uses canvas bbox — no need for a combo here.
        bbox = get_bbox_from_canvas(self.iface)
        if bbox is None:
            self._status('Não foi possível determinar a área. / '
                         'Could not determine the area.')
            return

        self._list_scenes.clear()
        self._features = []
        self._lbl_scenes_count.setText('Cenas / Scenes: buscando… / searching…')
        self._status('Buscando cenas... / Searching scenes...')

        params = {
            'coll_id':   self._combo_coll.currentData(),
            'bbox':      bbox,
            'date_ini':  self._date_ini.date().toString('yyyy-MM-dd'),
            'date_fim':  self._date_fim.date().toString('yyyy-MM-dd'),
            'cloud_max': self._spin_cloud.value(),
        }
        self._search_thread = _StacSearchThread(params, parent=self)
        self._search_thread.result.connect(self._on_search_done)
        self._search_thread.error.connect(self._on_search_error)
        self._search_thread.start()

    def _on_search_done(self, features):
        self._features = features
        self._list_scenes.clear()

        if not features:
            self._lbl_scenes_count.setText(
                'Cenas / Scenes: nenhuma encontrada / none found')
            self._status('Nenhuma cena encontrada. / No scenes found.')
            return

        self._lbl_scenes_count.setText(
            'Cenas / Scenes — {} encontrada(s) / found (selecione uma / select one):'.format(
                len(features)))

        thumb_items = []
        for i, f in enumerate(features):
            label = self._scene_label(f)
            item  = QListWidgetItem(label)
            item.setSizeHint(QSize(0, 132))
            self._list_scenes.addItem(item)
            url = _thumb_url(f)
            if url:
                thumb_items.append((i, url))

        self._list_scenes.setCurrentRow(0)
        self._status('{} cena(s) encontrada(s). / {} scene(s) found.'.format(
            len(features), len(features)))

        # Load thumbnails asynchronously
        if thumb_items:
            if self._thumb_loader and self._thumb_loader.isRunning():
                self._thumb_loader.terminate()
                self._thumb_loader.wait(500)
            self._thumb_loader = _ThumbLoaderML(thumb_items, parent=self)
            self._thumb_loader.ready.connect(self._on_thumb_ready)
            self._thumb_loader.start()

    def _on_thumb_ready(self, row, raw_bytes):
        item = self._list_scenes.item(row)
        if item is None or not raw_bytes:
            return
        try:
            px = QPixmap()
            px.loadFromData(QByteArray(raw_bytes))
            if not px.isNull():
                item.setIcon(QIcon(
                    px.scaled(90, 68, _KEEP_ASPECT, _SMOOTH)))
        except Exception:
            pass

    def _on_search_error(self, msg):
        self._lbl_scenes_count.setText('Cenas / Scenes: erro / error')
        self._status('Erro de busca / Search error: ' + msg)

    def _scene_label(self, feature):
        try:
            sid   = feature.get('id', '—')
            props = feature.get('properties', {})
            date  = props.get('datetime', props.get('start_datetime', ''))[:10]
            cloud = props.get('eo:cloud_cover', props.get('cloud_cover', '?'))
            if isinstance(cloud, float):
                cloud = '{:.1f}'.format(cloud)
            return '{} | {} | ☁ {}%'.format(date, sid[:32], cloud)
        except Exception:
            return feature.get('id', '—')

    # ── Stack execution ───────────────────────────────────────────────────────

    def _on_browse(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Salvar Stack / Save Stack', '', 'GeoTIFF (*.tif *.tiff)')
        if path:
            if not path.lower().endswith('.tif'):
                path += '.tif'
            self._edit_out.setText(path)

    def _on_run(self):
        if not _DEPS_OK:
            self._status(_DEPS_MSG)
            return
        if self._build_thread and self._build_thread.isRunning():
            self._status('Processando... / Processing...')
            return

        row = self._list_scenes.currentRow()
        if row < 0 or row >= len(self._features):
            self._status('Selecione uma cena na lista. / Select a scene from the list.')
            return
        feature = self._features[row]

        sel_bands   = [k for k, c in self._chk_bands.items()   if c.isChecked()]
        sel_indices = [k for k, c in self._chk_indices.items() if c.isChecked()]
        if not sel_bands and not sel_indices:
            self._status('Selecione ao menos uma banda ou índice. / '
                         'Select at least one band or index.')
            return

        out_path = self._edit_out.text().strip()
        if not out_path:
            self._status('Informe o caminho de saída. / Enter the output path.')
            return
        if not out_path.lower().endswith('.tif'):
            out_path += '.tif'

        # Determine clip/download bbox
        clip_mode = self._combo_clip.currentData()
        if clip_mode == 'scene':
            raw_bbox = feature.get('bbox')
            if not raw_bbox or len(raw_bbox) < 4:
                self._status(
                    'Cena sem bbox definido no STAC. / Scene has no bbox in STAC.')
                return
            bbox = list(raw_bbox)
        elif clip_mode == 'layer':
            lyr = self.iface.activeLayer()
            if lyr is None:
                self._status('Nenhuma camada ativa. / No active layer.')
                return
            try:
                from tools.field_analysis.tool_field_analysis import _bbox_from_layer
                bbox = _bbox_from_layer(lyr, selected_only=True)
            except Exception as e:
                self._status('Erro de bbox: {} / BBox error: {}'.format(e, e))
                return
        else:
            bbox = get_bbox_from_canvas(self.iface)

        if bbox is None:
            self._status('Não foi possível determinar a área. / '
                         'Could not determine the area.')
            return

        n_bands = len(sel_bands) + len(sel_indices)
        self._progress_dlg = QProgressDialog(
            'Processando... / Processing...', 'Cancelar / Cancel',
            0, n_bands + 1, self)
        self._progress_dlg.setWindowTitle('RTH Stack ML')
        self._progress_dlg.setMinimumDuration(500)

        self._btn_run.setEnabled(False)
        self._status('Iniciando empilhamento... / Starting stack...')

        self._build_thread = _StackBuildThread(
            feature, bbox, sel_bands, sel_indices, out_path,
            custom_indices=self._custom_indices, parent=self)
        self._build_thread.progress.connect(self._on_build_progress)
        self._build_thread.done.connect(self._on_build_done)
        self._build_thread.error.connect(self._on_build_error)

        if self._progress_dlg:
            self._progress_dlg.canceled.connect(self._build_thread.cancel)

        self._build_thread.start()

    def _on_build_progress(self, current, total, msg):
        self._status(msg)
        if self._progress_dlg:
            self._progress_dlg.setValue(current)
            self._progress_dlg.setLabelText(msg)
            QApplication.processEvents()

    def _on_build_done(self, out_path):
        if self._progress_dlg:
            self._progress_dlg.setValue(self._progress_dlg.maximum())
            self._progress_dlg = None

        layer_name = os.path.splitext(os.path.basename(out_path))[0]
        lyr = QgsRasterLayer(out_path, layer_name)
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
            self._status(
                'Stack criado com {} banda(s): {} / '
                'Stack created with {} band(s): {}'.format(
                    lyr.bandCount(), out_path,
                    lyr.bandCount(), out_path))
            self.iface.messageBar().pushMessage(
                'RTH Stack ML',
                'Stack gerado com {} bandas / Stack generated with {} bands'.format(
                    lyr.bandCount(), lyr.bandCount()),
                level=Qgis.MessageLevel.Success, duration=6)
        else:
            self._status('Arquivo gerado mas inválido como raster / '
                         'File generated but invalid as raster: {}'.format(out_path))
        self._btn_run.setEnabled(True)

    def _on_build_error(self, msg):
        if self._progress_dlg:
            self._progress_dlg.close()
            self._progress_dlg = None
        self._status('Erro / Error: ' + msg)
        self._btn_run.setEnabled(True)

    def _status(self, msg):
        self._lbl_status.setText(msg)
        QApplication.processEvents()


# ── Tool entry point ──────────────────────────────────────────────────────────

class StackMLTool:

    def __init__(self, iface):
        self.iface = iface
        self._dlg  = None

    def run(self):
        if self._dlg is None:
            self._dlg = StackMLDialog(self.iface, parent=self.iface.mainWindow())
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
