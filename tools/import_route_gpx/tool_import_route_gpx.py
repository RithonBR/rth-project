# -*- coding: utf-8 -*-
# ============================================================
# FERRAMENTA: Importar Rota / Import Route
#
# O que faz (ponto de vista do usuário):
#   O usuário escolhe um arquivo .gpx (formato padrão de GPS)
#   gerado pelo app RTH World Explorer ou qualquer outro GPS,
#   e o plugin carrega no QGIS todas as sub-camadas que tiverem
#   feições:
#     - waypoints → pontos de interesse (ícone estrela laranja)
#     - tracks    → trilha gravada pelo GPS (linha azul sólida)
#     - routes    → rota planejada (linha verde tracejada)
#   Sub-camadas vazias são silenciosamente ignoradas.
#
# Como funciona internamente:
#   GPX é um formato XML. O QGIS não lê GPX diretamente —
#   ele delega ao driver GDAL/OGR. Um único arquivo .gpx
#   contém múltiplas "camadas lógicas" (sublayers). Para acessar
#   cada sublayer, usamos uma URI especial com o sufixo
#   "|layername=nome" — o OGR entende esse formato para qualquer
#   arquivo multi-camada (GPX, GeoPackage, GeoJSON multilayer).
#
# Ciclo de vida no plugin:
#   Instanciada em RTH PROJECT.py no __init__() do plugin.
#   Ativada via menu RTH World Explorer > Importar Rota.
# ============================================================

import os

from qgis.PyQt.QtWidgets import QFileDialog
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer,
    QgsMarkerSymbol, QgsLineSymbol,
)


# Cada entrada define uma sublayer GPX que tentaremos carregar.
# Formato: (nome_ogr, sufixo_PT_EN, tipo_geom, parâmetros_estilo)
#
# O nome_ogr deve ser exatamente o nome que o driver OGR reconhece
# dentro do arquivo GPX — 'waypoints', 'tracks', 'routes' são os
# nomes padrão definidos na especificação GPX 1.1. Se o arquivo
# não tiver aquela sub-camada, QgsVectorLayer.isValid() retorna False.
_GPX_SUBLAYERS = [
    ('waypoints', 'Waypoints',              'point', {'color': '#FF6600', 'name': 'star',   'size': '5'}),
    ('tracks',    'Trilhas / Tracks',       'line',  {'color': '#1A73E8', 'width': '0.8',   'line_style': 'solid'}),
    ('routes',    'Rotas / Routes',         'line',  {'color': '#0F9D58', 'width': '0.8',   'line_style': 'dash'}),
]


class ImportRouteGPXTool:
    """Importa arquivo GPX para o QGIS / Imports a GPX file into QGIS."""

    def __init__(self, iface):
        # iface é a porta de entrada para tudo no QGIS:
        # canvas do mapa, barra de mensagens, janela principal, etc.
        self.iface = iface

    def run(self):
        # QFileDialog.getOpenFileName abre o seletor de arquivo
        # nativo do sistema operacional (não um diálogo Qt genérico).
        # O filtro 'GPX (*.gpx *.GPX)' limita o que o usuário vê
        # na caixa de diálogo, mas ';;Todos os arquivos (*)' permite
        # abrir qualquer arquivo caso o .gpx esteja com outra extensão.
        # O retorno é (caminho_absoluto, filtro_selecionado).
        # O segundo valor não é necessário — descartamos com _.
        path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            'Importar Rota GPX / Import GPX Route',
            '',
            'GPX (*.gpx *.GPX);;Todos os arquivos / All files (*)')
        if not path:
            # Usuário fechou o diálogo sem selecionar nada — encerra aqui
            return
        self._load(path)

    def _load(self, path):
        # os.path.basename extrai o nome do arquivo sem o diretório.
        # os.path.splitext remove a extensão. Ex:
        #   '/Downloads/missao_norte.gpx' → 'missao_norte'
        # Esse valor é usado como prefixo no nome das camadas QGIS.
        base = os.path.splitext(os.path.basename(path))[0]
        loaded = 0

        for ogr_name, suffix, geom_type, style in _GPX_SUBLAYERS:
            # URI no formato OGR para sublayer: 'caminho|layername=nome'
            # Isso instrui o driver GDAL/OGR a abrir apenas a camada
            # 'ogr_name' dentro do arquivo GPX. Sem o '|layername=',
            # o QGIS abriria apenas a primeira sublayer encontrada.
            # O mesmo padrão funciona para GeoPackage e outros formatos
            # multi-camada suportados pelo OGR.
            uri = '{}|layername={}'.format(path, ogr_name)

            # 'ogr' é o nome do data provider que o QGIS usa para GDAL/OGR.
            # Ele suporta mais de 80 formatos vetoriais (Shapefile, GeoJSON,
            # GPX, KML, GeoPackage, DXF...).
            lyr = QgsVectorLayer(uri, '{} — {}'.format(base, suffix), 'ogr')

            # isValid() retorna False quando o driver não conseguiu abrir
            # o arquivo ou quando a sublayer especificada não existe no GPX.
            # featureCount() == 0 significa que a sublayer existe mas não
            # contém feições — não faz sentido adicionar uma camada vazia
            # ao projeto: confunde o usuário e não tem utilidade prática.
            if not lyr.isValid() or lyr.featureCount() == 0:
                continue

            # Aplicamos simbologia ANTES de adicionar a camada ao projeto.
            # Se não fizermos isso, o QGIS sorteará uma cor aleatória para
            # a camada — resultado visual inconsistente entre sessões.
            if geom_type == 'point':
                # QgsMarkerSymbol.createSimple() cria um símbolo de ponto
                # a partir de um dicionário de propriedades simples.
                # 'name' define a forma: 'circle', 'square', 'star',
                # 'filled_arrowhead', etc. — formas nativas do QGIS.
                sym = QgsMarkerSymbol.createSimple({
                    'name':          style['name'],
                    'color':         style['color'],
                    'outline_color': '#333333',
                    'outline_width': '0.3',
                    'size':          style['size'],
                })
                # renderer() retorna o renderizador atual da camada.
                # Por padrão é QgsSingleSymbolRenderer — um único símbolo
                # para todas as feições. setSymbol() substitui o símbolo
                # padrão (cor aleatória) pelo que acabamos de criar.
                lyr.renderer().setSymbol(sym)
            else:
                # QgsLineSymbol.createSimple() — idêntico ao Marker,
                # mas para geometrias de linha.
                # 'line_style': 'solid' = linha contínua;
                #               'dash'  = tracejado;
                #               'dot'   = pontilhado.
                sym = QgsLineSymbol.createSimple({
                    'color':      style['color'],
                    'width':      style['width'],
                    'line_style': style['line_style'],
                })
                lyr.renderer().setSymbol(sym)

            # addMapLayer() registra a camada no projeto QGIS e a faz
            # aparecer no Painel de Camadas e no canvas do mapa.
            # Sem essa chamada, a camada existe apenas na memória Python
            # e o usuário jamais verá nada.
            QgsProject.instance().addMapLayer(lyr)
            loaded += 1

        if loaded == 0:
            # Nenhuma sublayer tinha feições — o arquivo pode ser vazio
            # ou estar no formato errado (ex: arquivo .fit renomeado para .gpx)
            self.iface.messageBar().pushMessage(
                'RTH World Explorer',
                'Nenhuma feição encontrada no arquivo GPX. / No features found in the GPX file.',
                level=Qgis.MessageLevel.Warning, duration=6)
        else:
            self.iface.messageBar().pushMessage(
                'RTH World Explorer',
                'Rota importada: {} ({} camada(s)). / Route imported: {} ({} layer(s)).'.format(
                    base, loaded, base, loaded),
                level=Qgis.MessageLevel.Success, duration=5)
