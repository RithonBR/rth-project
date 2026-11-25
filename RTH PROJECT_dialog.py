# -*- coding: utf-8 -*-
"""
RTH API BROWSER — Diálogo principal para busca e carregamento de imagens STAC
RTH API BROWSER — Main dialog for STAC image search and loading

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3

"""

# Biblioteca padrão para caminhos / Standard library for paths
import os

# Módulo PyQt para carregamento de arquivo UI / PyQt module for UI file loading
from qgis.PyQt import uic
# Módulos Qt para widgets / Qt modules for widgets
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QPushButton, QLabel
# Flags de janela / Window flags
from qgis.PyQt.QtCore import Qt, QDate

# Mixins com a lógica dividida por responsabilidade / Mixins with logic split by responsibility
from core.rth_dialog_catalog import CatalogMixin   # satélites, coleções, bandas / satellites, collections, bands
from core.rth_dialog_results import ResultsMixin   # busca STAC, cards de cenas / STAC search, scene cards
from core.rth_dialog_actions import ActionsMixin   # virtualizar, baixar, UI / virtualize, download, UI

# Carrega o arquivo .ui / Load .ui file
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'RTH PROJECT_dialog_base.ui'))


class rthprojectDialog(CatalogMixin, ResultsMixin, ActionsMixin,
                       QtWidgets.QDialog, FORM_CLASS):
    """Diálogo RTH API BROWSER — herda os mixins de catálogo, resultados e ações / RTH API BROWSER dialog — inherits catalog, results and actions mixins."""

    def __init__(self, iface, parent=None):
        """Construtor do diálogo / Dialog constructor."""
        super(rthprojectDialog, self).__init__(parent)
        # Interface QGIS / QGIS interface
        self.iface = iface
        # Popula widgets do arquivo .ui / Populate widgets from .ui file
        self.setupUi(self)
        # Habilita botões de minimizar e fechar na barra de título / Enable minimize and close buttons in title bar
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        # Feature atualmente selecionada / Currently selected feature
        self._selected_item = None
        # Lista de features da última busca / Feature list from last search
        self._results = []
        # Lista de widgets SceneCard ativos / Active SceneCard widget list
        self._cards = []
        # Índice do card atualmente selecionado / Currently selected card index
        self._selected_card_idx = None
        # Cache de metadados de coleção: {collection_id: detail_dict} / Collection metadata cache
        self._collection_cache = {}
        # Catálogo dinâmico carregado da API / Dynamic catalog loaded from API
        self._api_catalog = None
        # Paginação / Pagination state
        self._current_page  = 1
        self._total_matched = 0
        self._search_params = None
        # Inicializa a UI / Initialize UI
        self._init_ui()

    def closeEvent(self, event):
        """Cancela workers pendentes ao fechar o diálogo / Cancel pending workers when dialog closes."""
        # Para todos os workers de thumbnail em andamento / Stop all in-progress thumbnail workers
        if hasattr(self, '_thumb_cancel'):
            self._thumb_cancel[0] = True
        # Para o download em andamento, se houver / Stop in-progress download if any
        if hasattr(self, '_download_thread') and self._download_thread is not None:
            self._download_thread.cancel()
            # Aguarda até 3 s para finalizar graciosamente / Wait up to 3 s to finish gracefully
            self._download_thread.wait(3000)
        super().closeEvent(event)

    def resizeEvent(self, event):
        """Reposiciona e redimensiona widgets ao redimensionar a janela / Reposition and resize widgets on window resize."""
        super().resizeEvent(event)
        W = self.width()
        H = self.height()

        # ── Faixa superior: stretching horizontal / Top strip: horizontal stretch ──
        # Status ocupa toda a largura / Status spans full width
        self.lbl_status.setGeometry(8, 68, W - 16, 18)
        # Separador ocupa toda a largura / Separator spans full width
        self.line_sep.setGeometry(8, 90, W - 16, 3)
        # Botão "Puxar Imagens" começa após o slider de nuvens e estica até a borda direita / "Puxar" button starts after cloud slider and stretches to right edge
        self.btn_puxar.setGeometry(870, 35, W - 878, 28)

        # ── Scroll area: cresce para preencher o espaço central / Scroll area grows to fill center ──
        # Altura = janela menos topo(96) menos rodapé(162) / Height = window minus top(96) minus footer(162)
        self.scroll_resultados.setGeometry(8, 96, W - 16, max(H - 260, 100))

        # Barra de paginação / Pagination bar
        page_y = H - 160
        self.btn_prev_page.setGeometry(8, page_y, 140, 26)
        self.lbl_page_info.setGeometry(156, page_y, W - 312, 26)
        self.btn_next_page.setGeometry(W - 148, page_y, 140, 26)

        # ── Faixa inferior ancorada ao rodapé / Bottom strip anchored to footer ──
        pasta_y = H - 128   # linha da pasta de saída / output folder row
        btn_y   = H - 102   # linha dos botões de ação / action buttons row
        prog_y  = H - 58    # linha do label de progresso / progress label row
        bar_y   = H - 36    # linha da barra de progresso / progress bar row

        # Pasta de saída / Output folder row
        self.lbl_pasta.setGeometry(8, pasta_y, 105, 22)
        self.edit_pasta.setGeometry(117, pasta_y, W - 205, 22)
        self.btn_pasta.setGeometry(W - 80, pasta_y, 72, 22)

        # Três botões dividem a largura igualmente / Three buttons split width evenly
        btn_w = (W - 32) // 3
        self.btn_virtualizar.setGeometry(8,                  btn_y, btn_w, 36)
        self.btn_desmarcar.setGeometry(  16 + btn_w,         btn_y, btn_w, 36)
        self.btn_baixar.setGeometry(     24 + 2 * btn_w,     btn_y, btn_w, 36)

        # Progresso / Progress
        self.lbl_progresso.setGeometry(8, prog_y, W - 16, 18)
        self.progress_bar.setGeometry(8, bar_y, W - 16, 16)

    def _init_ui(self):
        """Configura widgets e conecta sinais / Set up widgets and connect signals."""
        # Importa catálogo estático para popular o combo inicial / Import static catalog to populate initial combo
        from core.rth_catalog import SATELLITE_COLLECTIONS
        # Preenche combo de satélites com o catálogo estático / Fill satellite combo with static catalog
        self._populate_satellites(SATELLITE_COLLECTIONS)
        # Satélite muda → atualiza coleções / Satellite changes → update collections
        self.combo_satelite.currentIndexChanged.connect(self._on_satellite_changed)
        # Coleção muda → atualiza composições e eo:bands / Collection changes → update compositions and eo:bands
        self.combo_colecao.currentIndexChanged.connect(self._on_colecao_changed)
        # Slider de nuvens → atualiza rótulo / Cloud slider → update label
        self.slider_nuvem.valueChanged.connect(self._on_slider_changed)
        # Botão puxar imagens / Fetch images button
        self.btn_puxar.clicked.connect(self._on_puxar_clicked)
        # Botão de pasta de destino / Output folder button
        self.btn_pasta.clicked.connect(self._on_browse_clicked)
        # Botão virtualizar / Virtualize button
        self.btn_virtualizar.clicked.connect(self._on_virtualizar_clicked)
        # Botão baixar / Download button
        self.btn_baixar.clicked.connect(self._on_baixar_clicked)
        # Define data final como hoje / Set end date to today
        self.date_final.setDate(QDate.currentDate())
        # Inicializa o primeiro satélite / Initialize first satellite
        self._on_satellite_changed(0)
        # Tenta carregar o catálogo dinâmico da API / Try to load dynamic catalog from API
        self._refresh_catalog_from_api()

        # Botão desmarcar todas / Deselect all button
        self.btn_desmarcar = QPushButton('✕  Desmarcar Todas / Deselect All', self)
        self.btn_desmarcar.setEnabled(True)
        self.btn_desmarcar.setToolTip('Desmarca todos os checkboxes e a seleção atual / Uncheck all checkboxes and clear current selection')
        self.btn_desmarcar.clicked.connect(self._deselect_all)

        # Botões de paginação / Pagination buttons
        self.btn_prev_page = QPushButton('← Anterior / Prev', self)
        self.btn_prev_page.setEnabled(False)
        self.btn_prev_page.setVisible(False)
        self.btn_prev_page.clicked.connect(self._on_prev_page)

        self.lbl_page_info = QLabel('', self)
        self.lbl_page_info.setAlignment(Qt.AlignCenter)
        self.lbl_page_info.setStyleSheet('color: #555; font-size: 11px;')
        self.lbl_page_info.setVisible(False)

        self.btn_next_page = QPushButton('Próxima → / Next', self)
        self.btn_next_page.setEnabled(False)
        self.btn_next_page.setVisible(False)
        self.btn_next_page.clicked.connect(self._on_next_page)
