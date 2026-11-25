# -*- coding: utf-8 -*-
"""
RespawnTool — Salva e restaura a posição e escala do canvas do mapa
RespawnTool — Save and restore map canvas position and scale

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

from qgis.core import QgsSettings, QgsRectangle, Qgis


class RespawnTool:
    """Salva um "spawn" (posição + escala do canvas) e teleporta de volta para ele / Save a "spawn" (canvas position + scale) and teleport back to it."""

    # Chave base no QgsSettings — persiste entre sessões do QGIS /
    # Base key in QgsSettings — persists between QGIS sessions
    _KEY_XMIN = 'rth_project/spawn/xmin'
    _KEY_YMIN = 'rth_project/spawn/ymin'
    _KEY_XMAX = 'rth_project/spawn/xmax'
    _KEY_YMAX = 'rth_project/spawn/ymax'

    def __init__(self, iface):
        self.iface = iface

    def set_spawn(self):
        """Salva a extensão atual do canvas como spawn / Save current canvas extent as spawn."""
        canvas = self.iface.mapCanvas()
        ext = canvas.extent()
        s = QgsSettings()
        s.setValue(self._KEY_XMIN, ext.xMinimum())
        s.setValue(self._KEY_YMIN, ext.yMinimum())
        s.setValue(self._KEY_XMAX, ext.xMaximum())
        s.setValue(self._KEY_YMAX, ext.yMaximum())
        self.iface.messageBar().pushMessage(
            'RTH Spawn',
            'Spawn salvo! Clique em Teleportar para voltar aqui. / '
            'Spawn saved! Click Teleport to return here.',
            level=Qgis.MessageLevel.Success, duration=4)

    def teleport(self):
        """Restaura o canvas para a posição e escala salvas / Restore canvas to saved position and scale."""
        s = QgsSettings()
        xmin = s.value(self._KEY_XMIN, None)
        if xmin is None:
            self.iface.messageBar().pushMessage(
                'RTH Spawn',
                'Nenhum spawn salvo. Use "Setar Spawn" primeiro. / '
                'No spawn saved. Use "Set Spawn" first.',
                level=Qgis.MessageLevel.Warning, duration=4)
            return
        try:
            ext = QgsRectangle(
                float(xmin),
                float(s.value(self._KEY_YMIN)),
                float(s.value(self._KEY_XMAX)),
                float(s.value(self._KEY_YMAX)))
        except (TypeError, ValueError):
            self.iface.messageBar().pushMessage(
                'RTH Spawn',
                'Dados de spawn corrompidos. Sete um novo spawn. / '
                'Spawn data corrupted. Set a new spawn.',
                level=Qgis.MessageLevel.Critical, duration=4)
            return
        canvas = self.iface.mapCanvas()
        canvas.setExtent(ext)
        canvas.refresh()
