# -*- coding: utf-8 -*-
"""
tool_meteo_data — Base de Dados Meteorológicos / Meteorological Data Base

Acessa produtos meteorológicos do INPE via STAC API (Brazil Data Cube).
Datasets: GOES-16/19, GOES-13, GL DSWRF, SAMeT, MERGE, ETA CC.

O botão principal baixa o arquivo do asset selecionado para uma pasta
escolhida pelo usuário — o download ocorre em thread de fundo para não
bloquear o QGIS.
"""

import os
from datetime import date

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QListWidget, QListWidgetItem, QSplitter,
    QApplication, QTextEdit, QWidget, QFileDialog,
)
from qgis.PyQt.QtCore import Qt, QThread, QSize, pyqtSignal, QUrl
from qgis.PyQt.QtGui import QPixmap, QIcon, QDesktopServices
from qgis.core import Qgis, QgsProject

from core.rth_stac_api import search_stac

# ── Qt5/Qt6 compat ────────────────────────────────────────────────────────────
try:
    _ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
    _KEEP_RATIO   = Qt.AspectRatioMode.KeepAspectRatio
    _SMOOTH       = Qt.TransformationMode.SmoothTransformation
except AttributeError:
    _ALIGN_CENTER = Qt.AlignCenter
    _KEEP_RATIO   = Qt.KeepAspectRatio
    _SMOOTH       = Qt.SmoothTransformation

_BRAZIL_BBOX = [-74.0, -34.0, -34.0, 6.0]
_PAGE_SIZE   = 20


# ── Dataset catalog ───────────────────────────────────────────────────────────
_METEO_DATASETS = [
    {
        'id':          'goes19',
        'label':       'GOES-19 (CMI L2)',
        'collection':  'GOES19-L2-CMI-1',
        'description': (
            u'Imagens GOES-19 com 16 canais ABI (CMI L2). Canal visível e infravermelho. '
            u'Cobertura: América do Sul. Resolução: 2 km (B01 em 1 km).\n'
            u'GOES-19 with 16 ABI channels (CMI L2). Visible and infrared. '
            u'Coverage: South America. Resolution: 2 km (B01 at 1 km).'
        ),
        'asset_keys':  ['B01', 'B02', 'B03', 'B04'],
        'raster_exts': ['.nc'],
    },
    {
        'id':          'goes16',
        'label':       'GOES-16 (CMI L2)',
        'collection':  'GOES16-L2-CMI-1',
        'description': (
            u'Imagens GOES-16 com 16 canais ABI (CMI L2). Principal satélite meteorológico '
            u'geostacionário sobre a América do Sul. Resolução: 2 km.\n'
            u'GOES-16 with 16 ABI channels (CMI L2). Primary geostationary met satellite '
            u'over South America. Resolution: 2 km.'
        ),
        'asset_keys':  ['B01', 'B02', 'B03', 'B04'],
        'raster_exts': ['.nc'],
    },
    {
        'id':          'goes13',
        'label':       'GOES-13 (Imager L3) — histórico',
        'collection':  'GOES13-L3-IMAGER-1',
        'description': (
            u'GOES-13 histórico (NOAA/INPE). Desativado em 2016. Dados históricos disponíveis.\n'
            u'⚠ Formato comprimido (.gz). Faça o download para descompactar localmente.\n\n'
            u'Historical GOES-13 (NOAA/INPE). Decommissioned in 2016.\n'
            u'⚠ Compressed format (.gz). Download and decompress locally.'
        ),
        'asset_keys':  ['B01', 'B02', 'B03', 'B04', 'B05'],
        'raster_exts': ['.gz'],
    },
    {
        'id':          'gl_dswrf',
        'label':       'GOES GL — Radiação Solar / Solar Radiation (DSWRF)',
        'collection':  'GOES-GL-DSWRF-Daily-1',
        'description': (
            u'Radiação de onda curta descendente (DSWRF) diária derivada do GOES GL. '
            u'Cobertura: Brasil. Formato NetCDF.\n'
            u'Daily Downward Short Wave Radiation Flux (DSWRF) from GOES GL. '
            u'Coverage: Brazil. NetCDF format.'
        ),
        'asset_keys':  ['dswrf_daily_mean', 'data'],
        'raster_exts': ['.nc', '.tif', '.tiff'],
    },
    {
        'id':          'samet_hourly',
        'label':       'SAMeT Horário / Hourly (Temperatura / Temperature)',
        'collection':  'samet_hourly-1',
        'description': (
            u'Temperatura horária do SAMeT/INPE (análise de temperatura do ar). '
            u'Resolução: 0.05° (~5.5 km). Cobertura: Brasil.\n'
            u'Hourly air temperature analysis from SAMeT/INPE. '
            u'Resolution: 0.05° (~5.5 km). Coverage: Brazil.'
        ),
        'asset_keys':  ['temperature', 'data'],
        'raster_exts': ['.nc'],
    },
    {
        'id':          'samet_daily',
        'label':       'SAMeT Diário / Daily (Temperatura / Temperature)',
        'collection':  'samet_daily-1',
        'description': (
            u'Temperatura máxima, mínima e média diária do SAMeT/INPE. '
            u'Resolução: 0.05° (~5.5 km). Cobertura: Brasil.\n'
            u'Daily max, min and mean air temperature from SAMeT/INPE. '
            u'Resolution: 0.05° (~5.5 km). Coverage: Brazil.'
        ),
        'asset_keys':  ['tmax', 'tmin', 'tmean'],
        'raster_exts': ['.nc'],
    },
    {
        'id':          'merge_daily',
        'label':       'MERGE Diário / Daily (Precipitação / Precipitation)',
        'collection':  'prec_merge_daily-1',
        'description': (
            u'Precipitação diária MERGE/INPE — combina radar, satélite e pluviômetros. '
            u'Resolução: 0.1° (~11 km). Formato GRIB2.\n'
            u'MERGE daily precipitation from INPE — combines radar, satellite and rain gauges. '
            u'Resolution: 0.1° (~11 km). GRIB2 format.'
        ),
        'asset_keys':  ['merge_daily'],
        'raster_exts': ['.grib2', '.grb2'],
    },
    {
        'id':          'merge_hourly',
        'label':       'MERGE Horário / Hourly (Precipitação / Precipitation)',
        'collection':  'prec_merge_hourly-1',
        'description': (
            u'Precipitação horária MERGE/INPE. Resolução: 0.1° (~11 km). Formato GRIB2.\n'
            u'MERGE hourly precipitation from INPE. Resolution: 0.1° (~11 km). GRIB2 format.'
        ),
        'asset_keys':  ['merge_hourly'],
        'raster_exts': ['.grib2', '.grb2'],
    },
    {
        'id':          'eta_cc',
        'label':       'ETA CC — Projeção Climática / Climate Projection (2071–2099)',
        'collection':  'EtaCCDay_CMIP5-1',
        'description': (
            u'Projeção climática diária (2071–2099) do modelo ETA/INPE baseado no CMIP5 '
            u'(HadGEM2-ES, RCP 4.5). Variáveis: chuva (pr), temperatura (tas, tasmax, tasmin), '
            u'vento, umidade, radiação.\n'
            u'Daily climate projection (2071–2099) from ETA/INPE model based on CMIP5 '
            u'(HadGEM2-ES, RCP 4.5). Variables: rain (pr), temperature (tas, tasmax, tasmin), '
            u'wind, humidity, radiation.'
        ),
        'asset_keys':  ['pr', 'tas', 'tasmax', 'tasmin', 'rsds', 'sfcwind'],
        'raster_exts': ['.nc'],
    },
]


# ── STAC search thread ────────────────────────────────────────────────────────

class _MeteoSearchThread(QThread):
    result = pyqtSignal(list)
    error  = pyqtSignal(str)

    def __init__(self, collection, parent=None):
        super().__init__(parent)
        self._collection = collection
        self._cancel     = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            today = date.today().isoformat()
            features, _ = search_stac(
                self._collection, _BRAZIL_BBOX, '1970-01-01', today, 100, limit=500)
            if self._cancel:
                return
            def _dt_key(f):
                props = f.get('properties', {})
                return props.get('datetime', props.get('start_datetime', '')) or ''
            features.sort(key=_dt_key, reverse=True)
            self.result.emit(features)
        except Exception as e:
            self.error.emit(str(e))


# ── Thumbnail loader thread ───────────────────────────────────────────────────

class _ThumbnailLoader(QThread):
    # QPixmap cannot be created in non-GUI thread — emit raw bytes instead
    thumbnail_ready = pyqtSignal(int, object)

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self._items  = items
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        import urllib.request
        for row, url in self._items:
            if self._cancel or not url:
                continue
            try:
                req = urllib.request.Request(
                    url, headers={'User-Agent': 'RTH-QGIS-Plugin/1.0'})
                with urllib.request.urlopen(req, timeout=8) as resp:  # nosec B310
                    data = resp.read()
                self.thumbnail_ready.emit(row, data)
            except Exception:  # nosec B110
                pass


# ── Download thread ───────────────────────────────────────────────────────────

class _DownloadThread(QThread):
    progress = pyqtSignal(int, int)  # (bytes_done, total_bytes)
    done     = pyqtSignal(str)       # dest_path
    error    = pyqtSignal(str)

    def __init__(self, url, dest_path, parent=None):
        super().__init__(parent)
        self._url       = url
        self._dest_path = dest_path
        self._cancel    = False

    def cancel(self):
        self._cancel = True

    def run(self):
        import urllib.request
        try:
            req = urllib.request.Request(
                self._url, headers={'User-Agent': 'RTH-QGIS-Plugin/1.0'})
            with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310
                total      = int(resp.headers.get('Content-Length', 0) or 0)
                downloaded = 0
                chunk_sz   = 65_536
                with open(self._dest_path, 'wb') as fh:
                    while True:
                        if self._cancel:
                            break
                        chunk = resp.read(chunk_sz)
                        if not chunk:
                            break
                        fh.write(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total)
            if self._cancel:
                try:
                    os.remove(self._dest_path)
                except OSError:  # nosec B110
                    pass
                return
            self.done.emit(self._dest_path)
        except Exception as e:
            try:
                os.remove(self._dest_path)
            except OSError:  # nosec B110
                pass
            self.error.emit(str(e))


# ── Dialog ────────────────────────────────────────────────────────────────────

class MeteoDataDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface            = iface
        self._all_features    = []
        self._current_ds      = None
        self._page            = 0
        self._search_thread   = None
        self._thumb_thread    = None
        self._download_thread = None
        self._last_dl_folder  = os.path.expanduser('~')

        self.setWindowTitle(
            'RTH Base de Dados Meteorológicos / Meteorological Data Base')
        self.setMinimumWidth(720)
        self.setMinimumHeight(560)

        try:
            self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        except AttributeError:
            self.setAttribute(Qt.WA_QuitOnClose, False)

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        lbl_title = QLabel(
            'RTH — Base de Dados Meteorológicos / Meteorological Data Base')
        lbl_title.setAlignment(_ALIGN_CENTER)
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold; color:#1a73e8;')
        root.addWidget(lbl_title)

        lbl_sub = QLabel(
            u'Dados do INPE via STAC API (Brazil Data Cube). '
            u'Selecione um dataset, escolha um item e baixe o arquivo. / '
            u'Select a dataset, choose an item, and download the file.')
        lbl_sub.setAlignment(_ALIGN_CENTER)
        lbl_sub.setStyleSheet('font-size:10px; color:#555;')
        lbl_sub.setWordWrap(True)
        root.addWidget(lbl_sub)

        self._sep(root)

        splitter = QSplitter(Qt.Horizontal)

        # ── Left: dataset list ────────────────────────────────────────────────
        left_w   = QWidget()
        left_lay = QVBoxLayout(left_w)
        left_lay.setContentsMargins(0, 0, 4, 0)
        left_lay.setSpacing(4)

        lbl_ds = QLabel('Datasets:')
        lbl_ds.setStyleSheet('font-weight:bold; font-size:11px;')
        left_lay.addWidget(lbl_ds)

        self._list_datasets = QListWidget()
        self._list_datasets.setMinimumWidth(200)
        for ds in _METEO_DATASETS:
            item = QListWidgetItem(ds['label'])
            item.setData(Qt.UserRole, ds)
            self._list_datasets.addItem(item)
        self._list_datasets.currentItemChanged.connect(self._on_dataset_selected)
        left_lay.addWidget(self._list_datasets)
        splitter.addWidget(left_w)

        # ── Right: description + results + pagination + download ──────────────
        right_w   = QWidget()
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(4, 0, 0, 0)
        right_lay.setSpacing(6)

        self._txt_desc = QTextEdit()
        self._txt_desc.setReadOnly(True)
        self._txt_desc.setMaximumHeight(80)
        self._txt_desc.setStyleSheet('background:#f8f9fa; font-size:10px;')
        right_lay.addWidget(self._txt_desc)

        lbl_res = QLabel(
            'Itens disponíveis / Available items (mais recente primeiro / newest first):')
        lbl_res.setStyleSheet('font-size:10px;')
        right_lay.addWidget(lbl_res)

        self._list_results = QListWidget()
        self._list_results.setMinimumHeight(220)
        self._list_results.setIconSize(QSize(96, 58))
        self._list_results.itemDoubleClicked.connect(self._on_download)
        right_lay.addWidget(self._list_results)

        # Pagination
        row_page = QHBoxLayout()
        self._btn_prev = QPushButton('◀  Anterior / Previous')
        self._btn_prev.setFixedHeight(28)
        self._btn_prev.setEnabled(False)
        self._btn_prev.clicked.connect(self._on_prev_page)
        row_page.addWidget(self._btn_prev)

        self._lbl_page = QLabel('')
        self._lbl_page.setAlignment(_ALIGN_CENTER)
        self._lbl_page.setStyleSheet('font-size:10px; color:#555;')
        row_page.addWidget(self._lbl_page, 1)

        self._btn_next = QPushButton('Próximo / Next  ▶')
        self._btn_next.setFixedHeight(28)
        self._btn_next.setEnabled(False)
        self._btn_next.clicked.connect(self._on_next_page)
        row_page.addWidget(self._btn_next)
        right_lay.addLayout(row_page)

        # Download + Cancel + Open Folder buttons
        dl_row = QHBoxLayout()

        self._btn_dl = QPushButton('⬇  Baixar Arquivo / Download File')
        self._btn_dl.setMinimumHeight(36)
        self._btn_dl.setStyleSheet(
            'QPushButton{background:#0f9d58;color:white;font-weight:bold;'
            'font-size:12px;border-radius:4px;}'
            'QPushButton:hover{background:#0b7842;}'
            'QPushButton:disabled{background:#aaa;}')
        self._btn_dl.clicked.connect(self._on_download)
        self._btn_dl.setEnabled(False)
        dl_row.addWidget(self._btn_dl, 3)

        self._btn_dl_cancel = QPushButton('✕')
        self._btn_dl_cancel.setMinimumHeight(36)
        self._btn_dl_cancel.setFixedWidth(40)
        self._btn_dl_cancel.setEnabled(False)
        self._btn_dl_cancel.setToolTip('Cancelar download / Cancel download')
        self._btn_dl_cancel.setStyleSheet(
            'QPushButton{background:#e53935;color:white;font-weight:bold;'
            'border-radius:4px;}'
            'QPushButton:hover{background:#b71c1c;}'
            'QPushButton:disabled{background:#ccc; color:#888;}')
        self._btn_dl_cancel.clicked.connect(self._on_dl_cancel)
        dl_row.addWidget(self._btn_dl_cancel)

        self._btn_open_folder = QPushButton('📂')
        self._btn_open_folder.setMinimumHeight(36)
        self._btn_open_folder.setFixedWidth(40)
        self._btn_open_folder.setEnabled(False)
        self._btn_open_folder.setToolTip(
            'Abrir pasta do download / Open download folder')
        self._btn_open_folder.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;'
            'border-radius:4px;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#ccc; color:#888;}')
        self._btn_open_folder.clicked.connect(self._open_dl_folder)
        dl_row.addWidget(self._btn_open_folder)

        right_lay.addLayout(dl_row)

        self._lbl_status = QLabel('')
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setAlignment(_ALIGN_CENTER)
        self._lbl_status.setStyleSheet('font-size:10px; color:#555;')
        right_lay.addWidget(self._lbl_status)

        splitter.addWidget(right_w)
        splitter.setSizes([210, 490])
        root.addWidget(splitter)

        if self._list_datasets.count() > 0:
            self._list_datasets.setCurrentRow(0)

    def _sep(self, layout):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

    # ── Dataset selection ─────────────────────────────────────────────────────

    def _on_dataset_selected(self, current, _previous):
        if current is None:
            return
        ds = current.data(Qt.UserRole)
        self._current_ds   = ds
        self._all_features = []
        self._page         = 0
        self._txt_desc.setPlainText(ds['description'])
        self._list_results.clear()
        self._btn_dl.setEnabled(False)
        self._lbl_page.setText('')
        self._btn_prev.setEnabled(False)
        self._btn_next.setEnabled(False)
        self._btn_open_folder.setEnabled(False)
        self._cancel_search_threads()
        self._fetch_all(ds['collection'])

    def _cancel_search_threads(self):
        for t in (self._search_thread, self._thumb_thread):
            if t and t.isRunning():
                t.cancel()
                try:
                    t.result.disconnect()
                    t.error.disconnect()
                    t.thumbnail_ready.disconnect()
                except Exception:  # nosec B110
                    pass

    def _fetch_all(self, collection):
        self._status('Buscando dados... / Fetching data...')
        self._search_thread = _MeteoSearchThread(collection, parent=self)
        self._search_thread.result.connect(self._on_search_done)
        self._search_thread.error.connect(self._on_search_error)
        self._search_thread.start()

    # ── Search results ────────────────────────────────────────────────────────

    def _on_search_done(self, features):
        self._all_features = features
        self._page = 0
        if not features:
            self._status(
                'Nenhum item encontrado para este dataset. / '
                'No items found for this dataset.')
            return
        self._render_page()
        self._status('{} item(ns) no total. / {} item(s) total.'.format(
            len(features), len(features)))

    def _on_search_error(self, msg):
        coll = self._current_ds['collection'] if self._current_ds else '?'
        self._status('Erro ao buscar {} / Search error {}: {}'.format(coll, coll, msg))

    # ── Pagination ────────────────────────────────────────────────────────────

    def _render_page(self):
        self._list_results.clear()
        if self._thumb_thread and self._thumb_thread.isRunning():
            self._thumb_thread.cancel()

        n_total = len(self._all_features)
        n_pages = max(1, (n_total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        start   = self._page * _PAGE_SIZE
        end     = min(start + _PAGE_SIZE, n_total)
        page_features = self._all_features[start:end]

        self._lbl_page.setText('Página / Page {}/{} ({} items)'.format(
            self._page + 1, n_pages, n_total))
        self._btn_prev.setEnabled(self._page > 0)
        self._btn_next.setEnabled(self._page < n_pages - 1)

        thumb_items = []
        for row, f in enumerate(page_features):
            item = QListWidgetItem(self._feature_label(f))
            item.setData(Qt.UserRole, f)
            self._list_results.addItem(item)

            thumb_url = None
            assets = f.get('assets', {})
            if 'thumbnail' in assets:
                thumb_url = assets['thumbnail'].get('href')
            thumb_items.append((row, thumb_url))

        self._list_results.setCurrentRow(0)
        self._btn_dl.setEnabled(bool(page_features))

        self._thumb_thread = _ThumbnailLoader(thumb_items, parent=self)
        self._thumb_thread.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._thumb_thread.start()

    def _on_prev_page(self):
        if self._page > 0:
            self._page -= 1
            self._render_page()

    def _on_next_page(self):
        n_total = len(self._all_features)
        n_pages = max(1, (n_total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        if self._page < n_pages - 1:
            self._page += 1
            self._render_page()

    # ── Thumbnails ────────────────────────────────────────────────────────────

    def _on_thumbnail_ready(self, row, data):
        pixmap = QPixmap()
        if isinstance(data, bytes) and pixmap.loadFromData(data):
            scaled = pixmap.scaled(96, 58, _KEEP_RATIO, _SMOOTH)
            item = self._list_results.item(row)
            if item:
                item.setIcon(QIcon(scaled))

    # ── Download ──────────────────────────────────────────────────────────────

    def _on_download(self, *_):
        if self._download_thread and self._download_thread.isRunning():
            self._status(
                'Download em andamento. Aguarde ou cancele. / '
                'Download in progress. Wait or cancel.')
            return

        feature = self._selected_feature()
        if feature is None:
            self._status('Selecione um item na lista. / Select an item from the list.')
            return

        assets = feature.get('assets', {})
        if not assets:
            self._status('Item sem assets. / Item has no assets.')
            return

        ds          = self._current_ds
        raster_exts = ds.get('raster_exts', ['.nc', '.grib2', '.grb2', '.gz', '.tif'])
        skip_keys   = {'thumbnail', 'ctl', 'idx', 'B02_1km'}

        chosen_href = None
        chosen_key  = None

        # Preferred asset keys first
        for pref in ds.get('asset_keys', []):
            if pref in assets:
                href = assets[pref].get('href', '')
                if href and any(href.lower().endswith(ext) for ext in raster_exts):
                    chosen_href = href
                    chosen_key  = pref
                    break

        # Fallback: first asset with matching extension
        if not chosen_href:
            for akey, aval in assets.items():
                if akey in skip_keys:
                    continue
                href = aval.get('href', '')
                if href and any(href.lower().endswith(ext) for ext in raster_exts):
                    chosen_href = href
                    chosen_key  = akey
                    break

        # Last resort: any non-thumbnail asset
        if not chosen_href:
            for akey, aval in assets.items():
                if akey in skip_keys:
                    continue
                href = aval.get('href', '')
                if href:
                    chosen_href = href
                    chosen_key  = akey
                    break

        if not chosen_href:
            self._status(
                u'Nenhum asset baixável encontrado. / No downloadable asset found.')
            return

        # Filename from URL
        url_path = chosen_href.split('?')[0]
        filename = url_path.split('/')[-1] or 'meteo_asset'

        folder = QFileDialog.getExistingDirectory(
            self,
            'Selecionar Pasta de Download / Select Download Folder',
            self._last_dl_folder)
        if not folder:
            return

        self._last_dl_folder = folder
        dest_path            = os.path.join(folder, filename)

        self._btn_dl.setEnabled(False)
        self._btn_dl_cancel.setEnabled(True)
        self._btn_open_folder.setEnabled(False)
        self._status('Iniciando: {} / Starting: {}'.format(filename, filename))

        self._download_thread = _DownloadThread(chosen_href, dest_path, parent=self)
        self._download_thread.progress.connect(self._on_dl_progress)
        self._download_thread.done.connect(self._on_dl_done)
        self._download_thread.error.connect(self._on_dl_error)
        self._download_thread.start()

    def _on_dl_cancel(self):
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.cancel()
        self._btn_dl_cancel.setEnabled(False)
        self._status('Cancelando... / Cancelling...')

    @staticmethod
    def _fmt_bytes(b):
        if b >= 1_048_576:
            return '{:.1f} MB'.format(b / 1_048_576)
        elif b >= 1024:
            return '{:.0f} KB'.format(b / 1024)
        return '{} B'.format(b)

    def _on_dl_progress(self, done_bytes, total_bytes):
        if total_bytes > 0:
            pct = int(done_bytes / total_bytes * 100)
            msg = 'Baixando / Downloading: {} / {} ({}%)'.format(
                self._fmt_bytes(done_bytes), self._fmt_bytes(total_bytes), pct)
        else:
            msg = 'Baixando / Downloading: {}'.format(self._fmt_bytes(done_bytes))
        self._status(msg)

    def _on_dl_done(self, dest_path):
        self._btn_dl.setEnabled(True)
        self._btn_dl_cancel.setEnabled(False)
        self._btn_open_folder.setEnabled(True)
        self._last_dl_folder = os.path.dirname(dest_path)
        filename = os.path.basename(dest_path)
        self._status(
            '✅  Concluído: {} / Complete: {}'.format(filename, filename))
        if self.iface:
            self.iface.messageBar().pushMessage(
                'RTH Meteorologia',
                'Arquivo baixado: {} / File downloaded: {}'.format(
                    filename, filename),
                level=Qgis.MessageLevel.Success, duration=6)

    def _on_dl_error(self, msg):
        self._btn_dl.setEnabled(True)
        self._btn_dl_cancel.setEnabled(False)
        self._status('Erro / Error: {}'.format(msg))

    def _open_dl_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_dl_folder))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _selected_feature(self):
        item = self._list_results.currentItem()
        if item:
            f = item.data(Qt.UserRole)
            if f:
                return f
        row = self._list_results.currentRow()
        if row >= 0:
            idx = self._page * _PAGE_SIZE + row
            if 0 <= idx < len(self._all_features):
                return self._all_features[idx]
        return None

    def _feature_label(self, feature):
        try:
            fid   = feature.get('id', '—')
            props = feature.get('properties', {})
            dt    = (props.get('datetime')
                     or props.get('start_datetime', ''))[:16].replace('T', '  ')
            return '{}  |  {}'.format(dt, fid[:50])
        except Exception:
            return feature.get('id', '—')

    def _status(self, msg):
        self._lbl_status.setText(msg)
        QApplication.processEvents()

    def closeEvent(self, event):
        self._cancel_search_threads()
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.cancel()
            self._download_thread.wait(3000)
        super().closeEvent(event)


# ── Tool entry point ──────────────────────────────────────────────────────────

class MeteoDataTool:

    def __init__(self, iface):
        self.iface = iface
        self._dlg  = None

    def run(self):
        if self._dlg is None:
            self._dlg = MeteoDataDialog(self.iface, parent=self.iface.mainWindow())
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
