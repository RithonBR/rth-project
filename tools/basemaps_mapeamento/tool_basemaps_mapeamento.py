# -*- coding: utf-8 -*-
"""
tool_basemaps_mapeamento — Basemaps de Satélite para Mapeamento Agrícola
tool_basemaps_mapeamento — Satellite Basemaps for Agricultural Mapping

Adiciona ao projeto QGIS layers de imagem de satélite de fundo:
  • ESRI Satellite   — ArcGIS World Imagery    (XYZ {z}/{y}/{x}, sem chave)
  • Google Satellite — Google Maps Satellite   (XYZ {x}/{y}/{z}, sem chave)
  • Bing Satellite   — Microsoft Bing Aerial   (XYZ {q} quadkey nativo, sem chave)

Integrado ao menu "Bases Geográficas > Basemaps" em RTH PROJECT.py.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

from qgis.core import Qgis


class BasemapsMapeamento:
    """Ferramenta de basemaps de satélite / Satellite basemaps tool."""

    def __init__(self, iface):
        self.iface = iface

    def load(self, name):
        """Adiciona o basemap pelo nome ao projeto atual /
        Add the named basemap to the current project."""
        from core.rth_basemaps import add_basemap
        layer = add_basemap(name)
        if layer:
            self.iface.messageBar().pushMessage(
                'RTH Basemaps',
                '{} adicionado ao projeto. / {} added to project.'.format(name, name),
                level=Qgis.MessageLevel.Success, duration=4)
        else:
            self.iface.messageBar().pushMessage(
                'RTH Basemaps',
                '{} não pôde ser carregado — verifique conexão. / '
                '{} could not be loaded — check connection.'.format(name, name),
                level=Qgis.MessageLevel.Warning, duration=6)
