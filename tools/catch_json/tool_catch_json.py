# -*- coding: utf-8 -*-
"""
Ferramenta Catch JSON - Exporta a geometria da feição selecionada como GeoJSON
Catch JSON Tool - Exports the selected feature geometry as GeoJSON

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Biblioteca padrão para serialização JSON / Standard library for JSON serialization
import json
# Importa a área de transferência do Qt / Import Qt clipboard
from qgis.PyQt.QtGui import QGuiApplication
# Importações do QGIS para reprojeção / QGIS imports for reprojection
from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsProject,
)


class CatchJsonTool:
    """Exporta a geometria da feição selecionada para o clipboard como GeoJSON / Exports selected feature geometry to clipboard as GeoJSON."""

    def __init__(self, iface):
        # Armazena a interface QGIS / Store QGIS interface
        self.iface = iface

    def export(self):
        """Pega o JSON da feição selecionada e copia para o clipboard / Get selected feature JSON and copy to clipboard."""
        # Obtém a camada ativa / Get the active layer
        layer = self.iface.activeLayer()
        # Verifica se há uma camada ativa / Check if there is an active layer
        if layer is None:
            self.iface.messageBar().pushMessage(
                'Catch JSON', 'Nenhuma camada ativa / No active layer', level=Qgis.MessageLevel.Warning)
            return
        try:
            # Obtém as feições selecionadas na camada ativa / Get selected features in the active layer
            feats = layer.selectedFeatures()
            # Verifica se há feições selecionadas / Check if there are selected features
            if not feats:
                self.iface.messageBar().pushMessage(
                    'Catch JSON', 'Nenhuma feição selecionada / No feature selected', level=Qgis.MessageLevel.Warning)
                return

            # Reprojeção para WGS84 se necessário / Reproject to WGS84 if needed
            wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
            layer_crs = layer.crs()
            need_reproject = layer_crs.authid() != 'EPSG:4326'
            if need_reproject:
                xform = QgsCoordinateTransform(layer_crs, wgs84, QgsProject.instance())

            # Serializa a geometria para GeoJSON com coordinates antes de type
            # Serialize geometry to GeoJSON with coordinates before type
            def _geom_to_ordered(geom):
                """Converte geometria para dict WGS84 com chave coordinates antes de type.
                Converts geometry to WGS84 dict with coordinates key before type."""
                if need_reproject:
                    # Clona e transforma para WGS84 antes de serializar / Clone and transform to WGS84 before serializing
                    from qgis.core import QgsGeometry
                    geom = QgsGeometry(geom)
                    geom.transform(xform)
                raw = json.loads(geom.asJson())
                # Garante a ordem: coordinates primeiro, type segundo / Ensures order: coordinates first, type second
                return {"coordinates": raw["coordinates"], "type": raw["type"]}

            if len(feats) == 1:
                # Uma feição: retorna o GeoJSON compacto / One feature: return compact GeoJSON
                result = json.dumps(_geom_to_ordered(feats[0].geometry()), separators=(',', ':'))
            else:
                # Múltiplas feições: retorna lista de objetos GeoJSON / Multiple features: return list of GeoJSON objects
                result = json.dumps(
                    [_geom_to_ordered(f.geometry()) for f in feats],
                    separators=(',', ':')
                )

            # Copia o resultado para o clipboard / Copy result to clipboard
            try:
                QGuiApplication.clipboard().setText(result)
            except Exception:  # nosec B110
                pass  # Ignora se o clipboard não estiver disponível / Ignore if clipboard is not available

            # Informa o usuário sobre o resultado / Inform the user about the result
            self.iface.messageBar().pushMessage(
                'Catch JSON',
                '{} feição(ões) copiada(s) para o clipboard / {} feature(s) copied to clipboard'.format(
                    len(feats), len(feats)),
                level=Qgis.MessageLevel.Info, duration=4)
        except Exception as e:
            # Exibe o erro na barra de mensagens / Show error in the message bar
            self.iface.messageBar().pushMessage('Catch JSON', str(e), level=Qgis.MessageLevel.Warning)
