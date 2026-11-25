# -*- coding: utf-8 -*-
"""
CameraDisplacementTool — Deslocamento manual e automático do canvas por passos configuráveis.
CameraDisplacementTool — Manual and automatic canvas displacement by configurable steps.

Uso / Usage:
  - Manual: ↑ Deslocar para Cima / ↓ Deslocar para Baixo — desloca N% da altura do canvas
  - Automático: timer desloca o canvas a cada X segundos
  - Configurar: define tamanho do passo (ticks = %) e intervalo automático (segundos)

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer
from qgis.core import Qgis, QgsPointXY

_SETTINGS_FRAC  = 'rth_project/camera_displacement/fraction'
_SETTINGS_SECS  = 'rth_project/camera_displacement/auto_secs'
_SETTINGS_DIR   = 'rth_project/camera_displacement/auto_direction'


class CameraDisplacementTool:
    """Desloca o canvas verticalmente com suporte a auto-pan por timer.
    Displaces canvas vertically with timer-based auto-pan support.
    """

    def __init__(self, iface):
        self.iface  = iface
        self.canvas = iface.mapCanvas()

        self._fraction       = 0.8   # 80% da altura do canvas por passo / 80% of canvas height per step
        self._auto_secs      = 5
        self._auto_direction = +1    # +1 = cima/up, -1 = baixo/down
        self._auto_enabled   = False

        # ação do menu para manter sincronismo do checkmark / menu action for checkmark sync
        self._auto_action = None

        self._timer = QTimer()
        self._timer.timeout.connect(self._auto_tick)

        self._load_settings()

    def tr(self, msg):
        return QCoreApplication.translate('CameraDisplacementTool', msg)

    # ------------------------------------------------------------------
    # API pública / Public API
    # ------------------------------------------------------------------

    def set_auto_action(self, action):
        """Registra a QAction do menu para manter o checkmark sincronizado.
        Register the menu QAction to keep checkmark in sync.
        """
        self._auto_action = action

    def pan_up(self, *_):
        """Desloca o canvas para cima (norte) / Shift canvas up (north)."""
        self._pan(+1)

    def pan_down(self, *_):
        """Desloca o canvas para baixo (sul) / Shift canvas down (south)."""
        self._pan(-1)

    def set_auto(self, enabled, *_):
        """Habilita ou desabilita o auto-pan via timer / Enable or disable auto-pan timer."""
        self._auto_enabled = bool(enabled)
        if self._auto_enabled:
            self._start_timer()
        else:
            self._stop_timer()
        if self._auto_action is not None:
            self._auto_action.setChecked(self._auto_enabled)

    def configure(self, *_):
        """Abre diálogo para configurar passo e intervalo / Open dialog to configure step and interval."""
        from qgis.PyQt.QtWidgets import (
            QDialog, QVBoxLayout, QFormLayout, QSpinBox,
            QDoubleSpinBox, QComboBox, QDialogButtonBox, QLabel,
        )

        dlg = QDialog(self.iface.mainWindow())
        dlg.setWindowTitle(self.tr(u'Configurar Deslocamento / Configure Displacement'))
        layout = QVBoxLayout(dlg)
        form   = QFormLayout()

        spin_frac = QDoubleSpinBox()
        spin_frac.setRange(1.0, 100.0)
        spin_frac.setDecimals(0)
        spin_frac.setSuffix(' %')
        spin_frac.setValue(self._fraction * 100)
        form.addRow(
            QLabel(self.tr(u'Passo (% da altura do canvas) / Step (% of canvas height):')),
            spin_frac)

        spin_secs = QSpinBox()
        spin_secs.setRange(1, 3600)
        spin_secs.setValue(self._auto_secs)
        form.addRow(
            QLabel(self.tr(u'Intervalo automático (segundos) / Auto interval (seconds):')),
            spin_secs)

        combo_dir = QComboBox()
        combo_dir.addItem(self.tr(u'↑  Para Cima / Up'),   +1)
        combo_dir.addItem(self.tr(u'↓  Para Baixo / Down'), -1)
        combo_dir.setCurrentIndex(0 if self._auto_direction == +1 else 1)
        form.addRow(
            QLabel(self.tr(u'Direção automática / Auto direction:')),
            combo_dir)

        layout.addLayout(form)

        try:
            std = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        except AttributeError:
            std = QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        btns = QDialogButtonBox(std)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec_():
            self._fraction       = spin_frac.value() / 100.0
            self._auto_secs      = spin_secs.value()
            self._auto_direction = combo_dir.currentData()
            self._save_settings()
            if self._auto_enabled:
                self._start_timer()   # reinicia com o novo intervalo / restart with new interval

    def stop(self):
        """Chamado no unload do plugin / Called on plugin unload."""
        self._stop_timer()

    # ------------------------------------------------------------------
    # Internos / Internals
    # ------------------------------------------------------------------

    def _pan(self, direction):
        """Desloca o centro do canvas na direção indicada.
        Displace the canvas center in the indicated direction.
        """
        center = self.canvas.center()
        extent = self.canvas.extent()
        dy = extent.height() * self._fraction * direction
        self.canvas.setCenter(QgsPointXY(center.x(), center.y() + dy))
        self.canvas.refresh()

    def _auto_tick(self):
        self._pan(self._auto_direction)

    def _start_timer(self):
        self._timer.stop()
        self._timer.setInterval(self._auto_secs * 1000)
        self._timer.start()
        self.iface.messageBar().pushMessage(
            'RTH',
            self.tr(u'Deslocamento automático ativado — {0}s por passo / Auto displacement active — {0}s per step').format(
                self._auto_secs),
            level=Qgis.MessageLevel.Info, duration=3)

    def _stop_timer(self):
        self._timer.stop()

    def _load_settings(self):
        s = QSettings()
        try:
            self._fraction       = float(s.value(_SETTINGS_FRAC, 0.8))
            self._auto_secs      = int(s.value(_SETTINGS_SECS,   5))
            self._auto_direction = int(s.value(_SETTINGS_DIR,    +1))
        except (TypeError, ValueError):
            pass

    def _save_settings(self):
        s = QSettings()
        s.setValue(_SETTINGS_FRAC, self._fraction)
        s.setValue(_SETTINGS_SECS, self._auto_secs)
        s.setValue(_SETTINGS_DIR,  self._auto_direction)
