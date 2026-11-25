# -*- coding: utf-8 -*-
"""
tool_drone_mosaic.py

Mosaico Automatico de Drone — combina tiles raster georreferenciados
(GeoTIFF, JP2, IMG) em um único ortomosaico usando GDAL Merge.

Drone Auto Mosaic — merges georeferenced raster tiles into a single
orthomosaic using GDAL Merge. Optionally applies LZW compression and
loads the result directly in QGIS.
"""

import os
import glob as _glob

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QComboBox, QFrame, QGroupBox, QWidget, QScrollArea,
    QApplication, QMessageBox, QListWidget, QListWidgetItem,
    QProgressDialog, QFileDialog, QLineEdit, QCheckBox,
    QAbstractItemView,
)
from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.core import Qgis, QgsProject, QgsRasterLayer
from core.rth_layer_utils import collapse_layer


# ─── Supported input extensions ───────────────────────────────────────────────

_RASTER_EXTS = ('.tif', '.tiff', '.img', '.jp2', '.vrt', '.ecw')

# gdal:merge DATA_TYPE codes
_DATA_TYPES = [
    ('Float32 (recomendado / recommended)', 6),
    ('Float64',                             7),
    ('UInt16',                              2),
    ('Int16',                               3),
    ('Byte / UInt8',                        0),
]


# ─── Dialog ───────────────────────────────────────────────────────────────────

class DroneAutoMosaicDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface

        self.setWindowTitle('RTH — Mosaico de Drone / Drone Auto Mosaic')
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(580)
        self.setMinimumHeight(700)
        self.setMaximumHeight(860)

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
        lbl_t = QLabel('Mosaico Automatico de Drone / Drone Auto Mosaic')
        lbl_t.setAlignment(Qt.AlignCenter)
        lbl_t.setStyleSheet('font-size:13px;font-weight:bold;')
        root.addWidget(lbl_t)

        lbl_s = QLabel(
            'Combina tiles raster georreferenciados em um unico mosaico via GDAL Merge.\n'
            'Combines georeferenced raster tiles into a single mosaic via GDAL Merge.')
        lbl_s.setAlignment(Qt.AlignCenter)
        lbl_s.setStyleSheet('color:#666;font-size:10px;')
        lbl_s.setWordWrap(True)
        root.addWidget(lbl_s)
        root.addWidget(self._sep())

        # ── Input files ───────────────────────────────────────────────────────
        grp_in = QGroupBox('Arquivos de Entrada / Input Files  (.tif .tiff .img .jp2 .vrt)')
        gl_in = QVBoxLayout()
        gl_in.setContentsMargins(8, 6, 8, 8)
        gl_in.setSpacing(5)

        self.list_files = QListWidget()
        self.list_files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_files.setMinimumHeight(100)
        self.list_files.setMaximumHeight(180)
        self.list_files.setToolTip('Caminho completo no tooltip / Full path in tooltip')
        gl_in.addWidget(self.list_files)

        btn_bar = QHBoxLayout()
        for label, slot in [
            ('+ Pasta / + Folder', self._add_folder),
            ('+ Arquivos / + Files', self._add_files),
            ('Remover / Remove', self._remove_selected),
            ('Limpar / Clear', self._clear_files),
        ]:
            b = QPushButton(label)
            b.setStyleSheet('font-size:10px;')
            b.clicked.connect(slot)
            btn_bar.addWidget(b)
        gl_in.addLayout(btn_bar)

        self.lbl_count = QLabel('0 arquivo(s) selecionado(s) / file(s) selected')
        self.lbl_count.setStyleSheet('color:#666;font-size:10px;')
        gl_in.addWidget(self.lbl_count)

        grp_in.setLayout(gl_in)
        root.addWidget(grp_in)

        # ── Output ────────────────────────────────────────────────────────────
        grp_out = QGroupBox('Saida / Output')
        gl_out = QGridLayout()
        gl_out.setContentsMargins(8, 6, 8, 8)
        gl_out.setSpacing(6)
        gl_out.setColumnStretch(1, 1)

        gl_out.addWidget(QLabel('Arquivo de saida / Output file:'), 0, 0)
        row_out = QHBoxLayout()
        row_out.setContentsMargins(0, 0, 0, 0)
        self.edit_output = QLineEdit()
        self.edit_output.setPlaceholderText('caminho/mosaico.tif')
        row_out.addWidget(self.edit_output)
        btn_browse = QPushButton('...')
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._browse_output)
        row_out.addWidget(btn_browse)
        gl_out.addLayout(row_out, 0, 1)

        gl_out.addWidget(QLabel('Nome da camada / Layer name:'), 1, 0)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText('Mosaico_Drone')
        gl_out.addWidget(self.edit_name, 1, 1)

        grp_out.setLayout(gl_out)
        root.addWidget(grp_out)

        # ── Options ───────────────────────────────────────────────────────────
        grp_opt = QGroupBox('Opcoes / Options')
        gl_opt = QGridLayout()
        gl_opt.setContentsMargins(8, 6, 8, 8)
        gl_opt.setSpacing(6)
        gl_opt.setColumnStretch(1, 1)

        gl_opt.addWidget(QLabel('Tipo de dado / Data type:'), 0, 0)
        self.combo_dtype = QComboBox()
        for label, code in _DATA_TYPES:
            self.combo_dtype.addItem(label, code)
        gl_opt.addWidget(self.combo_dtype, 0, 1)

        gl_opt.addWidget(QLabel('Valor no-data (vazio = auto):'), 1, 0)
        self.edit_nodata = QLineEdit()
        self.edit_nodata.setPlaceholderText('Ex: 0  ou  -9999  (deixe vazio = automatico)')
        gl_opt.addWidget(self.edit_nodata, 1, 1)

        self.chk_compress = QCheckBox('Compressao LZW / LZW Compression (recomendado / recommended)')
        self.chk_compress.setChecked(True)
        self.chk_compress.setStyleSheet('font-size:10px;')
        gl_opt.addWidget(self.chk_compress, 2, 0, 1, 2)

        self.chk_load = QCheckBox('Carregar no QGIS apos / Load in QGIS after')
        self.chk_load.setChecked(True)
        self.chk_load.setStyleSheet('font-size:10px;')
        gl_opt.addWidget(self.chk_load, 3, 0, 1, 2)

        grp_opt.setLayout(gl_opt)
        root.addWidget(grp_opt)

        # ── Note ──────────────────────────────────────────────────────────────
        lbl_note = QLabel(
            'ℹ  Os arquivos devem estar georreferenciados (GeoTIFF com CRS definido).\n'
            '   Para ortomosaico completo (SfM), use OpenDroneMap, Pix4D ou Agisoft Metashape.\n'
            '   Files must be georeferenced (GeoTIFF with defined CRS).\n'
            '   For full orthomosaic (SfM), use OpenDroneMap, Pix4D or Agisoft Metashape.')
        lbl_note.setStyleSheet(
            'font-size:9px;color:#555;background:#fffde7;border:1px solid #f9a825;'
            'border-radius:3px;padding:5px;')
        lbl_note.setWordWrap(True)
        root.addWidget(lbl_note)

        # ── Buttons (always visible outside scroll) ────────────────────────────
        outer.addWidget(self._sep())
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 6, 12, 12)

        self.btn_run = QPushButton('Gerar Mosaico / Generate Mosaic')
        self.btn_run.setMinimumHeight(38)
        self.btn_run.setStyleSheet(
            'QPushButton{background:#1976d2;color:white;font-weight:bold;'
            'font-size:12px;border-radius:5px;border:none;}'
            'QPushButton:hover{background:#1565c0;}'
            'QPushButton:disabled{background:#5a7fa8;color:#aaa;}')
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

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _sep(self):
        ln = QFrame()
        ln.setFrameShape(QFrame.HLine)
        ln.setFrameShadow(QFrame.Sunken)
        return ln

    def _existing_paths(self):
        return {self.list_files.item(i).data(Qt.UserRole)
                for i in range(self.list_files.count())}

    def _add_item(self, path):
        if path in self._existing_paths():
            return
        item = QListWidgetItem(os.path.basename(path))
        item.setData(Qt.UserRole, path)
        item.setToolTip(path)
        self.list_files.addItem(item)
        self._update_count()

    def _update_count(self):
        n = self.list_files.count()
        self.lbl_count.setText('{} arquivo(s) selecionado(s) / file(s) selected'.format(n))

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Selecionar pasta / Select folder')
        if not folder:
            return
        found = 0
        for ext in _RASTER_EXTS:
            for pat in ('*' + ext, '*' + ext.upper()):
                for fp in _glob.glob(os.path.join(folder, pat)):
                    self._add_item(fp)
                    found += 1
        if found == 0:
            QMessageBox.information(
                self, 'RTH',
                'Nenhum arquivo raster encontrado na pasta.\nNo raster file found in folder.\n'
                'Extensoes suportadas / Supported: {}'.format(', '.join(_RASTER_EXTS)))

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, 'Selecionar arquivos / Select files', '',
            'Raster (*.tif *.tiff *.img *.jp2 *.vrt *.ecw);;Todos / All (*.*)')
        for fp in paths:
            self._add_item(fp)

    def _remove_selected(self):
        for item in reversed(self.list_files.selectedItems()):
            self.list_files.takeItem(self.list_files.row(item))
        self._update_count()

    def _clear_files(self):
        self.list_files.clear()
        self._update_count()

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Salvar mosaico / Save mosaic', '', 'GeoTIFF (*.tif)')
        if path:
            if not path.lower().endswith('.tif'):
                path += '.tif'
            self.edit_output.setText(path)

    # ── Execute ───────────────────────────────────────────────────────────────

    def _on_run(self):
        files = [self.list_files.item(i).data(Qt.UserRole)
                 for i in range(self.list_files.count())]

        if not files:
            QMessageBox.warning(self, 'RTH',
                'Adicione pelo menos um arquivo raster de entrada.\n'
                'Add at least one input raster file.')
            return

        output = self.edit_output.text().strip()
        if not output:
            QMessageBox.warning(self, 'RTH',
                'Defina o arquivo de saida.\nDefine the output file.')
            return
        if not output.lower().endswith('.tif'):
            output += '.tif'

        try:
            import processing
        except ImportError:
            QMessageBox.critical(self, 'RTH',
                'Modulo "processing" nao disponivel. Certifique-se de estar rodando dentro do QGIS.\n'
                '"processing" module not available. Make sure you are running inside QGIS.')
            return

        options = 'BIGTIFF=IF_SAFER'
        if self.chk_compress.isChecked():
            options = 'COMPRESS=LZW|' + options

        nodata_str = self.edit_nodata.text().strip()
        params = {
            'INPUT':        files,
            'PCT':          False,
            'SEPARATE':     False,
            'DATA_TYPE':    self.combo_dtype.currentData(),
            'EXTRA':        '',
            'OPTIONS':      options,
            'OUTPUT':       output,
        }
        if nodata_str:
            try:
                nd = float(nodata_str)
                params['NODATA_INPUT']  = nd
                params['NODATA_OUTPUT'] = nd
            except ValueError:
                QMessageBox.warning(self, 'RTH',
                    'Valor no-data invalido. Use um numero (ex: 0 ou -9999).\n'
                    'Invalid no-data value. Use a number (e.g. 0 or -9999).')
                return

        progress = QProgressDialog(
            'Gerando mosaico, aguarde... / Generating mosaic, please wait...',
            None, 0, 0, self)
        progress.setWindowTitle('RTH Mosaico')
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        self.btn_run.setEnabled(False)
        QApplication.processEvents()

        try:
            result = processing.run('gdal:merge', params)
            progress.close()
            self.btn_run.setEnabled(True)

            out_path = result.get('OUTPUT', output)

            if self.chk_load.isChecked():
                name = self.edit_name.text().strip() or 'Mosaico_Drone'
                layer = QgsRasterLayer(out_path, name)
                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer)
                    collapse_layer(layer)
                    self.iface.messageBar().pushMessage(
                        'RTH Mosaico',
                        'Mosaico gerado e carregado / Mosaic generated and loaded: {}'.format(name),
                        level=Qgis.MessageLevel.Success, duration=5)
                else:
                    QMessageBox.warning(self, 'RTH',
                        'Mosaico gerado mas falhou ao carregar no QGIS.\n'
                        'Mosaic generated but failed to load in QGIS.\n{}'.format(out_path))
            else:
                self.iface.messageBar().pushMessage(
                    'RTH Mosaico',
                    'Mosaico gerado / Mosaic generated: {}'.format(output),
                    level=Qgis.MessageLevel.Success, duration=5)

        except Exception as e:
            progress.close()
            self.btn_run.setEnabled(True)
            QMessageBox.critical(self, 'RTH Mosaico',
                'Erro ao gerar mosaico / Error generating mosaic:\n\n{}'.format(str(e)))


# ─── Tool class ───────────────────────────────────────────────────────────────

class DroneAutoMosaicTool:

    def __init__(self, iface):
        self.iface   = iface
        self._dialog = None

    def run(self):
        if self._dialog is None or not self._dialog.isVisible():
            self._dialog = DroneAutoMosaicDialog(self.iface)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
