# -*- coding: utf-8 -*-
"""
RTH DEM Downloader — ponto de entrada do plugin
RTH DEM Downloader — plugin entry point

Estrutura de arquivos / File structure:
  tool_dem_constants.py  — constantes e tipos de dado / constants and data types
  tool_dem_sources.py    — busca INPE (STAC), grade Copernicus e thread de download /
                           INPE search (STAC), Copernicus grid and download thread
  tool_dem_maptool.py    — ferramenta de desenho de retângulo / rectangle drawing tool
  tool_dem_dialog.py     — janela principal / main dialog window
  tool_dem_downloader.py — este arquivo, registra a ferramenta no plugin / this file, registers tool in plugin

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

from qgis.core import Qgis
from .tool_dem_dialog import DEMDownloaderDialog


class DEMDownloaderTool:
    """
    Registra e gerencia o RTH DEM Downloader dentro do plugin RTH.
    Registers and manages RTH DEM Downloader inside the RTH plugin.

    Uso no plugin principal / Usage in main plugin:
        self.dem_tool = DEMDownloaderTool(self.iface)
        # ...
        self.dem_tool.open()
    """

    def __init__(self, iface):
        """
        Inicializa com a interface QGIS / Initialize with QGIS interface.

        iface : QgisInterface — interface principal do QGIS / main QGIS interface
        """
        # Interface QGIS / QGIS interface
        self.iface = iface
        # Referência ao diálogo (criado sob demanda) / Dialog reference (created on demand)
        self._dialog = None

    def open(self):
        """
        Abre (ou traz ao foco) o diálogo do DEM Downloader.
        Opens (or brings to focus) the DEM Downloader dialog.
        """
        try:
            # Cria o diálogo apenas na primeira chamada / Create dialog only on first call
            if self._dialog is None:
                self._dialog = DEMDownloaderDialog(self.iface)
            # Exibe e coloca em foco / Show and bring to focus
            self._dialog.show()
            self._dialog.raise_()
            self._dialog.activateWindow()
        except Exception as e:
            self.iface.messageBar().pushMessage('RTH DEM', str(e), level=Qgis.MessageLevel.Warning)
