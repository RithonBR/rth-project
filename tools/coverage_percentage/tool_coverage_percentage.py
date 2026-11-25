# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QDoubleSpinBox,
    QFrame, QApplication
)
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsGeometry, QgsCoordinateTransform, QgsCoordinateReferenceSystem
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _detect_utm(geom, src_crs):
    """Detecta CRS UTM regional a partir do centróide de uma geometria.
    Detects regional UTM CRS from the centroid of a geometry."""
    try:
        from core.rth_utm_utils import detect_regional_utm
        centroid = geom.centroid().asPoint()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        if src_crs.authid() != 'EPSG:4326':
            t = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
            centroid = t.transform(centroid)
        epsg = detect_regional_utm(centroid.y(), centroid.x())
        crs = QgsCoordinateReferenceSystem('EPSG:{}'.format(epsg))
        if crs.isValid():
            return crs
    except Exception:  # nosec B110
        pass
    return QgsCoordinateReferenceSystem('EPSG:31982')


def _compute_coverage(point_layer, ref_layer, buffer_m):
    """
    Calcula a porcentagem de cobertura dos pontos (com buffer) sobre a referência.
    Computes the coverage percentage of buffered points over the reference polygon.

    Retorna (dict com resultados, None) ou (None, mensagem de erro).
    Returns (dict with results, None) or (None, error message string).
    """
    # ── 1. Geometria de referência (seleção ou tudo) ──────────────────────────
    selected = ref_layer.selectedFeatures()
    ref_feats = selected if selected else list(ref_layer.getFeatures())

    if not ref_feats:
        return None, ('Camada de referência sem feições. / '
                      'Reference layer has no features.')

    ref_geom = None
    for f in ref_feats:
        g = f.geometry()
        if g and not g.isNull():
            # makeValid() corrige auto-interseções que fazem combine() retornar geometria vazia.
            # makeValid() fixes self-intersections that cause combine() to return an empty geometry.
            g = g.makeValid()
            if not g or g.isEmpty():
                continue
            ref_geom = g if ref_geom is None else ref_geom.combine(g)

    if ref_geom is None or ref_geom.isEmpty():
        return None, ('Geometria de referência inválida — verifique se a camada tem feições válidas. / '
                      'Invalid reference geometry — check that the layer has valid features.')

    # ── 2. Pontos ─────────────────────────────────────────────────────────────
    pt_feats = [f for f in point_layer.getFeatures()
                if f.geometry() and not f.geometry().isNull()]

    if not pt_feats:
        return None, ('Camada de pontos sem feições. / '
                      'Point layer has no features.')

    # ── 3. UTM para cálculo em metros ─────────────────────────────────────────
    utm_crs = _detect_utm(ref_geom, ref_layer.crs())

    t_ref = QgsCoordinateTransform(ref_layer.crs(), utm_crs, QgsProject.instance())
    ref_geom_utm = QgsGeometry(ref_geom)
    ref_geom_utm.transform(t_ref)

    ref_area_m2 = ref_geom_utm.area()
    if ref_area_m2 <= 0:
        return None, ('Área de referência inválida (área zero). / '
                      'Invalid reference area (zero area).')

    # ── 4. Buffer de cada ponto e união ───────────────────────────────────────
    t_pt = QgsCoordinateTransform(point_layer.crs(), utm_crs, QgsProject.instance())
    buffer_union = None
    n_valid = 0

    for f in pt_feats:
        g = QgsGeometry(f.geometry())
        g.transform(t_pt)
        buf = g.buffer(buffer_m, 36)
        if buf and not buf.isEmpty():
            n_valid += 1
            buffer_union = buf if buffer_union is None else buffer_union.combine(buf)

    if buffer_union is None or buffer_union.isEmpty():
        return None, ('Nenhum buffer gerado. / No buffer generated.')

    # ── 5. Interseção e porcentagem ───────────────────────────────────────────
    intersection = buffer_union.intersection(ref_geom_utm)
    covered_m2 = 0.0 if (intersection is None or intersection.isEmpty()) else intersection.area()

    pct          = (covered_m2 / ref_area_m2) * 100.0
    ref_ha       = ref_area_m2 / 10000.0
    covered_ha   = covered_m2 / 10000.0
    used_sel     = bool(selected)

    return {
        'pct':        pct,
        'covered_ha': covered_ha,
        'ref_ha':     ref_ha,
        'n_points':   n_valid,
        'used_sel':   used_sel,
        'n_ref_feats': len(ref_feats),
    }, None


# ──────────────────────────────────────────────────────────────────────────────
# Dialog
# ──────────────────────────────────────────────────────────────────────────────

class CoveragePercentageDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle('RTH Porcentagem de Cobertura / Coverage Percentage')
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint |
            Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint
        )
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)
        self._root = root

        # ── Título ────────────────────────────────────────────────────────────
        lbl = QLabel('Porcentagem de Cobertura / Coverage Percentage')
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet('font-size:13px; font-weight:bold;')
        root.addWidget(lbl)

        self._sep()

        # ── Parâmetros ────────────────────────────────────────────────────────
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

        self._combo_points = QComboBox()
        self._combo_points.setMinimumHeight(28)
        form.addRow('Camada de Pontos / Point Layer:', self._combo_points)

        self._combo_ref = QComboBox()
        self._combo_ref.setMinimumHeight(28)
        form.addRow('Camada de Referência / Reference Layer:', self._combo_ref)

        self._spin_buffer = QDoubleSpinBox()
        self._spin_buffer.setMinimum(0.001)
        self._spin_buffer.setMaximum(500.0)
        self._spin_buffer.setValue(1.0)
        self._spin_buffer.setDecimals(3)
        self._spin_buffer.setSuffix('  km')
        self._spin_buffer.setMinimumHeight(28)
        form.addRow('Raio do Buffer / Buffer Radius:', self._spin_buffer)

        root.addLayout(form)

        self._sep()

        # ── Botão executar ────────────────────────────────────────────────────
        self._btn_run = QPushButton('▶  Calcular Cobertura / Calculate Coverage')
        self._btn_run.setMinimumHeight(42)
        self._btn_run.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;'
            'font-size:13px;border-radius:6px;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        self._btn_run.clicked.connect(self._on_run)
        root.addWidget(self._btn_run)

        self._sep()

        # ── Resultado em card escuro para legibilidade ─────────────────────────
        # Dark result card for readability in any QGIS theme
        result_card = QFrame()
        result_card.setStyleSheet(
            'QFrame{background:#2d2d2d;border-radius:8px;border:none;}')
        rc_layout = QVBoxLayout(result_card)
        rc_layout.setContentsMargins(14, 16, 14, 16)
        rc_layout.setSpacing(10)

        pct_font = QFont()
        pct_font.setPointSize(32)
        pct_font.setBold(True)

        self._lbl_pct = QLabel('—')
        self._lbl_pct.setFont(pct_font)
        self._lbl_pct.setAlignment(Qt.AlignCenter)
        self._lbl_pct.setStyleSheet('color:#64b5f6; background:transparent; border:none;')
        rc_layout.addWidget(self._lbl_pct)

        self._lbl_details = QLabel('')
        self._lbl_details.setAlignment(Qt.AlignCenter)
        self._lbl_details.setWordWrap(True)
        self._lbl_details.setStyleSheet(
            'font-size:12px; color:#e0e0e0; background:transparent; border:none;')
        rc_layout.addWidget(self._lbl_details)

        root.addWidget(result_card)

        self._lbl_status = QLabel('')
        self._lbl_status.setAlignment(Qt.AlignCenter)
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setStyleSheet('font-size:10px; color:#c62828;')
        root.addWidget(self._lbl_status)

    def _sep(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self._root.addWidget(line)

    # ── População das combos ──────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._populate_layers()

    def _populate_layers(self):
        self._combo_points.clear()
        self._combo_ref.clear()

        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            geom_type = QgsWkbTypes.geometryType(layer.wkbType())
            if geom_type == QgsWkbTypes.PointGeometry:
                self._combo_points.addItem(layer.name(), layer.id())
            elif geom_type == QgsWkbTypes.PolygonGeometry:
                self._combo_ref.addItem(layer.name(), layer.id())

    # ── Execução ──────────────────────────────────────────────────────────────

    def _on_run(self):
        self._lbl_pct.setText('—')
        self._lbl_details.setText('')
        self._lbl_status.setText('')

        pt_id  = self._combo_points.currentData()
        ref_id = self._combo_ref.currentData()

        if not pt_id:
            self._error('Nenhuma camada de pontos disponível. / No point layer available.')
            return
        if not ref_id:
            self._error('Nenhuma camada de referência disponível. / No reference layer available.')
            return

        pt_layer  = QgsProject.instance().mapLayer(pt_id)
        ref_layer = QgsProject.instance().mapLayer(ref_id)

        if not pt_layer or not ref_layer:
            self._error('Camada não encontrada. / Layer not found.')
            return

        buffer_m = self._spin_buffer.value() * 1000  # km → m

        self._btn_run.setEnabled(False)
        self._lbl_status.setStyleSheet('font-size:10px; color:#555;')
        self._lbl_status.setText('Calculando... / Calculating...')
        QApplication.processEvents()

        try:
            result, err = _compute_coverage(pt_layer, ref_layer, buffer_m)
        except Exception as e:
            self._btn_run.setEnabled(True)
            self._error('Erro: {} / Error: {}'.format(e, e))
            return

        self._btn_run.setEnabled(True)

        if err:
            self._error(err)
            return

        self._show_result(result, buffer_m)

    def _show_result(self, r, buffer_m):
        pct = r['pct']

        # Cores para fundo escuro: mais saturadas para destacar no card dark
        # Colors for dark card: more saturated to stand out on dark background
        if pct >= 80.0:
            color = '#66bb6a'   # verde claro / light green
        elif pct >= 50.0:
            color = '#ffa726'   # laranja / orange
        else:
            color = '#ef5350'   # vermelho / red

        self._lbl_pct.setStyleSheet(
            'color:{}; background:transparent; border:none;'.format(color))
        self._lbl_pct.setText('{:.1f}%'.format(pct))

        ref_label = (
            '{} feição selecionada / selected feature'.format(r['n_ref_feats'])
            if r['used_sel'] else
            '{} feição(ões) / feature(s)'.format(r['n_ref_feats'])
        )

        buffer_km = buffer_m / 1000.0
        details = (
            'Área coberta / Covered area: {:.2f} ha\n'
            'Área total / Total area: {:.2f} ha\n'
            'Pontos processados / Points processed: {}\n'
            'Buffer: {:.3f} km  |  Referência / Reference: {}'
        ).format(
            r['covered_ha'], r['ref_ha'],
            r['n_points'], buffer_km, ref_label
        )
        self._lbl_details.setStyleSheet(
            'font-size:12px; color:#e0e0e0; background:transparent; border:none;')
        self._lbl_details.setText(details)
        self._lbl_status.setText('')

    def _error(self, msg):
        self._lbl_status.setStyleSheet('font-size:10px; color:#c62828;')
        self._lbl_status.setText(msg)


# ──────────────────────────────────────────────────────────────────────────────
# Tool
# ──────────────────────────────────────────────────────────────────────────────

class CoveragePercentageTool:

    def __init__(self, iface):
        self.iface = iface
        self._dlg  = None

    def run(self):
        if self._dlg is None:
            self._dlg = CoveragePercentageDialog(
                self.iface, parent=self.iface.mainWindow())
        self._dlg._populate_layers()
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
