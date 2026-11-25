# -*- coding: utf-8 -*-
"""
rth_scene_card — Widget de card para exibir uma cena STAC com thumbnail, data, nuvens e ID
rth_scene_card — Card widget to display a STAC scene with thumbnail, date, clouds and ID

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Módulos Qt para layout e widgets / Qt modules for layout and widgets
from qgis.PyQt.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout,
    QLabel, QCheckBox
)
# Módulos Qt para alinhamento, sinais e métricas de fonte / Qt modules for alignment, signals and font metrics
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFontMetrics
import re

# Carregador assíncrono de thumbnails / Async thumbnail loader
from .rth_thumbnail import load_thumbnail_async


def _extract_op(scene_id: str) -> str:
    """Extract the MGRS tile (OP) from a Sentinel-2 scene ID.

    'S2C_MSIL2A_20260419T125311_N0512_R052_T24KTF_20260419T173008' → '24KTF'
    Returns empty string for non-S2 or unrecognised IDs.
    """
    for part in scene_id.split('_'):
        if re.match(r'^T[0-9]{2}[A-Z]{3}$', part):
            return part[1:]   # strip leading T
    return ''


class SceneCard(QFrame):
    """Card visual para uma cena STAC: thumbnail + data + nuvens + ID / Visual card for a STAC scene: thumbnail + date + clouds + ID."""

    # Sinal emitido ao clicar no card (índice da feature) / Signal emitted on card click (feature index)
    selected = pyqtSignal(int)

    # Dimensões do thumbnail em pixels / Thumbnail dimensions in pixels
    THUMB_W = 207
    THUMB_H = 130

    # Dimensões fixas do card / Fixed card dimensions
    CARD_W = 215
    CARD_H = 215

    def __init__(self, idx, feature, parent=None):
        """Construtor do card / Card constructor.

        :param idx: índice da feature na lista de resultados / feature index in results list
        :param feature: GeoJSON feature com assets e properties / GeoJSON feature with assets and properties
        :param parent: widget pai / parent widget
        """
        super().__init__(parent)
        # Índice da feature / Feature index
        self._idx = idx
        # Feature GeoJSON completa / Full GeoJSON feature
        self._feature = feature
        # Thumbnail ainda não carregado / Thumbnail not yet loaded
        self._thumb_loaded = False
        # Monta os widgets internos / Build internal widgets
        self._build_ui()
        # Aplica estilo padrão (não selecionado) / Apply default style (not selected)
        self._apply_style(selected=False)

    def _build_ui(self):
        """Monta o layout vertical: thumbnail → linha data/nuvem → ID → checkbox / Build vertical layout: thumbnail → date/cloud row → ID → checkbox."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        # ── Thumbnail ─────────────────────────────────────────────────
        # Label que receberá o thumbnail carregado / Label that will receive the loaded thumbnail
        self.lbl_thumb = QLabel()
        self.lbl_thumb.setFixedSize(self.THUMB_W, self.THUMB_H)
        self.lbl_thumb.setAlignment(Qt.AlignCenter)
        self.lbl_thumb.setText('...')
        self.lbl_thumb.setStyleSheet(
            'background:#2a2a2a; color:#666; font-size:10px;'
        )
        layout.addWidget(self.lbl_thumb)

        # ── Linha: data (esquerda) | nuvens (direita) ─────────────────
        # Extrai data e cobertura de nuvens das properties / Extract date and cloud cover from properties
        props     = self._feature.get('properties', {})
        dt        = props.get('datetime', '')[:10]
        cloud_val = props.get('eo:cloud_cover')
        cloud_str = '{:.0f}%'.format(cloud_val) if isinstance(cloud_val, (int, float)) else 'N/A'

        row_info = QHBoxLayout()
        row_info.setSpacing(4)

        # Rótulo de data / Date label
        lbl_date = QLabel(dt)
        lbl_date.setStyleSheet('font-size:11px; color:#ccc;')

        # Rótulo de nuvens / Cloud label
        lbl_cloud = QLabel('☁ ' + cloud_str)
        lbl_cloud.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lbl_cloud.setStyleSheet('font-size:11px; color:#6bc;')

        row_info.addWidget(lbl_date)
        row_info.addWidget(lbl_cloud)
        layout.addLayout(row_info)

        # ── ID da cena (elided se muito longo) ────────────────────────
        scene_id = self._feature.get('id', '')
        self.lbl_id = QLabel()
        self.lbl_id.setAlignment(Qt.AlignCenter)
        self.lbl_id.setStyleSheet('font-size:10px; color:#888;')
        self.lbl_id.setMaximumWidth(self.THUMB_W)
        fm = QFontMetrics(self.lbl_id.font())
        self.lbl_id.setText(fm.elidedText(scene_id, Qt.ElideRight, self.THUMB_W))
        layout.addWidget(self.lbl_id)

        # ── Linha: checkbox (esquerda) | OP / MGRS tile (direita) ───────
        op_str = _extract_op(scene_id)

        row_chk = QHBoxLayout()
        row_chk.setContentsMargins(0, 0, 0, 0)
        row_chk.setSpacing(4)

        self.chk = QCheckBox('Selecionar / Select')
        self.chk.setStyleSheet('font-size:10px; color:#888;')
        row_chk.addWidget(self.chk)
        row_chk.addStretch()

        if op_str:
            lbl_op = QLabel(op_str)
            lbl_op.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl_op.setStyleSheet('font-size:10px; color:#f90; font-weight:bold;')
            lbl_op.setToolTip('MGRS tile / OP: ' + op_str)
            row_chk.addWidget(lbl_op)

        layout.addLayout(row_chk)

        # Tamanho fixo do card / Fixed card size
        self.setFixedSize(self.CARD_W, self.CARD_H)

    # ── API pública ───────────────────────────────────────────────────

    def is_checked(self):
        """Retorna se o checkbox está marcado / Returns whether the checkbox is checked."""
        return self.chk.isChecked()

    def load_thumb(self, cancel_flag):
        """Inicia o carregamento assíncrono do thumbnail (uma única vez) / Start async thumbnail loading (once only).

        :param cancel_flag: lista [bool] compartilhada — [True] cancela o worker / shared [bool] list — [True] cancels worker
        """
        if not self._thumb_loaded:
            # Exibe mensagem enquanto aguarda o worker / Show message while waiting for worker
            self.lbl_thumb.setText('Carregando... / Loading...')
            # Inicia carregamento em thread de background / Start loading in background thread
            load_thumbnail_async(self._feature, self.lbl_thumb, cancel_flag)
            self._thumb_loaded = True

    def set_selected(self, selected):
        """Aplica estilo de seleção / Apply selection style."""
        self._apply_style(selected)

    # ── Estilo interno ────────────────────────────────────────────────

    def _apply_style(self, selected):
        """Alterna borda azul (selecionado) ou cinza escuro (normal) / Toggle blue border (selected) or dark grey (normal)."""
        if selected:
            self.setStyleSheet(
                'QFrame { border: 2px solid #0077cc; '
                'background: #1e2a3a; border-radius: 4px; }'
            )
        else:
            self.setStyleSheet(
                'QFrame { border: 1px solid #444; '
                'background: #1a1a1a; border-radius: 4px; }'
            )

    # ── Evento de clique ──────────────────────────────────────────────

    def mousePressEvent(self, event):
        """Emite sinal com o índice da feature ao clicar no card / Emit signal with feature index on card click."""
        self.selected.emit(self._idx)
        super().mousePressEvent(event)
