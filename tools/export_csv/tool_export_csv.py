# -*- coding: utf-8 -*-
"""
Ferramenta Export CSV - Exporta camada de pontos para CSV com colunas latitude, longitude
Export CSV Tool - Exports point layer to CSV with latitude, longitude columns

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Diálogo de seleção de arquivo / File selection dialog
from qgis.PyQt.QtWidgets import QFileDialog
# Módulos QGIS para exportação vetorial e projeto / QGIS modules for vector export and project
from qgis.core import Qgis, QgsVectorFileWriter, QgsProject, QgsWkbTypes
# Módulo CSV para reordenar colunas no pós-processamento / CSV module to reorder columns in post-processing
import csv


class ExportGridCSVTool:
    """Exporta camada de pontos para CSV com colunas latitude e longitude / Exports point layer to CSV with latitude and longitude columns."""

    def __init__(self, iface):
        # Armazena a interface QGIS / Store QGIS interface
        self.iface = iface

    def run(self):
        """Executa a exportação para CSV / Execute CSV export."""

        # ── 1. Obtém a camada ativa / Get active layer ──
        layer = self.iface.activeLayer()
        if layer is None:
            self.iface.messageBar().pushMessage(
                'Export CSV', 'Nenhuma camada ativa / No active layer', level=Qgis.MessageLevel.Warning)
            return

        # ── 2. Valida se é uma camada vetorial de pontos / Validate it is a point vector layer ──
        if not hasattr(layer, 'wkbType'):
            self.iface.messageBar().pushMessage(
                'Export CSV', 'A camada ativa não é vetorial / Active layer is not a vector layer', level=Qgis.MessageLevel.Warning)
            return

        if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PointGeometry:
            self.iface.messageBar().pushMessage(
                'Export CSV',
                'A camada deve ser de pontos / Layer must be a point layer',
                level=Qgis.MessageLevel.Warning)
            return

        # ── 3. Abre diálogo para escolha do arquivo de saída / Open dialog to choose output file ──
        # Obtém o EPSG do CRS da camada para incluir no nome do arquivo / Get layer CRS EPSG to include in filename
        epsg_str = layer.crs().authid().replace(':', '_')  # ex: EPSG_31982
        # Sugere o nome da camada + EPSG como nome do arquivo / Suggest layer name + EPSG as filename
        suggested = layer.name().replace(' ', '_') + '_' + epsg_str + '.csv'
        path, _ = QFileDialog.getSaveFileName(
            None,
            'Salvar CSV / Save CSV',
            suggested,
            'CSV (*.csv)'
        )

        # Usuário cancelou / User cancelled
        if not path:
            return

        # Garante extensão .csv / Ensure .csv extension
        if not path.lower().endswith('.csv'):
            path += '.csv'

        # ── 4. Configura as opções de exportação / Configure export options ──
        options = QgsVectorFileWriter.SaveVectorOptions()
        # Formato CSV / CSV format
        options.driverName = 'CSV'
        # Codificação UTF-8 / UTF-8 encoding
        options.fileEncoding = 'UTF-8'
        # AS_XY: X=longitude (col 1), Y=latitude (col 2) — nomes garantidos pelo GDAL
        # AS_XY: X=longitude (col 1), Y=latitude (col 2) — names guaranteed by GDAL
        options.layerOptions = [
            'GEOMETRY=AS_XY',
            'SEPARATOR=COMMA',
            'STRING_QUOTING=IF_AMBIGUOUS',
            'LINEFORMAT=LF',
        ]

        # ── 5. Executa a exportação / Execute export ──
        # Número de valores retornados varia por versão do QGIS — captura tudo com *
        # Number of returned values varies by QGIS version — capture all with *
        error, *rest = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            path,
            QgsProject.instance().transformContext(),
            options
        )
        # Última entrada de rest é sempre a mensagem de erro / Last entry in rest is always the error message
        msg = rest[-1] if rest else ''

        # ── 6. Pós-processamento: reordena e renomeia colunas / Post-process: reorder and rename columns ──
        # AS_XY produz: X (longitude), Y (latitude) — queremos: latitude (col 1), longitude (col 2)
        # AS_XY produces: X (longitude), Y (latitude) — we want: latitude (col 1), longitude (col 2)
        if error == QgsVectorFileWriter.NoError:
            try:
                with open(path, 'r', newline='', encoding='utf-8-sig') as f:
                    rows = list(csv.reader(f))

                if rows:
                    header = rows[0]
                    # Localiza as colunas X (longitude) e Y (latitude) no cabeçalho do GDAL
                    # Locate X (longitude) and Y (latitude) columns in GDAL header
                    x_idx = next((i for i, h in enumerate(header) if h.strip().upper() == 'X'), None)
                    y_idx = next((i for i, h in enumerate(header) if h.strip().upper() == 'Y'), None)

                    if x_idx is not None and y_idx is not None:
                        # Índices das demais colunas (atributos) / Indices of other columns (attributes)
                        rest_idx = [i for i in range(len(header)) if i not in (x_idx, y_idx)]
                        # Novo cabeçalho: latitude primeiro, longitude segundo, depois atributos
                        # New header: latitude first, longitude second, then attributes
                        new_header = ['latitude', 'longitude'] + [header[i] for i in rest_idx]
                        new_rows = [new_header]
                        for row in rows[1:]:
                            if len(row) >= len(header):
                                # Y (índice y_idx) = latitude, X (índice x_idx) = longitude
                                # Y (index y_idx) = latitude, X (index x_idx) = longitude
                                new_rows.append(
                                    [row[y_idx], row[x_idx]] + [row[i] for i in rest_idx]
                                )
                        with open(path, 'w', newline='', encoding='utf-8') as f:
                            csv.writer(f).writerows(new_rows)
            except Exception:
                pass  # Não crítico — arquivo já foi salvo / Not critical — file already saved

            self.iface.messageBar().pushMessage(
                'Export CSV',
                '{} feição(ões) exportada(s) | colunas: latitude, longitude / feature(s) exported | columns: latitude, longitude → {}'.format(
                    layer.featureCount(), path),
                level=Qgis.MessageLevel.Info, duration=8)
        else:
            self.iface.messageBar().pushMessage(
                'Export CSV',
                'Erro ao exportar / Export error: {}'.format(msg),
                level=Qgis.MessageLevel.Critical)
