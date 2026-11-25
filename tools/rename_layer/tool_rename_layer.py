# -*- coding: utf-8 -*-
"""
RTH Renomear Layer Rápido — adiciona/remove ★ no início do nome da(s) camada(s).
Funciona em todas as camadas selecionadas no painel de camadas.
Toggle: adiciona ★ se não tem; remove se já tem.
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import Qgis

STAR = u'★ '


class RenameLayerTool:
    """Adiciona ou remove prefixo ★ nas camadas selecionadas / Add or remove ★ prefix on selected layers."""

    def __init__(self, iface):
        self.iface = iface

    def tr(self, message):
        return QCoreApplication.translate('RenameLayerTool', message)

    def run(self):
        """Alterna o prefixo ★ nas camadas selecionadas / Toggle ★ prefix on selected layers."""
        layers = self.iface.layerTreeView().selectedLayers()

        if not layers:
            # Tenta a camada ativa se nenhuma estiver selecionada / Fall back to active layer
            active = self.iface.activeLayer()
            if active is None:
                self.iface.messageBar().pushMessage(
                    'RTH',
                    self.tr(u'Selecione ao menos uma camada no painel / Select at least one layer in the panel'),
                    level=Qgis.MessageLevel.Warning, duration=3)
                return
            layers = [active]

        # Decide a direção do toggle:
        # Se TODAS já têm ★, remove de todas; caso contrário, adiciona nas que não têm.
        all_starred = all(lyr.name().startswith(STAR) for lyr in layers)

        renamed = 0
        for lyr in layers:
            name = lyr.name()
            if all_starred:
                new_name = name[len(STAR):]
            elif not name.startswith(STAR):
                new_name = STAR + name
            else:
                continue
            lyr.setName(new_name)
            renamed += 1

        if renamed == 1:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Camada renomeada: {0}').format(layers[0].name()),
                level=Qgis.MessageLevel.Info, duration=2)
        elif renamed > 1:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'{0} camadas renomeadas / {0} layers renamed').format(renamed),
                level=Qgis.MessageLevel.Info, duration=2)
