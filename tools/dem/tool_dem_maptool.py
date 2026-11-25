# -*- coding: utf-8 -*-
"""
Ferramenta de desenho de retângulo do RTH DEM Downloader
Rectangle drawing map tool for RTH DEM Downloader

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Módulo Qt para cores / Qt module for colors
from qgis.PyQt.QtGui import QColor
# Módulo Qt para sinais / Qt module for signals
from qgis.PyQt.QtCore import pyqtSignal

# Ferramenta de mapa base do QGIS / QGIS base map tool
from qgis.gui import QgsMapTool, QgsRubberBand
# Tipos de geometria e ponto / Geometry types and point
from qgis.core import QgsPointXY, QgsWkbTypes, QgsRectangle


class RectangleMapTool(QgsMapTool):
    """
    Ferramenta interativa para desenhar um retângulo no canvas do mapa.
    Interactive tool to draw a rectangle on the map canvas.

    Uso / Usage:
        tool = RectangleMapTool(canvas)
        tool.rectangleDrawn.connect(callback)
        canvas.setMapTool(tool)
    """

    # Emitido com o QgsRectangle quando o usuário solta o botão do mouse / Emitted with QgsRectangle on mouse release
    rectangleDrawn = pyqtSignal(object)

    def __init__(self, canvas):
        """Inicializa a ferramenta e a rubber band / Initialize the tool and rubber band."""
        super().__init__(canvas)
        # Referência ao canvas / Canvas reference
        self._canvas = canvas
        # Ponto onde o clique foi iniciado / Point where the click started
        self._start_point = None
        # Indica se o usuário está arrastando / Indicates if user is dragging
        self._drawing = False

        # Banda de borracha poligonal para exibir o retângulo / Polygon rubber band to display the rectangle
        self._rubber_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        # Preenchimento azul semitransparente / Semi-transparent blue fill
        self._rubber_band.setColor(QColor(0, 120, 255, 50))
        # Contorno azul escuro / Dark blue outline
        self._rubber_band.setStrokeColor(QColor(0, 80, 200, 200))
        # Espessura da borda / Border thickness
        self._rubber_band.setWidth(2)

    def canvasPressEvent(self, event):
        """Registra o ponto inicial ao pressionar o botão / Record start point on button press."""
        # Converte o ponto do canvas para coordenadas do mapa / Convert canvas point to map coordinates
        self._start_point = self.toMapCoordinates(event.pos())
        self._drawing = True
        # Limpa qualquer retângulo anterior / Clear any previous rectangle
        self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)

    def canvasMoveEvent(self, event):
        """Atualiza o retângulo visual enquanto arrasta / Update visual rectangle while dragging."""
        if not self._drawing or self._start_point is None:
            return

        # Posição atual do cursor no mapa / Current cursor position in map coordinates
        current = self.toMapCoordinates(event.pos())

        # Reconstrói os 4 vértices do retângulo / Rebuild the 4 rectangle vertices
        self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self._rubber_band.addPoint(QgsPointXY(self._start_point.x(), self._start_point.y()))
        self._rubber_band.addPoint(QgsPointXY(current.x(),            self._start_point.y()))
        self._rubber_band.addPoint(QgsPointXY(current.x(),            current.y()))
        self._rubber_band.addPoint(QgsPointXY(self._start_point.x(),  current.y()))
        # Fecha o polígono repetindo o primeiro ponto / Close the polygon by repeating the first point
        self._rubber_band.addPoint(QgsPointXY(self._start_point.x(), self._start_point.y()))

    def canvasReleaseEvent(self, event):
        """Finaliza o desenho e emite o retângulo / Finish drawing and emit the rectangle."""
        if not self._drawing or self._start_point is None:
            return

        self._drawing = False
        # Ponto final do retângulo / Rectangle end point
        end_point = self.toMapCoordinates(event.pos())
        # Cria o QgsRectangle com os dois pontos / Create QgsRectangle with the two points
        rect = QgsRectangle(self._start_point, end_point)

        # Remove a rubber band e desativa a ferramenta / Remove rubber band and deactivate tool
        self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self._canvas.unsetMapTool(self)

        # Emite o retângulo para o slot conectado / Emit rectangle to connected slot
        self.rectangleDrawn.emit(rect)

    def deactivate(self):
        """Limpa a rubber band ao desativar / Clean rubber band on deactivation."""
        self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        super().deactivate()
