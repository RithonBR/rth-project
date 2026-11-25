# -*- coding: utf-8 -*-
"""
rth_thumbnail — Carregamento assíncrono de thumbnails de cenas STAC
rth_thumbnail — Asynchronous STAC scene thumbnail loading

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Biblioteca padrão para requisições HTTP / Standard library for HTTP requests
import urllib.request

# Módulos Qt para imagem, threads e sinais / Qt modules for image, threads and signals
from qgis.PyQt.QtCore import Qt, QByteArray, QRunnable, QObject, pyqtSignal, QThreadPool
from qgis.PyQt.QtGui import QImage, QPixmap

# Resolução de URLs s3:// e assinatura de URLs do Planetary Computer / s3:// URL resolution and PC URL signing
from .rth_pc_auth import resolve_href

# Chaves de asset conhecidas para thumbnails, em ordem de prioridade / Known thumbnail asset keys, in priority order
_THUMB_KEYS = ('thumbnail', 'overview', 'preview', 'rendered_preview')

# Roles STAC que indicam visualização reduzida / STAC roles indicating reduced-resolution preview
_THUMB_ROLES = {'thumbnail', 'overview'}

# Tipos MIME de imagem plana renderizáveis pelo QPixmap / Flat image MIME types renderable by QPixmap
_RENDERABLE_MIME = ('image/jpeg', 'image/jpg', 'image/png', 'image/webp')


def _collect_candidate_urls(assets):
    """Coleta URLs candidatas de thumbnail em ordem de prioridade / Collect candidate thumbnail URLs in priority order.

    Ordem / Order:
    1. Chaves conhecidas (qualquer MIME, incluindo GeoTIFF) / Known keys (any MIME, including GeoTIFF)
    2. Roles STAC (qualquer MIME) / STAC roles (any MIME)
    3. Qualquer asset JPEG/PNG/WebP como fallback / Any JPEG/PNG/WebP asset as fallback

    :param assets: dicionário de assets da feature / feature assets dict
    :returns: lista de URLs em ordem de prioridade / list of URLs in priority order
    :rtype: list[str]
    """
    seen = set()
    urls = []

    def _add(href):
        # Evita duplicatas / Avoid duplicates
        if href and href not in seen:
            seen.add(href)
            urls.append(href)

    # 1. Chaves conhecidas primeiro (GeoTIFF incluído) / Known keys first (GeoTIFF included)
    for key in _THUMB_KEYS:
        if key in assets:
            _add(assets[key].get('href', ''))

    # 2. Roles STAC padrão / Standard STAC roles
    for asset_data in assets.values():
        roles = set(asset_data.get('roles') or [])
        if roles & _THUMB_ROLES:
            _add(asset_data.get('href', ''))

    # 3. Fallback: qualquer JPEG/PNG/WebP / Fallback: any JPEG/PNG/WebP
    for asset_data in assets.values():
        mime = (asset_data.get('type') or '').lower()
        if any(mime.startswith(r) for r in _RENDERABLE_MIME):
            _add(asset_data.get('href', ''))

    return urls


def _try_qpixmap(url, width, height):
    """Tenta carregar a imagem via QPixmap (funciona com JPEG, PNG, WebP) / Try loading the image via QPixmap (works with JPEG, PNG, WebP).

    :returns: QPixmap válido ou None / valid QPixmap or None
    :rtype: QPixmap | None
    """
    try:
        if not url.startswith(('https://', 'http://')):
            raise ValueError('URL scheme not permitted: {}'.format(url))
        with urllib.request.urlopen(url, timeout=10) as resp:  # nosec B310
            img_data = resp.read()
        pixmap = QPixmap()
        pixmap.loadFromData(QByteArray(img_data))
        if not pixmap.isNull():
            return pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception:
        pass
    return None


def _try_gdal(url, width, height):
    """Tenta carregar GeoTIFF via GDAL e converte para QPixmap / Try loading GeoTIFF via GDAL and convert to QPixmap.

    Lê as primeiras 3 bandas (ou 1 banda grayscale), normaliza e monta um QImage RGB.
    Reads first 3 bands (or 1 grayscale band), normalizes and builds an RGB QImage.

    :returns: QPixmap válido ou None / valid QPixmap or None
    :rtype: QPixmap | None
    """
    try:
        from osgeo import gdal
        import numpy as np
    except ImportError:
        # GDAL ou numpy não disponíveis / GDAL or numpy not available
        return None

    try:
        # Abre via vsicurl para URLs remotas / Open via vsicurl for remote URLs
        path = ('/vsicurl/' + url) if url.startswith('http') else url
        ds = gdal.Open(path)
        if not ds or ds.RasterCount == 0:
            return None

        # Lê até 3 bandas em resolução reduzida / Read up to 3 bands at reduced resolution
        n = min(ds.RasterCount, 3)
        bands = []
        for i in range(1, n + 1):
            arr = ds.GetRasterBand(i).ReadAsArray(buf_xsize=width, buf_ysize=height)
            if arr is None:
                return None
            bands.append(arr)

        # Repete a banda única para grayscale → RGB / Repeat single band for grayscale → RGB
        if len(bands) == 1:
            bands = bands * 3

        # Normaliza cada banda para 0-255 / Normalize each band to 0-255
        def _norm(arr):
            mn, mx = float(arr.min()), float(arr.max())
            if mx == mn:
                return np.zeros_like(arr, dtype=np.uint8)
            return ((arr - mn) / (mx - mn) * 255).astype(np.uint8)

        r, g, b = _norm(bands[0]), _norm(bands[1]), _norm(bands[2])

        # Monta array RGBA e cria QImage / Build RGBA array and create QImage
        rgba  = np.stack([r, g, b, np.full_like(r, 255, dtype=np.uint8)], axis=2)
        h_px, w_px = rgba.shape[:2]
        img = QImage(rgba.tobytes(), w_px, h_px, w_px * 4, QImage.Format_RGBA8888)
        if img.isNull():
            return None

        pixmap = QPixmap.fromImage(img)
        if pixmap.isNull():
            return None
        return pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    except Exception:
        return None


# ── Carregamento assíncrono via QThreadPool ───────────────────────────────────
# Async loading via QThreadPool

class _ThumbSignals(QObject):
    """Sinais para o worker de thumbnail / Signals for thumbnail worker."""
    # Emite QPixmap carregado ou None em caso de falha / Emits loaded QPixmap or None on failure
    done = pyqtSignal(object)


class _ThumbWorker(QRunnable):
    """Carrega um thumbnail em thread de background via QThreadPool / Load thumbnail in background thread via QThreadPool.

    Tenta cada URL candidata em ordem; emite done quando obtém imagem ou quando esgota as opções.
    Tries each candidate URL in order; emits done when image is obtained or options exhausted.
    """

    def __init__(self, urls, w, h, cancel_flag):
        """
        :param urls: lista de URLs já resolvidas (https://) / list of already resolved (https://) URLs
        :param w: largura alvo em pixels / target width in pixels
        :param h: altura alvo em pixels / target height in pixels
        :param cancel_flag: lista [bool] compartilhada — [True] cancela o worker / shared [bool] — [True] cancels worker
        """
        super().__init__()
        self._urls   = urls
        self._w      = w
        self._h      = h
        self._cancel = cancel_flag
        self.signals = _ThumbSignals()
        # Thread pool libera o worker automaticamente após run() / Thread pool auto-deletes after run()
        self.setAutoDelete(True)

    def run(self):
        """Executa em thread de background / Executes in background thread."""
        for url in self._urls:
            # Verifica cancelamento antes e depois de cada chamada bloqueante
            # Check cancellation before and after each blocking call
            if self._cancel[0]:
                return
            pixmap = _try_qpixmap(url, self._w, self._h)
            if self._cancel[0]:
                return
            if pixmap is None:
                pixmap = _try_gdal(url, self._w, self._h)
            if self._cancel[0]:
                return
            if pixmap is not None:
                # AutoConnection entrega na thread do objeto _ThumbSignals (thread principal)
                # AutoConnection delivers on _ThumbSignals object's thread (main thread)
                self.signals.done.emit(pixmap)
                return
        # Todas as URLs falharam / All URLs failed
        self.signals.done.emit(None)


def load_thumbnail_async(feature, label_widget, cancel_flag):
    """Carrega thumbnail de forma assíncrona sem bloquear a thread principal / Load thumbnail asynchronously without blocking the main thread.

    O resultado é entregue via sinal Qt na thread principal quando o carregamento terminar.
    The result is delivered via Qt signal on the main thread when loading completes.

    :param feature: feature GeoJSON com assets / GeoJSON feature with assets
    :param label_widget: QLabel onde o thumbnail será exibido / QLabel where thumbnail is displayed
    :param cancel_flag: lista [bool] — setar [0]=True cancela workers pendentes / list [bool] — set [0]=True cancels pending workers
    """
    assets = feature.get('assets', {})
    # Resolve todas as URLs antes de passar para o worker (s3:// → https://, PC → assinada)
    # Resolve all URLs before passing to worker (s3:// → https://, PC → signed)
    urls = [resolve_href(u) for u in _collect_candidate_urls(assets)]

    if not urls:
        try:
            label_widget.setText('Sem thumbnail / No thumbnail')
        except RuntimeError:
            pass
        return

    w = label_widget.width()  - 4
    h = label_widget.height() - 4

    def _on_done(pixmap):
        # Executado na thread principal via sinal Qt / Executed on main thread via Qt signal
        # Guard against the widget being deleted before the worker finishes
        # (e.g. user closed the dialog or scrolled away while download was in flight).
        try:
            if pixmap is not None:
                label_widget.setPixmap(pixmap)
            else:
                label_widget.setText('Sem thumbnail / No thumbnail')
        except RuntimeError:
            pass

    worker = _ThumbWorker(urls, w, h, cancel_flag)
    worker.signals.done.connect(_on_done)
    # Inicia o worker no pool global — pool gerencia concorrência automaticamente
    # Start worker in global pool — pool manages concurrency automatically
    QThreadPool.globalInstance().start(worker)
