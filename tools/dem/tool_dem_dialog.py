# -*- coding: utf-8 -*-
"""
Diálogo principal do RTH DEM Downloader
Main dialog for RTH DEM Downloader

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Biblioteca padrão para caminhos de arquivo / Standard library for file paths
import os

# Widgets Qt / Qt widgets
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QLineEdit, QProgressBar,
    QFileDialog, QSizePolicy, QFrame, QRadioButton,
    QButtonGroup, QWidget
)
# Módulo Qt para alinhamento e sinais / Qt module for alignment and signals
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal

# Módulos QGIS para CRS, transformação e camadas / QGIS modules for CRS, transform and layers
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsRasterLayer
)
from core.rth_layer_utils import collapse_layer

# Módulos locais / Local modules
from .tool_dem_constants import SOURCE_INPE, SOURCE_COPERNICUS, SOURCE_COPERNICUS_90, DATA_TYPES
from .tool_dem_sources   import search_topodata_items, get_copernicus_items, get_copernicus_90m_items, DownloadThread, virtualize_dem_items
# Utilitário de detecção de datum UTM regional / Regional UTM datum detection utility
from core.rth_utm_utils import detect_regional_utm
from .tool_dem_maptool   import RectangleMapTool


class _TopoSearchThread(QThread):
    """Busca tiles Topodata INPE via STAC em background / Searches INPE Topodata tiles via STAC in background."""
    result = pyqtSignal(list)
    error  = pyqtSignal(str)

    def __init__(self, bbox, asset_key, parent=None):
        super().__init__(parent)
        self._bbox      = bbox
        self._asset_key = asset_key

    def run(self):
        try:
            items = search_topodata_items(self._bbox, self._asset_key)
            self.result.emit(items)
        except Exception as e:
            self.error.emit(str(e))


class DEMDownloaderDialog(QDialog):
    """
    Janela principal do RTH DEM Downloader.
    Main window of RTH DEM Downloader.

    Permite ao usuário / Allows the user to:
      - Escolher a fonte (INPE ou Copernicus) / Choose source (INPE or Copernicus)
      - Definir a área de interesse / Define the area of interest
      - Virtualizar (COG) ou baixar os tiles / Virtualize (COG) or download tiles
    """

    def __init__(self, iface, parent=None):
        """Inicializa o diálogo / Initialize the dialog."""
        super().__init__(parent)
        # Interface QGIS / QGIS interface
        self.iface = iface
        # Bounding box em WGS84 / Bounding box in WGS84
        self._bbox         = None
        self._thread       = None
        self._rect_tool    = None
        self._preview_thread  = None
        self._run_tile_thread = None
        # Monta os widgets / Build widgets
        self._build_ui()

    # ──────────────────────────────────────────────────────────────────────────
    # Construção da UI / UI construction
    # ──────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        """Cria e organiza todos os widgets do diálogo / Create and arrange all dialog widgets."""
        self.setWindowTitle('RTH DEM Downloader')
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint |
            Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint
        )
        self.setMinimumWidth(460)

        # Layout raiz / Root layout
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── Cabeçalho / Header ────────────────────────────────────────────────
        lbl_title = QLabel('RTH DEM Downloader')
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold;')
        layout.addWidget(lbl_title)

        # Subtítulo dinâmico (muda com a fonte) / Dynamic subtitle (changes with source)
        self.lbl_sub = QLabel()
        self.lbl_sub.setAlignment(Qt.AlignCenter)
        self.lbl_sub.setStyleSheet('color:#666; font-size:10px;')
        layout.addWidget(self.lbl_sub)

        self._sep(layout)

        # ── Seletor de fonte / Source selector ───────────────────────────────
        lbl_source = QLabel('Fonte / Source')
        lbl_source.setStyleSheet('font-weight:bold;')
        layout.addWidget(lbl_source)

        self.combo_source = QComboBox()
        self.combo_source.addItem(SOURCE_INPE)
        self.combo_source.addItem(SOURCE_COPERNICUS)
        # Opção Copernicus 90m / Copernicus 90m option
        self.combo_source.addItem(SOURCE_COPERNICUS_90)
        self.combo_source.currentIndexChanged.connect(self._on_source_changed)
        layout.addWidget(self.combo_source)

        self._sep(layout)

        # ── Área de interesse / Area of interest ─────────────────────────────
        lbl_aoi = QLabel('Área de Interesse / Area of Interest')
        lbl_aoi.setStyleSheet('font-weight:bold;')
        layout.addWidget(lbl_aoi)

        aoi_row = QHBoxLayout()
        aoi_row.setSpacing(8)

        # Botão: extent atual do mapa / Button: current map extent
        self.btn_extent = QPushButton('Extensão da Tela / Screen Extent')
        self.btn_extent.setToolTip('Usa o extent atual do mapa / Use current map extent')
        self.btn_extent.setMinimumHeight(34)
        self.btn_extent.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_extent.clicked.connect(self._on_use_extent)
        aoi_row.addWidget(self.btn_extent)

        # Botão: desenhar retângulo / Button: draw rectangle
        self.btn_draw = QPushButton('Desenhar Área / Draw Area')
        self.btn_draw.setToolTip('Clique e arraste no mapa / Click and drag on map')
        self.btn_draw.setMinimumHeight(34)
        self.btn_draw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_draw.clicked.connect(self._on_draw_area)
        aoi_row.addWidget(self.btn_draw)

        layout.addLayout(aoi_row)

        # Label que exibe as coordenadas da área selecionada / Label showing selected area coordinates
        self.lbl_bbox = QLabel('Nenhuma área definida / No area defined')
        self.lbl_bbox.setAlignment(Qt.AlignCenter)
        self.lbl_bbox.setStyleSheet(
            'background:#f5f5f5; border:1px solid #ccc; padding:4px;'
            'font-size:10px; color:#555; border-radius:3px;'
        )
        self.lbl_bbox.setWordWrap(True)
        layout.addWidget(self.lbl_bbox)

        self._sep(layout)

        # ── Recorte / Clip ────────────────────────────────────────────────────
        lbl_clip = QLabel('Recorte / Clip')
        lbl_clip.setStyleSheet('font-weight:bold;')
        layout.addWidget(lbl_clip)

        clip_row = QHBoxLayout()
        clip_row.setSpacing(8)

        # Rádio: recortar pelo bbox desenhado / Radio: clip by drawn bbox
        self.radio_clip_aoi = QRadioButton('Área de Interesse / Area of Interest')
        self.radio_clip_aoi.setToolTip(
            'Recorta o resultado exatamente pelo bbox desenhado / Clips result exactly to the drawn bbox')
        self.radio_clip_aoi.setChecked(True)

        # Rádio: manter a cena completa sem recorte / Radio: keep full tile without clipping
        self.radio_clip_full = QRadioButton('Cena Completa / Full Scene')
        self.radio_clip_full.setToolTip(
            'Mantém o tile inteiro sem recortar / Keeps the full tile without clipping')

        self._clip_group = QButtonGroup()
        self._clip_group.addButton(self.radio_clip_aoi)
        self._clip_group.addButton(self.radio_clip_full)

        clip_row.addWidget(self.radio_clip_aoi)
        clip_row.addWidget(self.radio_clip_full)
        clip_row.addStretch()
        layout.addLayout(clip_row)

        self._sep(layout)

        # ── Tipo de dado — somente INPE / Data type — INPE only ──────────────
        # Container para poder esconder o bloco inteiro / Container to hide the whole block
        self.widget_type = QWidget()
        type_layout = QVBoxLayout(self.widget_type)
        type_layout.setContentsMargins(0, 0, 0, 0)
        type_layout.setSpacing(4)

        lbl_type = QLabel('Tipo de Dado / Data Type')
        lbl_type.setStyleSheet('font-weight:bold;')
        type_layout.addWidget(lbl_type)

        self.combo_type = QComboBox()
        for label in DATA_TYPES:
            self.combo_type.addItem(label)
        type_layout.addWidget(self.combo_type)

        # Separador dentro do bloco / Separator inside the block
        sep_inner = QFrame()
        sep_inner.setFrameShape(QFrame.HLine)
        sep_inner.setFrameShadow(QFrame.Sunken)
        type_layout.addWidget(sep_inner)

        layout.addWidget(self.widget_type)

        # ── Modo: virtualizar ou baixar / Mode: virtualize or download ────────
        lbl_mode = QLabel('Modo / Mode')
        lbl_mode.setStyleSheet('font-weight:bold;')
        layout.addWidget(lbl_mode)

        mode_row = QHBoxLayout()

        # Rádio: virtualizar via COG / Radio: virtualize via COG
        self.radio_virt = QRadioButton('Virtualizar / Virtualize (COG)')
        self.radio_virt.setToolTip('Carrega da URL sem baixar / Loads from URL without downloading')
        self.radio_virt.setChecked(True)

        # Rádio: baixar localmente / Radio: download locally
        self.radio_down = QRadioButton('Baixar / Download')
        self.radio_down.setToolTip('Salva .tif localmente / Saves .tif locally')

        # Grupo exclusivo / Exclusive group
        self._mode_group = QButtonGroup()
        self._mode_group.addButton(self.radio_virt)
        self._mode_group.addButton(self.radio_down)

        mode_row.addWidget(self.radio_virt)
        mode_row.addWidget(self.radio_down)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # Linha da pasta de saída (visível apenas no modo baixar) / Output folder row (visible only in download mode)
        dir_row = QHBoxLayout()
        self.edit_dir = QLineEdit()
        self.edit_dir.setPlaceholderText('Pasta de saída / Output folder...')
        dir_row.addWidget(self.edit_dir)

        self.btn_browse = QPushButton('...')
        self.btn_browse.setFixedWidth(32)
        self.btn_browse.clicked.connect(self._on_browse)
        dir_row.addWidget(self.btn_browse)

        layout.addLayout(dir_row)

        # Conecta o rádio para mostrar/esconder a pasta / Connect radio to show/hide folder row
        self.radio_virt.toggled.connect(lambda checked: self._set_dir_visible(not checked))
        self._set_dir_visible(False)

        self._sep(layout)

        # ── Status de tiles / Tiles status ────────────────────────────────────
        self.lbl_tiles = QLabel('')
        self.lbl_tiles.setAlignment(Qt.AlignCenter)
        self.lbl_tiles.setStyleSheet('font-size:10px; color:#444;')
        self.lbl_tiles.setWordWrap(True)
        layout.addWidget(self.lbl_tiles)

        # ── Botão Run ─────────────────────────────────────────────────────────
        self.btn_run = QPushButton('▶  Executar / Run')
        self.btn_run.setMinimumHeight(40)
        self.btn_run.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;font-size:13px;border-radius:5px;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        self.btn_run.clicked.connect(self._on_run)
        layout.addWidget(self.btn_run)

        # ── Progresso / Progress ──────────────────────────────────────────────
        self.lbl_progress = QLabel('')
        self.lbl_progress.setAlignment(Qt.AlignCenter)
        self.lbl_progress.setStyleSheet('font-size:10px; color:#333;')
        layout.addWidget(self.lbl_progress)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimum(0)
        layout.addWidget(self.progress_bar)

        # Inicializa o estado conforme a fonte padrão / Initialize state for the default source
        self._on_source_changed(0)

    def _get_dst_srs(self):
        """Detecta o CRS UTM regional a partir do centro do bbox atual / Detect regional UTM CRS from current bbox center.

        :returns: string do CRS de destino, ex: 'EPSG:31982' / target CRS string, e.g. 'EPSG:31982'
        :rtype: str
        """
        if self._bbox is None:
            # Sem bbox definido, usa WGS84 como fallback / No bbox defined, use WGS84 as fallback
            return 'EPSG:4326'
        # Centroide do bbox em WGS84 / Bbox centroid in WGS84
        lon = (self._bbox.xMinimum() + self._bbox.xMaximum()) / 2.0
        lat = (self._bbox.yMinimum() + self._bbox.yMaximum()) / 2.0
        # Detecta datum e EPSG regional / Detect regional datum and EPSG
        epsg, _, _, _ = detect_regional_utm(lon, lat)
        return 'EPSG:{}'.format(epsg)

    def _sep(self, layout):
        """Insere um separador horizontal / Insert a horizontal separator."""
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

    def _set_dir_visible(self, visible):
        """Mostra ou esconde o campo de pasta de saída / Show or hide the output folder field."""
        self.edit_dir.setVisible(visible)
        self.btn_browse.setVisible(visible)

    # ──────────────────────────────────────────────────────────────────────────
    # Troca de fonte / Source switch
    # ──────────────────────────────────────────────────────────────────────────

    def _is_inpe(self):
        """Retorna True se a fonte INPE está selecionada / Returns True if INPE source is selected."""
        return self.combo_source.currentText() == SOURCE_INPE

    def _get_copernicus_items_for_source(self, bbox):
        """Retorna os tiles Copernicus conforme a resolução selecionada / Return Copernicus tiles for the selected resolution."""
        if self.combo_source.currentText() == SOURCE_COPERNICUS_90:
            # 90m — bucket copernicus-dem-90m / 90m — copernicus-dem-90m bucket
            return get_copernicus_90m_items(bbox)
        # 30m padrão / Default 30m
        return get_copernicus_items(bbox)

    def _on_source_changed(self, _index):
        """Adapta a UI quando o usuário troca de fonte / Adapt UI when user switches source."""
        source = self.combo_source.currentText()
        if source == SOURCE_INPE:
            # Mostra o seletor de tipo de dado (INPE tem 16 produtos) / Show data type selector (INPE has 16 products)
            self.widget_type.setVisible(True)
            self.lbl_sub.setText('INPE Topodata  ·  STAC API  ·  ~30 m  ·  Brasil only')
        elif source == SOURCE_COPERNICUS:
            # Copernicus 30m: somente elevação / Copernicus 30m: elevation only
            self.widget_type.setVisible(False)
            self.lbl_sub.setText('Copernicus GLO-30  ·  S3 COG  ·  ~30 m  ·  Global')
        else:
            # Copernicus 90m: somente elevação / Copernicus 90m: elevation only
            self.widget_type.setVisible(False)
            self.lbl_sub.setText('Copernicus GLO-90  ·  S3 COG  ·  ~90 m  ·  Global')
        # Reajusta o tamanho do diálogo / Resize dialog to fit content
        self.adjustSize()
        # Atualiza a prévia se já houver uma área definida / Update preview if an area is already defined
        if self._bbox is not None:
            self._preview_tiles()

    # ──────────────────────────────────────────────────────────────────────────
    # Área de interesse / Area of interest
    # ──────────────────────────────────────────────────────────────────────────

    def _on_use_extent(self):
        """Captura o extent atual do canvas como AOI / Capture current canvas extent as AOI."""
        try:
            canvas = self.iface.mapCanvas()
            extent = canvas.extent()
            crs    = canvas.mapSettings().destinationCrs()
            wgs84  = QgsCoordinateReferenceSystem('EPSG:4326')
            # Transforma para WGS84 se o projeto usar outro CRS / Transform to WGS84 if project uses another CRS
            if crs.authid() != 'EPSG:4326':
                t = QgsCoordinateTransform(crs, wgs84, QgsProject.instance())
                extent = t.transformBoundingBox(extent)
            self._bbox = extent
            self._update_bbox_label()
        except Exception as e:
            self.lbl_bbox.setText('Erro / Error: {}'.format(str(e)))

    def _on_draw_area(self):
        """Ativa a ferramenta de retângulo e minimiza o diálogo / Activate rectangle tool and minimize dialog."""
        try:
            canvas = self.iface.mapCanvas()
            self._rect_tool = RectangleMapTool(canvas)
            self._rect_tool.rectangleDrawn.connect(self._on_rectangle_drawn)
            canvas.setMapTool(self._rect_tool)
            # Minimiza para liberar a visão do mapa / Minimize to free map view
            self.showMinimized()
            self.iface.messageBar().pushMessage(
                'RTH DEM',
                'Clique e arraste para desenhar a área / Click and drag to draw the area',
                level=Qgis.MessageLevel.Info, duration=5)
        except Exception as e:
            self.lbl_bbox.setText('Erro / Error: {}'.format(str(e)))

    def _on_rectangle_drawn(self, rect):
        """Recebe o retângulo desenhado e converte para WGS84 / Receive drawn rectangle and convert to WGS84."""
        try:
            # Restaura o diálogo / Restore dialog
            self.showNormal()
            self.raise_()
            self.activateWindow()
            crs   = self.iface.mapCanvas().mapSettings().destinationCrs()
            wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
            if crs.authid() != 'EPSG:4326':
                t = QgsCoordinateTransform(crs, wgs84, QgsProject.instance())
                rect = t.transformBoundingBox(rect)
            self._bbox = rect
            self._update_bbox_label()
        except Exception as e:
            self.lbl_bbox.setText('Erro / Error: {}'.format(str(e)))

    def _update_bbox_label(self):
        """Atualiza o label com as coordenadas e dispara a prévia / Update coordinate label and trigger preview."""
        if self._bbox is None:
            self.lbl_bbox.setText('Nenhuma área definida / No area defined')
            self.lbl_tiles.setText('')
            return
        b = self._bbox
        self.lbl_bbox.setText(
            'N:{:.4f}  S:{:.4f}  W:{:.4f}  E:{:.4f}'.format(
                b.yMaximum(), b.yMinimum(), b.xMinimum(), b.xMaximum()
            )
        )
        self._preview_tiles()

    def _preview_tiles(self):
        """Conta os tiles da área e exibe na UI sem fazer download / Count area tiles and show in UI without downloading."""
        if self._bbox is None:
            return

        if not self._is_inpe():
            # Copernicus — grade local, sem rede / Copernicus — local grid, no network
            items = self._get_copernicus_items_for_source(self._bbox)
            self._show_preview_items(items)
            return

        self.lbl_tiles.setText('Buscando tiles... / Searching tiles...')
        if self._preview_thread and self._preview_thread.isRunning():
            self._preview_thread.quit()
            self._preview_thread.wait(500)
        asset_key = DATA_TYPES[self.combo_type.currentText()]
        self._preview_thread = _TopoSearchThread(self._bbox, asset_key, self)
        self._preview_thread.result.connect(self._on_preview_result)
        self._preview_thread.error.connect(self._on_preview_error)
        self._preview_thread.start()

    def _on_preview_result(self, items):
        self._show_preview_items(items)

    def _on_preview_error(self, msg):
        self.lbl_tiles.setText('Erro na busca / Search error: {}'.format(msg))

    def _show_preview_items(self, items):
        if not items:
            self.lbl_tiles.setText('Nenhum tile encontrado / No tiles found')
        elif len(items) <= 6:
            self.lbl_tiles.setText('{} tile(s): {}'.format(len(items), ', '.join(i[0] for i in items)))
        else:
            self.lbl_tiles.setText('{} tile(s): {}, ...'.format(
                len(items), ', '.join(i[0] for i in items[:4])))

    def _on_browse(self):
        """Abre o diálogo de seleção de pasta / Open folder selection dialog."""
        folder = QFileDialog.getExistingDirectory(
            self,
            'Selecione a pasta de saída / Select output folder',
            self.edit_dir.text() or os.path.expanduser('~')
        )
        if folder:
            self.edit_dir.setText(folder)

    # ──────────────────────────────────────────────────────────────────────────
    # Run
    # ──────────────────────────────────────────────────────────────────────────

    def _on_run(self):
        """Valida entradas e inicia a virtualização ou o download / Validate inputs and start virtualization or download."""
        if self._bbox is None:
            self.iface.messageBar().pushMessage(
                'RTH DEM', 'Defina uma área antes de continuar / Define an area first',
                level=Qgis.MessageLevel.Warning, duration=4)
            return

        self.btn_run.setEnabled(False)
        self.btn_run.setText('Buscando... / Searching...')
        self.lbl_progress.setText('Obtendo tiles... / Fetching tiles...')

        if not self._is_inpe():
            # Copernicus — grade local, sem rede / Copernicus — local grid, no network
            try:
                items = self._get_copernicus_items_for_source(self._bbox)
            except Exception as e:
                self.iface.messageBar().pushMessage(
                    'RTH DEM', 'Erro / Error: {}'.format(str(e)), level=Qgis.MessageLevel.Warning)
                self._reset_run_button()
                return
            self._launch_with_items(items)
            return

        # INPE — busca STAC em background para não bloquear a UI
        if self._run_tile_thread and self._run_tile_thread.isRunning():
            self._run_tile_thread.quit()
            self._run_tile_thread.wait(500)
        asset_key = DATA_TYPES[self.combo_type.currentText()]
        self._run_tile_thread = _TopoSearchThread(self._bbox, asset_key, self)
        self._run_tile_thread.result.connect(self._on_run_tiles_ready)
        self._run_tile_thread.error.connect(self._on_run_tiles_error)
        self._run_tile_thread.start()

    def _on_run_tiles_ready(self, items):
        self._launch_with_items(items)

    def _on_run_tiles_error(self, msg):
        self.iface.messageBar().pushMessage(
            'RTH DEM', 'Erro / Error: {}'.format(msg), level=Qgis.MessageLevel.Warning)
        self._reset_run_button()

    def _launch_with_items(self, items):
        """Inicia virtualização ou download com a lista de tiles / Start virtualization or download with tile list."""
        if not items:
            self.iface.messageBar().pushMessage(
                'RTH DEM', 'Nenhum tile encontrado / No tiles found',
                level=Qgis.MessageLevel.Warning, duration=5)
            self._reset_run_button()
            return

        clip_bbox = self._bbox if self.radio_clip_aoi.isChecked() else None

        if self.radio_virt.isChecked():
            self._virtualize(items, clip_bbox)
            self._reset_run_button()
            return

        dst_srs = self._get_dst_srs()
        out_dir = self.edit_dir.text().strip()
        if not out_dir:
            self.iface.messageBar().pushMessage(
                'RTH DEM', 'Selecione uma pasta de saída / Select an output folder',
                level=Qgis.MessageLevel.Warning, duration=4)
            self._reset_run_button()
            return

        os.makedirs(out_dir, exist_ok=True)

        self.progress_bar.setMaximum(len(items))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.btn_run.setText('Baixando... / Downloading...')
        self.lbl_progress.setText(
            'Iniciando {} tile(s)... / Starting {} tile(s)...'.format(len(items), len(items)))

        self._thread = DownloadThread(items, out_dir, dst_srs=dst_srs, clip_bbox=clip_bbox)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _reset_run_button(self):
        """Restaura o botão Run para o estado padrão / Restore Run button to default state."""
        self.btn_run.setEnabled(True)
        self.btn_run.setText('▶  Executar / Run')
        self.lbl_progress.setText('')

    # ──────────────────────────────────────────────────────────────────────────
    # Virtualizar / Virtualize
    # ──────────────────────────────────────────────────────────────────────────

    def _virtualize(self, items, clip_bbox=None):
        """Virtualiza tiles DEM reprojetando para o datum UTM regional / Virtualize DEM tiles reprojecting to regional UTM datum."""
        # Detecta o CRS UTM regional para esta área / Detect regional UTM CRS for this area
        dst_srs = self._get_dst_srs()
        # Virtualiza com reprojection via GDAL Warp VRT / Virtualize with reprojection via GDAL Warp VRT
        loaded = virtualize_dem_items(items, dst_srs, clip_bbox=clip_bbox)

        self.lbl_progress.setText(
            '{} tile(s) virtualizado(s) ({}) / {} tile(s) virtualized ({})'.format(
                loaded, dst_srs, loaded, dst_srs))
        if loaded > 0:
            self.iface.messageBar().pushMessage(
                'RTH DEM',
                '{} tile(s) carregado(s) | {} / {} tile(s) loaded | {}'.format(
                    loaded, dst_srs, loaded, dst_srs),
                level=Qgis.MessageLevel.Info, duration=5)

    # ──────────────────────────────────────────────────────────────────────────
    # Slots da thread de download / Download thread slots
    # ──────────────────────────────────────────────────────────────────────────

    def _on_progress(self, current, total, filename):
        """Atualiza a barra e o texto de progresso / Update progress bar and text."""
        self.progress_bar.setValue(current)
        self.lbl_progress.setText(
            'Baixando ({}/{}): {} / Downloading ({}/{}): {}'.format(
                current, total, filename, current, total, filename))

    def _on_finished(self, downloaded_paths):
        """Carrega os arquivos baixados e notifica o usuário / Load downloaded files and notify user."""
        self.btn_run.setEnabled(True)
        self.btn_run.setText('▶  Executar / Run')
        count = len(downloaded_paths)
        self.lbl_progress.setText(
            '{} tile(s) baixado(s)! / {} tile(s) downloaded!'.format(count, count))

        # Adiciona cada arquivo baixado como camada raster / Add each downloaded file as raster layer
        for path in downloaded_paths:
            try:
                layer_name = os.path.splitext(os.path.basename(path))[0]
                rl = QgsRasterLayer(path, layer_name)
                if rl.isValid():
                    QgsProject.instance().addMapLayer(rl)
                    collapse_layer(rl)
            except Exception:
                pass

        level = 0 if count > 0 else 1
        msg = (
            '{} tile(s) baixado(s) e carregado(s)! / {} tile(s) downloaded and loaded!'.format(count, count)
            if count > 0
            else 'Nenhum tile baixado. Verifique a conexão. / No tiles downloaded. Check connection.'
        )
        self.iface.messageBar().pushMessage('RTH DEM', msg, level=level, duration=6)

    def _on_error(self, msg):
        """Exibe mensagem de erro na barra do QGIS / Show error message in QGIS message bar."""
        self.iface.messageBar().pushMessage('RTH DEM', msg, level=Qgis.MessageLevel.Warning, duration=5)

    # ──────────────────────────────────────────────────────────────────────────
    # Limpeza / Cleanup
    # ──────────────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """Cancela downloads e desativa ferramentas ao fechar / Cancel downloads and deactivate tools on close."""
        # Cancela a thread se estiver rodando / Cancel thread if running
        if self._thread is not None and self._thread.isRunning():
            self._thread.cancel()
            self._thread.wait(3000)
        # Desativa a ferramenta de mapa se ainda estiver ativa / Deactivate map tool if still active
        if self._rect_tool is not None:
            try:
                self.iface.mapCanvas().unsetMapTool(self._rect_tool)
            except Exception:
                pass
        super().closeEvent(event)
