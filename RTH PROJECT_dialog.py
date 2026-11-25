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
from qgis.PyQt.QtWidgets import (
    QPushButton, QLabel, QTabWidget, QWidget,
    QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QCheckBox,
)
# Flags de janela / Window flags
from qgis.PyQt.QtCore import Qt, QDate

# Mixins com a lógica dividida por responsabilidade / Mixins with logic split by responsibility
from core.rth_dialog_catalog import CatalogMixin   # satélites, coleções, bandas / satellites, collections, bands
from core.rth_dialog_results import ResultsMixin   # busca STAC, cards de cenas / STAC search, scene cards
from core.rth_dialog_actions import ActionsMixin   # virtualizar, baixar, UI / virtualize, download, UI
from core.rth_dialog_aoi import AoiMixin           # aba Área de Interesse / AOI tab
from core.rth_dialog_smart_dl import SmartDlMixin  # aba Download Inteligente / Smart Download tab

# Carrega o arquivo .ui / Load .ui file
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'RTH PROJECT_dialog_base.ui'))


class rthprojectDialog(CatalogMixin, ResultsMixin, AoiMixin, SmartDlMixin, ActionsMixin,
                       QtWidgets.QDialog, FORM_CLASS):
    # ==========================================================================
    # rthprojectDialog — diálogo principal do plugin RTH PROJECT
    #
    # Herança múltipla (Mixin pattern):
    #   A classe combina 3 mixins + QDialog + FORM_CLASS via MRO do Python.
    #   Cada mixin é responsável por uma área de funcionalidade:
    #     - CatalogMixin:  satélites, coleções, bandas disponíveis
    #     - ResultsMixin:  busca STAC, cards de cenas, seleção
    #     - ActionsMixin:  virtualizar, baixar, fila de downloads, UI helpers
    #   Os mixins NÃO herdam de QDialog — apenas adicionam métodos. Isso evita
    #   criar classes gigantes com centenas de linhas em um único arquivo.
    #
    # FORM_CLASS (gerado por uic.loadUiType):
    #   O QGIS criou um arquivo .ui no Qt Designer que define a estrutura visual
    #   dos widgets (campos, botões, etc.). uic.loadUiType() lê esse arquivo e
    #   gera em tempo de execução uma classe Python com todos os widgets como
    #   atributos (self.btn_puxar, self.combo_satelite, etc.).
    #   setupUi(self) instancia fisicamente esses widgets no diálogo.
    #
    # Criado em RTH PROJECT.py quando o usuário abre o diálogo pelo menu.
    # ==========================================================================
    """Diálogo RTH API BROWSER — herda os mixins de catálogo, resultados e ações / RTH API BROWSER dialog — inherits catalog, results and actions mixins."""

    def __init__(self, iface, parent=None):
        """Construtor do diálogo / Dialog constructor."""
        super(rthprojectDialog, self).__init__(parent)
        self.iface = iface
        self.setupUi(self)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self._selected_item    = None
        self._results          = []
        self._cards            = []
        self._selected_card_idx = None
        self._collection_cache = {}
        self._api_catalog      = None
        self._current_page     = 1
        self._total_matched    = 0
        self._search_params    = None
        self._download_rows    = []
        self._custom_bands     = None
        self._init_aoi()
        self._init_smart_dl()
        self._init_ui()

    def closeEvent(self, event):
        """Cancela workers pendentes ao fechar o diálogo / Cancel pending workers when dialog closes."""
        # Flag lida por lambdas e slots guardados para evitar acesso a widgets
        # já destruídos quando sinais de threads chegam após o fechamento.
        # Flag read by lambdas and guarded slots to avoid accessing destroyed
        # widgets when thread signals arrive after close.
        self._dialog_closing = True
        if hasattr(self, '_thumb_cancel'):
            self._thumb_cancel[0] = True
        if hasattr(self, '_aoi_cancel_flag'):
            self._aoi_cancel_flag[0] = True
        t = getattr(self, '_smart_search_thread', None)
        if t and t.isRunning():
            t.quit()
            t.wait(300)
        for row in getattr(self, '_download_rows', []):
            row.cancel_if_running()
        super().closeEvent(event)

    def resizeEvent(self, event):
        # Por que posicionamento manual em vez de QLayout?
        # O diálogo vem de um .ui do Qt Designer com layout fixo.
        # Os widgets gerados pelo .ui têm tamanho e posição fixos no arquivo.
        # Para torná-los responsivos (crescer com a janela), substituímos o
        # layout automático por posicionamento manual em resizeEvent:
        # setGeometry(x, y, width, height) posiciona cada widget em relação
        # ao canto superior esquerdo do widget pai. Isso é necessário porque
        # reparentamos os widgets para _scenes_panel (QWidget sem layout),
        # e QWidget sem layout não redimensiona os filhos automaticamente.
        """Reposiciona widgets ao redimensionar — tab bar no topo, painéis abaixo /
        Reposition widgets on resize — tab bar at top, panels below."""
        super().resizeEvent(event)
        W = self.width()
        H = self.height()

        # ── Barra de abas no topo / Tab bar at top ───────────────────────────────
        TAB_H = 32
        if hasattr(self, '_tab_widget'):
            TAB_H = max(self._tab_widget.tabBar().height(), 28)
            self._tab_widget.setGeometry(0, 0, W, TAB_H)

        CONTENT_H = H - TAB_H  # altura disponível abaixo da barra / height available below bar

        # ── Painel de cenas — ocupa todo o espaço abaixo da barra ───────────────
        # Scenes panel — fills all space below the tab bar
        if hasattr(self, '_scenes_panel'):
            self._scenes_panel.setGeometry(0, TAB_H, W, CONTENT_H)

            # Widgets redimensionáveis — coordenadas relativas ao _scenes_panel
            # Resizable widgets — coordinates relative to _scenes_panel
            self.lbl_status.setGeometry(8, 68, W - 16, 18)
            self.btn_puxar.setGeometry(870, 35, W - 878, 28)

            # Área de resultados cresce com o dialog / Results area grows with dialog
            self.scroll_resultados.setGeometry(8, 96, W - 16, max(CONTENT_H - 264, 60))

            # Barra de paginação / Pagination bar
            page_y = CONTENT_H - 160
            self.btn_prev_page.setGeometry(8, page_y, 140, 26)
            self.lbl_page_info.setGeometry(156, page_y, W - 312, 26)
            self.btn_next_page.setGeometry(W - 148, page_y, 140, 26)

            # Faixa inferior / Bottom strip
            pasta_y = CONTENT_H - 128
            btn_y   = CONTENT_H - 102
            prog_y  = CONTENT_H - 58
            self.lbl_pasta.setGeometry(8, pasta_y, 105, 22)
            self.edit_pasta.setGeometry(117, pasta_y, W - 205, 22)
            self.btn_pasta.setGeometry(W - 80, pasta_y, 72, 22)
            btn_w = (W - 32) // 3
            self.btn_virtualizar.setGeometry(8,                  btn_y, btn_w, 36)
            self.btn_desmarcar.setGeometry(  16 + btn_w,         btn_y, btn_w, 36)
            self.btn_baixar.setGeometry(     24 + 2 * btn_w,     btn_y, btn_w, 36)
            self.lbl_progresso.setGeometry(8, prog_y, W - 16, 18)

        # ── Painel de AOI — mesma área que o painel de cenas ────────────────────
        # AOI panel — same area as scenes panel
        if hasattr(self, '_aoi_panel'):
            self._aoi_panel.setGeometry(0, TAB_H, W, CONTENT_H)

        # ── Painel de Download Inteligente — mesma área ───────────────────────────
        # Smart Download panel — same area as scenes panel
        if hasattr(self, '_smart_dl_panel'):
            self._smart_dl_panel.setGeometry(0, TAB_H, W, CONTENT_H)

        # ── Painel de downloads — mesma área que o painel de cenas ──────────────
        # Downloads panel — same area as scenes panel
        if hasattr(self, '_dl_panel'):
            self._dl_panel.setGeometry(0, TAB_H, W, CONTENT_H)

    def _init_ui(self):
        """Monta os dois painéis, conecta sinais e cria a barra de abas /
        Build both panels, connect signals and create the tab bar."""
        from core.rth_catalog import SATELLITE_COLLECTIONS

        # ── Painel de cenas ───────────────────────────────────────────────────────
        # Todos os widgets do .ui são reparentados aqui para que desapareçam
        # junto com o painel quando a aba Downloads estiver ativa.
        # All .ui widgets are reparented here so they disappear together
        # with the panel when the Downloads tab is active.
        self._scenes_panel = QWidget(self)

        # Lista completa de widgets criados pelo .ui / Full list of .ui-created widgets
        _ui_names = [
            'lbl_satelite', 'combo_satelite',
            'lbl_colecao',  'combo_colecao',
            'lbl_data_ini', 'date_inicial',
            'lbl_data_fin', 'date_final',
            'lbl_composicao', 'combo_composicao',
            'lbl_nuvens', 'slider_nuvem', 'lbl_nuvem_val',
            'btn_puxar', 'lbl_status', 'line_sep',
            'scroll_resultados',
            'lbl_pasta', 'edit_pasta', 'btn_pasta',
            'btn_virtualizar', 'btn_baixar',
            'lbl_progresso', 'progress_bar',
        ]
        for _name in _ui_names:
            _w = getattr(self, _name, None)
            if _w is not None:
                _w.setParent(self._scenes_panel)
                _w.show()  # setParent() oculta o widget — precisamos reexibir / setParent() hides widget — must re-show

        # Oculta o separador e a barra de progresso do .ui / Hide .ui separator and progress bar
        if hasattr(self, 'line_sep'):
            self.line_sep.setVisible(False)
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setVisible(False)

        # Conecta sinais dos widgets do .ui / Connect signals for .ui widgets
        self._populate_satellites(SATELLITE_COLLECTIONS)
        self.combo_satelite.currentIndexChanged.connect(self._on_satellite_changed)
        self.combo_colecao.currentIndexChanged.connect(self._on_colecao_changed)
        self.slider_nuvem.valueChanged.connect(self._on_slider_changed)
        self.btn_puxar.clicked.connect(self._on_puxar_clicked)
        self.btn_pasta.clicked.connect(self._on_browse_clicked)
        self.btn_virtualizar.clicked.connect(self._on_virtualizar_clicked)
        self.btn_baixar.clicked.connect(self._on_baixar_clicked)

        # Botão ⚙ — filho do painel de cenas, posição fixa sobre combo_composicao
        # ⚙ button — child of scenes panel, fixed position over combo_composicao
        self.btn_cfg_composicao = QPushButton('⚙', self._scenes_panel)
        self.btn_cfg_composicao.setGeometry(368, 38, 26, 22)
        self.btn_cfg_composicao.setEnabled(False)
        self.btn_cfg_composicao.setToolTip(
            'Configurar bandas personalizadas / Configure custom bands\n'
            '(Selecione "Personalizado" na composição / Select "Personalizado" in composition)')
        self.btn_cfg_composicao.setStyleSheet(
            'QPushButton{border:1px solid #999;border-radius:3px;background:#d0d0d0;font-size:13px;}'
            'QPushButton:hover:enabled{background:#ddeeff;border-color:#0077cc;}'
            'QPushButton:disabled{color:#bbb;background:#e8e8e8;border-color:#ccc;}')
        self.btn_cfg_composicao.clicked.connect(self._on_cfg_composicao_clicked)
        self.combo_composicao.currentIndexChanged.connect(self._on_composicao_index_changed)

        self.date_final.setDate(QDate.currentDate())
        self._on_satellite_changed(0)
        self._refresh_catalog_from_api()

        # Botão desmarcar — filho do painel de cenas / Deselect button — child of scenes panel
        self.btn_desmarcar = QPushButton('✕  Desmarcar Todas / Deselect All', self._scenes_panel)
        self.btn_desmarcar.setToolTip(
            'Desmarca todos os checkboxes e a seleção atual / '
            'Uncheck all checkboxes and clear current selection')
        self.btn_desmarcar.clicked.connect(self._deselect_all)

        # Botões de paginação — filhos do painel de cenas / Pagination — children of scenes panel
        self.btn_prev_page = QPushButton('← Anterior / Prev', self._scenes_panel)
        self.btn_prev_page.setEnabled(False)
        self.btn_prev_page.setVisible(False)
        self.btn_prev_page.clicked.connect(self._on_prev_page)

        self.lbl_page_info = QLabel('', self._scenes_panel)
        self.lbl_page_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_page_info.setStyleSheet('color: #555; font-size: 11px;')
        self.lbl_page_info.setVisible(False)

        self.btn_next_page = QPushButton('Próxima → / Next', self._scenes_panel)
        self.btn_next_page.setEnabled(False)
        self.btn_next_page.setVisible(False)
        self.btn_next_page.clicked.connect(self._on_next_page)

        # ── Painel de downloads ───────────────────────────────────────────────────
        self._dl_panel = QWidget(self)
        self._dl_panel.setVisible(False)
        self._setup_downloads_panel()

        # ── Painel de AOI ─────────────────────────────────────────────────────────
        self._setup_aoi_panel()

        # ── Painel de Download Inteligente ────────────────────────────────────────
        self._setup_smart_dl_panel()

        # ── Barra de abas no topo — sem área de conteúdo própria ─────────────────
        # Tab bar at top — no content pane (content is in sibling panels)
        # QTabWidget normalmente renderiza a barra de abas + um painel de conteúdo
        # abaixo. Aqui só queremos a BARRA (a troca de conteúdo é feita manualmente
        # com _scenes_panel e _dl_panel). O truque CSS:
        #   QTabWidget::pane { max-height: 0px; padding: 0px; border: none; }
        # zera a área de conteúdo do QTabWidget sem remover a barra de abas.
        # Os painéis reais são widgets-filhos do diálogo posicionados por
        # resizeEvent(), e _on_tab_changed() controla qual fica visível.
        # raise_() garante que a barra de abas fique por cima dos painéis.
        self._tab_widget = QTabWidget(self)
        self._tab_widget.setStyleSheet(
            'QTabWidget::pane { border: none; max-height: 0px; padding: 0px; }'
            'QTabBar::tab { padding: 6px 22px; font-size: 11px; }'
            'QTabBar::tab:selected { font-weight: bold; color: #0055aa;'
            '  border-bottom: 2px solid #0055aa; }'
            'QTabBar::tab:!selected { color: #666; }')
        self._tab_widget.addTab(QWidget(), 'Cenas / Scenes')
        self._tab_widget.addTab(QWidget(), 'AOI')
        self._tab_widget.addTab(QWidget(), 'Download Inteligente / Smart DL')
        self._tab_widget.addTab(QWidget(), 'Downloads')
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        self._tab_widget.raise_()

    # ── Painel de downloads ────────────────────────────────────────────────────

    def _setup_downloads_panel(self):
        """Monta a fila de downloads dentro de _dl_panel / Build the download queue inside _dl_panel."""
        layout = QVBoxLayout(self._dl_panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # ── Painel de configurações (oculto por padrão) / Settings panel (hidden by default) ──
        self._dl_cfg_panel = QFrame()
        self._dl_cfg_panel.setVisible(False)
        self._dl_cfg_panel.setStyleSheet(
            'QFrame{background:#f0f6ff;border:1px solid #b0d0f0;border-radius:4px;}')
        cfg_inner = QHBoxLayout(self._dl_cfg_panel)
        cfg_inner.setContentsMargins(10, 6, 10, 6)

        self._chk_parallel = QCheckBox(
            'Download Múltiplo Paralelo / Multi-Download Parallel')
        self._chk_parallel.setChecked(False)
        self._chk_parallel.setToolTip(
            'Desmarcado (padrão): uma cena por vez, em fila sequencial.\n'
            'Marcado: todas as cenas baixadas ao mesmo tempo em paralelo.\n'
            'Unchecked (default): one scene at a time, in sequential queue.\n'
            'Checked: all scenes downloaded simultaneously in parallel.')
        self._chk_parallel.setStyleSheet('font-size:11px;')
        cfg_inner.addWidget(self._chk_parallel)

        _sep = QFrame()
        _sep.setFrameShape(QFrame.Shape.VLine)
        _sep.setFrameShadow(QFrame.Shadow.Sunken)
        _sep.setStyleSheet('color:#b0d0f0;')
        cfg_inner.addWidget(_sep)

        self._chk_newest_first = QCheckBox(
            'Mais Recente Primeiro / Newest First')
        self._chk_newest_first.setChecked(False)
        self._chk_newest_first.setToolTip(
            'Desmarcado (padrão): baixa da mais antiga para a mais nova.\n'
            'Marcado: baixa da mais recente para a mais antiga.\n'
            'Unchecked (default): downloads oldest to newest.\n'
            'Checked: downloads newest to oldest.')
        self._chk_newest_first.setStyleSheet('font-size:11px;')
        cfg_inner.addWidget(self._chk_newest_first)

        cfg_inner.addStretch()

        # ── Barra superior com botão ⚙ / Top bar with ⚙ settings button ──────
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.addStretch()
        self._btn_dl_cfg = QPushButton('⚙')
        self._btn_dl_cfg.setFixedSize(26, 26)
        self._btn_dl_cfg.setCheckable(True)
        self._btn_dl_cfg.setToolTip('Configurações de download / Download settings')
        self._btn_dl_cfg.setStyleSheet(
            'QPushButton{border:1px solid #999;border-radius:3px;'
            'background:#d0d0d0;font-size:13px;color:#333;}'
            'QPushButton:checked{background:#d0e8ff;border-color:#0077cc;color:#0055aa;}'
            'QPushButton:hover{background:#ddeeff;border-color:#0077cc;}')
        self._btn_dl_cfg.toggled.connect(self._dl_cfg_panel.setVisible)
        top_bar.addWidget(self._btn_dl_cfg)
        layout.addLayout(top_bar)
        layout.addWidget(self._dl_cfg_panel)

        # ── Scroll area com a fila de downloads / Scroll area with download queue ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._dl_inner = QWidget()
        self._dl_layout = QVBoxLayout(self._dl_inner)
        self._dl_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._dl_layout.setContentsMargins(0, 0, 0, 0)
        self._dl_layout.setSpacing(8)

        self._dl_empty = QLabel(
            'Nenhum download em fila.\n'
            'Selecione cenas na aba "Cenas" e clique em Baixar.\n\n'
            'No downloads queued.\n'
            'Select scenes in the "Scenes" tab and click Download.')
        self._dl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dl_empty.setStyleSheet('color:#aaa;font-size:12px;padding:40px;')
        self._dl_layout.addWidget(self._dl_empty)

        scroll.setWidget(self._dl_inner)
        layout.addWidget(scroll, 1)

        self._btn_clear_dl = QPushButton('Limpar Concluídos / Clear Completed')
        self._btn_clear_dl.setFixedHeight(30)
        self._btn_clear_dl.setStyleSheet(
            'QPushButton{border:1px solid #ccc;border-radius:4px;'
            'background:#f5f5f5;font-size:11px;color:#444;}'
            'QPushButton:hover{background:#e8e8e8;}')
        self._btn_clear_dl.clicked.connect(self._clear_completed_downloads)
        layout.addWidget(self._btn_clear_dl)

    # ── Troca de abas ─────────────────────────────────────────────────────────

    def _on_tab_changed(self, idx):
        """Alterna entre os quatro painéis: Cenas (0), AOI (1), Download Inteligente (2), Downloads (3) /
        Toggle between four panels: Scenes (0), AOI (1), Smart DL (2), Downloads (3)."""
        self._scenes_panel.setVisible(idx == 0)
        if hasattr(self, '_aoi_panel'):
            self._aoi_panel.setVisible(idx == 1)
        if hasattr(self, '_smart_dl_panel'):
            self._smart_dl_panel.setVisible(idx == 2)
        self._dl_panel.setVisible(idx == 3)
