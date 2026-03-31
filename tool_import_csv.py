# -*- coding: utf-8 -*-
"""
Ferramenta Import CSV - Importa CSV com colunas X, Y como camada de pontos
Import CSV Tool - Imports CSV with X, Y columns as a point layer

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Módulo padrão para leitura de CSV / Standard module for CSV reading
import csv
# Módulo padrão para caminhos / Standard module for paths
import os

# Widgets Qt / Qt widgets
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QPushButton, QLineEdit,
    QDialogButtonBox, QFrame, QFileDialog
)
# Codificação URL para o provider delimitedtext / URL encoding for delimitedtext provider
from qgis.PyQt.QtCore import QUrl

# Módulos QGIS para camadas, projeto e seleção de CRS / QGIS modules for layers, project and CRS selection
from qgis.core import QgsVectorLayer, QgsProject, QgsCoordinateReferenceSystem
from qgis.gui import QgsProjectionSelectionWidget


class ImportCSVDialog(QDialog):
    """Diálogo para importar CSV com colunas de coordenadas como pontos / Dialog to import CSV with coordinate columns as points."""

    def __init__(self, iface, parent=None):
        """Construtor do diálogo / Dialog constructor."""
        super().__init__(parent)
        # Interface QGIS / QGIS interface
        self.iface = iface
        # Cabeçalho do CSV lido / Read CSV header
        self._headers = []

        self.setWindowTitle('Importar CSV / Import CSV')
        self.setModal(True)
        self.setMinimumWidth(420)

        # Layout principal / Main layout
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # ── Arquivo CSV / CSV File ──
        lbl_file = QLabel('Arquivo / File:')
        layout.addWidget(lbl_file)

        file_row = QHBoxLayout()
        # Campo de texto com o caminho do arquivo / Text field with file path
        self.edit_file = QLineEdit()
        self.edit_file.setPlaceholderText('Selecione o arquivo CSV / Select CSV file...')
        self.edit_file.setReadOnly(True)
        file_row.addWidget(self.edit_file)
        # Botão de navegação / Browse button
        btn_browse = QPushButton('...')
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._on_browse)
        file_row.addWidget(btn_browse)
        layout.addLayout(file_row)

        # Separador / Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # ── Seleção de colunas / Column selection ──
        form = QFormLayout()
        form.setSpacing(8)

        # Coluna de Latitude — yField do provider / Latitude column — provider yField
        self.combo_y = QComboBox()
        form.addRow('Latitude:', self.combo_y)

        # Coluna de Longitude — xField do provider / Longitude column — provider xField
        self.combo_x = QComboBox()
        form.addRow('Longitude:', self.combo_x)

        layout.addLayout(form)

        # Separador / Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep2)

        # ── Seleção de CRS / CRS selection ──
        lbl_crs = QLabel('CRS das coordenadas / Coordinate CRS:')
        layout.addWidget(lbl_crs)

        # Widget nativo do QGIS para seleção de CRS / Native QGIS widget for CRS selection
        self.crs_widget = QgsProjectionSelectionWidget()
        # Padrão: WGS84 (lat/long do grid exportado) / Default: WGS84 (lat/long from exported grid)
        self.crs_widget.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
        layout.addWidget(self.crs_widget)

        # ── Botões OK / Cancel ──
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        # Desabilita OK até um arquivo ser carregado / Disable OK until a file is loaded
        self._btn_ok = btn_box.button(QDialogButtonBox.Ok)
        self._btn_ok.setEnabled(False)
        layout.addWidget(btn_box)

        self.setLayout(layout)

    def _on_browse(self):
        """Abre o seletor de arquivo CSV / Open CSV file selector."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            'Selecione o CSV / Select CSV',
            '',
            'CSV (*.csv);;Todos os arquivos / All files (*)'
        )
        if not path:
            return

        # Lê apenas o cabeçalho do arquivo / Read only the file header
        try:
            with open(path, newline='', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                self._headers = next(reader)
        except Exception as e:
            self.iface.messageBar().pushMessage(
                'Import CSV', 'Erro ao ler cabeçalho / Error reading header: {}'.format(e), level=1)
            return

        # Preenche os combos com os cabeçalhos / Fill combos with headers
        self.combo_x.clear()
        self.combo_y.clear()
        for h in self._headers:
            self.combo_x.addItem(h)
            self.combo_y.addItem(h)

        # Auto-seleciona colunas X e Y por nome comum / Auto-select X and Y columns by common name
        x_candidates = ['x', 'lon', 'longitude', 'lng', 'easting']
        y_candidates = ['y', 'lat', 'latitude', 'northing']

        for i, h in enumerate(self._headers):
            if h.lower() in x_candidates:
                self.combo_x.setCurrentIndex(i)
                break

        for i, h in enumerate(self._headers):
            if h.lower() in y_candidates:
                self.combo_y.setCurrentIndex(i)
                break

        # Exibe o caminho e habilita OK / Show path and enable OK
        self.edit_file.setText(path)
        self._btn_ok.setEnabled(True)

    def file_path(self):
        """Retorna o caminho do arquivo selecionado / Returns selected file path."""
        return self.edit_file.text()

    def x_field(self):
        """Retorna o nome da coluna X selecionada / Returns selected X column name."""
        return self.combo_x.currentText()

    def y_field(self):
        """Retorna o nome da coluna Y selecionada / Returns selected Y column name."""
        return self.combo_y.currentText()

    def crs(self):
        """Retorna o CRS selecionado / Returns selected CRS."""
        return self.crs_widget.crs()


class ImportCSVTool:
    """Importa CSV com colunas de coordenadas como camada de pontos no QGIS / Imports CSV with coordinate columns as a point layer in QGIS."""

    def __init__(self, iface):
        # Armazena a interface QGIS / Store QGIS interface
        self.iface = iface

    def run(self):
        """Abre o diálogo e carrega o CSV como camada de pontos / Open dialog and load CSV as point layer."""

        # Abre o diálogo de configuração / Open configuration dialog
        dlg = ImportCSVDialog(self.iface, parent=self.iface.mainWindow())
        if dlg.exec_() != QDialog.Accepted:
            # Usuário cancelou / User cancelled
            return

        path    = dlg.file_path()
        x_field = dlg.x_field()
        y_field = dlg.y_field()
        crs     = dlg.crs()

        # ── Valida seleção de colunas / Validate column selection ──
        if x_field == y_field:
            self.iface.messageBar().pushMessage(
                'Import CSV',
                'As colunas X e Y não podem ser iguais / X and Y columns cannot be the same',
                level=1)
            return

        # ── Monta a URI do provider delimitedtext / Build delimitedtext provider URI ──
        # Usa o provider nativo do QGIS para ler CSV com coordenadas
        # Uses QGIS native provider to read CSV with coordinates
        uri = QUrl.fromLocalFile(path).toString()
        uri += '?delimiter=,&xField={}&yField={}&crs={}'.format(
            x_field,
            y_field,
            crs.authid()
        )

        # Nome da camada a partir do nome do arquivo / Layer name from filename
        layer_name = os.path.splitext(os.path.basename(path))[0]

        # ── Cria a camada vetorial com o provider delimitedtext / Create vector layer with delimitedtext provider ──
        vl = QgsVectorLayer(uri, layer_name, 'delimitedtext')

        if not vl.isValid():
            self.iface.messageBar().pushMessage(
                'Import CSV',
                'Não foi possível carregar o CSV. Verifique as colunas e o CRS / Could not load CSV. Check columns and CRS.',
                level=2)
            return

        # Adiciona a camada ao projeto / Add layer to project
        QgsProject.instance().addMapLayer(vl)

        # Mensagem de sucesso / Success message
        self.iface.messageBar().pushMessage(
            'Import CSV',
            '{} ponto(s) carregado(s) | Lat:{} Long:{} | {} / point(s) loaded | Lat:{} Long:{} | {}'.format(
                vl.featureCount(), y_field, x_field, crs.authid(),
                y_field, x_field, crs.authid()),
            level=0, duration=8)
