# -*- coding: utf-8 -*-
"""
tool_drone_planner.py

Planejador de Voo para Drones / Drone Flight Planner

Gera linhas de voo paralelas sobre um polígono selecionado a partir dos
parâmetros da câmera, altitude, overlaps e direção de voo.

Generates parallel flight lines over a selected polygon from camera
parameters, altitude, overlaps and flight direction.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

import math

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QComboBox, QDoubleSpinBox, QSpinBox, QFrame, QGroupBox,
    QCheckBox, QMessageBox, QApplication, QScrollArea, QWidget,
)
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsField, QgsWkbTypes,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsCsException,
    QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsLineSymbol,
)

from core.rth_utm_utils import detect_regional_utm
from core.rth_layer_utils import collapse_layer


# ─── Drone / camera presets ───────────────────────────────────────────────────
# Specs sourced from official manufacturer documentation:
# DJI: https://www.dji.com/products
# Parrot: https://www.parrot.com
# Autel: https://www.autelrobotics.com
# WingtraOne: https://wingtra.com
#
# Columns: (display_name, sensor_w_mm, sensor_h_mm, focal_mm,
#            img_w_px, img_h_px, default_speed_ms, note)
# All focal lengths are REAL (not 35 mm equivalent).
# sensor_w = longer sensor dimension (landscape width).

DRONE_PRESETS = [
    # ── Custom ────────────────────────────────────────────────────────────────
    ('Personalizado / Custom',
     None, None, None, None, None, 10.0,
     'Insira os parametros da sua camera / Enter your camera parameters'),

    # ── DJI Profissional / Professional ───────────────────────────────────────
    ('DJI Phantom 4 RTK',
     13.2, 8.8, 8.8, 5472, 3648, 10.0,
     '1" CMOS 20MP  •  RTK/PPK integrado / integrated  •  referencia / reference para mapeamento de precisao / precision mapping'),

    ('DJI Phantom 4 Pro V2',
     13.2, 8.8, 8.8, 5472, 3648, 12.0,
     '1" CMOS 20MP  •  otimo custo-beneficio / great cost-benefit para mapeamento / for mapping'),

    ('DJI Mavic 3E Enterprise',
     17.3, 13.0, 12.3, 5280, 3956, 15.0,
     '4/3" CMOS 20MP  •  RTK integrado / optional integrated RTK  •  melhor relacao / best footprint-to-GSD ratio'),

    ('DJI Mavic 3M Multispectral',
     17.3, 13.0, 12.3, 5280, 3956, 15.0,
     '4/3" CMOS 20MP  +  4 bandas multiespectrais / multispectral bands (G/R/RE/NIR)  •  agricultura de precisao / precision agriculture'),

    ('DJI Matrice 350 RTK + P1 35mm',
     35.9, 24.0, 35.0, 8192, 5460, 15.0,
     'Full frame 45MP  •  industrial  •  cobertura massiva / massive coverage em menos voos / in fewer flights'),

    ('DJI Matrice 300 RTK + P1 35mm',
     35.9, 24.0, 35.0, 8192, 5460, 15.0,
     'Full frame 45MP  •  industrial  •  RTK + PPK / surveying grade'),

    ('DJI Matrice 350 RTK + L2 (LiDAR)',
     None, None, None, None, None, 15.0,
     'LiDAR — parametros opticos nao aplicaveis / LiDAR — optical params N/A'),

    # ── DJI Consumidor / Consumer ─────────────────────────────────────────────
    ('DJI Air 2S',
     13.2, 8.8, 8.38, 5472, 3648, 10.0,
     '1" CMOS 20MP  •  prosumer  •  bom para areas menores / good for smaller areas'),

    ('DJI Mavic 2 Pro',
     13.2, 8.8, 10.26, 5472, 3648, 10.0,
     '1" CMOS 20MP Hasselblad  •  focal 28mm equiv  •  consumer / prosumer'),

    ('DJI Mini 3 Pro',
     9.6, 7.2, 6.7, 4032, 3024, 8.0,
     '1/1.3" CMOS  •  12MP modo mapeamento / mapping mode  •  limite legal / legal limit 120m AGL'),

    ('DJI Mini 4 Pro',
     9.6, 7.2, 6.7, 4032, 3024, 8.0,
     '1/1.3" CMOS  •  12MP modo mapeamento / mapping mode  •  limite legal / legal limit 120m AGL'),

    # ── Parrot ────────────────────────────────────────────────────────────────
    ('Parrot ANAFI USA',
     6.2, 4.7, 4.14, 5344, 4016, 10.0,
     '1/2.4" CMOS 21MP  •  boa portabilidade / good portability'),

    # ── Autel ─────────────────────────────────────────────────────────────────
    ('Autel EVO II Pro 6K',
     17.3, 13.0, 8.0, 6000, 4000, 12.0,
     '4/3" CMOS 20MP  •  alternativa / alternative to Mavic 3E'),

    # ── Asa fixa VTOL / Fixed-wing VTOL ──────────────────────────────────────
    ('WingtraOne GEN II + Sony RX1R II',
     35.9, 24.0, 35.0, 7952, 5304, 16.0,
     'VTOL asa fixa / fixed-wing VTOL  •  Full frame 42MP Sony  •  ideal para grandes areas / ideal for large areas'),
]

# Quick lookup dict
_PRESET_MAP = {
    name: (sw, sh, fl, iw, ih, sp, note)
    for name, sw, sh, fl, iw, ih, sp, note in DRONE_PRESETS
}


# ─── Geometry / planning helpers ──────────────────────────────────────────────

def _compute_auto_direction(poly_geom_utm):
    """
    Return flight azimuth (0–179°, from North clockwise) that minimises
    the number of flight strips — i.e., the direction parallel to the
    longest polygon axis (minimises the width perpendicular to flight).
    """
    hull = poly_geom_utm.convexHull()
    if hull.isEmpty():
        return 0.0
    rings = hull.asPolygon() if not hull.isMultipart() else hull.asMultiPolygon()[0]
    pts = rings[0] if rings else []
    if len(pts) < 3:
        return 0.0

    xs = [p.x() for p in pts]
    ys = [p.y() for p in pts]

    best_az = 0.0
    min_w   = float('inf')
    for deg in range(0, 180):
        rad = math.radians(deg)
        # Perpendicular to flight direction (cos az, -sin az) in (E, N)
        px = math.cos(rad)
        py = -math.sin(rad)
        projs = [x * px + y * py for x, y in zip(xs, ys)]
        w = max(projs) - min(projs)
        if w < min_w:
            min_w   = w
            best_az = float(deg)
    return best_az


def _generate_flight_lines(poly_utm, flight_az_deg, line_spacing, margin_m):
    """
    Generate clipped LineString geometries for the flight plan.

    Lines are parallel to flight_az_deg, spaced line_spacing metres apart,
    clipped to poly_utm buffered by margin_m (edge coverage).
    """
    if line_spacing <= 0:
        return []

    coverage = poly_utm.buffer(margin_m, 5) if margin_m > 0 else QgsGeometry(poly_utm)
    if coverage.isEmpty():
        coverage = QgsGeometry(poly_utm)

    bbox = coverage.boundingBox()
    cx   = (bbox.xMinimum() + bbox.xMaximum()) / 2.0
    cy   = (bbox.yMinimum() + bbox.yMaximum()) / 2.0

    az  = math.radians(flight_az_deg)
    fdx = math.sin(az);  fdy = math.cos(az)   # flight direction unit vector
    px  = math.cos(az);  py  = -math.sin(az)  # perpendicular (right of flight)

    corners = [
        (bbox.xMinimum(), bbox.yMinimum()),
        (bbox.xMinimum(), bbox.yMaximum()),
        (bbox.xMaximum(), bbox.yMinimum()),
        (bbox.xMaximum(), bbox.yMaximum()),
    ]
    perp_projs = [x * px + y * py for x, y in corners]
    para_projs = [x * fdx + y * fdy for x, y in corners]
    perp_min = min(perp_projs);  perp_max = max(perp_projs)
    para_min = min(para_projs);  para_max = max(para_projs)

    # Centre of bbox in perpendicular direction
    perp_cx = cx * px + cy * py

    extend = math.sqrt(bbox.width() ** 2 + bbox.height() ** 2) * 0.1 + line_spacing
    n_pos  = int((perp_max - perp_cx) / line_spacing) + 2
    n_neg  = int((perp_cx - perp_min) / line_spacing) + 2

    lines = []
    for i in range(-n_neg, n_pos + 1):
        perp_pos = perp_cx + i * line_spacing
        ox = perp_pos * px
        oy = perp_pos * py
        p1 = QgsPointXY(ox + (para_min - extend) * fdx,
                        oy + (para_min - extend) * fdy)
        p2 = QgsPointXY(ox + (para_max + extend) * fdx,
                        oy + (para_max + extend) * fdy)
        raw     = QgsGeometry.fromPolylineXY([p1, p2])
        clipped = raw.intersection(coverage)
        if clipped and not clipped.isEmpty() and clipped.length() > 0.1:
            # intersection can return MultiLineString — explode to parts
            if clipped.isMultipart():
                for part in clipped.asMultiPolyline():
                    if len(part) >= 2:
                        g = QgsGeometry.fromPolylineXY(part)
                        if g.length() > 0.1:
                            lines.append(g)
            else:
                lines.append(clipped)

    return lines


def _connect_flight_route(flight_lines):
    """
    Build a boustrophedon (serpentine) route from ordered flight strips.

    Alternates traversal direction on each strip so the drone flies
    strip-1 forward → transit straight → strip-2 backward → transit straight
    → strip-3 forward → … without curves.

    Returns list of (QgsGeometry, tipo) where tipo is 'faixa' or 'transito'.
    Both types are LineString. The caller adds them to a single route layer
    so the user can apply different symbology per tipo.
    """
    segments = []
    forward  = True
    prev_end = None   # QgsPointXY of the last point placed

    for line in flight_lines:
        pts = list(line.asPolyline())
        if len(pts) < 2:
            continue

        if not forward:
            pts = list(reversed(pts))

        curr_start = QgsPointXY(pts[0])

        if prev_end is not None:
            # Straight transit from end of previous strip to start of this one
            segments.append((
                QgsGeometry.fromPolylineXY([prev_end, curr_start]),
                'transito',
            ))

        segments.append((
            QgsGeometry.fromPolylineXY([QgsPointXY(p) for p in pts]),
            'faixa',
        ))

        prev_end = QgsPointXY(pts[-1])
        forward  = not forward

    return segments


def _generate_waypoints(flight_lines, photo_spacing_m):
    """
    Interpolate photo-capture points along each flight line.
    Returns list of (QgsPointXY, line_id, sequence).
    """
    waypoints = []
    for lid, lg in enumerate(flight_lines, start=1):
        ll = lg.length()
        if ll < 0.01:
            continue
        n_pts   = max(2, int(math.ceil(ll / photo_spacing_m)) + 1)
        spacing = ll / (n_pts - 1)
        for j in range(n_pts):
            pt = lg.interpolate(j * spacing).asPoint()
            waypoints.append((QgsPointXY(pt), lid, j + 1))
    return waypoints


# ─── GSD / footprint formulas ─────────────────────────────────────────────────

def _gsd_cm(sensor_side_mm, img_side_px, focal_mm, altitude_m):
    """Ground Sampling Distance in cm/pixel."""
    if img_side_px == 0 or focal_mm == 0:
        return 0.0
    return (sensor_side_mm / img_side_px) / focal_mm * altitude_m * 100.0


def _footprint_m(sensor_w_mm, sensor_h_mm, focal_mm, altitude_m, landscape):
    """
    Returns (across_track_m, along_track_m).
    landscape=True  → sensor_w across track, sensor_h along track.
    landscape=False → sensor_h across track, sensor_w along track.
    """
    if focal_mm == 0:
        return 0.0, 0.0
    across = (sensor_w_mm if landscape else sensor_h_mm) / focal_mm * altitude_m
    along  = (sensor_h_mm if landscape else sensor_w_mm) / focal_mm * altitude_m
    return across, along


def _gsd_style(gsd):
    """Return (color, quality_label) based on GSD value."""
    if gsd <= 0:   return '#888888', '—'
    if gsd < 1.0:  return '#1565c0', 'Muito alta / Very high'
    if gsd < 3.0:  return '#2e7d32', 'Alta / High'
    if gsd < 6.0:  return '#f57c00', 'Media / Medium'
    return '#c62828', 'Baixa / Low'


def _apply_route_style(layer):
    """Categorized symbology: faixa=blue solid, transito=grey dashed."""
    sym_faixa = QgsLineSymbol.createSimple({
        'color': '#1565C0', 'width': '0.6', 'line_style': 'solid',
    })
    sym_transito = QgsLineSymbol.createSimple({
        'color': '#9E9E9E', 'width': '0.4', 'line_style': 'dash',
    })
    cats = [
        QgsRendererCategory('faixa',   sym_faixa,   'Faixa de voo / Flight strip'),
        QgsRendererCategory('transito', sym_transito, 'Trânsito / Transit'),
    ]
    renderer = QgsCategorizedSymbolRenderer('tipo', cats)
    layer.setRenderer(renderer)
    layer.triggerRepaint()


def _fmt_min(minutes):
    h = int(minutes // 60)
    m = int(minutes % 60)
    return '{}h {:02d}min'.format(h, m) if h else '{}min'.format(m)


# ─── Dialog ───────────────────────────────────────────────────────────────────

class DroneFlightPlannerDialog(QDialog):

    def __init__(self, poly_geom, layer_crs, epsg, datum, zone, hemi, iface, parent=None):
        super().__init__(parent)
        self.iface      = iface
        self._poly_geom = poly_geom
        self._layer_crs = layer_crs
        self._epsg      = epsg
        self._datum     = datum
        self._zone      = zone
        self._hemi      = hemi

        # Pre-transform polygon to UTM (used for auto-direction and live preview)
        utm_crs         = QgsCoordinateReferenceSystem('EPSG:{}'.format(epsg))
        xf              = QgsCoordinateTransform(layer_crs, utm_crs, QgsProject.instance())
        self._poly_utm  = QgsGeometry(poly_geom)
        try:
            self._poly_utm.transform(xf)
        except Exception:  # nosec B110
            pass

        self._build_ui()
        self._on_drone_changed()  # populate preset, triggers _update_preview

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle('RTH — Planejador de Voo para Drones / Drone Flight Planner')
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(300)
        self.setMinimumHeight(700)
        self.setMaximumWidth(460)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        _container = QWidget()
        scroll.setWidget(_container)

        root = QVBoxLayout(_container)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # Header
        lbl_t = QLabel('Planejador de Voo para Drones / Drone Flight Planner')
        lbl_t.setAlignment(Qt.AlignCenter)
        lbl_t.setStyleSheet('font-size:13px;font-weight:bold;')
        root.addWidget(lbl_t)

        lbl_crs = QLabel(
            '{} • EPSG:{} • Zona / Zone {}{}'.format(
                self._datum, self._epsg, self._zone, self._hemi))
        lbl_crs.setAlignment(Qt.AlignCenter)
        lbl_crs.setStyleSheet('color:#666;font-size:10px;')
        root.addWidget(lbl_crs)

        root.addWidget(self._sep())

        # ── Drone & Camera ────────────────────────────────────────────────────
        grp_drone = QGroupBox('Drone e Camera / Drone & Camera')
        lay_d = QVBoxLayout()
        lay_d.setContentsMargins(8, 6, 8, 8)
        lay_d.setSpacing(5)

        lay_d.addWidget(QLabel('Drone / Camera:'))
        self.combo_drone = QComboBox()
        for name, *_ in DRONE_PRESETS:
            self.combo_drone.addItem(name)
        self.combo_drone.currentIndexChanged.connect(self._on_drone_changed)
        lay_d.addWidget(self.combo_drone)

        self.lbl_note = QLabel('')
        self.lbl_note.setStyleSheet('font-size:9px;color:#888;')
        self.lbl_note.setWordWrap(True)
        lay_d.addWidget(self.lbl_note)

        # Camera spec fields
        grp_cam = QGroupBox('Especificacoes da Camera / Camera Specs')
        gcam = QGridLayout()
        gcam.setContentsMargins(8, 4, 8, 8)
        gcam.setSpacing(4)
        gcam.setColumnStretch(1, 1)

        def _clbl(text, row):
            lbl = QLabel(text); lbl.setStyleSheet('font-size:10px;')
            gcam.addWidget(lbl, row, 0)

        _clbl('Largura sensor / Sensor W (mm):', 0)
        self.spin_sw = QDoubleSpinBox()
        self.spin_sw.setRange(1.0, 100.0); self.spin_sw.setDecimals(2)
        self.spin_sw.setValue(13.2); self.spin_sw.setSingleStep(0.1)
        self.spin_sw.valueChanged.connect(self._update_preview)
        gcam.addWidget(self.spin_sw, 0, 1)

        _clbl('Altura sensor / Sensor H (mm):', 1)
        self.spin_sh = QDoubleSpinBox()
        self.spin_sh.setRange(1.0, 100.0); self.spin_sh.setDecimals(2)
        self.spin_sh.setValue(8.8); self.spin_sh.setSingleStep(0.1)
        self.spin_sh.valueChanged.connect(self._update_preview)
        gcam.addWidget(self.spin_sh, 1, 1)

        _clbl('Focal real / Focal length (mm):', 2)
        self.spin_fl = QDoubleSpinBox()
        self.spin_fl.setRange(1.0, 200.0); self.spin_fl.setDecimals(2)
        self.spin_fl.setValue(8.8); self.spin_fl.setSingleStep(0.1)
        self.spin_fl.valueChanged.connect(self._update_preview)
        gcam.addWidget(self.spin_fl, 2, 1)

        _clbl('Resolucao X / Image width (px):', 3)
        self.spin_iw = QSpinBox()
        self.spin_iw.setRange(100, 20000); self.spin_iw.setValue(5472)
        self.spin_iw.setSingleStep(100)
        self.spin_iw.valueChanged.connect(self._update_preview)
        gcam.addWidget(self.spin_iw, 3, 1)

        _clbl('Resolucao Y / Image height (px):', 4)
        self.spin_ih = QSpinBox()
        self.spin_ih.setRange(100, 20000); self.spin_ih.setValue(3648)
        self.spin_ih.setSingleStep(100)
        self.spin_ih.valueChanged.connect(self._update_preview)
        gcam.addWidget(self.spin_ih, 4, 1)

        grp_cam.setLayout(gcam)
        self._grp_cam = grp_cam
        lay_d.addWidget(grp_cam)

        grp_drone.setLayout(lay_d)
        root.addWidget(grp_drone)

        # ── Flight parameters ─────────────────────────────────────────────────
        grp_fl = QGroupBox('Parametros de Voo / Flight Parameters')
        gfl = QGridLayout()
        gfl.setContentsMargins(8, 6, 8, 8)
        gfl.setSpacing(5)
        gfl.setColumnStretch(1, 1)

        def _flbl(text, row):
            lbl = QLabel(text); lbl.setStyleSheet('font-size:11px;')
            gfl.addWidget(lbl, row, 0)

        _flbl('Altitude AGL (m):', 0)
        self.spin_alt = QDoubleSpinBox()
        self.spin_alt.setRange(10.0, 1000.0); self.spin_alt.setValue(100.0)
        self.spin_alt.setSuffix(' m'); self.spin_alt.setDecimals(0); self.spin_alt.setSingleStep(10)
        self.spin_alt.setToolTip(
            'Altitude acima do solo / Above Ground Level\n'
            'Verifique o limite legal da sua regiao / Check legal limit in your region')
        self.spin_alt.valueChanged.connect(self._update_preview)
        gfl.addWidget(self.spin_alt, 0, 1)

        _flbl('Front overlap (%):', 1)
        self.spin_front = QDoubleSpinBox()
        self.spin_front.setRange(50.0, 95.0); self.spin_front.setValue(80.0)
        self.spin_front.setSuffix(' %'); self.spin_front.setDecimals(0); self.spin_front.setSingleStep(5)
        self.spin_front.setToolTip(
            'Sobreposicao longitudinal (ao longo do voo)\n'
            'Longitudinal overlap — tipico: 70-90%')
        self.spin_front.valueChanged.connect(self._update_preview)
        gfl.addWidget(self.spin_front, 1, 1)

        _flbl('Side overlap (%):', 2)
        self.spin_side = QDoubleSpinBox()
        self.spin_side.setRange(40.0, 95.0); self.spin_side.setValue(75.0)
        self.spin_side.setSuffix(' %'); self.spin_side.setDecimals(0); self.spin_side.setSingleStep(5)
        self.spin_side.setToolTip(
            'Sobreposicao lateral (entre faixas)\n'
            'Lateral overlap — tipico: 60-80%')
        self.spin_side.valueChanged.connect(self._update_preview)
        gfl.addWidget(self.spin_side, 2, 1)

        _flbl('Orientacao camera / Camera orient.:', 3)
        self.combo_orient = QComboBox()
        self.combo_orient.addItem('Paisagem / Landscape', 'landscape')
        self.combo_orient.addItem('Retrato / Portrait',   'portrait')
        self.combo_orient.setToolTip(
            'Paisagem: sensor_W perpendicular ao voo\n'
            'Retrato:  sensor_H perpendicular ao voo')
        self.combo_orient.currentIndexChanged.connect(self._update_preview)
        gfl.addWidget(self.combo_orient, 3, 1)

        _flbl('Direcao de voo / Flight dir. (°):', 4)
        row_dir = QHBoxLayout()
        row_dir.setContentsMargins(0, 0, 0, 0)
        self.spin_dir = QDoubleSpinBox()
        self.spin_dir.setRange(0.0, 359.9); self.spin_dir.setValue(0.0)
        self.spin_dir.setSuffix(' °'); self.spin_dir.setDecimals(1); self.spin_dir.setSingleStep(5)
        self.spin_dir.setToolTip('0°=Norte/N  90°=Leste/E  180°=Sul/S  270°=Oeste/W')
        self.spin_dir.valueChanged.connect(self._update_preview)
        row_dir.addWidget(self.spin_dir)
        self.btn_auto = QPushButton('Auto')
        self.btn_auto.setFixedWidth(50)
        self.btn_auto.setToolTip(
            'Detecta a direcao que minimiza o numero de faixas\n'
            'Detects direction that minimises the number of strips')
        self.btn_auto.clicked.connect(self._on_auto_dir)
        row_dir.addWidget(self.btn_auto)
        w_dir = QFrame(); w_dir.setLayout(row_dir)
        gfl.addWidget(w_dir, 4, 1)

        _flbl('Velocidade / Speed (m/s):', 5)
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(1.0, 25.0); self.spin_speed.setValue(10.0)
        self.spin_speed.setSuffix(' m/s'); self.spin_speed.setDecimals(1); self.spin_speed.setSingleStep(1)
        self.spin_speed.setToolTip('Velocidade tipica de mapeamento / Typical mapping speed: 8-15 m/s')
        self.spin_speed.valueChanged.connect(self._update_preview)
        gfl.addWidget(self.spin_speed, 5, 1)

        _flbl('Autonomia / Endurance (0=ignorar):', 6)
        self.spin_endu = QSpinBox()
        self.spin_endu.setRange(0, 120); self.spin_endu.setValue(0)
        self.spin_endu.setSuffix(' min')
        self.spin_endu.setToolTip(
            'Autonomia real de voo para calcular numero de baterias\n'
            'Real flight endurance to calculate battery count\n'
            '0 = nao calcular / 0 = skip')
        self.spin_endu.valueChanged.connect(self._update_preview)
        gfl.addWidget(self.spin_endu, 6, 1)

        grp_fl.setLayout(gfl)
        root.addWidget(grp_fl)

        # ── Live preview ──────────────────────────────────────────────────────
        grp_prev = QGroupBox('Preview em Tempo Real / Live Preview')
        gprev = QGridLayout()
        gprev.setContentsMargins(8, 6, 8, 8)
        gprev.setSpacing(3)
        gprev.setColumnStretch(1, 1)

        def _prev_row(label, row):
            lbl = QLabel(label + ':'); lbl.setStyleSheet('color:#555;font-size:10px;')
            v = QLabel('—')
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            v.setStyleSheet('font-weight:bold;font-size:10px;')
            gprev.addWidget(lbl, row, 0)
            gprev.addWidget(v, row, 1)
            return v

        self.lbl_gsd     = _prev_row('GSD',                            0)
        self.lbl_fp      = _prev_row('Pegada / Footprint',             1)
        self.lbl_lsp     = _prev_row('Esp. faixas / Line spacing',     2)
        self.lbl_psp     = _prev_row('Interv. foto / Photo interval',  3)
        self.lbl_nlines  = _prev_row('Est. faixas / Est. strips',      4)
        self.lbl_nphotos = _prev_row('Est. fotos / Est. photos',       5)
        self.lbl_time    = _prev_row('Est. tempo / Est. flight time',  6)
        self.lbl_batt    = _prev_row('Est. baterias / Est. batteries', 7)

        grp_prev.setLayout(gprev)
        root.addWidget(grp_prev)

        # ── Options ───────────────────────────────────────────────────────────
        grp_opt = QGroupBox('Opcoes / Options')
        lay_opt = QVBoxLayout()
        lay_opt.setContentsMargins(8, 6, 8, 6)
        lay_opt.setSpacing(4)

        self.chk_wp = QCheckBox('Gerar waypoints de foto / Generate photo waypoints')
        self.chk_wp.setStyleSheet('font-size:10px;')
        lay_opt.addWidget(self.chk_wp)

        self.chk_cov = QCheckBox('Gerar poligono de cobertura / Generate coverage polygon')
        self.chk_cov.setChecked(True)
        self.chk_cov.setStyleSheet('font-size:10px;')
        lay_opt.addWidget(self.chk_cov)

        row_mg = QHBoxLayout()
        row_mg.addWidget(QLabel('Margem extra nas bordas / Extra edge margin:'))
        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(0.0, 100.0); self.spin_margin.setValue(0.0)
        self.spin_margin.setSuffix(' %'); self.spin_margin.setDecimals(0)
        self.spin_margin.setToolTip(
            '% adicional do footprint para garantir cobertura nas bordas\n'
            'Additional % of footprint to ensure edge coverage')
        self.spin_margin.valueChanged.connect(self._update_preview)
        row_mg.addWidget(self.spin_margin)
        row_mg.addStretch()
        lay_opt.addLayout(row_mg)

        grp_opt.setLayout(lay_opt)
        root.addWidget(grp_opt)

        # ── Action buttons — always visible outside scroll ─────────────────────
        outer.addWidget(self._sep())
        row_btn = QHBoxLayout()
        row_btn.setContentsMargins(12, 6, 12, 12)
        self.btn_gen = QPushButton('Gerar Plano de Voo / Generate Flight Plan')
        self.btn_gen.setMinimumHeight(38)
        self.btn_gen.setStyleSheet(
            'QPushButton{background:#1976d2;color:white;font-weight:bold;'
            'font-size:12px;border-radius:5px;border:none;}'
            'QPushButton:hover{background:#1565c0;}'
            'QPushButton:disabled{background:#5a7fa8;color:#aaa;}')
        self.btn_gen.clicked.connect(self.accept)
        row_btn.addWidget(self.btn_gen)

        btn_cancel = QPushButton('Cancelar / Cancel')
        btn_cancel.setMinimumHeight(38)
        btn_cancel.setStyleSheet(
            'QPushButton{background:#616161;color:white;border:none;'
            'border-radius:5px;}'
            'QPushButton:hover{background:#424242;}')
        btn_cancel.clicked.connect(self.reject)
        row_btn.addWidget(btn_cancel)
        outer.addLayout(row_btn)

    def _sep(self):
        ln = QFrame(); ln.setFrameShape(QFrame.HLine); ln.setFrameShadow(QFrame.Sunken)
        return ln

    # ── Slot: drone preset changed ────────────────────────────────────────────

    def _on_drone_changed(self):
        name = self.combo_drone.currentText()
        data = _PRESET_MAP.get(name)
        if data is None:
            return
        sw, sh, fl, iw, ih, speed, note = data
        is_custom = (sw is None)

        for spin in (self.spin_sw, self.spin_sh, self.spin_fl, self.spin_iw, self.spin_ih):
            spin.setEnabled(is_custom)
        self.lbl_note.setText(note)

        if not is_custom:
            for spin, val in ((self.spin_sw, sw), (self.spin_sh, sh),
                              (self.spin_fl, fl), (self.spin_speed, speed)):
                spin.blockSignals(True); spin.setValue(val); spin.blockSignals(False)
            self.spin_iw.blockSignals(True); self.spin_iw.setValue(iw); self.spin_iw.blockSignals(False)
            self.spin_ih.blockSignals(True); self.spin_ih.setValue(ih); self.spin_ih.blockSignals(False)

        # LiDAR preset — disable camera group entirely
        self._grp_cam.setEnabled(not (not is_custom and fl is None))
        self._update_preview()

    # ── Slot: auto direction ──────────────────────────────────────────────────

    def _on_auto_dir(self):
        best = _compute_auto_direction(self._poly_utm)
        self.spin_dir.setValue(best)

    # ── Live preview ──────────────────────────────────────────────────────────

    def _camera_params(self):
        return (self.spin_sw.value(), self.spin_sh.value(), self.spin_fl.value(),
                self.spin_iw.value(), self.spin_ih.value(),
                self.combo_orient.currentData() == 'landscape')

    def _update_preview(self):
        sw, sh, fl, iw, ih, landscape = self._camera_params()
        alt   = self.spin_alt.value()
        front = self.spin_front.value()
        side  = self.spin_side.value()
        speed = self.spin_speed.value()
        endu  = self.spin_endu.value()

        if fl <= 0 or iw <= 0 or ih <= 0:
            return

        fp_across, fp_along = _footprint_m(sw, sh, fl, alt, landscape)
        line_sp  = fp_across * (1.0 - side  / 100.0)
        photo_sp = fp_along  * (1.0 - front / 100.0)

        # GSD (using across-track pixel size)
        across_sensor = sw if landscape else sh
        across_px     = iw if landscape else ih
        gsd = _gsd_cm(across_sensor, across_px, fl, alt)
        gsd_color, gsd_lbl = _gsd_style(gsd)

        self.lbl_gsd.setText(
            '<span style="color:{}">{:.2f} cm/px  [{}]</span>'.format(
                gsd_color, gsd, gsd_lbl))
        self.lbl_gsd.setTextFormat(Qt.RichText)
        self.lbl_fp.setText('{:.1f} m × {:.1f} m  (faixa × comp.)'.format(fp_across, fp_along))
        self.lbl_lsp.setText('{:.1f} m'.format(line_sp) if line_sp > 0 else '—')
        self.lbl_psp.setText('{:.1f} m'.format(photo_sp) if photo_sp > 0 else '—')

        # Polygon-dependent estimates
        if not self._poly_utm.isEmpty() and line_sp > 0 and photo_sp > 0:
            margin_m = fp_across * (1.0 + self.spin_margin.value() / 100.0) / 2.0
            try:
                buf  = self._poly_utm.buffer(margin_m, 5)
                bbox = buf.boundingBox()
            except Exception:
                bbox = self._poly_utm.boundingBox()

            az  = math.radians(self.spin_dir.value())
            fdx = math.sin(az); fdy = math.cos(az)
            px  = math.cos(az); py  = -math.sin(az)
            corners = [
                (bbox.xMinimum(), bbox.yMinimum()),
                (bbox.xMinimum(), bbox.yMaximum()),
                (bbox.xMaximum(), bbox.yMinimum()),
                (bbox.xMaximum(), bbox.yMaximum()),
            ]
            pp = [x * px + y * py for x, y in corners]
            fp = [x * fdx + y * fdy for x, y in corners]
            width  = max(pp) - min(pp)
            length = max(fp) - min(fp)

            n_strips = max(1, int(math.ceil(width  / line_sp)))
            n_ph_line = max(1, int(math.ceil(length / photo_sp)) + 1)
            n_photos  = n_strips * n_ph_line
            total_m   = n_strips * length
            t_min     = total_m / speed / 60.0

            self.lbl_nlines .setText(str(n_strips))
            self.lbl_nphotos.setText('{:,}'.format(n_photos).replace(',', '.'))
            self.lbl_time   .setText(_fmt_min(t_min))
            self.lbl_batt   .setText(
                str(math.ceil(t_min / endu)) if endu > 0 else '—')
        else:
            for lbl in (self.lbl_nlines, self.lbl_nphotos, self.lbl_time, self.lbl_batt):
                lbl.setText('—')

    # ── Public: collect all params ────────────────────────────────────────────

    @property
    def flight_params(self):
        sw, sh, fl, iw, ih, landscape = self._camera_params()
        alt   = self.spin_alt.value()
        front = self.spin_front.value()
        side  = self.spin_side.value()
        fp_across, fp_along = _footprint_m(sw, sh, fl, alt, landscape)
        across_sensor = sw if landscape else sh
        across_px     = iw if landscape else ih
        return {
            'drone':         self.combo_drone.currentText(),
            'sensor_w': sw, 'sensor_h': sh, 'focal': fl,
            'img_w': iw,    'img_h': ih,    'landscape': landscape,
            'altitude':      alt,
            'front_overlap': front,
            'side_overlap':  side,
            'flight_az':     self.spin_dir.value(),
            'speed_ms':      self.spin_speed.value(),
            'endurance_min': self.spin_endu.value(),
            'margin_pct':    self.spin_margin.value(),
            'fp_across':     fp_across,
            'fp_along':      fp_along,
            'line_spacing':  fp_across * (1.0 - side  / 100.0),
            'photo_spacing': fp_along  * (1.0 - front / 100.0),
            'gsd_cm':        _gsd_cm(across_sensor, across_px, fl, alt),
            'gen_waypoints': self.chk_wp.isChecked(),
            'gen_coverage':  self.chk_cov.isChecked(),
        }


# ─── Tool class ───────────────────────────────────────────────────────────────

class DronePlannerTool:

    def __init__(self, iface):
        self.iface  = iface
        self.canvas = iface.mapCanvas()

    def run(self):
        layer = self.iface.activeLayer()
        if not layer or layer.type() != layer.VectorLayer:
            QMessageBox.warning(
                None, 'RTH Drone Planner',
                'Selecione uma camada vetorial de poligonos.\n'
                'Select a polygon vector layer.')
            return

        if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            QMessageBox.warning(
                None, 'RTH Drone Planner',
                'A camada ativa deve conter poligonos.\n'
                'The active layer must contain polygons.')
            return

        selected = layer.selectedFeatures()
        if not selected:
            QMessageBox.warning(
                None, 'RTH Drone Planner',
                'Selecione ao menos um poligono antes de ativar a ferramenta.\n'
                'Select at least one polygon before activating the tool.')
            return

        geoms     = [f.geometry() for f in selected]
        poly_geom = QgsGeometry.unaryUnion(geoms) if len(geoms) > 1 else geoms[0]
        layer_crs = layer.crs()

        # Detect regional UTM
        centroid = poly_geom.centroid().asPoint()
        wgs84    = QgsCoordinateReferenceSystem('EPSG:4326')
        if layer_crs.authid() != 'EPSG:4326':
            try:
                xf0      = QgsCoordinateTransform(layer_crs, wgs84, QgsProject.instance())
                centroid = xf0.transform(centroid)
            except QgsCsException:  # nosec B110
                pass

        epsg, datum, zone, hemi = detect_regional_utm(centroid.x(), centroid.y())

        dlg = DroneFlightPlannerDialog(
            poly_geom, layer_crs, epsg, datum, zone, hemi,
            self.iface, parent=self.iface.mainWindow())
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

        if dlg.exec_() != QDialog.Accepted:
            return

        self._do_generate(poly_geom, layer_crs, epsg, datum, dlg.flight_params)

    # ── Generation ────────────────────────────────────────────────────────────

    def _do_generate(self, poly_geom, layer_crs, epsg, datum, p):
        utm_crs  = QgsCoordinateReferenceSystem('EPSG:{}'.format(epsg))
        xf       = QgsCoordinateTransform(layer_crs, utm_crs, QgsProject.instance())

        poly_utm = QgsGeometry(poly_geom)
        try:
            poly_utm.transform(xf)
        except QgsCsException as e:
            QMessageBox.critical(None, 'RTH Drone Planner',
                                 'Erro ao reprojetar poligono / Error reprojecting polygon:\n{}'.format(e))
            return

        line_sp  = p['line_spacing']
        photo_sp = p['photo_spacing']

        if line_sp <= 0 or photo_sp <= 0:
            QMessageBox.warning(None, 'RTH Drone Planner',
                                'Parametros invalidos: espacamento de faixas ou de fotos <= 0.\n'
                                'Invalid parameters: line spacing or photo interval <= 0.')
            return

        margin_m = p['fp_across'] * (1.0 + p['margin_pct'] / 100.0) / 2.0

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            flight_lines = _generate_flight_lines(
                poly_utm, p['flight_az'], line_sp, margin_m)
        finally:
            QApplication.restoreOverrideCursor()

        if not flight_lines:
            QMessageBox.warning(None, 'RTH Drone Planner',
                                'Nenhuma faixa de voo gerada. Verifique os parametros.\n'
                                'No flight strips generated. Check parameters.')
            return

        # ── Flight lines layer ────────────────────────────────────────────────
        n_total_photos = 0
        total_dist_m   = 0.0

        lname = 'Linhas_Voo_{:.0f}m_GSD{:.1f}cm_EPSG_{}'.format(
            p['altitude'], p['gsd_cm'], epsg)
        vl = QgsVectorLayer('LineString?crs=EPSG:{}'.format(epsg), lname, 'memory')
        pr = vl.dataProvider()
        pr.addAttributes([
            QgsField('id',          QVariant.Int),
            QgsField('altitude_m',  QVariant.Double),
            QgsField('gsd_cm',      QVariant.Double),
            QgsField('length_m',    QVariant.Double),
            QgsField('n_fotos',     QVariant.Int),
            QgsField('front_ovlp',  QVariant.Double),
            QgsField('side_ovlp',   QVariant.Double),
            QgsField('drone',       QVariant.String),
            QgsField('datum',       QVariant.String),
        ])
        vl.updateFields()

        feats = []
        for i, lg in enumerate(flight_lines, start=1):
            ll   = lg.length()
            nph  = max(1, int(math.ceil(ll / photo_sp)) + 1)
            n_total_photos += nph
            total_dist_m   += ll

            f = QgsFeature(vl.fields())
            f.setGeometry(lg)
            f.setAttribute('id',         i)
            f.setAttribute('altitude_m', p['altitude'])
            f.setAttribute('gsd_cm',     round(p['gsd_cm'], 2))
            f.setAttribute('length_m',   round(ll, 2))
            f.setAttribute('n_fotos',    nph)
            f.setAttribute('front_ovlp', p['front_overlap'])
            f.setAttribute('side_ovlp',  p['side_overlap'])
            f.setAttribute('drone',      p['drone'])
            f.setAttribute('datum',      '{} EPSG:{}'.format(datum, epsg))
            feats.append(f)

        pr.addFeatures(feats)
        vl.updateExtents()
        QgsProject.instance().addMapLayer(vl)
        collapse_layer(vl)

        # ── Connected flight route (boustrophedon) ────────────────────────────
        route_segs = _connect_flight_route(flight_lines)
        if route_segs:
            rname = 'Rota_Voo_{:.0f}m_EPSG_{}'.format(p['altitude'], epsg)
            vl_r  = QgsVectorLayer('LineString?crs=EPSG:{}'.format(epsg), rname, 'memory')
            pr_r  = vl_r.dataProvider()
            pr_r.addAttributes([
                QgsField('id',     QVariant.Int),
                QgsField('tipo',   QVariant.String),   # 'faixa' | 'transito'
                QgsField('alt_m',  QVariant.Double),
                QgsField('dist_m', QVariant.Double),
            ])
            vl_r.updateFields()

            route_feats = []
            for rid, (geom, tipo) in enumerate(route_segs, start=1):
                fr = QgsFeature(vl_r.fields())
                fr.setGeometry(geom)
                fr.setAttribute('id',     rid)
                fr.setAttribute('tipo',   tipo)
                fr.setAttribute('alt_m',  p['altitude'])
                fr.setAttribute('dist_m', round(geom.length(), 2))
                route_feats.append(fr)

            pr_r.addFeatures(route_feats)
            vl_r.updateExtents()

            QgsProject.instance().addMapLayer(vl_r)
            collapse_layer(vl_r)
            _apply_route_style(vl_r)   # after addMapLayer so QGIS does not reset the renderer

        # ── Coverage polygon ──────────────────────────────────────────────────
        if p['gen_coverage']:
            cov = poly_utm.buffer(margin_m, 6)
            cov_name = 'Cobertura_Voo_{:.0f}m_EPSG_{}'.format(p['altitude'], epsg)
            vl_c = QgsVectorLayer('Polygon?crs=EPSG:{}'.format(epsg), cov_name, 'memory')
            pr_c = vl_c.dataProvider()
            pr_c.addAttributes([
                QgsField('id',       QVariant.Int),
                QgsField('alt_m',    QVariant.Double),
                QgsField('gsd_cm',   QVariant.Double),
                QgsField('drone',    QVariant.String),
            ])
            vl_c.updateFields()
            fc = QgsFeature(vl_c.fields())
            fc.setGeometry(cov)
            fc.setAttribute('id',     1)
            fc.setAttribute('alt_m',  p['altitude'])
            fc.setAttribute('gsd_cm', round(p['gsd_cm'], 2))
            fc.setAttribute('drone',  p['drone'])
            pr_c.addFeatures([fc])
            vl_c.updateExtents()
            QgsProject.instance().addMapLayer(vl_c)
            collapse_layer(vl_c)

        # ── Photo waypoints ───────────────────────────────────────────────────
        if p['gen_waypoints']:
            wps     = _generate_waypoints(flight_lines, photo_sp)
            wp_name = 'Waypoints_Foto_{:.0f}m_EPSG_{}'.format(p['altitude'], epsg)
            vl_w = QgsVectorLayer('Point?crs=EPSG:{}'.format(epsg), wp_name, 'memory')
            pr_w = vl_w.dataProvider()
            pr_w.addAttributes([
                QgsField('id',       QVariant.Int),
                QgsField('linha_id', QVariant.Int),
                QgsField('seq',      QVariant.Int),
                QgsField('alt_m',    QVariant.Double),
            ])
            vl_w.updateFields()
            wp_feats = []
            for wid, (pt, lid, seq) in enumerate(wps, start=1):
                fw = QgsFeature(vl_w.fields())
                fw.setGeometry(QgsGeometry.fromPointXY(pt))
                fw.setAttribute('id',       wid)
                fw.setAttribute('linha_id', lid)
                fw.setAttribute('seq',      seq)
                fw.setAttribute('alt_m',    p['altitude'])
                wp_feats.append(fw)
            pr_w.addFeatures(wp_feats)
            vl_w.updateExtents()
            QgsProject.instance().addMapLayer(vl_w)
            collapse_layer(vl_w)

        # ── Summary bar ───────────────────────────────────────────────────────
        est_min   = total_dist_m / p['speed_ms'] / 60.0
        batt_str  = ''
        if p['endurance_min'] > 0:
            batt_str = '  •  {} baterias / batteries'.format(
                math.ceil(est_min / p['endurance_min']))

        self.iface.messageBar().pushMessage(
            'RTH Drone Planner',
            '{} faixas / strips  •  {} fotos / photos  •  '
            'GSD {:.1f} cm/px  •  {}  •  {} — EPSG:{}{}'.format(
                len(flight_lines), n_total_photos,
                p['gsd_cm'], _fmt_min(est_min), datum, epsg, batt_str),
            level=Qgis.MessageLevel.Info, duration=12)
