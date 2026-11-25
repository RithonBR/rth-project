# -*- coding: utf-8 -*-
"""
RTH Auto-Save — salva o projeto e commita camadas em edição a cada X segundos.
Persiste o estado (habilitado/desabilitado) e o intervalo via QSettings.
"""
from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QSpinBox, QFrame
)
from qgis.core import Qgis, QgsProject


SETTINGS_ENABLED  = 'rth_project/autosave_enabled'
SETTINGS_INTERVAL = 'rth_project/autosave_interval'
DEFAULT_INTERVAL  = 300  # seconds


class AutoSaveConfigDialog(QDialog):

    def __init__(self, current_interval, parent=None):
        super(AutoSaveConfigDialog, self).__init__(parent)
        self.setWindowTitle('RTH Auto-Save — Configurar Intervalo / Configure Interval')
        self.setMinimumWidth(360)
        self._build_ui(current_interval)

    def tr(self, message):
        return QCoreApplication.translate('AutoSaveConfigDialog', message)

    def _sep(self, layout):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

    def _build_ui(self, current_interval):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        lbl_title = QLabel('RTH Auto-Save')
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold;')
        layout.addWidget(lbl_title)

        lbl_sub = QLabel(self.tr(u'Defina o intervalo de salvamento automático / Set the auto-save interval'))
        lbl_sub.setStyleSheet('color:#666; font-size:10px;')
        lbl_sub.setWordWrap(True)
        layout.addWidget(lbl_sub)

        self._sep(layout)

        lbl_interval = QLabel(self.tr(u'Intervalo (segundos) / Interval (seconds)'))
        lbl_interval.setStyleSheet('font-weight:bold;')
        layout.addWidget(lbl_interval)

        self.spinbox = QSpinBox()
        self.spinbox.setMinimum(30)
        self.spinbox.setMaximum(3600)
        self.spinbox.setSingleStep(30)
        self.spinbox.setValue(current_interval)
        self.spinbox.setSuffix(self.tr(u' s'))
        layout.addWidget(self.spinbox)

        lbl_presets = QLabel(self.tr(u'Atalhos rápidos / Quick presets'))
        lbl_presets.setStyleSheet('font-size:10px; color:#555;')
        layout.addWidget(lbl_presets)

        presets_row = QHBoxLayout()
        for label, secs in [('30s', 30), ('1min', 60), ('5min', 300), ('10min', 600), ('30min', 1800)]:
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda _, s=secs: self.spinbox.setValue(s))
            presets_row.addWidget(btn)
        layout.addLayout(presets_row)

        self._sep(layout)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton(self.tr(u'OK'))
        btn_ok.setMinimumHeight(36)
        btn_ok.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;border-radius:4px;}'
            'QPushButton:hover{background:#1558b0;}'
        )
        btn_cancel = QPushButton(self.tr(u'Cancelar / Cancel'))
        btn_cancel.setMinimumHeight(36)
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def get_interval(self):
        return self.spinbox.value()


class AutoSaveTool:
    """Salva o projeto e commita camadas em edição periodicamente / Periodically saves the project and commits edited layers."""

    def __init__(self, iface):
        self.iface = iface
        self._toggle_action = None
        self._timer = QTimer()
        self._timer.timeout.connect(self._on_timer)

        settings = QSettings()
        self._interval = int(settings.value(SETTINGS_INTERVAL, DEFAULT_INTERVAL))

        enabled = settings.value(SETTINGS_ENABLED, False)
        if isinstance(enabled, str):
            enabled = enabled.lower() == 'true'
        if enabled:
            self._timer.start(self._interval * 1000)

    def tr(self, message):
        return QCoreApplication.translate('AutoSaveTool', message)

    def set_toggle_action(self, action):
        """Associa o QAction checkable para manter o estado sincronizado / Associate the checkable QAction to keep state in sync."""
        self._toggle_action = action
        action.setChecked(self._timer.isActive())

    def toggle(self, checked):
        """Habilita ou desabilita o auto-save / Enable or disable auto-save."""
        if checked:
            self._timer.start(self._interval * 1000)
        else:
            self._timer.stop()
        if self._toggle_action:
            self._toggle_action.setChecked(self._timer.isActive())
        QSettings().setValue(SETTINGS_ENABLED, self._timer.isActive())

    def configure(self):
        """Abre o diálogo de configuração / Open the configuration dialog."""
        dlg = AutoSaveConfigDialog(self._interval, self.iface.mainWindow())
        if dlg.exec():
            self._interval = dlg.get_interval()
            QSettings().setValue(SETTINGS_INTERVAL, self._interval)
            if self._timer.isActive():
                self._timer.start(self._interval * 1000)
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Auto-Save: intervalo definido para {0}s / interval set to {0}s').format(self._interval),
                level=Qgis.MessageLevel.Info, duration=3
            )

    def stop(self):
        """Para o timer — chamado no unload / Stop the timer — called on unload."""
        self._timer.stop()

    def _on_timer(self):
        """Salva o projeto e commita layers em edição / Save project and commit layers being edited."""
        QgsProject.instance().write()

        committed = 0
        for layer in QgsProject.instance().mapLayers().values():
            if (hasattr(layer, 'isEditable') and layer.isEditable()
                    and hasattr(layer, 'isModified') and layer.isModified()):
                layer.commitChanges()
                committed += 1

        if committed:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Auto-Save: projeto e {0} camada(s) salvas / project and {0} layer(s) saved').format(committed),
                level=Qgis.MessageLevel.Info, duration=2
            )
        else:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Auto-Save: projeto salvo / project saved'),
                level=Qgis.MessageLevel.Info, duration=2
            )
