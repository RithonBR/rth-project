# -*- coding: utf-8 -*-
"""
tool_planting_lines.py

Ferramenta de Linhas de Plantio/Colheita / Planting-Harvest Lines Tool

Gera linhas paralelas (com suporte a curvas) de plantio/colheita dentro de um polígono
selecionado, baseadas em uma linha mestra digitada pelo usuário e no espaçamento do implemento.

Generates parallel (curve-aware) planting/harvesting lines inside a selected polygon,
based on a master line digitized by the user and the implement spacing.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

import math  # Cálculos geométricos / Geometric calculations

# Importações do QGIS Core / QGIS Core imports
from qgis.core import (
    Qgis,
    QgsProject,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsField,
    QgsWkbTypes,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsCsException,
)

# Importações do Qt / Qt imports
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtWidgets import (
    QDialog, QLabel, QDoubleSpinBox, QPushButton,
    QVBoxLayout, QHBoxLayout, QGroupBox, QMessageBox,
    QFrame, QComboBox, QRadioButton, QButtonGroup,
    QScrollArea, QWidget, QLineEdit,
)

# Utilitário de detecção de UTM regional / Regional UTM detection utility
from core.rth_utm_utils import detect_regional_utm
from core.rth_layer_utils import collapse_layer


# ─────────────────────────────────────────────────────────────────────────────
# Diálogo principal / Main dialog
# ─────────────────────────────────────────────────────────────────────────────
class PlantingLinesDialog(QDialog):
    """
    Diálogo de configuração das linhas de plantio.
    Planting lines configuration dialog.
    """

    _STYLE_DRAW = """
        QPushButton {
            background-color: #1976D2; color: white; border: none;
            padding: 9px 16px; border-radius: 5px; font-weight: bold; font-size: 11px;
        }
        QPushButton:hover   { background-color: #1565C0; }
        QPushButton:pressed { background-color: #0D47A1; }
        QPushButton:disabled{ background-color: #5a7fa8; color: #aaa; }
    """
    _STYLE_GENERATE = """
        QPushButton {
            background-color: #388E3C; color: white; border: none;
            padding: 9px 16px; border-radius: 5px; font-weight: bold; font-size: 11px;
        }
        QPushButton:hover   { background-color: #2E7D32; }
        QPushButton:pressed { background-color: #1B5E20; }
        QPushButton:disabled{ background-color: #4d7a50; color: #aaa; }
    """
    _STYLE_CANCEL = """
        QPushButton {
            background-color: #616161; color: white; border: none;
            padding: 9px 16px; border-radius: 5px; font-size: 11px;
        }
        QPushButton:hover   { background-color: #424242; }
        QPushButton:pressed { background-color: #212121; }
    """

    def __init__(self, epsg, datum_name, zone, hemi, parent=None):
        super().__init__(parent)
        self.setWindowTitle('RTH — Linhas de Plantio/Colheita / Planting/Harvest Lines')
        self.setMinimumWidth(710)
        self.setMinimumHeight(700)
        self.setMaximumHeight(720)
        # Mantém janela acima do QGIS sem bloquear o canvas / Keep window above QGIS without blocking canvas
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)

        # Layout externo do diálogo (contém apenas o scroll area)
        # Outer dialog layout (contains only the scroll area)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # Área de rolagem / Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer_layout.addWidget(scroll)

        # Widget container dentro do scroll / Container widget inside scroll
        container = QWidget()
        scroll.setWidget(container)

        root = QVBoxLayout(container)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # ── Cabeçalho / Header ─────────────────────────────────────────────
        lbl_title = QLabel('<span style="font-size:14px;font-weight:bold;">🌱 Linhas de Plantio/Colheita / Planting/Harvest Lines</span>')
        lbl_title.setAlignment(Qt.AlignCenter)
        root.addWidget(lbl_title)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # ── Sistema de referência / Reference system ───────────────────────
        grp_datum = QGroupBox('Sistema de Referência / Reference System')
        lay_datum = QVBoxLayout()
        lay_datum.setContentsMargins(8, 4, 8, 8)
        self.lbl_datum = QLabel(
            f'{datum_name}  •  EPSG:{epsg}  •  Zona / Zone {zone}{hemi}'
        )
        self.lbl_datum.setStyleSheet('font-size:11px; font-weight:bold;')
        lay_datum.addWidget(self.lbl_datum)
        grp_datum.setLayout(lay_datum)
        root.addWidget(grp_datum)

        # ── Nome da camada / Layer name ────────────────────────────────────
        grp_name = QGroupBox('Nome da Camada / Layer Name')
        lay_name = QVBoxLayout()
        lay_name.setContentsMargins(8, 4, 8, 8)
        lbl_name = QLabel('Prefixo do nome (opcional) / Name prefix (optional):')
        lbl_name.setStyleSheet('font-size:11px;')
        lay_name.addWidget(lbl_name)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText('Ex: Talhao_A1, Campo_Norte, Fazenda_XYZ...')
        self.edit_name.setMinimumHeight(28)
        lay_name.addWidget(self.edit_name)
        lbl_name_hint = QLabel('  Deixe vazio para usar o nome padrão / Leave empty for default name')
        lbl_name_hint.setStyleSheet('font-size:9px; color:#aaa;')
        lay_name.addWidget(lbl_name_hint)
        grp_name.setLayout(lay_name)
        root.addWidget(grp_name)

        # ── Espaçamento / Spacing ──────────────────────────────────────────
        grp_spacing = QGroupBox('Implemento Agrícola / Agricultural Implement')
        lay_spacing = QVBoxLayout()
        lay_spacing.setContentsMargins(8, 4, 8, 8)
        lbl_sp = QLabel('Espaçamento entre linhas (m) / Row spacing (m):')
        lbl_sp.setStyleSheet('font-size:11px;')
        lay_spacing.addWidget(lbl_sp)

        self.spin_spacing = QDoubleSpinBox()
        self.spin_spacing.setRange(0.1, 5000.0)
        self.spin_spacing.setValue(15.0)
        self.spin_spacing.setSuffix(' m')
        self.spin_spacing.setDecimals(2)
        self.spin_spacing.setSingleStep(0.5)
        self.spin_spacing.setMinimumHeight(30)
        lay_spacing.addWidget(self.spin_spacing)
        grp_spacing.setLayout(lay_spacing)
        root.addWidget(grp_spacing)

        # ── Modo de geração / Generation mode ─────────────────────────────
        grp_mode = QGroupBox('Modo de Geração / Generation Mode')
        lay_mode = QVBoxLayout()
        lay_mode.setContentsMargins(8, 6, 8, 8)
        lay_mode.setSpacing(6)

        self._btn_group_mode = QButtonGroup(self)

        # Opção 1: somente linhas paralelas / Option 1: parallel lines only
        self.radio_lines_only = QRadioButton('Somente Linhas / Lines Only')
        self.radio_lines_only.setStyleSheet('font-size:11px; font-weight:bold;')
        self.radio_lines_only.setChecked(True)
        lbl_lines_only = QLabel(
            '  Linhas paralelas recortadas ao polígono original.\n'
            '  Parallel lines clipped to the original polygon.'
        )
        lbl_lines_only.setStyleSheet('font-size:9px; color:#aaa; margin-bottom:4px;')
        self._btn_group_mode.addButton(self.radio_lines_only, 0)
        lay_mode.addWidget(self.radio_lines_only)
        lay_mode.addWidget(lbl_lines_only)

        sep_mode = QFrame(); sep_mode.setFrameShape(QFrame.HLine); sep_mode.setFrameShadow(QFrame.Sunken)
        lay_mode.addWidget(sep_mode)

        # Opção 2: offset interno + linhas / Option 2: inward offset + lines
        self.radio_curved = QRadioButton('Linhas desconsiderando Bordadura / Lines ignoring Headland')
        self.radio_curved.setStyleSheet('font-size:11px; font-weight:bold;')
        lbl_curved = QLabel(
            '  Recua o polígono 1× o espaçamento (bordadura) antes de gerar as\n'
            '  linhas. As linhas ficam afastadas da borda do campo.\n'
            '  Shrinks polygon 1× spacing inward (headland) before generating\n'
            '  lines. Lines stay away from the field boundary.'
        )
        lbl_curved.setStyleSheet('font-size:9px; color:#aaa;')
        self._btn_group_mode.addButton(self.radio_curved, 1)
        lay_mode.addWidget(self.radio_curved)
        lay_mode.addWidget(lbl_curved)

        sep_mode2 = QFrame(); sep_mode2.setFrameShape(QFrame.HLine); sep_mode2.setFrameShadow(QFrame.Sunken)
        lay_mode.addWidget(sep_mode2)

        # Opção 3: linhas com curvas de retorno / Option 3: lines with turn arcs
        self.radio_turns = QRadioButton('Linhas com Curvas de Retorno / Lines with Turn Arcs')
        self.radio_turns.setStyleSheet('font-size:11px; font-weight:bold;')
        lbl_turns = QLabel(
            '  Recua 1× o espaçamento (bordadura) e conecta as linhas com\n'
            '  arcos circulares (serpentina) dentro do talhão.\n'
            '  Shrinks 1× spacing inward and connects lines with circular\n'
            '  arcs (snake pattern) clipped inside the field.'
        )
        lbl_turns.setStyleSheet('font-size:9px; color:#aaa;')
        self._btn_group_mode.addButton(self.radio_turns, 2)
        lay_mode.addWidget(self.radio_turns)
        lay_mode.addWidget(lbl_turns)

        grp_mode.setLayout(lay_mode)
        root.addWidget(grp_mode)

        # ── Raio de Curva / Turn Radius ─────────────────────────────────────
        self.grp_turns_config = QGroupBox('Curvas de Retorno / Turn Arcs')
        lay_turns = QVBoxLayout()
        lay_turns.setContentsMargins(8, 4, 8, 8)
        lbl_tr = QLabel('Raio mínimo de curva (m) / Minimum turn radius (m):')
        lbl_tr.setStyleSheet('font-size:11px;')
        lay_turns.addWidget(lbl_tr)

        self.spin_turn_radius = QDoubleSpinBox()
        self.spin_turn_radius.setRange(0.5, 500.0)
        self.spin_turn_radius.setValue(6.0)
        self.spin_turn_radius.setSuffix(' m')
        self.spin_turn_radius.setDecimals(1)
        self.spin_turn_radius.setSingleStep(0.5)
        self.spin_turn_radius.setMinimumHeight(30)
        lay_turns.addWidget(self.spin_turn_radius)

        lbl_tr_hint = QLabel(
            '  Ex: 3,0 m (trator/ATV)  •  6,0 m (plantadeira)  •  12,0 m (colhedora)\n'
            '  Ex: 3.0 m (tractor/ATV)  •  6.0 m (planter)  •  12.0 m (harvester)'
        )
        lbl_tr_hint.setStyleSheet('font-size:9px; color:#aaa; margin-top:2px;')
        lay_turns.addWidget(lbl_tr_hint)
        self.grp_turns_config.setLayout(lay_turns)
        self.grp_turns_config.setVisible(False)
        root.addWidget(self.grp_turns_config)

        # ── Linha Mestra / Master Line ─────────────────────────────────────
        grp_line = QGroupBox('Linha Mestra / Master Line')
        lay_line = QVBoxLayout()
        lay_line.setContentsMargins(8, 4, 8, 8)
        lay_line.setSpacing(6)

        lbl_hint = QLabel(
            'Clique em "Desenhar" para criar a camada <b>Linha_Mestre</b> e\n'
            'usar a ferramenta nativa de digitação do QGIS.\n'
            'Click point by point — right-click to finish the line.\n'
            'Depois clique em "Gerar Linhas" / Then click "Generate Lines".'
        )
        lbl_hint.setStyleSheet('font-size:10px;')
        lbl_hint.setWordWrap(True)
        lay_line.addWidget(lbl_hint)

        self.lbl_line_status = QLabel('— Nenhuma linha desenhada / No line drawn —')
        self.lbl_line_status.setAlignment(Qt.AlignCenter)
        self.lbl_line_status.setStyleSheet(
            'font-style:italic; font-size:10px; '
            'padding:5px; border:1px dashed #888; border-radius:3px;'
        )
        lay_line.addWidget(self.lbl_line_status)

        self.btn_draw = QPushButton('✏  Desenhar Linha Mestra / Draw Master Line')
        self.btn_draw.setStyleSheet(self._STYLE_DRAW)
        self.btn_draw.setMinimumHeight(36)
        lay_line.addWidget(self.btn_draw)

        grp_line.setLayout(lay_line)
        root.addWidget(grp_line)

        # ── Suavização das linhas / Line smoothing ─────────────────────────
        grp_smooth = QGroupBox('Suavização das Linhas / Line Smoothing')
        lay_smooth = QVBoxLayout()
        lay_smooth.setContentsMargins(8, 4, 8, 8)
        lbl_smooth = QLabel('Intensidade de suavização / Smoothing intensity:')
        lbl_smooth.setStyleSheet('font-size:11px;')
        lay_smooth.addWidget(lbl_smooth)

        self.combo_smooth = QComboBox()
        self._smooth_opts = [
            ('Sem Suavização / No Smoothing',   0, 0.00),
            ('Suave / Gentle',                  1, 0.15),
            ('Médio / Medium',                  3, 0.25),
            ('Forte / Strong',                  5, 0.35),
            ('Muito Forte / Very Strong',        8, 0.45),
        ]
        for label, _, _ in self._smooth_opts:
            self.combo_smooth.addItem(label)
        self.combo_smooth.setCurrentIndex(0)
        lay_smooth.addWidget(self.combo_smooth)
        grp_smooth.setLayout(lay_smooth)
        root.addWidget(grp_smooth)

        # ── Ações / Actions ────────────────────────────────────────────────
        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); sep2.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep2)

        row_btns = QHBoxLayout()
        self.btn_generate = QPushButton('▶  Gerar Linhas / Generate Lines')
        self.btn_generate.setStyleSheet(self._STYLE_GENERATE)
        self.btn_generate.setMinimumHeight(36)
        self.btn_generate.setEnabled(False)

        self.btn_cancel = QPushButton('Cancelar / Cancel')
        self.btn_cancel.setStyleSheet(self._STYLE_CANCEL)
        self.btn_cancel.setMinimumHeight(36)

        row_btns.addWidget(self.btn_generate)
        row_btns.addWidget(self.btn_cancel)
        root.addLayout(row_btns)

        self.btn_cancel.clicked.connect(self.reject)
        self.radio_turns.toggled.connect(self._on_mode_changed)

    def _on_mode_changed(self, _checked=False):
        """Mostra/esconde o grupo de configuração de curvas. / Show/hide the turn arcs config group."""
        self.grp_turns_config.setVisible(self.radio_turns.isChecked())

    # ── API pública / Public API ───────────────────────────────────────────
    @property
    def spacing(self):
        return self.spin_spacing.value()

    @property
    def mode(self):
        """'lines_only' | 'curved_borders' | 'with_turns'"""
        if self.radio_turns.isChecked():
            return 'with_turns'
        return 'curved_borders' if self.radio_curved.isChecked() else 'lines_only'

    @property
    def turn_radius(self):
        return self.spin_turn_radius.value()

    @property
    def custom_name(self):
        return self.edit_name.text().strip()

    @property
    def smoothing_params(self):
        idx = self.combo_smooth.currentIndex()
        _, iters, offset = self._smooth_opts[idx]
        return iters, offset

    def set_layer_created(self):
        """Atualiza status quando a camada Linha_Mestre é criada. / Updates status when Linha_Mestre layer is created."""
        self.lbl_line_status.setText(
            '✔  Camada "Linha_Mestre" criada no projeto.\n'
            'Digitize a linha no mapa e depois clique Gerar.\n'
            '"Linha_Mestre" layer added to project.\n'
            'Digitize the line on the map then click Generate.'
        )
        self.lbl_line_status.setStyleSheet(
            'font-size:10px; font-weight:bold; '
            'padding:5px; border:1px solid #4CAF50; border-radius:3px;'
        )
        self.btn_generate.setEnabled(True)
        self.btn_draw.setText('↩  Recriar Camada / Recreate Layer')


# ─────────────────────────────────────────────────────────────────────────────
# Ferramenta principal / Main tool class
# ─────────────────────────────────────────────────────────────────────────────
class PlantingLinesTool:
    """
    Ferramenta para gerar linhas paralelas de plantio usando uma camada vetorial como linha mestra.
    Tool to generate parallel planting lines using a vector layer as master line.
    """

    MAX_LINES = 20000
    TEMP_LAYER_NAME = 'Linha_Mestre'

    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self._polygon_geom = None
        self._layer_crs = None
        self._epsg = self._datum = self._zone = self._hemi = None
        self._temp_layer_id = None
        self._dlg = None

    # ── Ponto de entrada / Entry point ────────────────────────────────────
    def run(self):
        """Valida a seleção e abre o diálogo. / Validates selection and opens dialog."""
        layer = self.iface.activeLayer()
        if not layer or layer.type() != layer.VectorLayer:
            QMessageBox.warning(
                None, 'RTH Linhas de Plantio/Colheita / Planting/Harvest Lines',
                'Selecione uma camada vetorial de polígonos.\n'
                'Select a polygon vector layer.'
            )
            return

        if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            QMessageBox.warning(
                None, 'RTH Linhas de Plantio/Colheita / Planting/Harvest Lines',
                'A camada ativa deve conter polígonos.\n'
                'The active layer must contain polygons.'
            )
            return

        selected = layer.selectedFeatures()
        if not selected:
            QMessageBox.warning(
                None, 'RTH Linhas de Plantio/Colheita / Planting/Harvest Lines',
                'Selecione ao menos um polígono antes de ativar a ferramenta.\n'
                'Select at least one polygon before activating the tool.'
            )
            return

        geoms = [f.geometry() for f in selected]
        self._polygon_geom = QgsGeometry.unaryUnion(geoms) if len(geoms) > 1 else geoms[0]
        self._layer_crs = layer.crs()
        self._temp_layer_id = None

        # ── Detecta UTM regional / Detect regional UTM ──────────────────
        centroid_layer = self._polygon_geom.centroid().asPoint()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        if self._layer_crs.authid() != 'EPSG:4326':
            xform = QgsCoordinateTransform(self._layer_crs, wgs84, QgsProject.instance())
            try:
                centroid_wgs = xform.transform(centroid_layer)
            except QgsCsException:
                centroid_wgs = centroid_layer
        else:
            centroid_wgs = centroid_layer

        self._epsg, self._datum, self._zone, self._hemi = detect_regional_utm(
            centroid_wgs.x(), centroid_wgs.y()
        )

        self._dlg = PlantingLinesDialog(self._epsg, self._datum, self._zone, self._hemi,
                                        parent=self.iface.mainWindow())
        self._dlg.btn_draw.clicked.connect(self._start_drawing)
        self._dlg.btn_generate.clicked.connect(self._do_generate)
        self._dlg.finished.connect(self._on_dialog_finished)
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()

    # ── Cria camada Linha_Mestre / Create Linha_Mestre layer ──────────────
    def _start_drawing(self):
        """
        Cria (ou recria) a camada 'Linha_Mestre' e ativa a ferramenta de adição de feição.
        Creates (or recreates) the 'Linha_Mestre' layer and activates the add feature tool.
        """
        if self._temp_layer_id:
            old = QgsProject.instance().mapLayer(self._temp_layer_id)
            if old:
                QgsProject.instance().removeMapLayer(self._temp_layer_id)
            self._temp_layer_id = None

        crs_str = self._layer_crs.authid()
        temp = QgsVectorLayer(f'LineString?crs={crs_str}', self.TEMP_LAYER_NAME, 'memory')

        if not temp.isValid():
            QMessageBox.critical(
                None, 'RTH',
                'Não foi possível criar a camada Linha_Mestre.\n'
                'Could not create Linha_Mestre layer.'
            )
            return

        QgsProject.instance().addMapLayer(temp)
        collapse_layer(temp)
        self._temp_layer_id = temp.id()

        self.iface.setActiveLayer(temp)
        temp.startEditing()
        self._activate_curve_tool()

        self.iface.messageBar().pushMessage(
            'RTH Linhas de Plantio/Colheita / Planting/Harvest Lines',
            'Digitize a linha mestra na camada "Linha_Mestre". '
            'Clique para adicionar vértices — clique direito para finalizar. '
            '/ Digitize master line in "Linha_Mestre" layer. '
            'Click to add vertices — right-click to finish.',
            level=Qgis.MessageLevel.Info, duration=30,
        )

        if self._dlg:
            self._dlg.set_layer_created()
            self._dlg.raise_()
            self._dlg.activateWindow()

    # ── Gera as linhas paralelas / Generate parallel lines ────────────────
    def _do_generate(self):
        """Lê a linha mestra da camada e gera as linhas paralelas. / Reads master line from layer and generates parallel lines."""
        spacing = self._dlg.spacing if self._dlg else 15.0

        if not self._temp_layer_id:
            QMessageBox.warning(None, 'RTH', 'Primeiro crie e desenhe a linha mestra.\nFirst create and draw the master line.')
            return

        temp = QgsProject.instance().mapLayer(self._temp_layer_id)
        if not temp:
            QMessageBox.warning(None, 'RTH', 'Camada "Linha_Mestre" não encontrada.\n"Linha_Mestre" layer not found.')
            return

        if temp.isEditable():
            temp.commitChanges()

        feats = list(temp.getFeatures())
        if not feats:
            QMessageBox.warning(None, 'RTH', 'Nenhuma feição em "Linha_Mestre". Desenhe a linha primeiro.\nNo features in "Linha_Mestre". Draw the line first.')
            return

        if len(feats) == 1:
            master_geom = feats[0].geometry()
        else:
            master_geom = QgsGeometry.collectGeometry([f.geometry() for f in feats])

        if master_geom.isEmpty():
            QMessageBox.warning(None, 'RTH', 'Geometria da linha mestra está vazia.\nMaster line geometry is empty.')
            return

        # ── Transformações de CRS / CRS transformations ──────────────────
        utm_crs = QgsCoordinateReferenceSystem(f'EPSG:{self._epsg}')
        xform_layer_utm = QgsCoordinateTransform(self._layer_crs, utm_crs, QgsProject.instance())

        master_utm = QgsGeometry(master_geom)
        try:
            master_utm.transform(xform_layer_utm)
        except QgsCsException as e:
            QMessageBox.critical(None, 'RTH', f'Erro ao transformar linha mestra.\nError transforming master line.\n{e}')
            return

        poly_utm = QgsGeometry(self._polygon_geom)
        try:
            poly_utm.transform(xform_layer_utm)
        except QgsCsException as e:
            QMessageBox.critical(None, 'RTH', f'Erro ao reprojetar polígono.\nError reprojecting polygon.\n{e}')
            return

        # ── Modo de geração / Generation mode ────────────────────────────
        gen_mode = self._dlg.mode if self._dlg else 'lines_only'
        turn_radius = 6.0

        if gen_mode == 'curved_borders':
            # Recua 1× o espaçamento (bordadura) / Shrink 1× spacing inward (headland)
            poly_inner = poly_utm.buffer(
                -spacing, 5,
                Qgis.EndCapStyle.Flat, Qgis.JoinStyle.Miter, 10.0
            )
            if not poly_inner or poly_inner.isEmpty():
                QMessageBox.warning(
                    None, 'RTH',
                    f'O offset interno de {spacing} m resultou em polígono vazio.\n'
                    f'O campo pode ser pequeno demais para esse espaçamento.\n\n'
                    f'Inward offset of {spacing} m resulted in empty polygon.\n'
                    f'The field may be too small for this spacing.'
                )
                return
            work_poly = poly_inner
            mode_label = 'SemBordadura'

        elif gen_mode == 'with_turns':
            turn_radius = self._dlg.turn_radius if self._dlg else 6.0
            # Usa o mesmo recuo de bordadura para que os arcos caibam dentro do talhão
            # Uses the same headland inset so arcs fit inside the field boundary
            poly_inner = poly_utm.buffer(
                -spacing, 5,
                Qgis.EndCapStyle.Flat, Qgis.JoinStyle.Miter, 10.0
            )
            if not poly_inner or poly_inner.isEmpty():
                QMessageBox.warning(
                    None, 'RTH',
                    f'O offset interno de {spacing} m resultou em polígono vazio.\n'
                    f'O campo pode ser pequeno demais para esse espaçamento.\n\n'
                    f'Inward offset of {spacing} m resulted in empty polygon.\n'
                    f'The field may be too small for this spacing.'
                )
                return
            work_poly = poly_inner
            mode_label = f'CurvasRetorno_r{turn_radius:.0f}m'

        else:
            work_poly = poly_utm
            mode_label = 'SomentLinhas'

        # ── Lê parâmetros de suavização / Read smoothing parameters ─────────
        smooth_iters, smooth_offset = self._dlg.smoothing_params if self._dlg else (0, 0.0)

        # ── Gera linhas / Generate lines ──────────────────────────────────
        result = self._generate_parallel_lines(master_utm, work_poly, spacing, smooth_iters, smooth_offset)

        if result is None:
            return
        if not result:
            QMessageBox.warning(
                None, 'RTH',
                'Nenhuma linha gerada dentro do polígono. '
                'Verifique a posição e direção da linha mestra.\n'
                'No lines generated inside the polygon. '
                'Check the master line position and direction.'
            )
            return

        # ── Nome da camada / Layer name ───────────────────────────────────
        custom_name = (self._dlg.custom_name if self._dlg else '').strip()
        base_name = custom_name if custom_name else 'Linhas_Plantio'
        layer_name = f'{base_name}_{spacing:.1f}m_{mode_label}_EPSG_{self._epsg}'

        # ── Cria camada de resultado / Create result layer ────────────────
        vl = QgsVectorLayer(f'LineString?crs=EPSG:{self._epsg}', layer_name, 'memory')
        pr = vl.dataProvider()
        pr.addAttributes([
            QgsField('id',            QVariant.Int),
            QgsField('dist_mestra_m', QVariant.Double),
            QgsField('espacamento_m', QVariant.Double),
            QgsField('datum',         QVariant.String),
        ])
        vl.updateFields()

        features = []
        for idx, (geom_utm, dist) in enumerate(result, start=1):
            f = QgsFeature(vl.fields())
            f.setGeometry(geom_utm)
            f.setAttribute('id',            idx)
            f.setAttribute('dist_mestra_m', round(dist, 3))
            f.setAttribute('espacamento_m', spacing)
            f.setAttribute('datum',         f'{self._datum} EPSG:{self._epsg}')
            features.append(f)

        pr.addFeatures(features)
        vl.updateExtents()
        QgsProject.instance().addMapLayer(vl)
        collapse_layer(vl)

        self.iface.messageBar().pushMessage(
            'RTH Linhas de Plantio/Colheita / Planting/Harvest Lines',
            f'{len(result)} linhas geradas / {len(result)} lines generated  •  '
            f'{self._datum}  EPSG:{self._epsg}  •  {spacing} m',
            level=Qgis.MessageLevel.Info, duration=7,
        )

        # ── Curvas de retorno / Turn arcs ─────────────────────────────────
        # Arcos são gerados e recortados ao polígono original para ficar dentro do talhão
        # Arcs are generated and clipped to the original polygon to stay inside the field
        if gen_mode == 'with_turns' and len(result) >= 2:
            turn_geoms = self._generate_turn_arcs(result, poly_utm, turn_radius)
            if turn_geoms:
                arc_name = f'{base_name}_Curvas_Retorno_{spacing:.1f}m_r{turn_radius:.0f}m_EPSG_{self._epsg}'
                vl_arcs = QgsVectorLayer(f'LineString?crs=EPSG:{self._epsg}', arc_name, 'memory')
                pr_arcs = vl_arcs.dataProvider()
                pr_arcs.addAttributes([QgsField('id', QVariant.Int)])
                vl_arcs.updateFields()
                arc_feats = []
                for i, arc_geom in enumerate(turn_geoms, start=1):
                    f = QgsFeature(vl_arcs.fields())
                    f.setGeometry(arc_geom)
                    f.setAttribute('id', i)
                    arc_feats.append(f)
                pr_arcs.addFeatures(arc_feats)
                vl_arcs.updateExtents()
                QgsProject.instance().addMapLayer(vl_arcs)
                collapse_layer(vl_arcs)

        if self._dlg:
            self._dlg.close()

    def _on_dialog_finished(self, result):
        self._dlg = None

    # ── Ativa ferramenta de curva / Activate curve tool ───────────────────
    def _activate_curve_tool(self):
        """
        Tenta ativar 'Digitalizar com Curva'. Fallback para Adicionar Feição.
        Tries to activate 'Digitize with Curve'. Fallback to Add Feature.
        """
        from qgis.PyQt.QtWidgets import QAction

        curve_action = self.iface.mainWindow().findChild(QAction, 'mActionDigitizeWithCurve')
        if curve_action and curve_action.isEnabled():
            curve_action.trigger()
            return

        try:
            for action in self.iface.digitizeToolBar().actions():
                name = action.objectName()
                text = action.text()
                if 'Curve' in name or 'Curva' in text or 'Curve' in text:
                    if action.isEnabled():
                        action.trigger()
                        return
        except Exception:  # nosec B110
            pass

        self.iface.actionAddFeature().trigger()

    # ── Geração de linhas paralelas / Parallel line generation ──────────
    def _generate_parallel_lines(self, master_utm, poly_utm, spacing, smooth_iters=0, smooth_offset=0.0):
        """
        Gera linhas paralelas à linha mestra usando QgsGeometry.offsetCurve.
        Generates parallel lines to master line using QgsGeometry.offsetCurve.
        """
        extended = self._extend_line(master_utm, poly_utm)

        bbox = poly_utm.boundingBox()
        diag = math.sqrt(bbox.width() ** 2 + bbox.height() ** 2)
        n_max = int(diag / spacing) + 2

        if n_max * 2 > self.MAX_LINES:
            QMessageBox.warning(
                None, 'RTH',
                f'Muitas linhas estimadas ({n_max * 2}). Aumente o espaçamento ou reduza a área.\n'
                f'Too many estimated lines ({n_max * 2}). Increase spacing or reduce the area.'
            )
            return None

        results = []

        for n in range(0, n_max + 1):
            for sign in ([1] if n == 0 else [1, -1]):
                dist = sign * n * spacing

                if n == 0:
                    candidate = QgsGeometry(extended)
                else:
                    candidate = extended.offsetCurve(
                        dist, 8, Qgis.JoinStyle.Round, 5.0
                    )

                if not candidate or candidate.isEmpty():
                    continue

                clipped = candidate.intersection(poly_utm)
                if not clipped or clipped.isEmpty() or clipped.length() <= 0.001:
                    continue

                if smooth_iters > 0:
                    smoothed = clipped.smooth(smooth_iters, smooth_offset, -1.0, 180.0)
                    if smoothed and not smoothed.isEmpty():
                        clipped = smoothed

                results.append((clipped, dist))

        results.sort(key=lambda x: x[1])
        return results

    # ── Extensão da linha mestra / Master line extension ──────────────────
    def _extend_line(self, geom, poly_utm):
        """
        Estende a linha mestra nas extremidades para cobrir todo o polígono.
        Extends master line at endpoints to ensure full polygon coverage.
        """
        bbox = poly_utm.boundingBox()
        ext = math.sqrt(bbox.width() ** 2 + bbox.height() ** 2) * 1.2

        def _extend_pts(pts):
            if len(pts) < 2:
                return pts
            dx0 = pts[0].x() - pts[1].x(); dy0 = pts[0].y() - pts[1].y()
            d0  = math.sqrt(dx0 * dx0 + dy0 * dy0)
            new_start = QgsPointXY(pts[0].x() + dx0 / d0 * ext, pts[0].y() + dy0 / d0 * ext) if d0 > 0 else pts[0]
            dxn = pts[-1].x() - pts[-2].x(); dyn = pts[-1].y() - pts[-2].y()
            dn  = math.sqrt(dxn * dxn + dyn * dyn)
            new_end = QgsPointXY(pts[-1].x() + dxn / dn * ext, pts[-1].y() + dyn / dn * ext) if dn > 0 else pts[-1]
            return [new_start] + list(pts) + [new_end]

        if geom.isMultipart():
            parts = geom.asMultiPolyline()
            if not parts:
                return geom
            return QgsGeometry.fromMultiPolylineXY([_extend_pts(p) for p in parts])
        else:
            pts = geom.asPolyline()
            if len(pts) < 2:
                return geom
            return QgsGeometry.fromPolylineXY(_extend_pts(pts))

    # ── Curvas de retorno / Turn arcs ─────────────────────────────────────
    def _get_line_endpoints(self, geom):
        """Retorna (primeiro_ponto, último_ponto) da geometria. / Returns (first_point, last_point) of geometry."""
        if geom is None or geom.isEmpty():
            return None, None
        if geom.isMultipart():
            parts = geom.asMultiPolyline()
            if not parts or not parts[0] or not parts[-1]:
                return None, None
            return QgsPointXY(parts[0][0]), QgsPointXY(parts[-1][-1])
        pts = geom.asPolyline()
        if len(pts) < 2:
            return None, None
        return QgsPointXY(pts[0]), QgsPointXY(pts[-1])

    def _make_turn_arc(self, p1, p2, turn_radius, poly_centroid, n_pts=16):
        """
        Gera um arco circular conectando p1 a p2.
        O arco vai para o lado oposto ao centroide (em direção à bordadura/headland).
        Generates a circular arc connecting p1 to p2.
        Arc goes to the side away from centroid (toward headland strip).
        """
        dx = p2.x() - p1.x(); dy = p2.y() - p1.y()
        chord_len = math.sqrt(dx * dx + dy * dy)
        if chord_len < 0.001:
            return [p1, p2]
        half_chord = chord_len / 2.0
        r = max(turn_radius, half_chord * 1.0001)

        mx = (p1.x() + p2.x()) / 2.0
        my = (p1.y() + p2.y()) / 2.0
        px = -dy / chord_len
        py =  dx / chord_len
        d = math.sqrt(r * r - half_chord * half_chord)

        ctm_x = mx - poly_centroid.x()
        ctm_y = my - poly_centroid.y()
        outward_sign = 1 if (ctm_x * px + ctm_y * py) >= 0 else -1

        cx = mx + outward_sign * d * px
        cy = my + outward_sign * d * py

        a1 = math.atan2(p1.y() - cy, p1.x() - cx)
        a2 = math.atan2(p2.y() - cy, p2.x() - cx)

        da_m = a2 - a1
        while da_m >  math.pi: da_m -= 2 * math.pi
        while da_m < -math.pi: da_m += 2 * math.pi

        da_M = (da_m - 2 * math.pi) if da_m > 0 else (da_m + 2 * math.pi)

        def _mid_pt(da):
            a = a1 + da / 2
            return QgsPointXY(cx + r * math.cos(a), cy + r * math.sin(a))

        def _d2(p, q):
            return (p.x() - q.x()) ** 2 + (p.y() - q.y()) ** 2

        da = da_M if _d2(_mid_pt(da_M), poly_centroid) >= _d2(_mid_pt(da_m), poly_centroid) else da_m

        return [
            QgsPointXY(cx + r * math.cos(a1 + i / n_pts * da),
                       cy + r * math.sin(a1 + i / n_pts * da))
            for i in range(n_pts + 1)
        ]

    def _generate_turn_arcs(self, lines_with_dist, poly_utm, turn_radius, n_arc_pts=16):
        """
        Gera arcos de retorno entre linhas consecutivas (padrão serpentina).
        Cada arco é recortado ao polígono para garantir que fique dentro do talhão.
        Generates turn arcs between consecutive lines (snake pattern).
        Each arc is clipped to the polygon to ensure it stays inside the field.
        """
        centroid = poly_utm.centroid().asPoint()
        turn_geoms = []

        for i in range(len(lines_with_dist) - 1):
            geom_i, _ = lines_with_dist[i]
            geom_j, _ = lines_with_dist[i + 1]
            start_i, end_i = self._get_line_endpoints(geom_i)
            start_j, end_j = self._get_line_endpoints(geom_j)
            if None in (start_i, end_i, start_j, end_j):
                continue

            p1, p2 = (end_i, end_j) if i % 2 == 0 else (start_i, start_j)

            arc_pts = self._make_turn_arc(p1, p2, turn_radius, centroid, n_arc_pts)
            if len(arc_pts) < 2:
                continue

            arc_geom = QgsGeometry.fromPolylineXY(arc_pts)
            if not arc_geom or arc_geom.isEmpty():
                continue

            # Recorta ao polígono para garantir que o arco fique dentro do talhão
            # Clip to polygon to ensure arc stays inside the field
            clipped = arc_geom.intersection(poly_utm)
            if clipped and not clipped.isEmpty() and clipped.length() > 0.001:
                turn_geoms.append(clipped)

        return turn_geoms
