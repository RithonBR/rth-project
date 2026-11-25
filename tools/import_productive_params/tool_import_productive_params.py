# -*- coding: utf-8 -*-
# ============================================================
# FERRAMENTA: Importar Parâmetros Produtivos / Import Productive Parameters
#
# O que faz (ponto de vista do usuário):
#   O usuário escolhe um CSV exportado pelo app RTH World
#   Explorer contendo parâmetros produtivos de campo (cultura,
#   solo, etc. — até 60+ colunas). O plugin cria uma camada de
#   pontos no QGIS com TODOS os campos do CSV como atributos,
#   usando latitude/longitude para a geometria.
#
#   Diferente da ferramenta de Pontos de Validação, esta não
#   aplica simbologia direcional — apenas pontos verdes simples.
#   O foco é preservar todos os dados para análise posterior
#   (filtros, heat maps, joins espaciais, etc.).
#
# Como funciona internamente:
#   1. Lê o CSV com encoding utf-8-sig (suporte a BOM)
#   2. Detecta lat/lon por nome de coluna (case-insensitive)
#   3. Cria campos para TODAS as colunas (nomes truncados a 50 chars
#      e deduplicados para evitar conflitos)
#   4. Cria camada de memória e adiciona as feições
#   5. Aplica símbolo de ponto verde simples
#
# Ciclo de vida no plugin:
#   Instanciada em RTH PROJECT.py no __init__() do plugin.
#   Ativada via menu RTH World Explorer > Importar Parâmetros Produtivos.
# ============================================================

import os
import csv

from qgis.PyQt.QtWidgets import QFileDialog
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer,
    QgsFields, QgsField, QgsFeature, QgsGeometry, QgsPointXY,
    QgsMarkerSymbol,
)


class ImportProductiveParamsTool:
    """Importa parâmetros produtivos do RTH World Explorer / Imports productive parameters."""

    def __init__(self, iface):
        # iface dá acesso à janela principal, barra de mensagens, canvas, etc.
        self.iface = iface

    def run(self):
        path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            'Importar Parâmetros Produtivos / Import Productive Parameters',
            '',
            'CSV (*.csv *.CSV);;Todos os arquivos / All files (*)')
        if not path:
            return
        self._load(path)

    def _load(self, path):
        base = os.path.splitext(os.path.basename(path))[0]

        # ── Leitura do CSV ────────────────────────────────────────────────────
        rows = []
        header = []
        try:
            # 'utf-8-sig' trata o BOM (Byte Order Mark) que o Flutter e
            # o Excel inserem no início dos CSVs. Sem isso, o nome da
            # primeira coluna ficaria com 3 caracteres invisíveis na frente
            # e a detecção de lat/lon falharia silenciosamente.
            with open(path, 'r', encoding='utf-8-sig', newline='') as fh:
                reader = csv.DictReader(fh, delimiter=';')
                header = list(reader.fieldnames or [])
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

        # ── Localiza colunas de lat/lon por nome (case-insensitive) ──────────
        # Construímos um índice {minúsculas: nome_original} para aceitar
        # 'latitude', 'Latitude', 'LATITUDE', etc. sem verificar cada caso.
        col_map = {k.lower().strip(): k for k in (header or rows[0].keys())}
        lat_col = col_map.get('latitude')
        lon_col = col_map.get('longitude')

        if not lat_col or not lon_col:
            self.iface.messageBar().pushMessage(
                'RTH World Explorer',
                'Colunas "latitude"/"longitude" não encontradas no CSV. / '
                '"latitude"/"longitude" columns not found in CSV.',
                level=Qgis.MessageLevel.Critical, duration=8)
            return

        # ── Constrói os campos: todas as colunas do CSV ───────────────────────
        # O objetivo é preservar TODOS os dados do CSV como atributos da
        # camada para que o usuário possa fazer análises posteriores no QGIS.
        csv_cols  = [c for c in header if c is not None]
        qfields   = QgsFields()
        seen_names = set()
        # safe_names é uma lista paralela a csv_cols:
        # safe_names[i] = nome do campo QGIS correspondente a csv_cols[i]
        safe_names = []
        for col in csv_cols:
            # Truncamos a 50 chars. Shapefiles limitam a 10, mas camadas
            # de memória não têm esse limite. 50 é conservador e evita
            # problemas se o usuário exportar para GeoPackage ou similar.
            safe = col[:50].strip()
            base_safe = safe
            n = 2
            # Deduplicação: se dois nomes de coluna ficarem iguais após
            # truncamento (ex: 'parametro_producao_soja_1' e
            # 'parametro_producao_soja_2' → ambos viram 'parametro_producao_'),
            # adicionamos um sufixo numérico para evitar o conflito.
            while safe in seen_names:
                safe = '{}_{}'.format(base_safe[:47], n)
                n += 1
            seen_names.add(safe)
            safe_names.append(safe)
            # QVariant.String: todos os campos são texto. Não tentamos
            # inferir tipos (int, float, date) — o CSV pode ter valores
            # mistos ou vazios em qualquer coluna. O usuário pode converter
            # tipos depois na calculadora de campos do QGIS.
            qfields.append(QgsField(safe, QVariant.String))

        # ── Cria camada de memória ────────────────────────────────────────────
        # 'Point?crs=EPSG:4326': pontos em WGS84 (latitude/longitude decimal),
        # que é o sistema de coordenadas dos dados do app (GPS smartphone).
        # 'memory' instrui o QGIS a não salvar em disco automaticamente.
        mem = QgsVectorLayer('Point?crs=EPSG:4326', base, 'memory')
        pr  = mem.dataProvider()
        pr.addAttributes(qfields.toList())
        # updateFields() é obrigatório após addAttributes() — sem ela,
        # a camada não "vê" os campos e qualquer acesso por nome falha.
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

            # Linhas com lat=0 e lon=0 são linhas de erro ou placeholder
            # do app (coordenada inválida exportada como zero).
            # Ignoramos para não poluir a camada com pontos no Atlântico.
            if lat == 0.0 and lon == 0.0:
                skipped += 1
                continue

            feat = QgsFeature(mem.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            # Iteramos com zip para alinhar nome_csv → nome_qgis sem
            # precisar de dicionário ou busca linear.
            for orig_col, safe_name in zip(csv_cols, safe_names):
                feat[safe_name] = str(row.get(orig_col, '') or '')
            feats.append(feat)

        if not feats:
            self.iface.messageBar().pushMessage(
                'RTH World Explorer',
                'Nenhuma feição válida encontrada. / No valid features found.',
                level=Qgis.MessageLevel.Warning, duration=6)
            return

        pr.addFeatures(feats)
        # updateExtents() recalcula o bounding box da camada após inserir
        # feições. Necessário para que "Zoom to Layer" funcione corretamente.
        mem.updateExtents()

        # ── Simbologia: ponto verde simples ───────────────────────────────────
        # Usamos verde (#0F9D58) para diferenciar visualmente dos pontos de
        # validação (que usam azul). O outline escuro (#065F34) dá contraste
        # para os pontos ficarem visíveis sobre imagens de satélite.
        sym = QgsMarkerSymbol.createSimple({
            'name':          'circle',
            'color':         '#0F9D58',
            'outline_color': '#065F34',
            'outline_width': '0.4',
            'size':          '3.5',
        })
        # renderer() retorna o QgsSingleSymbolRenderer padrão da camada.
        # setSymbol() substitui o símbolo padrão (cor aleatória) pelo nosso.
        mem.renderer().setSymbol(sym)
        QgsProject.instance().addMapLayer(mem)

        msg = '{} ponto(s) importado(s), {} campo(s)'.format(len(feats), len(csv_cols))
        if skipped:
            msg += ', {} ignorado(s) (lat/lon inválida)'.format(skipped)
        msg += '. / {} point(s) imported, {} field(s)'.format(len(feats), len(csv_cols))
        if skipped:
            msg += ', {} skipped'.format(skipped)
        msg += '.'

        self.iface.messageBar().pushMessage(
            'RTH World Explorer', msg,
            level=Qgis.MessageLevel.Success, duration=6)
