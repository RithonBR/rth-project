# -*- coding: utf-8 -*-
"""
RTH Medir Distância — clique em 2 pontos no mapa e obtém a distância.

CRS/EPSG: usa QgsProject.instance().crs() como CRS-fonte das coordenadas clicadas
(= CRS do canvas, que é o CRS da área de interesse). QgsDistanceArea converte para
distância geodésica real sobre o elipsoide do projeto — resultado sempre em metros,
independente da projeção usada no canvas.

Após a medição:
  - Rubber band laranja + label branco abaixo da linha (canvas overlay temporário)
  - Camada vetorial de linha adicionada ao projeto com rótulo centralizado abaixo
"""
from qgis.PyQt.QtCore import QCoreApplication, QRectF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPen
from qgis.core import (
    Qgis,
    QgsDistanceArea, QgsFeature, QgsGeometry, QgsProject,
    QgsUnitTypes, QgsWkbTypes,
    QgsPalLayerSettings, QgsVectorLayer, QgsVectorLayerSimpleLabeling,
    QgsTextFormat, QgsTextBufferSettings,
    QgsLineSymbol, QgsSingleSymbolRenderer,
)
from qgis.gui import QgsMapTool, QgsRubberBand, QgsMapCanvasItem
from core.rth_layer_utils import collapse_layer


# ---------------------------------------------------------------------------
# Label canvas item — pill branco com borda laranja (overlay temporário)
# ---------------------------------------------------------------------------

class _DistanceLabelItem(QgsMapCanvasItem):
    """Desenha a etiqueta de distância centralizada abaixo da linha no canvas."""

    def __init__(self, canvas):
        super(_DistanceLabelItem, self).__init__(canvas)
        self._canvas = canvas  # guardado manualmente — canvas() não disponível via Python binding
        self._p1   = None
        self._p2   = None
        self._text = ''
        self.setZValue(100)

    def set_display(self, p1, p2, text):
        self._p1, self._p2, self._text = p1, p2, text
        self.update()

    def clear(self):
        self._p1 = self._p2 = None
        self._text = ''
        self.update()

    def boundingRect(self):
        c = self._canvas
        return QRectF(0, 0, c.width() if c else 9999, c.height() if c else 9999)

    def paint(self, painter, option=None, widget=None):
        if not self._p1 or not self._p2 or not self._text:
            return

        sp1   = self.toCanvasCoordinates(self._p1)
        sp2   = self.toCanvasCoordinates(self._p2)
        mid_x = (sp1.x() + sp2.x()) / 2.0
        mid_y = (sp1.y() + sp2.y()) / 2.0

        painter.save()
        painter.setRenderHint(painter.Antialiasing, True)

        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)

        fm      = painter.fontMetrics()
        tw      = fm.horizontalAdvance(self._text)
        th      = fm.height()
        px, py  = 10, 5
        bg_w    = tw + px * 2
        bg_h    = th + py * 2
        bg_x    = mid_x - bg_w / 2.0
        bg_y    = mid_y + 14   # 14 px abaixo do ponto médio

        painter.setBrush(QBrush(QColor(255, 255, 255, 230)))
        painter.setPen(QPen(QColor(255, 80, 0), 1.8))
        painter.drawRoundedRect(QRectF(bg_x, bg_y, bg_w, bg_h), 5, 5)

        painter.setPen(QPen(QColor(30, 30, 30)))
        painter.drawText(QRectF(bg_x, bg_y, bg_w, bg_h), Qt.AlignCenter, self._text)

        painter.restore()


# ---------------------------------------------------------------------------
# Map tool interno
# ---------------------------------------------------------------------------

class _MeasureMapTool(QgsMapTool):

    def __init__(self, canvas, iface, label_item, on_done):
        super(_MeasureMapTool, self).__init__(canvas)
        self.iface    = iface
        self._label   = label_item
        self._on_done = on_done
        self._points  = []

        self._rubber = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._rubber.setColor(QColor(255, 80, 0, 200))
        self._rubber.setWidth(2)

        self._dot_start = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        self._dot_start.setColor(QColor(255, 80, 0, 230))
        self._dot_start.setIcon(QgsRubberBand.ICON_CIRCLE)
        self._dot_start.setIconSize(10)

        self._dot_end = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        self._dot_end.setColor(QColor(255, 80, 0, 230))
        self._dot_end.setIcon(QgsRubberBand.ICON_CIRCLE)
        self._dot_end.setIconSize(10)

        self._da = QgsDistanceArea()

    def tr(self, msg):
        return QCoreApplication.translate('MeasureDistanceTool', msg)

    def _setup_da(self):
        """Configura QgsDistanceArea com o CRS do canvas (= EPSG da área de interesse)."""
        self._da.setSourceCrs(
            QgsProject.instance().crs(),
            QgsProject.instance().transformContext()
        )
        self._da.setEllipsoid(QgsProject.instance().ellipsoid())

    def _calc_dist(self, p1, p2):
        """Retorna (dist_m: float, dist_str: str) usando o elipsoide do projeto."""
        dist_m = self._da.convertLengthMeasurement(
            self._da.measureLine(p1, p2),
            QgsUnitTypes.DistanceMeters
        )
        if dist_m >= 1000:
            dist_str = u'{:.3f} km  ({:.1f} m)'.format(dist_m / 1000.0, dist_m)
        else:
            dist_str = u'{:.2f} m'.format(dist_m)
        return dist_m, dist_str

    # -- ativação ----------------------------------------------------------

    def activate(self):
        super(_MeasureMapTool, self).activate()
        self._points = []
        self._reset_graphics()
        self._setup_da()
        self.canvas().setCursor(Qt.CrossCursor)
        self.iface.messageBar().pushMessage(
            'RTH',
            self.tr(u'Clique no 1º ponto / Click the 1st point  |  Esc = cancelar'),
            level=Qgis.MessageLevel.Info, duration=0
        )

    def deactivate(self):
        self.canvas().unsetCursor()
        super(_MeasureMapTool, self).deactivate()

    # -- eventos -----------------------------------------------------------

    def canvasMoveEvent(self, event):
        if len(self._points) == 1:
            pt = self.toMapCoordinates(event.pos())
            self._rubber.reset(QgsWkbTypes.LineGeometry)
            self._rubber.addPoint(self._points[0], False)
            self._rubber.addPoint(pt, True)
            try:
                _, dist_str = self._calc_dist(self._points[0], pt)
                self._label.set_display(self._points[0], pt, dist_str)
            except Exception:
                pass

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        pt = self.toMapCoordinates(event.pos())
        self._points.append(pt)

        if len(self._points) == 1:
            self._dot_start.reset(QgsWkbTypes.PointGeometry)
            self._dot_start.addPoint(pt, True)
            self._rubber.reset(QgsWkbTypes.LineGeometry)
            self._rubber.addPoint(pt, True)
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Clique no 2º ponto / Click the 2nd point  |  Esc = cancelar'),
                level=Qgis.MessageLevel.Info, duration=0
            )

        elif len(self._points) == 2:
            self._dot_end.reset(QgsWkbTypes.PointGeometry)
            self._dot_end.addPoint(pt, True)
            self._rubber.reset(QgsWkbTypes.LineGeometry)
            self._rubber.addPoint(self._points[0], False)
            self._rubber.addPoint(pt, True)
            self._finish()
            self.canvas().unsetMapTool(self)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._reset_graphics()
            self._label.clear()
            self.iface.messageBar().clearWidgets()
            self.canvas().unsetMapTool(self)

    # -- lógica ------------------------------------------------------------

    def _finish(self):
        p1, p2 = self._points
        try:
            dist_m, dist_str = self._calc_dist(p1, p2)
        except Exception as e:
            dist_m, dist_str = 0.0, 'Erro: {0}'.format(e)

        # Camada vetorial permanente com rótulo
        self._create_result_layer(p1, p2, dist_m, dist_str)

        # Remove todos os gráficos temporários — a layer já tem linha + rótulo
        self._reset_graphics()
        self._label.clear()

        self.iface.messageBar().pushMessage(
            'RTH',
            self.tr(u'Distância / Distance: {0}  (CRS: {1})').format(
                dist_str, QgsProject.instance().crs().authid()),
            level=Qgis.MessageLevel.Info, duration=8
        )
        self._on_done()

    def _create_result_layer(self, p1, p2, dist_m, dist_str):
        """Cria camada vetorial de linha com rótulo de distância centralizado abaixo."""
        crs_id = QgsProject.instance().crs().authid()

        lyr = QgsVectorLayer(
            'LineString?crs={0}&field=distancia_m:double&field=distancia:string(80)'.format(crs_id),
            'RTH Medição — {0}'.format(dist_str),
            'memory'
        )

        # Feição / Feature
        feat = QgsFeature(lyr.fields())
        feat.setGeometry(QgsGeometry.fromPolylineXY([p1, p2]))
        feat['distancia_m'] = dist_m
        feat['distancia']   = dist_str
        lyr.dataProvider().addFeature(feat)
        lyr.updateExtents()

        # Estilo: linha laranja / Style: orange line
        sym = QgsLineSymbol.createSimple({
            'color':      '255,80,0,200',
            'width':      '0.8',
            'line_style': 'solid',
        })
        lyr.setRenderer(QgsSingleSymbolRenderer(sym))

        # Rótulo centralizado abaixo da linha / Label centered below the line
        pal = QgsPalLayerSettings()
        pal.fieldName = 'distancia'
        pal.placement = QgsPalLayerSettings.Line

        # Abaixo da linha via QgsLabelLineSettings (QGIS 3.16+)
        try:
            from qgis.core import QgsLabelLineSettings, QgsLabeling
            ls = QgsLabelLineSettings()
            ls.setPlacementFlags(
                QgsLabeling.LinePlacementFlags(
                    QgsLabeling.BelowLine | QgsLabeling.MapOrientation
                )
            )
            pal.setLineSettings(ls)
        except Exception:
            pass   # fallback: label over line (still centered)

        # Formato de texto / Text format
        tf = QgsTextFormat()
        f  = QFont()
        f.setPointSize(9)
        f.setBold(True)
        tf.setFont(f)
        tf.setSize(9)
        tf.setColor(QColor(30, 30, 30))

        buf = QgsTextBufferSettings()
        buf.setEnabled(True)
        buf.setSize(1.0)
        buf.setColor(QColor(255, 255, 255))
        tf.setBuffer(buf)

        pal.setFormat(tf)

        lyr.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        lyr.setLabelsEnabled(True)

        QgsProject.instance().addMapLayer(lyr)
        collapse_layer(lyr)

    def _reset_graphics(self):
        self._rubber.reset(QgsWkbTypes.LineGeometry)
        self._dot_start.reset(QgsWkbTypes.PointGeometry)
        self._dot_end.reset(QgsWkbTypes.PointGeometry)

    def clear(self):
        self._reset_graphics()


# ---------------------------------------------------------------------------
# Classe pública
# ---------------------------------------------------------------------------

class MeasureDistanceTool:
    """Ativa o map tool de medição de distância entre 2 pontos / Activates the 2-point distance measurement map tool."""

    def __init__(self, iface):
        self.iface      = iface
        self._map_tool  = None
        self._prev_tool = None
        self._label     = None   # criado uma vez, reutilizado entre medições

    def run(self):
        canvas = self.iface.mapCanvas()

        if self._label is None:
            self._label = _DistanceLabelItem(canvas)
        else:
            self._label.clear()

        if self._map_tool is not None:
            self._map_tool.clear()

        self._prev_tool = canvas.mapTool()
        self._map_tool  = _MeasureMapTool(canvas, self.iface, self._label, self._on_done)
        canvas.setMapTool(self._map_tool)

    def _on_done(self):
        if self._prev_tool is not None:
            self.iface.mapCanvas().setMapTool(self._prev_tool)
            self._prev_tool = None
