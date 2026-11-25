# -*- coding: utf-8 -*-
"""
Diálogo PRODES Download — estilo idêntico ao RTH DEM Downloader.
"""
import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QLineEdit, QProgressBar,
    QFileDialog, QFrame, QRadioButton, QButtonGroup, QWidget
)
from qgis.PyQt.QtCore import QCoreApplication, Qt

from .tool_prodes_sources import BIOMES


class ProdesDialog(QDialog):

    def __init__(self, iface, parent=None):
        super(ProdesDialog, self).__init__(parent)
        self.iface = iface
        self._build_ui()

    def tr(self, message):
        return QCoreApplication.translate('ProdesDialog', message)

    # ------------------------------------------------------------------
    # Construção da UI / UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setWindowTitle('RTH PRODES Download')
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint |
            Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint
        )
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── Cabeçalho / Header ────────────────────────────────────────
        lbl_title = QLabel('RTH PRODES Download')
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold;')
        layout.addWidget(lbl_title)

        self.lbl_sub = QLabel('Fonte: TerraBrasilis / INPE  ·  Dados vetoriais de desmatamento')
        self.lbl_sub.setAlignment(Qt.AlignCenter)
        self.lbl_sub.setStyleSheet('color:#666; font-size:10px;')
        layout.addWidget(self.lbl_sub)

        self._sep(layout)

        # ── Escopo / Scope ────────────────────────────────────────────
        lbl_scope = QLabel('Escopo / Scope')
        lbl_scope.setStyleSheet('font-weight:bold;')
        layout.addWidget(lbl_scope)

        scope_row = QHBoxLayout()
        self.radio_brasil = QRadioButton('Brasil Inteiro / Entire Brazil')
        self.radio_bioma  = QRadioButton('Bioma Específico / Specific Biome')
        self.radio_brasil.setChecked(True)
        self._scope_group = QButtonGroup()
        self._scope_group.addButton(self.radio_brasil)
        self._scope_group.addButton(self.radio_bioma)
        scope_row.addWidget(self.radio_brasil)
        scope_row.addWidget(self.radio_bioma)
        scope_row.addStretch()
        layout.addLayout(scope_row)

        self.lbl_brasil_note = QLabel(
            'Aviso: carrega 6 biomas — pode demorar vários minutos / Warning: loads 6 biomes — may take several minutes'
        )
        self.lbl_brasil_note.setStyleSheet('color:#b87800; font-size:9px;')
        self.lbl_brasil_note.setWordWrap(True)
        layout.addWidget(self.lbl_brasil_note)

        self.combo_bioma = QComboBox()
        for b in BIOMES:
            self.combo_bioma.addItem(b['name'])
        self.combo_bioma.setEnabled(False)
        layout.addWidget(self.combo_bioma)

        self._sep(layout)

        # ── Tipo / Type ───────────────────────────────────────────────
        lbl_tipo = QLabel('Tipo / Type')
        lbl_tipo.setStyleSheet('font-weight:bold;')
        layout.addWidget(lbl_tipo)

        tipo_row = QHBoxLayout()
        self.radio_yearly     = QRadioButton('Incremento Anual / Annual Increment')
        self.radio_accumulated = QRadioButton('Acumulado / Accumulated')
        self.radio_yearly.setChecked(True)
        self._tipo_group = QButtonGroup()
        self._tipo_group.addButton(self.radio_yearly)
        self._tipo_group.addButton(self.radio_accumulated)
        tipo_row.addWidget(self.radio_yearly)
        tipo_row.addWidget(self.radio_accumulated)
        tipo_row.addStretch()
        layout.addLayout(tipo_row)

        # Bloco do ano (escondido no modo Acumulado) / Year block (hidden in Accumulated mode)
        self.widget_ano = QWidget()
        ano_inner = QHBoxLayout(self.widget_ano)
        ano_inner.setContentsMargins(0, 4, 0, 0)
        ano_inner.addWidget(QLabel('Ano / Year'))
        self.combo_ano = QComboBox()
        ano_inner.addWidget(self.combo_ano, 1)
        layout.addWidget(self.widget_ano)

        self._sep(layout)

        # ── Modo / Mode ───────────────────────────────────────────────
        lbl_mode = QLabel('Modo / Mode')
        lbl_mode.setStyleSheet('font-weight:bold;')
        layout.addWidget(lbl_mode)

        mode_row = QHBoxLayout()
        self.radio_wms      = QRadioButton('Carregar WMS / Load WMS')
        self.radio_download = QRadioButton('Baixar Vetor / Download Vector')
        self.radio_wms.setToolTip(
            'Exibe os dados como camada raster via TerraBrasilis (sem baixar) / '
            'Displays data as raster layer via TerraBrasilis (no download)')
        self.radio_download.setToolTip(
            'Baixa os polígonos vetoriais como GeoPackage / '
            'Downloads vector polygons as GeoPackage')
        self.radio_wms.setChecked(True)
        self._mode_group = QButtonGroup()
        self._mode_group.addButton(self.radio_wms)
        self._mode_group.addButton(self.radio_download)
        mode_row.addWidget(self.radio_wms)
        mode_row.addWidget(self.radio_download)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # Pasta de saída (visível somente no modo Baixar) / Output folder (visible only in Download mode)
        dir_row = QHBoxLayout()
        self.edit_dir = QLineEdit()
        self.edit_dir.setPlaceholderText('Pasta de saída / Output folder...')
        dir_row.addWidget(self.edit_dir)
        self.btn_browse = QPushButton('...')
        self.btn_browse.setFixedWidth(32)
        self.btn_browse.clicked.connect(self._on_browse)
        dir_row.addWidget(self.btn_browse)
        layout.addLayout(dir_row)
        self.radio_wms.toggled.connect(lambda checked: self._set_dir_visible(not checked))
        self._set_dir_visible(False)

        self._sep(layout)

        # ── Botão Run / Run button ────────────────────────────────────
        self.btn_run = QPushButton('▶  Executar / Run')
        self.btn_run.setMinimumHeight(40)
        self.btn_run.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;font-size:13px;border-radius:5px;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        layout.addWidget(self.btn_run)

        # ── Progresso / Progress ──────────────────────────────────────
        self.lbl_progress = QLabel('')
        self.lbl_progress.setAlignment(Qt.AlignCenter)
        self.lbl_progress.setStyleSheet('font-size:10px; color:#333;')
        self.lbl_progress.setWordWrap(True)
        layout.addWidget(self.lbl_progress)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimum(0)
        layout.addWidget(self.progress_bar)

        # ── Conexões / Connections ────────────────────────────────────
        self.radio_brasil.toggled.connect(self._on_scope_changed)
        self.combo_bioma.currentIndexChanged.connect(self._on_biome_changed)
        self.radio_yearly.toggled.connect(self._on_tipo_changed)

        # Popula anos iniciais / Populate initial years
        self._update_years()

    # ------------------------------------------------------------------
    # Helpers / Helpers
    # ------------------------------------------------------------------

    def _sep(self, layout):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

    def _set_dir_visible(self, visible):
        self.edit_dir.setVisible(visible)
        self.btn_browse.setVisible(visible)
        self.adjustSize()

    # ------------------------------------------------------------------
    # Slots / Slots
    # ------------------------------------------------------------------

    def _on_scope_changed(self):
        is_brasil = self.radio_brasil.isChecked()
        self.combo_bioma.setEnabled(not is_brasil)
        self.lbl_brasil_note.setVisible(is_brasil)
        self._update_years()
        self.adjustSize()

    def _on_biome_changed(self, idx):
        if self.radio_bioma.isChecked():
            biome = BIOMES[idx]
            has_acc = biome['accumulated_layer'] is not None
            self.radio_accumulated.setEnabled(has_acc)
            if not has_acc and self.radio_accumulated.isChecked():
                self.radio_yearly.setChecked(True)
            self._update_years()

    def _on_tipo_changed(self):
        self.widget_ano.setVisible(self.radio_yearly.isChecked())
        self.adjustSize()

    def _update_years(self):
        self.combo_ano.blockSignals(True)
        self.combo_ano.clear()
        if self.radio_brasil.isChecked():
            # União de todos os anos disponíveis, em ordem decrescente / Union of all available years, descending
            all_years = set()
            for b in BIOMES:
                all_years.update(b['times'])
            for y in sorted(all_years, reverse=True):
                self.combo_ano.addItem(y, y)
        else:
            biome = BIOMES[self.combo_bioma.currentIndex()]
            for y in reversed(biome['times']):
                self.combo_ano.addItem(y, y)
        self.combo_ano.blockSignals(False)

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            'Selecione a pasta de saída / Select output folder',
            self.edit_dir.text() or os.path.expanduser('~')
        )
        if folder:
            self.edit_dir.setText(folder)

    # ------------------------------------------------------------------
    # API pública / Public API
    # ------------------------------------------------------------------

    def get_params(self):
        return {
            'brasil':    self.radio_brasil.isChecked(),
            'biome_idx': self.combo_bioma.currentIndex(),
            'tipo':      'yearly' if self.radio_yearly.isChecked() else 'accumulated',
            'ano':       self.combo_ano.currentData() if self.radio_yearly.isChecked() else None,
            'mode':      'wms' if self.radio_wms.isChecked() else 'download',
            'out_dir':   self.edit_dir.text().strip(),
        }

    def set_busy(self, busy, text=''):
        self.btn_run.setEnabled(not busy)
        if busy and text:
            self.btn_run.setText(text)
        elif not busy:
            self.btn_run.setText('▶  Executar / Run')

    def set_progress(self, msg, value=None, maximum=None, error=False):
        color = 'red' if error else '#333'
        self.lbl_progress.setStyleSheet('font-size:10px; color:{0};'.format(color))
        self.lbl_progress.setText(msg)
        if maximum is not None:
            self.progress_bar.setMaximum(maximum)
            self.progress_bar.setVisible(True)
        if value is not None:
            self.progress_bar.setValue(value)
