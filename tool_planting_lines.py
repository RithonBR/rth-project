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
    Qgis,                          # Enumerações e constantes QGIS / QGIS enums and constants
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
)

# Utilitário de detecção de UTM regional / Regional UTM detection utility
from rth_utm_utils import detect_regional_utm


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
        self.setMinimumWidth(390)
        # Mantém janela acima do QGIS sem bloquear o canvas / Keep window above QGIS without blocking canvas
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)

        root = QVBoxLayout()
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
        # Cor clara para funcionar em temas escuros / Light color to work with dark themes
        self.lbl_datum = QLabel(
            f'{datum_name}  •  EPSG:{epsg}  •  Zona / Zone {zone}{hemi}'
        )
        self.lbl_datum.setStyleSheet('font-size:11px; font-weight:bold;')
        lay_datum.addWidget(self.lbl_datum)
        grp_datum.setLayout(lay_datum)
        root.addWidget(grp_datum)

        # ── Espaçamento / Spacing ──────────────────────────────────────────
        grp_spacing = QGroupBox('Implemento Agrícola / Agricultural Implement')
        lay_spacing = QVBoxLayout()
        lay_spacing.setContentsMargins(8, 4, 8, 8)
        lbl_sp = QLabel('Espaçamento entre linhas (m) / Row spacing (m):')
        lbl_sp.setStyleSheet('font-size:11px;')
        lay_spacing.addWidget(lbl_sp)

        self.spin_spacing = QDoubleSpinBox()
        self.spin_spacing.setRange(0.1, 5000.0)
        self.spin_spacing.setValue(15.0)        # Padrão 15 m / Default 15 m
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
        self.radio_lines_only.setChecked(True)   # Padrão / Default
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

        # Opção 2: offset interno + linhas (headland) / Option 2: inward offset + lines (headland)
        self.radio_curved = QRadioButton('Linhas com Bordas Curvas / Lines with Curved Borders')
        self.radio_curved.setStyleSheet('font-size:11px; font-weight:bold;')
        lbl_curved = QLabel(
            '  Recua o polígono 1× o espaçamento (headland) antes de gerar\n'
            '  as linhas, respeitando o contorno do campo.\n'
            '  Shrinks polygon 1× spacing inward (headland) before generating\n'
            '  lines, respecting the field boundary.'
        )
        lbl_curved.setStyleSheet('font-size:9px; color:#aaa;')
        self._btn_group_mode.addButton(self.radio_curved, 1)
        lay_mode.addWidget(self.radio_curved)
        lay_mode.addWidget(lbl_curved)

        grp_mode.setLayout(lay_mode)
        root.addWidget(grp_mode)

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

        # Status / Status
        self.lbl_line_status = QLabel('— Nenhuma linha desenhada / No line drawn —')
        self.lbl_line_status.setAlignment(Qt.AlignCenter)
        self.lbl_line_status.setStyleSheet(
            'font-style:italic; font-size:10px; '
            'padding:5px; border:1px dashed #888; border-radius:3px;'
        )
        lay_line.addWidget(self.lbl_line_status)

        # Botão desenhar / Draw button
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
        # (label, iterações, offset) / (label, iterations, offset)
        self._smooth_opts = [
            ('Sem Suavização / No Smoothing',   0, 0.00),
            ('Suave / Gentle',                  1, 0.15),
            ('Médio / Medium',                  3, 0.25),
            ('Forte / Strong',                  5, 0.35),
            ('Muito Forte / Very Strong',        8, 0.45),
        ]
        for label, _, _ in self._smooth_opts:
            self.combo_smooth.addItem(label)
        self.combo_smooth.setCurrentIndex(0)  # Padrão: sem suavização / Default: no smoothing
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
        self.btn_generate.setEnabled(False)  # Só habilita após criar a camada / Enabled only after layer is created

        self.btn_cancel = QPushButton('Cancelar / Cancel')
        self.btn_cancel.setStyleSheet(self._STYLE_CANCEL)
        self.btn_cancel.setMinimumHeight(36)

        row_btns.addWidget(self.btn_generate)
        row_btns.addWidget(self.btn_cancel)
        root.addLayout(row_btns)

        self.setLayout(root)
        self.btn_cancel.clicked.connect(self.reject)

    # ── API pública / Public API ───────────────────────────────────────────
    @property
    def spacing(self):
        """Retorna o espaçamento configurado / Returns configured spacing."""
        return self.spin_spacing.value()

    @property
    def mode(self):
        """
        Retorna o modo de geração selecionado.
        Returns the selected generation mode.
        'lines_only' | 'curved_borders'
        """
        return 'curved_borders' if self.radio_curved.isChecked() else 'lines_only'

    @property
    def smoothing_params(self):
        """Retorna (iterações, offset) da opção de suavização selecionada. / Returns (iterations, offset) for selected smoothing option."""
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

    MAX_LINES = 20000   # Limite de segurança / Safety limit
    TEMP_LAYER_NAME = 'Linha_Mestre'   # Nome da camada temporária / Temp layer name

    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        # Estado interno / Internal state
        self._polygon_geom = None
        self._layer_crs = None
        self._epsg = self._datum = self._zone = self._hemi = None
        self._temp_layer_id = None   # ID da camada Linha_Mestre / Linha_Mestre layer ID
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

        # Mescla múltiplas seleções / Merge multiple selections
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

        # ── Abre diálogo não bloqueante / Open non-blocking dialog ──────
        self._dlg = PlantingLinesDialog(self._epsg, self._datum, self._zone, self._hemi)
        self._dlg.btn_draw.clicked.connect(self._start_drawing)
        self._dlg.btn_generate.clicked.connect(self._do_generate)
        self._dlg.finished.connect(self._on_dialog_finished)
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()

    # ── Cria camada Linha_Mestre e ativa digitação / Create Linha_Mestre layer and activate digitizing ──
    def _start_drawing(self):
        """
        Cria (ou recria) a camada vetorial 'Linha_Mestre' e ativa a ferramenta de adição de feição.
        Creates (or recreates) the 'Linha_Mestre' vector layer and activates the add feature tool.
        """
        # Remove camada anterior se existir / Remove previous layer if exists
        if self._temp_layer_id:
            old = QgsProject.instance().mapLayer(self._temp_layer_id)
            if old:
                QgsProject.instance().removeMapLayer(self._temp_layer_id)
            self._temp_layer_id = None

        # Cria nova camada de linha no mesmo CRS da camada de polígonos / Create new line layer in same CRS as polygon layer
        crs_str = self._layer_crs.authid()
        temp = QgsVectorLayer(
            f'LineString?crs={crs_str}',
            self.TEMP_LAYER_NAME,
            'memory'
        )

        if not temp.isValid():
            QMessageBox.critical(
                None, 'RTH',
                'Não foi possível criar a camada Linha_Mestre.\n'
                'Could not create Linha_Mestre layer.'
            )
            return

        # Adiciona ao projeto / Add to project
        QgsProject.instance().addMapLayer(temp)
        self._temp_layer_id = temp.id()

        # Define como camada ativa e inicia edição / Set as active layer and start editing
        self.iface.setActiveLayer(temp)
        temp.startEditing()

        # Ativa "Digitalizar com Curva" com fallback para Adicionar Feição
        # Activates "Digitize with Curve" tool with fallback to Add Feature
        self._activate_curve_tool()

        # Instrução na barra de mensagens / Instruction in message bar
        self.iface.messageBar().pushMessage(
            'RTH Linhas de Plantio/Colheita / Planting/Harvest Lines',
            'Digitize a linha mestra na camada "Linha_Mestre". '
            'Clique para adicionar vértices — clique direito para finalizar. '
            '/ Digitize master line in "Linha_Mestre" layer. '
            'Click to add vertices — right-click to finish.',
            level=0, duration=30,
        )

        # Atualiza o diálogo / Update dialog
        if self._dlg:
            self._dlg.set_layer_created()
            self._dlg.raise_()
            self._dlg.activateWindow()

    # ── Gera as linhas paralelas / Generate parallel lines ────────────────
    def _do_generate(self):
        """Lê a linha mestra da camada e gera as linhas paralelas. / Reads master line from layer and generates parallel lines."""
        spacing = self._dlg.spacing if self._dlg else 15.0

        # Verifica se a camada existe / Check if layer exists
        if not self._temp_layer_id:
            QMessageBox.warning(
                None, 'RTH',
                'Primeiro crie e desenhe a linha mestra.\n'
                'First create and draw the master line.'
            )
            return

        temp = QgsProject.instance().mapLayer(self._temp_layer_id)
        if not temp:
            QMessageBox.warning(
                None, 'RTH',
                'Camada "Linha_Mestre" não encontrada no projeto.\n'
                '"Linha_Mestre" layer not found in project.'
            )
            return

        # Salva edições pendentes / Commit pending edits
        if temp.isEditable():
            temp.commitChanges()

        # Lê feições da camada / Read features from layer
        feats = list(temp.getFeatures())
        if not feats:
            QMessageBox.warning(
                None, 'RTH',
                'Nenhuma feição encontrada na camada "Linha_Mestre". Desenhe a linha primeiro.\n'
                'No features found in "Linha_Mestre" layer. Draw the line first.'
            )
            return

        # Une todas as feições em uma geometria / Merge all features into one geometry
        if len(feats) == 1:
            master_geom = feats[0].geometry()
        else:
            # Coleta múltiplas linhas em uma multiline / Collect multiple lines into a multiline
            geom_list = [f.geometry() for f in feats]
            master_geom = QgsGeometry.collectGeometry(geom_list)

        if master_geom.isEmpty():
            QMessageBox.warning(None, 'RTH', 'Geometria da linha mestra está vazia.\nMaster line geometry is empty.')
            return

        # ── Transformações de CRS / CRS transformations ──────────────────
        utm_crs = QgsCoordinateReferenceSystem(f'EPSG:{self._epsg}')

        # Transforma linha mestra: layer CRS → UTM / Transform master line: layer CRS → UTM
        xform_layer_utm = QgsCoordinateTransform(self._layer_crs, utm_crs, QgsProject.instance())
        master_utm = QgsGeometry(master_geom)
        try:
            master_utm.transform(xform_layer_utm)
        except QgsCsException as e:
            QMessageBox.critical(None, 'RTH', f'Erro ao transformar linha mestra.\nError transforming master line.\n{e}')
            return

        # Transforma polígono: layer CRS → UTM / Transform polygon: layer CRS → UTM
        poly_utm = QgsGeometry(self._polygon_geom)
        try:
            poly_utm.transform(xform_layer_utm)
        except QgsCsException as e:
            QMessageBox.critical(None, 'RTH', f'Erro ao reprojetar polígono.\nError reprojecting polygon.\n{e}')
            return

        # ── Modo de geração / Generation mode ────────────────────────────
        gen_mode = self._dlg.mode if self._dlg else 'lines_only'

        if gen_mode == 'curved_borders':
            # Recua o polígono 1× o espaçamento (headland) com joinStyle Miter (pontudo, sem arredondar)
            # Shrinks polygon 1× spacing inward (headland) with Miter join (sharp, no rounding)
            poly_inner = poly_utm.buffer(
                -spacing,                  # offset negativo = interno / negative = inward
                5,                         # segmentos (irrelevante com Miter) / segments (irrelevant with Miter)
                Qgis.EndCapStyle.Flat,     # extremidade plana / flat end cap
                Qgis.JoinStyle.Miter,      # cantos pontiagudos / sharp corners
                10.0                       # miter limit — permite cantos bem agudos / allows very sharp corners
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
            # Usa o polígono interno como área de trabalho / Use inner polygon as working area
            work_poly = poly_inner
            mode_label = f'CurvedBorders_offset{spacing:.0f}m'
        else:
            # Usa o polígono original / Use original polygon
            work_poly = poly_utm
            mode_label = 'LinesOnly'

        # ── Lê parâmetros de suavização / Read smoothing parameters ─────────
        smooth_iters, smooth_offset = self._dlg.smoothing_params if self._dlg else (0, 0.0)

        # ── Gera linhas / Generate lines ──────────────────────────────────
        result = self._generate_parallel_lines(master_utm, work_poly, spacing, smooth_iters, smooth_offset)

        if result is None:
            return  # Aviso já exibido / Warning already shown
        if not result:
            QMessageBox.warning(
                None, 'RTH',
                'Nenhuma linha gerada dentro do polígono. '
                'Verifique a posição e direção da linha mestra.\n'
                'No lines generated inside the polygon. '
                'Check the master line position and direction.'
            )
            return

        # ── Cria camada de resultado / Create result layer ────────────────
        layer_name = f'Linhas_Plantio_{spacing:.1f}m_{mode_label}_EPSG_{self._epsg}'
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

        self.iface.messageBar().pushMessage(
            'RTH Linhas de Plantio/Colheita / Planting/Harvest Lines',
            f'{len(result)} linhas geradas / {len(result)} lines generated  •  '
            f'{self._datum}  EPSG:{self._epsg}  •  {spacing} m',
            level=0, duration=7,
        )

        if self._dlg:
            self._dlg.close()

    def _on_dialog_finished(self, result):
        """Limpa referências ao fechar o diálogo. / Cleans up when dialog closes."""
        self._dlg = None

    # ── Ativa ferramenta de curva / Activate curve tool ───────────────────
    def _activate_curve_tool(self):
        """
        Tenta ativar a ferramenta 'Digitalizar com Curva' (mActionDigitizeWithCurve).
        Falls back para Adicionar Feição se não encontrar.
        Tries to activate 'Digitize with Curve' tool. Falls back to Add Feature if not found.
        """
        from qgis.PyQt.QtWidgets import QAction

        # Tentativa 1: busca pelo nome do objeto Qt / Attempt 1: search by Qt object name
        curve_action = self.iface.mainWindow().findChild(QAction, 'mActionDigitizeWithCurve')
        if curve_action and curve_action.isEnabled():
            curve_action.trigger()
            return

        # Tentativa 2: varre a barra de digitação procurando "Curve" / Attempt 2: scan digitize toolbar for "Curve"
        try:
            for action in self.iface.digitizeToolBar().actions():
                name = action.objectName()
                text = action.text()
                if 'Curve' in name or 'Curva' in text or 'Curve' in text:
                    if action.isEnabled():
                        action.trigger()
                        return
        except Exception:
            pass

        # Fallback: ferramenta padrão de adicionar feição / Fallback: standard add feature tool
        self.iface.actionAddFeature().trigger()

    # ── Geração de linhas paralelas por offsetCurve / Parallel line generation by offsetCurve ──
    def _generate_parallel_lines(self, master_utm, poly_utm, spacing, smooth_iters=0, smooth_offset=0.0):
        """
        Gera linhas paralelas à linha mestra usando QgsGeometry.offsetCurve.
        Generates parallel lines to master line using QgsGeometry.offsetCurve.
        Respeita curvas e geometrias multipart / Respects curves and multipart geometries.
        smooth_iters: número de iterações de suavização / number of smoothing iterations
        smooth_offset: intensidade do deslocamento de suavização (0.0–0.5) / smoothing offset intensity (0.0–0.5)
        """
        # Estende a linha mestra para cobrir todo o polígono / Extend master line to cover entire polygon
        extended = self._extend_line(master_utm, poly_utm)

        # Número máximo de offsets (diagonal do bbox / espaçamento) / Max offsets (bbox diagonal / spacing)
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

        # Gera offsets em ambos os lados / Generate offsets on both sides
        for n in range(0, n_max + 1):
            for sign in ([1] if n == 0 else [1, -1]):
                dist = sign * n * spacing

                if n == 0:
                    # Linha mestra estendida / Extended master line
                    candidate = QgsGeometry(extended)
                else:
                    # offsetCurve com junção arredondada (Round) para preservar curvas
                    # offsetCurve with Round join style to preserve curves
                    candidate = extended.offsetCurve(
                        dist,
                        8,                         # segmentos por quarto de círculo / segments per quarter-circle
                        Qgis.JoinStyle.Round,      # estilo de junção arredondado / rounded join style
                        5.0                        # limite de miter / miter limit
                    )

                if not candidate or candidate.isEmpty():
                    continue

                # Recorta ao polígono / Clip to polygon
                clipped = candidate.intersection(poly_utm)
                if not clipped or clipped.isEmpty() or clipped.length() <= 0.001:
                    continue

                # Aplica suavização se configurada / Apply smoothing if configured
                if smooth_iters > 0:
                    smoothed = clipped.smooth(
                        smooth_iters,   # iterações / iterations
                        smooth_offset,  # deslocamento (0.0–0.5) / offset intensity (0.0–0.5)
                        -1.0,           # distância mínima entre vértices (auto) / min vertex distance (auto)
                        180.0           # suaviza todos os ângulos / smooth all angles
                    )
                    # Usa suavizado se válido, senão mantém o original / Use smoothed if valid, else keep original
                    if smoothed and not smoothed.isEmpty():
                        clipped = smoothed

                results.append((clipped, dist))

        results.sort(key=lambda x: x[1])
        return results

    # ── Extensão da linha mestra / Master line extension ──────────────────
    def _extend_line(self, geom, poly_utm):
        """
        Estende a linha mestra nas extremidades para garantir que cubra todo o polígono.
        Extends master line at endpoints to ensure full polygon coverage.
        Funciona com LineString e MultiLineString / Works with LineString and MultiLineString.
        """
        bbox = poly_utm.boundingBox()
        ext = math.sqrt(bbox.width() ** 2 + bbox.height() ** 2) * 1.2  # Margem / Margin

        def _extend_pts(pts):
            """Estende uma lista de pontos nas duas extremidades. / Extends a point list at both ends."""
            if len(pts) < 2:
                return pts
            # Primeiro ponto: estende na direção inversa do primeiro segmento / First point: extends in reverse of first segment
            dx0 = pts[0].x() - pts[1].x()
            dy0 = pts[0].y() - pts[1].y()
            d0  = math.sqrt(dx0 * dx0 + dy0 * dy0)
            new_start = QgsPointXY(pts[0].x() + dx0 / d0 * ext, pts[0].y() + dy0 / d0 * ext) if d0 > 0 else pts[0]
            # Último ponto: estende na direção do último segmento / Last point: extends in direction of last segment
            dxn = pts[-1].x() - pts[-2].x()
            dyn = pts[-1].y() - pts[-2].y()
            dn  = math.sqrt(dxn * dxn + dyn * dyn)
            new_end = QgsPointXY(pts[-1].x() + dxn / dn * ext, pts[-1].y() + dyn / dn * ext) if dn > 0 else pts[-1]
            return [new_start] + list(pts) + [new_end]

        if geom.isMultipart():
            # Processa cada parte / Process each part
            parts = geom.asMultiPolyline()
            if not parts:
                return geom
            new_parts = [_extend_pts(part) for part in parts]
            return QgsGeometry.fromMultiPolylineXY(new_parts)
        else:
            pts = geom.asPolyline()
            if len(pts) < 2:
                return geom
            return QgsGeometry.fromPolylineXY(_extend_pts(pts))
