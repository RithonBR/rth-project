# -*- coding: utf-8 -*-
"""
tool_bordadura_lines.py

Ferramenta de Linhas de Bordadura / Headland Lines Tool

Gera a linha de bordadura (passada perimetral) dentro de um polígono
selecionado, com offset = metade da largura do implemento a partir da borda.
Suporte a cantos retos (Miter) ou curvados (raio mínimo de curva).

Generates the headland line (perimeter pass) inside a selected polygon,
with offset = half implement width from the field boundary.
Supports straight (Miter) or curved corners (minimum turn radius).

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

from qgis.core import (
    Qgis,
    QgsProject,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsField,
    QgsWkbTypes,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsCsException,
)
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtWidgets import (
    QDialog, QLabel, QDoubleSpinBox, QPushButton,
    QVBoxLayout, QHBoxLayout, QGroupBox, QMessageBox,
    QFrame, QLineEdit, QComboBox, QRadioButton, QButtonGroup,
)
from core.rth_utm_utils import detect_regional_utm
from core.rth_layer_utils import collapse_layer


# ─────────────────────────────────────────────────────────────────────────────
# Diálogo principal / Main dialog
# ─────────────────────────────────────────────────────────────────────────────
class BordaduraLinesDialog(QDialog):

    _STYLE_GENERATE = """
        QPushButton {
            background-color: #388E3C; color: white; border: none;
            padding: 9px 16px; border-radius: 5px; font-weight: bold; font-size: 11px;
        }
        QPushButton:hover   { background-color: #2E7D32; }
        QPushButton:pressed { background-color: #1B5E20; }
    """
    _STYLE_CANCEL = """
        QPushButton {
            background-color: #616161; color: white; border: none;
            padding: 9px 16px; border-radius: 5px; font-size: 11px;
        }
        QPushButton:hover   { background-color: #424242; }
        QPushButton:pressed { background-color: #212121; }
    """

    _SMOOTH_OPTS = [
        ('Sem Suavização / No Smoothing',  0, 0.00),
        ('Suave / Gentle',                 1, 0.15),
        ('Médio / Medium',                 3, 0.25),
        ('Forte / Strong',                 5, 0.35),
        ('Muito Forte / Very Strong',       8, 0.45),
    ]

    def __init__(self, epsg, datum_name, zone, hemi, parent=None):
        super().__init__(parent)
        self.setWindowTitle('RTH — Linhas de Bordadura / Headland Lines')
        self.setMinimumWidth(480)
        self.setMaximumWidth(560)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # ── Cabeçalho / Header ─────────────────────────────────────────────
        lbl_title = QLabel(
            '<span style="font-size:13px;font-weight:bold;">'
            '🌿 Linhas de Bordadura / Headland Lines'
            '</span>'
        )
        lbl_title.setAlignment(Qt.AlignCenter)
        root.addWidget(lbl_title)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # ── Sistema de referência / Reference System ───────────────────────
        grp_datum = QGroupBox('Sistema de Referência / Reference System')
        lay_datum = QVBoxLayout()
        lay_datum.setContentsMargins(8, 4, 8, 6)
        lbl_datum = QLabel(f'{datum_name}  •  EPSG:{epsg}  •  Zona / Zone {zone}{hemi}')
        lbl_datum.setStyleSheet('font-size:11px; font-weight:bold;')
        lay_datum.addWidget(lbl_datum)
        grp_datum.setLayout(lay_datum)
        root.addWidget(grp_datum)

        # ── Nome da camada / Layer name ────────────────────────────────────
        grp_name = QGroupBox('Nome da Camada / Layer Name')
        lay_name = QHBoxLayout()
        lay_name.setContentsMargins(8, 6, 8, 8)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText('Prefixo (opcional) / Prefix (optional)')
        self.edit_name.setMinimumHeight(28)
        lay_name.addWidget(self.edit_name)
        grp_name.setLayout(lay_name)
        root.addWidget(grp_name)

        # ── Implemento / Implement ─────────────────────────────────────────
        grp_impl = QGroupBox('Implemento Agrícola / Agricultural Implement')
        lay_impl = QVBoxLayout()
        lay_impl.setContentsMargins(8, 4, 8, 8)
        lay_impl.setSpacing(6)

        lbl_width = QLabel('Largura total do implemento (m) / Total implement width (m):')
        lbl_width.setStyleSheet('font-size:11px;')
        lay_impl.addWidget(lbl_width)

        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.1, 5000.0)
        self.spin_width.setValue(15.0)
        self.spin_width.setSuffix(' m')
        self.spin_width.setDecimals(2)
        self.spin_width.setSingleStep(0.5)
        self.spin_width.setMinimumHeight(30)
        lay_impl.addWidget(self.spin_width)

        self.lbl_offset = QLabel()
        self.lbl_offset.setStyleSheet('font-size:9px; color:#aaa;')
        lay_impl.addWidget(self.lbl_offset)

        grp_impl.setLayout(lay_impl)
        root.addWidget(grp_impl)

        # ── Modo de cantos / Corner mode ───────────────────────────────────
        grp_corners = QGroupBox('Modo de Cantos / Corner Mode')
        lay_corners = QVBoxLayout()
        lay_corners.setContentsMargins(8, 6, 8, 8)
        lay_corners.setSpacing(6)

        self._btn_group = QButtonGroup(self)

        self.radio_miter = QRadioButton('Reto / Straight')
        self.radio_miter.setStyleSheet('font-size:11px; font-weight:bold;')
        self.radio_miter.setChecked(True)
        self._btn_group.addButton(self.radio_miter, 0)
        lbl_miter = QLabel('  Cantos em ângulo vivo seguindo o polígono.\n'
                           '  Sharp corners following the polygon.')
        lbl_miter.setStyleSheet('font-size:9px; color:#aaa; margin-bottom:2px;')
        lay_corners.addWidget(self.radio_miter)
        lay_corners.addWidget(lbl_miter)

        sep_c = QFrame(); sep_c.setFrameShape(QFrame.HLine); sep_c.setFrameShadow(QFrame.Sunken)
        lay_corners.addWidget(sep_c)

        self.radio_round = QRadioButton('Curvado / Rounded')
        self.radio_round.setStyleSheet('font-size:11px; font-weight:bold;')
        self._btn_group.addButton(self.radio_round, 1)
        lbl_round = QLabel('  Cantos arredondados com raio mínimo de curva.\n'
                           '  Rounded corners with minimum turn radius.')
        lbl_round.setStyleSheet('font-size:9px; color:#aaa;')
        lay_corners.addWidget(self.radio_round)
        lay_corners.addWidget(lbl_round)

        # ── Raio de Curva (visível só quando Curvado) / Turn Radius (visible only when Rounded)
        self.grp_radius = QGroupBox('Raio Mínimo de Curva / Minimum Turn Radius')
        lay_radius = QVBoxLayout()
        lay_radius.setContentsMargins(8, 4, 8, 8)

        lbl_tr = QLabel('Raio mínimo de curva (m) / Minimum turn radius (m):')
        lbl_tr.setStyleSheet('font-size:11px;')
        lay_radius.addWidget(lbl_tr)

        self.spin_radius = QDoubleSpinBox()
        self.spin_radius.setRange(0.5, 500.0)
        self.spin_radius.setValue(6.0)
        self.spin_radius.setSuffix(' m')
        self.spin_radius.setDecimals(1)
        self.spin_radius.setSingleStep(0.5)
        self.spin_radius.setMinimumHeight(30)
        lay_radius.addWidget(self.spin_radius)

        lbl_tr_hint = QLabel(
            '  Ex: 3,0 m (trator/ATV)  •  6,0 m (plantadeira)  •  12,0 m (colhedora)\n'
            '  Ex: 3.0 m (tractor/ATV)  •  6.0 m (planter)  •  12.0 m (harvester)'
        )
        lbl_tr_hint.setStyleSheet('font-size:9px; color:#aaa; margin-top:2px;')
        lay_radius.addWidget(lbl_tr_hint)
        self.grp_radius.setLayout(lay_radius)
        self.grp_radius.setVisible(False)
        lay_corners.addWidget(self.grp_radius)

        grp_corners.setLayout(lay_corners)
        root.addWidget(grp_corners)

        # ── Suavização / Smoothing ─────────────────────────────────────────
        grp_smooth = QGroupBox('Suavização das Linhas / Line Smoothing')
        lay_smooth = QVBoxLayout()
        lay_smooth.setContentsMargins(8, 4, 8, 8)
        lbl_smooth = QLabel('Intensidade de suavização / Smoothing intensity:')
        lbl_smooth.setStyleSheet('font-size:11px;')
        lay_smooth.addWidget(lbl_smooth)

        self.combo_smooth = QComboBox()
        for label, _, _ in self._SMOOTH_OPTS:
            self.combo_smooth.addItem(label)
        self.combo_smooth.setCurrentIndex(0)  # Sem Suavização por padrão
        lay_smooth.addWidget(self.combo_smooth)
        grp_smooth.setLayout(lay_smooth)
        root.addWidget(grp_smooth)

        # ── Ações / Actions ────────────────────────────────────────────────
        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); sep2.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep2)

        row_btns = QHBoxLayout()
        self.btn_generate = QPushButton('▶  Gerar Bordadura / Generate Headland')
        self.btn_generate.setStyleSheet(self._STYLE_GENERATE)
        self.btn_generate.setMinimumHeight(36)

        self.btn_cancel = QPushButton('Cancelar / Cancel')
        self.btn_cancel.setStyleSheet(self._STYLE_CANCEL)
        self.btn_cancel.setMinimumHeight(36)

        row_btns.addWidget(self.btn_generate)
        row_btns.addWidget(self.btn_cancel)
        root.addLayout(row_btns)

        self.btn_cancel.clicked.connect(self.reject)
        self.spin_width.valueChanged.connect(self._update_offset_label)
        self.radio_round.toggled.connect(self._on_mode_changed)
        self._update_offset_label()

    def _update_offset_label(self, _=None):
        half = self.spin_width.value() / 2.0
        self.lbl_offset.setText(
            f'  Offset da borda / Edge offset: {half:.2f} m  '
            f'(metade do implemento / half implement width)'
        )

    def _on_mode_changed(self, checked=False):
        self.grp_radius.setVisible(self.radio_round.isChecked())
        self.adjustSize()

    # ── API pública / Public API ───────────────────────────────────────────
    @property
    def implement_width(self):
        return self.spin_width.value()

    @property
    def corner_mode(self):
        return 'rounded' if self.radio_round.isChecked() else 'miter'

    @property
    def turn_radius(self):
        return self.spin_radius.value()

    @property
    def smoothing_params(self):
        idx = self.combo_smooth.currentIndex()
        _, iters, offset = self._SMOOTH_OPTS[idx]
        return iters, offset

    @property
    def custom_name(self):
        return self.edit_name.text().strip()


# ─────────────────────────────────────────────────────────────────────────────
# Ferramenta principal / Main tool class
# ─────────────────────────────────────────────────────────────────────────────
class BordaduraLinesTool:
    """
    Gera a linha de bordadura (offset = metade do implemento) dentro de um polígono.
    Cantos retos (Miter) ou curvados via buffer(-r).buffer(r, Round).
    Generates the headland line (offset = half implement width) inside a polygon.
    Straight corners (Miter) or rounded via buffer(-r).buffer(r, Round).
    """

    def __init__(self, iface):
        self.iface = iface
        self._polygon_geom = None
        self._layer_crs = None
        self._epsg = self._datum = self._zone = self._hemi = None
        self._dlg = None

    # ── Ponto de entrada / Entry point ────────────────────────────────────
    def run(self):
        layer = self.iface.activeLayer()
        if not layer or layer.type() != layer.VectorLayer:
            QMessageBox.warning(
                None, 'RTH Linhas de Bordadura / Headland Lines',
                'Selecione uma camada vetorial de polígonos.\n'
                'Select a polygon vector layer.'
            )
            return

        if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            QMessageBox.warning(
                None, 'RTH Linhas de Bordadura / Headland Lines',
                'A camada ativa deve conter polígonos.\n'
                'The active layer must contain polygons.'
            )
            return

        selected = layer.selectedFeatures()
        if not selected:
            QMessageBox.warning(
                None, 'RTH Linhas de Bordadura / Headland Lines',
                'Selecione ao menos um polígono antes de ativar a ferramenta.\n'
                'Select at least one polygon before activating the tool.'
            )
            return

        geoms = [f.geometry() for f in selected]
        self._polygon_geom = QgsGeometry.unaryUnion(geoms) if len(geoms) > 1 else geoms[0]
        self._layer_crs = layer.crs()

        centroid_layer = self._polygon_geom.centroid().asPoint()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        if self._layer_crs.authid() != 'EPSG:4326':
            xform = QgsCoordinateTransform(self._layer_crs, wgs84, QgsProject.instance())
            try:
                centroid_wgs = xform.transform(centroid_layer)
            except QgsCsException:
                centroid_wgs = centroid_layer
        else:
            centroid_wgs = centroid_layer

        self._epsg, self._datum, self._zone, self._hemi = detect_regional_utm(
            centroid_wgs.x(), centroid_wgs.y()
        )

        self._dlg = BordaduraLinesDialog(
            self._epsg, self._datum, self._zone, self._hemi,
            parent=self.iface.mainWindow()
        )
        self._dlg.btn_generate.clicked.connect(self._do_generate)
        self._dlg.finished.connect(lambda _: setattr(self, '_dlg', None))
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()

    # ── Gera a linha de bordadura / Generate headland line ────────────────
    def _do_generate(self):
        implement_width              = self._dlg.implement_width   if self._dlg else 15.0
        corner_mode                  = self._dlg.corner_mode       if self._dlg else 'miter'
        turn_radius                  = self._dlg.turn_radius       if self._dlg else 6.0
        smooth_iters, smooth_offset  = self._dlg.smoothing_params  if self._dlg else (0, 0.0)
        half_width = implement_width / 2.0

        utm_crs = QgsCoordinateReferenceSystem(f'EPSG:{self._epsg}')
        xform   = QgsCoordinateTransform(self._layer_crs, utm_crs, QgsProject.instance())

        poly_utm = QgsGeometry(self._polygon_geom)
        try:
            poly_utm.transform(xform)
        except QgsCsException as e:
            QMessageBox.critical(None, 'RTH', f'Erro ao reprojetar polígono.\n{e}')
            return

        # ── Buffer interno com Miter / Inward Miter buffer ─────────────────
        inner = poly_utm.buffer(
            -half_width, 8,
            Qgis.EndCapStyle.Flat, Qgis.JoinStyle.Miter, 10.0
        )
        if not inner or inner.isEmpty():
            QMessageBox.warning(
                None, 'RTH',
                f'Polígono muito pequeno para um implemento de {implement_width} m.\n'
                f'Polygon too small for an implement of {implement_width} m.'
            )
            return

        # ── Arredondamento de cantos / Corner rounding ──────────────────────
        # Técnica: buffer(-r, Round).buffer(r, Round) arredonda os cantos com
        # raio r sem deslocar os trechos retos.
        # Technique: buffer(-r, Round).buffer(r, Round) rounds corners with
        # radius r without shifting the straight sections.
        if corner_mode == 'rounded':
            r = turn_radius
            inner_shrunk = inner.buffer(
                -r, 16,
                Qgis.EndCapStyle.Round, Qgis.JoinStyle.Round, 1.0
            )
            if inner_shrunk and not inner_shrunk.isEmpty():
                inner_rounded = inner_shrunk.buffer(
                    r, 16,
                    Qgis.EndCapStyle.Round, Qgis.JoinStyle.Round, 1.0
                )
                if inner_rounded and not inner_rounded.isEmpty():
                    inner = inner_rounded

        # ── Extrai anel exterior como linha / Extract exterior ring as line ─
        # boundary() não existe nesta versão; extrai anel via asPolygon()
        # boundary() absent in this build; extract ring via asPolygon()
        boundary_line = self._polygon_to_line(inner)
        if not boundary_line or boundary_line.isEmpty():
            QMessageBox.warning(None, 'RTH',
                'Não foi possível extrair a linha de bordadura.\n'
                'Could not extract headland line.')
            return

        # ── Suavização (idêntica ao PlantingLinesTool) / Smoothing ─────────
        if smooth_iters > 0:
            smoothed = boundary_line.smooth(smooth_iters, smooth_offset, -1.0, 180.0)
            if smoothed and not smoothed.isEmpty():
                boundary_line = smoothed

        # ── Cria camada de resultado / Create result layer ────────────────
        custom_name  = (self._dlg.custom_name if self._dlg else '').strip()
        base_name    = custom_name if custom_name else 'Linhas_Bordadura'
        mode_label   = f'Curvo_r{turn_radius:.0f}m' if corner_mode == 'rounded' else 'Reto'
        layer_name   = f'{base_name}_{implement_width:.1f}m_{mode_label}_EPSG_{self._epsg}'

        vl = QgsVectorLayer(f'LineString?crs=EPSG:{self._epsg}', layer_name, 'memory')
        pr = vl.dataProvider()
        pr.addAttributes([
            QgsField('id',             QVariant.Int),
            QgsField('dist_borda_m',   QVariant.Double),
            QgsField('largura_impl_m', QVariant.Double),
            QgsField('modo',           QVariant.String),
            QgsField('datum',          QVariant.String),
        ])
        vl.updateFields()

        f = QgsFeature(vl.fields())
        f.setGeometry(boundary_line)
        f.setAttribute('id',             1)
        f.setAttribute('dist_borda_m',   round(half_width, 3))
        f.setAttribute('largura_impl_m', implement_width)
        f.setAttribute('modo',           mode_label)
        f.setAttribute('datum',          f'{self._datum} EPSG:{self._epsg}')
        pr.addFeatures([f])

        vl.updateExtents()
        QgsProject.instance().addMapLayer(vl)
        collapse_layer(vl)

        self.iface.messageBar().pushMessage(
            'RTH Linhas de Bordadura / Headland Lines',
            f'Bordadura gerada / Headland generated  •  '
            f'offset {half_width:.2f} m  •  {mode_label}  •  '
            f'{self._datum} EPSG:{self._epsg}',
            level=Qgis.MessageLevel.Info, duration=7,
        )

        if self._dlg:
            self._dlg.close()

    # ── Extrai anel exterior de polígono como linha / Extract exterior ring ─
    @staticmethod
    def _polygon_to_line(geom):
        """
        Converte o(s) anel(is) exteriore(s) de um polígono (simples ou multi)
        em uma geometria LineString / MultiLineString.
        Converts exterior ring(s) of a (multi)polygon to a LineString/MultiLineString.
        """
        if geom.isMultipart():
            parts = geom.asMultiPolygon()
            rings = [part[0] for part in parts if part]
            if not rings:
                return None
            if len(rings) == 1:
                return QgsGeometry.fromPolylineXY(rings[0])
            return QgsGeometry.fromMultiPolylineXY(rings)
        else:
            ring = geom.asPolygon()
            if not ring:
                return None
            return QgsGeometry.fromPolylineXY(ring[0])
