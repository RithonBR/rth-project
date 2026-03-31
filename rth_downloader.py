# -*- coding: utf-8 -*-
"""
rth_downloader — Download de composição STAC como GeoTIFF no datum UTM regional via gdal.Warp em background
rth_downloader — STAC composite download as GeoTIFF in regional UTM datum via gdal.Warp in background

Estratégia / Strategy:
  - gdal.Warp faz streaming: lê as bandas remotas via vsicurl e grava progressivamente no disco
  - gdal.Warp does streaming: reads remote bands via vsicurl and writes progressively to disk
  - O CRS de saída é o datum UTM regional detectado pelo bbox da cena
  - The output CRS is the regional UTM datum detected from the scene bbox
  - Sem carregar tudo na RAM / Without loading everything into RAM
  - Progresso real via callback do GDAL / Real progress via GDAL callback
  - Cancelamento limpo via callback / Clean cancellation via callback

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Biblioteca padrão para caminhos / Standard library for paths
import os

# Thread do Qt para execução em background / Qt thread for background execution
from qgis.PyQt.QtCore import QThread, pyqtSignal

# Módulos QGIS para camadas e projeto / QGIS modules for layers and project
from qgis.core import QgsRasterLayer, QgsProject, QgsCoordinateReferenceSystem

# Importa catálogo de bandas / Import band catalog
from rth_catalog import get_band_tuple
# Importa resolução de bandas / Import band resolution
from rth_band_resolver import find_asset_key
# Importa assinatura de URLs / Import URL signing
from rth_pc_auth import resolve_href
# Importa utilitários de camada / Import layer utilities
from rth_layer_utils import assign_crs_from_bbox, apply_rgb_renderer, apply_stretch, safe_id
# Importa detecção de datum UTM regional / Import regional UTM datum detection
from rth_utm_utils import detect_regional_utm


def _scene_dst_srs(feature):
    """Detecta a string do CRS de saída a partir do bbox do item STAC / Detect output CRS string from STAC item bbox.

    :param feature: item STAC com campo 'bbox' / STAC item with 'bbox' field
    :returns: string do CRS de destino, ex: 'EPSG:31982' / target CRS string, e.g. 'EPSG:31982'
    :rtype: str
    """
    bbox = feature.get('bbox', [])
    if len(bbox) >= 4:
        # Centroide do bbox para detecção da região / Bbox centroid for region detection
        lon = (bbox[0] + bbox[2]) / 2.0
        lat = (bbox[1] + bbox[3]) / 2.0
        # Detecta datum e EPSG regional / Detect regional datum and EPSG
        epsg, _, _, _ = detect_regional_utm(lon, lat)
        return 'EPSG:{}'.format(epsg)
    # Fallback para WGS84 se bbox ausente / Fallback to WGS84 if bbox is missing
    return 'EPSG:4326'


# ── Inicialização do GDAL ─────────────────────────────────────────────────────

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
    _gdal.SetConfigOption('GDAL_HTTP_TIMEOUT',            '60')   # Timeout maior para download / Larger timeout for download
    _gdal.SetConfigOption('CPL_VSIL_CURL_USE_CACHE',      'YES')
    _gdal.SetConfigOption('CPL_VSIL_CURL_CACHE_SIZE',     '128000000')
    _gdal.SetConfigOption('GDAL_DISABLE_READDIR_ON_OPEN', 'EMPTY_DIR')
    return _gdal


# ── Callback de progresso do GDAL ─────────────────────────────────────────────

def _make_gdal_progress(scene_id, progress_cb, cancelled_ref):
    """Fábrica de callback de progresso integrado ao Qt e cancelamento / Factory of progress callback integrated with Qt and cancellation.

    O GDAL chama esta função durante o Warp — retornar 0 aborta a operação.
    GDAL calls this function during Warp — returning 0 aborts the operation.

    :param scene_id: ID da cena para o label / scene ID for label
    :param progress_cb: callable(msg, error) para emitir progresso / callable to emit progress
    :param cancelled_ref: lista [bool] — True aborta o Warp / list [bool] — True aborts Warp
    :returns: função de callback compatível com GDAL / GDAL-compatible callback function
    :rtype: callable
    """
    last_pct = [0]  # Closure para evitar emissões redundantes / Closure to avoid redundant emissions

    def _callback(complete, message, cb_data):
        # Cancelamento solicitado: retorna 0 para abortar o Warp / Cancellation requested: return 0 to abort Warp
        if cancelled_ref[0]:
            return 0
        pct = int(complete * 100)
        # Emite apenas a cada 5% para não sobrecarregar o UI / Emit only every 5% to not overload UI
        if pct != last_pct[0] and pct % 5 == 0:
            last_pct[0] = pct
            progress_cb('{}: {}%'.format(scene_id, pct), False)
        return 1  # Retorna 1 para continuar / Return 1 to continue

    return _callback


# ── Download principal via gdal.Warp ──────────────────────────────────────────

def _warp_to_geotiff(src, out_path, scene_id, comp_label, dst_srs, _gdal, progress_cb, cancelled_ref):
    """Reprojeita src para o CRS regional e grava como GeoTIFF comprimido / Reproject src to regional CRS and write as compressed GeoTIFF.

    Usa streaming — não carrega todo o dado na RAM de uma vez.
    Uses streaming — does not load all data into RAM at once.

    :param src: URL vsicurl, caminho VRT em disco ou vsimem / vsicurl URL, disk VRT or vsimem path
    :param out_path: caminho do GeoTIFF de saída / output GeoTIFF path
    :param scene_id: ID da cena para log / scene ID for logging
    :param comp_label: rótulo da composição para o nome da camada / composition label for layer name
    :param dst_srs: string do CRS de destino, ex: 'EPSG:31982' / target CRS string, e.g. 'EPSG:31982'
    :param _gdal: módulo gdal / gdal module
    :param progress_cb: callable(msg, error) / progress callable
    :param cancelled_ref: lista [bool] para sinalizar cancelamento / list [bool] for cancellation signal
    :returns: (out_path, layer_name) ou None / (out_path, layer_name) or None
    :rtype: tuple[str, str] | None
    """
    if _gdal is None:
        return None

    progress_cb('{}: iniciando composição {} / starting {} composite...'.format(
        scene_id, dst_srs, dst_srs), False)

    opts = _gdal.WarpOptions(
        format='GTiff',
        dstSRS=dst_srs,                                               # Datum UTM regional detectado / Detected regional UTM datum
        creationOptions=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=IF_SAFER'],  # GeoTIFF eficiente / Efficient GeoTIFF
        multithread=True,                                             # Múltiplos threads HTTP / Multiple HTTP threads
        callback=_make_gdal_progress(scene_id, progress_cb, cancelled_ref),
    )

    try:
        ds = _gdal.Warp(out_path, src, options=opts)
    except Exception as exc:
        progress_cb('{}: erro — {} / error — {}'.format(scene_id, exc, exc), True)
        return None

    if cancelled_ref[0] or ds is None:
        # Remove arquivo parcial se cancelado / Remove partial file if cancelled
        if os.path.isfile(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
        progress_cb('{}: cancelado / cancelled'.format(scene_id), False)
        return None

    ds.FlushCache()
    del ds
    progress_cb('{}: 100% — concluído ({}) / complete ({})'.format(
        scene_id, dst_srs, dst_srs), False)
    return (out_path, '{} [{}]'.format(scene_id, comp_label))


# ── Resolução da fonte de composição por cena ─────────────────────────────────

def _resolve_scene_source(scene_id, assets, collection_id, composition_key, band_tuple, _gdal):
    """Resolve a URL ou VRT vsimem que será entrada do Warp / Resolve URL or vsimem VRT as Warp input.

    Prioridade / Priority:
    1. PAN: URL direta do asset pancromático / PAN: direct URL of panchromatic asset
    2. TCI/visual (RGB pronto, 1 arquivo) / TCI/visual (ready RGB, 1 file)
    3. VRT vsimem empilhando as 3 bandas remotas / vsimem VRT stacking 3 remote bands
    4. Primeiro asset de imagem disponível / First available image asset

    :returns: (src, comp_label, vsimem_or_None) / (src, comp_label, vsimem_to_cleanup)
    :rtype: tuple[str, str, str | None] | None
    """
    # 1. Asset de banda única: PAN, EVI, NDVI / Single-band asset: PAN, EVI, NDVI
    if composition_key in ('PAN', 'EVI', 'NDVI'):
        asset_band = band_tuple if isinstance(band_tuple, str) else (
            get_band_tuple(collection_id, composition_key) if not band_tuple else None)
        asset_key = find_asset_key(assets, asset_band) if asset_band else None
        if asset_key:
            url = '/vsicurl/' + resolve_href(assets[asset_key]['href'])
            return (url, composition_key, None)
        return None

    # 2. Preview RGB pronto (TCI ou visual) / Ready RGB preview (TCI or visual)
    if composition_key == 'RGB':
        preview_key = next((k for k in ('TCI', 'visual') if k in assets), None)
        if preview_key:
            url = '/vsicurl/' + resolve_href(assets[preview_key]['href'])
            return (url, 'RGB', None)

    if _gdal is not None:
        bt = band_tuple or get_band_tuple(collection_id, composition_key)

        # 3. Bandas individuais → VRT vsimem empilhado / Individual bands → stacked vsimem VRT
        if composition_key == 'NIR_SWIR_RED':
            labels = ('NIR', 'SWIR', 'RED')
        elif composition_key == 'RED_NIR_BLUE':
            labels = ('RED', 'NIR', 'BLUE')
        elif composition_key == 'RED_NIR_GREEN':
            labels = ('RED', 'NIR', 'GREEN')
        else:
            labels = ('R', 'G', 'B')

        if bt:
            band_urls = []
            for band_name in bt:
                key = find_asset_key(assets, band_name)
                if key:
                    band_urls.append('/vsicurl/' + resolve_href(assets[key]['href']))

            if len(band_urls) == 3:
                # VRT em memória virtual — nenhum dado é baixado aqui / Virtual memory VRT — no data downloaded here
                vsimem = '/vsimem/rth_dl_{}.vrt'.format(safe_id(scene_id))
                vrt_ds = _gdal.BuildVRT(vsimem, band_urls, separate=True)
                if vrt_ds:
                    vrt_ds.FlushCache()
                    del vrt_ds
                    return (vsimem, '-'.join(labels), vsimem)

    # 4. Fallback: primeiro asset de imagem / Fallback: first image asset
    for asset_name, asset_data in assets.items():
        if asset_data.get('type', '').startswith('image/'):
            url = '/vsicurl/' + resolve_href(asset_data['href'])
            return (url, asset_name, None)

    return None


# ── Thread de download em background ─────────────────────────────────────────

class DownloadThread(QThread):
    """Executa o download de composições STAC em thread de background / Executes STAC composite download in background thread.

    Usa gdal.Warp para montar a composição e gravar como GeoTIFF no datum UTM regional.
    Uses gdal.Warp to assemble the composite and write as GeoTIFF in regional UTM datum.

    O addMapLayer é emitido via sinal para executar na thread principal.
    addMapLayer is emitted via signal to execute on the main thread.
    """

    # Mensagem de progresso (msg, is_error) / Progress message (msg, is_error)
    progress_sig = pyqtSignal(str, bool)
    # Progresso numérico (cena atual, total de cenas) / Numeric progress (current scene, total scenes)
    count_sig    = pyqtSignal(int, int)
    # Arquivo pronto para carregar na thread principal: (path, name, feature_dict)
    # File ready to load on main thread: (path, name, feature_dict)
    layer_ready  = pyqtSignal(str, str, object)
    # Total de arquivos criados ao finalizar / Total files created on finish
    finished_sig = pyqtSignal(int)

    def __init__(self, features, collection_id, composition_key, output_dir, band_tuple=None):
        """
        :param features: lista de features GeoJSON / list of GeoJSON features
        :param collection_id: ID da coleção STAC / STAC collection ID
        :param composition_key: 'RGB', 'NIR_SWIR_RED' ou 'RED_NIR_BLUE'
        :param output_dir: pasta de destino dos arquivos / output folder for files
        :param band_tuple: tupla de bandas override ou None / band tuple override or None
        """
        super().__init__()
        self._features        = features
        self._collection_id   = collection_id
        self._composition_key = composition_key
        self._output_dir      = output_dir
        self._band_tuple      = band_tuple
        # Referência mutável para cancelamento — compartilhada com o callback GDAL /
        # Mutable reference for cancellation — shared with GDAL callback
        self._cancelled_ref   = [False]

    def cancel(self):
        """Sinaliza cancelamento — o Warp em andamento aborta no próximo tick do callback / Signal cancellation — in-progress Warp aborts on next callback tick."""
        self._cancelled_ref[0] = True

    def run(self):
        """Executa em thread de background — não chamar diretamente / Runs in background thread — do not call directly."""
        _gdal   = _init_gdal()
        total   = len(self._features)
        created = 0

        for idx, feature in enumerate(self._features):
            if self._cancelled_ref[0]:
                break

            assets   = feature.get('assets', {})
            scene_id = feature.get('id', 'scene')
            comp_key = self._composition_key
            sid      = safe_id(scene_id)

            # ── Detecta o CRS de saída regional para esta cena / Detect regional output CRS for this scene ──
            dst_srs = _scene_dst_srs(feature)

            # ── Composição MS (3 bandas) ──────────────────────────────────────
            # MS composite (3 bands)
            out_name = '{}_{}.tif'.format(sid, comp_key)
            out_path = os.path.join(self._output_dir, out_name)

            if os.path.isfile(out_path):
                # Pula se já existe / Skip if already exists
                self.progress_sig.emit(
                    '{}: já existe / already exists — {}'.format(scene_id, out_name), False)
                self.layer_ready.emit(out_path, '{} [{}]'.format(scene_id, comp_key), feature)
                created += 1
            else:
                resolved = _resolve_scene_source(
                    scene_id, assets, self._collection_id,
                    comp_key, self._band_tuple, _gdal)

                if resolved is None:
                    self.progress_sig.emit(
                        '{}: sem assets de imagem / no image assets'.format(scene_id), True)
                    self.count_sig.emit(idx + 1, total)
                    continue

                src, comp_label, vsimem_to_cleanup = resolved

                # Warp → GeoTIFF no CRS regional / Warp → GeoTIFF in regional CRS
                result = _warp_to_geotiff(
                    src, out_path, scene_id, comp_label, dst_srs,
                    _gdal, self.progress_sig.emit, self._cancelled_ref)

                # Limpa VRT intermediário / Clean up intermediate VRT
                if vsimem_to_cleanup and _gdal is not None:
                    try:
                        _gdal.Unlink(vsimem_to_cleanup)
                    except Exception:
                        pass

                if result is not None:
                    path, layer_name = result
                    created += 1
                    self.layer_ready.emit(path, layer_name, feature)

            self.count_sig.emit(idx + 1, total)

        self.finished_sig.emit(created)
