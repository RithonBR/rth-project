# -*- coding: utf-8 -*-
"""
rth_aoi_maptool — Ferramenta de mapa para desenhar retângulo de AOI
rth_aoi_maptool — Map tool for drawing an AOI rectangle

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.core import (
    QgsRectangle, QgsCoordinateTransform,
    QgsCoordinateReferenceSystem, QgsProject, QgsGeometry,
)
from qgis.gui import QgsMapTool, QgsRubberBand

try:
    _CROSS_CURSOR = Qt.CursorShape.CrossCursor
except AttributeError:
    _CROSS_CURSOR = Qt.CrossCursor

try:
    from qgis.core import QgsWkbTypes
    _POLY_GEOM = QgsWkbTypes.PolygonGeometry
except Exception:
    _POLY_GEOM = 2  # QgsWkbTypes.PolygonGeometry == 2


class AoiRectangleTool(QgsMapTool):
    """Ferramenta de mapa para desenhar um retângulo de AOI no canvas do QGIS /
    Map tool for drawing an AOI rectangle on the QGIS canvas.

    O usuário clica e arrasta para definir o retângulo. Ao soltar o mouse a
    ferramenta emite bbox_selected([minX, minY, maxX, maxY]) em WGS84,
    remove o rubber band e devolve o controle ao QGIS.

    The user clicks and drags to define the rectangle. On mouse release the
    tool emits bbox_selected([minX, minY, maxX, maxY]) in WGS84, removes
    the rubber band and returns control to QGIS.
    """

    bbox_selected = pyqtSignal(list)  # [minX, minY, maxX, maxY] WGS84

    def __init__(self, canvas):
        super().__init__(canvas)
        self._canvas   = canvas
        self._start_pt = None
        self._rb       = None

    def activate(self):
        self._canvas.setCursor(QCursor(_CROSS_CURSOR))
        self._start_pt = None
        if self._rb:
            self._rb.reset()
            self._rb = None

    def deactivate(self):
        if self._rb:
            self._rb.reset()
            self._rb = None
        super().deactivate()

    def canvasPressEvent(self, event):
        self._start_pt = self.toMapCoordinates(event.pos())
        if self._rb is None:
            self._rb = QgsRubberBand(self._canvas, _POLY_GEOM)
            self._rb.setColor(QColor(255, 165, 0, 80))
            self._rb.setStrokeColor(QColor(255, 165, 0, 200))
            self._rb.setWidth(2)

    def canvasMoveEvent(self, event):
        if self._start_pt is None or self._rb is None:
            return
        end  = self.toMapCoordinates(event.pos())
        rect = QgsRectangle(self._start_pt, end)
        self._rb.setToGeometry(QgsGeometry.fromRect(rect), None)

    def canvasReleaseEvent(self, event):
        if self._start_pt is None:
            return
        end  = self.toMapCoordinates(event.pos())
        rect = QgsRectangle(self._start_pt, end)

        # Transforma para WGS84 se o canvas estiver em outro CRS /
        # Transform to WGS84 if the canvas is in a different CRS
        src_crs = self._canvas.mapSettings().destinationCrs()
        wgs84   = QgsCoordinateReferenceSystem('EPSG:4326')
        if src_crs.authid() != 'EPSG:4326':
            try:
                xform = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
                rect  = xform.transformBoundingBox(rect)
            except Exception:
                pass

        bbox = [rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()]

        if self._rb:
            self._rb.reset()
            self._rb = None
        self._start_pt = None

        # Devolve controle ao QGIS antes de emitir o sinal /
        # Return control to QGIS before emitting signal
        self._canvas.unsetMapTool(self)
        self.bbox_selected.emit(bbox)
