# -*- coding: utf-8 -*-
"""
Fontes de dados e thread de download do RTH DEM Downloader
Data sources and download thread for RTH DEM Downloader

Responsabilidades / Responsibilities:
  - Busca de tiles INPE via STAC API / INPE tile search via STAC API
  - Geração de grade de tiles Copernicus / Copernicus tile grid generation
  - Virtualização com reprojection UTM regional via GDAL / Virtualization with regional UTM reprojection via GDAL
  - Thread de download assíncrono com reprojection UTM regional / Async download thread with regional UTM reprojection

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Biblioteca padrão para caminhos de arquivo / Standard library for file paths
import os
# Biblioteca padrão para pasta temporária / Standard library for temp folder
import tempfile
# Biblioteca padrão para funções matemáticas (floor de coordenadas) / Standard library for math (coordinate floor)
import math
# Biblioteca padrão para requisições HTTP / Standard library for HTTP requests
import urllib.request
# Biblioteca padrão para parse de JSON / Standard library for JSON parsing
import json

# QThread e pyqtSignal para download assíncrono / QThread and pyqtSignal for async download
from qgis.PyQt.QtCore import QThread, pyqtSignal

# Módulos QGIS para camadas e projeto / QGIS modules for layers and project
from qgis.core import QgsRasterLayer, QgsProject, QgsCoordinateReferenceSystem

# Importa as constantes do módulo de constantes / Import constants from constants module
from tool_dem_constants import STAC_COLLECTION_URL, COPERNICUS_BASE_URL, COPERNICUS_BASE_URL_90M


# ──────────────────────────────────────────────────────────────────────────────
# Inicialização do GDAL / GDAL initialization
# ──────────────────────────────────────────────────────────────────────────────

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
    _gdal.SetConfigOption('GDAL_HTTP_UNSAFESSL',          'YES')
    _gdal.SetConfigOption('GDAL_HTTP_TIMEOUT',            '60')
    _gdal.SetConfigOption('CPL_VSIL_CURL_USE_CACHE',      'YES')
    _gdal.SetConfigOption('CPL_VSIL_CURL_CACHE_SIZE',     '128000000')
    _gdal.SetConfigOption('GDAL_DISABLE_READDIR_ON_OPEN', 'EMPTY_DIR')
    return _gdal


# ──────────────────────────────────────────────────────────────────────────────
# Busca INPE via STAC / INPE search via STAC
# ──────────────────────────────────────────────────────────────────────────────

def search_topodata_items(bbox_wgs84, asset_key, max_items=200):
    """
    Busca os itens Topodata via STAC API para o bounding box fornecido.
    Searches Topodata items via STAC API for the given bounding box.

    Parâmetros / Parameters:
        bbox_wgs84 : QgsRectangle em WGS84 / QgsRectangle in WGS84
        asset_key  : código do asset (ex: 'ZN', 'SN') / asset code (e.g. 'ZN', 'SN')
        max_items  : limite de itens retornados / item return limit

    Retorna / Returns:
        list of (item_id: str, asset_href: str)
    """
    # Monta o parâmetro bbox: min_lon,min_lat,max_lon,max_lat / Build bbox param: min_lon,min_lat,max_lon,max_lat
    bbox_str = '{},{},{},{}'.format(
        bbox_wgs84.xMinimum(),
        bbox_wgs84.yMinimum(),
        bbox_wgs84.xMaximum(),
        bbox_wgs84.yMaximum()
    )
    # Monta a URL de busca com bbox e limite / Build search URL with bbox and limit
    url = '{}?bbox={}&limit={}'.format(STAC_COLLECTION_URL, bbox_str, max_items)

    # Faz a requisição HTTP com timeout de 30s / Make HTTP request with 30s timeout
    req = urllib.request.Request(url, headers={'User-Agent': 'RTH-Plugin/1.0'})
    if not req.full_url.startswith(('https://', 'http://')):
        raise ValueError('URL scheme not permitted: {}'.format(req.full_url))
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
        # Decodifica o corpo JSON da resposta / Decode the JSON response body
        data = json.loads(resp.read().decode('utf-8'))

    # Extrai os pares (id, href) para o asset solicitado / Extract (id, href) pairs for the requested asset
    results = []
    for feature in data.get('features', []):
        # ID do tile / Tile ID
        item_id = feature.get('id', '')
        # Dicionário de assets do item / Item assets dictionary
        assets = feature.get('assets', {})
        # Verifica se o asset solicitado existe no item / Check if requested asset exists in the item
        if asset_key in assets:
            href = assets[asset_key].get('href', '')
            if href:
                results.append((item_id, href))

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Grade de tiles Copernicus / Copernicus tile grid
# ──────────────────────────────────────────────────────────────────────────────

def get_copernicus_items(bbox_wgs84):
    """
    Gera os tiles Copernicus DEM 30m para o bounding box a partir da grade 1°×1°.
    Generates Copernicus DEM 30m tiles for the bounding box from the 1°×1° grid.

    Os tiles são COG (Cloud Optimized GeoTIFF) hospedados em S3 público.
    Tiles are COG (Cloud Optimized GeoTIFF) hosted on a public S3 bucket.

    Parâmetros / Parameters:
        bbox_wgs84 : QgsRectangle em WGS84 / QgsRectangle in WGS84

    Retorna / Returns:
        list of (tile_id: str, tile_url: str)
    """
    results = []

    # Limites inteiros da grade (floor do canto SW de cada célula 1°×1°) / Integer grid bounds (floor of SW corner)
    lat_start = int(math.floor(bbox_wgs84.yMinimum()))
    lat_end   = int(math.floor(bbox_wgs84.yMaximum()))
    lon_start = int(math.floor(bbox_wgs84.xMinimum()))
    lon_end   = int(math.floor(bbox_wgs84.xMaximum()))

    # Itera por cada célula 1°×1° que intersecta o bbox / Iterate each 1°×1° cell intersecting the bbox
    for lat in range(lat_start, lat_end + 1):
        for lon in range(lon_start, lon_end + 1):
            ns      = 'N' if lat >= 0 else 'S'
            ew      = 'E' if lon >= 0 else 'W'
            lat_abs = abs(lat)
            lon_abs = abs(lon)
            tile_name = 'Copernicus_DSM_COG_10_{}{:02d}_00_{}{:03d}_00_DEM'.format(
                ns, lat_abs, ew, lon_abs)
            tile_url = '{}/{}/{}.tif'.format(COPERNICUS_BASE_URL, tile_name, tile_name)
            tile_id  = '{}{:02d}{}{:03d}'.format(ns, lat_abs, ew, lon_abs)
            results.append((tile_id, tile_url))

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Grade de tiles Copernicus 90m / Copernicus 90m tile grid
# ──────────────────────────────────────────────────────────────────────────────

def get_copernicus_90m_items(bbox_wgs84):
    """
    Gera os tiles Copernicus DEM 90m para o bounding box a partir da grade 1°×1°.
    Generates Copernicus DEM 90m tiles for the bounding box from the 1°×1° grid.

    Parâmetros / Parameters:
        bbox_wgs84 : QgsRectangle em WGS84 / QgsRectangle in WGS84

    Retorna / Returns:
        list of (tile_id: str, tile_url: str)
    """
    results = []

    lat_start = int(math.floor(bbox_wgs84.yMinimum()))
    lat_end   = int(math.floor(bbox_wgs84.yMaximum()))
    lon_start = int(math.floor(bbox_wgs84.xMinimum()))
    lon_end   = int(math.floor(bbox_wgs84.xMaximum()))

    for lat in range(lat_start, lat_end + 1):
        for lon in range(lon_start, lon_end + 1):
            ns      = 'N' if lat >= 0 else 'S'
            ew      = 'E' if lon >= 0 else 'W'
            lat_abs = abs(lat)
            lon_abs = abs(lon)
            # Código COG_30 = 3 arco-segundos (~90 m) / Code COG_30 = 3 arc-seconds (~90 m)
            tile_name = 'Copernicus_DSM_COG_30_{}{:02d}_00_{}{:03d}_00_DEM'.format(
                ns, lat_abs, ew, lon_abs)
            tile_url = '{}/{}/{}.tif'.format(COPERNICUS_BASE_URL_90M, tile_name, tile_name)
            tile_id  = '{}{:02d}{}{:03d}'.format(ns, lat_abs, ew, lon_abs)
            results.append((tile_id, tile_url))

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Virtualização com reprojection UTM regional / Virtualization with regional UTM reprojection
# ──────────────────────────────────────────────────────────────────────────────

def _bbox_to_output_bounds(bbox_wgs84, dst_srs_str):
    """Projeta um QgsRectangle WGS84 para o CRS de destino e retorna como tupla GDAL outputBounds.
    Projects a WGS84 QgsRectangle to the destination CRS and returns as GDAL outputBounds tuple.

    :param bbox_wgs84: QgsRectangle em WGS84 / QgsRectangle in WGS84
    :param dst_srs_str: string do CRS de destino, ex: 'EPSG:31982' / target CRS string
    :returns: (xmin, ymin, xmax, ymax) no CRS de destino / in destination CRS
    :rtype: tuple[float, float, float, float]
    """
    from qgis.core import QgsCoordinateTransform
    src_crs = QgsCoordinateReferenceSystem('EPSG:4326')
    dst_crs = QgsCoordinateReferenceSystem(dst_srs_str)
    if src_crs.authid() == dst_crs.authid():
        return (bbox_wgs84.xMinimum(), bbox_wgs84.yMinimum(),
                bbox_wgs84.xMaximum(), bbox_wgs84.yMaximum())
    t = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
    projected = t.transformBoundingBox(bbox_wgs84)
    return (projected.xMinimum(), projected.yMinimum(),
            projected.xMaximum(), projected.yMaximum())


def virtualize_dem_items(items, dst_srs, clip_bbox=None):
    """Virtualiza tiles DEM reprojetando para o datum UTM regional via GDAL Warp VRT / Virtualize DEM tiles reprojecting to regional UTM datum via GDAL Warp VRT.

    Tenta reprojetar via GDAL Warp + VRT virtual (sem download).
    Tries to reproject via GDAL Warp + virtual VRT (no download).
    Fallback: carrega direto via /vsicurl/ sem reprojection / Fallback: loads directly via /vsicurl/ without reprojection.

    :param items: lista de (item_id, href) / list of (item_id, href)
    :param dst_srs: string do CRS de destino, ex: 'EPSG:31982' / target CRS string, e.g. 'EPSG:31982'
    :param clip_bbox: QgsRectangle WGS84 para recorte, ou None para cena completa / WGS84 clip bbox, or None for full scene
    :returns: número de tiles carregados / number of tiles loaded
    :rtype: int
    """
    _gdal   = _init_gdal()
    tmp     = tempfile.gettempdir()
    # CRS UTM regional para atribuir à camada / Regional UTM CRS to assign to the layer
    utm_crs = QgsCoordinateReferenceSystem(dst_srs)
    # Projeta o bbox de recorte para o CRS de destino (se fornecido) / Project clip bbox to dst CRS (if provided)
    output_bounds = _bbox_to_output_bounds(clip_bbox, dst_srs) if clip_bbox is not None else None
    loaded  = 0

    for item_id, href in items:
        # Fonte via vsicurl (sem download) / Source via vsicurl (no download)
        src = '/vsicurl/' + href
        # Nome seguro para o arquivo VRT temporário / Safe name for temporary VRT file
        safe = item_id.replace('/', '_').replace('\\', '_')
        vrt_path = os.path.join(tmp, 'rth_dem_{}.vrt'.format(safe))

        if _gdal is not None:
            # Tenta criar VRT reprojetado no CRS regional / Try creating VRT reprojected to regional CRS
            try:
                warp_kwargs = dict(
                    format='VRT',
                    dstSRS=dst_srs,    # Datum UTM regional detectado / Detected regional UTM datum
                    multithread=True,
                )
                # Adiciona recorte se solicitado / Add clipping if requested
                if output_bounds is not None:
                    warp_kwargs['outputBounds'] = output_bounds
                opts = _gdal.WarpOptions(**warp_kwargs)
                ds = _gdal.Warp(vrt_path, src, options=opts)
                if ds:
                    ds.FlushCache()
                    del ds
                    # Carrega o VRT reprojetado / Load the reprojected VRT
                    rl = QgsRasterLayer(vrt_path, item_id)
                    if rl.isValid():
                        # Atribui o CRS regional / Assign the regional CRS
                        rl.setCrs(utm_crs)
                        QgsProject.instance().addMapLayer(rl)
                        loaded += 1
                        continue
            except Exception:
                pass

        # Fallback: carrega direto sem reprojection / Fallback: load directly without reprojection
        rl = QgsRasterLayer(src, item_id)
        if rl.isValid():
            QgsProject.instance().addMapLayer(rl)
            loaded += 1

    return loaded


# ──────────────────────────────────────────────────────────────────────────────
# Thread de download / Download thread
# ──────────────────────────────────────────────────────────────────────────────

class DownloadThread(QThread):
    """Thread de download assíncrono com reprojection UTM regional / Async download thread with regional UTM reprojection."""

    # Sinal de progresso: (índice atual, total, nome do arquivo) / Progress signal: (current index, total, filename)
    progress = pyqtSignal(int, int, str)
    # Sinal emitido ao concluir com a lista de caminhos baixados / Signal emitted on completion with downloaded paths
    finished = pyqtSignal(list)
    # Sinal de erro com mensagem / Error signal with message
    error = pyqtSignal(str)

    def __init__(self, items, output_dir, dst_srs='EPSG:4326', clip_bbox=None):
        """
        Inicializa a thread / Initialize thread.

        items      : list of (item_id: str, href: str)
        output_dir : str            — pasta de destino / destination folder
        dst_srs    : str            — CRS de destino regional, ex: 'EPSG:31982' / regional target CRS
        clip_bbox  : QgsRectangle   — bbox WGS84 para recorte, ou None para cena completa / WGS84 clip bbox or None
        """
        super().__init__()
        # Lista de itens a baixar / Items to download
        self._items = items
        # Diretório de saída / Output directory
        self._output_dir = output_dir
        # CRS de destino para reprojection / Target CRS for reprojection
        self._dst_srs = dst_srs
        # Bounds de recorte projetados para o dst_srs (None = cena completa) / Clip bounds in dst_srs (None = full scene)
        self._output_bounds = _bbox_to_output_bounds(clip_bbox, dst_srs) if clip_bbox is not None else None
        # Flag de cancelamento / Cancellation flag
        self._cancelled = False

    def cancel(self):
        """Sinaliza a thread para cancelar o download / Signal the thread to cancel download."""
        self._cancelled = True

    def run(self):
        """Loop principal de download com reprojection UTM / Main download loop with UTM reprojection."""
        # Inicializa GDAL para reprojection via Warp / Initialize GDAL for reprojection via Warp
        _gdal      = _init_gdal()
        downloaded = []
        total      = len(self._items)

        for idx, (item_id, href) in enumerate(self._items):
            # Interrompe se cancelado / Stop if cancelled
            if self._cancelled:
                break

            # Nome do arquivo de saída / Output filename
            filename = os.path.basename(href)
            # Notifica o progresso / Notify progress
            self.progress.emit(idx + 1, total, filename)

            # Caminho completo de saída / Full output path
            out_path = os.path.join(self._output_dir, filename)

            if _gdal is not None:
                # ── Tenta GDAL Warp: vsicurl → GeoTIFF reprojetado ──────────────
                # Try GDAL Warp: vsicurl → reprojected GeoTIFF
                src = '/vsicurl/' + href
                try:
                    warp_kwargs = dict(
                        format='GTiff',
                        dstSRS=self._dst_srs,   # Datum UTM regional / Regional UTM datum
                        creationOptions=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=IF_SAFER'],
                        multithread=True,
                    )
                    # Adiciona recorte se solicitado / Add clipping if requested
                    if self._output_bounds is not None:
                        warp_kwargs['outputBounds'] = self._output_bounds
                    opts = _gdal.WarpOptions(**warp_kwargs)
                    ds = _gdal.Warp(out_path, src, options=opts)
                    if ds:
                        ds.FlushCache()
                        del ds
                        downloaded.append(out_path)
                        continue
                except Exception as e:
                    # Registra o erro e cai no fallback urllib / Log error and fall through to urllib fallback
                    self.error.emit('Warp falhou / Warp failed {}: {}'.format(item_id, str(e)))

            # ── Fallback: download direto via urllib (sem reprojection) ──────
            # Fallback: direct download via urllib (no reprojection)
            try:
                req = urllib.request.Request(href, headers={'User-Agent': 'RTH-Plugin/1.0'})
                if not req.full_url.startswith(('https://', 'http://')):
                    raise ValueError('URL scheme not permitted: {}'.format(req.full_url))
                # Timeout de 120s para arquivos grandes / 120s timeout for large files
                with urllib.request.urlopen(req, timeout=120) as resp:  # nosec B310
                    data = resp.read()
                # Grava o arquivo em disco / Write file to disk
                with open(out_path, 'wb') as f:
                    f.write(data)
                downloaded.append(out_path)
            except Exception as e:
                self.error.emit('Erro em {} / Error on {}: {}'.format(filename, filename, str(e)))

        # Notifica conclusão com a lista de arquivos / Notify completion with files list
        self.finished.emit(downloaded)
