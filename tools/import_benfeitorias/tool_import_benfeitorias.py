# -*- coding: utf-8 -*-
"""
tool_import_benfeitorias.py

Importa pontos de benfeitorias do RTH World Explorer para o QGIS.
Lê CSV (;-delimitado) ou Excel (.xlsx), usa latitude/longitude para
geometria e gera simbologia categorizada pelo tipo de benfeitoria.

Imports farm infrastructure points (benfeitorias) from RTH World Explorer
into QGIS. Reads CSV (;-delimited) or Excel (.xlsx), uses lat/lon for
geometry and generates categorized symbology by benfeitoria type.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# GNU General Public License v3
"""

import os
import csv
import colorsys

from qgis.PyQt.QtWidgets import QFileDialog
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer,
    QgsFields, QgsField, QgsFeature, QgsGeometry, QgsPointXY,
    QgsMarkerSymbol, QgsCategorizedSymbolRenderer,
    QgsRendererCategory, QgsSymbolLayer, QgsProperty,
)

# ── Compat Qt5/Qt6 ──────────────────────────────────────────────────────────
try:
    _PROP_ANGLE = QgsSymbolLayer.Property.Angle
except AttributeError:
    _PROP_ANGLE = QgsSymbolLayer.PropertyAngle

# ── Paleta de cores para categorias / Category color palette ────────────────
# Gera N cores distintas espaçadas no espectro HSV.
# Generates N distinct evenly-spaced HSV colors.
def _palette(n):
    if n == 0:
        return []
    colors = []
    for i in range(n):
        h = i / n
        r, g, b = colorsys.hsv_to_rgb(h, 0.72, 0.88)
        colors.append('#{:02x}{:02x}{:02x}'.format(int(r * 255), int(g * 255), int(b * 255)))
    return colors


def _make_marker(color, heading=None):
    """Cria marcador quadrado colorido com rotação opcional pelo campo heading."""
    sym = QgsMarkerSymbol.createSimple({
        'name':          'square',
        'color':         color,
        'outline_color': '#333333',
        'outline_width': '0.3',
        'size':          '4',
    })
    sl = sym.symbolLayer(0)
    sl.setDataDefinedProperty(_PROP_ANGLE, QgsProperty.fromField('heading'))
    return sym


# ── Leitura de arquivo ───────────────────────────────────────────────────────
def _read_csv(path):
    """Lê CSV ;-delimitado com BOM. Retorna (header, rows) ou lança exceção."""
    rows = []
    with open(path, 'r', encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh, delimiter=';')
        header = [c for c in (reader.fieldnames or []) if c is not None]
        for row in reader:
            rows.append(dict(row))
    return header, rows


def _read_xlsx(path):
    """Lê planilha Excel. Retorna (header, rows) ou lança exceção."""
    try:
        import openpyxl
    except ImportError:
        raise ImportError(
            'openpyxl não encontrado. Converta para CSV e tente novamente.\n'
            'openpyxl not found. Convert to CSV and try again.'
        )
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows_raw = list(ws.iter_rows(values_only=True))
    if not rows_raw:
        return [], []
    header = [str(c) if c is not None else '' for c in rows_raw[0]]
    rows = []
    for raw in rows_raw[1:]:
        row = {header[i]: (str(raw[i]) if raw[i] is not None else '')
               for i in range(len(header))}
        rows.append(row)
    wb.close()
    return header, rows


class ImportBenfeitoriasTool:
    """
    Importa pontos de benfeitorias do RTH World Explorer.
    Imports farm infrastructure points from RTH World Explorer.
    """

    def __init__(self, iface):
        self.iface = iface

    def run(self):
        path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            'Importar Pontos de Benfeitorias / Import Infrastructure Points',
            '',
            'Dados RTH / RTH Data (*.csv *.CSV *.xlsx *.XLSX);;'
            'CSV (*.csv *.CSV);;Excel (*.xlsx *.XLSX);;'
            'Todos os arquivos / All files (*)'
        )
        if not path:
            return
        self._load(path)

    def _load(self, path):
        base = os.path.splitext(os.path.basename(path))[0]
        ext  = os.path.splitext(path)[1].lower()

        # ── Leitura ──────────────────────────────────────────────────────────
        try:
            if ext in ('.xlsx', '.xls'):
                header, rows = _read_xlsx(path)
            else:
                header, rows = _read_csv(path)
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

        # ── Detecta colunas obrigatórias (case-insensitive) ──────────────────
        col_map     = {k.lower().strip(): k for k in header if k}
        lat_col     = col_map.get('latitude')
        lon_col     = col_map.get('longitude')
        benf_col    = col_map.get('benfeitoria')
        heading_col = col_map.get('heading')

        if not lat_col or not lon_col:
            self.iface.messageBar().pushMessage(
                'RTH World Explorer',
                'Colunas "latitude"/"longitude" não encontradas. / '
                '"latitude"/"longitude" columns not found.',
                level=Qgis.MessageLevel.Critical, duration=8)
            return

        # ── Campos da camada ──────────────────────────────────────────────────
        csv_cols   = [c for c in header if c is not None]
        safe_names = []
        seen       = set()
        qfields    = QgsFields()
        for col in csv_cols:
            safe = col[:50].strip()
            base_safe = safe
            n = 2
            while safe in seen:
                safe = '{}_{}'.format(base_safe[:47], n)
                n += 1
            seen.add(safe)
            safe_names.append(safe)
            qfields.append(QgsField(safe, QVariant.String))

        # ── Camada de memória ─────────────────────────────────────────────────
        mem = QgsVectorLayer('Point?crs=EPSG:4326', base, 'memory')
        pr  = mem.dataProvider()
        pr.addAttributes(qfields.toList())
        mem.updateFields()

        # ── Feições ───────────────────────────────────────────────────────────
        feats   = []
        skipped = 0
        categories_seen = []  # mantém a ordem de aparição / preserve insertion order

        for row in rows:
            try:
                lat = float(row.get(lat_col, '') or 0)
                lon = float(row.get(lon_col, '') or 0)
            except (ValueError, TypeError):
                skipped += 1
                continue
            if lat == 0.0 and lon == 0.0:
                skipped += 1
                continue

            benf_val = str(row.get(benf_col, '') or '').strip() if benf_col else ''
            if benf_val and benf_val not in categories_seen:
                categories_seen.append(benf_val)

            feat = QgsFeature(mem.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            for orig, safe in zip(csv_cols, safe_names):
                feat[safe] = str(row.get(orig, '') or '')
            feats.append(feat)

        if not feats:
            self.iface.messageBar().pushMessage(
                'RTH World Explorer',
                'Nenhuma feição válida encontrada. / No valid features found.',
                level=Qgis.MessageLevel.Warning, duration=6)
            return

        pr.addFeatures(feats)
        mem.updateExtents()

        # ── Simbologia categorizada por benfeitoria ───────────────────────────
        if benf_col and categories_seen:
            benf_safe = safe_names[csv_cols.index(benf_col)] if benf_col in csv_cols else benf_col
            palette   = _palette(len(categories_seen))
            qcats     = []
            for cat_val, color in zip(categories_seen, palette):
                sym = _make_marker(color)
                qcats.append(QgsRendererCategory(cat_val, sym, cat_val))
            # Categoria vazia / Empty category
            sym_empty = _make_marker('#9E9E9E')
            qcats.append(QgsRendererCategory('', sym_empty, '(sem tipo / no type)'))
            renderer = QgsCategorizedSymbolRenderer(benf_safe, qcats)
            mem.setRenderer(renderer)

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
