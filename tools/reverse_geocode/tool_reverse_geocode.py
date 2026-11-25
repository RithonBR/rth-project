# -*- coding: utf-8 -*-
"""
Ferramenta Geocodificação Reversa - Cidade, estado e país do ponto clicado
Reverse Geocode Tool - City, state and country from a clicked map point

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

import json
import urllib.request

from qgis.PyQt.QtGui import QGuiApplication
from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
from qgis.gui import QgsMapToolEmitPoint

_NOMINATIM_URL = 'https://nominatim.openstreetmap.org/reverse?lat={}&lon={}&format=jsonv2'


class ReverseGeocodeTool:
    """Clica no mapa e exibe cidade, estado e país via Nominatim / Click the map to show city, state and country via Nominatim."""

    def __init__(self, iface):
        self.iface   = iface
        self.map_tool = None

    def activate(self):
        """Ativa a ferramenta de geocodificação reversa / Activate the reverse geocoding tool."""
        try:
            canvas         = self.iface.mapCanvas()
            self.map_tool  = QgsMapToolEmitPoint(canvas)
            self.map_tool.canvasClicked.connect(self._on_click)
            canvas.setMapTool(self.map_tool)
            self.iface.messageBar().pushMessage(
                self.iface.mainWindow().tr('Geocodificação Reversa'),
                self.iface.mainWindow().tr(
                    'Clique no mapa para obter cidade, estado e país / '
                    'Click on the map to get city, state and country'),
                level=Qgis.MessageLevel.Info, duration=3)
        except Exception as e:
            self.iface.messageBar().pushMessage(
                'ReverseGeocode', str(e), level=Qgis.MessageLevel.Warning)

    def _on_click(self, point, button):
        """Converte o ponto para WGS84 e consulta o Nominatim / Convert point to WGS84 and query Nominatim."""
        try:
            canvas  = self.iface.mapCanvas()
            src_crs = canvas.mapSettings().destinationCrs()
            wgs84   = QgsCoordinateReferenceSystem('EPSG:4326')

            if src_crs != wgs84:
                transform = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
                pt = transform.transform(point)
            else:
                pt = point

            lat = pt.y()
            lon = pt.x()

            url = _NOMINATIM_URL.format(lat, lon)
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'QGIS-RTH-Plugin/1.0 (https://rithon.com.br)'},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
                data = json.loads(resp.read().decode('utf-8'))

            address      = data.get('address', {})
            city         = (address.get('city')
                            or address.get('town')
                            or address.get('village')
                            or address.get('suburb')
                            or '')
            municipality = address.get('municipality', '')
            state        = address.get('state', '')
            country      = address.get('country', '')

            # Inclui município separado da cidade quando existir e for diferente
            # Include municipality separately from city when present and distinct
            parts = []
            if city:
                parts.append(city)
            if municipality and municipality != city:
                parts.append(municipality)
            if state:
                parts.append(state)
            if country:
                parts.append(country)

            result = ', '.join(parts) if parts else self.iface.mainWindow().tr('Localização não encontrada / Location not found')

            self.iface.messageBar().pushMessage(
                self.iface.mainWindow().tr('Localização / Location'),
                result,
                level=Qgis.MessageLevel.Info,
                duration=8)

            try:
                QGuiApplication.clipboard().setText(result)
            except Exception:
                pass

        except Exception as e:
            self.iface.messageBar().pushMessage(
                'ReverseGeocode',
                self.iface.mainWindow().tr('Erro ao consultar localização / Error querying location: ') + str(e),
                level=Qgis.MessageLevel.Warning,
                duration=5)
        finally:
            try:
                self.iface.mapCanvas().unsetMapTool(self.map_tool)
            except Exception:
                pass
