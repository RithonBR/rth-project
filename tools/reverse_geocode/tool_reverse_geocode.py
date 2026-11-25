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
from qgis.PyQt.QtCore import QThread, pyqtSignal, QObject
from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
from qgis.gui import QgsMapToolEmitPoint

_NOMINATIM_URL = 'https://nominatim.openstreetmap.org/reverse?lat={}&lon={}&format=jsonv2'


class _GeocoderThread(QThread):
    """Executa a consulta Nominatim em background / Runs Nominatim query in background."""
    result_ready = pyqtSignal(str)
    error_sig    = pyqtSignal(str)

    def __init__(self, lat, lon, parent=None):
        super().__init__(parent)
        self._lat = lat
        self._lon = lon

    def run(self):
        try:
            url = _NOMINATIM_URL.format(self._lat, self._lon)
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

            parts = []
            if city:
                parts.append(city)
            if municipality and municipality != city:
                parts.append(municipality)
            if state:
                parts.append(state)
            if country:
                parts.append(country)

            self.result_ready.emit(', '.join(parts))
        except Exception as e:
            self.error_sig.emit(str(e))


class ReverseGeocodeTool(QObject):
    """Clica no mapa e exibe cidade, estado e país via Nominatim / Click the map to show city, state and country via Nominatim."""

    def __init__(self, iface):
        super().__init__()
        self.iface             = iface
        self.map_tool          = None
        self._geocoder_thread  = None
        self._pending_bar_item = None

    def activate(self):
        """Ativa a ferramenta de geocodificação reversa / Activate the reverse geocoding tool."""
        try:
            canvas        = self.iface.mapCanvas()
            self.map_tool = QgsMapToolEmitPoint(canvas)
            self.map_tool.canvasClicked.connect(self._on_click)
            canvas.setMapTool(self.map_tool)
            self.iface.messageBar().pushMessage(
                self.iface.mainWindow().tr('Geocodificação Reversa / Reverse Geocoding'),
                self.iface.mainWindow().tr(
                    'Clique no mapa para obter cidade, estado e país / '
                    'Click on the map to get city, state and country'),
                level=Qgis.MessageLevel.Info, duration=3)
        except Exception as e:
            self.iface.messageBar().pushMessage(
                'ReverseGeocode', str(e), level=Qgis.MessageLevel.Warning)

    def _on_click(self, point, button):
        """Converte coordenadas e dispara a busca Nominatim em thread / Convert coordinates and dispatch Nominatim query in thread."""
        # Conversão de CRS — só matemática, sem rede, pode rodar na main thread
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
        except Exception as e:
            self.iface.messageBar().pushMessage(
                'ReverseGeocode', str(e), level=Qgis.MessageLevel.Warning)
            try:
                self.iface.mapCanvas().unsetMapTool(self.map_tool)
            except Exception:
                pass
            return

        # Desativa a ferramenta imediatamente para evitar duplo-clique
        try:
            self.iface.mapCanvas().unsetMapTool(self.map_tool)
        except Exception:
            pass

        # Cancela busca anterior se ainda estiver rodando
        if self._geocoder_thread and self._geocoder_thread.isRunning():
            self._geocoder_thread.quit()
            self._geocoder_thread.wait(500)
            self._dismiss_pending()

        # Exibe "Consultando" imediatamente para o usuário saber que a busca começou
        # Show "Querying" immediately so the user knows the lookup has started
        self._pending_bar_item = self.iface.messageBar().createMessage(
            '', 'Consultando localização... / Querying location...')
        self.iface.messageBar().pushWidget(
            self._pending_bar_item, Qgis.MessageLevel.Info, 0)

        # Lança a requisição Nominatim em background — não bloqueia a UI
        self._geocoder_thread = _GeocoderThread(lat, lon, self)
        self._geocoder_thread.result_ready.connect(self._on_geocoder_done)
        self._geocoder_thread.error_sig.connect(self._on_geocoder_error)
        self._geocoder_thread.start()

    def _dismiss_pending(self):
        if self._pending_bar_item:
            try:
                self.iface.messageBar().popWidget(self._pending_bar_item)
            except Exception:
                pass
            self._pending_bar_item = None

    def _on_geocoder_done(self, result):
        self._dismiss_pending()
        if not result:
            result = 'Localização não encontrada / Location not found'
        self.iface.messageBar().pushMessage(
            'Localização / Location',
            result,
            level=Qgis.MessageLevel.Info,
            duration=8)
        try:
            QGuiApplication.clipboard().setText(result)
        except Exception:
            pass

    def _on_geocoder_error(self, msg):
        self._dismiss_pending()
        self.iface.messageBar().pushMessage(
            'ReverseGeocode',
            'Erro ao consultar localização / Error querying location: ' + msg,
            level=Qgis.MessageLevel.Warning,
            duration=5)
