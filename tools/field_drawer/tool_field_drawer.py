# -*- coding: utf-8 -*-
"""
FieldDrawerTool — Desenha talhões automaticamente clicando no mapa.
Usa análise perceptual de cor no canvas (CIELAB flood fill + region growing).
FieldDrawerTool — Automatically draws fields by clicking the map.
Uses perceptual color analysis on canvas (CIELAB flood fill + region growing).

Algoritmo:
  1. _capture_canvas        → renderiza o canvas atual em QImage
  2. _pixels_to_cielab      → converte pixels BGR → CIELAB (sRGB/D65, só numpy)
  3. _click_color_reference → cor de referência = mediana do patch ao redor do clique
  4. _region_by_seeds       → flood fill no componente 4-conectado (union-find em runs)
  5. _expand_smooth_edges   → BFS sobre gradientes suaves (delta-E < EDGE_TOLERANCE)
  6. _mask_to_polygons      → máscara → retângulos → dissolve → simplify → QgsFeatures

Algorithm:
  1. _capture_canvas        → render current canvas to QImage
  2. _pixels_to_cielab      → convert BGR pixels → CIELAB (sRGB/D65, numpy only)
  3. _click_color_reference → reference color = median of patch around click
  4. _region_by_seeds       → flood fill on 4-connected component (union-find on runs)
  5. _expand_smooth_edges   → BFS over smooth gradients (delta-E < EDGE_TOLERANCE)
  6. _mask_to_polygons      → mask → rectangles → dissolve → simplify → QgsFeatures

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

import numpy as np

from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.PyQt.QtGui import QCursor, QImage, QPainter
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsGeometry,
    QgsMapRendererCustomPainterJob,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.gui import QgsMapTool
from qgis import processing

# ── Qt5/Qt6 enum compat ──────────────────────────────────────────────────────
try:
    _LEFT_BTN  = Qt.MouseButton.LeftButton
    _RIGHT_BTN = Qt.MouseButton.RightButton
    _KEY_ESC   = Qt.Key.Key_Escape
    _HORIZONTAL = Qt.Orientation.Horizontal
    _CROSS_CURSOR = Qt.CursorShape.CrossCursor
except AttributeError:
    _LEFT_BTN  = Qt.LeftButton
    _RIGHT_BTN = Qt.RightButton
    _KEY_ESC   = Qt.Key_Escape
    _HORIZONTAL = Qt.Horizontal
    _CROSS_CURSOR = Qt.CrossCursor

try:
    _FMT_RGB32  = QImage.Format.Format_RGB32
    _FMT_ARGB32 = QImage.Format.Format_ARGB32
except AttributeError:
    _FMT_RGB32  = QImage.Format_RGB32
    _FMT_ARGB32 = QImage.Format_ARGB32

# ── Parâmetros do algoritmo / Algorithm parameters ───────────────────────────
_TOLERANCE_MIN        = 1.0    # delta-E no threshold 10 (estrito / strict)
_TOLERANCE_MAX        = 12.0   # delta-E no threshold 90 (amplo / wide)
_SEED_PATCH_RADIUS    = 1      # raio do patch mediano ao redor do clique
_REFINE_MAX_ITER      = 1      # re-ancoragem da cor de referência
_REFINE_CONVERGED_RATIO = 0.02
_REFINE_MAX_DRIFT_RATIO = 0.5
_GRADIENT_CAP_RATIO   = 1.5   # limita region growing a 1.5× a tolerância
_EDGE_TOLERANCE       = 2.5   # passo delta-E entre pixels adjacentes para crescer
_SIMPLIFY_CELLS       = 1.0   # tolerância de simplificação em células (Visvalingam)
_NOISE_MULTIPLY       = 40    # remove feições < 40 células de área
_MAX_PIXELS           = 2_000_000  # resolução máxima de análise (downscale acima)
_SETTINGS_KEY         = 'rth_project/field_drawer/threshold'


# ── Análise de cor / Color analysis ─────────────────────────────────────────

def _slider_to_delta_e(t):
    """Mapeia slider 10-90 para delta-E CIELAB / Map slider 10-90 to CIELAB delta-E."""
    pos = min(max((t - 10) / 80, 0.0), 1.0)
    return _TOLERANCE_MIN * (_TOLERANCE_MAX / _TOLERANCE_MIN) ** pos


def _pixels_to_cielab(bgr):
    """BGR uint8 (...×3) → CIELAB (sRGB/D65, numpy puro / numpy only)."""
    rgb = bgr[..., ::-1].astype(np.float64) / 255.0
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                   [0.2126729, 0.7151522, 0.0721750],
                   [0.0193339, 0.1191920, 0.9503041]])
    xyz = linear @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def _click_color_reference(lab, sx, sy):
    r = _SEED_PATCH_RADIUS
    h, w = lab.shape[:2]
    patch = lab[max(0, sy-r):min(h, sy+r+1), max(0, sx-r):min(w, sx+r+1)]
    return np.median(patch.reshape(-1, 3), axis=0)


def _nearest_true_pixel(mask, sx, sy, radius=3):
    h, w = mask.shape
    y0, y1 = max(0, sy-radius), min(h, sy+radius+1)
    x0, x1 = max(0, sx-radius), min(w, sx+radius+1)
    ys, xs = np.nonzero(mask[y0:y1, x0:x1])
    if not len(ys):
        return None
    d = (ys + y0 - sy) ** 2 + (xs + x0 - sx) ** 2
    k = int(np.argmin(d))
    return (int(xs[k]) + x0, int(ys[k]) + y0)


def _region_by_seeds(mask, seeds):
    """Componentes 4-conectados de `mask` contendo qualquer semente (union-find em runs).
    4-connected components of `mask` containing any seed (union-find on runs).

    Retorna (component_mask, anchors) onde anchors = 1 ponto por componente.
    Returns (component_mask, anchors) where anchors = 1 point per component.
    """
    height, width = mask.shape
    component = np.zeros_like(mask)

    seeds_by_row = {}
    for sx, sy in seeds:
        if not (0 <= sy < height and 0 <= sx < width):
            continue
        if not mask[sy, sx]:
            near = _nearest_true_pixel(mask, sx, sy)
            if near is None:
                continue
            sx, sy = near
        seeds_by_row.setdefault(sy, []).append(sx)
    if not seeds_by_row:
        return component, []

    parent = []

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    rows = []
    prev_starts = prev_ends = prev_ids = None
    seed_runs = []

    for y in range(height):
        diff   = np.diff(mask[y].astype(np.int8), prepend=0, append=0)
        starts = np.flatnonzero(diff == 1)
        ends   = np.flatnonzero(diff == -1)
        ids    = list(range(len(parent), len(parent) + len(starts)))
        parent.extend(ids)
        rows.append((y, starts, ends, ids))

        for sx in seeds_by_row.get(y, ()):
            idx = int(np.searchsorted(starts, sx, 'right')) - 1
            if idx >= 0 and ends[idx] > sx:
                seed_runs.append(ids[idx])

        if prev_starts is not None:
            i = j = 0
            while i < len(starts) and j < len(prev_starts):
                if starts[i] < prev_ends[j] and prev_starts[j] < ends[i]:
                    union(ids[i], prev_ids[j])
                if ends[i] < prev_ends[j]:
                    i += 1
                else:
                    j += 1
        prev_starts, prev_ends, prev_ids = starts, ends, ids

    if not seed_runs:
        return component, []

    seed_roots = {find(r) for r in seed_runs}
    anchors_d  = {}
    for y, starts, ends, ids in rows:
        for k in range(len(ids)):
            root = find(ids[k])
            if root in seed_roots:
                component[y, starts[k]:ends[k]] = True
                if root not in anchors_d:
                    anchors_d[root] = (int(starts[k]), y)
    return component, list(anchors_d.values())


def _expand_smooth_edges(region, lab, delta_e_seed, tolerance, anchors=None):
    """Cresce `region` por gradientes suaves (passo delta-E < _EDGE_TOLERANCE).
    Grow `region` over smooth gradients (adjacent step delta-E < _EDGE_TOLERANCE).
    """
    cap = delta_e_seed < tolerance * _GRADIENT_CAP_RATIO
    if anchors is None:
        ys, xs = np.nonzero(region)
        if not len(ys):
            return region
        anchors = [(int(xs[0]), int(ys[0]))]
    envelope, _ = _region_by_seeds(cap, anchors)
    env_ys, env_xs = np.nonzero(envelope)
    if not len(env_ys):
        return region
    y0, y1 = int(env_ys.min()), int(env_ys.max()) + 1
    x0, x1 = int(env_xs.min()), int(env_xs.max()) + 1
    grown = region[y0:y1, x0:x1].copy()
    env   = envelope[y0:y1, x0:x1]
    win   = lab[y0:y1, x0:x1]
    sh = np.linalg.norm(win[:, 1:] - win[:, :-1], axis=2) < _EDGE_TOLERANCE
    sv = np.linalg.norm(win[1:, :] - win[:-1, :], axis=2) < _EDGE_TOLERANCE
    while True:
        frontier = np.zeros_like(grown)
        frontier[:, 1:]  |= grown[:, :-1] & sh
        frontier[:, :-1] |= grown[:, 1:]  & sh
        frontier[1:, :]  |= grown[:-1, :] & sv
        frontier[:-1, :] |= grown[1:, :]  & sv
        frontier &= env & ~grown
        if not frontier.any():
            break
        grown |= frontier
    result = np.zeros_like(region)
    result[y0:y1, x0:x1] = grown
    return result


def _select_color_region(lab, reference, tolerance, sx, sy):
    delta_e = np.linalg.norm(lab - reference, axis=2)
    core    = delta_e < tolerance
    region, _ = _region_by_seeds(core, [(sx, sy)])
    if not region.any():
        return region
    return _expand_smooth_edges(region, lab, delta_e, tolerance)


def _compute_talhao_mask(bgr, sx, sy, tolerance):
    """Gera máscara booleana do talhão ao redor do clique (sx, sy).
    Generate boolean mask of the field around the click point (sx, sy).
    """
    lab = _pixels_to_cielab(bgr)
    h, w = lab.shape[:2]
    if not (0 <= sx < w and 0 <= sy < h):
        return np.zeros((h, w), dtype=bool)
    reference = _click_color_reference(lab, sx, sy)
    region    = _select_color_region(lab, reference, tolerance, sx, sy)
    init_ref  = reference
    for _ in range(_REFINE_MAX_ITER):
        if not region.any():
            break
        refined_ref = np.median(lab[region], axis=0)
        drift = float(np.linalg.norm(refined_ref - init_ref))
        if drift > tolerance * _REFINE_MAX_DRIFT_RATIO:
            break
        new_region = _select_color_region(lab, refined_ref, tolerance, sx, sy)
        # garante que o pixel clicado ainda faz parte / ensure clicked pixel still belongs
        if not new_region[sy, sx] and _nearest_true_pixel(new_region, sx, sy) is None:
            break
        changed   = int(np.count_nonzero(new_region != region))
        prev_size = int(np.count_nonzero(region))
        region    = new_region
        if changed <= prev_size * _REFINE_CONVERGED_RATIO:
            break
    return region


# ── Máscara → polígono / Mask → polygon ─────────────────────────────────────

def _mask_to_polygons(mask, canvas, size_multiply):
    """Converte máscara booleana em lista de QgsFeature via retângulos + dissolve.
    Convert boolean mask to list of QgsFeature via rectangles + dissolve.
    """
    true_points = np.where(mask)
    if not len(true_points[0]):
        return []

    transform = canvas.getCoordinateTransform()

    def make_rect(x, y, count=0):
        tl = transform.toMapCoordinatesF(x * size_multiply,           y * size_multiply)
        br = transform.toMapCoordinatesF((x + count + 1) * size_multiply, (y + 1) * size_multiply)
        return QgsGeometry.fromRect(QgsRectangle(tl.x(), tl.y(), br.x(), br.y()))

    # agrupa runs horizontais em retângulos largos / group horizontal runs into wide rects
    rects = []
    connected = 0
    n = len(true_points[0])
    for i in range(n):
        if connected > 0:
            connected -= 1
            continue
        x = int(true_points[1][i])
        y = int(true_points[0][i])
        if i >= n - 1:
            f = QgsFeature()
            f.setGeometry(make_rect(x, y))
            rects.append(f)
            break
        while (i + connected + 1 < n and
               true_points[1][i + connected + 1] - true_points[1][i + connected] == 1):
            connected += 1
            if i + connected + 1 >= n - 1:
                break
        f = QgsFeature()
        f.setGeometry(make_rect(x, y, connected))
        rects.append(f)
    if not rects:
        return []

    minimum_area = make_rect(0, 0).area()
    crs = QgsProject.instance().crs()
    uri = 'Polygon?crs={}'.format(crs.authid())

    tmp = QgsVectorLayer(uri, '_fd_tmp', 'memory')
    tmp.dataProvider().addFeatures(rects)
    tmp.updateExtents()

    dissolved  = processing.run('native:dissolve',
                                {'INPUT': tmp, 'OUTPUT': 'memory:'})['OUTPUT']
    single     = processing.run('native:multiparttosingleparts',
                                {'INPUT': dissolved, 'OUTPUT': 'memory:'})['OUTPUT']
    denoised   = [ft for ft in single.getFeatures()
                  if ft.geometry().area() >= minimum_area * _NOISE_MULTIPLY]
    if not denoised:
        return []

    dn = QgsVectorLayer(uri, '_fd_dn', 'memory')
    dn.dataProvider().addFeatures(denoised)
    dn.updateExtents()

    cell_size  = minimum_area ** 0.5
    simplified = processing.run('native:simplifygeometries',
                                {'INPUT': dn, 'METHOD': 2,
                                 'TOLERANCE': cell_size * _SIMPLIFY_CELLS,
                                 'OUTPUT': 'memory:'})['OUTPUT']
    cleaned    = processing.run('native:deleteholes',
                                {'INPUT': simplified,
                                 'MIN_AREA': minimum_area * _NOISE_MULTIPLY,
                                 'OUTPUT': 'memory:'})['OUTPUT']
    return list(cleaned.getFeatures())


# ── Ferramenta principal / Main tool ─────────────────────────────────────────

class FieldDrawerTool(QgsMapTool):
    """Ferramenta de desenho automático de talhão por análise de cor do canvas.
    Automatic field drawing tool via canvas color analysis.

    Clique esquerdo = desenha polígono / Left click = draw polygon
    Clique direito  = configura tolerância / Right click = configure tolerance
    Esc             = desativa / deactivates
    """

    def __init__(self, iface):
        QgsMapTool.__init__(self, iface.mapCanvas())
        self.iface  = iface
        self.canvas = iface.mapCanvas()

        from qgis.PyQt.QtCore import QSettings
        self._threshold = int(QSettings().value(_SETTINGS_KEY, 50))
        self._lyr_id    = None   # ID da camada de saída / output layer ID

    def tr(self, msg):
        return QCoreApplication.translate('FieldDrawerTool', msg)

    def run(self):
        """Ativa a ferramenta no canvas / Activate the tool on the canvas."""
        self.canvas.setMapTool(self)
        # Mostra instruções toda vez que ativada via menu (mesmo que já estivesse ativa) /
        # Show instructions every time activated from menu (even if tool was already active)
        self.iface.messageBar().pushMessage(
            'RTH',
            self.tr(u'Desenhar Talhão: clique esquerdo = desenhar  |  direito = tolerância  |  Esc = sair / '
                    u'Draw Field: left = draw  |  right = tolerance  |  Esc = exit'),
            level=Qgis.MessageLevel.Info, duration=8)

    def activate(self):
        """QGIS chama ao ativar a ferramenta / QGIS calls when tool is activated."""
        self.canvas.setCursor(QCursor(_CROSS_CURSOR))

    def deactivate(self):
        """QGIS chama ao desativar / QGIS calls when tool is deactivated."""
        QgsMapTool.deactivate(self)

    def canvasPressEvent(self, e):
        if e.button() == _LEFT_BTN:
            self._on_left_click(e)
        elif e.button() == _RIGHT_BTN:
            self._configure_tolerance()

    def keyPressEvent(self, e):
        if e.key() == _KEY_ESC:
            self.canvas.unsetMapTool(self)
        else:
            QgsMapTool.keyPressEvent(self, e)

    # ------------------------------------------------------------------

    def _device_point(self, e):
        """Posição do evento em pixels de tela (Qt5/Qt6 compat).
        Event position in screen pixels (Qt5/Qt6 compat).
        """
        if hasattr(e, 'position'):   # Qt6
            return e.position().toPoint()
        return e.pos()               # Qt5

    def _on_left_click(self, e):
        pt = self._device_point(e)
        try:
            image = self._capture_canvas()
            w, h  = image.width(), image.height()

            # downscale via QImage.scaled() — interpolação bilinear, idêntico ao MagicWand /
            # downscale via QImage.scaled() — bilinear interpolation, identical to MagicWand
            resize_m = min(1.0, (_MAX_PIXELS / max(w * h, 1)) ** 0.5)
            if resize_m < 1.0:
                nw = max(1, int(w * resize_m))
                nh = max(1, int(h * resize_m))
                analysis_img = image.scaled(nw, nh).convertToFormat(_FMT_ARGB32)
            else:
                analysis_img = image.convertToFormat(_FMT_ARGB32)

            aw = analysis_img.width()
            ah = analysis_img.height()
            ptr = analysis_img.constBits()
            ptr.setsize(analysis_img.sizeInBytes())
            bgr = np.frombuffer(ptr, dtype=np.uint8).reshape(
                ah, analysis_img.bytesPerLine() // 4, 4)[:, :aw, :3].copy()

            sx = int(pt.x() * aw / w)
            sy = int(pt.y() * ah / h)

            tolerance     = _slider_to_delta_e(self._threshold)
            mask          = _compute_talhao_mask(bgr, sx, sy, tolerance)
            size_multiply = w / aw   # pixels canvas / pixels análise → escala de volta / scale back

            features = _mask_to_polygons(mask, self.canvas, size_multiply)
            if not features:
                self.iface.messageBar().pushMessage(
                    'RTH',
                    self.tr(u'Nenhum polígono encontrado — tente ajustar a tolerância (clique direito) / '
                            u'No polygon found — try adjusting tolerance (right click)'),
                    level=Qgis.MessageLevel.Warning, duration=4)
                return

            lyr = self._get_or_create_layer()
            if lyr.isEditable() or lyr.startEditing():
                lyr.beginEditCommand('RTH: Talhão / Field')
                lyr.addFeatures(features)
                lyr.endEditCommand()
            else:
                lyr.dataProvider().addFeatures(features)
            lyr.updateExtents()
            lyr.triggerRepaint()
            n = len(features)
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'{} polígono(s) adicionado(s) / {} polygon(s) added').format(n, n),
                level=Qgis.MessageLevel.Success, duration=3)

        except Exception as ex:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Erro ao desenhar talhão / Error drawing field: {}').format(str(ex)),
                level=Qgis.MessageLevel.Critical, duration=5)

    def _capture_canvas(self):
        """Renderiza o canvas atual em QImage RGB32 / Render current canvas to QImage RGB32."""
        ms    = self.canvas.mapSettings()
        image = QImage(ms.outputSize(), _FMT_RGB32)
        p     = QPainter()
        p.begin(image)
        job = QgsMapRendererCustomPainterJob(ms, p)
        job.start()
        job.waitForFinished()
        p.end()
        return image

    def _get_or_create_layer(self):
        """Reutiliza camada 'Talhão / Field' existente ou cria nova de memória.
        Reuse existing 'Talhão / Field' layer or create new memory layer.
        """
        if self._lyr_id:
            lyr = QgsProject.instance().mapLayer(self._lyr_id)
            if lyr and lyr.isValid():
                return lyr
        crs = QgsProject.instance().crs()
        lyr = QgsVectorLayer(
            'Polygon?crs={}'.format(crs.authid()),
            self.tr(u'Talhão / Field'),
            'memory')
        QgsProject.instance().addMapLayer(lyr)
        self._lyr_id = lyr.id()
        return lyr

    def _configure_tolerance(self):
        """Clique direito: diálogo para ajustar tolerância de cor.
        Right click: dialog to adjust color tolerance.
        """
        from qgis.PyQt.QtCore import QSettings
        from qgis.PyQt.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QSlider, QDialogButtonBox,
        )

        dlg = QDialog(self.iface.mainWindow())
        dlg.setWindowTitle(self.tr(u'Tolerância de Cor / Color Tolerance'))
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel(self.tr(
            u'Tolerância (10 = estrito, 90 = amplo) / Tolerance (10 = strict, 90 = wide):')))

        slider = QSlider(_HORIZONTAL)
        slider.setRange(10, 90)
        slider.setValue(self._threshold)
        layout.addWidget(slider)

        lbl = QLabel(str(self._threshold))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, 'AlignmentFlag') else Qt.AlignCenter)
        slider.valueChanged.connect(lambda v: lbl.setText(str(v)))
        layout.addWidget(lbl)

        try:
            std = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        except AttributeError:
            std = QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        btns = QDialogButtonBox(std)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec_():
            self._threshold = slider.value()
            QSettings().setValue(_SETTINGS_KEY, self._threshold)
