# -*- coding: utf-8 -*-
"""
rth_layer_utils — Utilitários de CRS, renderização e sanitização de nomes para camadas STAC
rth_layer_utils — CRS, rendering and filename sanitization utilities for STAC layers

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Biblioteca padrão para expressões regulares / Standard library for regular expressions
import re

# Módulos QGIS para renderização, contraste e CRS / QGIS modules for rendering, contrast and CRS
from qgis.core import (
    QgsMultiBandColorRenderer,
    QgsContrastEnhancement,
    QgsRasterMinMaxOrigin,
    QgsRectangle,
    QgsCoordinateReferenceSystem,
)


def assign_crs_from_bbox(layer, feature):
    """Atribui o CRS correto à camada usando as informações do item STAC / Assign correct CRS to layer using STAC item information.

    Chamada como fallback quando o Warp para EPSG:4326 não é possível.
    Called as fallback when Warp to EPSG:4326 is not possible.

    Prioridade / Priority:
    1. CRS já válido com EPSG reconhecido (GDAL leu corretamente) / Already valid EPSG CRS (GDAL read correctly)
    2. proj:epsg nas propriedades do item STAC (CRS nativo exato) / proj:epsg in STAC item properties (exact native CRS)
    3. proj:wkt nas propriedades do item STAC (inclui projeções não-padrão) / proj:wkt in STAC properties (includes non-standard projections)
    4. CRS válido qualquer que GDAL leu (mesmo sem código EPSG) / Any valid CRS GDAL read (even without EPSG code)
    5. Último recurso: EPSG:4326 / Last resort: EPSG:4326

    Nota: o fallback UTM foi removido pois errava a projeção de composites BDC em coordenadas geográficas.
    Note: UTM fallback was removed as it misplaced BDC composites stored in geographic coordinates.

    :param layer: camada raster a corrigir / raster layer to fix
    :param feature: item GeoJSON com properties / GeoJSON item with properties
    """
    # 1. Camada já tem CRS válido com EPSG reconhecido — GDAL leu corretamente / Layer already has valid EPSG CRS — GDAL read correctly
    if layer.crs().isValid() and layer.crs().authid().startswith('EPSG:'):
        return

    props = feature.get('properties', {})

    # 2. proj:epsg do item STAC — CRS nativo exato do dado / proj:epsg from STAC item — exact native data CRS
    proj_epsg = props.get('proj:epsg')
    if proj_epsg:
        try:
            crs = QgsCoordinateReferenceSystem('EPSG:{}'.format(int(proj_epsg)))
            if crs.isValid():
                layer.setCrs(crs)
                return
        except (ValueError, TypeError):
            pass

    # 3. proj:wkt do item STAC — cobre projeções não-padrão como BDC Albers / proj:wkt from STAC item — covers non-standard projections like BDC Albers
    proj_wkt = props.get('proj:wkt')
    if proj_wkt:
        crs = QgsCoordinateReferenceSystem(proj_wkt)
        if crs.isValid():
            layer.setCrs(crs)
            return

    # 4. Qualquer CRS válido que o GDAL leu do arquivo (mesmo sem código EPSG) / Any valid CRS GDAL read from file (even without EPSG code)
    if layer.crs().isValid():
        return  # Mantém o que GDAL detectou / Keep what GDAL detected

    # 5. Último recurso: EPSG:4326 (WGS84) — mais seguro que UTM para dados desconhecidos /
    # Last resort: EPSG:4326 (WGS84) — safer than UTM for unknown data
    crs = QgsCoordinateReferenceSystem('EPSG:4326')
    if crs.isValid():
        layer.setCrs(crs)


def apply_stretch(layer):
    """Aplica corte cumulativo 2-98% a qualquer camada (mono ou multibanda) / Apply 2-98% cumulative cut stretch to any layer (single or multiband).

    :param layer: camada raster / raster layer
    """
    # QgsRectangle() vazio usa a extensão completa do dataset / Empty QgsRectangle() uses full dataset extent
    layer.setContrastEnhancement(
        QgsContrastEnhancement.StretchToMinimumMaximum,
        QgsRasterMinMaxOrigin.CumulativeCut,
        QgsRectangle(),
    )


def apply_rgb_renderer(layer):
    """Aplica renderizador RGB e corte cumulativo 2-98% / Apply RGB renderer and 2-98% cumulative cut stretch.

    :param layer: camada raster de 3 bandas / 3-band raster layer
    """
    # Renderizador multiband: banda 1→R, 2→G, 3→B / Multiband renderer: band 1→R, 2→G, 3→B
    renderer = QgsMultiBandColorRenderer(layer.dataProvider(), 1, 2, 3)
    layer.setRenderer(renderer)
    # QgsRectangle() vazio usa a extensão completa da camada / Empty QgsRectangle() uses full layer extent
    layer.setContrastEnhancement(
        QgsContrastEnhancement.StretchToMinimumMaximum,
        QgsRasterMinMaxOrigin.CumulativeCut,
        QgsRectangle(),
    )


def safe_id(text):
    """Substitui caracteres não-alfanuméricos por _ para uso seguro em nomes de arquivo / Replace non-alphanumeric chars with _ for safe use in filenames.

    :param text: texto original / original text
    :returns: texto sanitizado / sanitized text
    :rtype: str
    """
    return re.sub(r'[^\w]', '_', text)
