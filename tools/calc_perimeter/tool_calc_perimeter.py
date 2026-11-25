# -*- coding: utf-8 -*-
"""
Ferramenta Calc Perimetro - Calcula o perímetro das feições selecionadas em metros
Calc Perimeter Tool - Calculates the perimeter of selected features in metres

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

from qgis.PyQt.QtGui import QGuiApplication
from qgis.core import (
    Qgis,
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
)
from core.rth_utm_utils import detect_regional_utm


class CalcPerimeterTool:
    """Calcula o perímetro total das feições selecionadas em metros usando projeção UTM regional / Calculates total perimeter of selected features in metres using regional UTM projection."""

    def __init__(self, iface):
        self.iface = iface

    def calculate(self):
        """Calcula o perímetro das feições selecionadas e copia o resultado para o clipboard / Calculate perimeter of selected features and copy result to clipboard."""
        layer = self.iface.activeLayer()
        if layer is None:
            self.iface.messageBar().pushMessage(
                'Calc Perímetro', 'Nenhuma camada ativa / No active layer',
                level=Qgis.MessageLevel.Warning)
            return
        try:
            feats = layer.selectedFeatures()
            if not feats:
                self.iface.messageBar().pushMessage(
                    'Calc Perímetro', 'Nenhuma feição selecionada / No feature selected',
                    level=Qgis.MessageLevel.Warning)
                return

            source_crs = layer.crs()
            wgs84      = QgsCoordinateReferenceSystem('EPSG:4326')
            to_wgs     = QgsCoordinateTransform(source_crs, wgs84, QgsProject.instance())

            first_geom   = feats[0].geometry()
            centroid_pt  = first_geom.centroid().asPoint()
            centroid_wgs = to_wgs.transform(centroid_pt)
            lon = centroid_wgs.x()
            lat = centroid_wgs.y()

            utm_epsg, datum_name, zone, hemi = detect_regional_utm(lon, lat)
            utm_crs = QgsCoordinateReferenceSystem('EPSG:{}'.format(utm_epsg))
            to_utm  = QgsCoordinateTransform(source_crs, utm_crs, QgsProject.instance())

            total_m = 0.0
            for feat in feats:
                geom = feat.geometry()
                if geom is None:
                    continue
                geom_utm = QgsGeometry(geom)
                geom_utm.transform(to_utm)
                total_m += geom_utm.length()

            if total_m >= 1000.0:
                formatted = '{:.4f} quilômetros / kilometers'.format(total_m / 1000.0)
                clip_val  = '{:.6f}'.format(total_m / 1000.0)
            else:
                formatted = '{:.2f} metros / meters'.format(total_m)
                clip_val  = '{:.4f}'.format(total_m)

            try:
                QGuiApplication.clipboard().setText(clip_val)
            except Exception:  # nosec B110
                pass

            self.iface.messageBar().pushMessage(
                'Calc Perímetro',
                '{} | {} EPSG:{} {}{}  (copiado / copied)'.format(
                    formatted, datum_name, utm_epsg, zone, hemi),
                level=Qgis.MessageLevel.Info, duration=8)

        except Exception as e:
            self.iface.messageBar().pushMessage(
                'Calc Perímetro', str(e), level=Qgis.MessageLevel.Warning)
