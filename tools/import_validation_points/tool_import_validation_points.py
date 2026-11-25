# -*- coding: utf-8 -*-
# ============================================================
# FERRAMENTA: Importar Pontos de Validação / Import Validation Points
#
# O que faz (ponto de vista do usuário):
#   O usuário escolhe um CSV exportado pelo app RTH World
#   Explorer. Cada linha do CSV representa uma observação de
#   campo: onde o observador estava (latitude/longitude), para
#   onde ele olhava (heading = ângulo bússola) e de que lado
#   estava a cultura que ele observava (lado_cultura).
#
#   O plugin cria uma camada de pontos no QGIS com setas
#   direcionais coloridas que indicam visualmente para qual
#   lado a cultura foi observada:
#     - Verde  → Direita  (cultura à direita do observador)
#     - Laranja → Esquerda (cultura à esquerda)
#     - Azul   → Ambos    (cultura dos dois lados)
#     - Cinza  → Outro    (valor não reconhecido)
#
# Como funciona internamente:
#   1. Lê o CSV com utf-8-sig para suportar BOM do Flutter/Excel
#   2. Detecta colunas por nome (case-insensitive)
#   3. Calcula o ângulo da seta (angulo_seta) por feição
#   4. Usa QgsRuleBasedRenderer — renderizador por regras —
#      para dar uma cor diferente para cada valor de lado_cultura
#   5. Cada regra usa QgsMarkerSymbol com rotação data-defined
#      lendo o campo 'angulo_seta' gerado no passo 3
#
# Ciclo de vida no plugin:
#   Instanciada em RTH PROJECT.py no __init__() do plugin.
#   Ativada via menu RTH World Explorer > Importar Pontos de Validação.
# ============================================================

import os
import csv

from qgis.PyQt.QtWidgets import QFileDialog
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer,
    QgsFields, QgsField, QgsFeature, QgsGeometry, QgsPointXY,
    QgsMarkerSymbol, QgsRuleBasedRenderer, QgsSymbolLayer, QgsProperty,
)

# ── Compat Qt5/Qt6: o enum de ângulo mudou de namespace no Qt6 ──────────────
# No QGIS 3.x (Qt5): QgsSymbolLayer.PropertyAngle
# No QGIS 4.x (Qt6): QgsSymbolLayer.Property.Angle
# O try/except aqui garante que o código funcione nas duas versões.
# Definimos no topo do módulo (nível de arquivo) para não repetir
# em cada chamada — uma constante é mais eficiente e mais fácil
# de manter se o enum mudar novamente no futuro.
try:
    _PROP_ANGLE = QgsSymbolLayer.Property.Angle
except AttributeError:
    _PROP_ANGLE = QgsSymbolLayer.PropertyAngle


def _make_arrow(color, size='5'):
    """Cria um símbolo de seta com rotação definida pelo campo 'angulo_seta'.

    Retorna QgsMarkerSymbol pronto para uso em QgsRuleBasedRenderer.Rule.
    """
    # QgsMarkerSymbol.createSimple() cria um símbolo de ponto simples
    # a partir de um dicionário. 'filled_arrowhead' é uma forma nativa
    # do QGIS — uma seta preenchida. O QGIS desenha a seta apontando
    # para cima (norte) quando o ângulo é 0.
    sym = QgsMarkerSymbol.createSimple({
        'name':          'filled_arrowhead',
        'color':         color,
        'outline_color': '#333333',
        'outline_width': '0.2',
        'size':          size,
    })

    # sym.symbolLayer(0) acessa a primeira camada de símbolo.
    # Um QgsMarkerSymbol pode ter várias camadas sobrepostas (ex: seta
    # com contorno separado), mas aqui usamos apenas a camada 0.
    sl = sym.symbolLayer(0)

    # setDataDefinedProperty vincula uma propriedade visual do símbolo
    # a uma expressão ou campo de atributo da feição. Aqui vinculamos
    # o ÂNGULO de rotação ao valor do campo 'angulo_seta' de cada ponto.
    # Isso faz com que cada seta aponte em uma direção diferente,
    # calculada em _arrow_angle() para cada feição.
    # Sem isso, todas as setas apontariam para a mesma direção fixa.
    sl.setDataDefinedProperty(_PROP_ANGLE, QgsProperty.fromField('angulo_seta'))
    return sym


def _arrow_angle(heading, lado):
    """Calcula o ângulo de exibição da seta no mapa.

    heading   → ângulo bússola do observador (0=Norte, sentido horário)
    lado      → 'Direita', 'Esquerda' ou 'Ambos'

    Lógica:
      - O observador está caminhando/olhando na direção 'heading'.
      - "Direita" = a cultura está 90° à direita do heading (heading + 90°)
      - "Esquerda" = a cultura está 90° à esquerda (heading - 90°)
      - "Ambos" = a seta aponta na própria direção do heading (frente)
    O módulo 360 garante que o ângulo fique sempre entre 0 e 359°.
    """
    try:
        h = float(heading or 0)
    except (ValueError, TypeError):
        h = 0.0
    lado_str = (lado or '').strip().lower()
    if lado_str in ('direita', 'd', 'right', 'r'):
        return (h + 90.0) % 360.0
    if lado_str in ('esquerda', 'e', 'left', 'l'):
        return (h - 90.0 + 360.0) % 360.0
    # 'ambos', 'both' ou qualquer valor não reconhecido → aponta para o heading
    return h % 360.0


class ImportValidationPointsTool:
    """Importa pontos de validação do RTH World Explorer / Imports validation points."""

    def __init__(self, iface):
        # iface dá acesso à janela principal, barra de mensagens, canvas, etc.
        self.iface = iface

    def run(self):
        path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            'Importar Pontos de Validação / Import Validation Points',
            '',
            'CSV (*.csv *.CSV);;Todos os arquivos / All files (*)')
        if not path:
            return
        self._load(path)

    def _load(self, path):
        base = os.path.splitext(os.path.basename(path))[0]

        # ── Leitura do CSV ────────────────────────────────────────────────────
        rows = []
        try:
            # 'utf-8-sig' é obrigatório para arquivos gerados por apps Flutter,
            # Excel ou LibreOffice no Windows: esses apps adicionam um BOM
            # (Byte Order Mark, 3 bytes invisíveis) no início do arquivo.
            # O Python padrão 'utf-8' leria o BOM como parte do nome da
            # primeira coluna — resultado: 'latitude' viraria '﻿latitude'
            # e a detecção de coluna falharia silenciosamente.
            with open(path, 'r', encoding='utf-8-sig', newline='') as fh:
                # DictReader lê cada linha como um dicionário {coluna: valor}.
                # delimiter=';' porque o app exporta com ponto-e-vírgula,
                # não com vírgula (padrão de planilhas brasileiras/europeias).
                reader = csv.DictReader(fh, delimiter=';')
                header = reader.fieldnames or []
                for row in reader:
                    rows.append(dict(row))
        except Exception as ex:
            self.iface.messageBar().pushMessage(
                'RTH World Explorer',
                'Erro ao ler o arquivo: {} / Error reading file: {}'.format(ex, ex),
                level=Qgis.MessageLevel.Critical, duration=8)
            return

        if not rows:
            self.iface.messageBar().pushMessage(
                'RTH World Explorer',
                'Arquivo sem dados. / File contains no data.',
                level=Qgis.MessageLevel.Warning, duration=6)
            return

        # ── Detecta colunas obrigatórias (case-insensitive) ───────────────────
        # Construímos um dicionário {nome_em_minúsculas: nome_original}
        # para tolerar variações como 'Latitude', 'LATITUDE', 'latitude'.
        # O app exporta sempre em minúsculas, mas defensivamente aceitamos
        # qualquer capitalização — o usuário pode ter editado o CSV.
        col_map     = {k.lower().strip(): k for k in (header or rows[0].keys())}
        lat_col     = col_map.get('latitude')
        lon_col     = col_map.get('longitude')
        heading_col = col_map.get('heading')
        lado_col    = col_map.get('lado_cultura')

        if not lat_col or not lon_col:
            self.iface.messageBar().pushMessage(
                'RTH World Explorer',
                'Colunas "latitude"/"longitude" não encontradas no CSV. / '
                '"latitude"/"longitude" columns not found in CSV.',
                level=Qgis.MessageLevel.Critical, duration=8)
            return

        # ── Define campos da camada: todas as colunas do CSV + angulo_seta ────
        # Preservamos todas as colunas para o usuário poder filtrar/exportar.
        # Truncamos os nomes a 50 caracteres — limite seguro para a maioria
        # dos drivers de exportação (Shapefile limita a 10, mas camadas de
        # memória aceitam mais; 50 é um meio-termo razoável).
        csv_cols = list(rows[0].keys())
        qfields  = QgsFields()
        for col in csv_cols:
            qfields.append(QgsField(col[:50], QVariant.String))
        # Campo calculado — não vem do CSV, é gerado por _arrow_angle().
        # Deve ser Double (ponto flutuante) porque o ângulo pode ter decimais.
        qfields.append(QgsField('angulo_seta', QVariant.Double))

        # ── Cria camada de memória ────────────────────────────────────────────
        # 'Point?crs=EPSG:4326' cria uma camada de pontos no sistema WGS84.
        # O parâmetro 'memory' ao final instrui o QGIS a não salvar em disco.
        # A camada existe apenas na RAM — se o usuário quiser salvar,
        # precisa exportar manualmente (botão direito > Exportar).
        mem = QgsVectorLayer('Point?crs=EPSG:4326', base, 'memory')
        pr  = mem.dataProvider()
        # addAttributes() registra os campos no data provider.
        # updateFields() sincroniza o schema do provider com a camada.
        # Sem updateFields(), os campos não ficam visíveis na tabela de atributos.
        pr.addAttributes(qfields.toList())
        mem.updateFields()

        # ── Adiciona feições ──────────────────────────────────────────────────
        feats   = []
        skipped = 0
        for row in rows:
            try:
                lat = float(row.get(lat_col, '') or 0)
                lon = float(row.get(lon_col, '') or 0)
            except (ValueError, TypeError):
                skipped += 1
                continue

            heading = row.get(heading_col, '0') if heading_col else '0'
            lado    = row.get(lado_col,    '')   if lado_col    else ''
            angulo  = _arrow_angle(heading, lado)

            # QgsFeature(mem.fields()) cria uma feição já com o schema
            # correto (campos certos, tipos certos). Se não passarmos os
            # fields, a feição fica sem atributos e assignments falham.
            feat = QgsFeature(mem.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            # Preenchemos cada campo com o valor do CSV (str).
            # col[:50] trunca igual ao que fizemos na definição dos campos.
            for col in csv_cols:
                feat[col[:50]] = str(row.get(col, '') or '')
            feat['angulo_seta'] = angulo
            feats.append(feat)

        if not feats:
            self.iface.messageBar().pushMessage(
                'RTH World Explorer',
                'Nenhuma feição válida encontrada. / No valid features found.',
                level=Qgis.MessageLevel.Warning, duration=6)
            return

        pr.addFeatures(feats)
        # updateExtents() recalcula o extent (bbox) da camada após inserir
        # as feições. Sem isso, o QGIS pode não fazer zoom correto na camada
        # quando o usuário clicar em "Zoom to Layer".
        mem.updateExtents()

        # ── Simbologia por regras (uma cor por valor de lado_cultura) ─────────
        # QgsRuleBasedRenderer é o renderizador mais poderoso do QGIS:
        # cada regra tem uma expressão de filtro e um símbolo próprio.
        # Funciona como um bloco if/elif/else aplicado a cada feição:
        #   - Feição onde "lado_cultura" = 'Direita' → seta verde
        #   - Feição onde "lado_cultura" = 'Esquerda' → seta laranja
        #   - etc.
        #
        # Rule(None) cria a regra raiz — ela não tem símbolo nem filtro
        # próprio, serve apenas como contêiner para as regras filhas.
        # Não adicionar a raiz ao renderer diretamente — ela é passada
        # ao construtor de QgsRuleBasedRenderer.
        root = QgsRuleBasedRenderer.Rule(None)
        for label, expr, color in [
            ('Direita / Right',  '"lado_cultura" = \'Direita\'',  '#4CAF50'),  # verde
            ('Esquerda / Left',  '"lado_cultura" = \'Esquerda\'', '#FF9800'),  # laranja
            ('Ambos / Both',     '"lado_cultura" = \'Ambos\'',    '#1A73E8'),  # azul
            ('Outro / Other',    'ELSE',                          '#9E9E9E'),  # cinza
        ]:
            # Cada Rule recebe um símbolo (a seta da cor correta)
            rule = QgsRuleBasedRenderer.Rule(_make_arrow(color))
            rule.setLabel(label)
            # setFilterExpression() define quando esta regra se aplica.
            # Expressões usam a sintaxe QGIS (similar a SQL WHERE).
            # 'ELSE' captura qualquer feição que não bateu nas regras anteriores.
            rule.setFilterExpression(expr)
            root.appendChild(rule)

        # setRenderer() substitui o renderizador padrão (cor aleatória)
        # pelo nosso renderizador por regras.
        mem.setRenderer(QgsRuleBasedRenderer(root))
        QgsProject.instance().addMapLayer(mem)

        msg = '{} ponto(s) importado(s)'.format(len(feats))
        if skipped:
            msg += ', {} ignorado(s) (lat/lon inválida)'.format(skipped)
        msg += '. / {} point(s) imported'.format(len(feats))
        if skipped:
            msg += ', {} skipped (invalid lat/lon)'.format(skipped)
        msg += '.'

        self.iface.messageBar().pushMessage(
            'RTH World Explorer', msg,
            level=Qgis.MessageLevel.Success, duration=6)
