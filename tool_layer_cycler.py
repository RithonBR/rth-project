# -*- coding: utf-8 -*-
"""
RTH Layer Cycler — Alternância automática de visibilidade de camadas
RTH Layer Cycler — Automatic layer visibility cycling

Alterna a visibilidade das camadas selecionadas no painel de camadas,
de baixo para cima, a cada ativação da ferramenta.

Cycles the visibility of layers selected in the layer panel,
from bottom to top, on each tool activation.

Autor / Author: Rithon (lucianoufscagve@gmail.com)
"""

from qgis.core import QgsProject


class LayerCyclerTool:
    """Alterna a visibilidade de camadas selecionadas uma de cada vez / Cycles selected layer visibility one at a time."""

    def __init__(self, iface):
        # Armazena a interface QGIS / Store QGIS interface
        self.iface = iface
        # IDs das camadas bloqueadas no ciclo atual / IDs of layers locked in the current cycle
        self._locked_ids = []
        # Índice da camada atualmente visível / Index of the currently visible layer
        self._index = -1

    # ------------------------------------------------------------------
    # Método principal / Main method
    # ------------------------------------------------------------------

    def cycle(self):
        """Avança para a próxima camada do ciclo / Advance to the next layer in the cycle."""

        # Obtém camadas selecionadas no painel de camadas / Get layers selected in the layer panel
        selected = self.iface.layerTreeView().selectedLayers()
        selected_ids = {lyr.id() for lyr in selected}

        # Se 2+ camadas selecionadas diferem do ciclo atual, reinicia / If 2+ selected layers differ, restart cycle
        if len(selected) >= 2 and selected_ids != set(self._locked_ids):
            self._locked_ids = self._order_bottom_to_top(selected)
            self._index = -1

        # Sem camadas bloqueadas — pede seleção / No locked layers — request selection
        if not self._locked_ids:
            self.iface.messageBar().pushMessage(
                'RTH Layer Cycler',
                'Selecione 2 ou mais camadas no painel / Select 2 or more layers in the panel',
                level=1, duration=4)
            return

        # Avança o índice ciclicamente / Advance index cyclically
        self._index = (self._index + 1) % len(self._locked_ids)

        # Aplica visibilidade: somente a camada atual fica visível / Apply visibility: only current layer stays visible
        root = QgsProject.instance().layerTreeRoot()
        for i, lid in enumerate(self._locked_ids):
            node = root.findLayer(lid)
            if node is not None:
                node.setItemVisibilityChecked(i == self._index)

        # Exibe feedback na barra de mensagens / Show feedback in the message bar
        current = QgsProject.instance().mapLayer(self._locked_ids[self._index])
        if current:
            self.iface.messageBar().pushMessage(
                'RTH Layer Cycler',
                f'Exibindo / Showing: {current.name()}  '
                f'({self._index + 1} / {len(self._locked_ids)})',
                level=0, duration=2)

    def reset(self):
        """Reseta o ciclo e restaura a visibilidade de todas as camadas / Reset cycle and restore all layers visibility."""
        root = QgsProject.instance().layerTreeRoot()
        for lid in self._locked_ids:
            node = root.findLayer(lid)
            if node is not None:
                node.setItemVisibilityChecked(True)
        self._locked_ids = []
        self._index = -1
        self.iface.messageBar().pushMessage(
            'RTH Layer Cycler',
            'Ciclo reiniciado — todas as camadas restauradas / Cycle reset — all layers restored',
            level=0, duration=3)

    # ------------------------------------------------------------------
    # Utilitário / Utility
    # ------------------------------------------------------------------

    def _order_bottom_to_top(self, layers):
        """Ordena uma lista de camadas de baixo para cima conforme o painel / Order layers bottom-to-top as in the panel."""
        root = QgsProject.instance().layerTreeRoot()
        # layerOrder() devolve a ordem de cima para baixo / layerOrder() returns top-to-bottom order
        top_to_bottom_ids = [lyr.id() for lyr in root.layerOrder()]
        layer_id_set = {lyr.id() for lyr in layers}
        # Filtra mantendo a ordem do painel, depois inverte para baixo→cima
        # Filter keeping panel order, then reverse for bottom→top
        ordered = [lid for lid in top_to_bottom_ids if lid in layer_id_set]
        ordered.reverse()
        return ordered
