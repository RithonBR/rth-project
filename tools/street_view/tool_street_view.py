# -*- coding: utf-8 -*-
"""
tool_street_view.py

Ferramenta Street View — Funcionalidades Adicionais / Additional Tools

Duas funções independentes:
  1. add_coverage_layer() — adiciona a camada XYZ de cobertura do Street View
     (as linhas azuis do Google) como QgsRasterLayer WMS/XYZ.
  2. StreetViewGotoTool (QgsMapTool) — clique simples ou clique+arraste no canvas
     para abrir o Google Street View no navegador. O arraste define o heading
     (direção para onde a câmera aponta); clique simples usa heading 0 (Norte).

Two independent functions:
  1. add_coverage_layer() — adds the Street View coverage XYZ layer
     (Google's blue lines) as a QgsRasterLayer WMS/XYZ.
  2. StreetViewGotoTool (QgsMapTool) — simple click or click+drag on the canvas
     to open Google Street View in the browser. Dragging sets the heading
     (camera direction); simple click uses heading 0 (North).

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# GNU General Public License v3
"""

import math
import webbrowser

import sip

from qgis.core import (
    Qgis, QgsProject, QgsRasterLayer,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsPointXY, QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QCursor

# ── URL do tile de cobertura do Street View / Street View coverage tile URL ──
# IMPORTANTE: o '?' antes de 'lyrs' deve ser literal (não %3F) para o driver
# XYZ do QGIS montar o request corretamente.
_COVERAGE_URI = (
    'type=xyz'
    '&url=https://mts2.google.com/mapslt'
    '?lyrs%3Dsvv'
    '%26x%3D%7Bx%7D%26y%3D%7By%7D%26z%3D%7Bz%7D'
    '%26w%3D256%26h%3D256%26hl%3Den%26style%3D40,18'
    '&zmax=18&zmin=0'
    '&http-header:referer='
)
_COVERAGE_NAME = 'Street View Coverage'

# ── Cor do rubber band / Rubber band color ───────────────────────────────────
_RB_COLOR = QColor('#4285F4')   # azul Google / Google blue


def _open_streetview(canvas, iface, point_map, heading=0):
    """Converte ponto para WGS84 e abre o Street View no navegador."""
    try:
        src_crs  = canvas.mapSettings().destinationCrs()
        wgs84    = QgsCoordinateReferenceSystem(4326)
        xform    = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
        pt_wgs84 = xform.transform(point_map)
        url = (
            f'https://www.google.com/maps/@?api=1&map_action=pano'
            f'&viewpoint={pt_wgs84.y()},{pt_wgs84.x()}'
            f'&heading={int(heading)}&pitch=10&fov=250'
        )
        webbrowser.open_new(url)
    except Exception as ex:
        iface.messageBar().pushMessage(
            'RTH Street View',
            f'Erro ao abrir Street View / Failed to open Street View: {ex}',
            level=Qgis.MessageLevel.Critical, duration=5)


class StreetViewGotoTool(QgsMapTool):
    """
    MapTool para navegar ao Street View.
    - Clique simples: abre o Street View no ponto clicado (heading=0).
    - Clique + arrastar: define a direção (heading) antes de abrir.
    """

    def __init__(self, canvas, iface, action):
        super().__init__(canvas)
        self.canvas  = canvas
        self.iface   = iface
        self.action  = action
        self._pressed = False
        self._point0  = None
        self._point1  = None
        self._rb_line = None
        self._rb_arrow = None
        self.setCursor(Qt.CrossCursor)

    # ── Eventos do canvas / Canvas events ────────────────────────────────────
    def canvasPressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        x, y = event.pos().x(), event.pos().y()
        self._point0  = self.canvas.getCoordinateTransform().toMapCoordinates(x, y)
        self._point1  = None
        self._pressed = True
        self._clear_rubber()

    def canvasMoveEvent(self, event):
        if not self._pressed or self._point0 is None:
            return
        x, y = event.pos().x(), event.pos().y()
        self._point1 = self.canvas.getCoordinateTransform().toMapCoordinates(x, y)
        self._draw_direction(self._point0, self._point1)

    def canvasReleaseEvent(self, event):
        if not self._pressed:
            return
        self._pressed = False

        if self._point1 is None:
            x, y = event.pos().x(), event.pos().y()
            self._point1 = self.canvas.getCoordinateTransform().toMapCoordinates(x, y)

        heading = self._calc_heading(self._point0, self._point1)
        self._clear_rubber()
        _open_streetview(self.canvas, self.iface, self._point0, heading)

        # Desativa o tool após uso / Deactivate tool after use
        self.canvas.unsetMapTool(self)
        if self.action:
            self.action.setChecked(False)
        self.iface.actionSelect().trigger()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._clear_rubber()
            self._pressed = False
            self.canvas.unsetMapTool(self)
            if self.action:
                self.action.setChecked(False)
            self.iface.actionSelect().trigger()

    def deactivate(self):
        self._clear_rubber()
        self._pressed = False
        if self.action:
            self.action.setChecked(False)
        super().deactivate()

    # ── Helpers / Helpers ─────────────────────────────────────────────────────
    def _calc_heading(self, p0, p1):
        """Ângulo bússola 0–360 de p0 → p1 (Norte = 0, sentido horário)."""
        dx = p1.x() - p0.x()
        dy = p1.y() - p0.y()
        # atan2 geográfico: Norte = eixo Y positivo
        angle = math.degrees(math.atan2(dx, dy)) % 360.0
        return angle

    def _draw_direction(self, p0, p1):
        """Desenha linha + seta indicando a direção escolhida."""
        if self._rb_line is None:
            self._rb_line = QgsRubberBand(self.canvas, QgsWkbTypes.GeometryType.LineGeometry)
            self._rb_line.setColor(_RB_COLOR)
            self._rb_line.setWidth(2)
        self._rb_line.reset(QgsWkbTypes.LineGeometry)
        self._rb_line.addPoint(p0)
        self._rb_line.addPoint(p1)

        # Seta / Arrow head
        if self._rb_arrow is None:
            self._rb_arrow = QgsRubberBand(self.canvas, QgsWkbTypes.GeometryType.LineGeometry)
            self._rb_arrow.setColor(_RB_COLOR)
            self._rb_arrow.setWidth(2)
        self._rb_arrow.reset(QgsWkbTypes.LineGeometry)
        mpp = self.canvas.mapUnitsPerPixel()
        angle = math.atan2(p1.y() - p0.y(), p1.x() - p0.x())
        for side in (math.radians(150), -math.radians(150)):
            ax = p1.x() + 20 * mpp * math.cos(angle + side)
            ay = p1.y() + 20 * mpp * math.sin(angle + side)
            self._rb_arrow.addPoint(QgsPointXY(ax, ay))
            self._rb_arrow.addPoint(p1)

    def _clear_rubber(self):
        for attr in ('_rb_line', '_rb_arrow'):
            rb = getattr(self, attr, None)
            if rb is not None:
                rb.reset()
                setattr(self, attr, None)

    def isZoomTool(self):  return False
    def isTransient(self): return False
    def isEditTool(self):  return True


# ── Ferramenta principal / Main tool class ────────────────────────────────────
class StreetViewTool:
    """
    Gerencia a camada de cobertura e o MapTool de navegação ao Street View.
    Manages the coverage layer and the Street View navigation MapTool.
    """

    def __init__(self, iface):
        self.iface          = iface
        self._coverage_layer = None
        self._goto_tool      = None
        self._goto_action    = None   # setado pelo initGui do plugin / set by plugin initGui

    def set_goto_action(self, action):
        """Recebe a QAction do menu para controle do estado checked."""
        self._goto_action = action

    # ── Adicionar camada / Add coverage layer ────────────────────────────────
    def add_coverage_layer(self):
        """Adiciona a camada XYZ de cobertura do Street View ao projeto."""
        # Se a camada ainda existe no projeto, não adiciona de novo.
        # sip.isdeleted() detecta se o objeto C++ foi destruído (ex: usuário
        # deletou a camada pelo painel) sem gerar RuntimeError.
        if self._coverage_layer is not None:
            if sip.isdeleted(self._coverage_layer):
                self._coverage_layer = None  # ponteiro morto, reseta
            elif QgsProject.instance().mapLayer(self._coverage_layer.id()):
                self.iface.messageBar().pushMessage(
                    'RTH Street View',
                    'Camada de cobertura já adicionada. / Coverage layer already added.',
                    level=Qgis.MessageLevel.Info, duration=4)
                return

        rlayer = QgsRasterLayer(_COVERAGE_URI, _COVERAGE_NAME, 'wms')
        if not rlayer.isValid():
            self.iface.messageBar().pushMessage(
                'RTH Street View',
                'Não foi possível carregar a camada de cobertura. '
                'Verifique sua conexão com a internet. / '
                'Could not load coverage layer. Check your internet connection.',
                level=Qgis.MessageLevel.Critical, duration=6)
            return

        root = QgsProject.instance().layerTreeRoot()
        QgsProject.instance().addMapLayer(rlayer, False)
        root.insertLayer(0, rlayer)
        self._coverage_layer = rlayer

        self.iface.messageBar().pushMessage(
            'RTH Street View',
            'Camada de cobertura adicionada. As linhas azuis mostram onde o '
            'Street View está disponível. / '
            'Coverage layer added. Blue lines show where Street View is available.',
            level=Qgis.MessageLevel.Success, duration=6)

    # ── Ir para local / Go to location ───────────────────────────────────────
    def goto(self):
        """Ativa o MapTool de navegação. Clique simples ou arraste para definir heading."""
        canvas = self.iface.mapCanvas()
        if self._goto_tool is None:
            self._goto_tool = StreetViewGotoTool(canvas, self.iface, self._goto_action)
        canvas.setMapTool(self._goto_tool)
        if self._goto_action:
            self._goto_action.setChecked(True)
        self.iface.messageBar().pushMessage(
            'RTH Street View',
            'Dê zoom nas linhas AZUIS e clique sobre elas — '
            'o Google Maps busca o panorama mais próximo automaticamente. '
            'Arraste para definir a direção da câmera. / '
            'Zoom into the BLUE lines and click on them — '
            'Google Maps finds the nearest panorama automatically. '
            'Drag to set the camera direction.',
            level=Qgis.MessageLevel.Info, duration=10)
