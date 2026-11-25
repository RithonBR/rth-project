# -*- coding: utf-8 -*-
"""
tool_drone_dem.py

Geração de MDE/MDT de Drone — cria Modelos Digitais de Elevação (MDE/DSM)
ou Modelos Digitais de Terreno (MDT/DTM) a partir de:

  • Tiles raster de elevação (GeoTIFF) — mescla via GDAL Merge
  • Nuvem de pontos LAS/LAZ — rasteriza via PDAL (requer QGIS com PDAL)

Opções de pós-processamento: Hillshade, Curvas de Nível e preenchimento
de vazios (Fill NoData).

---

Drone DEM/DTM Generation — creates Digital Elevation Models (DEM/DSM)
or Digital Terrain Models (DTM) from:

  • Elevation raster tiles (GeoTIFF) — merged via GDAL Merge
  • LAS/LAZ point clouds — rasterized via PDAL (requires QGIS with PDAL)

Post-processing options: Hillshade, Contour Lines, Fill NoData holes.
"""

import os
import glob as _glob

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QComboBox, QDoubleSpinBox, QSpinBox, QFrame, QGroupBox,
    QWidget, QScrollArea, QApplication, QMessageBox, QListWidget,
    QListWidgetItem, QProgressDialog, QFileDialog, QLineEdit,
    QCheckBox, QRadioButton, QButtonGroup, QAbstractItemView,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import Qgis, QgsProject, QgsRasterLayer, QgsVectorLayer
from core.rth_layer_utils import collapse_layer


# ─── Supported extensions ─────────────────────────────────────────────────────

_RASTER_EXTS = ('.tif', '.tiff', '.img', '.jp2', '.vrt')
_LAS_EXTS    = ('.las', '.laz', '.copc.laz')

# gdal:merge DATA_TYPE codes
_DATA_TYPES = [
    ('Float32 (recomendado / recommended)', 6),
    ('Float64',                             7),
    ('Int16',                               3),
]


# ─── PDAL availability check ──────────────────────────────────────────────────

def _has_pdal():
    try:
        from qgis.core import QgsApplication
        ids = [a.id() for a in QgsApplication.processingRegistry().algorithms()]
        return any('pdal' in a.lower() for a in ids)
    except Exception:
        return False


# ─── Dialog ───────────────────────────────────────────────────────────────────

class DroneDEMDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface

        self.setWindowTitle('RTH — Geracao de MDE/MDT de Drone / Drone DEM/DTM Generation')
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(600)
        self.setMinimumHeight(700)
        self.setMaximumHeight(900)

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
        lbl_t = QLabel('Geracao de MDE / MDT de Drone\nDrone DEM / DTM Generation')
        lbl_t.setAlignment(Qt.AlignCenter)
        lbl_t.setStyleSheet('font-size:13px;font-weight:bold;')
        root.addWidget(lbl_t)
        root.addWidget(self._sep())

        # ── Mode selection ────────────────────────────────────────────────────
        grp_mode = QGroupBox('Fonte de Dados / Data Source')
        gl_mode = QVBoxLayout()
        gl_mode.setContentsMargins(8, 6, 8, 8)
        gl_mode.setSpacing(4)

        self._btn_grp_mode = QButtonGroup(self)
        self.radio_tiles = QRadioButton(
            'Tiles Raster  (GeoTIFF ja georreferenciados de DEM/DSM tileados / '
            'Already-georeferenced tiled DEM/DSM GeoTIFFs)')
        self.radio_tiles.setStyleSheet('font-size:10px;')
        self.radio_tiles.setChecked(True)
        self._btn_grp_mode.addButton(self.radio_tiles, 0)
        gl_mode.addWidget(self.radio_tiles)

        self.radio_las = QRadioButton(
            'Nuvem de Pontos LAS / LAZ  (requer PDAL instalado no QGIS / requires PDAL in QGIS)')
        self.radio_las.setStyleSheet('font-size:10px;')
        self._btn_grp_mode.addButton(self.radio_las, 1)
        gl_mode.addWidget(self.radio_las)

        grp_mode.setLayout(gl_mode)
        root.addWidget(grp_mode)

        self.radio_tiles.toggled.connect(self._on_mode_changed)

        # ── Tiles input panel ─────────────────────────────────────────────────
        self.grp_tiles = QGroupBox('Tiles de Elevacao / Elevation Tiles  (.tif .tiff .img .jp2 .vrt)')
        gl_tiles = QVBoxLayout()
        gl_tiles.setContentsMargins(8, 6, 8, 8)
        gl_tiles.setSpacing(5)

        self.list_tiles = QListWidget()
        self.list_tiles.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_tiles.setMinimumHeight(90)
        self.list_tiles.setMaximumHeight(160)
        gl_tiles.addWidget(self.list_tiles)

        tile_btn_bar = QHBoxLayout()
        for label, slot in [
            ('+ Pasta / + Folder', self._add_tiles_folder),
            ('+ Arquivos / + Files', self._add_tiles_files),
            ('Remover / Remove', self._remove_tiles),
            ('Limpar / Clear', self._clear_tiles),
        ]:
            b = QPushButton(label)
            b.setStyleSheet('font-size:10px;')
            b.clicked.connect(slot)
            tile_btn_bar.addWidget(b)
        gl_tiles.addLayout(tile_btn_bar)

        self.lbl_tile_count = QLabel('0 arquivo(s) / file(s)')
        self.lbl_tile_count.setStyleSheet('color:#666;font-size:10px;')
        gl_tiles.addWidget(self.lbl_tile_count)

        self.grp_tiles.setLayout(gl_tiles)
        root.addWidget(self.grp_tiles)

        # ── LAS input panel ───────────────────────────────────────────────────
        self.grp_las = QGroupBox('Arquivo de Nuvem de Pontos / Point Cloud File  (.las .laz)')
        gl_las = QGridLayout()
        gl_las.setContentsMargins(8, 6, 8, 8)
        gl_las.setSpacing(6)
        gl_las.setColumnStretch(1, 1)

        gl_las.addWidget(QLabel('Arquivo LAS/LAZ / LAS/LAZ File:'), 0, 0)
        row_las = QHBoxLayout()
        row_las.setContentsMargins(0, 0, 0, 0)
        self.edit_las = QLineEdit()
        self.edit_las.setPlaceholderText('caminho/nuvem.laz')
        row_las.addWidget(self.edit_las)
        btn_las = QPushButton('...')
        btn_las.setFixedWidth(32)
        btn_las.clicked.connect(self._browse_las)
        row_las.addWidget(btn_las)
        gl_las.addLayout(row_las, 0, 1)

        gl_las.addWidget(QLabel('Tipo / Type:'), 1, 0)
        self.combo_dem_type = QComboBox()
        self.combo_dem_type.addItem(
            'MDE / DSM  — Modelo Digital de Superficie (todos os pontos / all points)', 'dsm')
        self.combo_dem_type.addItem(
            'MDT / DTM  — Modelo Digital de Terreno (apenas solo, classe 2 / ground class 2)', 'dtm')
        gl_las.addWidget(self.combo_dem_type, 1, 1)

        self.lbl_pdal_status = QLabel('')
        self.lbl_pdal_status.setStyleSheet('font-size:9px;')
        self.lbl_pdal_status.setWordWrap(True)
        gl_las.addWidget(self.lbl_pdal_status, 2, 0, 1, 2)

        self.grp_las.setLayout(gl_las)
        self.grp_las.setVisible(False)
        root.addWidget(self.grp_las)

        # ── Processing options ────────────────────────────────────────────────
        grp_proc = QGroupBox('Processamento / Processing')
        gl_proc = QGridLayout()
        gl_proc.setContentsMargins(8, 6, 8, 8)
        gl_proc.setSpacing(6)
        gl_proc.setColumnStretch(1, 1)

        gl_proc.addWidget(QLabel('Resolucao de saida / Output resolution (m):'), 0, 0)
        self.spin_res = QDoubleSpinBox()
        self.spin_res.setRange(0.01, 1000.0)
        self.spin_res.setValue(1.0)
        self.spin_res.setSuffix(' m')
        self.spin_res.setDecimals(2)
        self.spin_res.setSingleStep(0.5)
        self.spin_res.setToolTip(
            'Tamanho do pixel de saida em metros.\n'
            'Output pixel size in metres.\n'
            'Tipico para drone: 0.05–0.5 m  |  Tipico para tiles: 1–5 m')
        gl_proc.addWidget(self.spin_res, 0, 1)

        gl_proc.addWidget(QLabel('Tipo de dado / Data type:'), 1, 0)
        self.combo_dtype = QComboBox()
        for label, code in _DATA_TYPES:
            self.combo_dtype.addItem(label, code)
        gl_proc.addWidget(self.combo_dtype, 1, 1)

        self.chk_fillnodata = QCheckBox(
            'Preencher vazios (Fill NoData) — preenche buracos no DEM / fill holes in DEM')
        self.chk_fillnodata.setStyleSheet('font-size:10px;')
        gl_proc.addWidget(self.chk_fillnodata, 2, 0, 1, 2)

        grp_proc.setLayout(gl_proc)
        root.addWidget(grp_proc)

        # ── Post-processing ───────────────────────────────────────────────────
        grp_post = QGroupBox('Pos-Processamento / Post-Processing  (opcional / optional)')
        gl_post = QGridLayout()
        gl_post.setContentsMargins(8, 6, 8, 8)
        gl_post.setSpacing(6)
        gl_post.setColumnStretch(1, 1)

        self.chk_hillshade = QCheckBox('Gerar Hillshade (sombreamento de relevo / relief shading)')
        self.chk_hillshade.setStyleSheet('font-size:10px;')
        gl_post.addWidget(self.chk_hillshade, 0, 0, 1, 2)

        row_hs = QHBoxLayout()
        row_hs.setContentsMargins(16, 0, 0, 0)
        row_hs.addWidget(QLabel('Fator Z / Z Factor:'))
        self.spin_zfactor = QDoubleSpinBox()
        self.spin_zfactor.setRange(0.1, 10.0)
        self.spin_zfactor.setValue(1.0)
        self.spin_zfactor.setDecimals(1)
        self.spin_zfactor.setSingleStep(0.5)
        self.spin_zfactor.setEnabled(False)
        row_hs.addWidget(self.spin_zfactor)
        row_hs.addWidget(QLabel('Azimute / Azimuth (°):'))
        self.spin_azimuth = QSpinBox()
        self.spin_azimuth.setRange(0, 360)
        self.spin_azimuth.setValue(315)
        self.spin_azimuth.setEnabled(False)
        row_hs.addWidget(self.spin_azimuth)
        row_hs.addWidget(QLabel('Altitude (°):'))
        self.spin_altitude = QSpinBox()
        self.spin_altitude.setRange(0, 90)
        self.spin_altitude.setValue(45)
        self.spin_altitude.setEnabled(False)
        row_hs.addWidget(self.spin_altitude)
        row_hs.addStretch()
        hs_widget = QWidget()
        hs_widget.setLayout(row_hs)
        gl_post.addWidget(hs_widget, 1, 0, 1, 2)
        self.chk_hillshade.toggled.connect(
            lambda c: (self.spin_zfactor.setEnabled(c),
                       self.spin_azimuth.setEnabled(c),
                       self.spin_altitude.setEnabled(c)))

        self.chk_contours = QCheckBox('Gerar Curvas de Nivel / Generate Contour Lines')
        self.chk_contours.setStyleSheet('font-size:10px;')
        gl_post.addWidget(self.chk_contours, 2, 0, 1, 2)

        row_cnt = QHBoxLayout()
        row_cnt.setContentsMargins(16, 0, 0, 0)
        row_cnt.addWidget(QLabel('Intervalo / Interval (m):'))
        self.spin_interval = QDoubleSpinBox()
        self.spin_interval.setRange(0.1, 100.0)
        self.spin_interval.setValue(1.0)
        self.spin_interval.setSuffix(' m')
        self.spin_interval.setDecimals(1)
        self.spin_interval.setSingleStep(0.5)
        self.spin_interval.setEnabled(False)
        row_cnt.addWidget(self.spin_interval)
        row_cnt.addStretch()
        cnt_widget = QWidget()
        cnt_widget.setLayout(row_cnt)
        gl_post.addWidget(cnt_widget, 3, 0, 1, 2)
        self.chk_contours.toggled.connect(self.spin_interval.setEnabled)

        grp_post.setLayout(gl_post)
        root.addWidget(grp_post)

        # ── Output ────────────────────────────────────────────────────────────
        grp_out = QGroupBox('Saida / Output')
        gl_out = QGridLayout()
        gl_out.setContentsMargins(8, 6, 8, 8)
        gl_out.setSpacing(6)
        gl_out.setColumnStretch(1, 1)

        gl_out.addWidget(QLabel('Arquivo de saida DEM / DEM output file:'), 0, 0)
        row_out = QHBoxLayout()
        row_out.setContentsMargins(0, 0, 0, 0)
        self.edit_output = QLineEdit()
        self.edit_output.setPlaceholderText('caminho/dem.tif')
        row_out.addWidget(self.edit_output)
        btn_out = QPushButton('...')
        btn_out.setFixedWidth(32)
        btn_out.clicked.connect(self._browse_output)
        row_out.addWidget(btn_out)
        gl_out.addLayout(row_out, 0, 1)

        gl_out.addWidget(QLabel('Nome da camada DEM / DEM layer name:'), 1, 0)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText('DEM_Drone')
        gl_out.addWidget(self.edit_name, 1, 1)

        self.chk_compress = QCheckBox('Compressao LZW / LZW Compression (recomendado / recommended)')
        self.chk_compress.setChecked(True)
        self.chk_compress.setStyleSheet('font-size:10px;')
        gl_out.addWidget(self.chk_compress, 2, 0, 1, 2)

        self.chk_load = QCheckBox('Carregar resultados no QGIS / Load results in QGIS')
        self.chk_load.setChecked(True)
        self.chk_load.setStyleSheet('font-size:10px;')
        gl_out.addWidget(self.chk_load, 3, 0, 1, 2)

        grp_out.setLayout(gl_out)
        root.addWidget(grp_out)

        # ── Note ──────────────────────────────────────────────────────────────
        lbl_note = QLabel(
            'ℹ  Para fotogrametria completa (SfM/MVS) use OpenDroneMap, Pix4D ou Agisoft Metashape.\n'
            '   Este modulo trabalha com dados ja processados (tiles de elevacao ou nuvem de pontos).\n'
            '   For full photogrammetry (SfM/MVS) use OpenDroneMap, Pix4D or Agisoft Metashape.\n'
            '   This module works with already-processed data (elevation tiles or point clouds).')
        lbl_note.setStyleSheet(
            'font-size:9px;color:#555;background:#fffde7;border:1px solid #f9a825;'
            'border-radius:3px;padding:5px;')
        lbl_note.setWordWrap(True)
        root.addWidget(lbl_note)

        # ── Buttons ────────────────────────────────────────────────────────────
        outer.addWidget(self._sep())
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 6, 12, 12)

        self.btn_run = QPushButton('Gerar DEM/MDT / Generate DEM/DTM')
        self.btn_run.setMinimumHeight(38)
        self.btn_run.setStyleSheet(
            'QPushButton{background:#2e7d32;color:white;font-weight:bold;'
            'font-size:12px;border-radius:5px;border:none;}'
            'QPushButton:hover{background:#1b5e20;}'
            'QPushButton:disabled{background:#6a997a;color:#aaa;}')
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)

        btn_close = QPushButton('Fechar / Close')
        btn_close.setMinimumHeight(38)
        btn_close.setStyleSheet(
            'QPushButton{background:#616161;color:white;border:none;'
            'border-radius:5px;}'
            'QPushButton:hover{background:#424242;}')
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)

        outer.addLayout(btn_row)

        # Initial PDAL check
        self._refresh_pdal_status()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _sep(self):
        ln = QFrame()
        ln.setFrameShape(QFrame.HLine)
        ln.setFrameShadow(QFrame.Sunken)
        return ln

    def _on_mode_changed(self):
        tiles = self.radio_tiles.isChecked()
        self.grp_tiles.setVisible(tiles)
        self.grp_las.setVisible(not tiles)
        if not tiles:
            self._refresh_pdal_status()

    def _refresh_pdal_status(self):
        if _has_pdal():
            self.lbl_pdal_status.setText(
                '✔  PDAL detectado / PDAL detected — processamento de nuvem de pontos disponivel.')
            self.lbl_pdal_status.setStyleSheet('font-size:9px;color:#2e7d32;')
        else:
            self.lbl_pdal_status.setText(
                '✘  PDAL nao detectado / PDAL not detected.\n'
                '   Instale o provedor PDAL no QGIS (Plugins → Manage and Install Plugins → PDAL)\n'
                '   ou converta o LAS para GeoTIFF antes usando CloudCompare ou lasgrid.\n'
                '   Install PDAL provider in QGIS or convert LAS to GeoTIFF first using '
                'CloudCompare or lasgrid.')
            self.lbl_pdal_status.setStyleSheet('font-size:9px;color:#c62828;')

    def _existing_tile_paths(self):
        return {self.list_tiles.item(i).data(Qt.UserRole)
                for i in range(self.list_tiles.count())}

    def _add_tile_item(self, path):
        if path in self._existing_tile_paths():
            return
        item = QListWidgetItem(os.path.basename(path))
        item.setData(Qt.UserRole, path)
        item.setToolTip(path)
        self.list_tiles.addItem(item)
        self._update_tile_count()

    def _update_tile_count(self):
        n = self.list_tiles.count()
        self.lbl_tile_count.setText('{} arquivo(s) / file(s)'.format(n))

    def _add_tiles_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Selecionar pasta / Select folder')
        if not folder:
            return
        found = 0
        for ext in _RASTER_EXTS:
            for pat in ('*' + ext, '*' + ext.upper()):
                for fp in _glob.glob(os.path.join(folder, pat)):
                    self._add_tile_item(fp)
                    found += 1
        if found == 0:
            QMessageBox.information(self, 'RTH',
                'Nenhum tile raster encontrado.\nNo raster tile found.\n'
                'Extensoes / Extensions: {}'.format(', '.join(_RASTER_EXTS)))

    def _add_tiles_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, 'Selecionar tiles / Select tiles', '',
            'Raster (*.tif *.tiff *.img *.jp2 *.vrt);;Todos / All (*.*)')
        for fp in paths:
            self._add_tile_item(fp)

    def _remove_tiles(self):
        for item in reversed(self.list_tiles.selectedItems()):
            self.list_tiles.takeItem(self.list_tiles.row(item))
        self._update_tile_count()

    def _clear_tiles(self):
        self.list_tiles.clear()
        self._update_tile_count()

    def _browse_las(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Selecionar nuvem de pontos / Select point cloud', '',
            'LAS / LAZ (*.las *.laz);;Todos / All (*.*)')
        if path:
            self.edit_las.setText(path)

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Salvar DEM / Save DEM', '', 'GeoTIFF (*.tif)')
        if path:
            if not path.lower().endswith('.tif'):
                path += '.tif'
            self.edit_output.setText(path)

    # ── Execute ───────────────────────────────────────────────────────────────

    def _on_run(self):
        output = self.edit_output.text().strip()
        if not output:
            QMessageBox.warning(self, 'RTH', 'Defina o arquivo de saida DEM.\nDefine the DEM output file.')
            return
        if not output.lower().endswith('.tif'):
            output += '.tif'

        try:
            import processing
        except ImportError:
            QMessageBox.critical(self, 'RTH',
                'Modulo "processing" nao disponivel. Certifique-se de estar dentro do QGIS.\n'
                '"processing" module not available. Make sure you are running inside QGIS.')
            return

        options = 'BIGTIFF=IF_SAFER'
        if self.chk_compress.isChecked():
            options = 'COMPRESS=LZW|' + options

        progress = QProgressDialog('Aguarde / Please wait...', None, 0, 0, self)
        progress.setWindowTitle('RTH DEM/MDT — Aguarde / Please Wait')
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        self.btn_run.setEnabled(False)
        QApplication.processEvents()

        try:
            dem_path = self._generate_dem(processing, output, options, progress)
            if dem_path is None:
                progress.close()
                self.btn_run.setEnabled(True)
                return

            # ── Post-processing ───────────────────────────────────────────────
            hillshade_path = None
            contour_path   = None

            if self.chk_fillnodata.isChecked():
                progress.setLabelText('Preenchendo vazios / Filling NoData holes...')
                QApplication.processEvents()
                filled_path = dem_path.replace('.tif', '_filled.tif')
                try:
                    res = processing.run('gdal:fillnodata', {
                        'INPUT':      dem_path,
                        'BAND':       1,
                        'DISTANCE':   10,
                        'ITERATIONS': 0,
                        'MASK_LAYER': None,
                        'OPTIONS':    options,
                        'EXTRA':      '',
                        'OUTPUT':     filled_path,
                    })
                    dem_path = res.get('OUTPUT', filled_path)
                except Exception:
                    pass  # fillnodata is optional

            if self.chk_hillshade.isChecked():
                progress.setLabelText('Gerando hillshade / Generating hillshade...')
                QApplication.processEvents()
                hillshade_path = output.replace('.tif', '_hillshade.tif')
                try:
                    res = processing.run('gdal:hillshade', {
                        'INPUT':     dem_path,
                        'BAND':      1,
                        'Z_FACTOR':  self.spin_zfactor.value(),
                        'SCALE':     1.0,
                        'AZIMUTH':   float(self.spin_azimuth.value()),
                        'ALTITUDE':  float(self.spin_altitude.value()),
                        'COMBINED':  False,
                        'MULTIDIRECTIONAL': False,
                        'OPTIONS':   options,
                        'EXTRA':     '',
                        'OUTPUT':    hillshade_path,
                    })
                    hillshade_path = res.get('OUTPUT', hillshade_path)
                except Exception as e:
                    hillshade_path = None
                    self.iface.messageBar().pushMessage(
                        'RTH DEM', 'Hillshade falhou: {} / Hillshade failed: {}'.format(str(e), str(e)),
                        level=Qgis.MessageLevel.Warning, duration=4)

            if self.chk_contours.isChecked():
                progress.setLabelText('Gerando curvas de nivel / Generating contour lines...')
                QApplication.processEvents()
                contour_path = output.replace('.tif', '_curvas.gpkg')
                try:
                    res = processing.run('gdal:contour', {
                        'INPUT':         dem_path,
                        'BAND':          1,
                        'INTERVAL':      self.spin_interval.value(),
                        'FIELD_NAME':    'ELEV',
                        'CREATE_3D':     False,
                        'IGNORE_NODATA': True,
                        'NODATA':        None,
                        'OFFSET':        0.0,
                        'EXTRA':         '',
                        'OPTIONS':       '',
                        'OUTPUT':        contour_path,
                    })
                    contour_path = res.get('OUTPUT', contour_path)
                except Exception as e:
                    contour_path = None
                    self.iface.messageBar().pushMessage(
                        'RTH DEM', 'Curvas de nível falharam: {} / Contour lines failed: {}'.format(str(e), str(e)),
                        level=Qgis.MessageLevel.Warning, duration=4)

            progress.close()
            self.btn_run.setEnabled(True)

            # ── Load results ──────────────────────────────────────────────────
            if self.chk_load.isChecked():
                base_name = self.edit_name.text().strip() or 'DEM_Drone'

                layer_dem = QgsRasterLayer(dem_path, base_name)
                if layer_dem.isValid():
                    QgsProject.instance().addMapLayer(layer_dem)
                    collapse_layer(layer_dem)

                if hillshade_path and os.path.exists(hillshade_path):
                    hs = QgsRasterLayer(hillshade_path, base_name + '_Hillshade')
                    if hs.isValid():
                        QgsProject.instance().addMapLayer(hs)
                        collapse_layer(hs)

                if contour_path and os.path.exists(contour_path):
                    cv = QgsVectorLayer(contour_path, base_name + '_Curvas', 'ogr')
                    if cv.isValid():
                        QgsProject.instance().addMapLayer(cv)
                        collapse_layer(cv)

                self.iface.messageBar().pushMessage(
                    'RTH DEM/MDT',
                    'DEM gerado e carregado / DEM generated and loaded: {}'.format(base_name),
                    level=Qgis.MessageLevel.Success, duration=5)
            else:
                self.iface.messageBar().pushMessage(
                    'RTH DEM/MDT',
                    'DEM gerado / DEM generated: {}'.format(output),
                    level=Qgis.MessageLevel.Success, duration=5)

        except Exception as e:
            progress.close()
            self.btn_run.setEnabled(True)
            QMessageBox.critical(self, 'RTH DEM/MDT',
                'Erro / Error:\n\n{}'.format(str(e)))

    def _generate_dem(self, processing, output, options, progress):
        """Dispatch to tile merge or point cloud rasterization. Returns output path or None."""

        if self.radio_tiles.isChecked():
            return self._dem_from_tiles(processing, output, options, progress)
        else:
            return self._dem_from_las(processing, output, options, progress)

    def _dem_from_tiles(self, processing, output, options, progress):
        files = [self.list_tiles.item(i).data(Qt.UserRole)
                 for i in range(self.list_tiles.count())]
        if not files:
            QMessageBox.warning(self, 'RTH',
                'Adicione pelo menos um tile raster.\nAdd at least one raster tile.')
            return None

        # Step 1: merge tiles
        progress.setLabelText('Mesclando tiles / Merging tiles...')
        QApplication.processEvents()

        res = processing.run('gdal:merge', {
            'INPUT':       files,
            'PCT':         False,
            'SEPARATE':    False,
            'DATA_TYPE':   self.combo_dtype.currentData(),
            'EXTRA':       '',
            'OPTIONS':     options,
            'OUTPUT':      output,
        })
        merged = res.get('OUTPUT', output)

        # Step 2: optional resampling to requested resolution
        res_m = self.spin_res.value()
        if res_m != 1.0:
            progress.setLabelText('Reamostrado / Resampling to {:.2f} m...'.format(res_m))
            QApplication.processEvents()
            resampled = output.replace('.tif', '_res.tif')
            try:
                r2 = processing.run('gdal:warpreproject', {
                    'INPUT':             merged,
                    'SOURCE_CRS':        None,
                    'TARGET_CRS':        None,
                    'RESAMPLING':        1,   # bilinear
                    'NODATA':            None,
                    'TARGET_RESOLUTION': res_m,
                    'OPTIONS':           options,
                    'DATA_TYPE':         self.combo_dtype.currentData(),
                    'TARGET_EXTENT':     None,
                    'TARGET_EXTENT_CRS': None,
                    'MULTITHREADING':    False,
                    'EXTRA':             '',
                    'OUTPUT':            resampled,
                })
                merged = r2.get('OUTPUT', resampled)
            except Exception:
                pass  # keep merged without resampling if warp fails

        return merged

    def _dem_from_las(self, processing, output, options, progress):
        las_path = self.edit_las.text().strip()
        if not las_path or not os.path.exists(las_path):
            QMessageBox.warning(self, 'RTH',
                'Arquivo LAS/LAZ nao encontrado.\nLAS/LAZ file not found.\n{}'.format(las_path))
            return None

        if not _has_pdal():
            QMessageBox.critical(self, 'RTH',
                'PDAL nao encontrado no QGIS.\n'
                'PDAL not found in QGIS.\n\n'
                'Alternativas / Alternatives:\n'
                '• Instale o provedor PDAL: Plugins → Manage Plugins → PDAL\n'
                '• Converta o LAS para GeoTIFF usando CloudCompare ou lasgrid\n'
                '  e use o modo "Tiles Raster".\n'
                '• Install PDAL provider: Plugins → Manage Plugins → PDAL\n'
                '• Convert LAS to GeoTIFF using CloudCompare or lasgrid\n'
                '  and use "Tiles Raster" mode.')
            return None

        progress.setLabelText('Rasterizando nuvem de pontos / Rasterizing point cloud...')
        QApplication.processEvents()

        is_dtm = (self.combo_dem_type.currentData() == 'dtm')

        # Try pdal:exportraster
        try:
            pdal_params = {
                'INPUT':      las_path,
                'RESOLUTION': self.spin_res.value(),
                'OUTPUT':     output,
            }
            # Ground-only filter for DTM: LAS classification 2 = ground
            if is_dtm:
                pdal_params['FILTER_EXPRESSION'] = 'Classification == 2'

            # QGIS PDAL algorithm IDs can vary; try both known IDs
            for alg_id in ('pdal:exportraster', 'pdal:pdal_exportraster'):
                try:
                    res = processing.run(alg_id, pdal_params)
                    return res.get('OUTPUT', output)
                except Exception:
                    continue

            # Fallback: try without filter_expression key (older PDAL builds)
            basic_params = {k: v for k, v in pdal_params.items()
                            if k != 'FILTER_EXPRESSION'}
            for alg_id in ('pdal:exportraster', 'pdal:pdal_exportraster'):
                try:
                    res = processing.run(alg_id, basic_params)
                    return res.get('OUTPUT', output)
                except Exception:
                    continue

            raise RuntimeError(
                'Nenhum algoritmo PDAL exportraster encontrado.\n'
                'No PDAL exportraster algorithm found.\n'
                'Verifique se o provedor PDAL esta ativado no QGIS.\n'
                'Check that the PDAL provider is enabled in QGIS.')

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError('Erro PDAL / PDAL error: {}'.format(str(e)))


# ─── Tool class ───────────────────────────────────────────────────────────────

class DroneDEMTool:

    def __init__(self, iface):
        self.iface   = iface
        self._dialog = None

    def run(self):
        if self._dialog is None or not self._dialog.isVisible():
            self._dialog = DroneDEMDialog(self.iface, parent=self.iface.mainWindow())
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
