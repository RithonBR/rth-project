# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QDoubleSpinBox, QFrame,
    QApplication
)
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsGeometry, QgsFeature, QgsField, QgsEditFormConfig
)
from core.rth_layer_utils import collapse_layer


# ──────────────────────────────────────────────────────────────────────────────
# Geometria
# ──────────────────────────────────────────────────────────────────────────────

def _build_carreador(poly_geom, line_geom, width_m, layer_crs, ctx):
    """
    line_geom is already in layer_crs.
    Returns (field_geom, strip_geom) both in layer_crs.
    """
    if layer_crs.isGeographic():
        try:
            from core.rth_utm_utils import detect_regional_utm
            c = poly_geom.centroid().asPoint()
            wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
            if layer_crs.authid() != 'EPSG:4326':
                t0 = QgsCoordinateTransform(layer_crs, wgs84, ctx)
                c = t0.transform(c)
            epsg, *_ = detect_regional_utm(c.x(), c.y())
            metric_crs = QgsCoordinateReferenceSystem('EPSG:{}'.format(epsg))
        except Exception:
            metric_crs = QgsCoordinateReferenceSystem('EPSG:3857')
    else:
        metric_crs = layer_crs

    to_metric = QgsCoordinateTransform(layer_crs, metric_crs, ctx)
    to_layer  = QgsCoordinateTransform(metric_crs, layer_crs, ctx)

    poly_m = QgsGeometry(poly_geom)
    poly_m.transform(to_metric)
    line_m = QgsGeometry(line_geom)
    line_m.transform(to_metric)

    buf_m = line_m.buffer(width_m / 2.0, 32)

    strip_m = buf_m.intersection(poly_m)
    if strip_m is None or strip_m.isNull():
        raise RuntimeError(
            'A linha nao intersecta o poligono / '
            'The line does not intersect the polygon')

    field_m = poly_m.difference(strip_m)
    if field_m is None or field_m.isNull():
        raise RuntimeError(
            'O buffer cobre todo o poligono — reduza a largura / '
            'Buffer covers the entire polygon — reduce the width')

    strip_m.transform(to_layer)
    field_m.transform(to_layer)
    return field_m, strip_m


def _add_memory_layer(name, geom, crs, color_hex=None):
    layer = QgsVectorLayer('Polygon?crs={}'.format(crs.authid()), name, 'memory')
    provider = layer.dataProvider()
    provider.addAttributes([QgsField('nome', QVariant.String)])
    layer.updateFields()
    feat = QgsFeature(layer.fields())
    feat.setGeometry(geom)
    feat.setAttribute('nome', name)
    provider.addFeature(feat)
    layer.updateExtents()
    if color_hex:
        try:
            sym = layer.renderer().symbol()
            sym.setColor(QColor(color_hex))
            sym.symbolLayer(0).setStrokeColor(QColor('#333333'))
        except Exception:
            pass
    QgsProject.instance().addMapLayer(layer)
    collapse_layer(layer)
    return layer


# ──────────────────────────────────────────────────────────────────────────────
# Diálogo
# ──────────────────────────────────────────────────────────────────────────────

_INSTRUCTIONS = (
    '1. Desenhe a linha sobre o poligono usando as ferramentas nativas do QGIS\n'
    '2. Clique com botao DIREITO para finalizar o tracado\n'
    '3. O botao Aplicar sera habilitado automaticamente\n'
    '4. Ajuste a largura e clique Aplicar\n'
    '\n'
    '1. Draw the line over the polygon using native QGIS tools\n'
    '2. Right-click to finish the line\n'
    '3. Apply button enables automatically\n'
    '4. Adjust width and click Apply'
)


class CarreadorDialog(QDialog):
    """
    Fases / Phases:
      'idle'    → seleciona camada, clica Iniciar
      'drawing' → camada temporária ativa, usuário digitaliza
    """

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface       = iface
        self._temp_layer = None
        self._build_ui()
        self._populate_layers()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle('RTH Criacao de Carreadores')
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint |
            Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint
        )
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(12, 12, 12, 12)
        self._root = root

        lbl_title = QLabel('Criacao de Carreadores')
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold;')
        root.addWidget(lbl_title)

        lbl_sub = QLabel('Defina a faixa de manobra no poligono selecionado / '
                         'Define headland strip on the selected polygon')
        lbl_sub.setAlignment(Qt.AlignCenter)
        lbl_sub.setStyleSheet('color:#666; font-size:10px;')
        lbl_sub.setWordWrap(True)
        root.addWidget(lbl_sub)

        self._sep()

        # ── Camada ────────────────────────────────────────────────────────────
        lbl_layer = QLabel('Camada Poligono / Polygon Layer')
        lbl_layer.setStyleSheet('font-weight:bold;')
        root.addWidget(lbl_layer)

        layer_row = QHBoxLayout()
        self.combo_layer = QComboBox()
        layer_row.addWidget(self.combo_layer)
        btn_refresh = QPushButton('↺')
        btn_refresh.setFixedWidth(32)
        btn_refresh.setToolTip('Atualizar lista de camadas / Refresh layer list')
        btn_refresh.clicked.connect(self._populate_layers)
        layer_row.addWidget(btn_refresh)
        root.addLayout(layer_row)

        self.lbl_hint = QLabel(
            '⚠  Selecione uma feicao na camada ANTES de iniciar o desenho\n'
            '⚠  Select a feature in the layer BEFORE starting the drawing')
        self.lbl_hint.setStyleSheet('color:#b71c1c; font-size:9px; font-weight:bold;')
        self.lbl_hint.setWordWrap(True)
        root.addWidget(self.lbl_hint)

        self._sep()

        # ── Instruções (visível na fase drawing) ──────────────────────────────
        self.widget_instr = QLabel(_INSTRUCTIONS)
        self.widget_instr.setAlignment(Qt.AlignLeft)
        self.widget_instr.setStyleSheet(
            'background:#fff8e1; border:1px solid #ffe082; '
            'border-radius:4px; padding:8px; color:#5d4037; font-size:10px;')
        self.widget_instr.setWordWrap(True)
        self.widget_instr.setVisible(False)
        root.addWidget(self.widget_instr)

        # ── Largura (visível na fase drawing) ─────────────────────────────────
        self.widget_width_label = QLabel('Largura do Carreador / Headland Width')
        self.widget_width_label.setStyleSheet('font-weight:bold;')
        self.widget_width_label.setVisible(False)
        root.addWidget(self.widget_width_label)

        width_row = QHBoxLayout()
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(1.0, 500.0)
        self.spin_width.setValue(15.0)
        self.spin_width.setDecimals(1)
        self.spin_width.setSingleStep(1.0)
        self.spin_width.setSuffix('  m')
        self.spin_width.setToolTip(
            'Largura total — a linha traçada fica no centro / '
            'Total width — the drawn line is at the center')
        width_row.addWidget(self.spin_width)
        width_row.addStretch()
        self._width_row_widget = QFrame()
        self._width_row_widget.setLayout(width_row)
        self._width_row_widget.setVisible(False)
        root.addWidget(self._width_row_widget)

        width_hint = QLabel(
            'A linha tracada fica no centro da faixa (largura/2 para cada lado) / '
            'The drawn line is at the strip center (width/2 on each side)')
        width_hint.setStyleSheet('color:#888; font-size:9px;')
        width_hint.setWordWrap(True)
        self._width_hint = width_hint
        self._width_hint.setVisible(False)
        root.addWidget(width_hint)

        self._sep()

        # ── Status ────────────────────────────────────────────────────────────
        self.lbl_status = QLabel(
            '1. Selecione a feicao na camada\n'
            '2. Clique em Iniciar Desenho')
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet('font-size:10px; color:#444;')
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        # ── Botão Iniciar (fase idle) ─────────────────────────────────────────
        self.btn_start = QPushButton('Iniciar Desenho / Start Drawing')
        self.btn_start.setMinimumHeight(40)
        self.btn_start.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;'
            'font-size:13px;border-radius:5px;}'
            'QPushButton:hover{background:#1558b0;}'
        )
        self.btn_start.clicked.connect(self._on_start)
        root.addWidget(self.btn_start)

        # ── Aplicar + Cancelar (fase drawing) ────────────────────────────────
        draw_row = QHBoxLayout()
        draw_row.setSpacing(8)

        self.btn_apply = QPushButton('Aplicar / Apply')
        self.btn_apply.setMinimumHeight(40)
        self.btn_apply.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;'
            'font-size:13px;border-radius:5px;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_apply.setEnabled(False)
        draw_row.addWidget(self.btn_apply)

        self.btn_cancel_draw = QPushButton('Cancelar / Cancel')
        self.btn_cancel_draw.setMinimumHeight(40)
        self.btn_cancel_draw.setStyleSheet(
            'QPushButton{background:#fff;color:#d32f2f;font-weight:bold;'
            'font-size:12px;border:2px solid #d32f2f;border-radius:5px;}'
            'QPushButton:hover{background:#fdecea;}'
        )
        self.btn_cancel_draw.clicked.connect(self._on_cancel_draw)
        draw_row.addWidget(self.btn_cancel_draw)

        self._draw_row_widget = QFrame()
        self._draw_row_widget.setLayout(draw_row)
        self._draw_row_widget.setVisible(False)
        root.addWidget(self._draw_row_widget)

    def _sep(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self._root.addWidget(line)

    # ── Camadas ───────────────────────────────────────────────────────────────

    def _populate_layers(self):
        prev_id = self.combo_layer.currentData()
        self.combo_layer.clear()
        active = self.iface.activeLayer()
        active_id = active.id() if isinstance(active, QgsVectorLayer) else None
        best_idx = 0
        for i, layer in enumerate(QgsProject.instance().mapLayers().values()):
            if not isinstance(layer, QgsVectorLayer):
                continue
            if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
                continue
            self.combo_layer.addItem(layer.name(), layer.id())
            if layer.id() == (prev_id or active_id):
                best_idx = self.combo_layer.count() - 1
        if self.combo_layer.count() == 0:
            self.combo_layer.addItem('Nenhuma camada de poligono / No polygon layer', None)
        else:
            self.combo_layer.setCurrentIndex(best_idx)

    def _current_layer(self):
        layer_id = self.combo_layer.currentData()
        if not layer_id:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    # ── Fases ─────────────────────────────────────────────────────────────────

    def _set_phase(self, phase):
        is_idle    = phase == 'idle'
        is_drawing = phase == 'drawing'

        self.combo_layer.setEnabled(is_idle)
        self.lbl_hint.setVisible(is_idle)
        self.btn_start.setVisible(is_idle)

        self.widget_instr.setVisible(is_drawing)
        self.widget_width_label.setVisible(is_drawing)
        self._width_row_widget.setVisible(is_drawing)
        self._width_hint.setVisible(is_drawing)
        self._draw_row_widget.setVisible(is_drawing)

        self.adjustSize()

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _on_start(self):
        layer = self._current_layer()
        if layer is None:
            self.iface.messageBar().pushMessage(
                'RTH Carreador',
                'Selecione uma camada de poligono / Select a polygon layer',
                level=Qgis.MessageLevel.Warning, duration=4)
            return

        if not layer.selectedFeatures():
            self.iface.messageBar().pushMessage(
                'RTH Carreador',
                'Selecione ao menos uma feicao na camada antes de iniciar / '
                'Select at least one feature in the layer before starting',
                level=Qgis.MessageLevel.Warning, duration=5)
            return

        # Limpa sessão anterior se existir
        self._cleanup_temp_layer(commit=False)

        # Cria camada temporária de linha no mesmo CRS do polígono
        crs_str = layer.crs().authid()
        self._temp_layer = QgsVectorLayer(
            'LineString?crs={}'.format(crs_str),
            '__rth_carreador_linha__', 'memory')

        # Suprime o formulário de atributos para não aparecer ao finalizar
        try:
            cfg = self._temp_layer.editFormConfig()
            try:
                cfg.setSuppress(QgsEditFormConfig.FeatureFormSuppress.SuppressOn)
            except AttributeError:
                cfg.setSuppress(QgsEditFormConfig.SuppressOn)
            self._temp_layer.setEditFormConfig(cfg)
        except Exception:
            pass

        QgsProject.instance().addMapLayer(self._temp_layer)
        collapse_layer(self._temp_layer)

        # Habilita Aplicar automaticamente quando o usuário finaliza a linha
        self._temp_layer.featureAdded.connect(self._on_feature_added)

        self.iface.setActiveLayer(self._temp_layer)
        self._temp_layer.startEditing()
        self.iface.actionAddFeature().trigger()

        self._set_phase('drawing')
        self.btn_apply.setEnabled(False)
        self.lbl_status.setText(
            'Desenhe a linha e clique direito para finalizar / '
            'Draw the line and right-click to finish')
        self.showMinimized()

    def _on_feature_added(self, fid):
        """Disparado quando o usuário finaliza a linha (botão direito)."""
        self.btn_apply.setEnabled(True)
        self.lbl_status.setText(
            'Linha pronta! Ajuste a largura e clique Aplicar / '
            'Line ready! Adjust width and click Apply')
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_cancel_draw(self):
        self._cleanup_temp_layer(commit=False)
        self._set_phase('idle')
        self.lbl_status.setText('Desenho cancelado / Drawing cancelled')
        self.showNormal()
        self.raise_()

    def _cleanup_temp_layer(self, commit=False):
        if self._temp_layer is None:
            return
        try:
            if commit:
                self._temp_layer.commitChanges()
            else:
                self._temp_layer.rollBack()
        except Exception:
            pass
        try:
            QgsProject.instance().removeMapLayer(self._temp_layer.id())
        except Exception:
            pass
        self._temp_layer = None

    def _on_apply(self):
        if self._temp_layer is None:
            return

        # Garante que os dados estão no provider antes de ler
        try:
            self._temp_layer.commitChanges()
        except Exception:
            pass

        features = list(self._temp_layer.getFeatures())
        if not features:
            self.iface.messageBar().pushMessage(
                'RTH Carreador',
                'Nenhuma linha desenhada / No line drawn',
                level=Qgis.MessageLevel.Warning, duration=4)
            return

        # Usa a última linha desenhada
        line_geom = features[-1].geometry()

        layer = self._current_layer()
        if layer is None:
            self._cleanup_temp_layer()
            self._set_phase('idle')
            return

        features_poly = layer.selectedFeatures()
        if not features_poly:
            self.iface.messageBar().pushMessage(
                'RTH Carreador',
                'Nenhuma feicao selecionada na camada / '
                'No feature selected in the layer',
                level=Qgis.MessageLevel.Warning, duration=5)
            self._cleanup_temp_layer()
            self._set_phase('idle')
            return

        self.btn_apply.setEnabled(False)
        self.lbl_status.setText('Calculando... / Calculating...')
        QApplication.processEvents()

        layer_crs = layer.crs()
        width_m   = self.spin_width.value()
        ctx       = QgsProject.instance().transformContext()
        base_name = layer.name()

        errors      = []
        strips      = []
        fields_list = []

        for feat in features_poly:
            poly_geom = feat.geometry()
            if poly_geom is None or poly_geom.isNull():
                continue
            try:
                field_geom, strip_geom = _build_carreador(
                    poly_geom, line_geom, width_m, layer_crs, ctx)
                fields_list.append(field_geom)
                strips.append(strip_geom)
            except Exception as exc:
                errors.append(str(exc))

        self._cleanup_temp_layer()

        if not fields_list:
            msg = errors[0] if errors else 'Erro desconhecido / Unknown error'
            self.iface.messageBar().pushMessage(
                'RTH Carreador', msg,
                level=Qgis.MessageLevel.Critical, duration=6)
            self._set_phase('idle')
            self.btn_apply.setEnabled(True)
            return

        def _merge(geoms):
            if len(geoms) == 1:
                return geoms[0]
            g = geoms[0]
            for other in geoms[1:]:
                g = g.combine(other)
            return g

        _add_memory_layer(
            'Carreador - {}'.format(base_name),
            _merge(strips), layer_crs, '#BF8B2E')
        _add_memory_layer(
            'Campo sem Carreador - {}'.format(base_name),
            _merge(fields_list), layer_crs, '#4CAF50')

        n = len(fields_list)
        self.iface.messageBar().pushMessage(
            'RTH Carreador',
            '{} carreador(es) criado(s) com {:.1f} m / '
            '{} headland(s) created with {:.1f} m'.format(n, width_m, n, width_m),
            level=Qgis.MessageLevel.Success, duration=6)

        if errors:
            self.iface.messageBar().pushMessage(
                'RTH Carreador',
                '{} feicao(oes) com erro / {} feature(s) with error'.format(
                    len(errors), len(errors)),
                level=Qgis.MessageLevel.Warning, duration=5)

        self._set_phase('idle')
        self.lbl_status.setText(
            'Concluido! Camadas adicionadas ao projeto / '
            'Done! Layers added to the project')
        self.btn_apply.setEnabled(True)
        self.showNormal()
        self.raise_()

    def closeEvent(self, event):
        self._cleanup_temp_layer(commit=False)
        super().closeEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# Tool class
# ──────────────────────────────────────────────────────────────────────────────

class CarreadorTool:

    def __init__(self, iface):
        self.iface = iface
        self._dlg  = None

    def run(self):
        if self._dlg is None or not self._dlg.isVisible():
            self._dlg = CarreadorDialog(
                self.iface, parent=self.iface.mainWindow())
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
