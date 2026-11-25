# -*- coding: utf-8 -*-
import math
import statistics

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QDoubleSpinBox, QFrame, QWidget,
    QApplication, QGroupBox, QScrollArea, QTableWidget,
    QTableWidgetItem, QHeaderView,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
)


# ─── Geometric helpers ────────────────────────────────────────────────────────

def _line_endpoints(geom):
    if geom.isMultipart():
        parts = geom.asMultiPolyline()
        if parts:
            return parts[0][0], parts[-1][-1]
    else:
        pts = geom.asPolyline()
        if pts:
            return pts[0], pts[-1]
    return None, None


def _geo_azimuth_deg(p1, p2):
    dx = p2.x() - p1.x()
    dy = p2.y() - p1.y()
    return math.degrees(math.atan2(dx, dy)) % 360


def _normalize_az(az):
    return az % 180


def _circular_mean_180(angles_deg):
    sin_s = sum(math.sin(math.radians(2 * a)) for a in angles_deg)
    cos_s = sum(math.cos(math.radians(2 * a)) for a in angles_deg)
    return math.degrees(math.atan2(sin_s, cos_s)) / 2.0 % 180


def _angular_diff_180(a, b):
    d = abs(a - b) % 180
    return min(d, 180 - d)


# ─── Scoring helpers ──────────────────────────────────────────────────────────

def _parallelism_score(std_deg):
    if std_deg < 0.5:  return 100
    if std_deg < 1.0:  return 85
    if std_deg < 2.0:  return 70
    if std_deg < 3.5:  return 50
    if std_deg < 5.0:  return 30
    return 10


def _spacing_score(cv_pct):
    if cv_pct < 3.0:   return 100
    if cv_pct < 5.0:   return 85
    if cv_pct < 10.0:  return 70
    if cv_pct < 15.0:  return 50
    if cv_pct < 20.0:  return 30
    return 10


def _quality_label(score):
    if score >= 90: return 'Excelente / Excellent', '#2e7d32'
    if score >= 75: return 'Bom / Good',            '#558b2f'
    if score >= 55: return 'Regular / Fair',        '#f57c00'
    if score >= 35: return 'Fraco / Poor',          '#e65100'
    return 'Critico / Critical',                    '#c62828'


def _parallelism_quality(std_deg):
    if std_deg < 1.0:  return 'Excelente / Excellent', '#2e7d32'
    if std_deg < 3.0:  return 'Bom / Good', '#558b2f'
    if std_deg < 5.0:  return 'Regular / Fair', '#f57c00'
    return 'Irregular / Poor', '#c62828'


def _spacing_quality(cv_pct):
    if cv_pct < 5.0:   return 'Uniforme / Uniform', '#2e7d32'
    if cv_pct < 10.0:  return 'Aceitavel / Acceptable', '#558b2f'
    if cv_pct < 20.0:  return 'Variavel / Variable', '#f57c00'
    return 'Muito variavel / Very variable', '#c62828'


# ─── Formatters ───────────────────────────────────────────────────────────────

def _fmt_time(hours):
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        h += 1; m = 0
    return '{}h {:02d}min'.format(h, m) if h > 0 else '{}min'.format(m)


def _fmt_m(val):
    return '{:,.2f} m'.format(val).replace(',', '.')


def _fmt_ha(val):
    return '{:,.4f} ha'.format(val).replace(',', '.')


def _fmt_pct(val):
    return '{:.1f}%'.format(val)


def _fmt_brl(val):
    return 'R$ {:,.2f}'.format(val).replace(',', 'X').replace('.', ',').replace('X', '.')


# ─── Core computation ─────────────────────────────────────────────────────────

def compute_metrics(layer, speed_kmh, poly_layer=None, turns_layer=None,
                    cost_per_hour=0.0, fuel_l_ha=0.0, fuel_price=0.0):
    """Compute all line metrics. Returns a flat dict. Raises RuntimeError on failure."""

    feats = [f for f in layer.getFeatures()
             if f.geometry() and not f.geometry().isNull()]
    if not feats:
        raise RuntimeError('Nenhuma feicao com geometria / No features with geometry')

    n = len(feats)
    src_crs = layer.crs()

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
    geoms = []
    for f in feats:
        g = f.geometry()
        g.transform(xf)
        geoms.append(g)

    # ── Lengths ───────────────────────────────────────────────────────────────
    lengths      = [g.length() for g in geoms]
    total_length = sum(lengths)
    mean_length  = statistics.mean(lengths)
    min_length   = min(lengths)
    max_length   = max(lengths)
    std_length   = statistics.stdev(lengths) if n > 1 else 0.0

    # ── Azimuths ──────────────────────────────────────────────────────────────
    azs = []
    for g in geoms:
        p1, p2 = _line_endpoints(g)
        if p1 and p2:
            azs.append(_normalize_az(_geo_azimuth_deg(p1, p2)))

    if azs:
        mean_az = _circular_mean_180(azs)
        diffs   = [_angular_diff_180(a, mean_az) for a in azs]
        std_az  = statistics.stdev(diffs) if len(diffs) > 1 else 0.0
    else:
        mean_az = std_az = 0.0

    # ── Spacing ───────────────────────────────────────────────────────────────
    mean_spacing = std_spacing = cv_spacing = None

    if n >= 2 and azs:
        theta = math.radians(mean_az)
        pos   = sorted(
            -g.centroid().asPoint().x() * math.cos(theta)
            + g.centroid().asPoint().y() * math.sin(theta)
            for g in geoms
        )
        sps = [pos[i+1] - pos[i] for i in range(len(pos)-1) if pos[i+1]-pos[i] > 0.01]
        if sps:
            mean_spacing = statistics.mean(sps)
            std_spacing  = statistics.stdev(sps) if len(sps) > 1 else 0.0
            cv_spacing   = std_spacing / mean_spacing * 100 if mean_spacing else 0.0

    # ── Estimated covered area ─────────────────────────────────────────────────
    est_area_ha = (total_length * mean_spacing / 10_000) if mean_spacing else None

    # ── Quality scores ─────────────────────────────────────────────────────────
    ps = _parallelism_score(std_az)
    ss = _spacing_score(cv_spacing) if cv_spacing is not None else ps
    planting_quality_score = round((ps + ss) / 2)

    # ── Time (lines only) ──────────────────────────────────────────────────────
    # Tempo = distância total / velocidade  (independe do nº de linhas)
    # Time = total distance / speed  (independent of number of lines)
    speed_ms     = speed_kmh * 1000.0 / 3600.0   # m/s
    lines_time_h = total_length / speed_ms / 3600.0
    n_maneuvers  = n - 1

    # ── Polygon — field area ───────────────────────────────────────────────────
    polygon_area_ha = useful_area_pct = lost_area_pct = None
    if poly_layer is not None:
        pfts = [f for f in poly_layer.getFeatures()
                if f.geometry() and not f.geometry().isNull()]
        if pfts:
            pxf  = QgsCoordinateTransform(poly_layer.crs(), metric_crs, QgsProject.instance())
            area = 0.0
            for pf in pfts:
                pg = pf.geometry()
                pg.transform(pxf)
                area += pg.area()
            polygon_area_ha = area / 10_000
            if est_area_ha and polygon_area_ha > 0:
                useful_area_pct = min(100.0, est_area_ha / polygon_area_ha * 100)
                lost_area_pct   = 100.0 - useful_area_pct

    # ── Turns layer ────────────────────────────────────────────────────────────
    has_turns         = False
    turns_n           = None
    turns_length_m    = None
    real_total_dist_m = None
    turns_time_h      = None
    op_efficiency_pct = None

    if turns_layer is not None:
        tfts = [f for f in turns_layer.getFeatures()
                if f.geometry() and not f.geometry().isNull()]
        if tfts:
            has_turns = True
            turns_n   = len(tfts)
            txf       = QgsCoordinateTransform(
                turns_layer.crs(), metric_crs, QgsProject.instance())
            t_lens = []
            for tf in tfts:
                tg = tf.geometry()
                tg.transform(txf)
                t_lens.append(tg.length())
            turns_length_m    = sum(t_lens)
            real_total_dist_m = total_length + turns_length_m
            turns_time_h      = turns_length_m / speed_ms / 3600.0
            op_efficiency_pct = total_length / real_total_dist_m * 100

    # ── Total time ─────────────────────────────────────────────────────────────
    total_time_h = lines_time_h + (turns_time_h or 0.0)

    # ── Field efficiency index ─────────────────────────────────────────────────
    comps = [(planting_quality_score, 0.40)]
    if useful_area_pct is not None:
        comps.append((useful_area_pct, 0.35))
    if op_efficiency_pct is not None:
        comps.append((op_efficiency_pct, 0.25))
    w_sum = sum(w for _, w in comps)
    field_efficiency_index = round(sum(v * w / w_sum for v, w in comps))

    # ── Cost ───────────────────────────────────────────────────────────────────
    has_cost = cost_per_hour > 0 or (fuel_l_ha > 0 and fuel_price > 0)
    op_cost_total = cost_per_ha = cost_lost_turns = None

    if has_cost:
        area_ref  = polygon_area_ha or est_area_ha
        fuel_cost = (area_ref * fuel_l_ha * fuel_price
                     if area_ref and fuel_l_ha > 0 and fuel_price > 0 else 0.0)
        time_cost = total_time_h * cost_per_hour
        op_cost_total = time_cost + fuel_cost
        cost_per_ha   = (op_cost_total / area_ref) if area_ref and area_ref > 0 else None
        if has_turns and cost_per_hour > 0 and turns_time_h:
            cost_lost_turns = turns_time_h * cost_per_hour

    return {
        'n_lines': n, 'n_maneuvers': n_maneuvers,
        'total_length_m': total_length, 'mean_length_m': mean_length,
        'min_length_m': min_length, 'max_length_m': max_length, 'std_length_m': std_length,
        'mean_az_deg': mean_az, 'std_az_deg': std_az,
        'mean_spacing_m': mean_spacing, 'std_spacing_m': std_spacing, 'cv_spacing_pct': cv_spacing,
        'est_area_ha': est_area_ha,
        'polygon_area_ha': polygon_area_ha, 'useful_area_pct': useful_area_pct, 'lost_area_pct': lost_area_pct,
        'planting_quality_score': planting_quality_score, 'field_efficiency_index': field_efficiency_index,
        'has_turns': has_turns, 'turns_n': turns_n,
        'turns_length_m': turns_length_m, 'real_total_dist_m': real_total_dist_m,
        'turns_time_h': turns_time_h, 'op_efficiency_pct': op_efficiency_pct,
        'speed_kmh': speed_kmh, 'lines_time_h': lines_time_h, 'total_time_h': total_time_h,
        'has_cost': has_cost, 'op_cost_total': op_cost_total,
        'cost_per_ha': cost_per_ha, 'cost_lost_turns': cost_lost_turns,
        'metric_crs': metric_crs.authid(),
    }


# ─── Results Window (standalone) ─────────────────────────────────────────────

class LineResultsDialog(QDialog):
    """Janela de resultados da análise — abre separada para não sobrepor o formulário."""

    def __init__(self, metrics, layer_name, iface, parent=None):
        super().__init__(parent)
        self._metrics = metrics
        self._iface   = iface
        self._layer_name = layer_name

        self.setWindowTitle('RTH Resultados — {} / Results — {}'.format(layer_name, layer_name))
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint |
                            Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(460)
        self.setMinimumHeight(300)
        self.setMaximumHeight(780)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Scroll area ────────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(6)

        # Title inside scroll
        lbl_title = QLabel('Resultados / Results')
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold;')
        root.addWidget(lbl_title)
        lbl_sub = QLabel(layer_name)
        lbl_sub.setStyleSheet('color:#555; font-size:10px;')
        lbl_sub.setWordWrap(True)
        root.addWidget(lbl_sub)
        root.addWidget(self._sep())

        # Results grid container
        self._res_inner = QWidget()
        self._res_inner.setStyleSheet(
            'QWidget{background:#f5f8ff;border:1px solid #d0d8ef;border-radius:4px;}')
        self._res_grid = QGridLayout(self._res_inner)
        self._res_grid.setContentsMargins(10, 8, 10, 8)
        self._res_grid.setVerticalSpacing(3)
        self._res_grid.setHorizontalSpacing(16)
        self._res_grid.setColumnStretch(1, 1)
        root.addWidget(self._res_inner)

        # ── Copy button — always visible below scroll ──────────────────────────
        btn_copy = QPushButton('Copiar Relatorio / Copy Report')
        btn_copy.setMinimumHeight(32)
        btn_copy.setStyleSheet(
            'QPushButton{background:#fff;color:#1a73e8;font-weight:bold;'
            'font-size:11px;border:1px solid #1a73e8;border-radius:4px;margin:6px;}'
            'QPushButton:hover{background:#e8f0fe;}')
        btn_copy.clicked.connect(self._on_copy)
        outer.addWidget(btn_copy)

        self._build_results_grid(metrics)

    def _sep(self):
        ln = QFrame()
        ln.setFrameShape(QFrame.HLine)
        ln.setFrameShadow(QFrame.Sunken)
        return ln

    def _build_results_grid(self, m):
        while self._res_grid.count():
            item = self._res_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        row = [0]

        def add_section(title):
            lbl = QLabel(title)
            lbl.setStyleSheet('font-weight:bold;font-size:10px;color:#1a73e8;padding-top:6px;')
            self._res_grid.addWidget(lbl, row[0], 0, 1, 2)
            row[0] += 1

        def add_sep():
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFrameShadow(QFrame.Sunken)
            sep.setStyleSheet('border:none;background:#d0d8ef;')
            sep.setFixedHeight(1)
            self._res_grid.addWidget(sep, row[0], 0, 1, 2)
            row[0] += 1

        def add_row(name, value, color=None):
            ln = QLabel(name + ':')
            ln.setStyleSheet('color:#555;font-size:10px;')
            lv = QLabel(value)
            lv.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            st = 'font-weight:bold;font-size:10px;'
            if color:
                st += 'color:{};'.format(color)
            lv.setStyleSheet(st)
            lv.setWordWrap(True)
            self._res_grid.addWidget(ln, row[0], 0)
            self._res_grid.addWidget(lv, row[0], 1)
            row[0] += 1

        add_section('LINHAS / LINES')
        add_row('Quantidade de linhas / Number of lines', str(m['n_lines']))
        add_row('Numero de manobras / Number of maneuvers', str(m['n_maneuvers']))
        total_km = m['total_length_m'] / 1000
        add_row('Comprimento total / Total length',
                '{:,.0f} m  ({:.2f} km)'.format(m['total_length_m'], total_km).replace(',', '.'))
        add_row('Comprimento medio / Avg. length', _fmt_m(m['mean_length_m']))
        add_row('Min / Max comprimento / length',
                '{} / {}'.format(_fmt_m(m['min_length_m']), _fmt_m(m['max_length_m'])))
        add_row('Desvio padrao / Std dev (comprimento)', _fmt_m(m['std_length_m']))

        if m['has_turns']:
            add_sep()
            add_section('CURVAS DE RETORNO / TURN ARCS')
            add_row('Quantidade de curvas / Number of arcs', str(m['turns_n']))
            tkm = m['turns_length_m'] / 1000
            add_row('Comprimento das curvas / Turns length',
                    '{:,.0f} m  ({:.2f} km)'.format(m['turns_length_m'], tkm).replace(',', '.'))
            rkm = m['real_total_dist_m'] / 1000
            add_row('Distancia total percorrida / Total distance traveled',
                    '{:,.0f} m  ({:.2f} km)'.format(m['real_total_dist_m'], rkm).replace(',', '.'))
            eff_c = '#2e7d32' if m['op_efficiency_pct'] >= 80 else (
                '#f57c00' if m['op_efficiency_pct'] >= 60 else '#c62828')
            add_row('Eficiencia operacional / Operational efficiency',
                    '{:.1f}%'.format(m['op_efficiency_pct']), eff_c)

        add_sep()
        add_section('DIRECAO / DIRECTION')
        add_row('Angulo medio / Avg. direction',
                '{:.1f}° (de Norte / from North)'.format(m['mean_az_deg']))
        qt, qc = _parallelism_quality(m['std_az_deg'])
        add_row('Paralelismo / Parallelism (std)',
                '{:.2f}°  [{}]'.format(m['std_az_deg'], qt), qc)

        add_sep()
        add_section('ESPACAMENTO / SPACING')
        if m['mean_spacing_m'] is not None:
            add_row('Espacamento medio / Avg. spacing', _fmt_m(m['mean_spacing_m']))
            st, sc = _spacing_quality(m['cv_spacing_pct'])
            add_row('Variacao (CV) / Spacing CV',
                    '{:.1f}%  [{}]'.format(m['cv_spacing_pct'], st), sc)
        else:
            add_row('Espacamento', 'N/A (requer >= 2 linhas / requires >= 2 lines)')

        add_sep()
        add_section('AREA')
        if m['est_area_ha'] is not None:
            add_row('Area coberta estimada / Est. covered area', _fmt_ha(m['est_area_ha']))
        if m['polygon_area_ha'] is not None:
            add_row('Area do talhao / Field area', _fmt_ha(m['polygon_area_ha']))
        if m['useful_area_pct'] is not None:
            add_row('Area util / Useful area', '{:.1f}%'.format(m['useful_area_pct']))
        if m['lost_area_pct'] is not None:
            lc = '#2e7d32' if m['lost_area_pct'] < 5 else (
                '#f57c00' if m['lost_area_pct'] < 15 else '#c62828')
            add_row('Area perdida / Lost area',
                    '{:.1f}%'.format(m['lost_area_pct']), lc)

        add_sep()
        add_section('QUALIDADE / QUALITY')
        qs_l, qs_c = _quality_label(m['planting_quality_score'])
        add_row('Score de qualidade do plantio / Planting quality score',
                '{}  [{}]'.format(m['planting_quality_score'], qs_l), qs_c)
        ei_l, ei_c = _quality_label(m['field_efficiency_index'])
        add_row('Indice de eficiencia do talhao / Field efficiency index',
                '{}  [{}]'.format(m['field_efficiency_index'], ei_l), ei_c)

        add_sep()
        add_section('TEMPO / TIME')
        add_row('Velocidade usada / Speed used', '{:.1f} km/h'.format(m['speed_kmh']))
        add_row('Tempo nas linhas / Lines time', _fmt_time(m['lines_time_h']))
        if m['has_turns'] and m['turns_time_h'] is not None:
            add_row('Tempo nas curvas / Turns time', _fmt_time(m['turns_time_h']))
        add_row('Tempo total / Total time', _fmt_time(m['total_time_h']))
        # Nota: o tempo depende da distancia total, nao do numero de linhas
        note = QLabel('* Tempo proporcional a distancia total percorrida\n'
                      '* Time proportional to total distance traveled')
        note.setStyleSheet('font-size:9px;color:#888;font-style:italic;')
        self._res_grid.addWidget(note, row[0], 0, 1, 2)
        row[0] += 1

        if m['has_cost']:
            add_sep()
            add_section('CUSTO / COST')
            if m['op_cost_total'] is not None:
                add_row('Custo operacional total / Total operational cost',
                        _fmt_brl(m['op_cost_total']))
            if m['cost_per_ha'] is not None:
                add_row('Custo por hectare / Cost per hectare',
                        _fmt_brl(m['cost_per_ha']))
            if m['cost_lost_turns'] is not None:
                add_row('Custo perdido em manobras / Cost lost in turns',
                        _fmt_brl(m['cost_lost_turns']))

        add_sep()
        add_row('CRS de calculo / Calc. CRS', m['metric_crs'])

    def _on_copy(self):
        m = self._metrics
        lname = self._layer_name

        lines = [
            'RTH Analise de Linhas — {}'.format(lname),
            '=' * 52, '',
            'LINHAS / LINES',
            '  Quantidade:              {}'.format(m['n_lines']),
            '  Manobras:                {}'.format(m['n_maneuvers']),
            '  Comprimento total:       {:,.0f} m ({:.2f} km)'.format(
                m['total_length_m'], m['total_length_m']/1000).replace(',', '.'),
            '  Comprimento medio:       {}'.format(_fmt_m(m['mean_length_m'])),
            '  Min / Max:               {} / {}'.format(
                _fmt_m(m['min_length_m']), _fmt_m(m['max_length_m'])),
            '  Desvio padrao:           {}'.format(_fmt_m(m['std_length_m'])),
        ]

        if m['has_turns']:
            lines += [
                '', 'CURVAS DE RETORNO / TURN ARCS',
                '  Qtd curvas:            {}'.format(m['turns_n']),
                '  Dist. curvas:          {:,.0f} m ({:.2f} km)'.format(
                    m['turns_length_m'], m['turns_length_m']/1000).replace(',', '.'),
                '  Dist. total percorrida:{:,.0f} m ({:.2f} km)'.format(
                    m['real_total_dist_m'], m['real_total_dist_m']/1000).replace(',', '.'),
                '  Efic. operacional:     {:.1f}%'.format(m['op_efficiency_pct']),
            ]

        lines += [
            '', 'DIRECAO / DIRECTION',
            '  Angulo medio:            {:.1f} deg'.format(m['mean_az_deg']),
            '  Paralelismo:             {:.2f} deg  [{}]'.format(
                m['std_az_deg'], _parallelism_quality(m['std_az_deg'])[0]),
            '', 'ESPACAMENTO / SPACING',
        ]
        if m['mean_spacing_m'] is not None:
            lines += [
                '  Espacamento medio:     {}'.format(_fmt_m(m['mean_spacing_m'])),
                '  Variacao (CV):         {:.1f}%  [{}]'.format(
                    m['cv_spacing_pct'], _spacing_quality(m['cv_spacing_pct'])[0]),
            ]

        lines += ['', 'AREA']
        if m['est_area_ha']:
            lines.append('  Area coberta est.:     {}'.format(_fmt_ha(m['est_area_ha'])))
        if m['polygon_area_ha']:
            lines.append('  Area do talhao:        {}'.format(_fmt_ha(m['polygon_area_ha'])))
        if m['useful_area_pct'] is not None:
            lines.append('  Area util:             {:.1f}%'.format(m['useful_area_pct']))
        if m['lost_area_pct'] is not None:
            lines.append('  Area perdida:          {:.1f}%'.format(m['lost_area_pct']))

        ql, _ = _quality_label(m['planting_quality_score'])
        el, _ = _quality_label(m['field_efficiency_index'])
        lines += [
            '', 'QUALIDADE / QUALITY',
            '  Score qualidade:         {}  [{}]'.format(m['planting_quality_score'], ql),
            '  Indice eficiencia:       {}  [{}]'.format(m['field_efficiency_index'], el),
            '', 'TEMPO / TIME',
            '  Velocidade:              {:.1f} km/h'.format(m['speed_kmh']),
            '  Tempo linhas:            {}'.format(_fmt_time(m['lines_time_h'])),
        ]
        if m['has_turns'] and m['turns_time_h']:
            lines.append('  Tempo curvas:            {}'.format(_fmt_time(m['turns_time_h'])))
        lines.append('  Tempo total:             {}'.format(_fmt_time(m['total_time_h'])))

        if m['has_cost']:
            lines += ['', 'CUSTO / COST']
            if m['op_cost_total'] is not None:
                lines.append('  Custo total:           {}'.format(_fmt_brl(m['op_cost_total'])))
            if m['cost_per_ha'] is not None:
                lines.append('  Custo/ha:              {}'.format(_fmt_brl(m['cost_per_ha'])))
            if m['cost_lost_turns'] is not None:
                lines.append('  Custo manobras:        {}'.format(_fmt_brl(m['cost_lost_turns'])))

        lines += ['', 'CRS de calculo: {}'.format(m['metric_crs'])]
        QApplication.clipboard().setText('\n'.join(lines))
        self._iface.messageBar().pushMessage(
            'RTH Analise', 'Relatorio copiado / Report copied',
            level=Qgis.MessageLevel.Info, duration=3)


# ─── Comparison Results Window (standalone) ───────────────────────────────────

class LineComparisonResultsDialog(QDialog):
    """Janela de resultados da comparação — abre separada."""

    def __init__(self, results, iface, parent=None):
        super().__init__(parent)
        self._results = results
        self._iface   = iface

        names = [r['_name'] for r in results if r]
        self.setWindowTitle('RTH Comparação — Estratégias {} / Strategy Comparison {}'.format(', '.join(names), ', '.join(names)))
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint |
                            Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(700)
        self.setMinimumHeight(400)
        self.setMaximumHeight(800)
        self.resize(760, 620)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 0)
        outer.setSpacing(6)

        lbl_title = QLabel('Comparacao de Estrategias / Strategy Comparison')
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold;')
        outer.addWidget(lbl_title)

        lbl_hint = QLabel(
            'Verde = melhor valor na linha  •  Menor nº linhas = menos manobras = melhor conforto\n'
            'Green = best value in row  •  Fewer lines = fewer maneuvers = better operator comfort')
        lbl_hint.setAlignment(Qt.AlignCenter)
        lbl_hint.setStyleSheet('font-size:9px;color:#666;')
        outer.addWidget(lbl_hint)

        # Table fills remaining space
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table)

        btn_copy = QPushButton('Copiar Tabela / Copy Table')
        btn_copy.setMinimumHeight(32)
        btn_copy.setStyleSheet(
            'QPushButton{background:#fff;color:#1a73e8;font-weight:bold;'
            'font-size:11px;border:1px solid #1a73e8;border-radius:4px;margin:4px;}'
            'QPushButton:hover{background:#e8f0fe;}')
        btn_copy.clicked.connect(self._on_copy)
        outer.addWidget(btn_copy)

        self._build_table(results)

    def _build_table(self, results):
        any_turns = any(r and r.get('has_turns') for r in results)
        any_poly  = any(r and r.get('polygon_area_ha') is not None for r in results)
        any_cost  = any(r and r.get('has_cost') for r in results)

        # (display, key, higher_is_better, formatter)  key=None → section header
        # higher_is_better:
        #   True  → green on highest value (more is better)
        #   False → green on lowest value (less is better)
        #   None  → no highlight (neutral / context-dependent)
        rows = [
            ('LINHAS / LINES',                        None,              None,  None),
            # Fewer lines = fewer maneuvers = better operator comfort → lower is better
            ('Qtd linhas / Num. lines',               'n_lines',         False, str),
            # Fewer maneuvers = better → lower is better
            ('Manobras / Maneuvers',                  'n_maneuvers',     False, str),
            # Less total distance = less fuel and time → lower is better
            ('Comp. total / Total length (m)',        'total_length_m',  False, lambda v: '{:,.0f}'.format(v).replace(',', '.')),
            # Longer avg line = each pass covers more before turning → higher is better
            ('Comp. medio / Avg. length',             'mean_length_m',   True,  _fmt_m),
            # Less dispersion in length = more uniform → lower is better
            ('Desvio padrao / Std dev',               'std_length_m',    False, _fmt_m),
        ]

        if any_turns:
            rows += [
                ('CURVAS DE RETORNO / TURN ARCS',     None,              None,  None),
                ('Qtd curvas / Num arcs',             'turns_n',         False, str),
                ('Dist. curvas / Turns length (m)',   'turns_length_m',  False, lambda v: '{:,.0f}'.format(v).replace(',', '.')),
                ('Dist. total percorrida / Total dist. travelled (m)',         'real_total_dist_m', False, lambda v: '{:,.0f}'.format(v).replace(',', '.')),
                ('Efic. operacional / Op. efficiency','op_efficiency_pct', True, _fmt_pct),
            ]

        rows += [
            ('DIRECAO / DIRECTION',                   None,              None,  None),
            ('Paralelismo / Parallelism (std)',        'std_az_deg',      False, lambda v: '{:.2f}°'.format(v)),
            ('ESPACAMENTO / SPACING',                  None,              None,  None),
            ('Espacamento medio / Avg. spacing',      'mean_spacing_m',  None,  _fmt_m),
            ('Variacao (CV) / Spacing CV',             'cv_spacing_pct', False, _fmt_pct),
            ('AREA',                                   None,              None,  None),
            ('Area coberta / Covered area',           'est_area_ha',     True,  _fmt_ha),
        ]

        if any_poly:
            rows += [
                ('Area util / Useful area',           'useful_area_pct', True,  _fmt_pct),
                ('Area perdida / Lost area',           'lost_area_pct',  False, _fmt_pct),
            ]

        rows += [
            ('QUALIDADE / QUALITY',                   None,              None,  None),
            ('Score qualidade / Quality score',        'planting_quality_score', True, str),
            ('Indice eficiencia / Efficiency index',  'field_efficiency_index',  True, str),
            # Tempo: proporcional à distância total — não ao nº de linhas
            # Time: proportional to total distance — NOT to number of lines
            ('TEMPO * / TIME *',                       None,              None,  None),
            ('Tempo linhas / Lines time',             'lines_time_h',    False, _fmt_time),
        ]
        if any_turns:
            rows.append(('Tempo curvas / Turns time', 'turns_time_h',    False, _fmt_time))
        rows.append(('Tempo total / Total time',      'total_time_h',    False, _fmt_time))
        rows.append(('* Tempo / Time = distancia / velocidade (nao depende do no. de linhas / independent of line count)',
                     None, None, None))

        if any_cost:
            rows += [
                ('CUSTO / COST',                       None,              None,  None),
                ('Custo total / Total cost',           'op_cost_total',   False, _fmt_brl),
                ('Custo/ha / Cost per ha',             'cost_per_ha',     False, _fmt_brl),
            ]
            if any_turns:
                rows.append(('Custo manobras / Turns cost', 'cost_lost_turns', False, _fmt_brl))

        active = [i for i, r in enumerate(results) if r is not None]
        n_cols = len(active) + 1
        self.table.setColumnCount(n_cols)
        self.table.setRowCount(len(rows))

        headers = ['Metrica / Metric']
        for i in active:
            r = results[i]
            headers.append('Estrategia {}\n{}'.format(r['_name'], r['_layer']))
        self.table.setHorizontalHeaderLabels(headers)

        HDR_BG  = QColor('#e8f0fe')
        HDR_FG  = QColor('#1558b0')
        NOTE_BG = QColor('#fff9e6')
        NOTE_FG = QColor('#888')
        BEST_BG = QColor('#e8f5e9')
        BEST_FG = QColor('#2e7d32')
        NA_FG   = QColor('#aaaaaa')

        for ri, (name, key, higher, fmt) in enumerate(rows):
            if key is None:
                # Section header or note row
                is_note = name.startswith('*')
                item = QTableWidgetItem(name)
                item.setBackground(NOTE_BG if is_note else HDR_BG)
                item.setForeground(NOTE_FG if is_note else HDR_FG)
                if not is_note:
                    f = item.font(); f.setBold(True); item.setFont(f)
                else:
                    f = item.font(); f.setItalic(True); item.setFont(f)
                self.table.setItem(ri, 0, item)
                for ci in range(len(active)):
                    emp = QTableWidgetItem('')
                    emp.setBackground(NOTE_BG if is_note else HDR_BG)
                    self.table.setItem(ri, ci + 1, emp)
            else:
                lbl_item = QTableWidgetItem('  ' + name)
                self.table.setItem(ri, 0, lbl_item)

                vals = [(results[i].get(key) if results[i] else None) for i in active]

                best_ci = None
                if higher is not None:
                    valid = [(ci, v) for ci, v in enumerate(vals) if v is not None]
                    if len(valid) >= 2:
                        best_ci = (max if higher else min)(valid, key=lambda x: x[1])[0]

                for ci, v in enumerate(vals):
                    if v is None:
                        item = QTableWidgetItem('—')
                        item.setForeground(NA_FG)
                    else:
                        item = QTableWidgetItem(fmt(v) if fmt else str(v))
                    item.setTextAlignment(Qt.AlignCenter)
                    if ci == best_ci:
                        item.setBackground(BEST_BG)
                        item.setForeground(BEST_FG)
                        f = item.font(); f.setBold(True); item.setFont(f)
                    self.table.setItem(ri, ci + 1, item)

        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()

    def _on_copy(self):
        rows_text = []
        for r in range(self.table.rowCount()):
            cells = []
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                cells.append(item.text().strip() if item else '')
            rows_text.append('\t'.join(cells))
        QApplication.clipboard().setText('\n'.join(rows_text))
        self._iface.messageBar().pushMessage(
            'RTH Compare', 'Tabela copiada / Table copied',
            level=Qgis.MessageLevel.Info, duration=3)


# ─── Analysis Dialog ──────────────────────────────────────────────────────────

class LineAnalysisDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._results_dlg = None  # reference to keep results window alive
        self._build_ui()
        self._populate_layers()

    def _build_ui(self):
        self.setWindowTitle('RTH — Análise de Linhas de Plantio / Planting Line Analysis')
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint |
                            Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.setMinimumWidth(490)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        lbl_title = QLabel('Analise de Linhas de Plantio/Colheita / Planting/Harvest Line Analysis')
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold;')
        root.addWidget(lbl_title)

        lbl_sub = QLabel('Qualidade, eficiencia e custos / Line quality, efficiency and costs')
        lbl_sub.setAlignment(Qt.AlignCenter)
        lbl_sub.setStyleSheet('color:#666; font-size:10px;')
        root.addWidget(lbl_sub)

        root.addWidget(self._sep())

        # ── Layers ────────────────────────────────────────────────────────────
        grp_layers = QGroupBox('Camadas / Layers')
        lay_l = QGridLayout()
        lay_l.setContentsMargins(8, 6, 8, 8)
        lay_l.setSpacing(5)
        lay_l.setColumnStretch(1, 1)

        lay_l.addWidget(QLabel('Linhas / Lines:'), 0, 0)
        self.combo_layer = QComboBox()
        lay_l.addWidget(self.combo_layer, 0, 1)

        lay_l.addWidget(QLabel('Talhao / Field (opcional):'), 1, 0)
        self.combo_poly = QComboBox()
        lay_l.addWidget(self.combo_poly, 1, 1)

        lay_l.addWidget(QLabel('Curvas / Turns (opcional):'), 2, 0)
        self.combo_turns = QComboBox()
        lbl_turns_hint = QLabel(
            'Selecione a camada de curvas gerada pela ferramenta de Linhas de Plantio.\n'
            'Select the turn arcs layer generated by the Planting Lines tool.')
        lbl_turns_hint.setStyleSheet('font-size:9px; color:#888;')
        lbl_turns_hint.setWordWrap(True)
        lay_l.addWidget(self.combo_turns, 2, 1)
        lay_l.addWidget(lbl_turns_hint, 3, 1)

        grp_layers.setLayout(lay_l)
        root.addWidget(grp_layers)

        # ── Parameters ────────────────────────────────────────────────────────
        grp_params = QGroupBox('Parametros / Parameters')
        lay_p = QVBoxLayout()
        lay_p.setContentsMargins(8, 6, 8, 8)
        lay_p.setSpacing(6)

        row_sp = QHBoxLayout()
        row_sp.addWidget(QLabel('Velocidade / Speed:'))
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(1.0, 30.0)
        self.spin_speed.setValue(6.0)
        self.spin_speed.setSuffix('  km/h')
        self.spin_speed.setDecimals(1)
        self.spin_speed.setSingleStep(0.5)
        self.spin_speed.setToolTip('Tipico semeadura / Typical seeding: 4–8 km/h')
        row_sp.addWidget(self.spin_speed)
        row_sp.addStretch()
        lay_p.addLayout(row_sp)

        grp_cost = QGroupBox('Custo Operacional / Operational Cost (opcional)')
        lay_c = QGridLayout()
        lay_c.setContentsMargins(8, 6, 8, 8)
        lay_c.setSpacing(4)
        lay_c.setColumnStretch(1, 1)

        lay_c.addWidget(QLabel('Custo maquina / Machine cost:'), 0, 0)
        self.spin_cost_hr = QDoubleSpinBox()
        self.spin_cost_hr.setRange(0, 10000); self.spin_cost_hr.setValue(0)
        self.spin_cost_hr.setSuffix('  R$/h'); self.spin_cost_hr.setDecimals(2)
        self.spin_cost_hr.setSingleStep(10)
        lay_c.addWidget(self.spin_cost_hr, 0, 1)

        lay_c.addWidget(QLabel('Combustivel / Fuel:'), 1, 0)
        self.spin_fuel_lha = QDoubleSpinBox()
        self.spin_fuel_lha.setRange(0, 100); self.spin_fuel_lha.setValue(0)
        self.spin_fuel_lha.setSuffix('  L/ha'); self.spin_fuel_lha.setDecimals(2)
        self.spin_fuel_lha.setSingleStep(0.5)
        lay_c.addWidget(self.spin_fuel_lha, 1, 1)

        lay_c.addWidget(QLabel('Preco combustivel / Fuel price:'), 2, 0)
        self.spin_fuel_price = QDoubleSpinBox()
        self.spin_fuel_price.setRange(0, 50); self.spin_fuel_price.setValue(0)
        self.spin_fuel_price.setSuffix('  R$/L'); self.spin_fuel_price.setDecimals(2)
        self.spin_fuel_price.setSingleStep(0.1)
        lay_c.addWidget(self.spin_fuel_price, 2, 1)

        grp_cost.setLayout(lay_c)
        lay_p.addWidget(grp_cost)
        grp_params.setLayout(lay_p)
        root.addWidget(grp_params)

        root.addWidget(self._sep())

        # ── Action buttons ─────────────────────────────────────────────────────
        row_btns = QHBoxLayout()

        self.btn_run = QPushButton('Analisar / Analyze')
        self.btn_run.setMinimumHeight(38)
        self.btn_run.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;'
            'font-size:12px;border-radius:5px;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#aaa;}')
        self.btn_run.clicked.connect(self._on_run)
        row_btns.addWidget(self.btn_run)

        self.btn_compare = QPushButton('Comparar Estrategias / Compare')
        self.btn_compare.setMinimumHeight(38)
        self.btn_compare.setStyleSheet(
            'QPushButton{background:#388e3c;color:white;font-weight:bold;'
            'font-size:11px;border-radius:5px;}'
            'QPushButton:hover{background:#2e7d32;}')
        self.btn_compare.clicked.connect(self._on_compare)
        row_btns.addWidget(self.btn_compare)

        root.addLayout(row_btns)

        lbl_note = QLabel('Os resultados abrem em uma janela separada / Results open in a separate window')
        lbl_note.setAlignment(Qt.AlignCenter)
        lbl_note.setStyleSheet('font-size:9px; color:#888; margin-top:2px;')
        root.addWidget(lbl_note)

    def _sep(self):
        ln = QFrame()
        ln.setFrameShape(QFrame.HLine)
        ln.setFrameShadow(QFrame.Sunken)
        return ln

    def _populate_layers(self):
        self.combo_layer.clear()
        self.combo_poly.clear()
        self.combo_turns.clear()
        self.combo_poly.addItem('Nenhum / None', None)
        self.combo_turns.addItem('Nenhum / None', None)

        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            gt = QgsWkbTypes.geometryType(layer.wkbType())
            if gt == QgsWkbTypes.LineGeometry:
                self.combo_layer.addItem(layer.name(), layer.id())
                self.combo_turns.addItem(layer.name(), layer.id())
            elif gt == QgsWkbTypes.PolygonGeometry:
                self.combo_poly.addItem(layer.name(), layer.id())

        if self.combo_layer.count() == 0:
            self.combo_layer.addItem('Nenhuma camada de linhas / No line layer', None)

    def _get_layer(self, combo):
        lid = combo.currentData()
        return QgsProject.instance().mapLayer(lid) if lid else None

    def _on_run(self):
        layer = self._get_layer(self.combo_layer)
        if layer is None:
            self.iface.messageBar().pushMessage(
                'RTH Analise', 'Selecione uma camada de linhas / Select a line layer',
                level=Qgis.MessageLevel.Warning, duration=4)
            return

        self.btn_run.setEnabled(False)
        self.btn_run.setText('Analisando... / Analyzing...')
        QApplication.processEvents()

        try:
            m = compute_metrics(
                layer, self.spin_speed.value(),
                poly_layer=self._get_layer(self.combo_poly),
                turns_layer=self._get_layer(self.combo_turns),
                cost_per_hour=self.spin_cost_hr.value(),
                fuel_l_ha=self.spin_fuel_lha.value(),
                fuel_price=self.spin_fuel_price.value(),
            )
            # Close previous results window if open
            if self._results_dlg is not None and self._results_dlg.isVisible():
                self._results_dlg.close()
            # Open new standalone results window
            self._results_dlg = LineResultsDialog(
                m, self.combo_layer.currentText(), self.iface, parent=self)
            self._results_dlg.show()
            self._results_dlg.raise_()
            self._results_dlg.activateWindow()
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                'RTH Analise', str(exc),
                level=Qgis.MessageLevel.Critical, duration=6)
        finally:
            self.btn_run.setEnabled(True)
            self.btn_run.setText('Analisar / Analyze')

    def _on_compare(self):
        dlg = LineComparisonDialog(
            self.iface,
            speed=self.spin_speed.value(),
            cost_hr=self.spin_cost_hr.value(),
            fuel_lha=self.spin_fuel_lha.value(),
            fuel_price=self.spin_fuel_price.value(),
            parent=self,
        )
        dlg.exec_()


# ─── Comparison Dialog ────────────────────────────────────────────────────────

class LineComparisonDialog(QDialog):

    def __init__(self, iface, speed=6.0, cost_hr=0.0, fuel_lha=0.0, fuel_price=0.0, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._speed = speed
        self._cost_hr = cost_hr
        self._fuel_lha = fuel_lha
        self._fuel_price = fuel_price
        self._comparison_dlg = None  # reference to keep results window alive
        self._build_ui()
        self._populate_layers()

    def _build_ui(self):
        self.setWindowTitle('RTH — Comparação de Estratégias de Plantio / Planting Strategy Comparison')
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint |
                            Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        lbl_title = QLabel('Comparacao de Estrategias / Planting Strategy Comparison')
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold;')
        root.addWidget(lbl_title)

        lbl_sub = QLabel(
            'Compare ate 3 camadas de linhas com diferentes configuracoes.\n'
            'Compare up to 3 line layers with different configurations.')
        lbl_sub.setAlignment(Qt.AlignCenter)
        lbl_sub.setStyleSheet('color:#666; font-size:10px;')
        root.addWidget(lbl_sub)

        root.addWidget(self._sep())

        # ── Strategies grid ───────────────────────────────────────────────────
        grp_s = QGroupBox('Estrategias / Strategies')
        g = QGridLayout()
        g.setContentsMargins(8, 8, 8, 8)
        g.setSpacing(6)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(2, 1)

        g.addWidget(QLabel(''), 0, 0)
        h1 = QLabel('Linhas / Lines')
        h1.setStyleSheet('font-weight:bold;')
        g.addWidget(h1, 0, 1)
        h2 = QLabel('Curvas / Turns (opcional)')
        h2.setStyleSheet('font-weight:bold;')
        g.addWidget(h2, 0, 2)

        self._strategy_combos = []
        colors = ['#1a73e8', '#388e3c', '#e65100']
        names  = ['A', 'B', 'C']

        for i, (name, color) in enumerate(zip(names, colors)):
            lbl = QLabel('Estrategia {} / Strategy {}'.format(name, name))
            lbl.setStyleSheet('font-weight:bold; color:{};'.format(color))
            cl = QComboBox()
            ct = QComboBox()
            g.addWidget(lbl, i+1, 0)
            g.addWidget(cl,  i+1, 1)
            g.addWidget(ct,  i+1, 2)
            self._strategy_combos.append((cl, ct))

        grp_s.setLayout(g)
        root.addWidget(grp_s)

        # ── Shared parameters ─────────────────────────────────────────────────
        grp_sh = QGroupBox('Parametros Compartilhados / Shared Parameters')
        lay_sh = QGridLayout()
        lay_sh.setContentsMargins(8, 6, 8, 8)
        lay_sh.setSpacing(5)
        lay_sh.setColumnStretch(1, 1)

        lay_sh.addWidget(QLabel('Talhao / Field (opcional):'), 0, 0)
        self.combo_poly = QComboBox()
        lay_sh.addWidget(self.combo_poly, 0, 1)

        lay_sh.addWidget(QLabel('Velocidade / Speed:'), 1, 0)
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(1.0, 30.0); self.spin_speed.setValue(self._speed)
        self.spin_speed.setSuffix('  km/h'); self.spin_speed.setDecimals(1)
        lay_sh.addWidget(self.spin_speed, 1, 1)

        lay_sh.addWidget(QLabel('Custo maquina / Machine cost:'), 2, 0)
        self.spin_cost_hr = QDoubleSpinBox()
        self.spin_cost_hr.setRange(0, 10000); self.spin_cost_hr.setValue(self._cost_hr)
        self.spin_cost_hr.setSuffix('  R$/h'); self.spin_cost_hr.setDecimals(2)
        lay_sh.addWidget(self.spin_cost_hr, 2, 1)

        lay_sh.addWidget(QLabel('Combustivel / Fuel:'), 3, 0)
        self.spin_fuel_lha = QDoubleSpinBox()
        self.spin_fuel_lha.setRange(0, 100); self.spin_fuel_lha.setValue(self._fuel_lha)
        self.spin_fuel_lha.setSuffix('  L/ha'); self.spin_fuel_lha.setDecimals(2)
        lay_sh.addWidget(self.spin_fuel_lha, 3, 1)

        lay_sh.addWidget(QLabel('Preco combustivel / Fuel price:'), 4, 0)
        self.spin_fuel_price = QDoubleSpinBox()
        self.spin_fuel_price.setRange(0, 50); self.spin_fuel_price.setValue(self._fuel_price)
        self.spin_fuel_price.setSuffix('  R$/L'); self.spin_fuel_price.setDecimals(2)
        lay_sh.addWidget(self.spin_fuel_price, 4, 1)

        grp_sh.setLayout(lay_sh)
        root.addWidget(grp_sh)

        root.addWidget(self._sep())

        self.btn_run = QPushButton('Comparar / Compare')
        self.btn_run.setMinimumHeight(38)
        self.btn_run.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;'
            'font-size:13px;border-radius:5px;}'
            'QPushButton:hover{background:#1558b0;}')
        self.btn_run.clicked.connect(self._on_run)
        root.addWidget(self.btn_run)

        lbl_note = QLabel('Os resultados abrem em uma janela separada / Results open in a separate window')
        lbl_note.setAlignment(Qt.AlignCenter)
        lbl_note.setStyleSheet('font-size:9px; color:#888; margin-top:2px;')
        root.addWidget(lbl_note)

    def _sep(self):
        ln = QFrame()
        ln.setFrameShape(QFrame.HLine)
        ln.setFrameShadow(QFrame.Sunken)
        return ln

    def _populate_layers(self):
        self.combo_poly.addItem('Nenhum / None', None)
        for cl, ct in self._strategy_combos:
            cl.addItem('Nenhuma / None', None)
            ct.addItem('Nenhum / None', None)

        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            gt = QgsWkbTypes.geometryType(layer.wkbType())
            if gt == QgsWkbTypes.LineGeometry:
                for cl, ct in self._strategy_combos:
                    cl.addItem(layer.name(), layer.id())
                    ct.addItem(layer.name(), layer.id())
            elif gt == QgsWkbTypes.PolygonGeometry:
                self.combo_poly.addItem(layer.name(), layer.id())

    def _get_layer(self, combo):
        lid = combo.currentData()
        return QgsProject.instance().mapLayer(lid) if lid else None

    def _on_run(self):
        poly_layer = self._get_layer(self.combo_poly)
        speed     = self.spin_speed.value()
        cost_hr   = self.spin_cost_hr.value()
        fuel_lha  = self.spin_fuel_lha.value()
        fuel_p    = self.spin_fuel_price.value()

        self.btn_run.setEnabled(False)
        self.btn_run.setText('Analisando... / Analyzing...')
        QApplication.processEvents()

        results = []
        names   = ['A', 'B', 'C']

        try:
            for i, (combo_l, combo_t) in enumerate(self._strategy_combos):
                layer  = self._get_layer(combo_l)
                turns  = self._get_layer(combo_t)
                if layer is None:
                    results.append(None)
                    continue
                try:
                    m = compute_metrics(
                        layer, speed,
                        poly_layer=poly_layer, turns_layer=turns,
                        cost_per_hour=cost_hr, fuel_l_ha=fuel_lha, fuel_price=fuel_p,
                    )
                    m['_name']  = names[i]
                    m['_layer'] = combo_l.currentText()
                    results.append(m)
                except Exception as exc:
                    self.iface.messageBar().pushMessage(
                        'RTH Compare',
                        'Estrategia {} / Strategy {}: {}'.format(names[i], names[i], exc),
                        level=Qgis.MessageLevel.Warning, duration=5)
                    results.append(None)

            if not any(r is not None for r in results):
                self.iface.messageBar().pushMessage(
                    'RTH Compare', 'Nenhuma estrategia valida / No valid strategies',
                    level=Qgis.MessageLevel.Warning, duration=4)
                return

            # Close previous comparison window if open
            if self._comparison_dlg is not None and self._comparison_dlg.isVisible():
                self._comparison_dlg.close()
            # Open new standalone comparison results window
            self._comparison_dlg = LineComparisonResultsDialog(
                [r for r in results if r is not None], self.iface, parent=self)
            self._comparison_dlg.show()
            self._comparison_dlg.raise_()
            self._comparison_dlg.activateWindow()
        finally:
            self.btn_run.setEnabled(True)
            self.btn_run.setText('Comparar / Compare')


# ─── Tool class ───────────────────────────────────────────────────────────────

class LineAnalysisTool:

    def __init__(self, iface):
        self.iface = iface
        self._dlg = None

    def run(self):
        if self._dlg is None or not self._dlg.isVisible():
            self._dlg = LineAnalysisDialog(self.iface, parent=self.iface.mainWindow())
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
