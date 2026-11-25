# -*- coding: utf-8 -*-
"""
Ferramenta Send to Google Earth Pro - Envia um ponto clicado no mapa para o Google Earth Pro
Send to Google Earth Pro Tool - Sends a map-clicked point to Google Earth Pro

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

import os
import tempfile
import subprocess
from qgis.core import Qgis
from qgis.gui import QgsMapToolEmitPoint


class SendToGoogleTool:
    """Envia um ponto clicado no mapa ao Google Earth Pro via arquivo KML / Sends a map-clicked point to Google Earth Pro via KML file."""

    # Caminhos possíveis de instalação do Google Earth Pro / Possible Google Earth Pro installation paths
    GOOGLE_EARTH_PATHS = [
        r"C:\Program Files\Google\Google Earth Pro\client\googleearth.exe",
        r"C:\Program Files (x86)\Google\Google Earth Pro\client\googleearth.exe",
    ]

    def __init__(self, iface):
        # Armazena a interface QGIS / Store QGIS interface
        self.iface = iface
        # Referência à ferramenta de mapa ativa / Reference to the active map tool
        self.map_tool = None

    def activate(self):
        """Ativa o modo de captura de ponto para envio ao Google Earth Pro / Activate point capture mode to send to Google Earth Pro."""
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
                'Google Earth',
                'Clique no mapa para enviar o ponto ao Google Earth Pro / Click on map to send point to Google Earth Pro',
                level=Qgis.MessageLevel.Info, duration=3)
        except Exception as e:
            # Exibe o erro na barra de mensagens / Show error in the message bar
            self.iface.messageBar().pushMessage('Google Earth', str(e), level=Qgis.MessageLevel.Warning)

    def _on_click(self, point, button):
        """Captura o ponto clicado e abre o Google Earth Pro com um arquivo KML / Capture clicked point and open Google Earth Pro with a KML file."""
        try:
            # Obtém a longitude do ponto / Get the point longitude
            lon = point.x()
            # Obtém a latitude do ponto / Get the point latitude
            lat = point.y()

            # Monta o conteúdo do arquivo KML com as coordenadas / Build KML file content with coordinates
            kml_content = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
                '  <Document>\n'
                '    <Placemark>\n'
                '      <name>Point from RTH</name>\n'
                '      <Point>\n'
                '        <coordinates>{lon},{lat},0</coordinates>\n'
                '      </Point>\n'
                '    </Placemark>\n'
                '  </Document>\n'
                '</kml>'
            ).format(lon=lon, lat=lat)

            # Cria um arquivo KML temporário em disco / Create a temporary KML file on disk
            tf = tempfile.NamedTemporaryFile(delete=False, suffix='.kml')
            # Escreve o conteúdo KML no arquivo / Write KML content to file
            tf.write(kml_content.encode('utf-8'))
            # Fecha o arquivo para liberar o handle / Close file to release the handle
            tf.close()
            # Armazena o caminho do arquivo KML / Store the KML file path
            kml_path = tf.name

            # Tenta abrir o Google Earth Pro diretamente / Try to open Google Earth Pro directly
            launched = False
            for path in self.GOOGLE_EARTH_PATHS:
                # Verifica se o executável existe neste caminho / Check if executable exists at this path
                if os.path.exists(path):
                    try:
                        # Abre o Google Earth Pro passando o arquivo KML / Open Google Earth Pro passing the KML file
                        subprocess.Popen([path, kml_path], close_fds=True)
                        launched = True
                        break
                    except Exception:
                        launched = False

            # Fallback: abre o KML com o aplicativo padrão do sistema / Fallback: open KML with the system default app
            if not launched:
                try:
                    os.startfile(kml_path)
                    launched = True
                except Exception:
                    launched = False

            # Informa o usuário sobre o resultado do envio / Inform the user about the send result
            if launched:
                self.iface.messageBar().pushMessage(
                    'Google Earth',
                    'Ponto enviado: {} / Point sent: {}'.format(kml_path, kml_path),
                    level=Qgis.MessageLevel.Info, duration=5)
            else:
                self.iface.messageBar().pushMessage(
                    'Google Earth',
                    'Não foi possível abrir o Google Earth Pro. KML salvo em: {} / Could not open Google Earth Pro. KML saved at: {}'.format(
                        kml_path, kml_path),
                    level=Qgis.MessageLevel.Warning)
        finally:
            # Desativa a ferramenta de mapa após o clique / Deactivate the map tool after click
            try:
                self.iface.mapCanvas().unsetMapTool(self.map_tool)
            except Exception:
                pass  # Ignora erros ao desativar / Ignore deactivation errors
