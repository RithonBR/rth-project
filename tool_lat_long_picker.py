# -*- coding: utf-8 -*-
"""
Ferramenta Lat/Long Picker - Captura coordenadas ao clicar no mapa
LatLong Picker Tool - Captures coordinates by clicking on the map

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Importa a área de transferência do Qt / Import Qt clipboard
from qgis.PyQt.QtGui import QGuiApplication
# Importa a ferramenta de ponto do mapa QGIS / Import QGIS map point tool
from qgis.gui import QgsMapToolEmitPoint


class LatLongPickerTool:
    """Captura Lat/Long ao clicar no mapa e copia para o clipboard / Captures Lat/Long by clicking the map and copies to clipboard."""

    def __init__(self, iface):
        # Armazena a interface QGIS / Store QGIS interface
        self.iface = iface
        # Referência à ferramenta de mapa ativa / Reference to the active map tool
        self.map_tool = None

    def activate(self):
        """Ativa a ferramenta de captura de coordenadas / Activate the coordinate capture tool."""
        try:
            # Obtém o canvas do mapa / Get the map canvas
            canvas = self.iface.mapCanvas()
            # Cria a ferramenta de emissão de ponto / Create the point emit tool
            self.map_tool = QgsMapToolEmitPoint(canvas)
            # Conecta o sinal de clique ao handler / Connect the click signal to the handler
            self.map_tool.canvasClicked.connect(self._on_click)
            # Ativa a ferramenta no canvas / Activate the tool on the canvas
            canvas.setMapTool(self.map_tool)
            # Informa o usuário para clicar no mapa / Inform the user to click on the map
            self.iface.messageBar().pushMessage(
                'LatLong',
                'Clique no mapa para capturar as coordenadas / Click on the map to capture coordinates',
                level=0, duration=3)
        except Exception as e:
            # Exibe o erro na barra de mensagens / Show error in the message bar
            self.iface.messageBar().pushMessage('LatLong', str(e), level=1)

    def _on_click(self, point, button):
        """Captura as coordenadas do clique e copia para o clipboard / Capture click coordinates and copy to clipboard."""
        try:
            # Obtém a latitude do ponto clicado / Get the latitude of the clicked point
            lat = point.y()
            # Obtém a longitude do ponto clicado / Get the longitude of the clicked point
            lon = point.x()
            # Formata as coordenadas com 8 casas decimais / Format coordinates with 8 decimal places
            formatted = '{0:.8f}, {1:.8f}'.format(lat, lon)
            # Exibe as coordenadas na barra de mensagens / Show coordinates in the message bar
            self.iface.messageBar().pushMessage('LatLong', formatted, level=0, duration=5)
            # Copia as coordenadas para o clipboard / Copy coordinates to clipboard
            try:
                QGuiApplication.clipboard().setText(formatted)
            except Exception:
                pass  # Ignora se o clipboard não estiver disponível / Ignore if clipboard is not available
        finally:
            # Desativa a ferramenta após o clique / Deactivate the tool after the click
            try:
                self.iface.mapCanvas().unsetMapTool(self.map_tool)
            except Exception:
                pass  # Ignora erros ao desativar / Ignore deactivation errors
