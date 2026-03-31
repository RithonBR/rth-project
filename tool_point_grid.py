# -*- coding: utf-8 -*-
"""
Ferramenta Grid de Pontos - Gera uma grade regular de pontos dentro de um polígono selecionado
Point Grid Tool - Generates a regular grid of points inside a selected polygon

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Importações Qt para construção do diálogo / Qt imports for dialog construction
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QDoubleSpinBox, QDialogButtonBox, QFrame, QGroupBox
)
# Cálculo da raiz quadrada para a fórmula de hectares / Square root for hectare formula
import math
# Utilitário de detecção de datum regional / Regional datum detection utility
from rth_utm_utils import detect_regional_utm

# Importações QGIS para geometria, CRS e camadas / QGIS imports for geometry, CRS and layers
from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes,
    QgsField,
)
# Tipo de dado para campo inteiro / Integer field data type
from qgis.PyQt.QtCore import QVariant



class PointGridDialog(QDialog):
    """Diálogo para configurar o espaçamento do grid de pontos / Dialog to configure point grid spacing."""

    def __init__(self, epsg, datum_name, zone, hemi, parent=None):
        """Construtor do diálogo / Dialog constructor."""
        super().__init__(parent)
        # Título da janela / Window title
        self.setWindowTitle('Grid de Pontos / Point Grid')
        # Modal: bloqueia interação com a janela principal / Modal: blocks interaction with main window
        self.setModal(True)
        # Largura mínima do diálogo / Minimum dialog width
        self.setMinimumWidth(380)

        # Layout principal vertical / Main vertical layout
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # ── Datum detectado / Detected datum ──
        lbl_datum = QLabel('Datum detectado / Detected datum: <b>{}</b>'.format(datum_name))
        # Permite HTML no label / Allow HTML in label
        lbl_datum.setTextFormat(1)
        layout.addWidget(lbl_datum)

        # ── EPSG e zona UTM detectados / Detected EPSG and UTM zone ──
        lbl_epsg = QLabel(
            'CRS / CRS: <b>EPSG:{}</b>  —  Zona / Zone: <b>{}{}</b>'.format(epsg, zone, hemi)
        )
        lbl_epsg.setTextFormat(1)
        layout.addWidget(lbl_epsg)

        # Separador visual / Visual separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # ── Linha de espaçamento / Spacing row ──
        h_layout = QHBoxLayout()
        # Label do espaçamento / Spacing label
        lbl = QLabel('Espaçamento / Spacing:')
        h_layout.addWidget(lbl)

        # SpinBox para o valor do espaçamento / SpinBox for spacing value
        self.spin = QDoubleSpinBox()
        # Valor mínimo: 1 metro / Minimum value: 1 metre
        self.spin.setMinimum(1.0)
        # Valor máximo: 100 km / Maximum value: 100 km
        self.spin.setMaximum(100000.0)
        # Valor padrão: 100 metros / Default value: 100 metres
        self.spin.setValue(100.0)
        # Sufixo da unidade / Unit suffix
        self.spin.setSuffix(' m')
        # Uma casa decimal / One decimal place
        self.spin.setDecimals(1)
        # Incremento no scroll / Scroll step
        self.spin.setSingleStep(10.0)
        h_layout.addWidget(self.spin)
        layout.addLayout(h_layout)

        # ── Equivalência em hectares (atualiza dinamicamente) / Hectare equivalence (updates dynamically) ──
        self.lbl_ha = QLabel()
        self.lbl_ha.setStyleSheet('font-size:11px; font-weight:bold; padding:3px 0;')
        self._update_ha_label(self.spin.value())
        layout.addWidget(self.lbl_ha)

        # ── Dica: como calcular o espaçamento / Tip: how to calculate spacing ──
        grp_tip = QGroupBox('Como calcular o espaçamento? / How to calculate spacing?')
        lay_tip = QVBoxLayout()
        lay_tip.setContentsMargins(8, 4, 8, 8)
        lbl_tip = QLabel(
            'Para determinar o espaçamento correto, defina de quantos em quantos\n'
            'hectares você quer amostrar e calcule a raiz quadrada da área em m².\n\n'
            'To determine the correct spacing, define how many hectares per sample\n'
            'and calculate the square root of the area in m².\n\n'
            '<b>Fórmula / Formula:</b>\n'
            '  Espaçamento (m) = √(ha × 10.000)\n'
            '  Spacing (m) = √(ha × 10,000)\n\n'
            '<b>Exemplos / Examples:</b>\n'
            '  1 ha  →  √10.000  =  100 m\n'
            '  2 ha  →  √20.000  ≈  141 m\n'
            '  3 ha  →  √30.000  ≈  173 m\n'
            '  5 ha  →  √50.000  ≈  224 m\n'
            ' 10 ha  →  √100.000 ≈  316 m'
        )
        lbl_tip.setTextFormat(1)   # Permite HTML / Allow HTML
        lbl_tip.setStyleSheet('font-size:10px;')
        lbl_tip.setWordWrap(True)
        lay_tip.addWidget(lbl_tip)
        grp_tip.setLayout(lay_tip)
        layout.addWidget(grp_tip)

        # Conecta o spinbox para atualizar o label de hectares em tempo real / Connect spinbox to update hectare label in real time
        self.spin.valueChanged.connect(self._update_ha_label)

        # ── Botões OK e Cancelar / OK and Cancel buttons ──
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        # Conecta aceitar / Connect accept
        btn_box.accepted.connect(self.accept)
        # Conecta rejeitar / Connect reject
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self.setLayout(layout)

    def _update_ha_label(self, spacing_m):
        """Atualiza o label mostrando a qual amostragem em hectares o espaçamento equivale.
        Updates label showing the hectare sampling equivalent of the current spacing."""
        if spacing_m > 0:
            # Área da célula do grid em m² / Grid cell area in m²
            area_m2 = spacing_m * spacing_m
            # Converte para hectares / Convert to hectares
            area_ha = area_m2 / 10000.0
            self.lbl_ha.setText(
                f'≈ 1 ponto a cada  <b>{area_ha:.2f} ha</b>  '
                f'({spacing_m:.1f} m × {spacing_m:.1f} m = {area_m2:,.0f} m²)'
                f'  /  ≈ 1 point every <b>{area_ha:.2f} ha</b>'
            )

    def spacing(self):
        """Retorna o espaçamento configurado em metros / Returns the configured spacing in metres."""
        return self.spin.value()


class PointGridTool:
    """Gera uma grade regular de pontos dentro de um polígono selecionado / Generates a regular point grid inside a selected polygon."""

    def __init__(self, iface):
        """Construtor da ferramenta / Tool constructor."""
        # Armazena a interface QGIS / Store QGIS interface
        self.iface = iface

    def run(self):
        """Executa a geração do grid de pontos / Executes point grid generation."""

        # ── 1. Obtém a camada ativa / Get active layer ──
        layer = self.iface.activeLayer()
        if layer is None:
            self.iface.messageBar().pushMessage(
                'Point Grid',
                'Nenhuma camada ativa / No active layer',
                level=1)
            return

        # ── 2. Valida feições selecionadas / Validate selected features ──
        selected = layer.selectedFeatures()
        if not selected:
            self.iface.messageBar().pushMessage(
                'Point Grid',
                'Selecione um polígono primeiro / Select a polygon first',
                level=1)
            return

        # Coleta as geometrias válidas de todas as feições selecionadas / Collect valid geometries from all selected features
        geom_list = []
        for feat in selected:
            g = feat.geometry()
            # Ignora feições sem geometria ou que não sejam polígonos / Skip features without geometry or non-polygons
            if g is None or QgsWkbTypes.geometryType(g.wkbType()) != QgsWkbTypes.PolygonGeometry:
                continue
            geom_list.append(g)

        # Verifica se há ao menos um polígono válido / Check if there is at least one valid polygon
        if not geom_list:
            self.iface.messageBar().pushMessage(
                'Point Grid',
                'Nenhum polígono válido selecionado / No valid polygon selected',
                level=1)
            return

        # Une todas as geometrias em uma só para gerar o grid / Merge all geometries into one to generate the grid
        # Pontos serão gerados dentro de qualquer um dos polígonos selecionados / Points will be generated inside any of the selected polygons
        geom = QgsGeometry.unaryUnion(geom_list)

        # ── 3. Calcula o centroide em WGS84 para detectar a região / Calculate centroid in WGS84 to detect region ──
        source_crs = layer.crs()
        # CRS de referência WGS84 / WGS84 reference CRS
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        # Transformação para WGS84 / Transform to WGS84
        transform_to_wgs = QgsCoordinateTransform(source_crs, wgs84, QgsProject.instance())

        # Centroide da geometria no CRS original / Centroid in original CRS
        centroid_pt = geom.centroid().asPoint()
        # Reprojecta o centroide para WGS84 / Reproject centroid to WGS84
        centroid_wgs = transform_to_wgs.transform(centroid_pt)

        # Longitude e latitude do centroide / Centroid longitude and latitude
        lon = centroid_wgs.x()
        lat = centroid_wgs.y()

        # ── 4. Detecta o datum regional e o EPSG UTM / Detect regional datum and UTM EPSG ──
        utm_epsg, datum_name, zone, hemi = detect_regional_utm(lon, lat)

        # ── 5. Abre o diálogo para o usuário informar o espaçamento / Open dialog for user to input spacing ──
        dlg = PointGridDialog(utm_epsg, datum_name, zone, hemi, parent=self.iface.mainWindow())
        if dlg.exec_() != QDialog.Accepted:
            # Usuário cancelou / User cancelled
            return

        # Espaçamento em metros definido pelo usuário / User-defined spacing in metres
        spacing = dlg.spacing()

        # ── 6. Reprojecta o polígono para o CRS UTM regional / Reproject polygon to regional UTM CRS ──
        utm_crs = QgsCoordinateReferenceSystem('EPSG:{}'.format(utm_epsg))
        # Transformação do CRS original para UTM / Transform from original CRS to UTM
        transform_to_utm = QgsCoordinateTransform(source_crs, utm_crs, QgsProject.instance())

        # Copia a geometria e reprojecta / Copy geometry and reproject
        geom_utm = QgsGeometry(geom)
        geom_utm.transform(transform_to_utm)

        # ── 7. Gera a grade de pontos dentro do polígono / Generate point grid inside polygon ──
        # Bounding box do polígono em UTM / Polygon bounding box in UTM
        bbox = geom_utm.boundingBox()

        # Limites da grade / Grid limits
        x_min = bbox.xMinimum()
        x_max = bbox.xMaximum()
        y_min = bbox.yMinimum()
        y_max = bbox.yMaximum()

        # Estimativa do número máximo de pontos para segurança / Max point estimate for safety check
        cols = int((x_max - x_min) / spacing) + 1
        rows = int((y_max - y_min) / spacing) + 1
        if cols * rows > 500000:
            self.iface.messageBar().pushMessage(
                'Point Grid',
                'Espaçamento muito pequeno: geraria mais de 500.000 pontos / Spacing too small: would generate over 500,000 points',
                level=1)
            return

        # Lista de pontos dentro do polígono / List of points inside the polygon
        points = []
        x = x_min
        while x <= x_max:
            y = y_min
            while y <= y_max:
                # Cria ponto e verifica se está dentro do polígono / Create point and check if inside polygon
                pt = QgsPointXY(x, y)
                pt_geom = QgsGeometry.fromPointXY(pt)
                if geom_utm.contains(pt_geom):
                    points.append(pt)
                # Avança no eixo Y / Advance on Y axis
                y += spacing
            # Avança no eixo X / Advance on X axis
            x += spacing

        # Verifica se algum ponto foi gerado / Check if any point was generated
        if not points:
            self.iface.messageBar().pushMessage(
                'Point Grid',
                'Nenhum ponto gerado. Reduza o espaçamento / No points generated. Reduce the spacing.',
                level=1)
            return

        # ── 8. Cria a camada de memória com os pontos / Create memory layer with points ──
        layer_name = 'Grid {}m - {}'.format(int(spacing), layer.name())
        # Cria camada de pontos no CRS UTM regional / Create point layer in regional UTM CRS
        vl = QgsVectorLayer('Point?crs=EPSG:{}'.format(utm_epsg), layer_name, 'memory')
        pr = vl.dataProvider()

        # Adiciona campo de identificador único sequencial / Add sequential unique identifier field
        pr.addAttributes([QgsField('id', QVariant.Int)])
        # Atualiza o esquema de campos da camada / Update layer field schema
        vl.updateFields()

        # Monta as feições de ponto com ID sequencial / Build point features with sequential ID
        features = []
        for idx, pt in enumerate(points, start=1):
            f = QgsFeature(vl.fields())
            # Define a geometria do ponto / Set point geometry
            f.setGeometry(QgsGeometry.fromPointXY(pt))
            # Define o identificador único sequencial (inicia em 1) / Set sequential unique identifier (starts at 1)
            f.setAttribute('id', idx)
            features.append(f)

        # Adiciona todas as feições ao provider / Add all features to provider
        pr.addFeatures(features)
        # Atualiza a extensão da camada / Update layer extent
        vl.updateExtents()

        # Adiciona a camada ao projeto QGIS / Add layer to QGIS project
        QgsProject.instance().addMapLayer(vl)

        # ── 9. Exibe mensagem de sucesso / Show success message ──
        self.iface.messageBar().pushMessage(
            'Point Grid',
            '{} pontos | {} polígono(s) | {} EPSG:{} | {}m'.format(
                len(points), len(geom_list), datum_name, utm_epsg, spacing),
            level=0,
            duration=8)
