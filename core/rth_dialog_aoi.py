# -*- coding: utf-8 -*-
"""
rth_dialog_aoi — Mixin da aba Área de Interesse (AOI) do RTH API Browser
rth_dialog_aoi — AOI tab mixin for the RTH API Browser

Fluxo / Flow:
  1. Usuário desenha um retângulo no mapa com AoiRectangleTool.
     User draws a rectangle on the map with AoiRectangleTool.
  2. A bbox WGS84 é armazenada em self._aoi_bbox.
     The WGS84 bbox is stored in self._aoi_bbox.
  3. "Puxar Imagens" dispara um _PageLoader com a bbox da AOI como filtro espacial.
     "Puxar Imagens" fires a _PageLoader with the AOI bbox as spatial filter.
  4. Os resultados são exibidos como AoiSceneCard — thumbnails gerados via COG/GDAL.
     Results are shown as AoiSceneCards — thumbnails generated via COG/GDAL.
  5. "Baixar na AOI" cria DownloadThread com clip_bbox para recortar ao retângulo.
     "Baixar na AOI" creates DownloadThread with clip_bbox to crop to the rectangle.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QGridLayout,
)
from qgis.PyQt.QtCore import Qt

from .rth_scene_card import SceneCard
from .rth_aoi_thumb import load_aoi_thumb_async
from .rth_stac_api import _route_for, STAC_PC, search_stac, search_stac_pc
from .rth_dialog_results import _PageLoader

try:
    _ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
except AttributeError:
    _ALIGN_CENTER = Qt.AlignCenter

try:
    _ALIGN_TOP = Qt.AlignmentFlag.AlignTop
except AttributeError:
    _ALIGN_TOP = Qt.AlignTop

_GRID_COLS = 4


# ── Card de cena com thumbnail AOI ────────────────────────────────────────────

class AoiSceneCard(SceneCard):
    """Card de cena que gera thumbnail a partir de bandas COG recortadas na AOI /
    Scene card that generates thumbnail from COG bands clipped to AOI."""

    def __init__(self, idx, feature, collection_id, band_tuple, aoi_bbox, parent=None):
        super().__init__(idx, feature, parent)
        self._collection_id = collection_id
        self._band_tuple    = band_tuple
        self._aoi_bbox      = aoi_bbox

    def load_thumb(self, cancel_flag):
        """Substitui o carregador de thumbnail STAC pelo gerador COG com recorte à AOI /
        Replaces STAC thumbnail loader with COG generator clipped to AOI."""
        if not self._thumb_loaded:
            self.lbl_thumb.setText('COG...')
            load_aoi_thumb_async(
                self._feature, self._collection_id, self._band_tuple,
                self._aoi_bbox, self.lbl_thumb, cancel_flag,
                w=self.THUMB_W, h=self.THUMB_H)
            self._thumb_loaded = True


# ── Mixin da aba AOI ──────────────────────────────────────────────────────────

class AoiMixin:
    """Mixin que adiciona a aba Área de Interesse ao rthprojectDialog /
    Mixin that adds the Area of Interest tab to rthprojectDialog.

    Depende de CatalogMixin (_get_band_tuple, combo_colecao, combo_composicao,
    date_inicial, date_final, slider_nuvem) e ActionsMixin (_dl_inner, _dl_layout,
    _download_rows, _enqueue_prebuilt_groups, _update_dl_tab_label, _on_layer_ready,
    _on_dl_row_removed, edit_pasta).

    Depends on CatalogMixin (_get_band_tuple, combo_colecao, combo_composicao,
    date_inicial, date_final, slider_nuvem) and ActionsMixin (_dl_inner, _dl_layout,
    _download_rows, _enqueue_prebuilt_groups, _update_dl_tab_label, _on_layer_ready,
    _on_dl_row_removed, edit_pasta).
    """

    def _init_aoi(self):
        """Inicializa variáveis de estado da AOI / Initialize AOI state variables."""
        self._aoi_bbox              = None
        self._aoi_results           = []
        self._aoi_cards             = []
        self._aoi_selected_card_idx = None
        self._aoi_cancel_flag       = [False]
        self._aoi_loader            = None
        self._aoi_band_tuple        = None
        self._aoi_collection_id     = None
        self._aoi_composition_key   = None

    def _setup_aoi_panel(self):
        """Monta o painel de AOI como QWidget filho do diálogo / Build AOI panel as child QWidget of dialog."""
        self._aoi_panel = QWidget(self)
        self._aoi_panel.setVisible(False)

        layout = QVBoxLayout(self._aoi_panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # ── Linha superior: status da bbox + botões ───────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._lbl_aoi_bbox = QLabel(
            'Nenhuma área definida — clique em Desenhar e arraste no mapa. / '
            'No area defined — click Draw and drag on the map.')
        self._lbl_aoi_bbox.setStyleSheet('color:#888; font-size:11px;')
        self._lbl_aoi_bbox.setWordWrap(True)
        top_row.addWidget(self._lbl_aoi_bbox, 1)

        self._btn_draw_aoi = QPushButton('✏  Desenhar Área / Draw Area')
        self._btn_draw_aoi.setMinimumHeight(30)
        self._btn_draw_aoi.setFixedWidth(195)
        self._btn_draw_aoi.setStyleSheet(
            'QPushButton{background:#f57c00;color:white;border-radius:4px;font-size:11px;}'
            'QPushButton:hover{background:#e65100;}')
        self._btn_draw_aoi.clicked.connect(self._on_draw_aoi_clicked)
        top_row.addWidget(self._btn_draw_aoi)

        self._btn_aoi_puxar = QPushButton('▶  Puxar Imagens / Fetch Images')
        self._btn_aoi_puxar.setMinimumHeight(30)
        self._btn_aoi_puxar.setFixedWidth(205)
        self._btn_aoi_puxar.setEnabled(False)
        self._btn_aoi_puxar.setToolTip(
            'Usa os filtros da aba Cenas: satélite, coleção, composição, datas e nuvens.\n'
            'Uses filters from Scenes tab: satellite, collection, composition, dates and clouds.')
        self._btn_aoi_puxar.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;border-radius:4px;font-size:11px;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#aaa;color:#eee;}')
        self._btn_aoi_puxar.clicked.connect(self._on_aoi_puxar_clicked)
        top_row.addWidget(self._btn_aoi_puxar)

        layout.addLayout(top_row)

        # ── Dica sobre filtros compartilhados ─────────────────────────────────
        lbl_hint = QLabel(
            'ℹ  Satélite, coleção, composição, datas e filtro de nuvens são os mesmos da aba Cenas. / '
            'Satellite, collection, composition, dates and cloud filter are shared with the Scenes tab.')
        lbl_hint.setStyleSheet('color:#888; font-size:10px; font-style:italic;')
        lbl_hint.setWordWrap(True)
        layout.addWidget(lbl_hint)

        # ── Status da busca ───────────────────────────────────────────────────
        self._lbl_aoi_status = QLabel('')
        self._lbl_aoi_status.setStyleSheet('color:#555; font-size:11px;')
        layout.addWidget(self._lbl_aoi_status)

        # ── Área de resultados ────────────────────────────────────────────────
        self._aoi_scroll = QScrollArea()
        self._aoi_scroll.setWidgetResizable(True)
        self._aoi_scroll.setStyleSheet('QScrollArea{border:none;}')
        _placeholder = QLabel(
            'Defina uma área e clique em Puxar Imagens.\n'
            'Define an area and click Fetch Images.')
        _placeholder.setAlignment(_ALIGN_CENTER)
        _placeholder.setStyleSheet('color:#aaa; font-size:12px;')
        self._aoi_scroll.setWidget(_placeholder)
        layout.addWidget(self._aoi_scroll, 1)

        # ── Barra inferior: deselect + download ───────────────────────────────
        bot_row = QHBoxLayout()
        bot_row.setSpacing(8)
        bot_row.addStretch()

        self._btn_aoi_desmarcar = QPushButton('✕  Desmarcar / Deselect All')
        self._btn_aoi_desmarcar.setMinimumHeight(34)
        self._btn_aoi_desmarcar.clicked.connect(self._on_aoi_deselect_all)
        bot_row.addWidget(self._btn_aoi_desmarcar)

        self._btn_aoi_baixar = QPushButton('⬇  Baixar na AOI / Download AOI')
        self._btn_aoi_baixar.setMinimumHeight(34)
        self._btn_aoi_baixar.setEnabled(False)
        self._btn_aoi_baixar.setToolTip(
            'Baixa as cenas selecionadas recortadas ao retângulo desenhado.\n'
            'Downloads selected scenes clipped to the drawn rectangle.')
        self._btn_aoi_baixar.setStyleSheet(
            'QPushButton{background:#34a853;color:white;border-radius:4px;font-size:11px;}'
            'QPushButton:hover{background:#1e7e34;}'
            'QPushButton:disabled{background:#aaa;color:#eee;}')
        self._btn_aoi_baixar.clicked.connect(self._on_aoi_baixar_clicked)
        bot_row.addWidget(self._btn_aoi_baixar)

        layout.addLayout(bot_row)

    # ── Handlers de botão ─────────────────────────────────────────────────────

    def _on_draw_aoi_clicked(self):
        """Ativa a ferramenta de desenho de AOI no canvas / Activate AOI drawing tool on canvas."""
        from .rth_aoi_maptool import AoiRectangleTool
        self._aoi_tool = AoiRectangleTool(self.iface.mapCanvas())
        self._aoi_tool.bbox_selected.connect(self._on_aoi_bbox_ready)
        self.iface.mapCanvas().setMapTool(self._aoi_tool)
        self._lbl_aoi_bbox.setText(
            'Arraste um retângulo no mapa e solte o mouse... / '
            'Drag a rectangle on the map and release the mouse...')
        self._lbl_aoi_bbox.setStyleSheet('color:#f57c00; font-size:11px;')
        # Minimiza o diálogo para liberar o canvas ao usuário
        # Minimises dialog so the user can draw freely on the canvas
        self.showMinimized()

    def _on_aoi_bbox_ready(self, bbox):
        """Chamado pela AoiRectangleTool ao soltar o mouse / Called by AoiRectangleTool on mouse release."""
        self._aoi_bbox = bbox
        self._lbl_aoi_bbox.setText(
            'AOI: {:.4f}°, {:.4f}° → {:.4f}°, {:.4f}°'.format(*bbox))
        self._lbl_aoi_bbox.setStyleSheet('color:#34a853; font-size:11px;')
        self._btn_aoi_puxar.setEnabled(True)
        # Restaura o diálogo após o desenho concluído
        # Restore dialog after drawing is complete
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_aoi_puxar_clicked(self):
        """Dispara busca STAC com a bbox da AOI como filtro espacial /
        Fire STAC search with AOI bbox as spatial filter."""
        if not self._aoi_bbox:
            return

        collection_id   = self.combo_colecao.currentData()
        composition_key = self.combo_composicao.currentData()
        if not collection_id:
            self._lbl_aoi_status.setText(
                'Selecione uma coleção na aba Cenas. / Select a collection in the Scenes tab.')
            return

        date_ini  = self.date_inicial.date().toString('yyyy-MM-dd') + 'T00:00:00Z'
        date_fim  = self.date_final.date().toString('yyyy-MM-dd') + 'T23:59:59Z'
        cloud_max = self.slider_nuvem.value()

        self._aoi_collection_id   = collection_id
        self._aoi_composition_key = composition_key
        self._aoi_band_tuple      = self._get_band_tuple(collection_id, composition_key)

        # Cancela busca anterior / Cancel any previous search
        self._aoi_cancel_flag[0] = True
        self._aoi_cancel_flag    = [False]
        if self._aoi_loader and self._aoi_loader.isRunning():
            self._aoi_loader.quit()
            self._aoi_loader.wait(1000)

        self._lbl_aoi_status.setText('Buscando... / Searching...')
        self._btn_aoi_puxar.setEnabled(False)

        endpoint, _ = _route_for(collection_id)
        if endpoint == STAC_PC:
            fn     = search_stac_pc
            args   = (collection_id, self._aoi_bbox, date_ini, date_fim, cloud_max)
            kwargs = {}
        else:
            fn     = search_stac
            args   = (collection_id, self._aoi_bbox, date_ini, date_fim, cloud_max)
            kwargs = {'page': 1}

        self._aoi_loader = _PageLoader(fn, args, kwargs)
        self._aoi_loader.done.connect(self._on_aoi_page_loaded)
        self._aoi_loader.failed.connect(self._on_aoi_failed)
        self._aoi_loader.start()

    def _on_aoi_page_loaded(self, features, total, next_body, prev_body):
        """Exibe resultados da busca AOI como AoiSceneCards / Display AOI search results as AoiSceneCards."""
        self._aoi_results           = features
        self._aoi_cards             = []
        self._aoi_selected_card_idx = None
        self._btn_aoi_puxar.setEnabled(True)

        if not features:
            self._lbl_aoi_status.setText(
                'Nenhuma cena encontrada na área. / No scenes found in this area.')
            placeholder = QLabel('Sem resultados / No results')
            placeholder.setAlignment(_ALIGN_CENTER)
            placeholder.setStyleSheet('color:#aaa; font-size:12px;')
            self._aoi_scroll.setWidget(placeholder)
            self._btn_aoi_baixar.setEnabled(False)
            return

        n = len(features)
        self._lbl_aoi_status.setText(
            '{} cena(s) encontrada(s) / {} scene(s) found'.format(n, n))

        inner = QWidget()
        grid  = QGridLayout(inner)
        grid.setSpacing(8)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setAlignment(_ALIGN_TOP)

        for i, feature in enumerate(features):
            card = AoiSceneCard(
                i, feature,
                self._aoi_collection_id,
                self._aoi_band_tuple,
                self._aoi_bbox,
                parent=inner)
            card.selected.connect(self._on_aoi_card_clicked)
            grid.addWidget(card, i // _GRID_COLS, i % _GRID_COLS)
            self._aoi_cards.append(card)
            card.load_thumb(self._aoi_cancel_flag)

        self._aoi_scroll.setWidget(inner)
        self._btn_aoi_baixar.setEnabled(True)

    def _on_aoi_failed(self, err):
        """Exibe mensagem de erro / Display error message."""
        self._lbl_aoi_status.setText('Erro / Error: ' + err)
        self._btn_aoi_puxar.setEnabled(True)

    def _on_aoi_card_clicked(self, idx):
        """Seleciona o card clicado (borda azul) e deseleciona os demais /
        Select clicked card (blue border) and deselect others."""
        self._aoi_selected_card_idx = idx
        for i, card in enumerate(self._aoi_cards):
            card.set_selected(i == idx)

    def _on_aoi_deselect_all(self):
        """Desmarca todos os checkboxes e limpa a seleção visual /
        Uncheck all checkboxes and clear visual selection."""
        self._aoi_selected_card_idx = None
        for card in self._aoi_cards:
            card.chk.setChecked(False)
            card.set_selected(False)

    def _aoi_checked_features(self):
        """Retorna features marcadas (checkbox) ou a selecionada visualmente /
        Return checked (checkbox) features or the visually selected one."""
        checked = [
            self._aoi_results[i]
            for i, card in enumerate(self._aoi_cards)
            if card.is_checked()
        ]
        if checked:
            return checked
        # Fallback: feature selecionada visualmente / Fallback: visually selected feature
        idx = self._aoi_selected_card_idx
        if idx is not None and idx < len(self._aoi_results):
            return [self._aoi_results[idx]]
        return []

    def _on_aoi_baixar_clicked(self):
        """Inicia download das cenas selecionadas recortadas à AOI /
        Start download of selected scenes clipped to AOI."""
        if not self._aoi_bbox:
            return

        features = self._aoi_checked_features()
        if not features:
            self._lbl_aoi_status.setText(
                'Selecione ao menos uma cena (checkbox ou clique). / '
                'Select at least one scene (checkbox or click).')
            return

        import os
        output_dir = self.edit_pasta.text().strip()
        if not output_dir or not os.path.isdir(output_dir):
            self._lbl_aoi_status.setText(
                'Pasta de saída inválida — defina em Cenas > Browse. / '
                'Invalid output folder — set it in Scenes > Browse.')
            return

        collection_id   = self._aoi_collection_id or self.combo_colecao.currentData()
        composition_key = self._aoi_composition_key or self.combo_composicao.currentData() or 'RGB'
        bt              = self._aoi_band_tuple or self._get_band_tuple(collection_id, composition_key)

        from .rth_downloader import DownloadThread
        from .rth_dialog_actions import _DownloadRow

        scene_thread_groups = []
        for feature in features:
            scene_id = str(feature.get('id') or '')
            title    = 'AOI · {} · {}'.format(scene_id[:28], composition_key)

            fthread = DownloadThread(
                [feature], collection_id, composition_key, output_dir,
                band_tuple=bt,
                output_suffix=composition_key + '_aoi',
                clip_bbox=self._aoi_bbox)
            fthread.layer_ready.connect(self._on_layer_ready)
            fthread.finished_sig.connect(lambda _: self._update_dl_tab_label())

            row = _DownloadRow(title, self._dl_inner)
            row.attach_thread(fthread)
            row.row_removed.connect(self._on_dl_row_removed)
            self._dl_layout.insertWidget(0, row)
            self._dl_empty.setVisible(False)
            self._download_rows.append(row)
            scene_thread_groups.append(([fthread], row))

        self._enqueue_prebuilt_groups(scene_thread_groups)
        self._update_dl_tab_label()

        # Muda para aba Downloads para o usuário acompanhar /
        # Switch to Downloads tab so user can follow progress
        self._tab_widget.setCurrentIndex(3)
