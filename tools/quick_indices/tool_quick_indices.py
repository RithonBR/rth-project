# -*- coding: utf-8 -*-
# ============================================================
# FERRAMENTA: Índices Rápidos por Imagem / Quick Image Indices
#
# O que faz (ponto de vista do usuário):
#   O usuário abre o diálogo, escolhe uma coleção Sentinel-2 e um
#   intervalo de datas. A ferramenta detecta automaticamente a bbox
#   (bounding box) da área visível no canvas do QGIS e busca cenas
#   via STAC (Space/Time Asset Catalog). O usuário seleciona uma ou
#   mais cenas na lista e clica em Calcular Índice — lê apenas as
#   bandas necessárias via vsicurl (COG remoto) e gera uma camada
#   raster com o índice (NDVI, EVI, etc.) diretamente no QGIS.
#
# Diferença em relação à ferramenta tool_field_analysis:
#   - NÃO exige camada polígono — usa a bbox do canvas diretamente
#   - É mais rápida para estudos de caso de cenas específicas
#   - Compartilha as funções de cálculo com field_analysis via import
#
# Como funciona internamente:
#   O plugin cria uma instância de QuickIndicesTool em RTH PROJECT.py
#   no __init__(). Quando o usuário clica no menu, o método run() é
#   chamado — ele cria ou re-exibe um QuickIndicesDialog.
#   QuickIndicesDialog é um QDialog que gerencia toda a interação.
#
# Criada em RTH PROJECT.py no __init__() do plugin.
# Ativada via menu Funcionalidades Adicionais > Índices Rápidos por Imagem.
# ============================================================

import os
import re
import tempfile

# Imports de Qt via qgis.PyQt — SEMPRE usar qgis.PyQt, nunca PyQt5 ou PyQt6
# diretamente. O QGIS fornece um shim que garante que o mesmo import funcione
# tanto no QGIS 3 (Qt5) quanto no QGIS 4 (Qt6).
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QComboBox, QFrame, QGroupBox, QWidget, QScrollArea,
    QApplication, QMessageBox, QListWidget, QListWidgetItem,
    QProgressDialog, QLineEdit, QToolButton,
    QDateEdit, QSpinBox, QCheckBox, QFileDialog,
)
from qgis.PyQt.QtCore import Qt, QDate, QThread, pyqtSignal
from qgis.PyQt.QtGui import QPixmap
from qgis.core import (
    Qgis, QgsProject, QgsRasterLayer,
)

# Módulos internos do plugin RTH:
#   - search_stac:         faz a busca no STAC e retorna lista de features GeoJSON
#   - search_stac_pc:      idem mas para o Planetary Computer (usa paginação por cursor)
#   - _route_for:          retorna (endpoint_url, real_id) para a coleção
#   - STAC_PC:             constante com a URL base do Planetary Computer
#   - get_bbox_from_canvas: retorna [xmin, ymin, xmax, ymax] em WGS84 do canvas atual
#   - collapse_layer:      fecha o grupo da camada no painel de camadas (visual)
from core.rth_stac_api import search_stac, search_stac_pc, _route_for, STAC_PC, get_bbox_from_canvas
from core.rth_layer_utils import collapse_layer

# Reutilizamos as funções e constantes de cálculo do tool_field_analysis para evitar
# duplicação de código — se field_analysis for atualizado, quick_indices se beneficia.
# Reuse computation functions and constants from tool_field_analysis to avoid
# code duplication — if field_analysis is updated, quick_indices benefits.
#
# O que cada símbolo importado faz:
#   _INDEX_DEFS   — dicionário com todos os índices disponíveis (NDVI, EVI, etc.)
#                   e suas fórmulas, variáveis necessárias, e limites de visualização
#   _BAND_VARS    — mapeamento de nome de variável ('nir') para banda S-2 ('B08')
#   _clip_band    — abre uma banda via vsicurl e recorta para a bbox (sem download)
#   _eval_formula — avalia a expressão do índice com numpy (ex: "(nir-red)/(nir+red)")
#   _write_tiff   — salva o resultado numpy como arquivo GeoTIFF no disco
#   _apply_pseudocolor — aplica paleta de cor ao raster (verde = alto, vermelho = baixo)
#   _init_gdal    — importa GDAL de forma segura e retorna o módulo ou None
#   _scene_utm    — descobre o CRS UTM da cena a partir dos metadados STAC
#   _parse_s2_id  — extrai data, MGRS tile e sufixo de um ID Sentinel-2
#   _find_thumbnail_url — encontra a URL da preview da cena nos metadados STAC
#   _ThumbFetcher — QThread que baixa o thumbnail em background para não travar a UI
#   _ds_to_array  — converte um gdal.Dataset em array numpy
#   _match_shape  — redimensiona array para ter o mesmo shape da banda de referência
#   _NODATA       — valor sentinel usado para pixels inválidos (geralmente -9999)
#   _DEPS_OK      — bool: True se numpy e gdal estão disponíveis no ambiente
#   _DEPS_MSG     — string com instruções de instalação se _DEPS_OK for False
from tools.field_analysis.tool_field_analysis import (
    _INDEX_DEFS, _BAND_VARS, _clip_band, _eval_formula, _write_tiff,
    _init_gdal, _scene_utm, _parse_s2_id,
    _find_thumbnail_url, _ThumbFetcher, _ds_to_array, _match_shape,
    _NODATA, _DEPS_OK, _DEPS_MSG, _resolve,
)

# ── Coleções disponíveis ──────────────────────────────────────────────────────
# Cada entrada é uma tupla (id_interno_stac, label_exibido_ao_usuario).
# O id_interno_stac é roteado em core/rth_stac_api.py via _COLLECTION_ROUTING
# para o endpoint correto (BDC, AWS Element84 ou Planetary Computer).
# Não adicione coleções aqui sem antes adicionar o roteamento em rth_stac_api.py.
_COLLECTIONS = [
    ('S2_L2A-1',       'Sentinel-2 L2A — INPE/BDC (Brasil)'),
    ('sentinel-2-l2a', 'Sentinel-2 L2A — Planetary Computer (Global)'),
]


# ── STAC search thread ────────────────────────────────────────────────────────

class _StacSearchThread(QThread):
    """Executa busca STAC em background / Runs STAC search in background."""
    result = pyqtSignal(list, object, object)   # features, next_body, prev_body
    error  = pyqtSignal(str)

    def __init__(self, params, parent=None):
        super().__init__(parent)
        self._params = params

    def run(self):
        try:
            p = self._params
            endpoint, _ = _route_for(p['coll_id'])
            if endpoint == STAC_PC:
                features, _, next_body, prev_body = search_stac_pc(
                    p['coll_id'], p['bbox'], p['date_ini'], p['date_fim'],
                    p['cloud_max'])
            else:
                features, _ = search_stac(
                    p['coll_id'], p['bbox'], p['date_ini'], p['date_fim'],
                    p['cloud_max'])
                next_body = None
                prev_body = None
            self.result.emit(features, next_body, prev_body)
        except Exception as e:
            self.error.emit(str(e))


# ── Compute thread ────────────────────────────────────────────────────────────

class _ComputeThread(QThread):
    """Executa o cálculo de índices em background para não travar o QGIS.
    Runs index computation in background to avoid freezing QGIS.
    """
    progress_sig = pyqtSignal(int, int, str)          # (current, total, scene_label)
    scene_done   = pyqtSignal(str, str)                # (out_path, layer_name)
    scene_error  = pyqtSignal(str)                    # error message
    all_done     = pyqtSignal(int)                    # (n_ok,)

    def __init__(self, tasks, parent=None):
        super().__init__(parent)
        self._tasks  = tasks   # list of dicts prepared by _on_compute
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        ok = 0
        for i, t in enumerate(self._tasks):
            if self._cancel:
                break
            self.progress_sig.emit(i, len(self._tasks), t['label'])  # i = cenas já concluídas
            datasets  = {}
            ref_gt = ref_proj = ref_shape = None
            try:
                gdal = _init_gdal()
                if gdal is None:
                    raise RuntimeError('GDAL não disponível / GDAL not available')
                target_crs   = _scene_utm(t['feature'])
                x_res, y_res = t['x_res'], t['y_res']
                for var in t['needed']:
                    if self._cancel:
                        break
                    ds = _clip_band(t['feature'], _BAND_VARS[var], t['bbox'],
                                    gdal, target_crs, None,
                                    xRes=x_res, yRes=y_res)
                    if ds is None:
                        raise ValueError(
                            'Banda {} ({}) não encontrada na cena. / '
                            'Band {} ({}) not found in scene.'.format(
                                _BAND_VARS[var], var, _BAND_VARS[var], var))
                    if ref_gt is None:
                        ref_gt    = ds.GetGeoTransform()
                        ref_proj  = ds.GetProjection()
                        ref_shape = (ds.RasterYSize, ds.RasterXSize)
                    datasets[var] = ds

                if self._cancel:
                    continue

                arrays = {v: _match_shape(_ds_to_array(ds), ref_shape)
                          for v, ds in datasets.items()}
                result = _eval_formula(t['formula'], arrays)
                _write_tiff(result, ref_gt, ref_proj, t['out_path'])
                self.scene_done.emit(t['out_path'], t['name'])
                ok += 1
            except Exception as e:
                self.scene_error.emit(
                    'Cena {} / Scene {}: {}'.format(i + 1, i + 1, str(e)))
            finally:
                for ds in datasets.values():
                    del ds
        self.all_done.emit(ok)


# ── Dialog ────────────────────────────────────────────────────────────────────

class QuickIndicesDialog(QDialog):
    # QDialog é uma janela filha do QGIS (não independente).
    # Diferente de QMainWindow, um QDialog é pensado para interações temporárias —
    # o usuário preenche campos, clica em OK/Fechar, e o diálogo some.
    # Usamos QDialog porque esta ferramenta é modal no sentido de fluxo, mas
    # o usuário pode manter aberto enquanto olha o mapa (não bloqueamos o QGIS).
    #
    # Por que não QMainWindow?
    #   QMainWindow tem menu bar, status bar, toolbars — overhead desnecessário.
    #   QDialog é leve e segue as convenções da plataforma (botão X para fechar).

    def __init__(self, iface, parent=None):
        # super().__init__(parent) deve sempre ser a PRIMEIRA linha.
        # Isso inicializa a classe base Qt — sem isso, nenhum widget funcionará.
        # parent=None significa que o diálogo não tem janela-pai explícita,
        # mas o QGIS ainda o mantém no contexto da janela principal.
        super().__init__(parent)
        self.iface = iface

        # _thumb_fetcher: o QThread que busca o thumbnail em background.
        # Mantemos a referência para poder cancelar se o usuário trocar de cena
        # antes do download da prévia terminar — sem isso, teríamos threads soltas.
        self._thumb_fetcher = None

        # _compute_thread: QThread do cálculo de índices em background.
        # _compute_errors:  erros acumulados durante o cálculo (exibidos no final).
        # _progress_dlg:    QProgressDialog não-modal exibido durante o cálculo.
        # Guardamos as referências para poder cancelar se o usuário fechar o diálogo.
        self._compute_thread = None
        self._compute_errors = []
        self._progress_dlg   = None

        # _features: lista de dicionários GeoJSON retornados pelo search_stac().
        # Cada "feature" representa uma cena Sentinel-2 com metadados e links
        # para os assets (bandas, thumbnail, etc.). É o nosso modelo de dados.
        self._features = []

        self._search_params = {}
        self._save_folder   = None
        self._search_thread = None

        self.setWindowTitle('RTH — Índices de Vegetação em Imagem / Vegetation Indices in Image')

        # WA_QuitOnClose: por padrão, Qt encerra o processo quando a última janela
        # top-level é fechada. Desativamos para que fechar este diálogo não mate o QGIS.
        # try/except necessário: Qt5 usa Qt.WA_QuitOnClose, Qt6 usa Qt.WidgetAttribute.WA_QuitOnClose.
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        except AttributeError:
            self.setAttribute(Qt.WA_QuitOnClose, False)

        # Qt.Window: faz o diálogo ter seu próprio ícone na barra de tarefas.
        # Qt.WindowMinimizeButtonHint: mostra o botão minimizar — útil para o usuário
        #   tirar o diálogo da tela sem fechar enquanto aguarda o cálculo.
        # Qt.WindowCloseButtonHint: mostra o botão X.
        # Qt.WindowStaysOnTopHint: mantém o diálogo visível sobre o canvas do QGIS.
        # Nota: no QGIS 4 / Qt6, esses valores têm shim de compat — são seguros.
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(580)
        self.setMinimumHeight(680)
        self.setMaximumHeight(940)

        # ── Layout raiz ───────────────────────────────────────────────────────
        # Usamos um layout em dois níveis:
        #   outer (QVBoxLayout) → ocupa a janela inteira, sem margens
        #     └─ scroll (QScrollArea) → área rolável com todo o formulário
        #         └─ container (QWidget) → widget filho do scroll
        #             └─ root (QVBoxLayout) → empilha os grupos (search, index, etc.)
        #
        # Por que QScrollArea?
        #   Se o conteúdo for maior que a janela (telas pequenas), o usuário pode
        #   rolar para ver tudo. Sem QScrollArea, widgets ficariam cortados.
        #
        # Os botões de ação (Calcular, Virtualizar, Baixar) ficam FORA do scroll,
        # no outer, para sempre estarem visíveis mesmo com o formulário rolado.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # Esconder scroll horizontal para que o conteúdo se ajuste à largura.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        root = QVBoxLayout(container)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────────
        lbl_t = QLabel('Índices Rápidos por Imagem / Quick Image Indices')
        lbl_t.setAlignment(Qt.AlignCenter)
        lbl_t.setStyleSheet('font-size:13px;font-weight:bold;')
        root.addWidget(lbl_t)

        lbl_s = QLabel(
            'Busque cenas Sentinel-2 pela área visível no mapa, selecione uma ou mais e calcule índices.\n'
            'Search Sentinel-2 scenes by the visible map area, select one or more and compute indices.')
        lbl_s.setAlignment(Qt.AlignCenter)
        lbl_s.setStyleSheet('color:#666;font-size:10px;')
        lbl_s.setWordWrap(True)
        root.addWidget(lbl_s)

        # Aviso de dependências ausentes — aparece só se numpy ou gdal não estiverem
        # instalados no ambiente Python do QGIS. _DEPS_OK e _DEPS_MSG vêm de
        # tool_field_analysis.py onde a checagem é feita com try/except de import.
        if not _DEPS_OK:
            lbl_dep = QLabel('⚠  Dependências ausentes / Missing deps: numpy, gdal — ' + _DEPS_MSG)
            lbl_dep.setWordWrap(True)
            lbl_dep.setStyleSheet(
                'color:#b71c1c;background:#ffebee;border:1px solid #e57373;'
                'border-radius:3px;padding:4px;font-size:10px;')
            root.addWidget(lbl_dep)

        root.addWidget(self._sep())

        # ── Busca / Search ────────────────────────────────────────────────────
        # QGroupBox cria um container visual com título — útil para agrupar
        # campos relacionados e deixar a UI mais clara para o usuário.
        grp_search = QGroupBox('Busca de Imagem Sentinel-2 / Scene Search')

        # QGridLayout organiza widgets em linhas e colunas.
        # Aqui: coluna 0 = labels, coluna 1 = inputs.
        # setColumnStretch(1, 1) faz a coluna dos inputs expandir com a janela.
        gl_s = QGridLayout()
        gl_s.setContentsMargins(8, 6, 8, 8)
        gl_s.setSpacing(6)
        gl_s.setColumnStretch(1, 1)

        gl_s.addWidget(QLabel('Coleção / Collection:'), 0, 0)
        self.combo_coll = QComboBox()
        # Cada item do combo armazena um "user data" (cid) além do texto visível.
        # combo.currentData() retorna o cid, que é o que enviamos para a API STAC.
        # Assim, o usuário vê "Sentinel-2 L2A — INPE/BDC" mas o código usa "S2_L2A-1".
        for cid, clabel in _COLLECTIONS:
            self.combo_coll.addItem(clabel, cid)
        gl_s.addWidget(self.combo_coll, 0, 1)

        gl_s.addWidget(QLabel('Data inicial / From:'), 1, 0)
        self.date_from = QDateEdit()
        # setCalendarPopup(True): ao clicar no campo, abre um calendário visual.
        # Sem isso, o usuário teria que digitar a data manualmente.
        self.date_from.setCalendarPopup(True)
        # Padrão: 90 dias atrás — período razoável para começar a busca.
        self.date_from.setDate(QDate.currentDate().addDays(-90))
        self.date_from.setDisplayFormat('yyyy-MM-dd')
        gl_s.addWidget(self.date_from, 1, 1)

        gl_s.addWidget(QLabel('Data final / To:'), 2, 0)
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setDisplayFormat('yyyy-MM-dd')
        gl_s.addWidget(self.date_to, 2, 1)

        gl_s.addWidget(QLabel('Nuvem máx. / Max cloud:'), 3, 0)
        self.spin_cloud = QSpinBox()
        self.spin_cloud.setRange(0, 100)
        self.spin_cloud.setValue(20)
        # setSuffix(' %'): exibe o símbolo de porcentagem visualmente, mas
        # spin_cloud.value() retorna o número inteiro sem o sufixo (20, não '20 %').
        self.spin_cloud.setSuffix(' %')
        gl_s.addWidget(self.spin_cloud, 3, 1)

        btn_search = QPushButton('Buscar Cenas / Search Scenes')
        btn_search.setStyleSheet(
            'QPushButton{background:#0277bd;color:white;border-radius:4px;'
            'border:none;padding:5px 10px;font-weight:bold;}'
            'QPushButton:hover{background:#01579b;}')
        # clicked.connect(...): conecta o sinal "botão clicado" ao método _on_search.
        # No Qt, sinais e slots são a forma de comunicação entre widgets —
        # quando o usuário clica, Qt emite o sinal "clicked" e chama _on_search().
        btn_search.clicked.connect(self._on_search)
        gl_s.addWidget(btn_search, 4, 0, 1, 2)

        # ── Lista de cenas + thumbnail ─────────────────────────────────────────
        # Disposição lado a lado: lista à esquerda (flexível), thumbnail à direita (fixo).
        scene_row = QHBoxLayout()
        scene_row.setContentsMargins(0, 0, 0, 0)
        scene_row.setSpacing(6)

        self.list_scenes = QListWidget()
        # ExtendedSelection: permite que o usuário selecione múltiplos itens com
        # Ctrl+click ou Shift+click — importante pois calcular índice para várias
        # cenas de uma vez é o principal diferencial desta ferramenta.
        # Sem isso, o modo padrão (SingleSelection) limitaria a uma cena por vez.
        self.list_scenes.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_scenes.setMinimumHeight(140)
        self.list_scenes.setMaximumHeight(200)
        self.list_scenes.setToolTip(
            'Ctrl+click para selecionar múltiplas cenas — uma camada por cena. / '
            'Ctrl+click to select multiple scenes — one layer per scene.')
        # currentItemChanged: disparado quando o usuário muda o item destacado na lista.
        # Usamos para mostrar o thumbnail da cena destacada (não das selecionadas).
        self.list_scenes.currentItemChanged.connect(self._on_scene_selected)
        scene_row.addWidget(self.list_scenes, 1)

        # Área de thumbnail: QLabel com tamanho fixo.
        # Pode exibir texto (estado inicial) ou um QPixmap (imagem carregada).
        self._thumb_label = QLabel('Sem prévia\nNo preview')
        self._thumb_label.setFixedSize(200, 145)
        self._thumb_label.setAlignment(Qt.AlignCenter)
        self._thumb_label.setWordWrap(True)
        self._thumb_label.setStyleSheet(
            'background:#1a1a1a;border:1px solid #444;border-radius:3px;'
            'color:#888;font-size:9px;')
        scene_row.addWidget(self._thumb_label, 0)

        scene_container = QWidget()
        scene_container.setLayout(scene_row)
        gl_s.addWidget(scene_container, 5, 0, 1, 2)

        self.lbl_status = QLabel(
            'Zoom para a área de interesse e clique em Buscar. / '
            'Zoom to your area of interest then click Search.')
        self.lbl_status.setStyleSheet('color:#666;font-size:10px;')
        self.lbl_status.setWordWrap(True)
        gl_s.addWidget(self.lbl_status, 6, 0, 1, 2)

        grp_search.setLayout(gl_s)
        root.addWidget(grp_search)

        # ── Bandas (colapsável / collapsible) ─────────────────────────────────
        # QToolButton com setCheckable(True) age como toggle — clicado/desclicado.
        # É mais leve que um QPushButton para este caso de "expandir/recolher".
        # toggled.connect(...): disparado sempre que o estado checked muda.
        self._btn_bands = QToolButton()
        self._btn_bands.setCheckable(True)
        self._btn_bands.setChecked(False)
        # ToolButtonTextOnly: mostra apenas texto, sem ícone — deixamos o texto
        # ter o ▶/▼ como pseudo-ícone. No QGIS 4 / Qt6, tem shim de compat.
        self._btn_bands.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._btn_bands.setStyleSheet(
            'QToolButton{border:1px solid #bbb;border-radius:3px;padding:3px 6px;'
            'background:#f5f5f5;font-weight:bold;font-size:10px;text-align:left;}'
            'QToolButton:checked{background:#e3f2fd;}')
        self._btn_bands.toggled.connect(self._toggle_bands)
        self._btn_bands.setText('▶  Bandas utilizadas / Bands used')
        root.addWidget(self._btn_bands)

        # _wgt_bands começa oculto (setVisible(False)).
        # Só aparece quando o usuário clicar no botão de expandir.
        # É uma tabela informativa das bandas do Sentinel-2 e suas variáveis.
        self._wgt_bands = QWidget()
        bands_grid = QGridLayout(self._wgt_bands)
        bands_grid.setContentsMargins(8, 4, 8, 4)
        bands_grid.setSpacing(3)
        bands_grid.addWidget(QLabel('<b>Variável / Variable</b>'), 0, 0)
        bands_grid.addWidget(QLabel('<b>Banda S-2 / S-2 Band</b>'), 0, 1)
        bands_grid.addWidget(QLabel('<b>Resolução / Resolution</b>'), 0, 2)
        for r, (var, band, res) in enumerate([
            ('nir', 'B08', '10 m'), ('red', 'B04', '10 m'),
            ('green', 'B03', '10 m'), ('blue', 'B02', '10 m'),
            ('swir1', 'B11', '20 m'), ('swir2', 'B12', '20 m'),
            ('rededge', 'B05', '20 m'), ('rededge2', 'B06', '20 m'),
            ('rededge3', 'B07', '20 m'), ('nir2', 'B8A', '20 m'),
        ], start=1):
            bands_grid.addWidget(QLabel(var), r, 0)
            bands_grid.addWidget(QLabel(band), r, 1)
            bands_grid.addWidget(QLabel(res), r, 2)
        self._wgt_bands.setStyleSheet(
            'QWidget{background:#fafafa;border:1px solid #ddd;border-radius:3px;}'
            'QLabel{border:none;font-size:10px;padding:1px 4px;}')
        self._wgt_bands.setVisible(False)
        root.addWidget(self._wgt_bands)

        # ── Índice ────────────────────────────────────────────────────────────
        grp_idx = QGroupBox('Índice de Vegetação / Vegetation Index')
        gl_i = QGridLayout()
        gl_i.setContentsMargins(8, 6, 8, 8)
        gl_i.setSpacing(6)
        gl_i.setColumnStretch(1, 1)

        gl_i.addWidget(QLabel('Índice / Index:'), 0, 0)
        self.combo_index = QComboBox()
        # _INDEX_DEFS vem de field_analysis — dicionário ordenado onde cada
        # chave é o nome do índice ('NDVI', 'EVI', 'Custom', etc.) e o valor
        # tem 'label' (texto exibido), 'formula', 'vars', 'vmin', 'vmax'.
        for key, defn in _INDEX_DEFS.items():
            self.combo_index.addItem(defn['label'], key)
        # Quando o usuário muda o índice, mostramos ou escondemos o campo de
        # fórmula personalizada (só relevante para a opção 'Custom').
        self.combo_index.currentIndexChanged.connect(self._on_index_changed)
        gl_i.addWidget(self.combo_index, 0, 1)

        self.lbl_formula = QLabel('Fórmula / Formula:')
        self.edit_formula = QLineEdit()
        self.edit_formula.setPlaceholderText('Ex: (nir - red) / (nir + red)')
        self.lbl_hint = QLabel(
            'Variáveis / Variables: nir, red, green, blue, swir1, swir2, '
            'rededge, rededge2, rededge3, nir2  ·  Use np. para funções numpy / for numpy functions')
        self.lbl_hint.setStyleSheet(
            'color:#555;font-size:9px;background:#f5f5f5;border-radius:3px;padding:3px;')
        self.lbl_hint.setWordWrap(True)
        gl_i.addWidget(self.lbl_formula, 1, 0)
        gl_i.addWidget(self.edit_formula, 1, 1)
        gl_i.addWidget(self.lbl_hint, 2, 0, 1, 2)

        grp_idx.setLayout(gl_i)
        root.addWidget(grp_idx)

        # ── Info note ─────────────────────────────────────────────────────────
        lbl_note = QLabel(
            'ℹ  Calcular Índice: lê apenas as bandas necessárias via vsicurl — sem download completo.\n'
            '   Compute Index: reads only needed bands via vsicurl — no full download.\n'
            '   Requer conexão com internet. / Requires internet connection.')
        lbl_note.setStyleSheet(
            'font-size:9px;color:#555;background:#fffde7;border:1px solid #f9a825;'
            'border-radius:3px;padding:5px;')
        lbl_note.setWordWrap(True)
        root.addWidget(lbl_note)

        # ── Salvar em arquivo / Save to file ──────────────────────────────────
        self._chk_save = QCheckBox('Salvar resultado em arquivo / Save result to file')
        self._chk_save.setChecked(False)
        self._chk_save.toggled.connect(self._on_save_toggled)
        root.addWidget(self._chk_save)

        self._save_row = QWidget()
        save_hl = QHBoxLayout(self._save_row)
        save_hl.setContentsMargins(20, 0, 0, 0)
        save_hl.setSpacing(6)
        self._btn_choose_folder = QPushButton('Escolher pasta / Choose folder')
        self._btn_choose_folder.setFixedHeight(26)
        self._btn_choose_folder.clicked.connect(self._on_choose_folder)
        self._lbl_save_path = QLabel('(temporário / temporary)')
        self._lbl_save_path.setStyleSheet('font-size:9px;color:#555;')
        self._lbl_save_path.setWordWrap(True)
        save_hl.addWidget(self._btn_choose_folder)
        save_hl.addWidget(self._lbl_save_path, 1)
        self._save_row.setVisible(False)
        root.addWidget(self._save_row)

        # ── Botões (fixos fora do scroll / fixed outside scroll) ──────────────
        # Os botões ficam no outer (fora do QScrollArea) para sempre estarem
        # visíveis, mesmo quando o usuário rola o formulário para cima ou baixo.
        outer.addWidget(self._sep())
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 6, 12, 12)
        btn_row.setSpacing(6)

        self.btn_compute = QPushButton('Calcular Índice / Compute Index')
        self.btn_compute.setMinimumHeight(38)
        self.btn_compute.setToolTip(
            'Calcula o índice para cada cena selecionada usando a área visível no mapa. / '
            'Computes the index for each selected scene using the visible map area.')
        self.btn_compute.setStyleSheet(
            'QPushButton{background:#2e7d32;color:white;font-weight:bold;'
            'font-size:12px;border-radius:5px;border:none;}'
            'QPushButton:hover{background:#1b5e20;}'
            'QPushButton:disabled{background:#4a7a4b;color:#aaa;}')
        self.btn_compute.clicked.connect(self._on_compute)
        btn_row.addWidget(self.btn_compute)

        btn_close = QPushButton('Fechar / Close')
        btn_close.setMinimumHeight(38)
        btn_close.setStyleSheet(
            'QPushButton{background:#616161;color:white;border:none;border-radius:5px;}'
            'QPushButton:hover{background:#424242;}')
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)

        outer.addLayout(btn_row)

        # Label de status do cálculo — fica sempre visível abaixo dos botões.
        # Começa vazio e é atualizado pelos slots do _ComputeThread.
        self._compute_status = QLabel('')
        self._compute_status.setAlignment(Qt.AlignCenter)
        self._compute_status.setWordWrap(True)
        self._compute_status.setStyleSheet(
            'font-size:10px;color:#444;padding:2px 12px 8px;')
        outer.addWidget(self._compute_status)

        # Chama _on_index_changed() na construção para esconder o campo de
        # fórmula personalizada se o índice padrão não for 'Custom'.
        self._on_index_changed()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _sep(self):
        # Cria uma linha horizontal visual separando seções da UI.
        # QFrame.HLine = horizontal line; QFrame.Sunken = estilo afundado (3D).
        ln = QFrame()
        ln.setFrameShape(QFrame.HLine)
        ln.setFrameShadow(QFrame.Sunken)
        return ln

    def _toggle_bands(self, checked):
        # QUANDO É CHAMADO: toggled signal do _btn_bands — sempre que o usuário
        # clica no botão expandir/recolher da seção de bandas.
        #
        # setVisible(False/True) é mais correto que hide()/show() em layouts —
        # o layout se reajusta automaticamente quando um widget muda de visibilidade.
        self._wgt_bands.setVisible(checked)
        self._btn_bands.setText(
            ('▼' if checked else '▶') + '  Bandas utilizadas / Bands used')

    def _on_save_toggled(self, checked):
        self._save_row.setVisible(checked)
        if not checked:
            self._save_folder = None
            self._lbl_save_path.setText('(temporário / temporary)')

    def _on_choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            'Escolher pasta de saída / Choose output folder',
            self._save_folder or '',
        )
        if folder:
            self._save_folder = folder
            self._lbl_save_path.setText(folder)

    def _on_index_changed(self):
        # QUANDO É CHAMADO: combo_index.currentIndexChanged — ao trocar o índice.
        #
        # Esconde os campos de fórmula personalizada para todos os índices
        # pré-definidos e só mostra quando o usuário escolhe 'Custom'.
        # Isso evita confusão: se o usuário selecionou NDVI, ele não precisa
        # ver (nem editar) a fórmula.
        is_custom = (self.combo_index.currentData() == 'Custom')
        self.lbl_formula.setVisible(is_custom)
        self.edit_formula.setVisible(is_custom)
        self.lbl_hint.setVisible(is_custom)

    def _get_selected_features(self):
        # Retorna a lista de features GeoJSON correspondentes aos itens
        # selecionados na lista. Cada QListWidgetItem carrega o dict da feature
        # no Qt.UserRole — um mecanismo do Qt para armazenar dados arbitrários
        # junto com o item visual, sem precisar de um dicionário separado.
        #
        # Qt.UserRole é um inteiro especial reservado para dados do aplicativo.
        # item.data(Qt.UserRole) é o getter; item.setData(Qt.UserRole, obj) é o setter.
        return [item.data(Qt.UserRole) for item in self.list_scenes.selectedItems()]

    # ── Thumbnail ─────────────────────────────────────────────────────────────

    def _on_scene_selected(self, current, _previous):
        # QUANDO É CHAMADO: currentItemChanged signal da list_scenes.
        # current = item agora destacado; _previous = item anterior (ignorado aqui).
        #
        # O thumbnail é carregado em background via _ThumbFetcher (QThread) para
        # não bloquear a UI enquanto o download acontece. Se o usuário trocar de
        # cena rapidamente, cancelamos o fetch anterior antes de iniciar um novo.
        if current is None:
            self._thumb_label.setPixmap(QPixmap())
            self._thumb_label.setText('Sem prévia\nNo preview')
            return
        feature = current.data(Qt.UserRole)
        if feature is None:
            return
        thumb_url = _find_thumbnail_url(feature)
        # _resolve() adiciona token SAS para URLs do Planetary Computer e normaliza
        # URLs das demais coleções (AWS, BDC). Sem isso, PC URLs retornam 403 Forbidden.
        thumb_url = _resolve(thumb_url)
        if not thumb_url:
            self._thumb_label.setPixmap(QPixmap())
            self._thumb_label.setText('Sem prévia\nNo preview')
            return
        self._thumb_label.setText('Carregando…\nLoading…')
        self._thumb_label.setPixmap(QPixmap())

        # Se já há um fetch em andamento, desconectamos seus sinais antes de
        # chamar quit() — sem desconectar, o slot poderia ser chamado uma última
        # vez com dados obsoletos após o novo fetch já ter iniciado.
        if self._thumb_fetcher and self._thumb_fetcher.isRunning():
            self._thumb_fetcher.loaded.disconnect()
            self._thumb_fetcher.failed.disconnect()
            self._thumb_fetcher.quit()
            # wait(1000): espera até 1 segundo pela thread parar.
            # Se não esperarmos, podemos destruir o objeto enquanto a thread ainda roda.
            self._thumb_fetcher.wait(1000)

        self._thumb_fetcher = _ThumbFetcher(thumb_url, self)
        self._thumb_fetcher.loaded.connect(self._on_thumb_loaded)
        self._thumb_fetcher.failed.connect(self._on_thumb_failed)
        self._thumb_fetcher.start()

    def _on_thumb_loaded(self, data: bytes):
        # QUANDO É CHAMADO: sinal 'loaded' do _ThumbFetcher, emitido quando o
        # download do thumbnail concluiu com sucesso.
        # data: bytes brutos da imagem (JPEG/PNG).
        #
        # QPixmap.loadFromData() decodifica os bytes em imagem Qt.
        # Se falhar (arquivo corrompido, formato desconhecido), retorna False.
        px = QPixmap()
        if px.loadFromData(data):
            # scaled() redimensiona mantendo proporção (Qt.KeepAspectRatio).
            # Qt.SmoothTransformation usa interpolação bicúbica — mais lento mas
            # resulta em imagem mais nítida ao redimensionar.
            # Descontamos 4px para não encostar nas bordas do QLabel.
            scaled = px.scaled(
                self._thumb_label.width() - 4,
                self._thumb_label.height() - 4,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self._thumb_label.setPixmap(scaled)
            self._thumb_label.setText('')
        else:
            self._thumb_label.setText('Sem prévia\nNo preview')

    def _on_thumb_failed(self):
        # QUANDO É CHAMADO: sinal 'failed' do _ThumbFetcher — erro de rede,
        # timeout, ou URL inválida.
        self._thumb_label.setPixmap(QPixmap())
        self._thumb_label.setText('Sem prévia\nNo preview')

    # ── Search ────────────────────────────────────────────────────────────────

    def _on_search(self):
        bbox     = get_bbox_from_canvas(self.iface)
        lon_span = abs(bbox[2] - bbox[0])
        if lon_span > 5.0:
            self.lbl_status.setText(
                '⚠ Área muito grande — zoom para a região de interesse antes de buscar. / '
                '⚠ Area too large — zoom to your region of interest before searching.')

        self._search_params = {
            'coll_id':   self.combo_coll.currentData(),
            'bbox':      bbox,
            'date_ini':  self.date_from.date().toString('yyyy-MM-dd'),
            'date_fim':  self.date_to.date().toString('yyyy-MM-dd'),
            'cloud_max': self.spin_cloud.value(),
        }
        self._do_search()

    def _do_search(self):
        if not self._search_params:
            return

        self.list_scenes.clear()
        self._features = []
        self.lbl_status.setText('Buscando cenas... / Searching scenes...')

        if self._search_thread and self._search_thread.isRunning():
            self._search_thread.quit()
            self._search_thread.wait(500)

        self._search_thread = _StacSearchThread(self._search_params, parent=self)
        self._search_thread.result.connect(self._on_search_result)
        self._search_thread.error.connect(self._on_search_error)
        self._search_thread.start()

    def _on_search_result(self, features, next_body, prev_body):
        self._features = features

        if not features:
            self.lbl_status.setText(
                'Nenhuma cena encontrada. Tente ampliar o período ou aumentar o limite de nuvens.\n'
                'No scenes found. Try expanding the date range or increasing the cloud limit.')
            return

        for feat in features:
            props     = feat.get('properties', {})
            cloud     = props.get('eo:cloud_cover')
            cloud_str = '{:.1f}%'.format(cloud) if cloud is not None else '?%'
            scene_id  = feat.get('id', 'unknown')
            s_date, mgrs, _suffix = _parse_s2_id(scene_id)
            if not s_date:
                s_date = (props.get('datetime') or '')[:10]
            label = '{}   ☁ {}   {}'.format(s_date, cloud_str, mgrs or scene_id[:20])
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, feat)
            self.list_scenes.addItem(item)

        self.list_scenes.setCurrentRow(0)
        self.lbl_status.setText(
            '{} cena(s) encontrada(s) — Ctrl+click p/ múltiplas / '
            '{} scene(s) found — Ctrl+click for multiple'.format(
                len(features), len(features)))

    def _on_search_error(self, msg):
        self.lbl_status.setText('Erro / Error: {}'.format(msg[:120]))
        QMessageBox.critical(self, 'RTH',
            'Erro ao buscar cenas / Error searching scenes:\n\n{}'.format(msg))

    # ── Calcular Índice ───────────────────────────────────────────────────────

    def _on_compute(self):
        # QUANDO É CHAMADO: btn_compute.clicked.
        #
        # Monta a lista de tarefas e lança _ComputeThread — retorna imediatamente.
        # Todo o processamento (vsicurl + GDAL Warp + numpy) corre na thread de fundo;
        # os slots _on_cthread_* recebem os resultados via pyqtSignal e atualizam a UI.
        if not _DEPS_OK:
            QMessageBox.critical(self, 'RTH',
                'numpy e/ou gdal não disponíveis.\nnumpy and/or gdal not available.\n\n' + _DEPS_MSG)
            return

        features = self._get_selected_features()
        if not features:
            QMessageBox.warning(self, 'RTH',
                'Selecione ao menos uma cena na lista. / Select at least one scene from the list.')
            return

        index_key = self.combo_index.currentData()
        defn      = _INDEX_DEFS[index_key]

        if index_key == 'Custom':
            formula = self.edit_formula.text().strip()
            if not formula:
                QMessageBox.warning(self, 'RTH',
                    'Digite uma fórmula personalizada. / Enter a custom formula.')
                return
            needed = [v for v in _BAND_VARS if re.search(r'\b' + v + r'\b', formula)]
            if not needed:
                QMessageBox.warning(self, 'RTH',
                    'Nenhuma variável de banda reconhecida na fórmula.\n'
                    'No recognized band variable in formula.\n'
                    'Use: {}'.format(', '.join(_BAND_VARS.keys())))
                return
        else:
            formula = defn['formula']
            needed  = defn['vars']

        # bbox_canvas: fallback caso a feature não tenha bbox próprio no metadado STAC.
        bbox_canvas = get_bbox_from_canvas(self.iface)

        tasks = []
        for i, feature in enumerate(features):
            scene_id          = feature.get('id', 'scene_{}'.format(i))
            s_date, mgrs, sfx = _parse_s2_id(scene_id)
            if not sfx:
                sfx = (feature.get('properties', {}).get('datetime') or '')[:10].replace('-', '')
            fname = 'rth_qi_{}_{}_{}.tif'.format(
                index_key, re.sub(r'[^\w]', '_', sfx[:20]), i)
            if self._chk_save.isChecked() and self._save_folder:
                out_path = os.path.join(self._save_folder, fname)
            else:
                out_path = os.path.join(tempfile.gettempdir(), fname)
            # Nome da camada: "{indice} — {data} — {tile_mgrs}", ex: "NDVI — 20240315 — 22KEB"
            layer_name = '{} — {} — {}'.format(
                index_key, s_date or sfx[:12], mgrs or scene_id[:16])

            # Usa o bbox do próprio tile Sentinel-2 (metadado STAC) em vez do canvas.
            # feature['bbox'] = [min_lon, min_lat, max_lon, max_lat] — extent real do tile.
            # Isso garante que o índice cobre a cena inteira, não só a área visível no mapa.
            raw_bbox   = feature.get('bbox')
            scene_bbox = raw_bbox if (raw_bbox and len(raw_bbox) == 4) else bbox_canvas
            x_res, y_res = self._safe_res(scene_bbox)

            tasks.append({
                'feature':  feature,
                'bbox':     scene_bbox,
                'x_res':    x_res,
                'y_res':    y_res,
                'needed':   needed,
                'formula':  formula,
                'out_path': out_path,
                'name':     layer_name,
                'label':    '{} · {}'.format(s_date or sfx[:12], mgrs or scene_id[:16]),
            })

        self._compute_errors = []

        # QProgressDialog não-modal: o usuário ainda pode interagir com o QGIS
        # enquanto o cálculo corre em background — pan/zoom são possíveis.
        # Qt.NonModal difere de Qt.WindowModal (que bloqueia a janela pai).
        self._progress_dlg = QProgressDialog(
            'Calculando {}... / Computing {}...'.format(index_key, index_key),
            'Cancelar / Cancel', 0, len(tasks), self)
        self._progress_dlg.setWindowTitle('RTH — Índices de Vegetação em Imagem / Vegetation Indices in Image')
        self._progress_dlg.setWindowModality(Qt.NonModal)
        self._progress_dlg.setMinimumDuration(0)
        self._progress_dlg.setValue(0)
        # canceled signal: emitido quando o usuário clica em "Cancelar".
        self._progress_dlg.canceled.connect(self._on_cthread_cancel)

        self._compute_thread = _ComputeThread(tasks, self)
        self._compute_thread.progress_sig.connect(self._on_cthread_progress)
        self._compute_thread.scene_done.connect(self._on_cthread_done)
        self._compute_thread.scene_error.connect(self._on_cthread_error)
        self._compute_thread.all_done.connect(self._on_cthread_all_done)

        self.btn_compute.setEnabled(False)
        self._compute_status.setText('⏳ Calculando {}… / Computing {}…'.format(index_key, index_key))
        self._compute_thread.start()
        # Retorna imediatamente — o cálculo continua em background na thread.

    # ── Slots do compute thread ────────────────────────────────────────────────

    def _on_cthread_cancel(self):
        # QUANDO É CHAMADO: sinal canceled do QProgressDialog (botão "Cancelar").
        # Sinaliza para a thread parar no próximo ponto de checagem (início de cada cena).
        if self._compute_thread and self._compute_thread.isRunning():
            self._compute_thread.cancel()

    def _on_cthread_progress(self, current, total, label):
        # QUANDO É CHAMADO: sinal progress_sig da _ComputeThread, emitido no início
        # de cada cena. Atualiza o texto e a barra de progresso na thread principal.
        # Sinais Qt cruzam threads de forma segura — é por isso que usamos pyqtSignal.
        if self._progress_dlg:
            self._progress_dlg.setLabelText(
                'Calculando {}/{} / Computing {}/{}\n{}'.format(
                    current, total, current, total, label))
            self._progress_dlg.setValue(current)
        pct = int(current / total * 100)
        self._compute_status.setText(
            '⏳ {}% — Cena {}/{} / Scene {}/{} — {}'.format(pct, current, total, current, total, label))

    def _on_cthread_done(self, out_path, layer_name):
        # QUANDO É CHAMADO: sinal scene_done da _ComputeThread — uma cena foi calculada
        # e o TIFF salvo em out_path. Aqui carregamos a camada no projeto QGIS.
        # ATENÇÃO: este slot roda na thread principal — safe para chamar API do QGIS.
        rlayer = QgsRasterLayer(out_path, layer_name)
        if rlayer.isValid():
            QgsProject.instance().addMapLayer(rlayer)
            collapse_layer(rlayer)
        else:
            self._compute_errors.append(
                'Falha ao carregar camada / Failed to load layer: {}'.format(out_path))

    def _on_cthread_error(self, msg):
        # QUANDO É CHAMADO: sinal scene_error da _ComputeThread — a cena falhou.
        # Acumula o erro para exibir no final (o cálculo das demais cenas continua).
        self._compute_errors.append(msg)

    def _on_cthread_all_done(self, n_ok):
        # QUANDO É CHAMADO: sinal all_done da _ComputeThread — todas as cenas foram
        # processadas (ou canceladas). Faz a limpeza final e exibe relatório.
        if self._progress_dlg:
            self._progress_dlg.close()
            self._progress_dlg = None
        self.btn_compute.setEnabled(True)

        if n_ok:
            self._compute_status.setText(
                '✓ {} camada(s) gerada(s) / {} layer(s) generated'.format(n_ok, n_ok))
            self.iface.messageBar().pushMessage(
                'RTH Índices',
                '{} camada(s) gerada(s) / {} layer(s) generated'.format(n_ok, n_ok),
                level=Qgis.MessageLevel.Success, duration=6)
        else:
            self._compute_status.setText('')

        if self._compute_errors:
            QMessageBox.critical(self, 'RTH — Índices Rápidos / Quick Indices',
                'Erro(s) / Error(s):\n\n' + '\n'.join(self._compute_errors[:5]))

        self._compute_thread = None
        self._compute_errors = []

    @staticmethod
    def _safe_res(bbox_wgs84, max_px=4096, min_res=10.0):
        """Calcula xRes/yRes em metros para o bbox dado, limitando a max_px pixels por lado.
        Compute xRes/yRes in metres for the given bbox, capping at max_px pixels per side.

        Sem isso, GDAL tenta criar o raster na resolução nativa de 10 m do COG para
        toda a extensão do canvas — o que pode exigir centenas de GB de RAM.
        Without this, GDAL tries to allocate the full canvas at 10 m native COG
        resolution, requiring hundreds of GB of RAM for large canvas views.
        """
        import math
        lat_avg = (bbox_wgs84[1] + bbox_wgs84[3]) / 2.0
        width_m  = abs(bbox_wgs84[2] - bbox_wgs84[0]) * 111_319 * math.cos(math.radians(lat_avg))
        height_m = abs(bbox_wgs84[3] - bbox_wgs84[1]) * 110_574
        # Calcula resolução necessária para caber em max_px pixels por lado.
        # max(min_res, ...) garante que nunca superamos a resolução nativa (10 m).
        x_res = max(min_res, width_m  / max_px)
        y_res = max(min_res, height_m / max_px)
        return x_res, y_res

    def _compute_one(self, feature, index_key, formula, bbox_wgs84, output_path):
        """Calcula um índice para uma cena — sem cutline (cena inteira limitada ao bbox do canvas).
        Compute one index for one scene — no cutline (full scene clipped to canvas bbox).
        """
        # _init_gdal() importa o módulo gdal de forma segura e retorna None se não disponível.
        # Fazemos essa verificação aqui (além da que já está em _on_compute) porque
        # _compute_one pode ser chamada de outros pontos no futuro.
        gdal = _init_gdal()
        if gdal is None:
            raise RuntimeError('GDAL não disponível / GDAL not available')

        # _scene_utm() lê os metadados da feature STAC e retorna o CRS UTM da cena
        # (ex: EPSG:32722 para UTM 22S). Usamos isso para garantir que todas as bandas
        # sejam reprojetadas para o mesmo CRS antes do cálculo — bandas de CRS diferentes
        # produziriam shapes incompatíveis.
        target_crs = _scene_utm(feature)

        # Calcula a resolução de saída segura para este bbox.
        # Sem isso, GDAL leria a resolução nativa do COG (10 m) e tentaria criar um
        # raster enorme para qualquer canvas com mais de alguns quilômetros de extensão.
        x_res, y_res = self._safe_res(bbox_wgs84)

        if index_key == 'Custom':
            # Para fórmulas personalizadas, detectamos quais variáveis de banda foram
            # usadas com regex de word boundary (\b) para não confundir 'nir2' com 'nir'.
            needed = [v for v in _BAND_VARS if re.search(r'\b' + v + r'\b', formula)]
            if not needed:
                raise ValueError(
                    'Nenhuma variável de banda reconhecida na fórmula.\n'
                    'No recognized band variable in formula.\n'
                    'Use: {}'.format(', '.join(_BAND_VARS.keys())))
        else:
            # Para índices pré-definidos, a lista de variáveis necessárias já está
            # em _INDEX_DEFS[index_key]['vars'].
            needed = _INDEX_DEFS[index_key]['vars']

        # datasets: dicionário de {var_name: gdal.Dataset}.
        # Cada Dataset aponta para a banda recortada via vsicurl (não é um arquivo local).
        # ref_gt, ref_proj, ref_shape: geotransform, projeção e shape da primeira banda —
        # usados como referência para alinhar todas as demais bandas.
        datasets  = {}
        ref_gt    = None
        ref_proj  = None
        ref_shape = None

        try:
            for var in needed:
                # processEvents() aqui permite que o botão Cancelar do QProgressDialog
                # seja processado durante o download de cada banda.
                QApplication.processEvents()

                # _clip_band() faz a mágica principal:
                #   1) Encontra a URL COG da banda na feature STAC (ex: B04.tif na AWS S3)
                #   2) Abre o arquivo via /vsicurl/ — GDAL lê só o pedaço necessário
                #   3) Recorta para bbox_wgs84 (área visível no canvas)
                #   4) Reprojeta para target_crs (UTM da cena)
                #   5) Retorna um gdal.Dataset em memória (/vsimem/)
                #
                # cutline_path=None — diferença fundamental desta ferramenta vs field_analysis:
                #   Em field_analysis, um polígono (talhão) é usado como máscara de recorte.
                #   Aqui não temos polígono — recortamos só pelo bbox do canvas.
                #
                # xRes/yRes calculados por _safe_res() evitam alocação de RAM absurda:
                #   sem eles, GDAL usa a resolução nativa do COG (10 m) para TODA a
                #   extensão do canvas, gerando rasters de centenas de GB.
                ds = _clip_band(feature, _BAND_VARS[var], bbox_wgs84, gdal,
                                target_crs, None,  # cutline_path=None — sem polígono / no polygon mask
                                xRes=x_res, yRes=y_res)
                if ds is None:
                    raise ValueError(
                        'Banda {} ({}) não encontrada na cena. / Band {} ({}) not found in scene.'.format(
                            _BAND_VARS[var], var, _BAND_VARS[var], var))

                # A primeira banda baixada define o shape de referência.
                # As demais são redimensionadas para esse shape por _match_shape().
                # Isso é necessário porque as bandas S-2 de 20m têm metade da
                # resolução das bandas de 10m, gerando shapes diferentes.
                if ref_gt is None:
                    ref_gt    = ds.GetGeoTransform()
                    ref_proj  = ds.GetProjection()
                    ref_shape = (ds.RasterYSize, ds.RasterXSize)
                datasets[var] = ds

            # _ds_to_array: converte gdal.Dataset → numpy array 2D (float32).
            # _match_shape: redimensiona o array para (ref_shape) via scipy.zoom ou similar.
            arrays = {var: _match_shape(_ds_to_array(ds), ref_shape)
                      for var, ds in datasets.items()}

            # _eval_formula: avalia a expressão usando numpy.
            # Exemplo: formula='(nir - red) / (nir + red)' com arrays={'nir': ..., 'red': ...}
            # Retorna um numpy array com os valores do índice.
            result = _eval_formula(formula, arrays)

            # _write_tiff: salva o array numpy como GeoTIFF com georreferenciamento.
            # ref_gt e ref_proj definem a posição e projeção do arquivo de saída.
            _write_tiff(result, ref_gt, ref_proj, output_path)

        finally:
            # Libera explicitamente os Datasets GDAL do dicionário.
            # Em Python, o garbage collector normalmente faria isso,
            # mas GDAL mantém handles de arquivo e locks que podem causar
            # problemas em Windows se não forem liberados manualmente.
            for ds in datasets.values():
                del ds

        return output_path

    def closeEvent(self, event):
        # QUANDO É CHAMADO: o QGIS chama closeEvent() quando o usuário fecha
        # o diálogo (botão X, ESC, ou btn_close.clicked.connect(self.close)).
        #
        # CRÍTICO: cancelar AMBAS as threads antes de destruir o diálogo.
        # Se não cancelarmos, threads podem tentar atualizar widgets que
        # não existem mais — resultando em crash.
        if self._thumb_fetcher and self._thumb_fetcher.isRunning():
            self._thumb_fetcher.quit()
            self._thumb_fetcher.wait(2000)
        if self._compute_thread and self._compute_thread.isRunning():
            self._compute_thread.cancel()
            # wait(5000): até 5 s para a thread terminar a cena atual.
            # Se a rede estiver lenta, a thread pode demorar — esse timeout
            # evita travar o QGIS indefinidamente na hora de fechar.
            self._compute_thread.wait(5000)
        super().closeEvent(event)


# ── Tool class ────────────────────────────────────────────────────────────────

class QuickIndicesTool:
    # Esta classe é o "ponto de entrada" da ferramenta no ciclo de vida do plugin.
    # É um wrapper leve que:
    #   1) É instanciado uma vez em RTH PROJECT.py __init__()
    #   2) Tem um método run() conectado ao QAction do menu
    #   3) Cria o diálogo sob demanda e reutiliza a mesma instância
    #
    # Por que não fazer o QDialog diretamente no __init__ do plugin?
    #   Criar o diálogo no __init__ do plugin consumiria memória mesmo quando
    #   a ferramenta nunca for usada. Criamos sob demanda (lazy) no run().
    #
    # Por que guardar a instância em self._dialog?
    #   Para reutilizar o diálogo já aberto (show/raise) em vez de criar um novo
    #   toda vez que o usuário clicar no menu. Isso preserva o estado dos campos.

    def __init__(self, iface):
        self.iface   = iface
        # _dialog começa None e é criado na primeira chamada de run().
        self._dialog = None

    def run(self):
        # QUANDO É CHAMADO: QAction.triggered — o usuário clicou no item do menu.
        #
        # Se o diálogo não existir ou tiver sido fechado (isVisible() == False),
        # criamos uma nova instância. Caso contrário, apenas trazemos para frente.
        if self._dialog is None or not self._dialog.isVisible():
            # iface.mainWindow() como parent garante que o Qt não trata este
            # diálogo como janela principal do processo — fechar ele não fecha o QGIS.
            self._dialog = QuickIndicesDialog(self.iface, parent=self.iface.mainWindow())
        # show(): torna o diálogo visível (se estava oculto).
        # raise_(): traz para frente de outras janelas.
        # activateWindow(): garante que receba foco do teclado.
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
