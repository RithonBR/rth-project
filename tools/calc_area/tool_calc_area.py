# -*- coding: utf-8 -*-
"""
Ferramenta Calc Area - Calcula a área das feições selecionadas em hectares
Calc Area Tool - Calculates the area of selected features in hectares

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Importa a área de transferência do Qt / Import Qt clipboard
from qgis.PyQt.QtGui import QGuiApplication
# Importa os módulos QGIS para projeto, CRS e transformação / Import QGIS modules for project, CRS and transform
from qgis.core import (
    Qgis,
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
)
# Utilitário de detecção de datum regional / Regional datum detection utility
from core.rth_utm_utils import detect_regional_utm


class CalcAreaTool:
    """Calcula a área total das feições selecionadas em hectares usando projeção UTM regional / Calculates total area of selected features in hectares using regional UTM projection."""

    def __init__(self, iface):
        # Armazena a interface QGIS / Store QGIS interface
        self.iface = iface

    def calculate(self):
        """Calcula a área das feições selecionadas e copia o resultado para o clipboard / Calculate area of selected features and copy result to clipboard."""
        # Obtém a camada ativa / Get the active layer
        layer = self.iface.activeLayer()
        # Verifica se há uma camada ativa / Check if there is an active layer
        if layer is None:
            self.iface.messageBar().pushMessage(
                'Calc Area', 'Nenhuma camada ativa / No active layer', level=Qgis.MessageLevel.Warning)
            return
        try:
            # Obtém as feições selecionadas / Get the selected features
            feats = layer.selectedFeatures()
            # Verifica se há feições selecionadas / Check if there are selected features
            if not feats:
                self.iface.messageBar().pushMessage(
                    'Calc Area', 'Nenhuma feição selecionada / No feature selected', level=Qgis.MessageLevel.Warning)
                return

            # ── Detecta datum regional usando o centroide da primeira feição ──
            # ── Detect regional datum using centroid of first feature ──
            source_crs = layer.crs()
            # CRS WGS84 para cálculo da zona UTM / WGS84 CRS to calculate UTM zone
            wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
            # Transformação para WGS84 / Transform to WGS84
            to_wgs = QgsCoordinateTransform(source_crs, wgs84, QgsProject.instance())
            # Usa o centroide da primeira feição para detectar a região / Use first feature centroid to detect region
            first_geom = feats[0].geometry()
            centroid_pt = first_geom.centroid().asPoint()
            # Reprojecta o centroide para WGS84 / Reproject centroid to WGS84
            centroid_wgs = to_wgs.transform(centroid_pt)
            lon = centroid_wgs.x()
            lat = centroid_wgs.y()

            # Detecta o datum e EPSG UTM regional / Detect regional datum and UTM EPSG
            utm_epsg, datum_name, zone, hemi = detect_regional_utm(lon, lat)
            # CRS UTM regional / Regional UTM CRS
            utm_crs = QgsCoordinateReferenceSystem('EPSG:{}'.format(utm_epsg))
            # Transformação do CRS da camada para UTM / Transform from layer CRS to UTM
            to_utm = QgsCoordinateTransform(source_crs, utm_crs, QgsProject.instance())

            # ── Calcula a área reprojectando cada feição para UTM ──
            # ── Calculate area by reprojecting each feature to UTM ──
            total_m2 = 0.0
            for feat in feats:
                # Obtém a geometria da feição / Get feature geometry
                geom = feat.geometry()
                # Pula feições sem geometria / Skip features without geometry
                if geom is None:
                    continue
                # Copia e reprojecta a geometria para UTM / Copy and reproject geometry to UTM
                geom_utm = QgsGeometry(geom)
                geom_utm.transform(to_utm)
                # Área planar em metros quadrados no CRS UTM / Planar area in square metres in UTM CRS
                total_m2 += geom_utm.area()

            # Converte metros quadrados para hectares (1 ha = 10.000 m²) / Convert sq metres to hectares (1 ha = 10,000 m²)
            total_ha = total_m2 / 10000.0
            # Formata o resultado com 4 casas decimais / Format result with 4 decimal places
            formatted = '{:.4f} ha'.format(total_ha)

            # Copia o valor numérico para o clipboard / Copy numeric value to clipboard
            try:
                QGuiApplication.clipboard().setText('{:.6f}'.format(total_ha))
            except Exception:
                pass  # Ignora se o clipboard não estiver disponível / Ignore if clipboard is not available

            # Exibe o resultado com o datum utilizado / Show result with the datum used
            self.iface.messageBar().pushMessage(
                'Calc Area',
                '{} | {} EPSG:{} {}{}  (copiado / copied)'.format(
                    formatted, datum_name, utm_epsg, zone, hemi),
                level=Qgis.MessageLevel.Info, duration=8)

        except Exception as e:
            # Exibe o erro na barra de mensagens / Show error in the message bar
            self.iface.messageBar().pushMessage('Calc Area', str(e), level=Qgis.MessageLevel.Warning)
