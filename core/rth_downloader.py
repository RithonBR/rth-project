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
from .rth_catalog import get_band_tuple
# Importa resolução de bandas / Import band resolution
from .rth_band_resolver import find_asset_key
# Importa assinatura de URLs / Import URL signing
from .rth_pc_auth import resolve_href
# Importa utilitários de camada / Import layer utilities
from .rth_layer_utils import assign_crs_from_bbox, apply_rgb_renderer, apply_stretch, safe_id
# Importa detecção de datum UTM regional / Import regional UTM datum detection
from .rth_utm_utils import detect_regional_utm


# Mapeamento de chave STAC → nome curto de banda / STAC key → short band name mapping
_BAND_SHORT = {
    'B01': 'Coastal',   'B02': 'Blue',      'B03': 'Green',
    'B04': 'Red',       'B05': 'RedEdge-1', 'B06': 'RedEdge-2',
    'B07': 'RedEdge-3', 'B08': 'NIR',       'B8A': 'NIR-n',
    'B09': 'WV',        'B11': 'SWIR-1',    'B12': 'SWIR-2',
    # Landsat OLI / outros / other sensors
    'SR_B1': 'Coastal', 'SR_B2': 'Blue', 'SR_B3': 'Green',
    'SR_B4': 'Red',     'SR_B5': 'NIR',  'SR_B6': 'SWIR-1', 'SR_B7': 'SWIR-2',
}


def _band_lbl(name):
    """Formata banda para rótulo legível: 'NIR (B08)'.

    Aceita: str com chave STAC ('B08'), str semântica ('NIR'),
    ou tupla ('NIR', 'B08') (usada pelo Smart Download).
    Accepts: STAC key str ('B08'), semantic str ('NIR'),
    or tuple ('NIR', 'B08') (used by Smart Download).
    """
    if isinstance(name, tuple) and len(name) == 2:
        return '{} ({})'.format(name[0], name[1])
    short = _BAND_SHORT.get(name, '')
    if short:
        return '{} ({})'.format(short, name)
    return name


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


def _bbox_wgs84_to_crs(bbox_wgs84, dst_srs_str):
    """Reprojecta bbox WGS84 para o CRS de destino usando OSR / Reproject WGS84 bbox to destination CRS using OSR.

    Usado para converter clip_bbox (WGS84) em outputBounds para gdal.Warp
    (que exige as coordenadas no CRS de saída).
    Used to convert clip_bbox (WGS84) into outputBounds for gdal.Warp
    (which requires coordinates in the output CRS).

    :param bbox_wgs84: [minX, minY, maxX, maxY] em WGS84 / in WGS84
    :param dst_srs_str: string do CRS de destino, ex: 'EPSG:31982' / target CRS string
    :returns: (minX, minY, maxX, maxY) no CRS de destino ou None se falhar /
              (minX, minY, maxX, maxY) in target CRS or None on failure
    :rtype: tuple | None
    """
    try:
        from osgeo import osr
        src_sr = osr.SpatialReference()
        src_sr.ImportFromEPSG(4326)
        try:
            src_sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        except AttributeError:  # nosec B110
            pass
        dst_sr = osr.SpatialReference()
        dst_sr.SetFromUserInput(dst_srs_str)
        try:
            dst_sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        except AttributeError:  # nosec B110
            pass
        ct      = osr.CoordinateTransformation(src_sr, dst_sr)
        minX, minY, maxX, maxY = bbox_wgs84
        corners = [ct.TransformPoint(x, y) for x, y in [
            (minX, minY), (maxX, minY), (minX, maxY), (maxX, maxY)]]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return (min(xs), min(ys), max(xs), max(ys))
    except Exception:
        return None


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

    # Thread-local: afeta só esta thread de download, não a thread de render do QGIS.
    # SetConfigOption (global) alterava o GDAL do QGIS inteiro → travadas no render.
    # Thread-local: affects only this download thread, not QGIS render thread.
    # SetConfigOption (global) was changing QGIS-wide GDAL → render freezes.
    _gdal.SetThreadLocalConfigOption('GDAL_HTTP_UNSAFESSL',          'YES')
    _gdal.SetThreadLocalConfigOption('GDAL_HTTP_TIMEOUT',            '60')
    _gdal.SetThreadLocalConfigOption('CPL_VSIL_CURL_USE_CACHE',      'YES')
    _gdal.SetThreadLocalConfigOption('GDAL_DISABLE_READDIR_ON_OPEN', 'EMPTY_DIR')
    # CPL_VSIL_CURL_CACHE_SIZE é um recurso de processo — não tem versão thread-local.
    # CPL_VSIL_CURL_CACHE_SIZE is a process-level resource — no thread-local equivalent.
    _gdal.SetConfigOption('CPL_VSIL_CURL_CACHE_SIZE', '128000000')
    return _gdal


# ── Callback de progresso do GDAL ─────────────────────────────────────────────

def _make_gdal_progress(scene_id, progress_cb, cancelled_ref, pct_cb=None):
    """Fábrica de callback de progresso integrado ao Qt e cancelamento / Factory of progress callback integrated with Qt and cancellation.

    O GDAL chama esta função durante o Warp — retornar 0 aborta a operação.
    GDAL calls this function during Warp — returning 0 aborts the operation.

    :param scene_id: ID da cena para o label / scene ID for label
    :param progress_cb: callable(msg, error) para emitir progresso / callable to emit progress
    :param cancelled_ref: lista [bool] — True aborta o Warp / list [bool] — True aborts Warp
    :param pct_cb: callable(int) opcional para emitir só a % inteira / optional callable to emit integer % only
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
            if pct_cb is not None:
                pct_cb(pct)
        return 1  # Retorna 1 para continuar / Return 1 to continue

    return _callback


# ── Download principal via gdal.Warp ──────────────────────────────────────────

def _warp_to_geotiff(src, out_path, scene_id, comp_label, dst_srs, _gdal, progress_cb, cancelled_ref, pct_cb=None, clip_bounds=None, band_names=None):
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
    :param clip_bounds: (minX, minY, maxX, maxY) no dst_srs para recortar à AOI ou None /
                        (minX, minY, maxX, maxY) in dst_srs to clip to AOI or None
    :returns: (out_path, layer_name) ou None / (out_path, layer_name) or None
    :rtype: tuple[str, str] | None
    """
    if _gdal is None:
        return None

    progress_cb('{}: iniciando composição {} / starting {} composite...'.format(
        scene_id, dst_srs, dst_srs), False)

    # ── Configurações HTTP para downloads COG confiáveis ─────────────────────────
    # GDAL_NUM_THREADS=1: o retry HTTP só funciona em modo single-threaded.
    # Com NUM_THREADS>1, o vsicurl usa ReadMultiRange() paralelo que não tem retry
    # e falha silenciosamente em quedas de conexão → tile corrompido no output.
    # Referência: GDAL issue #12426 (retry ineffective when threading enabled).
    # GDAL_NUM_THREADS=1: HTTP retry only works single-threaded.
    # With NUM_THREADS>1, vsicurl uses parallel ReadMultiRange() with no retry
    # → silent failure on connection drops → corrupt output tile. Ref: #12426.
    #
    # SetThreadLocalConfigOption: afeta SOMENTE esta thread de background.
    # SetConfigOption afetaria o GDAL global do QGIS (renderização, WMS, etc.)
    # e causaria travadas na thread principal durante o download.
    # SetThreadLocalConfigOption: affects ONLY this background thread.
    # SetConfigOption would touch QGIS's global GDAL (rendering, WMS, etc.)
    # and cause main-thread freezes while downloading.
    _gdal.SetThreadLocalConfigOption('GDAL_NUM_THREADS',     '1')
    _gdal.SetThreadLocalConfigOption('GDAL_HTTP_MULTIRANGE', 'SERIAL')
    _gdal.SetThreadLocalConfigOption('GDAL_HTTP_MAX_RETRY',  '3')
    _gdal.SetThreadLocalConfigOption('GDAL_HTTP_RETRY_DELAY','2')
    _gdal.SetThreadLocalConfigOption('GDAL_HTTP_RETRY_CODES','ALL')

    warp_kwargs = dict(
        format='GTiff',
        dstSRS=dst_srs,
        # PREDICTOR=2: diferenciação horizontal antes do LZW — torna o stream mais
        # regular e resistente a 'TIFFREADENCODERTILE() Failed' em leitura posterior.
        # PREDICTOR=2: horizontal differencing before LZW — makes the stream more
        # regular and resistant to 'TIFFREADENCODERTILE() Failed' on later reads.
        creationOptions=['COMPRESS=LZW', 'PREDICTOR=2', 'TILED=YES', 'BIGTIFF=IF_SAFER'],
        callback=_make_gdal_progress(scene_id, progress_cb, cancelled_ref, pct_cb=pct_cb),
    )
    if clip_bounds is not None:
        warp_kwargs['outputBounds'] = clip_bounds
    opts = _gdal.WarpOptions(**warp_kwargs)

    _MAX_ATTEMPTS = 3
    result = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        if cancelled_ref[0]:
            break

        if attempt > 1:
            progress_cb('{}: tentativa {}/{} / attempt {}/{}'.format(
                scene_id, attempt, _MAX_ATTEMPTS, attempt, _MAX_ATTEMPTS), False)

        _gdal.ErrorReset()
        ds = None
        try:
            ds = _gdal.Warp(out_path, src, options=opts)
        except Exception as exc:
            progress_cb('{}: erro — {} / error — {}'.format(scene_id, exc, exc), True)
            if os.path.isfile(out_path):
                try:
                    os.remove(out_path)
                except OSError:  # nosec B110
                    pass
            continue

        if cancelled_ref[0] or ds is None:
            # No Windows, o handle GDAL deve ser liberado antes de remover o arquivo /
            # On Windows, the GDAL handle must be released before removing the file
            if ds is not None:
                try:
                    ds.FlushCache()
                    del ds
                except Exception:  # nosec B110
                    pass
            if os.path.isfile(out_path):
                try:
                    os.remove(out_path)
                except OSError:  # nosec B110
                    pass
            progress_cb('{}: cancelado / cancelled'.format(scene_id), False)
            break

        if band_names:
            for i, name in enumerate(band_names, 1):
                b = ds.GetRasterBand(i)
                if b:
                    b.SetDescription(_band_lbl(name))
                b = None  # Libera a referência Python à banda antes do FlushCache.
                          # Sem isso, 'b' mantém o dataset vivo após 'del ds',
                          # abrindo um segundo handle no Open() de validação.
                          # Release Python band reference before FlushCache.
                          # Without this, 'b' keeps the dataset alive after 'del ds',
                          # opening a second handle during the validation Open().
        try:
            ds.FlushCache()
            ds = None  # Fecha o handle GDAL imediatamente (ref count → 0) /
                       # Close GDAL handle immediately (ref count → 0)
        except Exception:
            ds = None

        # Valida o arquivo lendo todos os tiles com Checksum() — isso força a
        # decodificação LZW de cada tile e expõe corrupção silenciosa do warp.
        # Validate the file by reading all tiles via Checksum() — this forces
        # LZW decoding of every tile and exposes silent warp-time corruption.
        _gdal.ErrorReset()
        corrupt = False
        val_ds = None
        try:
            val_ds = _gdal.Open(out_path)
            if val_ds is None:
                corrupt = True
            else:
                for b_idx in range(1, val_ds.RasterCount + 1):
                    val_ds.GetRasterBand(b_idx).Checksum()
                    if _gdal.GetLastErrorType() >= 3:  # CE_Failure
                        corrupt = True
                        break
        except Exception:
            corrupt = True
        finally:
            if val_ds is not None:
                try:
                    del val_ds
                except Exception:  # nosec B110
                    pass

        if not corrupt:
            # Computa estatísticas aproximadas via sampling (~100ms) e grava no arquivo.
            # Sem isso, o QGIS lê todos os pixels na thread principal ao carregar a camada
            # (CumulativeCut com QgsRectangle vazio) → trava a UI por 1–5s em cenas grandes.
            # Compute approximate stats via sampling (~100ms) and write to file.
            # Without this, QGIS reads all pixels on the main thread when loading the layer
            # (CumulativeCut with empty QgsRectangle) → freezes UI 1–5s for large scenes.
            try:
                _st_ds = _gdal.Open(out_path, _gdal.GA_Update)
                if _st_ds:
                    for _bi in range(1, _st_ds.RasterCount + 1):
                        _st_ds.GetRasterBand(_bi).ComputeStatistics(True)
                    _st_ds = None
            except Exception:  # nosec B110
                pass  # Estatísticas são opcionais — não impede o carregamento / Stats are optional — does not block loading

            # Usa os nomes de banda reais quando disponíveis; sem band_names usa comp_label.
            # _band_lbl converte 'B08'→'NIR (B08)', ('NIR','B08')→'NIR (B08)'.
            # Uses real band names when available; without band_names uses comp_label.
            _lbl = ('-'.join(_band_lbl(n) for n in band_names)
                    if band_names else comp_label)
            result = (out_path, '{} [{}]'.format(scene_id, _lbl))
            break

        # Tile corrompido: deleta o arquivo e tenta novamente /
        # Corrupt tile: delete the file and retry
        if os.path.isfile(out_path):
            try:
                os.remove(out_path)
            except OSError:  # nosec B110
                pass

        if attempt < _MAX_ATTEMPTS:
            progress_cb('{}: tile corrompido, tentativa {}/{} / corrupt tile, attempt {}/{}'.format(
                scene_id, attempt + 1, _MAX_ATTEMPTS, attempt + 1, _MAX_ATTEMPTS), False)
        else:
            progress_cb('{}: tile corrompido após {} tentativas / corrupt tile after {} attempts'.format(
                scene_id, _MAX_ATTEMPTS, _MAX_ATTEMPTS), True)

    # Limpa as configurações thread-local ao sair (boa prática — QThread pode ser reutilizada) /
    # Clear thread-local settings on exit (good practice — QThread may be reused)
    for _key in ('GDAL_NUM_THREADS', 'GDAL_HTTP_MULTIRANGE',
                 'GDAL_HTTP_MAX_RETRY', 'GDAL_HTTP_RETRY_DELAY', 'GDAL_HTTP_RETRY_CODES'):
        _gdal.SetThreadLocalConfigOption(_key, None)

    if result:
        progress_cb('{}: 100% — concluído ({}) / complete ({})'.format(
            scene_id, dst_srs, dst_srs), False)
    return result


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
    # 1. Asset de banda única: PAN, EVI, NDVI, ou banda extra personalizada / Single-band asset: PAN, EVI, NDVI, or custom extra band
    if composition_key in ('PAN', 'EVI', 'NDVI', 'EXTRA'):
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

            # Verifica se todas as bandas do bt foram encontradas nos assets.
            # Condição era == 3, mas stacks de 4 (Café) e 5 (Algodão) bandas
            # também chegam aqui. Com == 3 eles caíam no fallback de primeira
            # imagem (geralmente TCI/3 bandas), e o worker derivado tentava
            # extrair bandList=[4] ou [5] de um arquivo de 3 bandas → NULL hBand.
            if band_urls and len(band_urls) == len(bt):
                # VRT em memória virtual — nenhum dado é baixado aqui / Virtual memory VRT — no data downloaded here
                vsimem = '/vsimem/rth_dl_{}.vrt'.format(safe_id(scene_id))
                vrt_ds = _gdal.BuildVRT(vsimem, band_urls, separate=True)
                if vrt_ds:
                    vrt_ds.FlushCache()
                    del vrt_ds
                    _comp_label = '-'.join(labels) if len(band_urls) == 3 else 'STACK{}'.format(len(band_urls))
                    return (vsimem, _comp_label, vsimem)

    # 4. Fallback: primeiro asset de imagem / Fallback: first image asset
    for asset_name, asset_data in assets.items():
        if asset_data.get('type', '').startswith('image/'):
            url = '/vsicurl/' + resolve_href(asset_data['href'])
            return (url, asset_name, None)

    return None


# ── Thread de download em background ─────────────────────────────────────────

class DownloadThread(QThread):
    # ======================================================================
    # DownloadThread — thread de download em background
    #
    # QThread é a classe do Qt para executar código em paralelo sem travar
    # a interface do usuário. Ao herdar de QThread e sobrescrever run(),
    # o QGIS chama run() automaticamente em uma thread separada quando
    # chamamos start(). NUNCA chame run() diretamente — isso executaria
    # na thread principal e travaria a UI.
    #
    # Comunicação com a thread principal via pyqtSignal:
    #   Qt proíbe acessar widgets de uma thread que não seja a principal.
    #   A solução é emitir SINAIS do QThread: o Qt enfileira as chamadas
    #   automaticamente para a thread principal (QueuedConnection).
    #   Assim, progress_sig.emit('mensagem', False) pode ser chamado de
    #   qualquer thread — o slot correspondente sempre executa na UI thread.
    #
    # Ciclo de vida:
    #   1. _on_baixar_clicked() cria a instância e conecta os sinais
    #   2. _advance_dl_queue() chama .start() na hora certa
    #   3. run() executa em background, emitindo sinais de progresso
    #   4. finished_sig é emitido ao final → _on_dl_group_done() avança a fila
    # ======================================================================
    """Executa o download de composições STAC em thread de background / Executes STAC composite download in background thread."""

    # Mensagem de progresso (msg, is_error) / Progress message (msg, is_error)
    progress_sig = pyqtSignal(str, bool)
    # Progresso numérico (cena atual, total de cenas) / Numeric progress (current scene, total scenes)
    count_sig    = pyqtSignal(int, int)
    # Progresso real do GDAL Warp (0–100) para a barra de progresso / Real GDAL Warp progress (0–100) for the progress bar
    warp_pct_sig = pyqtSignal(int)
    # Arquivo pronto para carregar na thread principal: (path, name, feature_dict)
    # File ready to load on main thread: (path, name, feature_dict)
    layer_ready  = pyqtSignal(str, str, object)
    # Total de arquivos criados ao finalizar / Total files created on finish
    finished_sig = pyqtSignal(int)

    def __init__(self, features, collection_id, composition_key, output_dir,
                 band_tuple=None, output_suffix=None, clip_bbox=None, band_names=None):
        """
        :param features: lista de features GeoJSON / list of GeoJSON features
        :param collection_id: ID da coleção STAC / STAC collection ID
        :param composition_key: 'RGB', 'NIR_SWIR_RED', 'RED_NIR_BLUE', 'EXTRA', etc.
        :param output_dir: pasta de destino dos arquivos / output folder for files
        :param band_tuple: tupla de bandas override ou None / band tuple override or None
        :param output_suffix: sufixo do nome de arquivo (ex: 'B11'); usa composition_key se None /
                              filename suffix (e.g. 'B11'); uses composition_key if None
        :param clip_bbox: [minX, minY, maxX, maxY] em WGS84 para recortar à AOI ou None /
                          [minX, minY, maxX, maxY] in WGS84 to clip to AOI or None
        """
        super().__init__()
        self._features        = features
        self._collection_id   = collection_id
        self._composition_key = composition_key
        self._output_dir      = output_dir
        self._band_tuple      = band_tuple
        self._output_suffix   = output_suffix
        self._clip_bbox       = clip_bbox
        # _cancelled_ref é uma LISTA com um único booleano, não um bool simples.
        # Por quê? O callback do GDAL (_callback dentro de _make_gdal_progress)
        # captura 'cancelled_ref' por referência de closure. Se usássemos
        # self._cancelled = False, o callback capturaria o valor inicial False
        # e nunca veria a atualização. A lista é um objeto mutável: quando
        # cancel() faz cancelled_ref[0] = True, o callback enxerga a mudança.
        # Isso é o "mutable default argument" trick do Python para closures.
        self._band_names      = band_names
        self._cancelled_ref   = [False]

    def cancel(self):
        """Sinaliza cancelamento — o Warp em andamento aborta no próximo tick do callback / Signal cancellation — in-progress Warp aborts on next callback tick."""
        self._cancelled_ref[0] = True

    def run(self):
        """Executa em thread de background — não chamar diretamente / Runs in background thread — do not call directly."""
        _gdal   = _init_gdal()
        total   = len(self._features)
        created = 0

        try:
            for idx, feature in enumerate(self._features):
                if self._cancelled_ref[0]:
                    break

                assets   = feature.get('assets', {})
                scene_id = feature.get('id', 'scene')
                comp_key = self._composition_key
                sid      = safe_id(scene_id)

                # ── Detecta o CRS de saída regional para esta cena / Detect regional output CRS for this scene ──
                dst_srs = _scene_dst_srs(feature)

                # ── Converte clip_bbox WGS84 → dst_srs para outputBounds do Warp ──
                # Convert clip_bbox WGS84 → dst_srs for Warp outputBounds
                clip_bounds = None
                if self._clip_bbox:
                    clip_bounds = _bbox_wgs84_to_crs(self._clip_bbox, dst_srs)

                # ── Composição MS (3 bandas) ──────────────────────────────────────
                # MS composite (3 bands)
                # output_suffix permite nomear bandas extras com a chave real (ex: 'B11') /
                # output_suffix lets extra bands be named with the real key (e.g. 'B11')
                file_suffix = self._output_suffix or comp_key
                out_name = '{}_{}.tif'.format(sid, file_suffix)
                out_path = os.path.join(self._output_dir, out_name)

                # Se o arquivo já existe, tenta remover para forçar re-download.
                # No Windows, o QGIS pode manter o arquivo aberto (lock), impedindo
                # os.remove(). Nesse caso, baixamos para um caminho temporário e
                # depois substituímos — se a substituição também falhar, usamos o
                # arquivo temporário como resultado final (mesmo caminho base).
                # If the file already exists, try to remove it to force re-download.
                # On Windows, QGIS may hold the file open (lock), preventing os.remove().
                # In that case we download to a temp path and then replace — if the
                # replace also fails, we use the temp file as the final result.
                _use_temp = False
                if os.path.isfile(out_path):
                    try:
                        os.remove(out_path)
                    except OSError:
                        # Arquivo bloqueado pelo QGIS — baixa para nome temp /
                        # File locked by QGIS — download to temp name
                        _use_temp = True

                _actual_out = out_path + '._tmp' if _use_temp else out_path

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
                    src, _actual_out, scene_id, comp_label, dst_srs,
                    _gdal, self.progress_sig.emit, self._cancelled_ref,
                    pct_cb=self.warp_pct_sig.emit,
                    clip_bounds=clip_bounds,
                    band_names=self._band_names)

                # Limpa VRT intermediário / Clean up intermediate VRT
                if vsimem_to_cleanup and _gdal is not None:
                    try:
                        _gdal.Unlink(vsimem_to_cleanup)
                    except Exception:  # nosec B110
                        pass

                if result is not None:
                    tmp_path, layer_name = result
                    # Se baixamos para path temporário, tenta mover para o path final.
                    # Se o move falhar (arquivo ainda locked), usa o path temporário.
                    # If we downloaded to a temp path, try to move to the final path.
                    # If the move fails (file still locked), use the temp path as-is.
                    if _use_temp and os.path.isfile(tmp_path):
                        try:
                            if os.path.isfile(out_path):
                                os.remove(out_path)
                            os.rename(tmp_path, out_path)
                            tmp_path = out_path
                        except OSError:  # nosec B110
                            pass  # usa o arquivo temp como resultado / use temp file as result
                    created += 1
                    self.layer_ready.emit(tmp_path, layer_name, feature)

                self.count_sig.emit(idx + 1, total)
        except Exception as _exc:
            self.progress_sig.emit(
                'Erro inesperado: {} — {} / Unexpected error: {} — {}'.format(
                    type(_exc).__name__, _exc, type(_exc).__name__, _exc), True)

        self.finished_sig.emit(created)
