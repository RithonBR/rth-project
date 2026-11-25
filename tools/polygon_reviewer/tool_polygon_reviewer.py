# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QFont, QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QProgressBar, QApplication
)
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateTransform, QgsField, QgsGeometry
)


REVISION_FIELD = 'Revision'
VALUE_YES = 'Yes'
VALUE_NO  = 'No'


# ──────────────────────────────────────────────────────────────────────────────
# Spatial ordering — greedy nearest-neighbor by centroid
# ──────────────────────────────────────────────────────────────────────────────

def _dist2(p1, p2):
    dx = p1.x() - p2.x()
    dy = p1.y() - p2.y()
    return dx * dx + dy * dy


def _spatial_order(features):
    """
    Returns a list of features sorted so that spatially adjacent features
    are consecutive — greedy nearest-neighbor starting from westernmost.
    """
    valid = [
        (f, f.geometry().centroid().asPoint())
        for f in features
        if f.geometry() and not f.geometry().isNull()
    ]
    if not valid:
        return [f for f, _ in valid]

    # Start from the westernmost centroid (smallest X) for a predictable entry
    valid.sort(key=lambda item: item[1].x())
    ordered = []
    remaining = list(valid)
    current = remaining.pop(0)
    ordered.append(current[0])

    while remaining:
        curr_pt = current[1]
        nearest_i = min(range(len(remaining)),
                        key=lambda i: _dist2(curr_pt, remaining[i][1]))
        current = remaining.pop(nearest_i)
        ordered.append(current[0])

    return ordered


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _is_null(val):
    """True for None, empty string, or PyQt QVariant null."""
    if val is None:
        return True
    try:
        from qgis.PyQt.QtCore import QVariant as _QV
        if isinstance(val, _QV) and val.isNull():
            return True
    except Exception:  # nosec B110
        pass
    return str(val).strip() == ''


def _update_attr(layer, feat_id, field_idx, value):
    """Write a single attribute value, respecting existing edit sessions."""
    was_editing = layer.isEditable()
    if not was_editing:
        layer.startEditing()
    layer.changeAttributeValue(feat_id, field_idx, value)
    if not was_editing:
        layer.commitChanges()


# ──────────────────────────────────────────────────────────────────────────────
# Dialog
# ──────────────────────────────────────────────────────────────────────────────

class PolygonReviewerDialog(QDialog):
    """
    Navegador de feições com zoom automático e rastreamento de revisão.
    Feature navigator with automatic zoom and revision tracking.

    Permance não-modal (show) para o usuário interagir com o canvas.
    Stays non-modal (show) so the user can interact with the canvas.
    """

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface   = iface
        self._layer  = None
        self._feats  = []
        self._idx    = 0
        self._rev_fi = -1
        self._visited = set()   # feature IDs already marked Yes
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle('RTH Revisor de Polígonos / Polygon Reviewer')
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint |
            Qt.WindowStaysOnTopHint
        )
        self.setMinimumWidth(340)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(12, 12, 12, 12)
        self._root = root

        # ── Cabeçalho ─────────────────────────────────────────────────────────
        lbl_title = QLabel('Revisor de Poligonos / Polygon Reviewer')
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold;')
        root.addWidget(lbl_title)

        self.lbl_layer = QLabel('—')
        self.lbl_layer.setAlignment(Qt.AlignCenter)
        self.lbl_layer.setStyleSheet('color:#666; font-size:10px;')
        self.lbl_layer.setWordWrap(True)
        root.addWidget(self.lbl_layer)

        self._sep()

        # ── Posição atual / Current position ──────────────────────────────────
        pos_font = QFont()
        pos_font.setPointSize(22)
        pos_font.setBold(True)

        self.lbl_position = QLabel('— / —')
        self.lbl_position.setFont(pos_font)
        self.lbl_position.setAlignment(Qt.AlignCenter)
        root.addWidget(self.lbl_position)

        self.lbl_fid = QLabel('')
        self.lbl_fid.setAlignment(Qt.AlignCenter)
        self.lbl_fid.setStyleSheet('color:#555; font-size:10px;')
        root.addWidget(self.lbl_fid)

        self.lbl_revision = QLabel('')
        self.lbl_revision.setAlignment(Qt.AlignCenter)
        self.lbl_revision.setStyleSheet('font-size:11px; font-weight:bold;')
        root.addWidget(self.lbl_revision)

        self._sep()

        # ── Progresso / Progress ──────────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setFormat('{} visitados / visited'.format(0))
        self.progress.setAlignment(Qt.AlignCenter)
        root.addWidget(self.progress)

        self._sep()

        # ── Navegação / Navigation ────────────────────────────────────────────
        nav_row = QHBoxLayout()
        nav_row.setSpacing(8)

        self.btn_prev = QPushButton('◀  Anterior / Previous')
        self.btn_prev.setMinimumHeight(48)
        self.btn_prev.setStyleSheet(
            'QPushButton{background:#fff;color:#1a73e8;font-weight:bold;'
            'font-size:13px;border:2px solid #1a73e8;border-radius:6px;}'
            'QPushButton:hover{background:#e8f0fe;}'
            'QPushButton:disabled{color:#bbb;border-color:#ddd;background:#fafafa;}'
        )
        self.btn_prev.clicked.connect(self._on_prev)
        nav_row.addWidget(self.btn_prev)

        self.btn_next = QPushButton('Próxima / Next  ▶')
        self.btn_next.setMinimumHeight(48)
        self.btn_next.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;'
            'font-size:13px;border-radius:6px;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        self.btn_next.clicked.connect(self._on_next)
        nav_row.addWidget(self.btn_next)

        root.addLayout(nav_row)

        # ── Encerrar ──────────────────────────────────────────────────────────
        self.btn_close = QPushButton('Encerrar / Close')
        self.btn_close.setMinimumHeight(32)
        self.btn_close.setStyleSheet(
            'QPushButton{background:#fff;color:#666;font-size:10px;'
            'border:1px solid #ccc;border-radius:5px;}'
            'QPushButton:hover{background:#f0f0f0;}'
        )
        self.btn_close.clicked.connect(self.close)
        root.addWidget(self.btn_close)

    def _sep(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self._root.addWidget(line)

    # ── Inicialização de sessão / Session init ────────────────────────────────

    def start(self, layer, features):
        """Inicia uma nova sessão de revisão / Start a new review session."""
        self._layer   = layer
        self._idx     = 0
        self._visited = set()

        # Preserve spatial order from the original selection IDs
        feat_ids = [f.id() for f in features
                    if f.geometry() and not f.geometry().isNull()]

        # 1. Garante o campo ANTES de recarregar as feições
        #    Ensures the field exists BEFORE re-fetching features
        self._rev_fi = self._ensure_revision_field()

        # 2. Recarrega as feições da camada para que contenham o novo campo
        #    Re-fetch features from the layer so they carry the new field schema
        fresh = [layer.getFeature(fid) for fid in feat_ids]
        self._feats = _spatial_order(fresh)

        self._init_revision_values()

        # Carrega IDs já revisados de sessões anteriores / Load previously reviewed IDs
        fi = self._rev_fi
        if fi >= 0:
            for feat in self._feats:
                val = feat.attribute(fi)   # use index — always safe
                if not _is_null(val) and str(val) == VALUE_YES:
                    self._visited.add(feat.id())

        n = len(self._feats)
        self.lbl_layer.setText(
            '{}\n{} feições selecionadas / features selected'.format(
                layer.name(), n))
        self.progress.setMaximum(n)
        self._goto(0)

    # ── Campo Revision / Revision field ──────────────────────────────────────

    def _ensure_revision_field(self):
        layer = self._layer
        fi = layer.fields().indexOf(REVISION_FIELD)
        if fi >= 0:
            return fi
        was_editing = layer.isEditable()
        if not was_editing:
            layer.startEditing()
        layer.addAttribute(QgsField(REVISION_FIELD, QVariant.String))
        if not was_editing:
            layer.commitChanges()
        return layer.fields().indexOf(REVISION_FIELD)

    def _init_revision_values(self):
        """Define 'No' para feições sem valor no campo Revision."""
        fi = self._rev_fi
        if fi < 0:
            return
        layer = self._layer
        was_editing = layer.isEditable()
        if not was_editing:
            layer.startEditing()
        for feat in self._feats:
            # Use field index (not name) — safe for both new and existing fields
            val = feat.attribute(fi)
            if _is_null(val):
                layer.changeAttributeValue(feat.id(), fi, VALUE_NO)
        if not was_editing:
            layer.commitChanges()

    def _mark_yes(self, feat_id):
        fi = self._rev_fi
        if fi < 0 or feat_id in self._visited:
            return
        _update_attr(self._layer, feat_id, fi, VALUE_YES)
        self._visited.add(feat_id)

    # ── Navegação / Navigation ────────────────────────────────────────────────

    def _goto(self, idx):
        self._idx = idx
        feat = self._feats[idx]
        self._zoom_to(feat)
        self._mark_yes(feat.id())
        self._update_ui()

    def _on_next(self):
        if self._idx < len(self._feats) - 1:
            self._goto(self._idx + 1)

    def _on_prev(self):
        if self._idx > 0:
            self._goto(self._idx - 1)

    def _zoom_to(self, feat):
        canvas = self.iface.mapCanvas()
        layer_crs  = self._layer.crs()
        canvas_crs = canvas.mapSettings().destinationCrs()

        extent = feat.geometry().boundingBox()
        if layer_crs.authid() != canvas_crs.authid():
            t = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
            extent = t.transformBoundingBox(extent)

        # Padding so the polygon doesn't fill the entire canvas
        extent.scale(2.0)
        canvas.setExtent(extent)
        canvas.refresh()

        # Flash para destacar visualmente / Flash to visually highlight
        try:
            canvas.flashFeatureIds(
                self._layer, [feat.id()],
                QColor('#1a73e8'), QColor(255, 255, 255, 0),
                flashes=2, duration=500)
        except Exception:  # nosec B110
            pass

    # ── Atualização da UI / UI update ─────────────────────────────────────────

    def _update_ui(self):
        n   = len(self._feats)
        idx = self._idx
        feat = self._feats[idx]

        self.lbl_position.setText('{} / {}'.format(idx + 1, n))
        self.lbl_fid.setText('FID: {}'.format(feat.id()))

        visited = len(self._visited)

        if feat.id() in self._visited:
            self.lbl_revision.setText('Revision:  Yes  — visitada / visited')
            self.lbl_revision.setStyleSheet(
                'font-size:11px; font-weight:bold; color:#2e7d32;')
        else:
            self.lbl_revision.setText('Revision:  No  — nao visitada / not visited')
            self.lbl_revision.setStyleSheet(
                'font-size:11px; font-weight:bold; color:#c62828;')

        self.progress.setValue(visited)
        self.progress.setFormat(
            '{}/{} visitados / visited'.format(visited, n))

        self.btn_prev.setEnabled(idx > 0)
        self.btn_next.setEnabled(idx < n - 1)

        # Destaca a feição na tabela de atributos / Highlight in attribute table
        try:
            self._layer.selectByIds([feat.id()])
        except Exception:  # nosec B110
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Tool class
# ──────────────────────────────────────────────────────────────────────────────

class PolygonReviewerTool:

    def __init__(self, iface):
        self.iface = iface
        self._dlg  = None

    def run(self):
        # ── Validações / Validations ──────────────────────────────────────────
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            self.iface.messageBar().pushMessage(
                'RTH Revisor',
                'Ative uma camada vetorial de poligono / '
                'Activate a polygon vector layer',
                level=Qgis.MessageLevel.Warning, duration=5)
            return

        if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
            self.iface.messageBar().pushMessage(
                'RTH Revisor',
                'A camada ativa nao e de poligono / '
                'The active layer is not a polygon layer',
                level=Qgis.MessageLevel.Warning, duration=5)
            return

        selected = layer.selectedFeatures()
        if not selected:
            self.iface.messageBar().pushMessage(
                'RTH Revisor',
                'Selecione ao menos um poligono na camada ativa / '
                'Select at least one polygon in the active layer',
                level=Qgis.MessageLevel.Warning, duration=5)
            return

        # ── Cria / reutiliza diálogo ──────────────────────────────────────────
        if self._dlg is None:
            self._dlg = PolygonReviewerDialog(
                self.iface, parent=self.iface.mainWindow())

        self._dlg.start(layer, selected)
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
