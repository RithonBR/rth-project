# -*- coding: utf-8 -*-
# ============================================================
# FERRAMENTA: Pontos Aleatórios em Camada / Random Points in Layer
#
# O que faz (ponto de vista do usuário):
#   O usuário escolhe uma camada de polígonos, define quantos
#   pontos quer gerar e um buffer mínimo de distância entre eles.
#   O plugin coloca N pontos aleatórios dentro dos polígonos
#   e cria uma nova camada de memória com esses pontos.
#
# Algoritmo (polygon-first):
#   Em vez de amostrar do bounding box de TODA a camada
#   (que falha para polígonos pequenos em áreas grandes),
#   o algoritmo:
#     1. Sorteia um polígono aleatório da lista
#     2. Sorteia um ponto aleatório dentro do bbox DESSE polígono
#     3. Verifica se o ponto está geometricamente dentro do polígono
#     4. Verifica o buffer mínimo contra os pontos já aceitos
#     5. Aceita ou rejeita; repete até atingir N pontos
#   Isso garante que polígonos pequenos sejam tão acessíveis
#   quanto polígonos grandes — cada candidato sai do seu próprio bbox.
#
# Por que usar QThread:
#   A geração pode levar segundos para N grande ou buffers apertados.
#   Rodar na thread principal do QGIS travaria a interface — o usuário
#   não conseguiria mover o mapa, fechar janelas, nem cancelar.
#   Com QThread, a geração ocorre em paralelo e o usuário pode cancelar.
#
# Ciclo de vida no plugin:
#   Instanciada em RTH PROJECT.py no __init__() do plugin.
#   Ativada via menu Sensoriamento Remoto > Pontos Aleatórios em Camada.
# ============================================================

import random

from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QDoubleSpinBox,
    QFrame,
)
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsFeature, QgsGeometry, QgsPointXY,
    QgsMarkerSymbol,
)


# ──────────────────────────────────────────────────────────────────────────────
# Thread de geração — algoritmo polygon-first
# ──────────────────────────────────────────────────────────────────────────────

class _PointGenThread(QThread):
    # QThread é a classe base do Qt para execução em thread separada.
    # Sobrescrevemos o método run() — o Qt chama run() automaticamente
    # quando chamamos start(). Tudo dentro de run() executa fora da
    # thread principal (GUI thread), sem travar a interface.
    #
    # pyqtSignal permite que a thread comunique resultados de volta
    # para a thread principal de forma segura. NUNCA atualize widgets
    # Qt diretamente de dentro de run() — isso causa crash ou condição
    # de corrida. Sempre emita um sinal e deixe o Qt entregar o valor
    # para a thread principal via fila interna.

    # Emitido a cada ponto aceito: (quantidade_colocada, total_pedido)
    progress = pyqtSignal(int, int)
    # Emitido ao final: ([lista de QgsPointXY em CRS da fonte], mensagem_aviso)
    # A lista vazia + aviso indica erro; lista não-vazia = sucesso.
    finished = pyqtSignal(list, str)

    def __init__(self, layer, n_requested, min_spacing_km, parent=None):
        super().__init__(parent)
        self._layer          = layer
        self._n_requested    = n_requested
        self._min_spacing_km = min_spacing_km
        # Flag de cancelamento: a thread verifica periodicamente.
        # bool é thread-safe em CPython para leitura/escrita simples.
        self._cancel         = False

    def cancel(self):
        # Chamado pela thread principal quando o usuário clica em Cancelar.
        # Não matamos a thread à força (perigoso) — apenas sinalizamos
        # para que run() encerre no próximo ciclo do while.
        self._cancel = True

    def run(self):
        # Este método é executado em uma thread separada pelo Qt.
        # NÃO chamar métodos de UI aqui — use self.progress.emit() e
        # self.finished.emit() para comunicar com a thread principal.
        try:
            crs = self._layer.crs()

            # Convertemos o espaçamento de km para unidades do CRS da camada,
            # SEM reprojetar a camada. Reprojetar poderia distorcer geometrias
            # e tornaria o código mais frágil.
            #
            # CRS geográfico (graus, ex: EPSG:4326):
            #   1 grau de latitude ≈ 111 km no equador.
            #   Usamos essa aproximação — suficiente para buffer de campo.
            # CRS projetado (metros, ex: UTM EPSG:31982):
            #   1 km = 1000 m — conversão exata.
            if crs.isGeographic():
                min_dist = self._min_spacing_km / 111.0
            else:
                min_dist = self._min_spacing_km * 1000.0

            # ── Coleta geometrias válidas da camada ───────────────────────────
            # Fazemos uma cópia (QgsGeometry(g)) para que a thread tenha
            # acesso às geometrias sem depender do estado da camada no QGIS.
            # Se o usuário editar a camada durante a geração, nossa cópia
            # fica intacta.
            geoms = []
            for f in self._layer.getFeatures():
                if self._cancel:
                    self.finished.emit([], 'cancelado')
                    return
                g = f.geometry()
                if g and not g.isNull() and not g.isEmpty():
                    geoms.append(QgsGeometry(g))

            if not geoms:
                self.finished.emit(
                    [], 'Sem geometrias válidas. / No valid geometries.')
                return

            n_polys = len(geoms)
            placed  = []    # lista de (x, y) em unidades do CRS da fonte
            # Distância ao quadrado: comparar d² é mais rápido que comparar
            # d (evita a raiz quadrada em cada verificação de buffer).
            # Para N pontos já colocados, isso é N multiplicações vs N raízes.
            min_sq  = min_dist * min_dist

            # max_fails: limite de falhas CONSECUTIVAS antes de abortar.
            # Se o buffer estiver muito grande para a área disponível,
            # o algoritmo nunca encontraria um ponto válido — entraria em
            # loop infinito. Esse limite força a saída com os pontos que
            # conseguiu colocar até ali.
            # "50× os pontos pedidos" é conservador: se pediu 100 pontos,
            # tenta pelo menos 5000 antes de desistir.
            max_fails = max(self._n_requested * 50, 2000)
            fails     = 0

            while len(placed) < self._n_requested and not self._cancel:
                if fails >= max_fails:
                    break

                # Escolhe um polígono aleatório da lista.
                # Por que não iterar polígono por polígono?
                # Porque queremos distribuição proporcional: se houver 3
                # polígonos grandes e 1 pequeno, sortear aleatoriamente
                # garante que todos recebam pontos, não apenas o primeiro.
                # (Limitação: polígonos de tamanhos muito diferentes terão
                # densidades diferentes — mas é o comportamento esperado.)
                poly_idx = random.randint(0, n_polys - 1)
                g        = geoms[poly_idx]

                pt = self._random_point_in_geom(g)
                if pt is None:
                    fails += 1
                    continue

                x, y = pt

                # Verificação de buffer — pulamos se min_dist == 0 (sem buffer)
                # para não fazer nenhuma iteração desnecessária.
                if min_dist > 0:
                    too_close = any(
                        (x - px) ** 2 + (y - py) ** 2 < min_sq
                        for (px, py) in placed
                    )
                    if too_close:
                        fails += 1
                        continue

                # Ponto aceito — reseta o contador de falhas consecutivas.
                # Reseta (não incrementa) porque queremos detectar falhas
                # CONSECUTIVAS — um ponto aceito indica que a área ainda
                # tem espaço disponível.
                placed.append((x, y))
                fails = 0
                self.progress.emit(len(placed), self._n_requested)

            self.finished.emit(
                [QgsPointXY(x, y) for (x, y) in placed], '')

        except Exception as e:
            self.finished.emit([], str(e))

    def _random_point_in_geom(self, geom, max_tries=300):
        """Retorna (x, y) aleatório estritamente dentro de geom, ou None.

        Estratégia:
          1. Tenta max_tries candidatos aleatórios no bbox do polígono.
          2. Se nenhum caiu dentro, usa o centroide como fallback.
          3. Se o centroide também estiver fora (polígonos côncavos), retorna None.

        Por que max_tries=300?
          Para polígonos convexos (retângulos, elipses), a eficiência
          de acerto dentro do bbox é alta (>50%). Para polígonos em L
          ou estreitos, pode ser baixa (<20%). 300 tentativas equilibra
          velocidade e cobertura para a maioria dos casos de uso agrícola.
        """
        bb    = geom.boundingBox()
        min_x = bb.xMinimum()
        min_y = bb.yMinimum()
        max_x = bb.xMaximum()
        max_y = bb.yMaximum()

        if max_x <= min_x or max_y <= min_y:
            # Geometria degenerada (ponto ou linha disfarçado de polígono).
            # Tentamos o centroide que pode ainda ser válido.
            c = geom.centroid()
            if c and not c.isNull():
                cp = c.asPoint()
                pt = QgsGeometry.fromPointXY(QgsPointXY(cp.x(), cp.y()))
                if geom.contains(pt):
                    return cp.x(), cp.y()
            return None

        for _ in range(max_tries):
            x = random.uniform(min_x, max_x)
            y = random.uniform(min_y, max_y)
            # geom.contains() faz a verificação de contenção ponto-em-polígono
            # diretamente no CRS nativo da camada — sem reprojeção.
            # Precisamos criar um QgsGeometry de ponto para a comparação
            # porque contains() espera geometria, não coordenadas nuas.
            if geom.contains(QgsGeometry.fromPointXY(QgsPointXY(x, y))):
                return x, y

        # Esgotou as tentativas aleatórias (polígono estreito, L-shape, etc.).
        # Centroide é o melhor fallback — para polígonos simples convexos,
        # o centroide está sempre dentro. Para polígonos côncavos, pode
        # estar fora — nesse caso o contains() abaixo rejeita corretamente.
        c = geom.centroid()
        if c and not c.isNull():
            cp = c.asPoint()
            pt = QgsGeometry.fromPointXY(QgsPointXY(cp.x(), cp.y()))
            if geom.contains(pt):
                return cp.x(), cp.y()

        return None


# ──────────────────────────────────────────────────────────────────────────────
# Diálogo de configuração
# ──────────────────────────────────────────────────────────────────────────────

class RandomPointsDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface              = iface
        # Referência à thread de geração — guardamos para poder cancelar
        # se o usuário fechar o diálogo enquanto a thread ainda roda.
        self._gen_thread        = None
        self._n_requested       = 0
        # Guardamos ID e nome da camada para uso em _on_gen_done(),
        # onde não temos mais acesso ao combo (pode ter sido alterado).
        self._active_layer_id   = None
        self._active_layer_name = ''
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle('RTH Pontos Aleatórios / Random Points')
        # Qt.Window cria uma janela independente (não fica preso ao pai).
        # WindowMinimizeButtonHint adiciona o botão de minimizar.
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint |
            Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint
        )
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        lbl = QLabel('Pontos Aleatórios em Camada / Random Points in Layer')
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet('font-size:13px; font-weight:bold;')
        root.addWidget(lbl)

        self._sep(root)

        # QFormLayout alinha labels à direita e widgets à esquerda,
        # criando o visual clássico de formulário (label: [campo]).
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

        # QComboBox preenchido em showEvent() com as camadas polígono
        # do projeto atual. Não preenchemos no __init__ porque o diálogo
        # pode ser criado antes de qualquer camada existir no projeto.
        self._combo_layer = QComboBox()
        self._combo_layer.setMinimumHeight(28)
        form.addRow('Camada / Layer:', self._combo_layer)

        # QSpinBox: inteiros. range(1, 100_000) cobre casos realistas.
        # Valor padrão 50 é suficiente para testes rápidos no campo.
        self._spin_n = QSpinBox()
        self._spin_n.setMinimum(1)
        self._spin_n.setMaximum(100_000)
        self._spin_n.setValue(50)
        self._spin_n.setMinimumHeight(28)
        form.addRow('Quantidade / Count:', self._spin_n)

        # QDoubleSpinBox: decimais. Buffer em km com 3 casas decimais
        # para permitir buffers precisos (ex: 0.050 km = 50 m).
        # 0.0 = sem buffer — gera pontos sem verificar espaçamento.
        self._spin_radius = QDoubleSpinBox()
        self._spin_radius.setMinimum(0.0)
        self._spin_radius.setMaximum(500.0)
        self._spin_radius.setValue(1.0)
        self._spin_radius.setDecimals(3)
        self._spin_radius.setSuffix('  km')
        self._spin_radius.setMinimumHeight(28)
        form.addRow('Buffer mínimo / Min. buffer:', self._spin_radius)

        root.addLayout(form)

        # Label informativo — explica o algoritmo ao usuário em linguagem simples
        lbl_info = QLabel(
            u'Sorteia um polígono aleatório, coloca 1 ponto dentro, verifica buffer, '
            u'repete até N pontos. Buffer = 0: sem restrição de espaçamento. / '
            u'Picks a random polygon, places 1 point inside, checks buffer, '
            u'repeats until N points. Buffer = 0: no spacing restriction.')
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet(
            'font-size:9px; color:#555; padding:4px; '
            'background:#f0f4ff; border-radius:4px;')
        root.addWidget(lbl_info)

        self._sep(root)

        btn_row = QHBoxLayout()

        self._btn_run = QPushButton('▶  Gerar Pontos / Generate Points')
        self._btn_run.setMinimumHeight(42)
        self._btn_run.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;'
            'font-size:13px;border-radius:6px;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        self._btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self._btn_run, 3)

        # Botão Cancelar começa desabilitado — só faz sentido durante a geração
        self._btn_cancel = QPushButton('✕  Cancelar / Cancel')
        self._btn_cancel.setMinimumHeight(42)
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.setStyleSheet(
            'QPushButton{background:#e53935;color:white;font-weight:bold;'
            'font-size:11px;border-radius:6px;}'
            'QPushButton:hover{background:#b71c1c;}'
            'QPushButton:disabled{background:#ccc; color:#888;}'
        )
        self._btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._btn_cancel, 1)
        root.addLayout(btn_row)

        self._lbl_status = QLabel('')
        self._lbl_status.setAlignment(Qt.AlignCenter)
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setStyleSheet('font-size:10px; color:#444;')
        root.addWidget(self._lbl_status)

    def _sep(self, layout):
        # Helper para linha separadora horizontal — visualmente organiza o form
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

    def showEvent(self, event):
        # QUANDO É CHAMADO: o Qt chama showEvent() toda vez que o diálogo
        # se torna visível (tanto na primeira abertura quanto ao reabrir).
        # Usamos isso para atualizar o combo de camadas com o estado atual
        # do projeto — se o usuário criou ou removeu camadas desde a última
        # vez que abriu o diálogo, a lista ficará atualizada.
        super().showEvent(event)
        self._populate_layers()

    def _populate_layers(self):
        # Limpa e repopula o combo com camadas polígono do projeto atual.
        # Usamos layer.id() como dados internos do item (não o nome)
        # porque o nome pode mudar; o ID é estável durante a sessão.
        self._combo_layer.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            # QgsWkbTypes.geometryType() retorna 0=Point, 1=Line, 2=Polygon.
            # Filtramos apenas polígonos — pontos aleatórios dentro de linhas
            # ou pontos não fazem sentido geometricamente.
            if QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PolygonGeometry:
                self._combo_layer.addItem(layer.name(), layer.id())

    # ── Iniciar geração ───────────────────────────────────────────────────────

    def _on_run(self):
        # Se uma geração anterior ainda estiver rodando (improvável mas possível),
        # cancelamos antes de começar uma nova.
        if self._gen_thread and self._gen_thread.isRunning():
            self._gen_thread.cancel()
            self._gen_thread.wait(2000)

        layer_id = self._combo_layer.currentData()
        if not layer_id:
            self._status(
                'Nenhuma camada polígono encontrada. / No polygon layer found.',
                error=True)
            return

        # mapLayer() retorna a camada pelo ID. Pode retornar None se a camada
        # foi removida depois de o combo ser populado.
        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer or not isinstance(layer, QgsVectorLayer):
            self._status('Camada inválida. / Invalid layer.', error=True)
            return

        self._n_requested       = self._spin_n.value()
        self._active_layer_id   = layer_id
        self._active_layer_name = layer.name()
        min_spacing_km          = self._spin_radius.value()

        # Desabilitamos Gerar e habilitamos Cancelar durante a geração
        self._btn_run.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._status('Iniciando... / Starting...')

        # Criamos a thread e conectamos os sinais ANTES de chamar start().
        # Se conectarmos depois, podemos perder sinais emitidos logo no início.
        self._gen_thread = _PointGenThread(
            layer, self._n_requested, min_spacing_km, parent=self)
        self._gen_thread.progress.connect(self._on_gen_progress)
        self._gen_thread.finished.connect(self._on_gen_done)
        # start() inicializa a thread e chama run() em paralelo.
        # O método run() não bloqueia — retorna imediatamente.
        self._gen_thread.start()

    def _on_cancel(self):
        if self._gen_thread and self._gen_thread.isRunning():
            # Apenas sinaliza — a thread terminará no próximo ciclo do while.
            # Não chamamos wait() aqui para não travar a UI enquanto a thread
            # conclui a iteração atual (pode levar alguns ms).
            self._gen_thread.cancel()
        self._btn_cancel.setEnabled(False)
        self._status('Cancelando... / Cancelling...')

    # ── Callbacks dos sinais da thread ────────────────────────────────────────

    def _on_gen_progress(self, n_placed, n_total):
        # QUANDO É CHAMADO: cada vez que a thread emite progress.emit().
        # Atualiza o label de status — o Qt entrega o sinal na thread
        # principal (GUI), então é seguro atualizar o widget aqui.
        self._status(
            'Gerando: {}/{} pontos / Generating: {}/{} points'.format(
                n_placed, n_total, n_placed, n_total))

    def _on_gen_done(self, points_src, warn):
        # QUANDO É CHAMADO: quando a thread emite finished.emit() — seja por
        # conclusão normal, cancelamento ou erro.
        # Reabilitamos os botões independentemente do resultado.
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)

        if warn == 'cancelado':
            self._status('Geração cancelada. / Generation cancelled.')
            return

        if warn and not points_src:
            self._status(warn, error=True)
            return

        if not points_src:
            self._status(
                'Nenhum ponto gerado. Verifique se a camada tem geometrias '
                'válidas ou reduza o buffer. / '
                'No points generated. Check that the layer has valid geometries '
                'or reduce the buffer.',
                error=True)
            return

        # Os pontos já estão no CRS da camada fonte — NÃO precisamos reprojetar.
        # A thread trabalhou no CRS nativo para evitar distorções.
        layer   = QgsProject.instance().mapLayer(self._active_layer_id)
        src_crs = layer.crs() if layer else None
        crs_str = src_crs.authid() if src_crs else 'EPSG:4326'

        # Criamos a camada de resultado no mesmo CRS da camada de entrada.
        # Os campos 'revisao' e 'acerto' são usados pela ferramenta
        # Revisor de Pontos para marcar o resultado de cada ponto.
        layer_name = '{} RandomPoints'.format(self._active_layer_name)
        uri        = 'Point?crs={}&field=revisao:string(20)&field=acerto:string(20)'.format(
            crs_str)
        mem_layer = QgsVectorLayer(uri, layer_name, 'memory')

        if not mem_layer.isValid():
            self._status('Erro ao criar camada. / Error creating layer.', error=True)
            return

        provider = mem_layer.dataProvider()
        features = []
        for pt in points_src:
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPointXY(pt))
            # Valores padrão para as colunas de revisão — o usuário
            # preencherá com a ferramenta Revisor de Pontos.
            feat.setAttributes(['Não', 'indiferente'])
            features.append(feat)

        provider.addFeatures(features)
        mem_layer.updateExtents()

        # Símbolo azul simples — contrasta bem com camadas de satélite
        # e com os polígonos da camada de origem (geralmente verde ou cinza).
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'circle', 'color': '#1a73e8',
            'outline_color': '#0d47a1', 'outline_width': '0.4', 'size': '3',
        })
        mem_layer.renderer().setSymbol(symbol)
        QgsProject.instance().addMapLayer(mem_layer)

        n_placed = len(points_src)
        if n_placed < self._n_requested:
            # A thread saiu antes de completar — o buffer era muito grande
            # para a área disponível ou max_fails foi atingido.
            msg = (
                '{}/{} pontos — buffer esgotou a área disponível. / '
                '{}/{} points — buffer exhausted available area.'.format(
                    n_placed, self._n_requested, n_placed, self._n_requested))
        else:
            msg = '{} pontos gerados. / {} points generated.'.format(
                n_placed, n_placed)
        self._status(msg, error=False)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _status(self, msg, error=False):
        # Centraliza a atualização do label de status com cor semântica:
        # vermelho para erro, verde para sucesso/andamento.
        color = '#c62828' if error else '#2e7d32'
        self._lbl_status.setStyleSheet('font-size:10px; color:{};'.format(color))
        self._lbl_status.setText(msg)

    def closeEvent(self, event):
        # QUANDO É CHAMADO: o Qt chama closeEvent() quando o usuário fecha
        # a janela (X ou Alt+F4). Se a thread ainda estiver rodando,
        # precisamos cancelá-la ANTES de destruir o diálogo.
        # Sem isso, a thread pode tentar emitir sinais para um diálogo
        # que já foi destruído — crash garantido.
        if self._gen_thread and self._gen_thread.isRunning():
            self._gen_thread.cancel()
            # wait(2000): aguarda até 2 segundos pela thread terminar.
            # Após esse timeout, a thread é abandonada pelo Python
            # (o GC cuidará da limpeza eventualmente).
            self._gen_thread.wait(2000)
        super().closeEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# Tool — wrapper de ciclo de vida
# ──────────────────────────────────────────────────────────────────────────────

class RandomPointsTool:
    # Esta classe segue o padrão do plugin: uma classe "Tool" leve que
    # instancia o diálogo apenas na primeira chamada e o reutiliza depois.
    # Manter o diálogo vivo preserva os valores dos campos entre sessões.

    def __init__(self, iface):
        self.iface = iface
        # None significa que o diálogo ainda não foi criado.
        # Criamos na primeira chamada a run() para não atrasar o startup
        # do plugin com a criação de todos os diálogos de uma vez.
        self._dlg  = None

    def run(self):
        if self._dlg is None:
            # parent=iface.mainWindow() faz o diálogo aparecer centralizado
            # sobre a janela principal do QGIS e o mantém na frente dela.
            self._dlg = RandomPointsDialog(self.iface, parent=self.iface.mainWindow())
        # Atualiza o combo de camadas antes de mostrar — o projeto pode ter
        # mudado desde a última vez que o diálogo foi aberto.
        self._dlg._populate_layers()
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
