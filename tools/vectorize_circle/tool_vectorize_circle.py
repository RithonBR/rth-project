# -*- coding: utf-8 -*-
"""
Ferramenta Vetorizar Círculo — desenha pivôs de irrigação como círculos suaves
Vectorize Circle Tool — draw irrigation pivots as smooth, lightweight circles

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QCursor
from qgis.core import (
    Qgis,
    QgsWkbTypes,
    QgsGeometry,
    QgsPointXY,
    QgsFeature,
    QgsVectorLayer,
    QgsProject,
    QgsCoordinateTransform,
)
from qgis.gui import QgsMapTool, QgsRubberBand

# 36 segmentos por quadrante = 144 vértices totais
# Círculo suave sem sobrecarregar a camada
# 36 segments per quadrant = 144 total vertices — smooth circle, not heavy
_SEGMENTS = 36


class VectorizeCircleTool(QgsMapTool):
    """Clique no centro, mova para expandir, clique de novo para finalizar o círculo.
    Clique direito cancela. O círculo é adicionado à camada polígono editável ativa
    ou a uma nova camada 'Círculo'.

    Click centre, move to expand, click again to finish.
    Right-click cancels. The circle is added to the active editable polygon layer
    or a new 'Pivôs de Irrigação' layer.
    """

    def __init__(self, iface):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self._center = None
        self._rubber_band = None

    def run(self):
        """Ativa a ferramenta no canvas / Activate the tool on the canvas."""
        self.iface.mapCanvas().setMapTool(self)

    def activate(self):
        """Chamado pelo QGIS ao setar esta ferramenta / Called by QGIS when tool becomes active."""
        self._center = None
        self.iface.mapCanvas().setCursor(QCursor(Qt.CrossCursor))
        if self._rubber_band is None:
            self._rubber_band = QgsRubberBand(
                self.iface.mapCanvas(), QgsWkbTypes.PolygonGeometry)
        self._rubber_band.setColor(QColor(255, 120, 0, 220))
        self._rubber_band.setFillColor(QColor(255, 120, 0, 35))
        self._rubber_band.setWidth(2)
        self.iface.messageBar().pushMessage(
            'Vetorizar Círculo',
            '1º clique: centro do pivô. Mova para expandir. 2º clique: finalizar. '
            'Clique direito: cancelar. / '
            '1st click: pivot centre. Move to expand. 2nd click: finish. Right-click: cancel.',
            level=Qgis.MessageLevel.Info, duration=7)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pt = self.toMapCoordinates(event.pos())
            if self._center is None:
                self._center = QgsPointXY(pt)
            else:
                r = self._center.distance(pt)
                if r > 0:
                    self._finalize(r)
        elif event.button() == Qt.RightButton:
            if self._center is not None:
                self._rubber_band.reset()
                self._center = None
            else:
                self.iface.mapCanvas().unsetMapTool(self)

    def canvasMoveEvent(self, event):
        if self._center is None or self._rubber_band is None:
            return
        pt = self.toMapCoordinates(event.pos())
        r = self._center.distance(pt)
        if r > 0:
            self._rubber_band.setToGeometry(
                QgsGeometry.fromPointXY(self._center).buffer(r, _SEGMENTS))

    def _finalize(self, radius_map):
        circle_geom = QgsGeometry.fromPointXY(self._center).buffer(radius_map, _SEGMENTS)

        layer = self.iface.activeLayer()
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

        if (layer is not None
                and isinstance(layer, QgsVectorLayer)
                and layer.geometryType() == QgsWkbTypes.PolygonGeometry
                and layer.isEditable()):
            geom = circle_geom
            if canvas_crs != layer.crs():
                geom_copy = QgsGeometry(geom)
                xf = QgsCoordinateTransform(canvas_crs, layer.crs(), QgsProject.instance())
                geom_copy.transform(xf)
                geom = geom_copy
            feat = QgsFeature(layer.fields())
            feat.setGeometry(geom)
            layer.addFeature(feat)
            layer.triggerRepaint()
            dest = layer.name()
        else:
            mem_lyr = QgsVectorLayer(
                'Polygon?crs={}'.format(canvas_crs.authid()),
                u'Círculo / Circle', 'memory')
            mem_lyr.startEditing()
            feat = QgsFeature(mem_lyr.fields())
            feat.setGeometry(circle_geom)
            mem_lyr.addFeature(feat)
            mem_lyr.commitChanges()
            QgsProject.instance().addMapLayer(mem_lyr)
            dest = u'Círculo / Circle'

        self.iface.messageBar().pushMessage(
            u'Vetorizar Círculo / Vectorize Circle',
            u'Círculo adicionado / Circle added — {}'.format(dest),
            level=Qgis.MessageLevel.Success, duration=4)

        self._rubber_band.reset()
        self._center = None
        self.iface.mapCanvas().unsetMapTool(self)

    def deactivate(self):
        if self._rubber_band:
            self._rubber_band.reset()
        self._center = None
        super().deactivate()
