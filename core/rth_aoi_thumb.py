# -*- coding: utf-8 -*-
"""
rth_aoi_thumb — Gerador de thumbnails COG recortados na AOI usando GDAL + numpy
rth_aoi_thumb — COG thumbnail generator clipped to AOI using GDAL + numpy

Lê bandas COG via /vsicurl/, recorta à bbox da AOI e devolve um QPixmap
com stretch percentílico 2%/98%.

Reads COG bands via /vsicurl/, clips to AOI bbox and returns a QPixmap
with 2%/98% percentile stretch.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

import time as _time

try:
    import numpy as np
    _NUMPY = True
except ImportError:
    _NUMPY = False

from qgis.PyQt.QtCore import QRunnable, QObject, pyqtSignal, QThreadPool, Qt, QPointF
from qgis.PyQt.QtGui import QImage, QPixmap, QPainter, QPen, QColor

try:
    from osgeo import gdal as _gdal_mod
    _gdal_mod.UseExceptions()
except ImportError:
    _gdal_mod = None

from .rth_band_resolver import find_asset_key
from .rth_pc_auth import sign_pc_href

try:
    _FMT_RGB = QImage.Format.Format_RGB888
except AttributeError:
    _FMT_RGB = QImage.Format_RGB888

try:
    _SMOOTH = Qt.TransformationMode.SmoothTransformation
except AttributeError:
    _SMOOTH = Qt.SmoothTransformation

try:
    _KEEP_AR = Qt.AspectRatioMode.KeepAspectRatio
except AttributeError:
    _KEEP_AR = Qt.KeepAspectRatio

try:
    _PEN_SOLID = Qt.PenStyle.SolidLine
except AttributeError:
    _PEN_SOLID = Qt.SolidLine

try:
    _ANTIALIAS = QPainter.RenderHint.Antialiasing
except AttributeError:
    _ANTIALIAS = QPainter.Antialiasing


# Pool dedicado com máximo 3 threads paralelas — evita flood nos servidores COG
# e rate limiting que derruba thumbnails aleatoriamente no QThreadPool global.
# Dedicated pool capped at 3 parallel threads — prevents COG server flooding
# and random rate-limiting failures that occur with the global QThreadPool.
_THUMB_POOL = None

def _thumb_pool():
    global _THUMB_POOL
    if _THUMB_POOL is None:
        _THUMB_POOL = QThreadPool()
        _THUMB_POOL.setMaxThreadCount(3)
    return _THUMB_POOL


class _Signals(QObject):
    done = pyqtSignal(object)   # QPixmap | None


class AoiThumbWorker(QRunnable):
    """Worker que gera thumbnail a partir de bandas COG recortadas na AOI /
    Worker that generates thumbnail from COG bands clipped to AOI.

    Roda em thread de background via QThreadPool — não bloqueia a UI.
    Runs in background thread via QThreadPool — does not block the UI.
    """

    def __init__(self, feature, collection_id, band_tuple, aoi_bbox, w, h, cancel_flag):
        """
        :param feature: GeoJSON feature com assets / GeoJSON feature with assets
        :param collection_id: ID da coleção STAC / STAC collection ID
        :param band_tuple: str ou lista de chaves de banda / str or list of band keys
        :param aoi_bbox: [minX, minY, maxX, maxY] em WGS84 / in WGS84
        :param w: largura do thumbnail em pixels / thumbnail width in pixels
        :param h: altura do thumbnail em pixels / thumbnail height in pixels
        :param cancel_flag: lista [bool] — [True] cancela o worker / list [bool] — [True] cancels worker
        """
        super().__init__()
        self._feature       = feature
        self._collection_id = collection_id
        self._band_tuple    = band_tuple
        self._bbox          = aoi_bbox
        self._w             = w
        self._h             = h
        self._cancel        = cancel_flag
        self.signals        = _Signals()
        self.setAutoDelete(True)

    def run(self):
        if _gdal_mod is None or not _NUMPY:
            self.signals.done.emit(None)
            return
        # Configurações HTTP thread-local — não afetam o GDAL global do QGIS.
        # Thread-local HTTP settings — do not affect QGIS's global GDAL.
        _gdal_mod.SetThreadLocalConfigOption('GDAL_HTTP_TIMEOUT',            '15')
        _gdal_mod.SetThreadLocalConfigOption('GDAL_HTTP_UNSAFESSL',          'YES')
        _gdal_mod.SetThreadLocalConfigOption('GDAL_DISABLE_READDIR_ON_OPEN', 'EMPTY_DIR')
        _gdal_mod.SetThreadLocalConfigOption('CPL_VSIL_CURL_USE_CACHE',      'YES')
        try:
            pm = None
            # Tenta até 5 vezes quando GDAL lança exceção (rate limit, falha de rede).
            # Retorno None sem exceção = banda não encontrada no asset → para imediatamente.
            # Up to 5 attempts when GDAL raises exception (rate limit, network error).
            # None return without exception = band not in assets → stop immediately.
            for _attempt in range(5):
                if self._cancel[0]:
                    break
                _network_err = False
                try:
                    pm = self._generate()
                except Exception:
                    pm = None
                    _network_err = True
                if pm is not None or not _network_err:
                    break
                if _attempt < 4 and not self._cancel[0]:
                    _time.sleep(2.0)
        finally:
            for _k in ('GDAL_HTTP_TIMEOUT', 'GDAL_HTTP_UNSAFESSL',
                       'GDAL_DISABLE_READDIR_ON_OPEN', 'CPL_VSIL_CURL_USE_CACHE'):
                _gdal_mod.SetThreadLocalConfigOption(_k, None)
        self.signals.done.emit(pm)

    def _href_for(self, band_key):
        """Resolve URL do asset para a banda especificada / Resolve asset URL for the given band."""
        assets = self._feature.get('assets', {})
        key    = band_key if band_key in assets else find_asset_key(assets, band_key)
        if not key:
            return None
        href = (assets.get(key) or {}).get('href', '')
        if not href:
            return None
        # Assina hrefs do Planetary Computer / Sign Planetary Computer hrefs
        if 'planetarycomputer' in href or '.blob.core.windows.net' in href:
            try:
                href = sign_pc_href(href)
            except Exception:  # nosec B110
                pass
        # Converte s3:// para https HTTPS / Convert s3:// to HTTPS
        if href.startswith('s3://'):
            parts = href[5:].split('/', 1)
            if len(parts) == 2:
                href = 'https://{}.s3.amazonaws.com/{}'.format(*parts)
        return href

    def _read_band(self, band_key):
        """Lê uma banda COG via vsicurl, recortada à AOI e reescalonada /
        Read a COG band via vsicurl, clipped to AOI and rescaled."""
        href = self._href_for(band_key)
        if not href:
            return None

        ds = _gdal_mod.Open('/vsicurl/' + href, _gdal_mod.GA_ReadOnly)
        if ds is None:
            return None
        try:
            gt = ds.GetGeoTransform()
            # Geotransform padrão indica ausência de georreferenciamento /
            # Default geotransform indicates no georeferencing available
            if gt == (0.0, 1.0, 0.0, 0.0, 0.0, 1.0):
                return None

            sw = ds.RasterXSize
            sh = ds.RasterYSize

            minX, minY, maxX, maxY = self._bbox  # WGS84

            # Transforma bbox WGS84 para o CRS do raster / Transform WGS84 bbox to raster CRS
            raster_wkt = ds.GetProjection()
            if raster_wkt:
                try:
                    from osgeo import osr
                    src_sr = osr.SpatialReference()
                    src_sr.ImportFromEPSG(4326)
                    try:
                        src_sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                    except AttributeError:  # nosec B110
                        pass
                    dst_sr = osr.SpatialReference()
                    dst_sr.ImportFromWkt(raster_wkt)
                    try:
                        dst_sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                    except AttributeError:  # nosec B110
                        pass
                    ct = osr.CoordinateTransformation(src_sr, dst_sr)
                    corners = [ct.TransformPoint(x, y) for x, y in [
                        (minX, minY), (maxX, minY), (minX, maxY), (maxX, maxY)]]
                    minX = min(c[0] for c in corners)
                    minY = min(c[1] for c in corners)
                    maxX = max(c[0] for c in corners)
                    maxY = max(c[1] for c in corners)
                except Exception:  # nosec B110
                    pass  # Usa bbox original se a transformação falhar / Use original bbox if transform fails

            # Converte bbox para janela de pixels / Convert bbox to pixel window
            px0 = max(0,  int((minX - gt[0]) / gt[1]))
            py0 = max(0,  int((maxY - gt[3]) / gt[5]))
            px1 = min(sw, int((maxX - gt[0]) / gt[1]) + 1)
            py1 = min(sh, int((minY - gt[3]) / gt[5]) + 1)

            if px1 <= px0 or py1 <= py0:
                return None

            arr = ds.GetRasterBand(1).ReadAsArray(
                px0, py0, px1 - px0, py1 - py0,
                buf_xsize=self._w, buf_ysize=self._h)
            return arr
        finally:
            del ds

    @staticmethod
    def _stretch(arr):
        """Normaliza o array para 0–255 com stretch percentílico 2%/98% /
        Normalize array to 0–255 with 2%/98% percentile stretch."""
        if arr is None:
            return None
        a = arr.astype('float32')
        p2, p98 = np.percentile(a[a > 0], (2, 98)) if (a > 0).any() else (0.0, 1.0)
        if p98 <= p2:
            return np.zeros(arr.shape, dtype='uint8')
        a = np.clip((a - p2) / (p98 - p2) * 255.0, 0, 255)
        return a.astype('uint8')

    def _generate(self):
        if self._cancel[0]:
            return None
        bt = self._band_tuple
        if not bt:
            return None

        keys = [bt] if isinstance(bt, str) else list(bt)

        if len(keys) == 1:
            arr = self._stretch(self._read_band(keys[0]))
            if arr is None:
                return None
            rgb = np.stack([arr, arr, arr], axis=2)
        else:
            channels = []
            for k in keys[:3]:
                if self._cancel[0]:
                    return None
                arr = self._stretch(self._read_band(k))
                if arr is None:
                    return None
                channels.append(arr)
            rgb = np.stack(channels, axis=2)

        h, w = rgb.shape[:2]
        img  = QImage(rgb.tobytes(), w, h, w * 3, _FMT_RGB)
        return QPixmap.fromImage(img).scaled(self._w, self._h, _KEEP_AR, _SMOOTH)


def _overlay_rings_on_pixmap(pixmap, rings, bbox):
    """Desenha contornos dos anéis WGS84 sobre o pixmap usando mapeamento linear da bbox.
    Draws WGS84 ring outlines on pixmap using linear bbox mapping (approximate, fast)."""
    minx, miny, maxx, maxy = bbox
    dx, dy = maxx - minx, maxy - miny
    if dx <= 0 or dy <= 0:
        return pixmap

    result  = QPixmap(pixmap)
    painter = QPainter(result)
    pen     = QPen(QColor(255, 220, 0, 220))  # amarelo semi-transparente / yellow semi-transparent
    pen.setWidth(2)
    pen.setStyle(_PEN_SOLID)
    painter.setPen(pen)
    painter.setRenderHint(_ANTIALIAS)

    pw, ph = result.width(), result.height()
    for ring in rings:
        if len(ring) < 2:
            continue
        pts = []
        for lon, lat in ring:
            px = (lon - minx) / dx * pw
            py = (maxy - lat) / dy * ph  # y invertido: lat crescente = pixel decrescente
            pts.append(QPointF(px, py))
        if pts:
            if pts[0] != pts[-1]:
                pts.append(pts[0])  # fecha o anel / close the ring
            for i in range(len(pts) - 1):
                painter.drawLine(pts[i], pts[i + 1])

    painter.end()
    return result


def load_aoi_thumb_async(feature, collection_id, band_tuple, aoi_bbox,
                          label, cancel_flag, w=207, h=130,
                          overlay_rings=None):
    """Inicia geração assíncrona de thumbnail COG e atualiza o label ao concluir.
    Opcionalmente sobrepõe contornos de polígono sobre o thumbnail.
    Start async COG thumbnail generation and update label on completion.
    Optionally overlays polygon ring outlines on the thumbnail."""
    worker = AoiThumbWorker(
        feature, collection_id, band_tuple, aoi_bbox, w, h, cancel_flag)

    def _done(pixmap):
        try:
            if pixmap is not None:
                if overlay_rings:
                    pixmap = _overlay_rings_on_pixmap(pixmap, overlay_rings, aoi_bbox)
                label.setPixmap(pixmap)
            else:
                label.setText('—')
        except RuntimeError:  # nosec B110
            pass  # Widget já destruído / Widget already destroyed

    worker.signals.done.connect(_done)
    _thumb_pool().start(worker)
