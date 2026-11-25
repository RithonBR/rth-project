# -*- coding: utf-8 -*-
"""
tool_drone_analysis.py

Drone Flight Analysis — analyzes RTH Drone Planner output layers to compute
battery estimates, flight time, completion time and other operational metrics.
"""

import math
import datetime

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QComboBox, QDoubleSpinBox, QSpinBox, QFrame, QGroupBox,
    QWidget, QScrollArea, QApplication, QMessageBox, QDateTimeEdit,
    QCheckBox,
)
from qgis.PyQt.QtCore import Qt, QDateTime, QCoreApplication
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
)


# ─── Drone presets  (name, battery_min, speed_ms, reserve_pct) ───────────────
# battery_min  = maximum usable flight time per battery (minutes, manufacturer spec)
# speed_ms     = typical mapping speed (m/s)
# reserve_pct  = recommended reserve to keep in battery (%)

DRONE_ANALYSIS_PRESETS = [
    ('Personalizado / Custom',        30, 10.0, 20),
    ('DJI Phantom 4 RTK',             30, 10.0, 20),
    ('DJI Phantom 4 Pro V2',          30, 12.0, 20),
    ('DJI Mavic 3E Enterprise',       45, 15.0, 20),
    ('DJI Mavic 3M Multispectral',    43, 15.0, 20),
    ('DJI Matrice 350 RTK + P1 35mm', 55, 15.0, 20),
    ('DJI Matrice 300 RTK + P1 35mm', 45, 15.0, 20),
    ('DJI Matrice 350 RTK + L2',      55, 15.0, 20),
    ('DJI Air 2S',                    31, 10.0, 20),
    ('DJI Mavic 2 Pro',               31, 10.0, 20),
    ('DJI Mini 3 Pro',                34,  8.0, 20),
    ('DJI Mini 4 Pro',                34,  8.0, 20),
    ('Parrot ANAFI USA',              32, 10.0, 20),
    ('Autel EVO II Pro 6K',           42, 12.0, 20),
    ('WingtraOne GEN II',             55, 16.0, 15),
]

_PRESET_MAP = {name: (bmin, spd, res) for name, bmin, spd, res in DRONE_ANALYSIS_PRESETS}


# ─── Formatters ───────────────────────────────────────────────────────────────

def _fmt_time(minutes):
    h = int(minutes // 60)
    m = int(round(minutes % 60))
    if m == 60:
        h += 1; m = 0
    return '{}h {:02d}min'.format(h, m) if h > 0 else '{:.0f} min'.format(minutes)


def _fmt_km(m):
    if m >= 1000:
        return '{:.2f} km'.format(m / 1000)
    return '{:.0f} m'.format(m)


def _fmt_ha(val):
    return '{:,.2f} ha'.format(val).replace(',', '.')


def _quality_label(score):
    if score >= 90: return 'Excelente / Excellent', '#2e7d32'
    if score >= 75: return 'Bom / Good',            '#558b2f'
    if score >= 55: return 'Regular / Fair',        '#f57c00'
    if score >= 35: return 'Fraco / Poor',          '#e65100'
    return 'Critico / Critical',                    '#c62828'


def _gsd_label(gsd_cm):
    if gsd_cm <= 2.0:  return 'Muito alta / Very high', '#2e7d32'
    if gsd_cm <= 5.0:  return 'Alta / High',             '#558b2f'
    if gsd_cm <= 10.0: return 'Media / Medium',          '#f57c00'
    return 'Baixa / Low',                                '#c62828'


# ─── Core computation ─────────────────────────────────────────────────────────

def compute_drone_metrics(lines_layer, coverage_layer,
                          speed_ms, battery_min, reserve_pct,
                          n_batteries_avail, swap_time_min,
                          start_dt=None):
    """Compute drone operational metrics. Returns flat dict. Raises RuntimeError on failure."""

    feats = [f for f in lines_layer.getFeatures()
             if f.geometry() and not f.geometry().isNull()]
    if not feats:
        raise RuntimeError('Nenhuma feicao com geometria / No features with geometry')

    n_lines = len(feats)
    src_crs = lines_layer.crs()

    # ── Project to metric CRS ──────────────────────────────────────────────────
    if src_crs.isGeographic():
        try:
            from core.rth_utm_utils import detect_regional_utm
            c0 = feats[0].geometry().centroid().asPoint()
            wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
            if src_crs.authid() != 'EPSG:4326':
                t0 = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
                c0 = t0.transform(c0)
            epsg, *_ = detect_regional_utm(c0.x(), c0.y())
            metric_crs = QgsCoordinateReferenceSystem('EPSG:{}'.format(epsg))
        except Exception:
            metric_crs = QgsCoordinateReferenceSystem('EPSG:3857')
    else:
        metric_crs = src_crs

    xf = QgsCoordinateTransform(src_crs, metric_crs, QgsProject.instance())

    # ── Total distance from geometry ────────────────────────────────────────────
    total_length_m = 0.0
    for f in feats:
        g = f.geometry()
        g.transform(xf)
        total_length_m += g.length()

    # ── Read attributes from first feature ──────────────────────────────────────
    first = feats[0]
    fields = {field.name(): True for field in lines_layer.fields()}

    def _attr(feat, name, default=None):
        if name in fields:
            v = feat[name]
            if v is not None and v != '' and str(v) != 'NULL':
                try:
                    return float(v)
                except (ValueError, TypeError):
                    pass
        return default

    altitude_m = _attr(first, 'altitude_m', None)
    gsd_cm     = _attr(first, 'gsd_cm',     None)

    # ── Count photos ────────────────────────────────────────────────────────────
    total_photos = None
    if 'n_fotos' in fields:
        total_photos = 0
        for f in feats:
            v = _attr(f, 'n_fotos', 0)
            if v is not None:
                total_photos += int(v)

    # ── Coverage area from coverage layer ────────────────────────────────────────
    coverage_ha = None
    if coverage_layer is not None:
        cfts = [f for f in coverage_layer.getFeatures()
                if f.geometry() and not f.geometry().isNull()]
        if cfts:
            cxf = QgsCoordinateTransform(coverage_layer.crs(), metric_crs, QgsProject.instance())
            area = 0.0
            for cf in cfts:
                cg = cf.geometry()
                cg.transform(cxf)
                area += cg.area()
            coverage_ha = area / 10_000

            # Also read n_fotos_est if available
            if total_photos is None:
                cfields = {field.name(): True for field in coverage_layer.fields()}
                if 'n_fotos_est' in cfields:
                    nfe = _attr(cfts[0], 'n_fotos_est', None)
                    if nfe is not None:
                        total_photos = int(nfe)

    # ── Flight time ──────────────────────────────────────────────────────────────
    if speed_ms <= 0:
        raise RuntimeError('Velocidade invalida / Invalid speed')
    flight_time_min = total_length_m / speed_ms / 60.0

    # ── Battery math ──────────────────────────────────────────────────────────────
    # Usable time = battery spec * (1 - reserve%)
    usable_min = battery_min * (1.0 - reserve_pct / 100.0)
    if usable_min <= 0:
        usable_min = battery_min * 0.8

    n_batteries_needed = max(1, math.ceil(flight_time_min / usable_min))
    batteries_shortfall = max(0, n_batteries_needed - n_batteries_avail)
    batteries_sufficient = (batteries_shortfall == 0)

    # ── Ground time (battery swaps) ───────────────────────────────────────────────
    n_swaps          = max(0, n_batteries_needed - 1)
    swap_total_min   = n_swaps * swap_time_min
    total_oper_min   = flight_time_min + swap_total_min

    # ── Per-battery metrics ───────────────────────────────────────────────────────
    dist_per_batt_m  = total_length_m / n_batteries_needed
    area_per_batt_ha = (coverage_ha / n_batteries_needed) if coverage_ha else None
    photos_per_batt  = (total_photos / n_batteries_needed) if total_photos else None

    # ── Completion time ────────────────────────────────────────────────────────────
    completion_dt = None
    if start_dt is not None:
        try:
            completion_dt = start_dt + datetime.timedelta(minutes=total_oper_min)
        except Exception:
            pass

    # ── Operational efficiency ────────────────────────────────────────────────────
    op_efficiency_pct = (flight_time_min / total_oper_min * 100.0
                         if total_oper_min > 0 else 100.0)

    # ── Overall score ──────────────────────────────────────────────────────────────
    score_comps = []
    score_comps.append((min(100.0, op_efficiency_pct), 0.4))
    if batteries_sufficient:
        score_comps.append((100.0, 0.3))
    else:
        shortfall_pct = max(0, 100.0 - batteries_shortfall / n_batteries_needed * 100)
        score_comps.append((shortfall_pct, 0.3))
    if gsd_cm is not None:
        gsd_score = max(0, min(100, 100 - (gsd_cm - 2) * 8))
        score_comps.append((gsd_score, 0.3))
    w_sum = sum(w for _, w in score_comps)
    op_score = round(sum(v * w / w_sum for v, w in score_comps))

    return {
        'n_lines':             n_lines,
        'total_length_m':      total_length_m,
        'flight_time_min':     flight_time_min,
        'speed_ms':            speed_ms,
        'battery_min':         battery_min,
        'reserve_pct':         reserve_pct,
        'usable_min':          usable_min,
        'n_batteries_needed':  n_batteries_needed,
        'n_batteries_avail':   n_batteries_avail,
        'batteries_shortfall': batteries_shortfall,
        'batteries_sufficient': batteries_sufficient,
        'n_swaps':             n_swaps,
        'swap_time_min':       swap_time_min,
        'swap_total_min':      swap_total_min,
        'total_oper_min':      total_oper_min,
        'dist_per_batt_m':     dist_per_batt_m,
        'area_per_batt_ha':    area_per_batt_ha,
        'photos_per_batt':     photos_per_batt,
        'total_photos':        total_photos,
        'coverage_ha':         coverage_ha,
        'altitude_m':          altitude_m,
        'gsd_cm':              gsd_cm,
        'op_efficiency_pct':   op_efficiency_pct,
        'op_score':            op_score,
        'start_dt':            start_dt,
        'completion_dt':       completion_dt,
        'metric_crs':          metric_crs.authid(),
    }


# ─── Results window ───────────────────────────────────────────────────────────

class DroneResultsDialog(QDialog):

    def __init__(self, metrics, layer_name, iface, parent=None):
        super().__init__(parent)
        self._metrics    = metrics
        self._iface      = iface
        self._layer_name = layer_name

        self.setWindowTitle('RTH Analise de Voo — {}'.format(layer_name))
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint |
                            Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(600)
        self.setMinimumHeight(300)
        self.setMaximumHeight(820)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(6)

        lbl_title = QLabel('Analise de Voo / Flight Analysis')
        lbl_title.setStyleSheet('font-size:13px;font-weight:bold;')
        root.addWidget(lbl_title)
        lbl_sub = QLabel(layer_name)
        lbl_sub.setStyleSheet('color:#555;font-size:10px;')
        lbl_sub.setWordWrap(True)
        root.addWidget(lbl_sub)
        root.addWidget(self._sep())

        inner = QWidget()
        inner.setStyleSheet(
            'QWidget{background:#f5f8ff;border:1px solid #d0d8ef;border-radius:4px;}')
        self._grid = QGridLayout(inner)
        self._grid.setContentsMargins(10, 8, 10, 8)
        self._grid.setVerticalSpacing(3)
        self._grid.setHorizontalSpacing(16)
        self._grid.setColumnStretch(1, 1)
        root.addWidget(inner)
        root.addStretch()

        btn_copy = QPushButton('Copiar Relatorio / Copy Report')
        btn_copy.setMinimumHeight(32)
        btn_copy.setStyleSheet(
            'QPushButton{background:#fff;color:#1a73e8;font-weight:bold;'
            'font-size:11px;border:1px solid #1a73e8;border-radius:4px;margin:6px;}'
            'QPushButton:hover{background:#e8f0fe;}')
        btn_copy.clicked.connect(self._on_copy)
        outer.addWidget(btn_copy)

        self._build_grid(metrics)

    def _sep(self):
        ln = QFrame()
        ln.setFrameShape(QFrame.HLine)
        ln.setFrameShadow(QFrame.Sunken)
        return ln

    def _build_grid(self, m):
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        row = [0]

        def section(title):
            lbl = QLabel(title)
            lbl.setStyleSheet('font-weight:bold;font-size:10px;color:#1a73e8;padding-top:6px;')
            self._grid.addWidget(lbl, row[0], 0, 1, 2)
            row[0] += 1

        def hsep():
            s = QFrame()
            s.setFrameShape(QFrame.HLine)
            s.setFrameShadow(QFrame.Sunken)
            s.setStyleSheet('border:none;background:#d0d8ef;')
            s.setFixedHeight(1)
            self._grid.addWidget(s, row[0], 0, 1, 2)
            row[0] += 1

        def add(name, value, color=None):
            ln = QLabel(name + ':')
            ln.setStyleSheet('color:#555;font-size:10px;')
            lv = QLabel(str(value))
            lv.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            st = 'font-weight:bold;font-size:10px;'
            if color:
                st += 'color:{};'.format(color)
            lv.setStyleSheet(st)
            lv.setWordWrap(True)
            self._grid.addWidget(ln, row[0], 0)
            self._grid.addWidget(lv, row[0], 1)
            row[0] += 1

        # ── Distância / Distance ───────────────────────────────────────────────
        section('DISTANCIA / DISTANCE')
        add('Linhas de voo / Flight lines', str(m['n_lines']))
        total_km = m['total_length_m'] / 1000
        add('Metros lineares / Linear meters',
            '{:,.0f} m  ({:.2f} km)'.format(m['total_length_m'], total_km).replace(',', '.'))
        add('Velocidade / Speed', '{:.1f} m/s  ({:.1f} km/h)'.format(
            m['speed_ms'], m['speed_ms'] * 3.6))

        hsep()
        section('TEMPO DE VOO / FLIGHT TIME')
        add('Tempo de voo / Flight time', _fmt_time(m['flight_time_min']))
        if m['swap_total_min'] > 0:
            add('Trocas de bateria / Battery swaps', str(m['n_swaps']))
            add('Tempo de troca total / Total swap time', _fmt_time(m['swap_total_min']))
        add('Tempo operacional total / Total operation time', _fmt_time(m['total_oper_min']))
        eff_c = '#2e7d32' if m['op_efficiency_pct'] >= 85 else (
                '#f57c00' if m['op_efficiency_pct'] >= 65 else '#c62828')
        add('Eficiencia operacional / Op. efficiency',
            '{:.1f}%'.format(m['op_efficiency_pct']), eff_c)

        if m['start_dt'] is not None:
            add('Inicio / Start', m['start_dt'].strftime('%d/%m/%Y %H:%M'))
        if m['completion_dt'] is not None:
            add('Conclusao estimada / Est. completion',
                m['completion_dt'].strftime('%d/%m/%Y %H:%M'))

        hsep()
        section('BATERIAS / BATTERIES')
        add('Autonomia configurada / Battery endurance', '{:.0f} min'.format(m['battery_min']))
        add('Reserva / Reserve', '{:.0f}%'.format(m['reserve_pct']))
        add('Tempo util por bateria / Usable time/battery', '{:.1f} min'.format(m['usable_min']))
        batt_c = '#2e7d32' if m['batteries_sufficient'] else '#c62828'
        add('Baterias necessarias / Batteries needed', str(m['n_batteries_needed']), batt_c)
        add('Baterias disponiveis / Available batteries', str(m['n_batteries_avail']))
        if m['batteries_shortfall'] > 0:
            add('Deficit de baterias / Battery shortfall',
                str(m['batteries_shortfall']), '#c62828')
        else:
            add('Status baterias / Battery status',
                'Suficiente / Sufficient  (+{})'.format(
                    m['n_batteries_avail'] - m['n_batteries_needed']), '#2e7d32')

        hsep()
        section('POR BATERIA / PER BATTERY')
        add('Distancia por bateria / Distance per battery',
            _fmt_km(m['dist_per_batt_m']))
        if m['area_per_batt_ha'] is not None:
            add('Area por bateria / Area per battery',
                _fmt_ha(m['area_per_batt_ha']))
        if m['photos_per_batt'] is not None:
            add('Fotos por bateria / Photos per battery',
                '{:,.0f}'.format(m['photos_per_batt']).replace(',', '.'))

        if m['total_photos'] is not None or m['coverage_ha'] is not None:
            hsep()
            section('COBERTURA / COVERAGE')
        if m['total_photos'] is not None:
            add('Fotos estimadas / Est. photos',
                '{:,.0f}'.format(m['total_photos']).replace(',', '.'))
        if m['coverage_ha'] is not None:
            add('Area de cobertura / Coverage area', _fmt_ha(m['coverage_ha']))

        if m['altitude_m'] is not None or m['gsd_cm'] is not None:
            hsep()
            section('QUALIDADE / QUALITY')
        if m['altitude_m'] is not None:
            add('Altitude AGL', '{:.0f} m'.format(m['altitude_m']))
        if m['gsd_cm'] is not None:
            gl, gc = _gsd_label(m['gsd_cm'])
            add('GSD', '{:.2f} cm/px  [{}]'.format(m['gsd_cm'], gl), gc)

        hsep()
        section('SCORE OPERACIONAL / OPERATIONAL SCORE')
        sl, sc = _quality_label(m['op_score'])
        add('Score geral / Overall score',
            '{}  [{}]'.format(m['op_score'], sl), sc)

    def _on_copy(self):
        m  = self._metrics
        ln = '\n'
        lines_out = [
            'RTH Analise de Voo / Flight Analysis',
            'Camada / Layer: {}'.format(self._layer_name),
            '',
            '-- DISTANCIA / DISTANCE --',
            'Linhas de voo: {}'.format(m['n_lines']),
            'Metros lineares: {:.0f} m  ({:.2f} km)'.format(
                m['total_length_m'], m['total_length_m'] / 1000),
            'Velocidade: {:.1f} m/s  ({:.1f} km/h)'.format(
                m['speed_ms'], m['speed_ms'] * 3.6),
            '',
            '-- TEMPO / TIME --',
            'Tempo de voo: {}'.format(_fmt_time(m['flight_time_min'])),
            'Tempo operacional total: {}'.format(_fmt_time(m['total_oper_min'])),
            'Eficiencia operacional: {:.1f}%'.format(m['op_efficiency_pct']),
        ]
        if m['start_dt']:
            lines_out.append('Inicio: {}'.format(m['start_dt'].strftime('%d/%m/%Y %H:%M')))
        if m['completion_dt']:
            lines_out.append('Conclusao estimada: {}'.format(
                m['completion_dt'].strftime('%d/%m/%Y %H:%M')))
        lines_out += [
            '',
            '-- BATERIAS / BATTERIES --',
            'Baterias necessarias: {}'.format(m['n_batteries_needed']),
            'Baterias disponiveis: {}'.format(m['n_batteries_avail']),
            'Tempo util por bateria: {:.1f} min'.format(m['usable_min']),
        ]
        if m['total_photos'] is not None:
            lines_out.append('Fotos estimadas: {:,.0f}'.format(m['total_photos']))
        if m['coverage_ha'] is not None:
            lines_out.append('Area de cobertura: {}'.format(_fmt_ha(m['coverage_ha'])))
        if m['gsd_cm'] is not None:
            lines_out.append('GSD: {:.2f} cm/px'.format(m['gsd_cm']))

        QApplication.clipboard().setText(ln.join(lines_out))
        self._iface.messageBar().pushMessage(
            'RTH', 'Relatorio copiado / Report copied',
            level=Qgis.MessageLevel.Info, duration=2)


# ─── Input dialog ─────────────────────────────────────────────────────────────

class DroneAnalysisDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._results_dlg = None

        self.setWindowTitle('RTH — Analise de Voo para Drones / Drone Flight Analysis')
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(640)
        self.setMinimumHeight(700)
        self.setMaximumHeight(800)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Header
        lbl_t = QLabel('Analise de Voo para Drones / Drone Flight Analysis')
        lbl_t.setAlignment(Qt.AlignCenter)
        lbl_t.setStyleSheet('font-size:13px;font-weight:bold;')
        root.addWidget(lbl_t)
        lbl_s = QLabel('Selecione as camadas geradas pelo Planejador de Voo para Drones')
        lbl_s.setAlignment(Qt.AlignCenter)
        lbl_s.setStyleSheet('color:#666;font-size:10px;')
        lbl_s.setWordWrap(True)
        root.addWidget(lbl_s)
        root.addWidget(self._sep())

        # ── Layers ──────────────────────────────────────────────────────────────
        grp_layers = QGroupBox('Camadas / Layers')
        gl = QGridLayout()
        gl.setContentsMargins(8, 6, 8, 8)
        gl.setSpacing(5)
        gl.setColumnStretch(1, 1)

        gl.addWidget(QLabel('Linhas de voo * / Flight lines *:'), 0, 0)
        self.combo_lines = QComboBox()
        gl.addWidget(self.combo_lines, 0, 1)

        gl.addWidget(QLabel('Cobertura (opcional) / Coverage:'), 1, 0)
        self.combo_coverage = QComboBox()
        gl.addWidget(self.combo_coverage, 1, 1)

        grp_layers.setLayout(gl)
        root.addWidget(grp_layers)

        # ── Drone preset ────────────────────────────────────────────────────────
        grp_drone = QGroupBox('Drone / Preset')
        gd = QVBoxLayout()
        gd.setContentsMargins(8, 6, 8, 8)
        gd.setSpacing(5)

        self.combo_drone = QComboBox()
        for name, *_ in DRONE_ANALYSIS_PRESETS:
            self.combo_drone.addItem(name)
        self.combo_drone.currentIndexChanged.connect(self._on_preset_changed)
        gd.addWidget(self.combo_drone)

        grp_drone.setLayout(gd)
        root.addWidget(grp_drone)

        # ── Flight parameters ────────────────────────────────────────────────────
        grp_fp = QGroupBox('Parametros / Parameters')
        gfp = QGridLayout()
        gfp.setContentsMargins(8, 6, 8, 8)
        gfp.setSpacing(5)
        gfp.setColumnStretch(1, 1)

        def _lbl(text, row):
            l = QLabel(text)
            l.setStyleSheet('font-size:10px;')
            gfp.addWidget(l, row, 0)

        _lbl('Velocidade / Speed (m/s):', 0)
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(1.0, 30.0)
        self.spin_speed.setValue(10.0)
        self.spin_speed.setSuffix(' m/s')
        self.spin_speed.setDecimals(1)
        self.spin_speed.setSingleStep(0.5)
        gfp.addWidget(self.spin_speed, 0, 1)

        _lbl('Autonomia / Battery endurance (min):', 1)
        self.spin_batt = QDoubleSpinBox()
        self.spin_batt.setRange(1.0, 120.0)
        self.spin_batt.setValue(30.0)
        self.spin_batt.setSuffix(' min')
        self.spin_batt.setDecimals(0)
        self.spin_batt.setSingleStep(1)
        gfp.addWidget(self.spin_batt, 1, 1)

        _lbl('Reserva / Reserve (%):', 2)
        self.spin_reserve = QDoubleSpinBox()
        self.spin_reserve.setRange(0.0, 50.0)
        self.spin_reserve.setValue(20.0)
        self.spin_reserve.setSuffix(' %')
        self.spin_reserve.setDecimals(0)
        self.spin_reserve.setSingleStep(5)
        gfp.addWidget(self.spin_reserve, 2, 1)

        _lbl('Baterias disponiveis / Available batteries:', 3)
        self.spin_avail = QSpinBox()
        self.spin_avail.setRange(1, 50)
        self.spin_avail.setValue(3)
        gfp.addWidget(self.spin_avail, 3, 1)

        _lbl('Tempo troca / Swap time (min):', 4)
        self.spin_swap = QDoubleSpinBox()
        self.spin_swap.setRange(0.0, 30.0)
        self.spin_swap.setValue(5.0)
        self.spin_swap.setSuffix(' min')
        self.spin_swap.setDecimals(0)
        self.spin_swap.setSingleStep(1)
        gfp.addWidget(self.spin_swap, 4, 1)

        grp_fp.setLayout(gfp)
        root.addWidget(grp_fp)

        # ── Start time ──────────────────────────────────────────────────────────
        grp_time = QGroupBox('Hora de Inicio / Start Time (opcional)')
        gt = QVBoxLayout()
        gt.setContentsMargins(8, 6, 8, 8)
        gt.setSpacing(4)

        self.chk_start = QCheckBox('Calcular hora de conclusao / Calculate completion time')
        self.chk_start.setStyleSheet('font-size:10px;')
        self.chk_start.toggled.connect(self._on_start_toggled)
        gt.addWidget(self.chk_start)

        self.dt_start = QDateTimeEdit()
        self.dt_start.setDisplayFormat('dd/MM/yyyy HH:mm')
        self.dt_start.setDateTime(QDateTime.currentDateTime())
        self.dt_start.setEnabled(False)
        gt.addWidget(self.dt_start)

        grp_time.setLayout(gt)
        root.addWidget(grp_time)

        # ── Run button (always visible outside scroll) ──────────────────────────
        outer.addWidget(self._sep())
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 6, 12, 12)

        self.btn_run = QPushButton('Analisar Voo / Analyse Flight')
        self.btn_run.setMinimumHeight(38)
        self.btn_run.setStyleSheet(
            'QPushButton{background:#1976d2;color:white;font-weight:bold;'
            'font-size:12px;border-radius:5px;border:none;}'
            'QPushButton:hover{background:#1565c0;}'
            'QPushButton:disabled{background:#5a7fa8;color:#aaa;}')
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)

        btn_close = QPushButton('Fechar / Close')
        btn_close.setMinimumHeight(38)
        btn_close.setStyleSheet(
            'QPushButton{background:#616161;color:white;border:none;'
            'border-radius:5px;}'
            'QPushButton:hover{background:#424242;}')
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)

        outer.addLayout(btn_row)

        self._populate_layers()
        self._on_preset_changed()

    def _sep(self):
        ln = QFrame()
        ln.setFrameShape(QFrame.HLine)
        ln.setFrameShadow(QFrame.Sunken)
        return ln

    def _populate_layers(self):
        line_types = {QgsWkbTypes.LineGeometry}
        poly_types = {QgsWkbTypes.PolygonGeometry}

        self.combo_lines.clear()
        self.combo_coverage.clear()
        self.combo_coverage.addItem('(nenhum / none)', None)

        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            gt = layer.geometryType()
            if gt in line_types:
                self.combo_lines.addItem(layer.name(), layer.id())
            if gt in poly_types:
                self.combo_coverage.addItem(layer.name(), layer.id())

    def _on_preset_changed(self):
        name = self.combo_drone.currentText()
        data = _PRESET_MAP.get(name)
        if data is None:
            return
        bmin, spd, res = data
        self.spin_batt.blockSignals(True)
        self.spin_speed.blockSignals(True)
        self.spin_reserve.blockSignals(True)
        self.spin_batt.setValue(bmin)
        self.spin_speed.setValue(spd)
        self.spin_reserve.setValue(res)
        self.spin_batt.blockSignals(False)
        self.spin_speed.blockSignals(False)
        self.spin_reserve.blockSignals(False)

    def _on_start_toggled(self, checked):
        self.dt_start.setEnabled(checked)

    def _on_run(self):
        if self.combo_lines.count() == 0:
            QMessageBox.warning(self, 'RTH',
                'Nenhuma camada de linhas disponivel.\n'
                'No flight lines layer available.')
            return

        lines_id = self.combo_lines.currentData()
        lines_layer = QgsProject.instance().mapLayer(lines_id) if lines_id else None
        if lines_layer is None:
            QMessageBox.warning(self, 'RTH', 'Camada de linhas nao encontrada / Lines layer not found.')
            return

        cov_id = self.combo_coverage.currentData()
        coverage_layer = QgsProject.instance().mapLayer(cov_id) if cov_id else None

        start_dt = None
        if self.chk_start.isChecked():
            qdt = self.dt_start.dateTime()
            py_dt = qdt.toPyDateTime() if hasattr(qdt, 'toPyDateTime') else None
            if py_dt is None:
                try:
                    py_dt = datetime.datetime(
                        qdt.date().year(), qdt.date().month(), qdt.date().day(),
                        qdt.time().hour(), qdt.time().minute())
                except Exception:
                    py_dt = None
            start_dt = py_dt

        try:
            m = compute_drone_metrics(
                lines_layer      = lines_layer,
                coverage_layer   = coverage_layer,
                speed_ms         = self.spin_speed.value(),
                battery_min      = self.spin_batt.value(),
                reserve_pct      = self.spin_reserve.value(),
                n_batteries_avail= self.spin_avail.value(),
                swap_time_min    = self.spin_swap.value(),
                start_dt         = start_dt,
            )
        except RuntimeError as e:
            QMessageBox.warning(self, 'RTH Analise de Voo', str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, 'RTH Analise de Voo',
                'Erro inesperado / Unexpected error:\n{}'.format(str(e)))
            return

        if self._results_dlg is not None and self._results_dlg.isVisible():
            self._results_dlg.close()
        self._results_dlg = DroneResultsDialog(
            m, self.combo_lines.currentText(), self.iface, parent=self)
        self._results_dlg.show()


# ─── Tool class ───────────────────────────────────────────────────────────────

class DroneAnalysisTool:

    def __init__(self, iface):
        self.iface   = iface
        self._dialog = None

    def run(self):
        if self._dialog is None or not self._dialog.isVisible():
            self._dialog = DroneAnalysisDialog(self.iface)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
        self._dialog._populate_layers()
