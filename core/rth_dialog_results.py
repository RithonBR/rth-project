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
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal

# Importa busca STAC e bbox do canvas / Import STAC search and canvas bbox
from .rth_stac_api import search_stac, search_stac_pc, get_bbox_from_canvas, provider_label_for, _route_for, STAC_PC
# Importa widget de card de cena / Import scene card widget
from .rth_scene_card import SceneCard

# Número de colunas no grid de cards / Number of columns in the card grid
_GRID_COLS = 4


class _PageLoader(QThread):
    """Executa a busca STAC em background para não travar a UI / Runs STAC search in background to keep UI responsive."""

    done   = pyqtSignal(list, int, object, object)  # features, total, next_body, prev_body
    failed = pyqtSignal(str)

    def __init__(self, fn, args, kwargs):
        super().__init__()
        self._fn     = fn
        self._args   = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            if len(result) == 4:
                self.done.emit(*result)
            else:
                # search_stac retorna 2-tuple — completa com None, None
                self.done.emit(result[0], result[1], None, None)
        except urllib.error.URLError as e:
            self.failed.emit('URL:{}'.format(e.reason))
        except Exception as e:
            self.failed.emit(str(e))


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

        # Armazena parâmetros da busca para paginação / Store search params for pagination
        self._search_params = {
            'collection_id': collection_id,
            'bbox':          bbox,
            'date_ini':      date_ini,
            'date_fim':      date_fim,
            'cloud_max':     cloud_max,
        }
        self._current_page   = 1
        self._total_matched  = 0
        self._next_body      = None   # body do link next (PC cursor pagination)
        self._prev_body      = None   # body do link previous (PC cursor pagination)
        self._load_page(1)

    def _load_page(self, page, cursor_body=None):
        """Inicia carregamento de página em background / Start page loading in background."""
        p = self._search_params
        if page == 1:
            self._set_status('Buscando... / Searching...')
        else:
            self._set_status('Carregando página {} / Loading page {}...'.format(page, page))

        self._pending_page = page
        self.btn_puxar.setEnabled(False)
        if hasattr(self, 'btn_prev_page'):
            self.btn_prev_page.setEnabled(False)
        if hasattr(self, 'btn_next_page'):
            self.btn_next_page.setEnabled(False)

        # Cancela loader anterior se ainda estiver rodando
        # Cancel previous loader if still running
        if hasattr(self, '_page_loader') and self._page_loader and self._page_loader.isRunning():
            self._page_loader.quit()
            self._page_loader.wait(2000)

        endpoint, _ = _route_for(p['collection_id'])
        if endpoint == STAC_PC:
            fn     = search_stac_pc
            args   = (p['collection_id'], p['bbox'], p['date_ini'], p['date_fim'], p['cloud_max'])
            kwargs = {'cursor_body': cursor_body}
        else:
            fn     = search_stac
            args   = (p['collection_id'], p['bbox'], p['date_ini'], p['date_fim'], p['cloud_max'])
            kwargs = {'page': page}

        self._page_loader = _PageLoader(fn, args, kwargs)
        self._page_loader.done.connect(lambda f, t, nb, pb: self._on_page_loaded(page, f, t, nb, pb))
        self._page_loader.failed.connect(self._on_page_failed)
        self._page_loader.start()

    def _on_page_loaded(self, page, features, total, next_body, prev_body):
        """Callback executado na thread principal quando o loader termina / Callback on main thread when loader finishes."""
        self._current_page  = page
        self._total_matched = total
        self._next_body     = next_body
        self._prev_body     = prev_body
        self._results       = features
        self._populate_results(features)
        self._update_page_controls()
        self._set_status('{} cenas encontradas / {} scenes found — {}'.format(
            total, total, self._search_params['collection_id']))
        self.btn_puxar.setEnabled(True)

    def _on_page_failed(self, msg):
        """Callback de erro do loader / Loader error callback."""
        self.btn_puxar.setEnabled(True)
        self._update_page_controls()   # reabilita botões de página
        p = self._search_params
        if msg.startswith('URL:'):
            provider = provider_label_for(p['collection_id'])
            self._set_status(
                'Este Provedor ({0}) se encontra indisponivel no momento, '
                'tente os outros provedores ou tente mais tarde / '
                'Provider ({0}) is currently unavailable, '
                'try another provider or try again later.'.format(provider),
                error=True)
        else:
            self._set_status('Erro: {} / Error: {}'.format(msg, msg), error=True)

    def _on_prev_page(self):
        """Navega para a página anterior / Navigate to the previous page."""
        page      = getattr(self, '_current_page', 1)
        prev_body = getattr(self, '_prev_body', None)
        if prev_body:
            # PC cursor pagination — usa o body do link previous diretamente
            self._load_page(page - 1, cursor_body=prev_body)
        elif page > 1:
            self._load_page(page - 1)

    def _on_next_page(self):
        """Navega para a próxima página / Navigate to the next page."""
        page      = getattr(self, '_current_page', 1)
        total     = getattr(self, '_total_matched', 0)
        next_body = getattr(self, '_next_body', None)
        if next_body:
            # PC cursor pagination — usa o body do link next diretamente
            self._load_page(page + 1, cursor_body=next_body)
        elif page * 100 < total:
            self._load_page(page + 1)

    def _update_page_controls(self):
        """Atualiza texto e estado dos controles de paginação / Update pagination controls text and state."""
        page      = getattr(self, '_current_page', 1)
        total     = getattr(self, '_total_matched', 0)
        next_body = getattr(self, '_next_body', None)
        prev_body = getattr(self, '_prev_body', None)
        pages     = max(1, (total + 99) // 100)

        if hasattr(self, 'lbl_page_info'):
            if next_body or prev_body:
                # Planetary Computer — sem total de páginas, exibe só a página atual
                # Planetary Computer — no total pages, show current page only
                self.lbl_page_info.setText(
                    'Página {} / Page {}'.format(page, page))
            else:
                # INPE/AWS — total conhecido, exibe página atual e total entre parênteses
                # INPE/AWS — total known, show current page and total in parentheses
                self.lbl_page_info.setText(
                    'Pág. {} ({}) • {} cenas / Pg. {} ({}) • {} scenes'.format(
                        page, pages, total, page, pages, total))

        has_prev = prev_body is not None or page > 1
        has_next = next_body is not None or page < pages
        if hasattr(self, 'btn_prev_page'):
            self.btn_prev_page.setEnabled(has_prev)
        if hasattr(self, 'btn_next_page'):
            self.btn_next_page.setEnabled(has_next)
        visible = has_prev or has_next
        for w in ('btn_prev_page', 'btn_next_page', 'lbl_page_info'):
            if hasattr(self, w):
                getattr(self, w).setVisible(visible)

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

    def _deselect_all(self):
        """Desmarca todos os checkboxes e limpa a seleção atual / Uncheck all checkboxes and clear current selection."""
        for card in self._cards:
            card.chk.setChecked(False)
        if self._selected_card_idx is not None and self._selected_card_idx < len(self._cards):
            self._cards[self._selected_card_idx].set_selected(False)
        self._selected_card_idx = None
        self._selected_item     = None

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
