# -*- coding: utf-8 -*-
"""
rth_dialog_results — Mixin de busca STAC e exibição de cards de cenas
rth_dialog_results — RTH dialog mixin for STAC search and scene card display

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Biblioteca padrão para erros HTTP / Standard library for HTTP errors
import urllib.error

# Módulos Qt para widgets / Qt modules for widgets
from qgis.PyQt.QtWidgets import QApplication, QWidget, QGridLayout, QLabel
from qgis.PyQt.QtCore import Qt

# Importa busca STAC e bbox do canvas / Import STAC search and canvas bbox
from rth_stac_api import search_stac, get_bbox_from_canvas
# Importa widget de card de cena / Import scene card widget
from rth_scene_card import SceneCard

# Número de colunas no grid de cards / Number of columns in the card grid
_GRID_COLS = 4


class ResultsMixin:
    """Busca STAC, exibição de cards de cenas e seleção / STAC search, scene card display and selection."""

    def _on_puxar_clicked(self):
        """Executa a busca STAC com os parâmetros do formulário / Run STAC search with form parameters."""
        collection_id = self.combo_colecao.currentData()
        if not collection_id:
            self._set_status('Selecione uma coleção / Select a collection', error=True)
            return

        # Formata datas ISO 8601 / Format dates ISO 8601
        date_ini  = self.date_inicial.date().toString('yyyy-MM-dd') + 'T00:00:00Z'
        date_fim  = self.date_final.date().toString('yyyy-MM-dd') + 'T23:59:59Z'
        cloud_max = self.slider_nuvem.value()

        try:
            bbox = get_bbox_from_canvas(self.iface)
        except Exception as e:
            self._set_status('Erro ao obter extent: {} / Error getting extent: {}'.format(e, e), error=True)
            return

        self._set_status('Buscando... / Searching...')
        self.btn_puxar.setEnabled(False)
        QApplication.processEvents()

        try:
            features      = search_stac(collection_id, bbox, date_ini, date_fim, cloud_max)
            self._results = features
            self._populate_results(features)
            self._set_status('{} cenas encontradas / {} scenes found — {}'.format(
                len(features), len(features), collection_id))
        except urllib.error.URLError as e:
            self._set_status('Erro de conexão: {} / Connection error: {}'.format(
                e.reason, e.reason), error=True)
        except Exception as e:
            self._set_status('Erro: {} / Error: {}'.format(str(e), str(e)), error=True)
        finally:
            self.btn_puxar.setEnabled(True)

    def _populate_results(self, features):
        """Cria cards no scroll area e inicia carregamento assíncrono de thumbnails / Create cards in scroll area and start async thumbnail loading."""
        # Cancela workers de thumbnails da busca anterior — seta a flag antiga para True
        # Cancel thumbnail workers from previous search — set old flag to True
        if hasattr(self, '_thumb_cancel'):
            self._thumb_cancel[0] = True
        # Nova flag para esta busca — workers antigos verificam a flag antiga / New flag for this search — old workers check the old flag
        self._thumb_cancel = [False]

        self._cards = []
        self._selected_card_idx = None

        # Habilita ou desabilita botões conforme resultado / Enable or disable buttons based on result
        has = len(features) > 0
        self.btn_virtualizar.setEnabled(has)
        self.btn_baixar.setEnabled(has)

        # Widget interno do scroll area com grid / Scroll area inner widget with grid
        inner = QWidget()
        inner.setStyleSheet('background: #111;')
        grid  = QGridLayout(inner)
        grid.setSpacing(8)
        grid.setContentsMargins(8, 8, 8, 8)
        # Empurra cards para a esquerda / Push cards to the left
        grid.setColumnStretch(_GRID_COLS, 1)

        if not features:
            # Mensagem de resultado vazio / Empty result message
            lbl = QLabel('Nenhuma cena encontrada / No scenes found')
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet('color: #666; font-size:13px;')
            grid.addWidget(lbl, 0, 0, 1, _GRID_COLS)
        else:
            for i, feature in enumerate(features):
                # Cria card e conecta sinal de seleção / Create card and connect selection signal
                card = SceneCard(i, feature, parent=inner)
                card.selected.connect(self._on_card_clicked)
                grid.addWidget(card, i // _GRID_COLS, i % _GRID_COLS)
                self._cards.append(card)

        # Instala o widget no scroll area / Install widget in scroll area
        self.scroll_resultados.setWidget(inner)
        self.scroll_resultados.setWidgetResizable(True)

        # Inicia carregamento assíncrono de todos os thumbnails em paralelo
        # Start async loading of all thumbnails in parallel
        # QThreadPool gerencia a concorrência — workers excedentes ficam na fila
        # QThreadPool manages concurrency — excess workers queue automatically
        for card in self._cards:
            card.load_thumb(self._thumb_cancel)

    def _on_card_clicked(self, idx):
        """Seleciona o card clicado e desseleciona o anterior / Select clicked card and deselect previous."""
        # Remove seleção do card anterior / Remove selection from previous card
        if self._selected_card_idx is not None and self._selected_card_idx < len(self._cards):
            self._cards[self._selected_card_idx].set_selected(False)

        # Seleciona novo card / Select new card
        self._selected_card_idx = idx
        self._cards[idx].set_selected(True)
        # Atualiza feature selecionada / Update selected feature
        self._selected_item = self._results[idx]

    def _get_checked_features(self):
        """Retorna features com checkbox marcado ou a selecionada como fallback / Return checkbox-checked features or current selection as fallback."""
        # Coleta todas as features cujo card está marcado / Collect all features whose card is checked
        checked = [
            self._results[i]
            for i, card in enumerate(self._cards)
            if card.is_checked()
        ]
        if checked:
            return checked
        # Fallback: feature do card atualmente selecionado / Fallback: currently selected card's feature
        if self._selected_item is not None:
            return [self._selected_item]
        return []
