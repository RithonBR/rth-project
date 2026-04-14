# -*- coding: utf-8 -*-
"""
tool_points_to_polygon.py

Ferramenta Pontos de GPS para Polígono / GPS Points to Polygon Tool

Importa um CSV com colunas latitude/longitude (ou usa a camada ativa de pontos)
e aplica o algoritmo de Forma Côncava (Concave Hull) para gerar um polígono.

Imports a CSV with latitude/longitude columns (or uses the active point layer)
and applies the Concave Hull algorithm to generate a polygon.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Módulo CSV para leitura de cabeçalho / CSV module for header reading
import csv
# Módulo de caminhos / Path module
import os

# Widgets Qt / Qt widgets
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QPushButton, QLineEdit,
    QDialogButtonBox, QFrame, QFileDialog,
    QDoubleSpinBox, QGroupBox, QRadioButton,
    QButtonGroup, QCheckBox, QMessageBox,
)
from qgis.PyQt.QtCore import Qt, QUrl, QVariant

# Módulos QGIS / QGIS modules
from qgis.core import (
    QgsVectorLayer,
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsWkbTypes,
    QgsFeature,
    QgsField,
    QgsFields,
)
# Widget de seleção de CRS / CRS selection widget
from qgis.gui import QgsProjectionSelectionWidget
# Módulo de processamento QGIS / QGIS processing module
import processing


# ─────────────────────────────────────────────────────────────────────────────
# Diálogo / Dialog
# ─────────────────────────────────────────────────────────────────────────────
class PointsToPolygonDialog(QDialog):
    """
    Diálogo para configurar a geração de polígono a partir de pontos.
    Dialog to configure polygon generation from points.
    """

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._headers = []
        self._csv_path = ''

        self.setWindowTitle('RTH — Pontos de GPS para Polígono / GPS Points to Polygon')
        self.setMinimumWidth(420)
        self.setModal(True)

        root = QVBoxLayout()
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # ── Cabeçalho / Header ─────────────────────────────────────────────
        lbl_title = QLabel(
            '<span style="font-size:13px;font-weight:bold;">'
            '⬡  Pontos de GPS para Polígono / GPS Points to Polygon</span>'
        )
        lbl_title.setAlignment(Qt.AlignCenter)
        root.addWidget(lbl_title)

        sep0 = QFrame(); sep0.setFrameShape(QFrame.HLine); sep0.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep0)

        # ── Fonte dos pontos / Point source ────────────────────────────────
        grp_src = QGroupBox('Fonte dos Pontos / Point Source')
        lay_src = QVBoxLayout()
        lay_src.setSpacing(6)

        self._bg_src = QButtonGroup(self)

        # Opção 1: camada ativa / Option 1: active layer
        self.radio_layer = QRadioButton(
            'Usar camada ativa de pontos / Use active point layer'
        )
        self._bg_src.addButton(self.radio_layer, 0)
        lay_src.addWidget(self.radio_layer)

        # Opção 2: arquivo CSV / Option 2: CSV file
        self.radio_csv = QRadioButton(
            'Importar CSV / Import CSV'
        )
        self.radio_csv.setChecked(True)
        self._bg_src.addButton(self.radio_csv, 1)
        lay_src.addWidget(self.radio_csv)

        # Seletor de arquivo CSV / CSV file selector
        csv_row = QHBoxLayout()
        self.edit_file = QLineEdit()
        self.edit_file.setPlaceholderText('Selecione o arquivo CSV / Select CSV file...')
        self.edit_file.setReadOnly(True)
        csv_row.addWidget(self.edit_file)
        self.btn_browse = QPushButton('...')
        self.btn_browse.setFixedWidth(32)
        self.btn_browse.clicked.connect(self._on_browse)
        csv_row.addWidget(self.btn_browse)
        lay_src.addLayout(csv_row)

        # Colunas lat/lon / Lat/lon columns
        form_cols = QFormLayout()
        form_cols.setSpacing(6)
        self.combo_lat = QComboBox()
        form_cols.addRow('Latitude:', self.combo_lat)
        self.combo_lon = QComboBox()
        form_cols.addRow('Longitude:', self.combo_lon)
        lay_src.addLayout(form_cols)

        # Seleção de CRS das coordenadas / Coordinate CRS selection
        lbl_crs = QLabel('CRS das coordenadas / Coordinate CRS:')
        lbl_crs.setStyleSheet('font-size:10px;')
        lay_src.addWidget(lbl_crs)
        self.crs_widget = QgsProjectionSelectionWidget()
        # Padrão WGS84 — GPS padrão / Default WGS84 — standard GPS
        self.crs_widget.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
        lay_src.addWidget(self.crs_widget)
        self._crs_label = lbl_crs

        grp_src.setLayout(lay_src)
        root.addWidget(grp_src)

        # Conecta rádios para habilitar/desabilitar controles CSV (chamada inicial após _btn_ok ser criado)
        # Connect radios to enable/disable CSV controls (initial call after _btn_ok is created)
        self.radio_csv.toggled.connect(self._on_source_toggled)

        # ── Modo de Geração / Generation Mode ─────────────────────────────
        grp_mode = QGroupBox('Modo de Geração / Generation Mode')
        lay_mode = QVBoxLayout()
        lay_mode.setSpacing(6)

        self._bg_mode = QButtonGroup(self)

        # Opção 1: um polígono com todos os pontos / Option 1: single polygon from all points
        self.radio_single = QRadioButton(
            'Um polígono com todos os pontos / Single polygon from all points'
        )
        self.radio_single.setChecked(True)
        self._bg_mode.addButton(self.radio_single, 0)
        lay_mode.addWidget(self.radio_single)

        # Opção 2: múltiplos polígonos agrupados por coluna ID / Option 2: multiple polygons grouped by ID column
        self.radio_multi = QRadioButton(
            'Múltiplos polígonos por identificador / Multiple polygons by ID'
        )
        self._bg_mode.addButton(self.radio_multi, 1)
        lay_mode.addWidget(self.radio_multi)

        # Seletor de coluna identificadora (visível apenas no modo múltiplo)
        # ID column selector (visible only in multiple mode)
        id_row = QHBoxLayout()
        id_row.setSpacing(6)
        self.lbl_id_col = QLabel('Coluna ID / ID Column:')
        self.lbl_id_col.setStyleSheet('font-size:10px; margin-left:16px;')
        self.combo_id = QComboBox()
        self.combo_id.setToolTip(
            'Pontos com o mesmo valor nesta coluna formarão um polígono / '
            'Points sharing the same value in this column will form one polygon'
        )
        id_row.addWidget(self.lbl_id_col)
        id_row.addWidget(self.combo_id, 1)
        lay_mode.addLayout(id_row)

        grp_mode.setLayout(lay_mode)
        root.addWidget(grp_mode)

        # Conecta o rádio de modo para mostrar/esconder o seletor de ID
        # Connect mode radio to show/hide ID selector
        self.radio_multi.toggled.connect(self._on_mode_toggled)
        self._on_mode_toggled(False)  # Estado inicial / Initial state

        # ── Parâmetros Forma Côncava / Concave Hull parameters ─────────────
        grp_hull = QGroupBox('Forma Côncava / Concave Hull')
        lay_hull = QVBoxLayout()
        lay_hull.setSpacing(6)

        lbl_alpha_info = QLabel(
            'Limiar (0 = muito côncavo  →  1 = convexo)\n'
            'Threshold (0 = very concave  →  1 = convex)'
        )
        lbl_alpha_info.setStyleSheet('font-size:10px;')
        lay_hull.addWidget(lbl_alpha_info)

        form_hull = QFormLayout()
        form_hull.setSpacing(6)

        self.spin_alpha = QDoubleSpinBox()
        self.spin_alpha.setRange(0.0, 1.0)
        self.spin_alpha.setValue(0.3)       # Padrão agrícola / Agricultural default
        self.spin_alpha.setDecimals(2)
        self.spin_alpha.setSingleStep(0.05)
        form_hull.addRow('Limiar / Threshold:', self.spin_alpha)

        lay_hull.addLayout(form_hull)

        # Opção sem multigeometria / No multigeometry option
        self.chk_single = QCheckBox(
            'Forçar polígono único / Force single polygon'
        )
        self.chk_single.setChecked(True)
        lay_hull.addWidget(self.chk_single)

        # Manter camada de pontos / Keep point layer
        self.chk_keep_pts = QCheckBox(
            'Manter camada de pontos no projeto / Keep point layer in project'
        )
        self.chk_keep_pts.setChecked(False)
        lay_hull.addWidget(self.chk_keep_pts)

        grp_hull.setLayout(lay_hull)
        root.addWidget(grp_hull)

        # ── Botões / Buttons ───────────────────────────────────────────────
        sep1 = QFrame(); sep1.setFrameShape(QFrame.HLine); sep1.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep1)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Ok).setText('Gerar Polígono / Generate Polygon')
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        self._btn_ok = btn_box.button(QDialogButtonBox.Ok)
        root.addWidget(btn_box)

        self.setLayout(root)
        self._on_source_toggled(True)  # Estado inicial — após _btn_ok ser criado / Initial state — after _btn_ok is created

    # ── Controles CSV habilitados conforme seleção / CSV controls enabled based on selection ──
    def _on_source_toggled(self, csv_checked):
        """Habilita ou desabilita controles CSV / Enable or disable CSV controls."""
        self.edit_file.setEnabled(csv_checked)
        self.btn_browse.setEnabled(csv_checked)
        self.combo_lat.setEnabled(csv_checked)
        self.combo_lon.setEnabled(csv_checked)
        self.crs_widget.setEnabled(csv_checked)
        self._crs_label.setEnabled(csv_checked)
        # Quando muda para camada ativa, popula combo_id com os campos da camada
        # When switching to active layer, populate combo_id with layer fields
        if not csv_checked:
            active = self.iface.activeLayer()
            if active and hasattr(active, 'fields'):
                self.combo_id.clear()
                for field in active.fields():
                    self.combo_id.addItem(field.name())
        self._update_ok_state()

    def _on_mode_toggled(self, multi_checked):
        """Mostra ou esconde o seletor de coluna ID / Show or hide the ID column selector."""
        self.lbl_id_col.setVisible(multi_checked)
        self.combo_id.setVisible(multi_checked)

    def _update_ok_state(self):
        """Habilita OK apenas quando a fonte está pronta / Enable OK only when source is ready."""
        if self.radio_csv.isChecked():
            self._btn_ok.setEnabled(bool(self._csv_path))
        else:
            self._btn_ok.setEnabled(True)

    def _on_browse(self):
        """Abre seletor de arquivo CSV / Open CSV file selector."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            'Selecione o CSV / Select CSV',
            '',
            'CSV (*.csv);;Todos os arquivos / All files (*)'
        )
        if not path:
            return

        # Lê o cabeçalho / Read header
        try:
            with open(path, newline='', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                self._headers = next(reader)
        except Exception as e:
            QMessageBox.warning(self, 'RTH', f'Erro ao ler cabeçalho.\nError reading header.\n{e}')
            return

        self._csv_path = path
        self.edit_file.setText(path)

        # Preenche combos de lat/lon e ID / Fill lat/lon and ID combos
        self.combo_lat.clear()
        self.combo_lon.clear()
        self.combo_id.clear()
        for h in self._headers:
            self.combo_lat.addItem(h)
            self.combo_lon.addItem(h)
            self.combo_id.addItem(h)

        # Auto-detecta colunas / Auto-detect columns
        lat_cands = ['latitude', 'lat', 'y']
        lon_cands = ['longitude', 'lon', 'long', 'x', 'lng']

        for i, h in enumerate(self._headers):
            if h.lower() in lat_cands:
                self.combo_lat.setCurrentIndex(i)
                break
        for i, h in enumerate(self._headers):
            if h.lower() in lon_cands:
                self.combo_lon.setCurrentIndex(i)
                break

        self._update_ok_state()

    # ── Propriedades / Properties ──────────────────────────────────────────
    @property
    def use_csv(self):
        """True se a fonte for CSV / True if source is CSV."""
        return self.radio_csv.isChecked()

    @property
    def csv_path(self):
        """Caminho do CSV selecionado / Selected CSV path."""
        return self._csv_path

    @property
    def lat_field(self):
        """Nome da coluna de latitude / Latitude column name."""
        return self.combo_lat.currentText()

    @property
    def lon_field(self):
        """Nome da coluna de longitude / Longitude column name."""
        return self.combo_lon.currentText()

    @property
    def alpha(self):
        """Limiar da forma côncava / Concave hull threshold."""
        return self.spin_alpha.value()

    @property
    def force_single(self):
        """Forçar polígono único / Force single polygon."""
        return self.chk_single.isChecked()

    @property
    def keep_points(self):
        """Manter camada de pontos / Keep point layer."""
        return self.chk_keep_pts.isChecked()

    @property
    def selected_crs(self):
        """Retorna o CRS selecionado pelo usuário / Returns user-selected CRS."""
        return self.crs_widget.crs()

    @property
    def multi_mode(self):
        """True se o modo múltiplos polígonos por ID estiver ativo / True if multiple polygons by ID mode is active."""
        return self.radio_multi.isChecked()

    @property
    def id_field(self):
        """Nome da coluna identificadora no modo múltiplo / ID column name in multiple mode."""
        return self.combo_id.currentText() if self.radio_multi.isChecked() else ''


# ─────────────────────────────────────────────────────────────────────────────
# Ferramenta principal / Main tool
# ─────────────────────────────────────────────────────────────────────────────
class PointsToPolygonTool:
    """
    Gera um polígono de forma côncava a partir de um CSV ou camada de pontos ativa.
    Generates a concave hull polygon from a CSV or the active point layer.
    """

    def __init__(self, iface):
        self.iface = iface

    def run(self):
        """Abre o diálogo e executa a geração do polígono / Open dialog and execute polygon generation."""
        dlg = PointsToPolygonDialog(self.iface, parent=self.iface.mainWindow())
        if dlg.exec_() != QDialog.Accepted:
            return  # Usuário cancelou / User cancelled

        # ── Obtém a camada de pontos / Get point layer ────────────────────
        point_layer = None
        temp_layer_added = False   # Controla se adicionamos camada temporária / Tracks if we added a temp layer

        if dlg.use_csv:
            # Carrega CSV como camada de pontos via provider delimitedtext
            # Load CSV as point layer via delimitedtext provider
            uri = QUrl.fromLocalFile(dlg.csv_path).toString()
            # Usa o CRS selecionado pelo usuário (padrão WGS84) / Use user-selected CRS (default WGS84)
            crs_authid = dlg.selected_crs.authid() or 'EPSG:4326'
            uri += '?delimiter=,&xField={}&yField={}&crs={}'.format(
                dlg.lon_field,   # xField = longitude / xField = longitude
                dlg.lat_field,   # yField = latitude / yField = latitude
                crs_authid,
            )
            layer_name = os.path.splitext(os.path.basename(dlg.csv_path))[0]
            point_layer = QgsVectorLayer(uri, layer_name, 'delimitedtext')

            if not point_layer.isValid():
                QMessageBox.critical(
                    None, 'RTH',
                    'Não foi possível carregar o CSV. Verifique as colunas.\n'
                    'Could not load CSV. Check the columns.'
                )
                return

            # Adiciona ao projeto temporariamente para o processing acessar
            # Add to project temporarily so processing can access it
            QgsProject.instance().addMapLayer(point_layer, False)  # False = não adiciona ao painel
            temp_layer_added = True

        else:
            # Usa a camada ativa / Use active layer
            point_layer = self.iface.activeLayer()
            if not point_layer:
                QMessageBox.warning(
                    None, 'RTH',
                    'Nenhuma camada ativa.\nNo active layer.'
                )
                return
            if QgsWkbTypes.geometryType(point_layer.wkbType()) != QgsWkbTypes.PointGeometry:
                QMessageBox.warning(
                    None, 'RTH',
                    'A camada ativa deve ser de pontos.\nThe active layer must be a point layer.'
                )
                return

        base_name = os.path.splitext(os.path.basename(dlg.csv_path))[0] if dlg.use_csv else point_layer.name()

        # ── Modo múltiplos polígonos por ID / Multiple polygons by ID mode ─
        if dlg.multi_mode:
            poly_layer = self._run_multi(point_layer, dlg, base_name)
        else:
            # ── Modo único / Single mode ──────────────────────────────────
            try:
                result = processing.run(
                    'qgis:concavehull',
                    {
                        'INPUT':            point_layer,
                        'ALPHA':            dlg.alpha,
                        'HOLES':            False,
                        'NO_MULTIGEOMETRY': dlg.force_single,
                        'OUTPUT':           'memory:Poligono_Concavo',
                    }
                )
                poly_layer = result['OUTPUT']
            except Exception as e:
                QMessageBox.critical(
                    None, 'RTH',
                    f'Erro ao gerar forma côncava.\nError generating concave hull.\n{e}'
                )
                if temp_layer_added and not dlg.keep_points:
                    QgsProject.instance().removeMapLayer(point_layer.id())
                return

        if poly_layer is None:
            if temp_layer_added and not dlg.keep_points:
                QgsProject.instance().removeMapLayer(point_layer.id())
            return

        # ── Adiciona camada ao projeto / Add layer to project ─────────────
        poly_layer.setName(f'Poligono_{base_name}_alpha{dlg.alpha:.2f}')
        QgsProject.instance().addMapLayer(poly_layer)

        # ── Gerencia camada de pontos temporária / Manage temporary point layer ──
        if temp_layer_added:
            if dlg.keep_points:
                QgsProject.instance().addMapLayer(point_layer)
            else:
                QgsProject.instance().removeMapLayer(point_layer.id())

        # ── Mensagem de sucesso / Success message ─────────────────────────
        feat_count = poly_layer.featureCount()
        self.iface.messageBar().pushMessage(
            'RTH Pontos de GPS para Polígono / GPS Points to Polygon',
            f'{feat_count} polígono(s) gerado(s) | limiar / threshold: {dlg.alpha:.2f}',
            level=0, duration=6,
        )

    def _run_multi(self, point_layer, dlg, base_name):
        """Gera um polígono por valor único da coluna ID / Generate one polygon per unique ID column value.

        :param point_layer: camada de pontos de entrada / input point layer
        :param dlg: diálogo com os parâmetros / dialog with parameters
        :param base_name: nome base para a camada de saída / base name for output layer
        :returns: camada de polígonos com campo ID, ou None em caso de erro / polygon layer with ID field, or None on error
        :rtype: QgsVectorLayer | None
        """
        id_field = dlg.id_field
        if not id_field:
            QMessageBox.warning(None, 'RTH', 'Selecione a coluna ID.\nSelect the ID column.')
            return None

        # Coleta valores únicos do campo ID / Collect unique values of the ID field
        unique_ids = []
        seen = set()
        for feat in point_layer.getFeatures():
            val = feat[id_field]
            if val not in seen:
                seen.add(val)
                unique_ids.append(val)

        if not unique_ids:
            QMessageBox.warning(None, 'RTH', 'Nenhum valor encontrado na coluna ID.\nNo values found in the ID column.')
            return None

        # Camada de saída com campo ID / Output layer with ID field
        crs_authid = point_layer.crs().authid() or 'EPSG:4326'
        out_layer = QgsVectorLayer(f'Polygon?crs={crs_authid}', 'multi_poly', 'memory')
        out_fields = QgsFields()
        out_fields.append(QgsField(id_field, QVariant.String))
        out_layer.dataProvider().addAttributes(out_fields)
        out_layer.updateFields()

        skipped = 0
        for uid in unique_ids:
            # Cria camada temporária com os pontos deste ID / Create temp layer with points for this ID
            temp = QgsVectorLayer(f'Point?crs={crs_authid}', 'temp_pts', 'memory')
            temp.dataProvider().addAttributes(point_layer.fields())
            temp.updateFields()

            feats = [f for f in point_layer.getFeatures() if f[id_field] == uid]

            # Concave hull precisa de pelo menos 3 pontos / Concave hull needs at least 3 points
            if len(feats) < 3:
                skipped += 1
                continue

            temp.dataProvider().addFeatures(feats)
            temp.updateExtents()
            QgsProject.instance().addMapLayer(temp, False)

            try:
                result = processing.run(
                    'qgis:concavehull',
                    {
                        'INPUT':            temp,
                        'ALPHA':            dlg.alpha,
                        'HOLES':            False,
                        'NO_MULTIGEOMETRY': dlg.force_single,
                        'OUTPUT':           'memory:',
                    }
                )
                hull = result['OUTPUT']
                for hf in hull.getFeatures():
                    new_feat = QgsFeature(out_layer.fields())
                    new_feat.setGeometry(hf.geometry())
                    new_feat[id_field] = str(uid)
                    out_layer.dataProvider().addFeature(new_feat)
            except Exception:
                skipped += 1
            finally:
                QgsProject.instance().removeMapLayer(temp.id())

        out_layer.updateExtents()

        if skipped > 0:
            self.iface.messageBar().pushMessage(
                'RTH',
                f'{skipped} grupo(s) ignorado(s) por ter menos de 3 pontos / '
                f'{skipped} group(s) skipped for having fewer than 3 points',
                level=1, duration=5,
            )

        return out_layer
