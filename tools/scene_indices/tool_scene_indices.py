# -*- coding: utf-8 -*-
"""
tool_scene_indices.py

Índices de Vegetação em Cena — igual ao de Talhão, mas usa a extensão atual
do canvas em vez de um polígono selecionado. Sem cutline de polígono.

Vegetation Indices in Scene — same as Field Analysis but uses current canvas
extent instead of a selected polygon. No polygon cutline mask.
"""

import os
import re
import tempfile

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QComboBox, QFrame, QGroupBox, QWidget, QScrollArea,
    QApplication, QMessageBox, QListWidget, QListWidgetItem,
    QProgressDialog, QFileDialog, QLineEdit, QCheckBox,
    QDateEdit, QSpinBox, QToolButton,
)
from qgis.PyQt.QtCore import Qt, QDate
from qgis.PyQt.QtGui import QPixmap
from qgis.core import (
    Qgis, QgsProject, QgsRasterLayer,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsRasterBandStats,
)

# Importa EXATAMENTE os mesmos helpers que o Talhão usa
# Import exactly the same helpers as the Field Analysis tool uses
from core.rth_stac_api import search_stac
from core.rth_layer_utils import collapse_layer

# Compartilha constantes e helpers com o módulo Talhão para evitar duplicação
# Shares constants and helpers with the Field Analysis module to avoid duplication
from tools.field_analysis.tool_field_analysis import (
    _COLLECTIONS, _BAND_VARS, _INDEX_DEFS, _NODATA,
    _DEPS_OK, _DEPS_MSG,
    _init_gdal, _scene_utm, _clip_band, _ds_to_array,
    _match_shape, _eval_formula, _write_tiff, _apply_pseudocolor,
    _find_thumbnail_url, _ThumbFetcher, _parse_s2_id,
)

try:
    import numpy as np
except ImportError:
    np = None


# ── Bbox do canvas (equivalente a _bbox_from_layer do Talhão) ─────────────────

def _bbox_from_canvas(iface):
    """Retorna [min_lon, min_lat, max_lon, max_lat] em WGS84 da extensão atual do canvas.
    Return [min_lon, min_lat, max_lon, max_lat] in WGS84 from current canvas extent.
    """
    wgs84  = QgsCoordinateReferenceSystem('EPSG:4326')
    canvas = iface.mapCanvas()
    ext    = canvas.extent()
    crs    = canvas.mapSettings().destinationCrs()
    if crs != wgs84:
        xf  = QgsCoordinateTransform(crs, wgs84, QgsProject.instance())
        ext = xf.transformBoundingBox(ext)
    return [
        round(ext.xMinimum(), 6),
        round(ext.yMinimum(), 6),
        round(ext.xMaximum(), 6),
        round(ext.yMaximum(), 6),
    ]


# ── Dialog ────────────────────────────────────────────────────────────────────

class SceneIndicesDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._thumb_fetcher = None
        self._features = []

        self.setWindowTitle(u'RTH — Índices de Vegetação em Cena / Vegetation Indices in Scene')
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(580)
        self.setMinimumHeight(660)
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
        lbl_t = QLabel(u'Índices de Vegetação em Cena / Vegetation Indices in Scene')
        lbl_t.setAlignment(Qt.AlignCenter)
        lbl_t.setStyleSheet('font-size:13px;font-weight:bold;')
        root.addWidget(lbl_t)

        lbl_s = QLabel(
            u'Busca cenas Sentinel-2 na extensão do canvas e computa índices sem download da cena completa.\n'
            u'Searches Sentinel-2 in the canvas extent and computes indices — no full scene download (COG).\n'
            u'⚠  Zoom até a área de interesse antes de buscar. / Zoom to the area of interest before searching.')
        lbl_s.setAlignment(Qt.AlignCenter)
        lbl_s.setStyleSheet('color:#555;font-size:10px;')
        lbl_s.setWordWrap(True)
        root.addWidget(lbl_s)

        if not _DEPS_OK:
            lbl_dep = QLabel(u'⚠  Dependências ausentes / Missing deps: numpy, gdal — ' + _DEPS_MSG)
            lbl_dep.setWordWrap(True)
            lbl_dep.setStyleSheet(
                'color:#b71c1c;background:#ffebee;border:1px solid #e57373;'
                'border-radius:3px;padding:4px;font-size:10px;')
            root.addWidget(lbl_dep)

        root.addWidget(self._sep())

        # ── Extensão / Extent info ────────────────────────────────────────────
        grp_ext = QGroupBox(u'Área de Busca / Search Area')
        gl_e = QGridLayout()
        gl_e.setContentsMargins(8, 6, 8, 8)
        gl_e.setSpacing(4)
        gl_e.setColumnStretch(1, 1)
        gl_e.addWidget(QLabel(u'Extensão / Extent:'), 0, 0)
        self.lbl_extent = QLabel(u'—')
        self.lbl_extent.setStyleSheet('font-weight:bold;font-size:10px;color:#1565c0;')
        self.lbl_extent.setWordWrap(True)
        gl_e.addWidget(self.lbl_extent, 0, 1)
        lbl_hint = QLabel(
            u'Ajuste o zoom antes de buscar — áreas muito grandes podem ser lentas ou gerar timeout.\n'
            u'Adjust zoom before searching — very large areas can be slow or time out.')
        lbl_hint.setStyleSheet('color:#888;font-size:9px;')
        lbl_hint.setWordWrap(True)
        gl_e.addWidget(lbl_hint, 1, 0, 1, 2)
        grp_ext.setLayout(gl_e)
        root.addWidget(grp_ext)

        # ── Busca / Search ────────────────────────────────────────────────────
        grp_search = QGroupBox(u'Busca de Imagem Sentinel-2 / Scene Search')
        gl_s = QGridLayout()
        gl_s.setContentsMargins(8, 6, 8, 8)
        gl_s.setSpacing(6)
        gl_s.setColumnStretch(1, 1)

        gl_s.addWidget(QLabel(u'Coleção / Collection:'), 0, 0)
        self.combo_coll = QComboBox()
        for cid, clabel in _COLLECTIONS:
            self.combo_coll.addItem(clabel, cid)
        gl_s.addWidget(self.combo_coll, 0, 1)

        gl_s.addWidget(QLabel(u'Data inicial / From:'), 1, 0)
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addDays(-90))
        self.date_from.setDisplayFormat('yyyy-MM-dd')
        gl_s.addWidget(self.date_from, 1, 1)

        gl_s.addWidget(QLabel(u'Data final / To:'), 2, 0)
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setDisplayFormat('yyyy-MM-dd')
        gl_s.addWidget(self.date_to, 2, 1)

        gl_s.addWidget(QLabel(u'Nuvem máx. / Max cloud:'), 3, 0)
        self.spin_cloud = QSpinBox()
        self.spin_cloud.setRange(0, 100)
        self.spin_cloud.setValue(20)
        self.spin_cloud.setSuffix(' %')
        gl_s.addWidget(self.spin_cloud, 3, 1)

        btn_search = QPushButton(u'Buscar Cenas / Search Scenes')
        btn_search.setStyleSheet(
            'QPushButton{background:#0277bd;color:white;border-radius:4px;'
            'border:none;padding:5px 10px;font-weight:bold;}'
            'QPushButton:hover{background:#01579b;}')
        btn_search.clicked.connect(self._on_search)
        gl_s.addWidget(btn_search, 4, 0, 1, 2)

        # Lista de cenas + thumbnail
        scene_row = QHBoxLayout()
        scene_row.setContentsMargins(0, 0, 0, 0)
        scene_row.setSpacing(6)

        self.list_scenes = QListWidget()
        self.list_scenes.setMinimumHeight(120)
        self.list_scenes.setMaximumHeight(190)
        self.list_scenes.setToolTip(u'Selecione uma cena / Select a scene')
        self.list_scenes.currentItemChanged.connect(self._on_scene_selected)
        scene_row.addWidget(self.list_scenes, 1)

        self._thumb_label = QLabel(u'Sem prévia\nNo preview')
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

        self.lbl_status = QLabel(u'Clique em Buscar para encontrar cenas / Click Search to find scenes')
        self.lbl_status.setStyleSheet('color:#666;font-size:10px;')
        gl_s.addWidget(self.lbl_status, 6, 0, 1, 2)

        grp_search.setLayout(gl_s)
        root.addWidget(grp_search)

        # ── Bandas (colapsável) ───────────────────────────────────────────────
        self._btn_bands = QToolButton()
        self._btn_bands.setCheckable(True)
        self._btn_bands.setChecked(False)
        self._btn_bands.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._btn_bands.setStyleSheet(
            'QToolButton{border:1px solid #bbb;border-radius:3px;padding:3px 6px;'
            'background:#f5f5f5;font-weight:bold;font-size:10px;text-align:left;}'
            'QToolButton:checked{background:#e3f2fd;}')
        self._btn_bands.toggled.connect(self._toggle_bands)
        self._btn_bands.setText(u'▶  Bandas utilizadas / Bands used')
        root.addWidget(self._btn_bands)

        self._wgt_bands = QWidget()
        bands_grid = QGridLayout(self._wgt_bands)
        bands_grid.setContentsMargins(8, 4, 8, 4)
        bands_grid.setSpacing(3)
        bands_grid.addWidget(QLabel('<b>Variável</b>'), 0, 0)
        bands_grid.addWidget(QLabel('<b>Banda S-2</b>'), 0, 1)
        bands_grid.addWidget(QLabel('<b>Resolução</b>'), 0, 2)
        for r, (var, band, res) in enumerate([
            ('nir', 'B08', '10 m'), ('red', 'B04', '10 m'),
            ('green', 'B03', '10 m'), ('blue', 'B02', '10 m'),
            ('swir1', 'B11', '20 m'), ('swir2', 'B12', '20 m'),
            ('rededge', 'B05', '20 m'), ('rededge2', 'B06', '20 m'),
            ('rededge3', 'B07', '20 m'), ('nir2', 'B8A', '20 m'),
        ], start=1):
            bands_grid.addWidget(QLabel(var), r, 0)
            bands_grid.addWidget(QLabel(band), r, 1)
            bands_grid.addWidget(QLabel(res), r, 2)
        self._wgt_bands.setStyleSheet(
            'QWidget{background:#fafafa;border:1px solid #ddd;border-radius:3px;}'
            'QLabel{border:none;font-size:10px;padding:1px 4px;}')
        self._wgt_bands.setVisible(False)
        root.addWidget(self._wgt_bands)

        # ── Índice ────────────────────────────────────────────────────────────
        grp_idx = QGroupBox(u'Índice de Vegetação / Vegetation Index')
        gl_i = QGridLayout()
        gl_i.setContentsMargins(8, 6, 8, 8)
        gl_i.setSpacing(6)
        gl_i.setColumnStretch(1, 1)

        gl_i.addWidget(QLabel(u'Índice / Index:'), 0, 0)
        self.combo_index = QComboBox()
        for key, defn in _INDEX_DEFS.items():
            self.combo_index.addItem(defn['label'], key)
        self.combo_index.currentIndexChanged.connect(self._on_index_changed)
        gl_i.addWidget(self.combo_index, 0, 1)

        self.lbl_formula = QLabel(u'Fórmula / Formula:')
        self.edit_formula = QLineEdit()
        self.edit_formula.setPlaceholderText(u'Ex: (nir - red) / (nir + red)')
        self.lbl_hint = QLabel(
            u'Variáveis / Variables: nir, red, green, blue, swir1, swir2, '
            u'rededge, rededge2, rededge3, nir2  ·  Use np. para funções numpy / for numpy functions')
        self.lbl_hint.setStyleSheet(
            'color:#555;font-size:9px;background:#f5f5f5;border-radius:3px;padding:3px;')
        self.lbl_hint.setWordWrap(True)
        gl_i.addWidget(self.lbl_formula, 1, 0)
        gl_i.addWidget(self.edit_formula, 1, 1)
        gl_i.addWidget(self.lbl_hint, 2, 0, 1, 2)

        grp_idx.setLayout(gl_i)
        root.addWidget(grp_idx)

        # ── Saída ─────────────────────────────────────────────────────────────
        grp_out = QGroupBox(u'Saída / Output')
        gl_o = QGridLayout()
        gl_o.setContentsMargins(8, 6, 8, 8)
        gl_o.setSpacing(6)
        gl_o.setColumnStretch(1, 1)

        gl_o.addWidget(QLabel(u'Arquivo de saída / Output file:'), 0, 0)
        row_out = QHBoxLayout()
        row_out.setContentsMargins(0, 0, 0, 0)
        self.edit_output = QLineEdit()
        self.edit_output.setPlaceholderText(u'(vazio = pasta temporária / empty = temp folder)')
        row_out.addWidget(self.edit_output)
        btn_browse = QPushButton('...')
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._browse_output)
        row_out.addWidget(btn_browse)
        gl_o.addLayout(row_out, 0, 1)

        gl_o.addWidget(QLabel(u'Nome da camada / Layer name:'), 1, 0)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText('NDVI_Cena')
        gl_o.addWidget(self.edit_name, 1, 1)

        self.chk_load = QCheckBox(u'Carregar no QGIS após / Load in QGIS after')
        self.chk_load.setChecked(True)
        self.chk_load.setStyleSheet('font-size:10px;')
        gl_o.addWidget(self.chk_load, 2, 0, 1, 2)

        grp_out.setLayout(gl_o)
        root.addWidget(grp_out)

        # ── Info note ─────────────────────────────────────────────────────────
        lbl_note = QLabel(
            u'ℹ  Apenas a região visível do canvas é lida — sem download da cena completa (COG via vsicurl).\n'
            u'   Requer conexão com internet. Planetary Computer: sem autenticação necessária.\n'
            u'   Only the visible canvas region is read — no full scene download (COG via vsicurl).\n'
            u'   Requires internet. Planetary Computer: no authentication needed.')
        lbl_note.setStyleSheet(
            'font-size:9px;color:#555;background:#fffde7;border:1px solid #f9a825;'
            'border-radius:3px;padding:5px;')
        lbl_note.setWordWrap(True)
        root.addWidget(lbl_note)

        # ── Botões ────────────────────────────────────────────────────────────
        outer.addWidget(self._sep())
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 6, 12, 12)

        self.btn_run = QPushButton(u'Gerar Índice / Generate Index')
        self.btn_run.setMinimumHeight(38)
        self.btn_run.setStyleSheet(
            'QPushButton{background:#2e7d32;color:white;font-weight:bold;'
            'font-size:12px;border-radius:5px;border:none;}'
            'QPushButton:hover{background:#1b5e20;}'
            'QPushButton:disabled{background:#4a7a4b;color:#aaa;}')
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)

        btn_close = QPushButton(u'Fechar / Close')
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
            (u'▼' if checked else u'▶') + u'  Bandas utilizadas / Bands used')

    def _on_index_changed(self):
        is_custom = (self.combo_index.currentData() == 'Custom')
        self.lbl_formula.setVisible(is_custom)
        self.edit_formula.setVisible(is_custom)
        self.lbl_hint.setVisible(is_custom)
        current = self.edit_name.text().strip()
        new_key = self.combo_index.currentData() or ''
        if current and new_key:
            for key in _INDEX_DEFS:
                if re.match(r'^' + re.escape(key) + r'_', current):
                    self.edit_name.setText(new_key + current[len(key):])
                    break

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, u'Salvar índice / Save index', '', 'GeoTIFF (*.tif)')
        if path:
            if not path.lower().endswith('.tif'):
                path += '.tif'
            self.edit_output.setText(path)

    # ── Thumbnail ─────────────────────────────────────────────────────────────

    def _on_scene_selected(self, current, _previous):
        if current is None:
            self._thumb_label.setPixmap(QPixmap())
            self._thumb_label.setText(u'Sem prévia\nNo preview')
            return
        feature = current.data(Qt.UserRole)
        if feature is None:
            return
        thumb_url = _find_thumbnail_url(feature)
        if not thumb_url:
            self._thumb_label.setPixmap(QPixmap())
            self._thumb_label.setText(u'Sem prévia\nNo preview')
            return
        self._thumb_label.setText(u'Carregando…\nLoading…')
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

    def _on_thumb_loaded(self, data):
        px = QPixmap()
        if px.loadFromData(data):
            scaled = px.scaled(
                self._thumb_label.width() - 4,
                self._thumb_label.height() - 4,
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._thumb_label.setPixmap(scaled)
            self._thumb_label.setText('')
        else:
            self._thumb_label.setText(u'Sem prévia\nNo preview')

    def _on_thumb_failed(self):
        self._thumb_label.setPixmap(QPixmap())
        self._thumb_label.setText(u'Sem prévia\nNo preview')

    # ── Search — idêntico ao Talhão, bbox vem do canvas ──────────────────────

    def _on_search(self):
        # Obtém bbox da extensão atual do canvas (equivalente a _bbox_from_layer do Talhão)
        # Get bbox from current canvas extent (equivalent to _bbox_from_layer in Field Analysis)
        bbox = _bbox_from_canvas(self.iface)

        self.lbl_extent.setText(u'[{:.4f}, {:.4f}, {:.4f}, {:.4f}]'.format(*bbox))

        coll_id   = self.combo_coll.currentData()
        date_ini  = self.date_from.date().toString('yyyy-MM-dd')
        date_fim  = self.date_to.date().toString('yyyy-MM-dd')
        cloud_max = self.spin_cloud.value()

        self.list_scenes.clear()
        self.lbl_status.setText(u'Buscando cenas... / Searching scenes...')
        QApplication.processEvents()

        try:
            features, _ = search_stac(coll_id, bbox, date_ini, date_fim, cloud_max)
        except Exception as e:
            self.lbl_status.setText(u'Erro / Error: {}'.format(str(e)[:120]))
            QMessageBox.critical(self, 'RTH',
                u'Erro ao buscar cenas / Error searching scenes:\n\n{}'.format(str(e)))
            return

        self._features = features

        if not features:
            self.lbl_status.setText(
                u'Nenhuma cena encontrada. Tente ampliar o período ou o zoom.\n'
                u'No scenes found. Try a wider date range or zoom out.')
            return

        for feat in features:
            props     = feat.get('properties', {})
            cloud     = props.get('eo:cloud_cover')
            cloud_str = u'{:.1f}%'.format(cloud) if cloud is not None else u'?%'
            scene_id  = feat.get('id', 'unknown')
            s_date, mgrs, _suffix = _parse_s2_id(scene_id)
            if not s_date:
                s_date = (props.get('datetime') or '')[:10]
            label = u'{}   ☁ {}   {}'.format(s_date, cloud_str, mgrs or scene_id[:20])
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, feat)
            self.list_scenes.addItem(item)

        self.list_scenes.setCurrentRow(0)
        self.lbl_status.setText(
            u'{} cena(s) encontrada(s) — selecione uma / scene(s) found — select one'.format(
                len(features)))

        if not self.edit_name.text().strip():
            idx_key  = self.combo_index.currentData()
            first_id = features[0].get('id', '')
            _, mgrs0, suffix0 = _parse_s2_id(first_id)
            if suffix0:
                self.edit_name.setText(u'{}_{}Cena'.format(idx_key, suffix0))
            else:
                dt0 = (features[0].get('properties', {}).get('datetime') or '')[:10].replace('-', '')
                self.edit_name.setText(u'{}_{}_Cena'.format(idx_key, dt0))

    # ── Run — idêntico ao Talhão (single mode), sem polígono / cutline ────────

    def _on_run(self):
        if not _DEPS_OK:
            QMessageBox.critical(self, 'RTH',
                u'numpy e/ou gdal não disponíveis.\nnumpy and/or gdal not available.')
            return

        sel_item = self.list_scenes.currentItem()
        if sel_item is None:
            QMessageBox.warning(self, 'RTH',
                u'Selecione uma cena na lista.\nSelect a scene from the list.')
            return

        bbox = _bbox_from_canvas(self.iface)

        feature   = sel_item.data(Qt.UserRole)
        index_key = self.combo_index.currentData()
        defn      = _INDEX_DEFS[index_key]

        if index_key == 'Custom':
            formula = self.edit_formula.text().strip()
            if not formula:
                QMessageBox.warning(self, 'RTH',
                    u'Digite uma fórmula personalizada.\nEnter a custom formula.')
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

        if base_output:
            out = base_output if base_output.lower().endswith('.tif') else base_output + '.tif'
        else:
            out = os.path.join(
                tempfile.gettempdir(),
                'rth_cena_{}_{}.tif'.format(
                    index_key, re.sub(r'[^\w]', '_', scene_id[:20])))

        name = base_name or '{}_Cena_{}'.format(index_key, suffix0) or index_key

        progress = QProgressDialog(
            u'Calculando {}... / Computing {}...'.format(index_key, index_key),
            None, 0, 1, self)
        progress.setWindowTitle(u'RTH — Índices em Cena / Scene Indices')
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        self.btn_run.setEnabled(False)
        QApplication.processEvents()

        error = None
        result_path = None
        try:
            result_path = self._compute(feature, index_key, formula, bbox, out)
            progress.setValue(1)
        except Exception as e:
            error = str(e)
        finally:
            progress.close()
            self.btn_run.setEnabled(True)

        if error:
            QMessageBox.critical(self, u'RTH — Índices em Cena / Scene Indices',
                u'Erro / Error:\n\n' + error)
            return

        if self.chk_load.isChecked() and result_path:
            rlayer = QgsRasterLayer(result_path, name)
            if rlayer.isValid():
                QgsProject.instance().addMapLayer(rlayer)
                collapse_layer(rlayer)
                stats = rlayer.dataProvider().bandStatistics(
                    1, QgsRasterBandStats.Min | QgsRasterBandStats.Max,
                    rlayer.extent(), 0)
                r_min, r_max = stats.minimumValue, stats.maximumValue
                _apply_pseudocolor(rlayer,
                                   r_min if r_min < r_max else vmin,
                                   r_max if r_min < r_max else vmax)
                self.iface.messageBar().pushMessage(
                    u'RTH Cena',
                    u'{} gerado e carregado / generated and loaded'.format(index_key),
                    level=Qgis.MessageLevel.Success, duration=6)
            else:
                QMessageBox.warning(self, 'RTH',
                    u'Camada inválida / Invalid layer:\n' + result_path)
        elif result_path:
            self.iface.messageBar().pushMessage(
                u'RTH Cena',
                u'{} salvo / saved: {}'.format(index_key, result_path),
                level=Qgis.MessageLevel.Info, duration=5)

    # ── Compute — igual ao Talhão mas SEM cutline de polígono ────────────────

    def _compute(self, feature, index_key, formula, bbox_wgs84, output_path):
        """Recorta bandas S-2 ao bbox do canvas e calcula o índice — sem cutline.
        Clips S-2 bands to canvas bbox and evaluates the index — no polygon cutline.
        """
        gdal = _init_gdal()
        if gdal is None:
            raise RuntimeError(u'GDAL não disponível / GDAL not available')

        target_crs = _scene_utm(feature)

        if index_key == 'Custom':
            needed = [v for v in _BAND_VARS if re.search(r'\b' + v + r'\b', formula)]
            if not needed:
                raise ValueError(
                    u'Nenhuma variável de banda reconhecida na fórmula.\n'
                    u'No recognized band variable in formula.\n'
                    u'Use: {}'.format(', '.join(_BAND_VARS.keys())))
        else:
            needed = _INDEX_DEFS[index_key]['vars']

        datasets  = {}
        ref_gt    = None
        ref_proj  = None
        ref_shape = None

        try:
            for var in needed:
                QApplication.processEvents()
                ds = _clip_band(feature, _BAND_VARS[var], bbox_wgs84, gdal,
                                target_crs, cutline_path=None)
                if ds is None:
                    raise ValueError(
                        u'Banda {} ({}) não encontrada na cena selecionada.\n'
                        u'Band {} ({}) not found in the selected scene.'.format(
                            _BAND_VARS[var], var, _BAND_VARS[var], var))
                if ref_gt is None:
                    ref_gt    = ds.GetGeoTransform()
                    ref_proj  = ds.GetProjection()
                    ref_shape = (ds.RasterYSize, ds.RasterXSize)
                datasets[var] = ds

            arrays = {}
            for var, ds in datasets.items():
                arr = _ds_to_array(ds)
                arrays[var] = _match_shape(arr, ref_shape)

            result = _eval_formula(formula, arrays)
            _write_tiff(result, ref_gt, ref_proj, output_path)

        finally:
            for ds in datasets.values():
                del ds

        return output_path

    def closeEvent(self, event):
        if self._thumb_fetcher and self._thumb_fetcher.isRunning():
            self._thumb_fetcher.quit()
            self._thumb_fetcher.wait(2000)
        super().closeEvent(event)


# ── Tool class ────────────────────────────────────────────────────────────────

class SceneIndicesTool:

    def __init__(self, iface):
        self.iface   = iface
        self._dialog = None

    def run(self):
        if self._dialog is None or not self._dialog.isVisible():
            self._dialog = SceneIndicesDialog(self.iface)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
