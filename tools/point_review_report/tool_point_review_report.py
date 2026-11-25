# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QComboBox,
    QFrame, QApplication
)
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes
)

# ── Compat Qt5/Qt6: QFrame enums ─────────────────────────────────────────────
try:
    _FRAME_HLINE  = QFrame.Shape.HLine
    _FRAME_SUNKEN = QFrame.Shadow.Sunken
except AttributeError:
    _FRAME_HLINE  = QFrame.HLine
    _FRAME_SUNKEN = QFrame.Sunken

# ── Constantes de campo / Field constants ─────────────────────────────────────
_ACERTO_FIELD = 'acerto'
_VAL_ACERTOU  = 'acertou'
_VAL_ERROU    = 'errou'


# ──────────────────────────────────────────────────────────────────────────────
# Lógica de cálculo / Calculation logic
# ──────────────────────────────────────────────────────────────────────────────

def _compute_stats(layer):
    """Conta pontos por categoria e calcula acurácia geral.
    Counts points by category and calculates overall accuracy.

    Retorna (dict, None) ou (None, mensagem_de_erro).
    Returns (dict, None) or (None, error_message)."""
    acerto_idx = layer.fields().indexOf(_ACERTO_FIELD)
    if acerto_idx < 0:
        return None, (
            'Campo "{}" não encontrado na camada. / '
            'Field "{}" not found in layer.').format(_ACERTO_FIELD, _ACERTO_FIELD)

    n_total   = 0
    n_acertou = 0
    n_errou   = 0
    n_indif   = 0

    for feat in layer.getFeatures():
        n_total += 1
        val = str(feat.attributes()[acerto_idx]).strip().lower()
        if val == _VAL_ACERTOU:
            n_acertou += 1
        elif val == _VAL_ERROU:
            n_errou += 1
        else:
            n_indif += 1

    n_reviewed = n_acertou + n_errou
    oa         = n_acertou / n_reviewed if n_reviewed > 0 else 0.0

    return {
        'n_total':    n_total,
        'n_acertou':  n_acertou,
        'n_errou':    n_errou,
        'n_indif':    n_indif,
        'n_reviewed': n_reviewed,
        'oa':         oa,
    }, None


# ──────────────────────────────────────────────────────────────────────────────
# Dialog
# ──────────────────────────────────────────────────────────────────────────────

class PointReviewReportDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle(
            'RTH Relatório de Revisão de Pontos / Point Review Report')
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint |
            Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint
        )
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)
        self._root = root

        lbl = QLabel('Relatório de Revisão de Pontos / Point Review Report')
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet('font-size:13px; font-weight:bold;')
        root.addWidget(lbl)

        self._sep()

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

        self._combo_layer = QComboBox()
        self._combo_layer.setMinimumHeight(28)
        form.addRow('Camada de Pontos / Point Layer:', self._combo_layer)

        root.addLayout(form)

        self._btn_run = QPushButton('▶  Gerar Relatório / Generate Report')
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

        # ── Card de resultado (fundo escuro) / Dark result card ───────────────
        card = QFrame()
        card.setStyleSheet(
            'QFrame{background:#2d2d2d;border-radius:8px;border:none;}')
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        self._lbl_total = QLabel('—')
        self._lbl_total.setAlignment(Qt.AlignCenter)
        self._lbl_total.setStyleSheet(
            'font-size:11px; color:#9aa0a6; background:transparent; border:none;')
        card_layout.addWidget(self._lbl_total)

        sep1 = QFrame()
        sep1.setFixedHeight(1)
        sep1.setStyleSheet('background:#444; border:none;')
        card_layout.addWidget(sep1)

        # Linhas de contagem / Count rows
        self._val_acertou = self._add_count_row(
            card_layout, 'Acertou / Hit', '#66bb6a')
        self._val_errou   = self._add_count_row(
            card_layout, 'Errou / Miss', '#ef5350')
        self._val_indif   = self._add_count_row(
            card_layout, 'Indiferente / Indifferent', '#9aa0a6')

        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet('background:#444; border:none;')
        card_layout.addWidget(sep2)

        # Acurácia geral / Overall accuracy
        acc_row = QHBoxLayout()
        acc_title = QLabel('Acurácia Geral / Overall Accuracy:')
        acc_title.setStyleSheet(
            'font-size:12px; color:#9aa0a6; background:transparent; border:none;')
        self._lbl_accuracy = QLabel('—')
        f_acc = QFont()
        f_acc.setBold(True)
        f_acc.setPointSize(15)
        self._lbl_accuracy.setFont(f_acc)
        self._lbl_accuracy.setStyleSheet(
            'color:#64b5f6; background:transparent; border:none;')
        acc_row.addWidget(acc_title)
        acc_row.addStretch()
        acc_row.addWidget(self._lbl_accuracy)
        card_layout.addLayout(acc_row)

        root.addWidget(card)

        self._lbl_status = QLabel('')
        self._lbl_status.setAlignment(Qt.AlignCenter)
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setStyleSheet('font-size:10px; color:#c62828;')
        root.addWidget(self._lbl_status)

    def _add_count_row(self, layout, label_text, color):
        """Adiciona linha de contagem ao card e retorna o QLabel de valor.
        Adds count row to card and returns the value QLabel."""
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet(
            'font-size:11px; color:#d4d6d9; background:transparent; border:none;')
        val = QLabel('—')
        f = QFont()
        f.setBold(True)
        val.setFont(f)
        val.setStyleSheet(
            'font-size:11px; color:{}; background:transparent; border:none;'.format(color))
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(val)
        layout.addLayout(row)
        return val

    def _sep(self):
        line = QFrame()
        line.setFrameShape(_FRAME_HLINE)
        line.setFrameShadow(_FRAME_SUNKEN)
        self._root.addWidget(line)

    # ── Eventos ───────────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._populate_layers()

    def _populate_layers(self):
        self._combo_layer.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PointGeometry:
                continue
            self._combo_layer.addItem(layer.name(), layer.id())

    # ── Execução / Run ────────────────────────────────────────────────────────

    def _on_run(self):
        self._lbl_status.setText('')
        layer_id = self._combo_layer.currentData()
        if not layer_id:
            self._error(
                'Nenhuma camada de pontos disponível. / No point layer available.')
            return

        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer or not isinstance(layer, QgsVectorLayer):
            self._error('Camada não encontrada. / Layer not found.')
            return

        self._btn_run.setEnabled(False)
        self._lbl_status.setStyleSheet('font-size:10px; color:#555;')
        self._lbl_status.setText('Calculando... / Calculating...')
        QApplication.processEvents()

        try:
            stats, err = _compute_stats(layer)
        except Exception as e:
            self._btn_run.setEnabled(True)
            self._error('Erro: {} / Error: {}'.format(e, e))
            return

        self._btn_run.setEnabled(True)

        if err:
            self._error(err)
            return

        self._show_result(stats)

    def _show_result(self, s):
        n_total    = s['n_total']
        n_acertou  = s['n_acertou']
        n_errou    = s['n_errou']
        n_indif    = s['n_indif']
        n_reviewed = s['n_reviewed']
        oa         = s['oa']

        def pct(n, total):
            return '{:.1f}%'.format(n / total * 100.0) if total > 0 else '0.0%'

        self._lbl_total.setText(
            'Total: {} pontos / points  |  Avaliados / Evaluated: {} ({})'.format(
                n_total, n_reviewed, pct(n_reviewed, n_total)))

        self._val_acertou.setText('{} ({})'.format(n_acertou, pct(n_acertou, n_total)))
        self._val_errou.setText('{} ({})'.format(n_errou,   pct(n_errou,   n_total)))
        self._val_indif.setText('{} ({})'.format(n_indif,   pct(n_indif,   n_total)))

        acc_color = ('#66bb6a' if oa >= 0.8 else
                     '#ffa726' if oa >= 0.5 else '#ef5350')
        self._lbl_accuracy.setText('{:.1f}%'.format(oa * 100.0))
        self._lbl_accuracy.setStyleSheet(
            'font-size:15px; font-weight:bold; color:{}; '
            'background:transparent; border:none;'.format(acc_color))

        self._lbl_status.setText('')

    def _error(self, msg):
        self._lbl_status.setStyleSheet('font-size:10px; color:#c62828;')
        self._lbl_status.setText(msg)


# ──────────────────────────────────────────────────────────────────────────────
# Tool
# ──────────────────────────────────────────────────────────────────────────────

class PointReviewReportTool:

    def __init__(self, iface):
        self.iface = iface
        self._dlg  = None

    def run(self):
        if self._dlg is None:
            self._dlg = PointReviewReportDialog(
                self.iface, parent=self.iface.mainWindow())
        self._dlg._populate_layers()
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
