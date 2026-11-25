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

from qgis.core import Qgis, QgsProject


class LayerCyclerTool:
    """Alterna a visibilidade de camadas selecionadas uma de cada vez / Cycles selected layer visibility one at a time."""

    def __init__(self, iface):
        # Armazena a interface QGIS / Store QGIS interface
        self.iface = iface
        # IDs das camadas bloqueadas no ciclo atual / IDs of layers locked in the current cycle
        self._locked_ids = []
        # Índice da camada atualmente visível; None = ciclo não iniciado / Currently visible layer index; None = cycle not started
        self._index = None

    # ------------------------------------------------------------------
    # API pública / Public API
    # ------------------------------------------------------------------

    def cycle(self):
        """Avança para a próxima camada do ciclo / Advance to the next layer in the cycle."""
        self._step(+1)

    def cycle_back(self):
        """Retrocede para a camada anterior do ciclo / Go back to the previous layer in the cycle."""
        self._step(-1)

    def reset(self):
        """Reseta o ciclo e restaura a visibilidade de todas as camadas / Reset cycle and restore all layers visibility."""
        root = QgsProject.instance().layerTreeRoot()
        for lid in self._locked_ids:
            node = root.findLayer(lid)
            if node is not None:
                node.setItemVisibilityChecked(True)
        self._locked_ids = []
        self._index = None
        self.iface.messageBar().pushMessage(
            'RTH Layer Cycler',
            'Ciclo reiniciado — todas as camadas restauradas / Cycle reset — all layers restored',
            level=Qgis.MessageLevel.Info, duration=3)

    # ------------------------------------------------------------------
    # Lógica interna / Internal logic
    # ------------------------------------------------------------------

    def _step(self, direction):
        """Move o ciclo um passo na direção indicada (+1 = próxima, -1 = anterior) / Step the cycle one position (+1 = next, -1 = previous)."""
        selected = self.iface.layerTreeView().selectedLayers()
        selected_ids = {lyr.id() for lyr in selected}

        # Se 2+ camadas selecionadas diferem do ciclo atual, reinicia / If 2+ selected layers differ, restart cycle
        if len(selected) >= 2 and selected_ids != set(self._locked_ids):
            self._locked_ids = self._order_bottom_to_top(selected)
            self._index = None

        # Sem camadas bloqueadas — pede seleção / No locked layers — request selection
        if not self._locked_ids:
            self.iface.messageBar().pushMessage(
                'RTH Layer Cycler',
                'Selecione 2 ou mais camadas no painel / Select 2 or more layers in the panel',
                level=Qgis.MessageLevel.Warning, duration=4)
            return

        n = len(self._locked_ids)

        if self._index is None:
            # Primeiro passo: frente começa no índice 0, trás começa no último / First step: forward starts at 0, backward starts at last
            self._index = 0 if direction > 0 else n - 1
        else:
            self._index = (self._index + direction) % n

        # Aplica visibilidade: somente a camada atual fica visível / Apply visibility: only current layer stays visible
        root = QgsProject.instance().layerTreeRoot()
        for i, lid in enumerate(self._locked_ids):
            node = root.findLayer(lid)
            if node is not None:
                node.setItemVisibilityChecked(i == self._index)

        # Exibe feedback na barra de mensagens / Show feedback in the message bar
        current = QgsProject.instance().mapLayer(self._locked_ids[self._index])
        if current:
            arrow = '▶' if direction > 0 else '◀'
            self.iface.messageBar().pushMessage(
                'RTH Layer Cycler',
                f'{arrow} {current.name()}  ({self._index + 1} / {n})',
                level=Qgis.MessageLevel.Info, duration=2)

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
