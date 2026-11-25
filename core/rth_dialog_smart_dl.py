# -*- coding: utf-8 -*-
"""
rth_dialog_smart_dl — Download Inteligente para Mapeamento Agrícola
rth_dialog_smart_dl — Smart Download for Agricultural Mapping

Fluxo / Flow:
  1. Usuário escolhe satélite, provedor, datas e cultura mapeada.
     User chooses satellite, provider, dates and crop culture.
  2. "Iniciar" divide o intervalo em quinzenas (1–15 e 16–fim do mês).
     "Start" splits the range into fortnights (1–15 and 16–end of month).
  3. Para cada quinzena, busca STAC e escolhe a cena com menos nuvens.
     For each fortnight, searches STAC and picks the least-cloudy scene.
  4. Baixa imagem stack com todas as bandas necessárias para a cultura.
     Downloads a multi-band stack with all bands needed for the culture.
  5. Após conclusão, gera composições derivadas via GDAL/vsimem (extração de bandas
     do stack em memória — sem download adicional).
     After completion, generates derived composites via GDAL/vsimem (band extraction
     from in-memory stack — no additional download).

Culturas / Cultures:
  Soja/Milho/Cana  → stack NIR-SWIR-RED (1 composição)
  Algodão          → stack NIR-SWIR-RED-GREEN-BLUE → NIR-SWIR-RED  +  RED-GREEN-BLUE
  Café             → stack NIR-GREEN-BLUE-RED       → NIR-G-B       +  B-R-G
  Silvicultura     → stack NIR-BLUE-GREEN (1 composição)

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

import os
import calendar
from datetime import date, timedelta

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QScrollArea, QGridLayout,
    QFrame, QLineEdit, QFileDialog,
)
from qgis.PyQt.QtCore import Qt, QThread, QThreadPool, QRunnable, QObject, pyqtSignal

try:
    _ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
except AttributeError:
    _ALIGN_CENTER = Qt.AlignCenter

try:
    _ALIGN_TOP = Qt.AlignmentFlag.AlignTop
except AttributeError:
    _ALIGN_TOP = Qt.AlignTop

# ── Catálogo de bandas por coleção ────────────────────────────────────────────

_BAND_KEYS = {
    'S2_L2A-1':             {'NIR': 'B08', 'SWIR': 'B11', 'RED': 'B04', 'GREEN': 'B03', 'BLUE': 'B02'},
    'S2-16D-2':             {'NIR': 'B08', 'SWIR': 'B11', 'RED': 'B04', 'GREEN': 'B03', 'BLUE': 'B02'},
    'sentinel-2-l2a':       {'NIR': 'B08', 'SWIR': 'B11', 'RED': 'B04', 'GREEN': 'B03', 'BLUE': 'B02'},
    'sentinel-2-l2a-aws':   {'NIR': 'B08', 'SWIR': 'B11', 'RED': 'B04', 'GREEN': 'B03', 'BLUE': 'B02'},
    'landsat-2':            {'NIR': 'nir08', 'SWIR': 'swir16', 'RED': 'red', 'GREEN': 'green', 'BLUE': 'blue'},
    'LANDSAT-16D-1':        {'NIR': 'nir08', 'SWIR': 'swir16', 'RED': 'red', 'GREEN': 'green', 'BLUE': 'blue'},
    'landsat-c2-l2':        {'NIR': 'nir08', 'SWIR': 'swir16', 'RED': 'red', 'GREEN': 'green', 'BLUE': 'blue'},
}

# Satélites e coleções disponíveis (apenas Sentinel-2 e Landsat)
SMART_SATELLITES = [
    ('Sentinel-2', [
        ('S2_L2A-1',           'Sentinel-2 — Imagens  [INPE/BDC]  (Brazil Only)'),
        ('S2-16D-2',           'Sentinel-2 — DataCube 16 dias  [INPE/BDC]  (Brazil Only)'),
        ('sentinel-2-l2a',     'Sentinel-2 — Global  [Planetary Computer]'),
        ('sentinel-2-l2a-aws', 'Sentinel-2 — Global  [AWS Element84]'),
    ]),
    ('Landsat', [
        ('landsat-2',     'Landsat 5·7·8·9 — Imagens  [INPE/BDC]  (Brazil Only)'),
        ('LANDSAT-16D-1', 'Landsat — DataCube 16 dias  [INPE/BDC]  (Brazil Only)'),
        ('landsat-c2-l2', 'Landsat 4·5·7·8·9 — Global  [Planetary Computer]'),
    ]),
]

# Culturas e suas configurações de composição
CULTURE_CONFIGS = {
    'SOY_CORN_SUGAR': {
        'label': 'Soja / Milho / Cana — NIR-SWIR-RED',
        # Papéis de banda para a composição primária (3 bandas)
        'primary_roles':  ('NIR', 'SWIR', 'RED'),
        'primary_suffix': 'SDL_NIR_SWIR_RED',
        # Bandas extras para composição derivada: [(papel, sufixo_arquivo), ...]
        'extra_roles': [],
        # Composição derivada: None = sem derivada
        'derived': None,
    },
    'COTTON': {
        'label': 'Algodão / Cotton — NIR-SWIR-RED + RGB',
        # Baixa 1 stack com as 5 bandas. O GDAL extrai bandas em vsimem para montar
        # os 2 compostos sem download adicional.
        # Downloads 1 five-band stack. GDAL extracts bands via vsimem to produce
        # both composites without an additional download.
        'primary_roles':  ('NIR', 'SWIR', 'RED', 'GREEN', 'BLUE'),
        'primary_suffix': 'SDL_STACK',
        'extra_roles': [],
        'derived': None,
        'derived_list': [
            {
                'suffix':  'SDL_NIR_SWIR_RED',
                'sources': [('primary', 1), ('primary', 2), ('primary', 3)],
                'desc':    'NIR-SWIR-RED',
            },
            {
                'suffix':  'SDL_RGB',
                'sources': [('primary', 3), ('primary', 4), ('primary', 5)],
                'desc':    'RED-GREEN-BLUE',
            },
        ],
    },
    'COFFEE': {
        'label': 'Café / Coffee — NIR-G-B + B-R-G',
        # Baixa 1 stack com 4 bandas. O GDAL extrai e reordena as bandas em vsimem
        # para gerar NIR-G-B e B-R-G sem download adicional.
        # Downloads 1 four-band stack. GDAL extracts and reorders bands via vsimem
        # to produce NIR-G-B and B-R-G without an additional download.
        'primary_roles':  ('NIR', 'GREEN', 'BLUE', 'RED'),
        'primary_suffix': 'SDL_STACK',
        'extra_roles': [],
        'derived': None,
        'derived_list': [
            {
                'suffix':  'SDL_NIR_G_B',
                'sources': [('primary', 1), ('primary', 2), ('primary', 3)],
                'desc':    'NIR-G-B',
            },
            {
                'suffix':  'SDL_B_R_G',
                'sources': [('primary', 3), ('primary', 4), ('primary', 2)],
                'desc':    'B-R-G',
            },
        ],
    },
    'FORESTRY': {
        'label': 'Silvicultura / Forestry — NIR-Blue-Green',
        'primary_roles':  ('NIR', 'BLUE', 'GREEN'),
        'primary_suffix': 'SDL_NIR_B_G',
        'extra_roles': [],
        'derived': None,
    },
}


# ── Helpers de quinzena e nuvens ──────────────────────────────────────────────

def _split_quinzenas(start_date, end_date):
    """Divide o intervalo em períodos de 15 dias (1→15 e 16→fim do mês) /
    Split the interval into 15-day periods (1→15 and 16→end of month).

    :returns: lista de (data_inicio, data_fim) / list of (start_date, end_date)
    """
    intervals = []
    current = start_date
    while current <= end_date:
        if current.day <= 15:
            last = min(date(current.year, current.month, 15), end_date)
        else:
            last_day = calendar.monthrange(current.year, current.month)[1]
            last = min(date(current.year, current.month, last_day), end_date)
        intervals.append((current, last))
        current = last + timedelta(days=1)
    return intervals


def _best_feature(features):
    """Retorna a feature com menor cobertura de nuvens / Return feature with lowest cloud cover.

    :returns: feature GeoJSON ou None
    """
    if not features:
        return None

    def _cloud(f):
        v = f.get('properties', {}).get('eo:cloud_cover')
        return float(v) if v is not None else 100.0

    return min(features, key=_cloud)


def _cloud_pct(feature):
    """Retorna a % de nuvens formatada / Return formatted cloud cover %."""
    v = (feature.get('properties') or {}).get('eo:cloud_cover')
    if v is None:
        return 'N/A'
    return '{:.1f}%'.format(float(v))


def _band_tuple_for(collection_id, roles, culture_config):
    """Resolve os nomes reais de banda para os papéis solicitados /
    Resolve real band names for the requested roles."""
    keys = _BAND_KEYS.get(collection_id, {})
    return tuple(keys.get(r, r) for r in roles)


# ── Thread de busca das melhores cenas ───────────────────────────────────────

class _SmartSearchThread(QThread):
    """Busca sequencialmente a melhor cena de cada quinzena /
    Sequentially search for the best scene in each fortnight."""

    progress = pyqtSignal(str)                   # mensagem de status / status message
    found    = pyqtSignal(list)                  # [(label, feature_or_None), ...]
    failed   = pyqtSignal(str)

    def __init__(self, collection_id, bbox, quinzenas):
        super().__init__()
        self._collection_id = collection_id
        self._bbox          = bbox
        self._quinzenas     = quinzenas

    def run(self):
        from .rth_stac_api import _route_for, STAC_PC, search_stac, search_stac_pc
        results = []
        n = len(self._quinzenas)
        for i, (q_start, q_end) in enumerate(self._quinzenas):
            label = '{} → {}'.format(q_start.strftime('%d/%m/%Y'),
                                      q_end.strftime('%d/%m/%Y'))
            self.progress.emit('[{}/{}] {} ...'.format(i + 1, n, label))
            date_ini = q_start.isoformat() + 'T00:00:00Z'
            date_fim = q_end.isoformat() + 'T23:59:59Z'
            try:
                endpoint, _ = _route_for(self._collection_id)
                if endpoint == STAC_PC:
                    # search_stac_pc retorna (features, total, next_body, prev_body)
                    feats = search_stac_pc(
                        self._collection_id, self._bbox,
                        date_ini, date_fim, 100)[0]
                else:
                    feats = search_stac(
                        self._collection_id, self._bbox,
                        date_ini, date_fim, 100,
                        page=1, limit=100)[0]
                best = _best_feature(feats)
            except Exception as exc:
                best = None
            results.append((label, best))
        self.found.emit(results)


# ── Worker de composição derivada ─────────────────────────────────────────────

class _DerivedSignals(QObject):
    """Sinais emitidos pelo worker de composição derivada /
    Signals emitted by the derived composite worker."""
    progress = pyqtSignal(str)


class _DerivedCompositeWorker(QRunnable):
    """Cria composição derivada combinando bandas de arquivos já baixados /
    Create derived composite by combining bands from already-downloaded files.

    Usa gdal.Translate (extração de banda) + gdal.BuildVRT (separar bandas) +
    gdal.Translate (GeoTIFF final) — tudo via vsimem (sem arquivos temporários em disco).

    Uses gdal.Translate (band extraction) + gdal.BuildVRT (separate bands) +
    gdal.Translate (final GeoTIFF) — all via vsimem (no temp files on disk).

    Os sinais QObject em `self.signals` garantem entrega na thread principal via
    fila de eventos do Qt — seguro para atualizar widgets de UI.
    The QObject signals in `self.signals` guarantee delivery on the main thread via
    Qt event queue — safe to update UI widgets.
    """

    def __init__(self, primary_path, extra_paths, sources, output_path, label, band_names=None):
        """
        :param primary_path: caminho do GeoTIFF primário (3 bandas) / primary GeoTIFF path (3 bands)
        :param extra_paths:  lista de caminhos de bandas extras (1 banda cada) / list of extra band paths (1 band each)
        :param sources:      [(tipo, idx)] onde tipo='primary'|'extra' e idx é banda 1-based (primary) ou índice (extra)
        :param output_path:  caminho do GeoTIFF derivado de saída / output derived GeoTIFF path
        :param label:        rótulo para logs / label for logs
        :param band_names:   lista de nomes de banda para gravar no GeoTIFF / list of band names to write into GeoTIFF
        """
        super().__init__()
        self._primary_path = primary_path
        self._extra_paths  = extra_paths
        self._sources      = sources
        self._output_path  = output_path
        self._label        = label
        self._band_names   = band_names or []
        self.signals       = _DerivedSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            self._build()
        except Exception as exc:
            self.signals.progress.emit('{}: erro na derivada — {} / derived error — {}'.format(
                self._label, exc, exc))

    def _build(self):
        try:
            from osgeo import gdal as _gdal
        except ImportError:
            return

        vsimem = []
        sources = []

        for source_type, source_idx in self._sources:
            if source_type == 'primary':
                tmp = '/vsimem/sdl_p{}_{}_{}.tif'.format(
                    source_idx,
                    os.path.basename(self._primary_path)[:20],
                    id(self))
                _gdal.Translate(tmp, self._primary_path, bandList=[source_idx], format='GTiff')
                sources.append(tmp)
                vsimem.append(tmp)
            else:  # 'extra'
                ep = self._extra_paths[source_idx] if source_idx < len(self._extra_paths) else None
                if not ep or not os.path.isfile(ep):
                    self.signals.progress.emit('{}: banda extra {} ausente / extra band {} missing'.format(
                        self._label, source_idx, source_idx))
                    for p in vsimem:
                        try: _gdal.Unlink(p)
                        except: pass  # nosec B110
                    return
                sources.append(ep)

        vrt = '/vsimem/sdl_vrt_{}.vrt'.format(id(self))
        vrt_ds = _gdal.BuildVRT(vrt, sources, separate=True)
        if vrt_ds is None:
            for p in vsimem + [vrt]:
                try: _gdal.Unlink(p)
                except: pass  # nosec B110
            return
        del vrt_ds

        _gdal.Translate(
            self._output_path, vrt,
            format='GTiff',
            creationOptions=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=IF_SAFER'])

        if self._band_names and os.path.isfile(self._output_path):
            out_ds = _gdal.Open(self._output_path, _gdal.GA_Update)
            if out_ds:
                for i, name in enumerate(self._band_names, 1):
                    b = out_ds.GetRasterBand(i)
                    if b:
                        b.SetDescription(str(name))
                out_ds.FlushCache()
                del out_ds

        for p in vsimem + [vrt]:
            try: _gdal.Unlink(p)
            except: pass  # nosec B110

        self.signals.progress.emit('{}: ✓ derivada criada — {} / derived created — {}'.format(
            self._label, os.path.basename(self._output_path),
            os.path.basename(self._output_path)))


# ── Tracker por cena — coordena download primário + extras + derivada ─────────

class _SceneTracker(QObject):
    """Acompanha os downloads de uma cena e dispara a derivada ao concluir.
    Tracks downloads for one scene and fires derived composite on completion.

    É um QObject para que seu sinal `status` seja entregue via fila de eventos
    do Qt na thread principal — seguro para atualizar widgets de UI a partir de
    threads de download.
    Is a QObject so its `status` signal is delivered via Qt event queue on the
    main thread — safe to update UI widgets from download threads.
    """

    status       = pyqtSignal(str)
    # Emitido após _build() terminar — garante que a camada primária só
    # entra no QGIS depois de toda composição derivada estar concluída.
    # Emitted after _build() finishes — ensures the primary layer is only
    # added to QGIS after all derived composites are complete.
    layer_ready  = pyqtSignal(str, str, object)

    def __init__(self, scene_id, output_dir, derived_configs, primary_roles=None):
        """
        :param derived_configs: lista de dicts de composição derivada, ou [] para nenhuma /
                                list of derived composite dicts, or [] for none
        :param primary_roles:   tupla de papéis de banda do stack primário, ex: ('NIR', 'SWIR', 'RED') /
                                tuple of primary stack band roles, e.g. ('NIR', 'SWIR', 'RED')
        """
        super().__init__()
        self.scene_id         = scene_id
        self.output_dir       = output_dir
        self._derived_configs = derived_configs or []
        self._primary_roles   = list(primary_roles) if primary_roles else []
        self.primary_path     = None
        self._pending_layer   = None  # (path, name, feature) — aguarda fim do _build
        self._extra_paths     = {}    # idx → path
        self._extra_count     = 0
        self._remaining       = 0     # set after construction via set_total()

    def set_total(self, total):
        self._remaining = total

    def set_extra_count(self, n):
        self._extra_count = n
        self._extra_paths = {}

    def on_primary_ready(self, path, name, feature):
        self.primary_path   = path
        self._pending_layer = (path, name, feature)

    def on_extra_ready(self, idx, path, name, feature):
        self._extra_paths[idx] = path

    def on_download_done(self, count):
        self._remaining -= 1
        if self._remaining <= 0:
            self._maybe_derive()

    def _maybe_derive(self):
        # Runs entirely on the main thread (called from a queued-connection slot).
        # _build() reads self.primary_path; we must NOT add it to QGIS yet —
        # if QGIS render thread starts reading the same file concurrently we get
        # a GDAL block-cache race → SEGFAULT. layer_ready is emitted at the very
        # end so addMapLayer() only happens after _build() releases all handles.
        if self._derived_configs:
            # Verifica se o primary está pronto apenas quando alguma fonte o referencia.
            # Check primary only when at least one source references it.
            needs_primary = any(
                src[0] == 'primary'
                for dcfg in self._derived_configs
                for src in dcfg['sources']
            )
            if needs_primary and (not self.primary_path or not os.path.isfile(self.primary_path)):
                # Primary missing — skip derived but still add primary layer to QGIS.
                if self._pending_layer is not None:
                    self.layer_ready.emit(*self._pending_layer)
                return
            extra_list = [self._extra_paths.get(i) for i in range(self._extra_count)]
            if any(p is None for p in extra_list):
                self.status.emit(
                    '{}: bandas extras incompletas — composições canceladas / '
                    'extra bands incomplete — composites cancelled'.format(self.scene_id[:20]))
                if self._pending_layer is not None:
                    self.layer_ready.emit(*self._pending_layer)
                return
            from .rth_layer_utils import safe_id
            sid = safe_id(self.scene_id)
            for dcfg in self._derived_configs:
                out = os.path.join(self.output_dir,
                                   '{}_{}.tif'.format(sid, dcfg['suffix']))
                # Reconstrói os nomes de banda da derivada a partir dos papéis do stack primário.
                # Reconstruct derived band names from primary stack roles.
                derived_band_names = None
                if self._primary_roles:
                    derived_band_names = [
                        self._primary_roles[src_idx - 1]
                        for src_type, src_idx in dcfg['sources']
                        if src_type == 'primary' and 0 < src_idx <= len(self._primary_roles)
                    ]
                worker = _DerivedCompositeWorker(
                    self.primary_path, extra_list,
                    dcfg['sources'], out,
                    '{} {}'.format(self.scene_id[:22], dcfg['desc']),
                    band_names=derived_band_names)
                worker.signals.progress.connect(self.status)
                # Executa SINCRONAMENTE na thread principal — NÃO usar QThreadPool.
                # O GDAL não é thread-safe: gdal.Warp (DownloadThread) e gdal.Translate/
                # BuildVRT (worker derivado) em threads paralelas causam race condition
                # no cache global do vsicurl → crash. Como o Qt entrega os sinais
                # finished_sig em ordem de conexão, chamar run() aqui garante que a
                # derivada termina ANTES de _on_dl_group_done avançar para a próxima cena.
                # Runs SYNCHRONOUSLY on main thread — do NOT use QThreadPool.
                # GDAL is not thread-safe: concurrent gdal.Warp (DownloadThread) and
                # gdal.Translate/BuildVRT (derived worker) race on the global vsicurl
                # cache → crash. Qt delivers finished_sig slots in connection order,
                # so calling run() here ensures the derived work completes BEFORE
                # _on_dl_group_done advances to the next scene's download.
                worker.run()

        # Emite layer_ready DEPOIS de todo _build() — o QGIS só recebe a camada
        # primária após o GDAL ter fechado todos os handles, eliminando a race
        # condition entre o render thread do QGIS e o _build() lendo o mesmo arquivo.
        # Emits layer_ready AFTER all _build() calls — QGIS only receives the primary
        # layer after GDAL has closed all handles, eliminating the race condition
        # between QGIS render thread and _build() reading the same file.
        if self._pending_layer is not None:
            self.layer_ready.emit(*self._pending_layer)


# ── Mixin da aba Download Inteligente ─────────────────────────────────────────

class SmartDlMixin:
    """Mixin que adiciona a aba 'Download Inteligente para Mapeamento' /
    Mixin that adds the 'Smart Download for Mapping' tab.

    Depende de ActionsMixin (_dl_inner, _dl_layout, _download_rows,
    _enqueue_prebuilt_groups, _update_dl_tab_label, _on_layer_ready,
    _on_dl_row_removed, edit_pasta).

    Depends on ActionsMixin (_dl_inner, _dl_layout, _download_rows,
    _enqueue_prebuilt_groups, _update_dl_tab_label, _on_layer_ready,
    _on_dl_row_removed, edit_pasta).
    """

    def _init_smart_dl(self):
        """Inicializa variáveis de estado / Initialize state variables."""
        self._smart_search_thread = None
        self._smart_quinzenas     = []
        # _smart_trackers mantém referências Python fortes aos _SceneTracker.
        # PyQt armazena QObjects via referência FRACA nas conexões de sinal;
        # sem esta lista, os trackers seriam coletados pelo GC logo após
        # _queue_smart_downloads retornar, desconectando todos os sinais e
        # impedindo que layer_ready chegue ao _on_layer_ready.
        # _smart_trackers holds strong Python refs to _SceneTracker instances.
        # PyQt stores QObjects via WEAK ref in signal connections; without this
        # list the trackers would be GC'd right after _queue_smart_downloads
        # returns, disconnecting all signals and preventing layer_ready from
        # reaching _on_layer_ready.
        self._smart_trackers = []

    def _setup_smart_dl_panel(self):
        """Monta o painel de download inteligente / Build the smart download panel."""
        self._smart_dl_panel = QWidget(self)
        self._smart_dl_panel.setVisible(False)

        layout = QVBoxLayout(self._smart_dl_panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ── Título ────────────────────────────────────────────────────────────
        lbl_title = QLabel('⬇  Download Inteligente para Mapeamento / Smart Download for Mapping')
        lbl_title.setStyleSheet(
            'font-size:13px; font-weight:bold; color:#1a73e8; padding-bottom:2px;')
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            'Divide o período em quinzenas, escolhe a cena com menos nuvens por quinzena e baixa automaticamente. / '
            'Splits the period into fortnights, picks the least-cloudy scene per fortnight and downloads automatically.')
        lbl_desc.setStyleSheet('font-size:10px; color:#888; font-style:italic;')
        lbl_desc.setWordWrap(True)
        layout.addWidget(lbl_desc)

        _sep = QFrame()
        try:
            _sep.setFrameShape(QFrame.Shape.HLine)
            _sep.setFrameShadow(QFrame.Shadow.Sunken)
        except AttributeError:
            _sep.setFrameShape(QFrame.HLine)
            _sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(_sep)

        # ── Pasta de saída ────────────────────────────────────────────────────
        row_pasta = QHBoxLayout()
        row_pasta.setSpacing(8)

        lbl_pasta = QLabel('Pasta de saída / Output folder:')
        lbl_pasta.setFixedWidth(145)
        lbl_pasta.setStyleSheet('font-size:11px;')
        row_pasta.addWidget(lbl_pasta)

        self._smart_edit_pasta = QLineEdit()
        self._smart_edit_pasta.setStyleSheet('font-size:11px;')
        self._smart_edit_pasta.setPlaceholderText(
            'Selecione uma pasta... / Select a folder...')
        row_pasta.addWidget(self._smart_edit_pasta, 1)

        btn_pasta = QPushButton('📁')
        btn_pasta.setFixedWidth(32)
        btn_pasta.setToolTip('Selecionar pasta de saída / Select output folder')
        btn_pasta.clicked.connect(self._on_smart_browse_pasta)
        row_pasta.addWidget(btn_pasta)
        layout.addLayout(row_pasta)

        # ── Satélite + Provedor ───────────────────────────────────────────────
        row_sat = QHBoxLayout()
        row_sat.setSpacing(8)

        lbl_sat = QLabel('Satélite / Satellite:')
        lbl_sat.setFixedWidth(145)
        lbl_sat.setStyleSheet('font-size:11px;')
        row_sat.addWidget(lbl_sat)

        self._combo_smart_sat = QComboBox()
        self._combo_smart_sat.setStyleSheet('font-size:11px;')
        for sat_name, _ in SMART_SATELLITES:
            self._combo_smart_sat.addItem(sat_name)
        self._combo_smart_sat.currentIndexChanged.connect(self._on_smart_sat_changed)
        row_sat.addWidget(self._combo_smart_sat, 1)
        layout.addLayout(row_sat)

        row_col = QHBoxLayout()
        row_col.setSpacing(8)
        lbl_col = QLabel('Provedor / Provider:')
        lbl_col.setFixedWidth(145)
        lbl_col.setStyleSheet('font-size:11px;')
        row_col.addWidget(lbl_col)

        self._combo_smart_col = QComboBox()
        self._combo_smart_col.setStyleSheet('font-size:11px;')
        row_col.addWidget(self._combo_smart_col, 1)
        layout.addLayout(row_col)

        # ── Datas ─────────────────────────────────────────────────────────────
        row_dates = QHBoxLayout()
        row_dates.setSpacing(8)

        lbl_di = QLabel('Data inicial / Start date:')
        lbl_di.setFixedWidth(145)
        lbl_di.setStyleSheet('font-size:11px;')
        row_dates.addWidget(lbl_di)

        # Reutiliza o widget de data da aba Cenas (mesma referência) /
        # Reuse the date widget from the Scenes tab (same reference)
        from qgis.PyQt.QtWidgets import QDateEdit
        from qgis.PyQt.QtCore import QDate
        self._smart_date_ini = QDateEdit()
        self._smart_date_ini.setCalendarPopup(True)
        self._smart_date_ini.setDate(QDate.currentDate().addMonths(-4))
        self._smart_date_ini.setDisplayFormat('yyyy-MM-dd')
        self._smart_date_ini.setStyleSheet('font-size:11px;')
        row_dates.addWidget(self._smart_date_ini)

        lbl_df = QLabel('Data final / End date:')
        lbl_df.setFixedWidth(130)
        lbl_df.setStyleSheet('font-size:11px;')
        row_dates.addWidget(lbl_df)

        self._smart_date_fim = QDateEdit()
        self._smart_date_fim.setCalendarPopup(True)
        self._smart_date_fim.setDate(QDate.currentDate())
        self._smart_date_fim.setDisplayFormat('yyyy-MM-dd')
        self._smart_date_fim.setStyleSheet('font-size:11px;')
        row_dates.addWidget(self._smart_date_fim)
        layout.addLayout(row_dates)

        # ── Cultura Mapeada ───────────────────────────────────────────────────
        row_cult = QHBoxLayout()
        row_cult.setSpacing(8)

        lbl_cult = QLabel('Cultura Mapeada / Crop:')
        lbl_cult.setFixedWidth(145)
        lbl_cult.setStyleSheet('font-size:11px;')
        row_cult.addWidget(lbl_cult)

        self._combo_smart_culture = QComboBox()
        self._combo_smart_culture.setStyleSheet('font-size:11px;')
        for key, cfg in CULTURE_CONFIGS.items():
            self._combo_smart_culture.addItem(cfg['label'], key)
        self._combo_smart_culture.currentIndexChanged.connect(self._on_smart_culture_changed)
        row_cult.addWidget(self._combo_smart_culture, 1)
        layout.addLayout(row_cult)

        # ── Nota sobre café ───────────────────────────────────────────────────
        self._lbl_smart_culture_note = QLabel('')
        self._lbl_smart_culture_note.setStyleSheet(
            'font-size:10px; color:#888; font-style:italic; padding-left:153px;')
        self._lbl_smart_culture_note.setWordWrap(True)
        layout.addWidget(self._lbl_smart_culture_note)
        self._on_smart_culture_changed(0)

        # ── Info: área de busca ───────────────────────────────────────────────
        self._lbl_smart_area = QLabel(
            'Área de busca: extensão atual do canvas (zoom para sua área de interesse antes de buscar). / '
            'Search area: current canvas extent (zoom to your area of interest before searching).')
        self._lbl_smart_area.setStyleSheet('font-size:10px; color:#888; font-style:italic;')
        self._lbl_smart_area.setWordWrap(True)
        layout.addWidget(self._lbl_smart_area)

        # ── Botão Iniciar ─────────────────────────────────────────────────────
        row_btn = QHBoxLayout()
        row_btn.addStretch()
        self._btn_smart_start = QPushButton('▶  Buscar e Baixar / Search & Download')
        self._btn_smart_start.setMinimumHeight(36)
        self._btn_smart_start.setFixedWidth(250)
        self._btn_smart_start.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;border-radius:4px;font-size:12px;font-weight:bold;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#aaa;color:#eee;}')
        self._btn_smart_start.clicked.connect(self._on_smart_start)
        row_btn.addWidget(self._btn_smart_start)
        layout.addLayout(row_btn)

        # ── Status ────────────────────────────────────────────────────────────
        self._lbl_smart_status = QLabel('')
        self._lbl_smart_status.setStyleSheet('font-size:11px; color:#555;')
        self._lbl_smart_status.setWordWrap(True)
        layout.addWidget(self._lbl_smart_status)

        # ── Área de resultado das quinzenas ───────────────────────────────────
        self._smart_scroll = QScrollArea()
        self._smart_scroll.setWidgetResizable(True)
        self._smart_scroll.setStyleSheet('QScrollArea{border:1px solid #ddd; border-radius:4px;}')
        _ph = QLabel(
            'As quinzenas e cenas encontradas aparecerão aqui após a busca.\n'
            'Fortnights and found scenes will appear here after the search.')
        _ph.setAlignment(_ALIGN_CENTER)
        _ph.setStyleSheet('color:#aaa; font-size:11px;')
        self._smart_scroll.setWidget(_ph)
        layout.addWidget(self._smart_scroll, 1)

        # Popula as coleções do satélite inicial / Populate collections for initial satellite
        self._on_smart_sat_changed(0)

    # ── Handlers de controle ──────────────────────────────────────────────────

    def _on_smart_sat_changed(self, idx):
        """Atualiza o combo de coleções ao mudar de satélite /
        Update the collections combo when satellite changes."""
        self._combo_smart_col.clear()
        sat_collections = SMART_SATELLITES[idx][1] if idx < len(SMART_SATELLITES) else []
        for col_id, col_label in sat_collections:
            self._combo_smart_col.addItem(col_label, col_id)

    def _on_smart_culture_changed(self, idx):
        """Atualiza a nota informativa conforme a cultura /
        Update the info note based on the selected culture."""
        key = self._combo_smart_culture.currentData() if hasattr(self, '_combo_smart_culture') else None
        if key == 'COFFEE':
            self._lbl_smart_culture_note.setText(
                'ℹ Café gera composições NIR-G-B e B-R-G. '
                'ESRI Satellite, Google Satellite e Bing Satellite serão adicionados automaticamente ao projeto. / '
                'Coffee generates NIR-G-B and B-R-G composites. '
                'ESRI Satellite, Google Satellite and Bing Satellite will be added automatically to the project.')
        else:
            self._lbl_smart_culture_note.setText('')

    def _on_smart_browse_pasta(self):
        """Abre o seletor de pasta de saída para o painel Smart DL /
        Opens the output folder picker for the Smart DL panel."""
        current = self._smart_edit_pasta.text().strip() or self.edit_pasta.text().strip()
        folder = QFileDialog.getExistingDirectory(
            None,
            'Selecionar pasta de saída / Select output folder',
            current)
        if folder:
            self._smart_edit_pasta.setText(folder)

    # ── Handler principal ─────────────────────────────────────────────────────

    def _on_smart_start(self):
        """Valida inputs, divide em quinzenas e inicia busca STAC em background /
        Validate inputs, split into fortnights and start STAC search in background."""
        collection_id = self._combo_smart_col.currentData()
        if not collection_id:
            self._lbl_smart_status.setText('Selecione um provedor. / Select a provider.')
            return

        output_dir = self._smart_edit_pasta.text().strip() or self.edit_pasta.text().strip()
        if not output_dir or not os.path.isdir(output_dir):
            self._lbl_smart_status.setText(
                'Pasta de saída inválida — selecione uma pasta acima ou defina em Cenas > Browse. / '
                'Invalid output folder — select a folder above or set it in Scenes > Browse.')
            return

        culture_key = self._combo_smart_culture.currentData()
        if not culture_key:
            return

        q_di = self._smart_date_ini.date()
        q_df = self._smart_date_fim.date()
        if q_di > q_df:
            self._lbl_smart_status.setText(
                'Data inicial maior que data final. / Start date after end date.')
            return

        from datetime import date as _date
        start = _date(q_di.year(), q_di.month(), q_di.day())
        end   = _date(q_df.year(), q_df.month(), q_df.day())

        self._smart_quinzenas = _split_quinzenas(start, end)
        n = len(self._smart_quinzenas)

        self._lbl_smart_status.setText(
            '{} quinzenas identificadas. Buscando cenas... / '
            '{} fortnights identified. Searching scenes...'.format(n, n))
        self._btn_smart_start.setEnabled(False)
        self._smart_scroll.setWidget(
            _make_status_label('Buscando... / Searching...'))

        from .rth_stac_api import get_bbox_from_canvas
        bbox = get_bbox_from_canvas(self.iface)

        if self._smart_search_thread and self._smart_search_thread.isRunning():
            self._smart_search_thread.quit()
            self._smart_search_thread.wait(500)

        self._smart_collection_id = collection_id
        self._smart_culture_key   = culture_key
        self._smart_output_dir    = output_dir

        self._smart_search_thread = _SmartSearchThread(collection_id, bbox, self._smart_quinzenas)
        self._smart_search_thread.progress.connect(self._on_smart_progress)
        self._smart_search_thread.found.connect(self._on_smart_found)
        self._smart_search_thread.failed.connect(self._on_smart_failed)
        self._smart_search_thread.start()

    def _on_smart_tracker_status(self, msg):
        """Slot guardado — ignora emissões após o dialog ter iniciado fechamento /
        Guarded slot — ignores emissions after the dialog has started closing."""
        if not getattr(self, '_dialog_closing', False):
            self._lbl_smart_status.setText(msg)

    def _on_smart_progress(self, msg):
        self._lbl_smart_status.setText(msg)

    def _on_smart_failed(self, err):
        self._lbl_smart_status.setText('Erro / Error: ' + err)
        self._btn_smart_start.setEnabled(True)

    def _on_smart_found(self, results):
        """Exibe quinzenas encontradas e inicia downloads /
        Display found fortnights and start downloads."""
        self._btn_smart_start.setEnabled(True)

        found    = [(lbl, f) for lbl, f in results if f is not None]
        not_found = [(lbl, f) for lbl, f in results if f is None]

        n_found = len(found)
        n_total = len(results)
        self._lbl_smart_status.setText(
            '{}/{} quinzenas com cena disponível. / '
            '{}/{} fortnights with available scene.'.format(n_found, n_total, n_found, n_total))

        # Monta painel de resultados / Build results panel
        inner  = QWidget()
        grid   = QGridLayout(inner)
        grid.setSpacing(4)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setAlignment(_ALIGN_TOP)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 4)
        grid.setColumnStretch(2, 1)

        # Cabeçalho / Header
        for col, txt in enumerate(['Quinzena / Fortnight', 'Cena ID / Scene ID', 'Nuvens / Clouds']):
            h = QLabel(txt)
            h.setStyleSheet('font-size:10px; font-weight:bold; color:#555;')
            grid.addWidget(h, 0, col)

        for row, (lbl, feat) in enumerate(results, 1):
            lbl_q = QLabel(lbl)
            lbl_q.setStyleSheet('font-size:11px;')
            grid.addWidget(lbl_q, row, 0)
            if feat:
                scene_id = feat.get('id', '?')
                short_id = scene_id[:45] + '…' if len(scene_id) > 45 else scene_id
                lbl_s = QLabel(short_id)
                lbl_s.setStyleSheet('font-size:10px; color:#1a73e8;')
                lbl_s.setToolTip(scene_id)
                grid.addWidget(lbl_s, row, 1)
                lbl_c = QLabel(_cloud_pct(feat))
                lbl_c.setStyleSheet('font-size:11px; color:#34a853;')
                grid.addWidget(lbl_c, row, 2)
            else:
                lbl_na = QLabel('Sem cena / No scene')
                lbl_na.setStyleSheet('font-size:11px; color:#aaa; font-style:italic;')
                grid.addWidget(lbl_na, row, 1, 1, 2)

        self._smart_scroll.setWidget(inner)

        if not found:
            self._lbl_smart_status.setText(
                'Nenhuma cena encontrada em nenhuma quinzena. / '
                'No scene found in any fortnight.')
            return

        # Inicia downloads / Start downloads
        self._lbl_smart_status.setText(
            'Iniciando {} download(s)... / Starting {} download(s)...'.format(n_found, n_found))
        self._queue_smart_downloads(found)

    def _queue_smart_downloads(self, found_pairs):
        """Cria e enfileira os DownloadThreads para todas as quinzenas encontradas /
        Create and enqueue DownloadThreads for all found fortnights."""
        from .rth_downloader import DownloadThread
        from .rth_dialog_actions import _DownloadRow

        collection_id  = self._smart_collection_id
        culture_key    = self._smart_culture_key
        output_dir     = self._smart_output_dir
        culture_cfg    = CULTURE_CONFIGS[culture_key]
        extra_roles    = culture_cfg['extra_roles']   # [(role, suffix), ...]

        # Agrega as configurações de composição derivada numa lista unificada.
        # Suporta legado (chave 'derived') e o novo formato (chave 'derived_list').
        # Aggregate derived composite configs into a unified list.
        # Supports legacy ('derived' key) and new format ('derived_list' key).
        _single = culture_cfg.get('derived')
        derived_configs = culture_cfg.get('derived_list') or ([_single] if _single else [])

        primary_roles  = culture_cfg['primary_roles']
        primary_suffix = culture_cfg['primary_suffix']
        has_primary    = bool(primary_roles)
        if has_primary:
            primary_bt = _band_tuple_for(collection_id, primary_roles, culture_cfg)

        scene_groups = []

        for lbl, feature in found_pairs:
            scene_id = feature.get('id', 'scene')
            tracker = _SceneTracker(scene_id, output_dir, derived_configs,
                                    primary_roles=primary_roles if has_primary else None)
            # Referência forte: PyQt usa weak-ref para QObjects em conexões de sinal;
            # sem isso o tracker seria coletado pelo GC logo após a função retornar,
            # desconectando os sinais antes do download terminar.
            # Strong ref: PyQt uses weak-ref for QObjects in signal connections;
            # without this the tracker would be GC'd right after the function returns,
            # disconnecting all signals before the download completes.
            self._smart_trackers.append(tracker)
            tracker.status.connect(self._on_smart_tracker_status)
            n_dl = (1 if has_primary else 0) + len(extra_roles)
            tracker.set_total(n_dl)
            tracker.set_extra_count(len(extra_roles))

            group = []
            group_row = None  # row líder do grupo — exibe posição na fila / leader row — shows queue position

            # ── Thread primária (só culturas com stacked primary) ──────────────
            if has_primary:
                title_primary = 'Smart · {} · {} · {}'.format(
                    lbl, scene_id[:22], primary_suffix)
                fthread = DownloadThread(
                    [feature], collection_id, 'CUSTOM', output_dir,
                    band_tuple=primary_bt,
                    output_suffix=primary_suffix,
                    band_names=list(zip(primary_roles, primary_bt)))
                fthread.layer_ready.connect(tracker.on_primary_ready)
                # NÃO conectar fthread.layer_ready → _on_layer_ready aqui.
                # O tracker emite seu próprio layer_ready DEPOIS de _build() completar,
                # evitando que o render thread do QGIS leia o arquivo ao mesmo tempo
                # que _build() — race condition no block cache do GDAL → crash.
                # Do NOT connect fthread.layer_ready → _on_layer_ready here.
                # Tracker emits its own layer_ready AFTER _build() completes,
                # preventing QGIS render thread from reading the file concurrently
                # with _build() — GDAL block cache race condition → crash.
                tracker.layer_ready.connect(self._on_layer_ready)
                fthread.finished_sig.connect(tracker.on_download_done)
                fthread.finished_sig.connect(lambda _: self._update_dl_tab_label())

                row_p = _DownloadRow(title_primary, self._dl_inner)
                row_p.attach_thread(fthread)
                row_p.row_removed.connect(self._on_dl_row_removed)
                self._dl_layout.insertWidget(0, row_p)
                self._dl_empty.setVisible(False)
                self._download_rows.append(row_p)
                group.append(fthread)
                group_row = row_p

            # ── Threads de bandas extras ───────────────────────────────────────
            for ex_idx, (role, ex_suffix) in enumerate(extra_roles):
                ex_bt = _band_tuple_for(collection_id, (role,), culture_cfg)
                title_ex = 'Smart · {} · {} · {}'.format(lbl, scene_id[:22], ex_suffix)
                ex_thread = DownloadThread(
                    [feature], collection_id, 'EXTRA', output_dir,
                    band_tuple=ex_bt,
                    output_suffix=ex_suffix)

                def _make_extra_ready_handler(idx, t):
                    def _handler(path, name, feat):
                        t.on_extra_ready(idx, path, name, feat)
                    return _handler

                ex_thread.layer_ready.connect(_make_extra_ready_handler(ex_idx, tracker))
                ex_thread.finished_sig.connect(tracker.on_download_done)
                ex_thread.finished_sig.connect(lambda _: self._update_dl_tab_label())

                row_ex = _DownloadRow(title_ex, self._dl_inner)
                row_ex.attach_thread(ex_thread)
                row_ex.row_removed.connect(self._on_dl_row_removed)
                self._dl_layout.insertWidget(0, row_ex)
                self._dl_empty.setVisible(False)
                self._download_rows.append(row_ex)

                group.append(ex_thread)
                if group_row is None:
                    group_row = row_ex  # culturas sem primary usam 1ª extra como líder / cultures without primary use 1st extra as leader

            scene_groups.append((group, group_row))

        self._enqueue_prebuilt_groups(scene_groups)
        self._update_dl_tab_label()

        # Café carrega os 3 basemaps de satélite automaticamente para referência visual /
        # Coffee loads all 3 satellite basemaps automatically for visual reference
        if culture_key == 'COFFEE':
            from .rth_basemaps import add_basemap
            for _bm in ('ESRI Satellite', 'Google Satellite', 'Bing Satellite'):
                add_basemap(_bm)

        # Muda para aba Downloads / Switch to Downloads tab
        self._tab_widget.setCurrentIndex(3)


# ── Helper local ──────────────────────────────────────────────────────────────

def _make_status_label(text):
    lbl = QLabel(text)
    lbl.setAlignment(_ALIGN_CENTER)
    lbl.setStyleSheet('color:#aaa; font-size:11px;')
    return lbl
