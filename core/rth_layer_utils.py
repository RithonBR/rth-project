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
    QgsSingleBandGrayRenderer,
    QgsContrastEnhancement,
    QgsRasterMinMaxOrigin,
    QgsRectangle,
    QgsCoordinateReferenceSystem,
)

# Enums com try/except: QGIS 3 (Qt5) expõe direto na classe;
# QGIS 4 (Qt6) pode exigir o sub-namespace Limits / ContrastEnhancementAlgorithm.
try:
    _CUMCUT = QgsRasterMinMaxOrigin.Limits.CumulativeCut
except AttributeError:
    _CUMCUT = QgsRasterMinMaxOrigin.CumulativeCut

try:
    _CE_STRETCH = QgsContrastEnhancement.ContrastEnhancementAlgorithm.StretchToMinimumMaximum
except AttributeError:
    _CE_STRETCH = QgsContrastEnhancement.StretchToMinimumMaximum


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
        except (ValueError, TypeError):  # nosec B110
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


def _apply_cumcut(layer):
    """Corte cumulativo 2-98% sobre a extensão completa da camada com valores estimados.
    QgsRectangle() vazio = QGIS usa extensão total do dataset com sampling (~250k pixels).
    Cumulative cut 2-98% over full layer extent with estimated values (sampling ~250k px)."""
    layer.setContrastEnhancement(_CE_STRETCH, _CUMCUT, QgsRectangle())


def apply_stretch(layer):
    """Aplica corte cumulativo 2-98% a qualquer camada (mono ou multibanda) /
    Apply 2-98% cumulative cut stretch to any layer (single or multiband)."""
    _apply_cumcut(layer)


def apply_rgb_renderer(layer):
    """Aplica renderizador adequado ao número de bandas e corte cumulativo 2-98%.
    Apply renderer appropriate to band count and 2-98% cumulative cut stretch.

    1 banda  → escala de cinza (QgsSingleBandGrayRenderer)
    ≥3 bandas → RGB (QgsMultiBandColorRenderer, bandas 1→R, 2→G, 3→B)

    Sem esta verificação, um GeoTIFF de 1 banda com renderer RGB gera
    'Pointer hBand is NULL in GDALRasterIOEx' porque as bandas 2 e 3 não existem.
    Without this check, a 1-band GeoTIFF with RGB renderer raises
    'Pointer hBand is NULL in GDALRasterIOEx' because bands 2 and 3 do not exist.
    """
    n_bands = layer.bandCount()
    if n_bands >= 3:
        # Renderizador multiband: banda 1→R, 2→G, 3→B / Multiband renderer: band 1→R, 2→G, 3→B
        renderer = QgsMultiBandColorRenderer(layer.dataProvider(), 1, 2, 3)
    else:
        # Banda única (extras do Smart Download: B11, B8A…) / Single band (Smart Download extras: B11, B8A…)
        renderer = QgsSingleBandGrayRenderer(layer.dataProvider(), 1)
    layer.setRenderer(renderer)
    _apply_cumcut(layer)


def safe_id(text):
    """Substitui caracteres não-alfanuméricos por _ para uso seguro em nomes de arquivo / Replace non-alphanumeric chars with _ for safe use in filenames.

    :param text: texto original / original text
    :returns: texto sanitizado / sanitized text
    :rtype: str
    """
    return re.sub(r'[^\w]', '_', text)


def collapse_layer(layer):
    """Collapse the layer's panel node, resisting QGIS 4's async auto-expand.

    QGIS (especially 4.x / Qt6) fires an automatic expand on the layer tree
    node some time after addMapLayer() returns, once legend items finish loading
    in the background.  A plain setExpanded(False) right after addMapLayer runs
    too early and gets overridden.

    Strategy:
      1. Collapse immediately (catches the synchronous case / QGIS 3.x).
      2. Install a one-shot guard on expandedChanged: the first time QGIS
         auto-expands the node the guard re-collapses it and disconnects itself,
         so the user can still expand it manually afterwards.
      3. A 2-second safety timer disconnects the guard even if auto-expand
         never fires (e.g. layer with no legend items).
    """
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QTimer

    layer_id = layer.id()

    def _install():
        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(layer_id)
        if node is None:
            return

        node.setExpanded(False)

        def _guard(expanded):
            if not expanded:
                return
            # QGIS auto-expanded — re-collapse and remove this one-shot guard
            root2 = QgsProject.instance().layerTreeRoot()
            n = root2.findLayer(layer_id)
            if n:
                try:
                    n.expandedChanged.disconnect(_guard)
                except Exception:  # nosec B110
                    pass
                n.setExpanded(False)

        node.expandedChanged.connect(_guard)

        def _cleanup():
            root3 = QgsProject.instance().layerTreeRoot()
            n = root3.findLayer(layer_id)
            if n:
                try:
                    n.expandedChanged.disconnect(_guard)
                except Exception:  # nosec B110
                    pass

        QTimer.singleShot(2000, _cleanup)

    QTimer.singleShot(0, _install)
