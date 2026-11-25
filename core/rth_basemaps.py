# -*- coding: utf-8 -*-
"""
rth_basemaps — Carregador de basemaps de satélite para mapeamento agrícola
rth_basemaps — Satellite basemap loader for agricultural mapping

Provedores suportados / Supported providers:
  ESRI Satellite   → XYZ tiles via server.arcgisonline.com  (sem chave / no key)
  Google Satellite → XYZ tiles via mt1.google.com            (sem chave / no key)
  Bing Satellite   → XYZ tiles com quadkey {q} nativo do QGIS (sem chave / no key)

Todos os três usam o provider 'wms' do QGIS com type=xyz.
O QGIS converte internamente {x}/{y}/{z} e {q} (quadkey Bing) sem depender do GDAL.
URI construída com QgsDataSourceUri para encoding correto dos parâmetros.

All three use QGIS 'wms' provider with type=xyz.
QGIS internally converts {x}/{y}/{z} and {q} (Bing quadkey) without relying on GDAL.
URI built with QgsDataSourceUri for correct parameter encoding.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""


# ── Catálogo de provedores / Provider catalogue ───────────────────────────────
#
# {x}, {y}, {z} → substituídos pelo provider XYZ nativo do QGIS
# {q}           → quadkey Bing (base-4, comprimento = z), também suportado nativamente

BASEMAP_PROVIDERS = {
    'ESRI Satellite': {
        'url':  'https://server.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        'zmin': '0',
        'zmax': '22',
    },
    'Google Satellite': {
        'url':     'https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        'zmin':    '0',
        'zmax':    '21',
        # referer reduz bloqueios/timeouts do servidor de tiles do Google.
        # referer reduces blocking/timeouts from Google's tile server.
        'referer': 'https://maps.google.com/',
    },
    'Bing Satellite': {
        # {q} = quadkey calculado pelo QGIS a partir de x/y/z — sem GDAL, sem crash
        'url':  'http://ecn.t3.tiles.virtualearth.net/tiles/a{q}.jpeg?g=1',
        'zmin': '1',
        'zmax': '19',
    },
}


def add_basemap(name):
    """Adiciona um basemap de satélite ao projeto QGIS atual /
    Add a satellite basemap to the current QGIS project.

    :param name: chave do provedor — 'ESRI Satellite', 'Google Satellite', 'Bing Satellite' /
                 provider key — 'ESRI Satellite', 'Google Satellite', 'Bing Satellite'
    :returns: QgsRasterLayer adicionado ao projeto, ou None em caso de falha /
              QgsRasterLayer added to project, or None on failure
    """
    from qgis.core import QgsDataSourceUri, QgsRasterLayer, QgsProject

    cfg = BASEMAP_PROVIDERS.get(name)
    if not cfg:
        return None

    # QgsDataSourceUri faz o encoding correto da URL como parâmetro URI.
    # Preserva os placeholders {x}/{y}/{z}/{q} que o QGIS substitui ao renderizar.
    # QgsDataSourceUri correctly encodes the URL as a URI parameter.
    # It preserves {x}/{y}/{z}/{q} placeholders that QGIS substitutes on render.
    uri = QgsDataSourceUri()
    uri.setParam('type', 'xyz')
    uri.setParam('url', cfg['url'])
    uri.setParam('zmin', cfg['zmin'])
    uri.setParam('zmax', cfg['zmax'])
    if cfg.get('referer'):
        uri.setParam('referer', cfg['referer'])

    layer = QgsRasterLayer(str(uri.encodedUri(), 'utf-8'), name, 'wms')

    if layer and layer.isValid():
        QgsProject.instance().addMapLayer(layer)
        return layer
    return None
