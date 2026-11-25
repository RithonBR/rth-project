# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QFont, QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QProgressBar
)
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateTransform, QgsField, QgsPointXY,
    QgsRectangle
)


REVISAO_FIELD = 'revisao'
ACERTO_FIELD  = 'acerto'

VAL_REVISAO_SIM     = 'sim'
VAL_REVISAO_NAO     = 'Não'
VAL_ACERTO_ACERTOU  = 'acertou'
VAL_ACERTO_ERROU    = 'errou'
VAL_ACERTO_INDIF    = 'indiferente'

# Escala fixa de exibição em metros/unidade do canvas (1:2000)
_ZOOM_SCALE = 2000


# ──────────────────────────────────────────────────────────────────────────────
# Spatial ordering — greedy nearest-neighbor by point geometry
# ──────────────────────────────────────────────────────────────────────────────

def _dist2(p1, p2):
    dx = p1.x() - p2.x()
    dy = p1.y() - p2.y()
    return dx * dx + dy * dy


def _spatial_order(features):
    """Ordena feições de ponto pela vizinhança mais próxima (greedy NN).
    Sorts point features by greedy nearest-neighbor from westernmost point."""
    valid = []
    for f in features:
        if not f.geometry() or f.geometry().isNull():
            continue
        pt = f.geometry().asPoint()
        valid.append((f, pt))

    if not valid:
        return []

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
    if val is None:
        return True
    try:
        from qgis.PyQt.QtCore import QVariant as _QV
        if isinstance(val, _QV) and val.isNull():
            return True
    except Exception:
        pass
    return str(val).strip() == ''


def _update_attr(layer, feat_id, field_idx, value):
    was_editing = layer.isEditable()
    if not was_editing:
        layer.startEditing()
    layer.changeAttributeValue(feat_id, field_idx, value)
    if not was_editing:
        layer.commitChanges()


# ──────────────────────────────────────────────────────────────────────────────
# Dialog
# ──────────────────────────────────────────────────────────────────────────────

class PointReviewerDialog(QDialog):
    """
    Navegador de pontos com zoom automático, rastreamento de revisão e
    marcação de acerto. Não-modal para o usuário interagir com o canvas.

    Non-modal point navigator with auto-zoom, revisao tracking and
    acerto marking (acertou / errou / indiferente).
    """

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface   = iface
        self._layer  = None
        self._feats  = []
        self._idx    = 0
        self._rev_fi = -1   # field index — revisao
        self._ace_fi = -1   # field index — acerto
        self._visited = set()
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle('RTH Revisor de Pontos / Point Reviewer')
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint |
            Qt.WindowStaysOnTopHint
        )
        self.setMinimumWidth(360)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(12, 12, 12, 12)
        self._root = root

        # ── Cabeçalho ─────────────────────────────────────────────────────────
        lbl_title = QLabel('Revisor de Pontos / Point Reviewer')
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold;')
        root.addWidget(lbl_title)

        self.lbl_layer = QLabel('—')
        self.lbl_layer.setAlignment(Qt.AlignCenter)
        self.lbl_layer.setStyleSheet('color:#666; font-size:10px;')
        self.lbl_layer.setWordWrap(True)
        root.addWidget(self.lbl_layer)

        self._sep()

        # ── Posição / Position ────────────────────────────────────────────────
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

        # Revisão status
        self.lbl_revisao = QLabel('')
        self.lbl_revisao.setAlignment(Qt.AlignCenter)
        self.lbl_revisao.setStyleSheet('font-size:11px; font-weight:bold;')
        root.addWidget(self.lbl_revisao)

        # Acerto status
        self.lbl_acerto = QLabel('')
        self.lbl_acerto.setAlignment(Qt.AlignCenter)
        self.lbl_acerto.setStyleSheet('font-size:11px;')
        root.addWidget(self.lbl_acerto)

        self._sep()

        # ── Progresso / Progress ──────────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setFormat('0 visitados / visited')
        self.progress.setAlignment(Qt.AlignCenter)
        root.addWidget(self.progress)

        self._sep()

        # ── Botões de Acerto / Acerto buttons ────────────────────────────────
        acerto_row = QHBoxLayout()
        acerto_row.setSpacing(6)

        self.btn_acertou = QPushButton('Acertou / Correct')
        self.btn_acertou.setMinimumHeight(38)
        self.btn_acertou.setStyleSheet(
            'QPushButton{background:#2e7d32;color:white;font-weight:bold;'
            'font-size:12px;border-radius:6px;}'
            'QPushButton:hover{background:#1b5e20;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        self.btn_acertou.clicked.connect(lambda: self._on_acerto(VAL_ACERTO_ACERTOU))
        acerto_row.addWidget(self.btn_acertou)

        self.btn_errou = QPushButton('Errou / Wrong')
        self.btn_errou.setMinimumHeight(38)
        self.btn_errou.setStyleSheet(
            'QPushButton{background:#c62828;color:white;font-weight:bold;'
            'font-size:12px;border-radius:6px;}'
            'QPushButton:hover{background:#b71c1c;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        self.btn_errou.clicked.connect(lambda: self._on_acerto(VAL_ACERTO_ERROU))
        acerto_row.addWidget(self.btn_errou)

        self.btn_indif = QPushButton('Indiferente / Neutral')
        self.btn_indif.setMinimumHeight(38)
        self.btn_indif.setStyleSheet(
            'QPushButton{background:#e65100;color:white;font-weight:bold;'
            'font-size:12px;border-radius:6px;}'
            'QPushButton:hover{background:#bf360c;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        self.btn_indif.clicked.connect(lambda: self._on_acerto(VAL_ACERTO_INDIF))
        acerto_row.addWidget(self.btn_indif)

        root.addLayout(acerto_row)

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

        self.btn_next = QPushButton('Próximo / Next  ▶')
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

    def start(self, layer):
        """Inicia uma nova sessão de revisão com todas as feições da camada.
        Start a new review session with all features from the layer."""
        self._layer   = layer
        self._idx     = 0
        self._visited = set()

        # Garante campos ANTES de recarregar as feições
        # Ensures fields BEFORE re-fetching features
        self._rev_fi = self._ensure_field(REVISAO_FIELD)
        self._ace_fi = self._ensure_field(ACERTO_FIELD)

        all_feats = list(layer.getFeatures())
        fresh = [layer.getFeature(f.id()) for f in all_feats
                 if f.geometry() and not f.geometry().isNull()]
        self._feats = _spatial_order(fresh)

        self._init_field_values()

        # Carrega IDs já revisados de sessões anteriores
        # Loads already-reviewed IDs from prior sessions
        fi = self._rev_fi
        if fi >= 0:
            for feat in self._feats:
                val = feat.attribute(fi)
                if not _is_null(val) and str(val) == VAL_REVISAO_SIM:
                    self._visited.add(feat.id())

        n = len(self._feats)
        self.lbl_layer.setText(
            '{}\n{} pontos / points'.format(layer.name(), n))
        self.progress.setMaximum(n)
        if n > 0:
            self._goto(0)

    # ── Gerenciamento de campos / Field management ────────────────────────────

    def _ensure_field(self, field_name):
        """Garante que o campo existe na camada, criando-o se necessário.
        Ensures the field exists on the layer, creating it if needed."""
        layer = self._layer
        fi = layer.fields().indexOf(field_name)
        if fi >= 0:
            return fi
        was_editing = layer.isEditable()
        if not was_editing:
            layer.startEditing()
        layer.addAttribute(QgsField(field_name, QVariant.String))
        if not was_editing:
            layer.commitChanges()
        return layer.fields().indexOf(field_name)

    def _init_field_values(self):
        """Inicializa revisao='Não' e acerto='indiferente' onde estiverem nulos.
        Initialises revisao='Não' and acerto='indiferente' where null."""
        rev_fi = self._rev_fi
        ace_fi = self._ace_fi
        layer = self._layer

        was_editing = layer.isEditable()
        if not was_editing:
            layer.startEditing()

        for feat in self._feats:
            if rev_fi >= 0:
                val = feat.attribute(rev_fi)
                if _is_null(val):
                    layer.changeAttributeValue(feat.id(), rev_fi, VAL_REVISAO_NAO)
            if ace_fi >= 0:
                val = feat.attribute(ace_fi)
                if _is_null(val):
                    layer.changeAttributeValue(feat.id(), ace_fi, VAL_ACERTO_INDIF)

        if not was_editing:
            layer.commitChanges()

    def _mark_revisao_sim(self, feat_id):
        fi = self._rev_fi
        if fi < 0 or feat_id in self._visited:
            return
        _update_attr(self._layer, feat_id, fi, VAL_REVISAO_SIM)
        self._visited.add(feat_id)

    # ── Acerto ────────────────────────────────────────────────────────────────

    def _on_acerto(self, value):
        if not self._feats:
            return
        feat = self._feats[self._idx]
        fi = self._ace_fi
        if fi < 0:
            return
        _update_attr(self._layer, feat.id(), fi, value)
        self._update_ui()

    # ── Navegação / Navigation ────────────────────────────────────────────────

    def _goto(self, idx):
        self._idx = idx
        feat = self._feats[idx]
        self._zoom_to(feat)
        self._mark_revisao_sim(feat.id())
        self._update_ui()

    def _on_next(self):
        if self._idx < len(self._feats) - 1:
            self._goto(self._idx + 1)

    def _on_prev(self):
        if self._idx > 0:
            self._goto(self._idx - 1)

    def _zoom_to(self, feat):
        """Centraliza o canvas no ponto com escala fixa de 1:_ZOOM_SCALE.
        Centers the canvas on the point at fixed 1:_ZOOM_SCALE scale."""
        canvas = self.iface.mapCanvas()
        layer_crs  = self._layer.crs()
        canvas_crs = canvas.mapSettings().destinationCrs()

        pt = feat.geometry().asPoint()
        if layer_crs.authid() != canvas_crs.authid():
            t = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
            pt = t.transform(pt)

        # setCenter + zoomScale: o QGIS resolve internamente a conversão de escala
        # independente de o CRS ser geográfico (graus) ou projetado (metros).
        # setCenter + zoomScale: QGIS resolves scale conversion internally
        # regardless of whether the CRS is geographic (degrees) or projected (metres).
        canvas.setCenter(pt)
        canvas.zoomScale(_ZOOM_SCALE)
        canvas.refresh()

        try:
            canvas.flashFeatureIds(
                self._layer, [feat.id()],
                QColor('#1a73e8'), QColor(255, 255, 255, 0),
                flashes=2, duration=500)
        except Exception:
            pass

    # ── Atualização da UI / UI update ─────────────────────────────────────────

    def _update_ui(self):
        if not self._feats:
            return

        n    = len(self._feats)
        idx  = self._idx
        feat = self._feats[idx]

        self.lbl_position.setText('{} / {}'.format(idx + 1, n))
        self.lbl_fid.setText('FID: {}'.format(feat.id()))

        visited = len(self._visited)

        # Revisão
        if feat.id() in self._visited:
            self.lbl_revisao.setText('revisao: sim — visitado / visited')
            self.lbl_revisao.setStyleSheet(
                'font-size:11px; font-weight:bold; color:#2e7d32;')
        else:
            self.lbl_revisao.setText('revisao: Não — não visitado / not visited')
            self.lbl_revisao.setStyleSheet(
                'font-size:11px; font-weight:bold; color:#c62828;')

        # Acerto — lê o valor atual do layer (pode ter sido alterado pelo botão)
        # Reads current value from layer (may have been changed by the button)
        acerto_val = VAL_ACERTO_INDIF
        ace_fi = self._ace_fi
        if ace_fi >= 0:
            fresh_feat = self._layer.getFeature(feat.id())
            val = fresh_feat.attribute(ace_fi)
            if not _is_null(val):
                acerto_val = str(val)

        _acerto_colors = {
            VAL_ACERTO_ACERTOU: '#2e7d32',
            VAL_ACERTO_ERROU:   '#c62828',
            VAL_ACERTO_INDIF:   '#e65100',
        }
        color = _acerto_colors.get(acerto_val, '#555')
        self.lbl_acerto.setText('acerto: {}'.format(acerto_val))
        self.lbl_acerto.setStyleSheet(
            'font-size:11px; font-weight:bold; color:{};'.format(color))

        self.progress.setValue(visited)
        self.progress.setFormat(
            '{}/{} visitados / visited'.format(visited, n))

        self.btn_prev.setEnabled(idx > 0)
        self.btn_next.setEnabled(idx < n - 1)

        self.btn_acertou.setEnabled(True)
        self.btn_errou.setEnabled(True)
        self.btn_indif.setEnabled(True)

        try:
            self._layer.selectByIds([feat.id()])
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Tool
# ──────────────────────────────────────────────────────────────────────────────

class PointReviewerTool:

    def __init__(self, iface):
        self.iface = iface
        self._dlg  = None

    def run(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            self.iface.messageBar().pushMessage(
                'RTH Revisor',
                'Ative uma camada vetorial de pontos / '
                'Activate a point vector layer',
                level=Qgis.MessageLevel.Warning, duration=5)
            return

        if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PointGeometry:
            self.iface.messageBar().pushMessage(
                'RTH Revisor',
                'A camada ativa não é de pontos / '
                'The active layer is not a point layer',
                level=Qgis.MessageLevel.Warning, duration=5)
            return

        if layer.featureCount() == 0:
            self.iface.messageBar().pushMessage(
                'RTH Revisor',
                'A camada não possui feições / '
                'The layer has no features',
                level=Qgis.MessageLevel.Warning, duration=5)
            return

        if self._dlg is None:
            self._dlg = PointReviewerDialog(
                self.iface, parent=self.iface.mainWindow())

        self._dlg.start(layer)
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
