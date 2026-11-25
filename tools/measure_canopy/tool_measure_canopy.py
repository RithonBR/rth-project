# -*- coding: utf-8 -*-
"""
Ferramenta Medir Copa das Árvores — mede o diâmetro e raio da copa
Measure Tree Canopy Tool — measures canopy diameter and radius interactively

Mostra o diâmetro acima do círculo e o raio abaixo enquanto o usuário arrasta.
Ao finalizar, cria uma camada vetorial com o círculo e os atributos diametro_m e raio_m.

Shows diameter above the circle and radius below while the user drags.
On finish, creates a vector layer with the circle and diametro_m / raio_m attributes.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

import math

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QCursor, QFont
from qgis.PyQt.QtWidgets import QLabel
from qgis.core import (
    Qgis,
    QgsWkbTypes,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsDistanceArea,
    QgsVectorLayer,
    QgsFeature,
    QgsFillSymbol,
    QgsSingleSymbolRenderer,
    QgsPalLayerSettings,
    QgsRuleBasedLabeling,
    QgsTextFormat,
    QgsTextBufferSettings,
)
from qgis.gui import QgsMapTool, QgsRubberBand

# Qt5 (QGIS 3) usa Qt.WA_TransparentForMouseEvents
# Qt6 (QGIS 4) moveu para Qt.WidgetAttribute.WA_TransparentForMouseEvents
try:
    _WA_TRANSPARENT = Qt.WidgetAttribute.WA_TransparentForMouseEvents  # Qt6/QGIS4
except AttributeError:
    _WA_TRANSPARENT = Qt.WA_TransparentForMouseEvents  # Qt5/QGIS3


class MeasureCanopyTool(QgsMapTool):
    """Clique no centro da árvore, mova até a borda da copa e clique de novo.
    Mostra diâmetro acima e raio abaixo do círculo em tempo real.
    Ao finalizar, cria camada vetorial com o círculo e atributos diametro_m e raio_m.

    Click tree centre, drag to canopy edge, click again.
    Shows diameter above and radius below in real-time.
    On finish creates a vector layer with circle geometry and diametro_m / raio_m fields.
    """

    def __init__(self, iface):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self._center = None
        self._rubber_band = None
        self._lbl_diameter = None
        self._lbl_radius = None

    def run(self):
        """Ativa a ferramenta no canvas / Activate the tool on the canvas."""
        self.iface.mapCanvas().setMapTool(self)

    def activate(self):
        """Chamado pelo QGIS ao setar esta ferramenta / Called by QGIS when tool becomes active."""
        self._center = None
        canvas = self.iface.mapCanvas()
        canvas.setCursor(QCursor(Qt.CrossCursor))

        if self._rubber_band is None:
            self._rubber_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self._rubber_band.setColor(QColor(0, 180, 255, 220))
        self._rubber_band.setFillColor(QColor(0, 180, 255, 30))
        self._rubber_band.setWidth(2)

        self._ensure_labels()

        self.iface.messageBar().pushMessage(
            u'Medir Copa / Measure Canopy',
            u'1º clique: centro da árvore. 2º clique: borda da copa. Direito: cancelar. / '
            u'1st click: tree centre. 2nd click: canopy edge. Right-click: cancel.',
            level=Qgis.MessageLevel.Info, duration=7)

    def _ensure_labels(self):
        """Cria os labels flutuantes sobre o canvas / Create floating labels over canvas."""
        canvas = self.iface.mapCanvas()
        if self._lbl_diameter is None:
            self._lbl_diameter = QLabel(canvas)
            self._lbl_diameter.setStyleSheet(
                'QLabel{background:rgba(10,10,10,190);color:#ffffff;'
                'border-radius:4px;padding:3px 10px;font-weight:bold;font-size:11px;}')
            self._lbl_diameter.setAttribute(_WA_TRANSPARENT, True)
        if self._lbl_radius is None:
            self._lbl_radius = QLabel(canvas)
            self._lbl_radius.setStyleSheet(
                'QLabel{background:rgba(10,10,10,140);color:#cccccc;'
                'border-radius:4px;padding:2px 8px;font-size:10px;}')
            self._lbl_radius.setAttribute(_WA_TRANSPARENT, True)
        self._lbl_diameter.hide()
        self._lbl_radius.hide()

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pt = self.toMapCoordinates(event.pos())
            if self._center is None:
                self._center = QgsPointXY(pt)
            else:
                r = self._center.distance(pt)
                if r > 0:
                    self._finalize(QgsPointXY(pt))
        elif event.button() == Qt.RightButton:
            self._cancel()

    def canvasMoveEvent(self, event):
        if self._center is None:
            return
        pt = self.toMapCoordinates(event.pos())
        r_map = self._center.distance(pt)
        if r_map <= 0:
            return

        if self._rubber_band:
            self._rubber_band.setToGeometry(
                QgsGeometry.fromPointXY(self._center).buffer(r_map, 36))

        dist_m = self._measure_m(self._center, QgsPointXY(pt))

        m2p = self.iface.mapCanvas().getCoordinateTransform()
        center_px = m2p.transform(self._center)
        cursor_px = event.pos()

        cx = int(center_px.x())
        cy = int(center_px.y())
        sr = int(math.sqrt(
            (cursor_px.x() - center_px.x()) ** 2 +
            (cursor_px.y() - center_px.y()) ** 2
        ))

        self._place_label(
            self._lbl_diameter,
            u'Ø {:.2f} m'.format(dist_m * 2),
            cx, cy - sr, above=True)
        self._place_label(
            self._lbl_radius,
            u'r = {:.2f} m'.format(dist_m),
            cx, cy + sr, above=False)

    def _place_label(self, lbl, text, cx, cy, above):
        """Posiciona o label centralizado horizontalmente /
        Position label centred horizontally."""
        lbl.setText(text)
        lbl.adjustSize()
        canvas = self.iface.mapCanvas()
        x = cx - lbl.width() // 2
        y = (cy - lbl.height() - 5) if above else (cy + 5)
        x = max(2, min(x, canvas.width()  - lbl.width()  - 2))
        y = max(2, min(y, canvas.height() - lbl.height() - 2))
        lbl.move(x, y)
        lbl.show()
        lbl.raise_()

    def _measure_m(self, center, pt):
        """Distância em metros entre dois pontos no CRS do canvas /
        Distance in metres between two canvas-CRS points."""
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        da = QgsDistanceArea()
        da.setSourceCrs(canvas_crs, QgsProject.instance().transformContext())
        da.setEllipsoid('WGS84')
        return da.measureLength(QgsGeometry.fromPolylineXY([center, pt]))

    def _finalize(self, edge_pt):
        radius_map = self._center.distance(edge_pt)
        dist_m     = self._measure_m(self._center, edge_pt)
        diam_m     = dist_m * 2

        # Círculo com 36 segmentos por quadrante = 144 vértices
        circle_geom = QgsGeometry.fromPointXY(self._center).buffer(radius_map, 36)

        # Cria camada de memória com os atributos de medição
        # Create memory layer with measurement attributes
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        uri = u'Polygon?crs={}&field=diametro_m:double&field=raio_m:double'.format(
            canvas_crs.authid())
        lyr = QgsVectorLayer(uri, u'Medição de Copa / Canopy Measurement', 'memory')

        lyr.startEditing()
        feat = QgsFeature(lyr.fields())
        feat.setGeometry(circle_geom)
        feat.setAttribute('diametro_m', round(diam_m, 4))
        feat.setAttribute('raio_m',     round(dist_m, 4))
        lyr.addFeature(feat)
        lyr.commitChanges()

        # Estilo: somente contorno laranja, sem preenchimento — igual ao Medir Distância
        # Style: orange stroke only, no fill — same orange as Measure Distance
        sym = QgsFillSymbol.createSimple({
            'color':         '0,0,0,0',
            'outline_color': '255,80,0,220',
            'outline_width': '0.8',
            'style':         'no',
        })
        lyr.setRenderer(QgsSingleSymbolRenderer(sym))

        QgsProject.instance().addMapLayer(lyr)
        self._setup_labels(lyr)

        self.iface.messageBar().pushMessage(
            u'Medir Copa / Measure Canopy',
            u'Ø {:.2f} m  |  r {:.2f} m — camada criada / layer created'.format(diam_m, dist_m),
            level=Qgis.MessageLevel.Success, duration=6)

        self._cleanup()
        self.iface.mapCanvas().unsetMapTool(self)

    def _setup_labels(self, lyr):
        """Rótulos por regras na camada do círculo:
        — Diâmetro (Ø) acima via geometry generator em y_max + QuadrantAbove
        — Raio (r) abaixo via geometry generator em y_min + QuadrantBelow
        Texto escuro com buffer branco de 1 mm.

        Rule-based labels on the circle layer:
        — Diameter (Ø) above via geometry generator at y_max + QuadrantAbove
        — Radius (r) below via geometry generator at y_min + QuadrantBelow
        Dark text with 1 mm white buffer.
        """
        def _fmt():
            tf = QgsTextFormat()
            f = QFont('Arial', 10)
            f.setBold(True)
            tf.setFont(f)
            tf.setColor(QColor('#1a1a1a'))
            buf = QgsTextBufferSettings()
            buf.setEnabled(True)
            buf.setSize(1.0)
            buf.setColor(QColor('#ffffff'))
            tf.setBuffer(buf)
            return tf

        def _placement():
            try:
                return QgsPalLayerSettings.Placement.OverPoint  # QGIS 4
            except AttributeError:
                return QgsPalLayerSettings.OverPoint             # QGIS 3

        def _quadrant(above):
            try:
                # QGIS 4 — enum aninhado
                q = QgsPalLayerSettings.QuadrantPosition
                return q.QuadrantAbove if above else q.QuadrantBelow
            except AttributeError:
                # QGIS 3 — enum plano
                return (QgsPalLayerSettings.QuadrantAbove if above
                        else QgsPalLayerSettings.QuadrantBelow)

        def _make_rule(expr, geom_expr, above):
            pal = QgsPalLayerSettings()
            pal.fieldName          = expr
            pal.isExpression       = True
            pal.placement          = _placement()
            pal.quadrantPosition   = _quadrant(above)
            # Geometry generator: ponto no topo ou fundo do círculo
            # Geometry generator: point at top or bottom of circle
            pal.geometryGenerator        = geom_expr
            pal.geometryGeneratorEnabled = True
            pal.geometryGeneratorType    = QgsWkbTypes.PointGeometry
            pal.setFormat(_fmt())
            rule = QgsRuleBasedLabeling.Rule(pal)
            rule.setActive(True)
            return rule

        root = QgsRuleBasedLabeling.Rule(QgsPalLayerSettings())
        root.setActive(True)

        # Diâmetro acima — âncora no ponto mais alto do círculo
        root.appendChild(_make_rule(
            u"concat('Ø : ', format_number(\"diametro_m\", 2), ' m')",
            "make_point(x(centroid($geometry)), y_max($geometry))",
            above=True,
        ))

        # Raio abaixo — âncora no ponto mais baixo do círculo
        root.appendChild(_make_rule(
            u"concat('r : ', format_number(\"raio_m\", 2), ' m')",
            "make_point(x(centroid($geometry)), y_min($geometry))",
            above=False,
        ))

        lyr.setLabeling(QgsRuleBasedLabeling(root))
        lyr.setLabelsEnabled(True)

    def keyPressEvent(self, event):
        """Cancela a ferramenta ao pressionar ESC / Cancel tool on ESC key."""
        if event.key() == Qt.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(event)

    def _cancel(self):
        self._cleanup()
        self.iface.mapCanvas().unsetMapTool(self)

    def _cleanup(self):
        if self._rubber_band:
            self._rubber_band.reset()
        if self._lbl_diameter:
            self._lbl_diameter.hide()
        if self._lbl_radius:
            self._lbl_radius.hide()
        self._center = None

    def deactivate(self):
        self._cleanup()
        super().deactivate()
