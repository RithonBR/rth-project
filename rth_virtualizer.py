# -*- coding: utf-8 -*-
"""
rth_virtualizer — Virtualização padronizada de cenas STAC com datum UTM regional
rth_virtualizer — Standardized STAC scene virtualization with regional UTM datum

Abordagem padrão: usa gdal.Warp para reprojetar para o datum UTM regional detectado.
Standard approach: uses gdal.Warp to reproject to the detected regional UTM datum.

Isso garante que TODOS os satélites (S2 cena, S2 16D, Landsat cena, Landsat 16D,
CBERS, Amazonia) apareçam no local correto, na projeção adequada para a região.
This ensures ALL satellites appear in the correct location, in the appropriate
projection for the region.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Biblioteca padrão para caminhos e pasta temporária / Standard library for paths and temp folder
import os
import tempfile

# Módulos QGIS para camadas e projeto / QGIS modules for layers and project
from qgis.core import QgsRasterLayer, QgsProject, QgsCoordinateReferenceSystem

# Importa catálogo de bandas / Import band catalog
from rth_catalog import get_band_tuple
# Importa resolução de bandas / Import band resolution
from rth_band_resolver import find_asset_key
# Importa assinatura de URLs do Planetary Computer / Import Planetary Computer URL signing
from rth_pc_auth import resolve_href
# Importa utilitários de camada / Import layer utilities
from rth_layer_utils import assign_crs_from_bbox, apply_stretch, apply_rgb_renderer, safe_id
# Importa detecção de datum UTM regional / Import regional UTM datum detection
from rth_utm_utils import detect_regional_utm

# CRS WGS84 utilizado como fallback quando bbox não está disponível / WGS84 CRS used as fallback when bbox is unavailable
_WGS84 = QgsCoordinateReferenceSystem('EPSG:4326')


def _scene_utm_crs(feature):
    """Detecta o CRS UTM regional a partir do bbox do item STAC / Detect regional UTM CRS from STAC item bbox.

    Usa o centroide do bbox para chamar detect_regional_utm e obter o datum correto.
    Uses bbox centroid to call detect_regional_utm and get the correct datum.

    :param feature: item STAC com campo 'bbox' / STAC item with 'bbox' field
    :returns: (dst_srs_str, QgsCoordinateReferenceSystem) do datum regional
    :rtype: tuple[str, QgsCoordinateReferenceSystem]
    """
    bbox = feature.get('bbox', [])
    if len(bbox) >= 4:
        # Centroide do bbox: (lon_min + lon_max) / 2, (lat_min + lat_max) / 2
        # Bbox centroid: (lon_min + lon_max) / 2, (lat_min + lat_max) / 2
        lon = (bbox[0] + bbox[2]) / 2.0
        lat = (bbox[1] + bbox[3]) / 2.0
        # Detecta datum e EPSG regional / Detect regional datum and EPSG
        epsg, _, _, _ = detect_regional_utm(lon, lat)
        dst_srs = 'EPSG:{}'.format(epsg)
        return dst_srs, QgsCoordinateReferenceSystem(dst_srs)
    # Fallback para WGS84 se bbox ausente / Fallback to WGS84 if bbox is missing
    return 'EPSG:4326', _WGS84


def _init_gdal():
    """Inicializa e configura o GDAL para acesso remoto via vsicurl / Initialize and configure GDAL for remote access via vsicurl.

    :returns: módulo gdal configurado ou None / configured gdal module or None
    :rtype: module | None
    """
    try:
        from osgeo import gdal as _gdal
    except ImportError:
        return None

    # Configurações para COGs remotos via HTTP(S) / Settings for remote COGs via HTTP(S)
    _gdal.SetConfigOption('GDAL_HTTP_UNSAFESSL',          'YES')   # Ignora erros SSL / Ignore SSL errors
    _gdal.SetConfigOption('GDAL_HTTP_TIMEOUT',            '30')    # Timeout em segundos / Timeout in seconds
    _gdal.SetConfigOption('CPL_VSIL_CURL_USE_CACHE',      'YES')   # Cache de headers / Header cache
    _gdal.SetConfigOption('CPL_VSIL_CURL_CACHE_SIZE',     '128000000')  # 128 MB
    _gdal.SetConfigOption('GDAL_DISABLE_READDIR_ON_OPEN', 'EMPTY_DIR')
    return _gdal


def _warp_to_crs_vrt(src, vrt_path, _gdal, dst_srs):
    """Cria VRT reprojetado para o CRS de destino via gdal.Warp / Create VRT reprojected to target CRS via gdal.Warp.

    O Warp lê o CRS nativo diretamente do GDAL (incluindo projeções não-padrão como BDC Albers),
    garantindo que a imagem apareça no local correto para qualquer satélite.
    Warp reads the native CRS directly from GDAL (including non-standard projections like BDC Albers),
    ensuring the image appears in the correct location for any satellite.

    :param src: URL vsicurl, caminho VRT em disco ou vsimem / vsicurl URL, disk VRT path or vsimem
    :param vrt_path: caminho de saída do VRT reprojetado / reprojected VRT output path
    :param _gdal: módulo gdal / gdal module
    :param dst_srs: string do CRS de destino, ex: 'EPSG:31982' / target CRS string, e.g. 'EPSG:31982'
    :returns: True se o VRT foi criado com sucesso / True if VRT created successfully
    :rtype: bool
    """
    try:
        opts = _gdal.WarpOptions(
            format='VRT',
            dstSRS=dst_srs,       # Datum UTM regional detectado / Detected regional UTM datum
            multithread=True,     # Usa múltiplos threads para leitura de headers / Use multiple threads for header reading
        )
        ds = _gdal.Warp(vrt_path, src, options=opts)
        if ds:
            ds.FlushCache()
            del ds
            return True
    except Exception:
        pass
    return False


def _add_layer(vrt_or_url, layer_name, feature, apply_fn, target_crs=None):
    """Carrega a camada no QGIS e atribui CRS / Load layer in QGIS and assign CRS.

    :param vrt_or_url: caminho VRT ou URL vsicurl / VRT path or vsicurl URL
    :param layer_name: nome da camada / layer name
    :param feature: item STAC para extração de CRS (fallback) / STAC item for CRS extraction (fallback)
    :param apply_fn: função de renderização / rendering function
    :param target_crs: CRS detectado para atribuir, ou None para usar bbox do item / detected CRS to assign, or None to use item bbox
    :returns: 1 se carregada com sucesso, 0 caso contrário / 1 if loaded successfully, 0 otherwise
    :rtype: int
    """
    layer = QgsRasterLayer(vrt_or_url, layer_name)
    if not layer.isValid():
        return 0

    if target_crs is not None:
        # Atribui o CRS UTM regional detectado / Assign detected regional UTM CRS
        layer.setCrs(target_crs)
    else:
        # Fallback: usa proj:epsg/wkt do item STAC / Fallback: use proj:epsg/wkt from STAC item
        assign_crs_from_bbox(layer, feature)

    apply_fn(layer)
    QgsProject.instance().addMapLayer(layer)
    return 1


def virtualize_scenes(features, collection_id, composition_key,
                      progress_cb=None, band_tuple=None):
    """Virtualiza cenas STAC como composição RGB no datum UTM regional correto / Virtualize STAC scenes as RGB composite in the correct regional UTM datum.

    Fluxo padrão para todos os satélites / Standard flow for all satellites:
    1. Detecta datum UTM regional pelo bbox da cena / Detect regional UTM datum from scene bbox
    2. Tenta reprojetar para o CRS regional via gdal.Warp (VRT virtual, sem download)
    3. Fallback: carrega direto + atribui CRS via proj:epsg/wkt do item STAC

    :param features: lista de features GeoJSON / list of GeoJSON features
    :param collection_id: ID da coleção STAC / STAC collection ID
    :param composition_key: 'RGB', 'RED_NIR_BLUE', 'NIR_SWIR_RED' ou 'PAN'
    :param progress_cb: callable(msg, error=False) para progresso / progress callable
    :param band_tuple: tuple de bandas ou string do asset PAN ou None / band override or None for catalog
    :returns: número de camadas carregadas / number of layers loaded
    :rtype: int
    """
    _gdal = _init_gdal()

    # Usa o valor fornecido ou consulta o catálogo / Use provided value or query catalog
    bt = band_tuple if band_tuple is not None else get_band_tuple(collection_id, composition_key)

    # Rótulos dos canais de acordo com a composição / Channel labels according to composition
    if composition_key == 'NIR_SWIR_RED':
        labels = ('NIR', 'SWIR', 'RED')
    elif composition_key == 'RED_NIR_BLUE':
        labels = ('RED', 'NIR', 'BLUE')
    elif composition_key == 'RED_NIR_GREEN':
        labels = ('RED', 'NIR', 'GREEN')
    else:
        labels = ('R', 'G', 'B')

    loaded = 0
    tmp    = tempfile.gettempdir()

    for feature in features:
        assets   = feature.get('assets', {})
        scene_id = feature.get('id', 'scene')

        # ── Detecta datum UTM regional para esta cena / Detect regional UTM datum for this scene ──
        dst_srs, utm_crs = _scene_utm_crs(feature)

        # ── Caminho A: asset de banda única (PAN, EVI, NDVI) — escala de cinza ─
        # Single-band asset (PAN, EVI, NDVI) — grayscale
        if composition_key in ('PAN', 'EVI', 'NDVI'):
            asset_name = bt if isinstance(bt, str) else None
            asset_key  = find_asset_key(assets, asset_name) if asset_name else None
            if asset_key:
                url     = '/vsicurl/' + resolve_href(assets[asset_key]['href'])
                name    = '{} [{}]'.format(scene_id, composition_key)
                vrt_out = os.path.join(tmp, 'rth_{}_{}_utm.vrt'.format(
                    safe_id(scene_id), composition_key))
                if _gdal and _warp_to_crs_vrt(url, vrt_out, _gdal, dst_srs):
                    loaded += _add_layer(vrt_out, name, feature, apply_stretch, target_crs=utm_crs)
                else:
                    loaded += _add_layer(url, name, feature, apply_stretch)
            elif progress_cb:
                progress_cb('{}: asset {} não encontrado / {} asset not found'.format(
                    scene_id, composition_key, composition_key), True)
            continue

        # ── Caminho B: preview RGB pronto (TCI ou visual) ────────────────────
        # RGB shortcut: ready 3-band preview (TCI or visual)
        preview_key = next((k for k in ('TCI', 'visual') if k in assets), None)
        if composition_key == 'RGB' and preview_key:
            src_url = '/vsicurl/' + resolve_href(assets[preview_key]['href'])
            vrt_out = os.path.join(tmp, 'rth_{}_{}.vrt'.format(safe_id(scene_id), preview_key))
            name    = '{} [RGB]'.format(scene_id)
            if _gdal and _warp_to_crs_vrt(src_url, vrt_out, _gdal, dst_srs):
                loaded += _add_layer(vrt_out, name, feature, apply_rgb_renderer, target_crs=utm_crs)
            else:
                if progress_cb:
                    progress_cb('{}: warp falhou — carga direta / warp failed — direct load'.format(scene_id))
                loaded += _add_layer(src_url, name, feature, apply_rgb_renderer)
            continue

        # ── Caminho C: bandas individuais → composição 3 bandas ──────────────
        # Individual bands → 3-band composite
        if bt:
            loaded += _load_from_bands(
                feature, scene_id, assets, bt, labels, _gdal,
                composition_key, tmp, progress_cb, dst_srs, utm_crs)
        else:
            # ── Caminho D: sem mapeamento → primeiro asset disponível ─────────
            # No band mapping → first available image asset
            loaded += _load_first_image(feature, scene_id, assets, _gdal, tmp, dst_srs, utm_crs)

    return loaded


def _load_from_bands(feature, scene_id, assets, bt, labels, _gdal,
                     composition_key, tmp, progress_cb, dst_srs, utm_crs):
    """Resolve bandas individualmente, monta VRT composto e reprojeita para o CRS regional / Resolve bands individually, build composite VRT and reproject to regional CRS.

    :param dst_srs: string do CRS de destino regional / regional target CRS string
    :param utm_crs: objeto QgsCoordinateReferenceSystem do CRS regional / regional QgsCoordinateReferenceSystem object
    :returns: número de camadas carregadas para esta cena / number of layers loaded for this scene
    :rtype: int
    """
    band_urls = []
    resolved  = []
    missing   = []

    for band_name in bt:
        key = find_asset_key(assets, band_name)
        if key:
            band_urls.append('/vsicurl/' + resolve_href(assets[key]['href']))
            resolved.append(key)
        else:
            missing.append(band_name)

    # Reporta bandas ausentes / Report missing bands
    if missing:
        img_assets = [k for k, v in assets.items()
                      if v.get('type', '').startswith('image/') or
                      k.upper().startswith(('B', 'BAND', 'SR_'))]
        if progress_cb:
            progress_cb(
                '{}: bandas não encontradas [{}] | disponíveis: {} / '
                'bands not found [{}] | available: {}'.format(
                    scene_id,
                    ', '.join(missing), ', '.join(img_assets[:10]),
                    ', '.join(missing), ', '.join(img_assets[:10])),
                error=True)
        if not band_urls:
            return 0

    if progress_cb:
        progress_cb('{}: bandas → {} / bands → {}'.format(
            scene_id, ', '.join(resolved), ', '.join(resolved)))

    # ── Tenta composição de 3 bandas via VRT + Warp ──────────────────────────
    # Try 3-band composite via VRT + Warp
    if len(band_urls) == 3 and _gdal is not None:
        comp_label = '-'.join(labels)
        layer_name = '{} [{}]'.format(scene_id, comp_label)
        sid        = safe_id(scene_id)

        # VRT com as 3 bandas empilhadas (em disco para suportar o Warp VRT)
        # VRT with 3 stacked bands (on disk to support Warp VRT reference)
        raw_vrt   = os.path.join(tmp, 'rth_{}_bands_{}.vrt'.format(sid, composition_key))
        utm_vrt   = os.path.join(tmp, 'rth_{}_utm_{}.vrt'.format(sid, composition_key))

        if progress_cb:
            progress_cb('Criando composição {} para {} / Creating {} composite for {}...'.format(
                comp_label, scene_id, comp_label, scene_id))

        vrt_ds = _gdal.BuildVRT(raw_vrt, band_urls, separate=True)
        if vrt_ds:
            vrt_ds.FlushCache()
            del vrt_ds

            # Tenta Warp para o CRS regional / Try Warp to regional CRS
            if _warp_to_crs_vrt(raw_vrt, utm_vrt, _gdal, dst_srs):
                result = _add_layer(utm_vrt, layer_name, feature, apply_rgb_renderer, target_crs=utm_crs)
                if result:
                    return result

            # Fallback: usa VRT bruto + atribui CRS do item STAC / Fallback: raw VRT + assign CRS from STAC item
            if progress_cb:
                progress_cb('{}: warp falhou — VRT direto / warp failed — direct VRT'.format(scene_id))
            result = _add_layer(raw_vrt, layer_name, feature, apply_rgb_renderer)
            if result:
                return result

    # ── Fallback: carrega bandas separadamente ───────────────────────────────
    # Fallback: load bands separately
    if not band_urls:
        return 0

    if _gdal is None and progress_cb:
        progress_cb('GDAL indisponível — bandas separadas / GDAL unavailable — separate bands')

    count = 0
    for url, lbl, rkey in zip(band_urls, labels, resolved):
        name    = '{} — {} ({})'.format(scene_id, rkey, lbl)
        sid     = safe_id(scene_id)
        utm_vrt = os.path.join(tmp, 'rth_{}_{}_{}.vrt'.format(sid, safe_id(rkey), lbl))

        if _gdal and _warp_to_crs_vrt(url, utm_vrt, _gdal, dst_srs):
            count += _add_layer(utm_vrt, name, feature, apply_stretch, target_crs=utm_crs)
        else:
            count += _add_layer(url, name, feature, apply_stretch)
    return count


def _load_first_image(feature, scene_id, assets, _gdal, tmp, dst_srs, utm_crs):
    """Sem mapeamento de bandas: carrega o primeiro asset de imagem disponível no CRS regional / No band mapping: load first available image asset in regional CRS.

    :param dst_srs: string do CRS de destino regional / regional target CRS string
    :param utm_crs: objeto QgsCoordinateReferenceSystem do CRS regional / regional QgsCoordinateReferenceSystem object
    :returns: 1 se a camada for carregada com sucesso, 0 caso contrário / 1 if loaded successfully, 0 otherwise
    :rtype: int
    """
    for asset_name, asset_data in assets.items():
        if asset_data.get('type', '').startswith('image/'):
            url     = '/vsicurl/' + resolve_href(asset_data['href'])
            name    = '{} — {}'.format(scene_id, asset_name)
            utm_vrt = os.path.join(tmp, 'rth_{}_{}.vrt'.format(safe_id(scene_id), safe_id(asset_name)))

            if _gdal and _warp_to_crs_vrt(url, utm_vrt, _gdal, dst_srs):
                return _add_layer(utm_vrt, name, feature, apply_stretch, target_crs=utm_crs)
            else:
                return _add_layer(url, name, feature, apply_stretch)
    return 0
