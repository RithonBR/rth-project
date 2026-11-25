# -*- coding: utf-8 -*-
"""
tool_drone_analytics.py

Analises para Drone / Drone Analytics — ferramentas de visão computacional
e sensoriamento remoto para agricultura de precisão com drones.

  1. Contagem de Plantas Automática  — local maxima em índice de vegetação
  2. Detecção de Falhas de Plantio   — gaps na cobertura vegetal esperada
  3. Detecção de Daninhas            — vegetação nas zonas de entreerrei
  4. Altura de Planta (DSM - DTM)    — Canopy Height Model

Requisitos: numpy, scipy, osgeo.gdal — todos incluídos no QGIS.
"""

import os
import math

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QComboBox, QDoubleSpinBox, QSpinBox, QFrame, QGroupBox,
    QWidget, QScrollArea, QApplication, QMessageBox, QFileDialog,
    QLineEdit, QCheckBox, QRadioButton, QButtonGroup, QProgressDialog,
    QSlider,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import (
    Qgis, QgsProject, QgsRasterLayer, QgsVectorLayer,
    QgsField, QgsFeature, QgsGeometry, QgsPointXY,
    QgsCoordinateReferenceSystem, QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant
from core.rth_layer_utils import collapse_layer

# ─── Dependency check ─────────────────────────────────────────────────────────

try:
    import numpy as np
    from scipy.ndimage import (
        maximum_filter, gaussian_filter, label as nd_label,
        binary_closing, binary_dilation, generate_binary_structure,
    )
    from osgeo import gdal, ogr, osr
    gdal.UseExceptions()
    _DEPS_OK = True
    _DEPS_ERR = ''
except ImportError as _e:
    _DEPS_OK = False
    _DEPS_ERR = str(_e)


# ─── Shared raster utilities ──────────────────────────────────────────────────

def _check_deps():
    if not _DEPS_OK:
        raise RuntimeError(
            'Dependencias nao encontradas / Dependencies not found:\n{}\n\n'
            'numpy, scipy e osgeo.gdal sao necessarios (incluidos no QGIS padrao).\n'
            'numpy, scipy and osgeo.gdal are required (bundled with standard QGIS).'.format(
                _DEPS_ERR))


def _open_raster(source):
    """Open a raster file/layer source. Returns gdal.Dataset."""
    ds = gdal.Open(source, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError('Nao foi possivel abrir o raster / Could not open raster:\n{}'.format(source))
    return ds


def _read_band(ds, band_num=1, downsample=1):
    """Read a raster band as float32 numpy array. downsample=2 halves resolution."""
    b = ds.GetRasterBand(band_num)
    w = ds.RasterXSize
    h = ds.RasterYSize
    buf_w = max(1, w // downsample)
    buf_h = max(1, h // downsample)
    data = b.ReadAsArray(buf_xsize=buf_w, buf_ysize=buf_h).astype(np.float32)
    nodata = b.GetNoDataValue()
    if nodata is not None:
        data[data == nodata] = np.nan
    return data, buf_w, buf_h


def _adjusted_gt(ds, downsample):
    """Return geotransform adjusted for a downsampled array."""
    gt = ds.GetGeoTransform()
    return (gt[0], gt[1] * downsample, gt[2],
            gt[3], gt[4], gt[5] * downsample)


def _write_raster(path, data, gt, proj, nodata=-9999.0):
    """Write a float32 GeoTIFF."""
    driver = gdal.GetDriverByName('GTiff')
    h, w = data.shape
    ds_out = driver.Create(path, w, h, 1, gdal.GDT_Float32,
                           ['COMPRESS=LZW', 'BIGTIFF=IF_SAFER'])
    ds_out.SetGeoTransform(gt)
    ds_out.SetProjection(proj)
    band_out = ds_out.GetRasterBand(1)
    out = np.where(np.isnan(data), nodata, data).astype(np.float32)
    band_out.WriteArray(out)
    band_out.SetNoDataValue(nodata)
    ds_out.FlushCache()
    ds_out = None


def _write_byte_raster(path, data_bool, gt, proj):
    """Write a byte (0/1) GeoTIFF for a boolean array."""
    driver = gdal.GetDriverByName('GTiff')
    h, w = data_bool.shape
    ds_out = driver.Create(path, w, h, 1, gdal.GDT_Byte,
                           ['COMPRESS=LZW', 'BIGTIFF=IF_SAFER'])
    ds_out.SetGeoTransform(gt)
    ds_out.SetProjection(proj)
    band_out = ds_out.GetRasterBand(1)
    band_out.WriteArray(data_bool.astype(np.uint8))
    band_out.SetNoDataValue(255)
    ds_out.FlushCache()
    ds_out = None


def _polygonize(raster_path, output_gpkg, layer_name, field_name='DN'):
    """Convert binary raster to polygon layer using GDAL Polygonize."""
    src_ds = gdal.Open(raster_path)
    src_band = src_ds.GetRasterBand(1)

    drv = ogr.GetDriverByName('GPKG')
    if os.path.exists(output_gpkg):
        drv.DeleteDataSource(output_gpkg)
    dst_ds = drv.CreateDataSource(output_gpkg)

    srs = osr.SpatialReference()
    srs.ImportFromWkt(src_ds.GetProjection())
    dst_layer = dst_ds.CreateLayer(layer_name, srs=srs, geom_type=ogr.wkbMultiPolygon)

    fd = ogr.FieldDefn(field_name, ogr.OFTInteger)
    dst_layer.CreateField(fd)

    gdal.Polygonize(src_band, None, dst_layer, 0, [], callback=None)

    dst_ds.Destroy()
    src_ds = None


def _pixel_size_m(gt, proj_wkt):
    """Return (px_w_m, px_h_m) in metres. Assumes metric CRS."""
    return abs(gt[1]), abs(gt[5])


def _compute_veg_index(ds, mode, bands, downsample=1):
    """
    Compute vegetation index array.
    mode:  'single'  — bands=(b,)
           'exg'     — bands=(r,g,b); ExG = 2g - r - b  (normalised 0–1)
           'ndvi'    — bands=(r,nir); NDVI = (nir-r)/(nir+r)
    Returns float32 array in range approx [-1, 1] or [0, 1] depending on mode.
    """
    def _b(n):
        arr, _, _ = _read_band(ds, n, downsample)
        return arr.astype(np.float32)

    if mode == 'single':
        arr, _, _ = _read_band(ds, bands[0], downsample)
        return arr.astype(np.float32)

    elif mode == 'exg':
        r, g, b = _b(bands[0]), _b(bands[1]), _b(bands[2])
        total = r + g + b
        total = np.where(total == 0, np.nan, total)
        rn = r / total; gn = g / total; bn = b / total
        return 2 * gn - rn - bn          # ExG range ≈ [-1, 1]

    elif mode == 'ndvi':
        r, nir = _b(bands[0]), _b(bands[1])
        denom = nir + r
        denom = np.where(denom == 0, np.nan, denom)
        return (nir - r) / denom         # NDVI range [-1, 1]

    raise ValueError('Unknown mode: {}'.format(mode))


# ─── Shared UI helpers ────────────────────────────────────────────────────────

def _sep_widget():
    ln = QFrame()
    ln.setFrameShape(QFrame.HLine)
    ln.setFrameShadow(QFrame.Sunken)
    return ln


def _raster_layers():
    return [(lyr.name(), lyr.source())
            for lyr in QgsProject.instance().mapLayers().values()
            if isinstance(lyr, QgsRasterLayer) and lyr.isValid()]


def _base_dialog(title, subtitle=None, min_w=520):
    """Returns (dialog, outer_layout, root_layout) with scroll already wired."""
    dlg = QDialog()
    dlg.setWindowTitle(title)
    dlg.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
    dlg.setMinimumWidth(min_w)
    dlg.setMinimumHeight(300)
    dlg.setMaximumHeight(860)

    outer = QVBoxLayout(dlg)
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

    lbl_t = QLabel(title.replace('RTH — ', ''))
    lbl_t.setAlignment(Qt.AlignCenter)
    lbl_t.setStyleSheet('font-size:13px;font-weight:bold;')
    root.addWidget(lbl_t)

    if subtitle:
        lbl_s = QLabel(subtitle)
        lbl_s.setAlignment(Qt.AlignCenter)
        lbl_s.setStyleSheet('color:#666;font-size:10px;')
        lbl_s.setWordWrap(True)
        root.addWidget(lbl_s)

    root.addWidget(_sep_widget())
    return dlg, outer, root


def _add_run_close(outer, run_slot, run_label='Executar / Run', color='#1976d2'):
    """Add pinned run+close buttons below scroll. Returns btn_run."""
    outer.addWidget(_sep_widget())
    row = QHBoxLayout()
    row.setContentsMargins(12, 6, 12, 12)

    btn_run = QPushButton(run_label)
    btn_run.setMinimumHeight(38)
    btn_run.setStyleSheet(
        'QPushButton{{background:{c};color:white;font-weight:bold;font-size:12px;'
        'border-radius:5px;border:none;}}'
        'QPushButton:hover{{background:{h};}}'
        'QPushButton:disabled{{background:#999;color:#ccc;}}'.format(
            c=color,
            h='#1565c0' if color == '#1976d2' else '#1b5e20'))
    btn_run.clicked.connect(run_slot)
    row.addWidget(btn_run)

    btn_close = QPushButton('Fechar / Close')
    btn_close.setMinimumHeight(38)
    btn_close.setStyleSheet(
        'QPushButton{background:#616161;color:white;border:none;border-radius:5px;}'
        'QPushButton:hover{background:#424242;}')
    # close will be connected by caller using dlg reference
    row.addWidget(btn_close)
    outer.addLayout(row)
    return btn_run, btn_close


def _veg_index_group(parent_layout, title='Indice de Vegetacao / Vegetation Index'):
    """Builds the vegetation index selector group. Returns a dict of widgets."""
    grp = QGroupBox(title)
    gl = QGridLayout()
    gl.setContentsMargins(8, 6, 8, 8)
    gl.setSpacing(5)
    gl.setColumnStretch(1, 1)

    gl.addWidget(QLabel('Raster:'), 0, 0)
    combo_raster = QComboBox()
    for name, _ in _raster_layers():
        combo_raster.addItem(name)
    gl.addWidget(combo_raster, 0, 1)

    gl.addWidget(QLabel('Tipo de indice / Index type:'), 1, 0)
    combo_type = QComboBox()
    combo_type.addItem('Banda unica / Single band (NDVI pre-calculado, etc.)', 'single')
    combo_type.addItem('ExG — Excess Green (ortofotos RGB)', 'exg')
    combo_type.addItem('NDVI (multiespectral R + NIR)', 'ndvi')
    gl.addWidget(combo_type, 1, 1)

    # ── Single band ────────────────────────────────────────────────────────────
    grp_single = QGroupBox('Banda / Band')
    gs = QHBoxLayout()
    gs.setContentsMargins(4, 4, 4, 4)
    lbl_b1 = QLabel('Banda / Band:')
    spin_b1 = QSpinBox(); spin_b1.setRange(1, 20); spin_b1.setValue(1)
    gs.addWidget(lbl_b1); gs.addWidget(spin_b1); gs.addStretch()
    grp_single.setLayout(gs)
    gl.addWidget(grp_single, 2, 0, 1, 2)

    # ── ExG ───────────────────────────────────────────────────────────────────
    grp_exg = QGroupBox('Bandas RGB')
    ge = QHBoxLayout()
    ge.setContentsMargins(4, 4, 4, 4)
    spin_r = QSpinBox(); spin_r.setRange(1, 20); spin_r.setValue(1)
    spin_g = QSpinBox(); spin_g.setRange(1, 20); spin_g.setValue(2)
    spin_b = QSpinBox(); spin_b.setRange(1, 20); spin_b.setValue(3)
    for lbl, sp in [('R:', spin_r), ('G:', spin_g), ('B:', spin_b)]:
        ge.addWidget(QLabel(lbl)); ge.addWidget(sp)
    ge.addStretch()
    grp_exg.setLayout(ge)
    grp_exg.setVisible(False)
    gl.addWidget(grp_exg, 3, 0, 1, 2)

    # ── NDVI ──────────────────────────────────────────────────────────────────
    grp_ndvi = QGroupBox('Bandas NDVI')
    gn = QHBoxLayout()
    gn.setContentsMargins(4, 4, 4, 4)
    spin_nr = QSpinBox(); spin_nr.setRange(1, 20); spin_nr.setValue(1)
    spin_nn = QSpinBox(); spin_nn.setRange(1, 20); spin_nn.setValue(4)
    for lbl, sp in [('R (vermelho / red):', spin_nr), ('NIR:', spin_nn)]:
        gn.addWidget(QLabel(lbl)); gn.addWidget(sp)
    gn.addStretch()
    grp_ndvi.setLayout(gn)
    grp_ndvi.setVisible(False)
    gl.addWidget(grp_ndvi, 4, 0, 1, 2)

    def _on_type(idx):
        t = combo_type.currentData()
        grp_single.setVisible(t == 'single')
        grp_exg.setVisible(t == 'exg')
        grp_ndvi.setVisible(t == 'ndvi')

    combo_type.currentIndexChanged.connect(_on_type)

    grp.setLayout(gl)
    parent_layout.addWidget(grp)

    return {
        'combo_raster': combo_raster,
        'combo_type':   combo_type,
        'spin_b1':      spin_b1,
        'spin_r':       spin_r, 'spin_g': spin_g, 'spin_b': spin_b,
        'spin_nr':      spin_nr, 'spin_nn': spin_nn,
    }


def _get_veg_params(w):
    """Extract (source_path, mode, bands_tuple) from the _veg_index_group widgets dict."""
    layers = _raster_layers()
    idx = w['combo_raster'].currentIndex()
    if idx < 0 or idx >= len(layers):
        raise RuntimeError(
            'Nenhuma camada raster selecionada / No raster layer selected.\n'
            'Certifique-se de que o raster esta carregado no QGIS. / Make sure the raster is loaded in QGIS.')
    source = layers[idx][1]
    mode = w['combo_type'].currentData()
    if mode == 'single':
        bands = (w['spin_b1'].value(),)
    elif mode == 'exg':
        bands = (w['spin_r'].value(), w['spin_g'].value(), w['spin_b'].value())
    else:
        bands = (w['spin_nr'].value(), w['spin_nn'].value())
    return source, mode, bands


def _output_group(parent_layout, placeholder='saida.gpkg'):
    """Standard output group. Returns (edit_path, edit_name, chk_load)."""
    grp = QGroupBox('Saida / Output')
    gl = QGridLayout()
    gl.setContentsMargins(8, 6, 8, 8)
    gl.setSpacing(5)
    gl.setColumnStretch(1, 1)

    gl.addWidget(QLabel('Arquivo / File:'), 0, 0)
    row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
    edit_path = QLineEdit(); edit_path.setPlaceholderText(placeholder)
    row.addWidget(edit_path)
    btn = QPushButton('...'); btn.setFixedWidth(32)
    btn.clicked.connect(lambda: _browse_gpkg(edit_path))
    row.addWidget(btn)
    gl.addLayout(row, 0, 1)

    gl.addWidget(QLabel('Nome da camada / Layer name:'), 1, 0)
    edit_name = QLineEdit(); edit_name.setPlaceholderText('Resultado_Drone')
    gl.addWidget(edit_name, 1, 1)

    chk_load = QCheckBox('Carregar no QGIS / Load in QGIS')
    chk_load.setChecked(True)
    chk_load.setStyleSheet('font-size:10px;')
    gl.addWidget(chk_load, 2, 0, 1, 2)

    grp.setLayout(gl)
    parent_layout.addWidget(grp)
    return edit_path, edit_name, chk_load


def _browse_gpkg(edit):
    path, _ = QFileDialog.getSaveFileName(None, 'Salvar / Save', '', 'GeoPackage (*.gpkg)')
    if path:
        if not path.lower().endswith('.gpkg'):
            path += '.gpkg'
        edit.setText(path)


def _browse_tif(edit):
    path, _ = QFileDialog.getSaveFileName(None, 'Salvar / Save', '', 'GeoTIFF (*.tif)')
    if path:
        if not path.lower().endswith('.tif'):
            path += '.tif'
        edit.setText(path)


def _load_vector(path, name, iface):
    lyr = QgsVectorLayer(path, name, 'ogr')
    if lyr.isValid():
        QgsProject.instance().addMapLayer(lyr)
        collapse_layer(lyr)
    else:
        iface.messageBar().pushMessage(
            'RTH', 'Nao foi possivel carregar / Could not load: {}'.format(path),
            level=Qgis.MessageLevel.Warning, duration=4)


def _load_raster(path, name, iface):
    lyr = QgsRasterLayer(path, name)
    if lyr.isValid():
        QgsProject.instance().addMapLayer(lyr)
        collapse_layer(lyr)
    else:
        iface.messageBar().pushMessage(
            'RTH', 'Nao foi possivel carregar / Could not load: {}'.format(path),
            level=Qgis.MessageLevel.Warning, duration=4)


# ─── 1. Contagem de Plantas ───────────────────────────────────────────────────

class PlantCountDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        dlg, outer, root = _base_dialog(
            'RTH — Contagem de Plantas / Plant Count',
            'Detecta plantas individuais via maximos locais no indice de vegetacao.\n'
            'Detects individual plants via local maxima in the vegetation index.')
        # steal layout
        self.setWindowTitle(dlg.windowTitle())
        self.setWindowFlags(dlg.windowFlags())
        self.setMinimumWidth(520)
        self.setMaximumHeight(860)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._outer.addWidget(scroll)
        cont = QWidget(); scroll.setWidget(cont)
        root = QVBoxLayout(cont)
        root.setContentsMargins(12, 12, 12, 12); root.setSpacing(8)

        _add_header(root,
            'Contagem de Plantas / Plant Count',
            'Detecta plantas individuais via maximos locais no indice de vegetacao. / Detects individual plants via local maxima in the vegetation index.')

        self._veg_w = _veg_index_group(root)

        grp_p = QGroupBox('Parametros de Deteccao / Detection Parameters')
        gp = QGridLayout(); gp.setContentsMargins(8,6,8,8); gp.setSpacing(5)
        gp.setColumnStretch(1, 1)

        gp.addWidget(QLabel('Limiar de vegetacao / Veg. threshold:'), 0, 0)
        self.spin_thresh = QDoubleSpinBox()
        self.spin_thresh.setRange(-1.0, 1.0); self.spin_thresh.setValue(0.15)
        self.spin_thresh.setSingleStep(0.05); self.spin_thresh.setDecimals(2)
        self.spin_thresh.setToolTip(
            'Pixels acima deste valor sao considerados vegetacao.\n'
            'Pixels above this value are considered vegetation.\n'
            'ExG tipico: 0.05–0.20  |  NDVI tipico: 0.20–0.40')
        gp.addWidget(self.spin_thresh, 0, 1)

        gp.addWidget(QLabel('Janela de maximo local / Local maxima window (px):'), 1, 0)
        self.spin_window = QSpinBox()
        self.spin_window.setRange(3, 99); self.spin_window.setValue(9)
        self.spin_window.setSingleStep(2)
        self.spin_window.setToolTip(
            'Tamanho da janela para encontrar o maximo local (em pixels).\n'
            'Window size for local maxima search (pixels).\n'
            'Tipico: diametro da copa em pixels. Ex: copa 0.3m, GSD 0.03m → 10px → 11')
        gp.addWidget(self.spin_window, 1, 1)

        gp.addWidget(QLabel('Suavizacao / Smoothing (sigma px):'), 2, 0)
        self.spin_sigma = QDoubleSpinBox()
        self.spin_sigma.setRange(0.5, 20.0); self.spin_sigma.setValue(2.0)
        self.spin_sigma.setSingleStep(0.5); self.spin_sigma.setDecimals(1)
        self.spin_sigma.setToolTip(
            'Suavizacao gaussiana antes da deteccao (reduz falsos positivos).\n'
            'Gaussian smoothing before detection (reduces false positives).')
        gp.addWidget(self.spin_sigma, 2, 1)

        gp.addWidget(QLabel('Downsample (1 = resolucao original / original resolution):'), 3, 0)
        self.spin_ds = QSpinBox()
        self.spin_ds.setRange(1, 16); self.spin_ds.setValue(1)
        self.spin_ds.setToolTip(
            'Reduz resolucao antes de processar (economiza memoria).\n'
            'Reduce resolution before processing (saves memory).\n'
            '2 = metade, 4 = quarto da resolucao original.')
        gp.addWidget(self.spin_ds, 3, 1)

        grp_p.setLayout(gp); root.addWidget(grp_p)

        self._edit_out, self._edit_name, self._chk_load = _output_group(root, 'contagem_plantas.gpkg')
        self._edit_name.setPlaceholderText('Contagem_Plantas')

        self._btn_run, btn_close = _add_run_close(self._outer, self._on_run, 'Contar Plantas / Count Plants')
        btn_close.clicked.connect(self.close)

    def _on_run(self):
        try:
            _check_deps()
            source, mode, bands = _get_veg_params(self._veg_w)
            out = self._edit_out.text().strip()
            if not out:
                QMessageBox.warning(self, 'RTH', 'Defina o arquivo de saída. / Define the output file.'); return
            if not out.lower().endswith('.gpkg'): out += '.gpkg'

            ds_val = self.spin_ds.value()
            prog = _progress(self, 'Calculando indice de vegetacao... / Computing vegetation index...')
            prog.show(); QApplication.processEvents()

            ds = _open_raster(source)
            vi = _compute_veg_index(ds, mode, bands, downsample=ds_val)
            gt = _adjusted_gt(ds, ds_val)
            proj = ds.GetProjection()
            ds = None

            prog.setLabelText('Aplicando suavizacao gaussiana... / Applying Gaussian smoothing...')
            QApplication.processEvents()
            smoothed = gaussian_filter(np.nan_to_num(vi, nan=0.0),
                                       sigma=self.spin_sigma.value())

            prog.setLabelText('Detectando maximos locais... / Detecting local maxima...')
            QApplication.processEvents()
            win = self.spin_window.value()
            local_max = (smoothed == maximum_filter(smoothed, size=win))
            veg_mask  = (~np.isnan(vi)) & (vi > self.spin_thresh.value())
            plant_px  = local_max & veg_mask

            rows_idx, cols_idx = np.where(plant_px)

            prog.setLabelText('Criando camada de pontos... / Creating point layer...')
            QApplication.processEvents()

            # Convert pixels to geographic coordinates
            xs = gt[0] + cols_idx * gt[1] + rows_idx * gt[2]
            ys = gt[3] + cols_idx * gt[4] + rows_idx * gt[5]
            vi_vals = smoothed[rows_idx, cols_idx]

            # Write GPKG point layer via OGR
            drv = ogr.GetDriverByName('GPKG')
            if os.path.exists(out): drv.DeleteDataSource(out)
            dst_ds = drv.CreateDataSource(out)
            srs = osr.SpatialReference(); srs.ImportFromWkt(proj)
            dst_lyr = dst_ds.CreateLayer('plantas', srs=srs, geom_type=ogr.wkbPoint)
            dst_lyr.CreateField(ogr.FieldDefn('id', ogr.OFTInteger))
            dst_lyr.CreateField(ogr.FieldDefn('vi_value', ogr.OFTReal))

            for i, (x, y, vi_v) in enumerate(zip(xs, ys, vi_vals)):
                feat = ogr.Feature(dst_lyr.GetLayerDefn())
                pt = ogr.Geometry(ogr.wkbPoint)
                pt.AddPoint(float(x), float(y))
                feat.SetGeometry(pt)
                feat.SetField('id', i + 1)
                feat.SetField('vi_value', float(vi_v))
                dst_lyr.CreateFeature(feat)
            dst_ds.Destroy()

            prog.close()

            n_plants = int(len(xs))
            px_w, px_h = abs(gt[1]), abs(gt[5])
            h_arr, w_arr = vi.shape
            area_ha = (w_arr * h_arr * px_w * px_h) / 10_000
            density = n_plants / area_ha if area_ha > 0 else 0

            if self._chk_load.isChecked():
                name = self._edit_name.text().strip() or 'Contagem_Plantas'
                _load_vector(out, name, self.iface)

            QMessageBox.information(self, 'RTH — Contagem de Plantas / Plant Count',
                'Plantas detectadas / Plants detected: {:,}\n'
                'Area analisada / Analysed area: {:.2f} ha\n'
                'Densidade / Density: {:.0f} plantas/ha\n\n'
                'Arquivo / File: {}'.format(n_plants, area_ha, density, out))

        except RuntimeError as e:
            if 'prog' in dir(): prog.close()
            QMessageBox.critical(self, 'RTH', str(e))
        except Exception as e:
            if 'prog' in dir(): prog.close()
            QMessageBox.critical(self, 'RTH', 'Erro inesperado / Unexpected error:\n{}'.format(str(e)))


# ─── 2. Detecção de Falhas de Plantio ────────────────────────────────────────

class PlantingGapsDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle('RTH — Deteccao de Falhas de Plantio / Planting Gap Detection')
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(540); self.setMaximumHeight(860)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0); self._outer.setSpacing(0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._outer.addWidget(scroll)
        cont = QWidget(); scroll.setWidget(cont)
        root = QVBoxLayout(cont)
        root.setContentsMargins(12, 12, 12, 12); root.setSpacing(8)

        _add_header(root,
            'Deteccao de Falhas de Plantio / Planting Gap Detection',
            'Identifica areas sem cobertura vegetal dentro do talhao.\n'
            'Identifies areas without vegetation cover within the field.')

        self._veg_w = _veg_index_group(root)

        grp_p = QGroupBox('Parametros de Linha / Row Parameters')
        gp = QGridLayout(); gp.setContentsMargins(8,6,8,8); gp.setSpacing(5)
        gp.setColumnStretch(1, 1)

        gp.addWidget(QLabel('Limiar de vegetacao / Veg. threshold:'), 0, 0)
        self.spin_thresh = QDoubleSpinBox()
        self.spin_thresh.setRange(-1.0, 1.0); self.spin_thresh.setValue(0.15)
        self.spin_thresh.setSingleStep(0.05); self.spin_thresh.setDecimals(2)
        gp.addWidget(self.spin_thresh, 0, 1)

        gp.addWidget(QLabel('Direcao das linhas / Row direction (°):'), 1, 0)
        self.spin_dir = QDoubleSpinBox()
        self.spin_dir.setRange(0.0, 179.9); self.spin_dir.setValue(0.0)
        self.spin_dir.setSuffix(' °'); self.spin_dir.setDecimals(1)
        self.spin_dir.setToolTip('0° = linhas N-S  |  90° = linhas L-O  |  45° = diagonal')
        gp.addWidget(self.spin_dir, 1, 1)

        gp.addWidget(QLabel('Espaçamento entre linhas / Row spacing (m):'), 2, 0)
        self.spin_spacing = QDoubleSpinBox()
        self.spin_spacing.setRange(0.1, 50.0); self.spin_spacing.setValue(0.5)
        self.spin_spacing.setSuffix(' m'); self.spin_spacing.setDecimals(2)
        gp.addWidget(self.spin_spacing, 2, 1)

        gp.addWidget(QLabel('Largura da faixa de cultura / Crop row width (m):'), 3, 0)
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.05, 10.0); self.spin_width.setValue(0.2)
        self.spin_width.setSuffix(' m'); self.spin_width.setDecimals(2)
        gp.addWidget(self.spin_width, 3, 1)

        gp.addWidget(QLabel('Area minima de falha / Min gap area (m²):'), 4, 0)
        self.spin_min_area = QDoubleSpinBox()
        self.spin_min_area.setRange(0.01, 1000.0); self.spin_min_area.setValue(0.1)
        self.spin_min_area.setSuffix(' m²'); self.spin_min_area.setDecimals(2)
        gp.addWidget(self.spin_min_area, 4, 1)

        gp.addWidget(QLabel('Downsample (1 = resolucao original / original resolution):'), 5, 0)
        self.spin_ds = QSpinBox()
        self.spin_ds.setRange(1, 16); self.spin_ds.setValue(2)
        gp.addWidget(self.spin_ds, 5, 1)

        grp_p.setLayout(gp); root.addWidget(grp_p)

        self._edit_out, self._edit_name, self._chk_load = _output_group(root, 'falhas_plantio.gpkg')
        self._edit_name.setPlaceholderText('Falhas_Plantio')

        self._btn_run, btn_close = _add_run_close(
            self._outer, self._on_run, 'Detectar Falhas / Detect Gaps', '#e65100')
        btn_close.clicked.connect(self.close)

    def _on_run(self):
        try:
            _check_deps()
            source, mode, bands = _get_veg_params(self._veg_w)
            out = self._edit_out.text().strip()
            if not out: QMessageBox.warning(self, 'RTH', 'Defina o arquivo de saida. / Define the output file.'); return
            if not out.lower().endswith('.gpkg'): out += '.gpkg'

            ds_val = self.spin_ds.value()
            prog = _progress(self, 'Calculando indice de vegetacao... / Computing vegetation index...')
            prog.show(); QApplication.processEvents()

            ds = _open_raster(source)
            vi = _compute_veg_index(ds, mode, bands, downsample=ds_val)
            gt = _adjusted_gt(ds, ds_val)
            proj = ds.GetProjection()
            ds = None

            prog.setLabelText('Calculando mascara de vegetacao... / Computing vegetation mask...')
            QApplication.processEvents()

            veg_mask = (~np.isnan(vi)) & (vi > self.spin_thresh.value())

            prog.setLabelText('Calculando mascara de linhas de cultivo... / Computing crop row mask...')
            QApplication.processEvents()

            h, w = vi.shape
            px_w, px_h = abs(gt[1]), abs(gt[5])
            cols_i, rows_i = np.meshgrid(np.arange(w), np.arange(h))
            x_map = gt[0] + cols_i * gt[1]
            y_map = gt[3] + rows_i * gt[5]

            az_rad = math.radians(self.spin_dir.value())
            perp_x = math.cos(az_rad); perp_y = -math.sin(az_rad)
            perp_dist = x_map * perp_x + y_map * perp_y

            row_sp = self.spin_spacing.value()
            row_w  = self.spin_width.value()
            cycle  = perp_dist % row_sp
            cycle  = np.where(cycle < 0, cycle + row_sp, cycle)
            in_row = (cycle < row_w / 2.0) | (cycle > row_sp - row_w / 2.0)

            # Gaps = expected crop row but no vegetation
            gaps = in_row & (~veg_mask)

            # Morphological closing to remove tiny holes
            struct = generate_binary_structure(2, 2)
            gaps_clean = binary_closing(gaps, structure=struct, iterations=2)

            prog.setLabelText('Poligonizando falhas... / Polygonizing gaps...')
            QApplication.processEvents()

            # Write temp raster, polygonize, filter by area
            tmp = out.replace('.gpkg', '_tmp_gap.tif')
            _write_byte_raster(tmp, gaps_clean, gt, proj)

            _polygonize(tmp, out, 'falhas', 'tipo')

            # Filter by min area and type=1
            drv = ogr.GetDriverByName('GPKG')
            edit_ds = drv.Open(out, 1)
            lyr = edit_ds.GetLayer('falhas')
            min_area_m2 = self.spin_min_area.value()
            to_delete = []
            lyr.ResetReading()
            for feat in lyr:
                geom = feat.GetGeometryRef()
                dn   = feat.GetField('tipo')
                area = geom.GetArea() if geom else 0
                if dn != 1 or area < min_area_m2:
                    to_delete.append(feat.GetFID())
            for fid in to_delete:
                lyr.DeleteFeature(fid)
            edit_ds.ExecuteSQL('VACUUM INTO "{}"'.format(out))
            edit_ds.Destroy()

            try: os.remove(tmp)
            except Exception: pass  # nosec B110

            gap_px   = int(np.sum(gaps_clean))
            area_ha  = (w * h * px_w * px_h) / 10_000
            gap_area = gap_px * px_w * px_h
            gap_pct  = gap_area / (w * h * px_w * px_h) * 100 if (w * h) > 0 else 0
            prog.close()

            if self._chk_load.isChecked():
                name = self._edit_name.text().strip() or 'Falhas_Plantio'
                _load_vector(out, name, self.iface)

            QMessageBox.information(self, 'RTH — Falhas de Plantio / Planting Gaps',
                'Area total de falhas / Total gap area: {:.2f} m²\n'
                'Percentual de falhas / Gap percentage: {:.1f}%\n'
                'Area analisada / Analysed area: {:.2f} ha\n\n'
                'Arquivo / File: {}'.format(gap_area, gap_pct, area_ha, out))

        except RuntimeError as e:
            if 'prog' in dir(): prog.close()
            QMessageBox.critical(self, 'RTH', str(e))
        except Exception as e:
            if 'prog' in dir(): prog.close()
            QMessageBox.critical(self, 'RTH', 'Erro inesperado / Unexpected error:\n{}'.format(str(e)))


# ─── 3. Detecção de Daninhas ─────────────────────────────────────────────────

class WeedDetectionDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle('RTH — Deteccao de Daninhas / Weed Detection')
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(540); self.setMaximumHeight(860)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0); self._outer.setSpacing(0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._outer.addWidget(scroll)
        cont = QWidget(); scroll.setWidget(cont)
        root = QVBoxLayout(cont)
        root.setContentsMargins(12, 12, 12, 12); root.setSpacing(8)

        _add_header(root,
            'Deteccao de Daninhas / Weed Detection',
            'Detecta vegetacao nas zonas de entreerrei (daninhas / plantas invasoras).\n'
            'Detects vegetation in inter-row zones (weeds / invasive plants).')

        self._veg_w = _veg_index_group(root)

        grp_p = QGroupBox('Parametros de Linha / Row & Threshold Parameters')
        gp = QGridLayout(); gp.setContentsMargins(8,6,8,8); gp.setSpacing(5)
        gp.setColumnStretch(1, 1)

        gp.addWidget(QLabel('Limiar de vegetacao / Veg. threshold:'), 0, 0)
        self.spin_thresh = QDoubleSpinBox()
        self.spin_thresh.setRange(-1.0, 1.0); self.spin_thresh.setValue(0.15)
        self.spin_thresh.setSingleStep(0.05); self.spin_thresh.setDecimals(2)
        gp.addWidget(self.spin_thresh, 0, 1)

        gp.addWidget(QLabel('Direcao das linhas / Row direction (°):'), 1, 0)
        self.spin_dir = QDoubleSpinBox()
        self.spin_dir.setRange(0.0, 179.9); self.spin_dir.setValue(0.0)
        self.spin_dir.setSuffix(' °'); self.spin_dir.setDecimals(1)
        gp.addWidget(self.spin_dir, 1, 1)

        gp.addWidget(QLabel('Espaçamento entre linhas / Row spacing (m):'), 2, 0)
        self.spin_spacing = QDoubleSpinBox()
        self.spin_spacing.setRange(0.1, 50.0); self.spin_spacing.setValue(0.5)
        self.spin_spacing.setSuffix(' m'); self.spin_spacing.setDecimals(2)
        gp.addWidget(self.spin_spacing, 2, 1)

        gp.addWidget(QLabel('Largura da faixa de cultura / Crop row width (m):'), 3, 0)
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.05, 10.0); self.spin_width.setValue(0.2)
        self.spin_width.setSuffix(' m'); self.spin_width.setDecimals(2)
        gp.addWidget(self.spin_width, 3, 1)

        gp.addWidget(QLabel('Area minima de daninha / Min weed area (m²):'), 4, 0)
        self.spin_min_area = QDoubleSpinBox()
        self.spin_min_area.setRange(0.001, 1000.0); self.spin_min_area.setValue(0.05)
        self.spin_min_area.setSuffix(' m²'); self.spin_min_area.setDecimals(3)
        gp.addWidget(self.spin_min_area, 4, 1)

        gp.addWidget(QLabel('Downsample (1 = resolucao original / original resolution):'), 5, 0)
        self.spin_ds = QSpinBox()
        self.spin_ds.setRange(1, 16); self.spin_ds.setValue(2)
        gp.addWidget(self.spin_ds, 5, 1)

        grp_p.setLayout(gp); root.addWidget(grp_p)

        lbl_note = QLabel(
            'ℹ  Limitacao: assume que TODA vegetacao fora das linhas e daninha.\n'
            '   Para maior precisao use imagens multiespectrais com separacao espectral.\n'
            '   Limitation: assumes ALL vegetation outside rows is weed.\n'
            '   For higher accuracy use multispectral images with spectral separation.')
        lbl_note.setStyleSheet(
            'font-size:9px;color:#555;background:#fffde7;border:1px solid #f9a825;'
            'border-radius:3px;padding:5px;')
        lbl_note.setWordWrap(True)
        root.addWidget(lbl_note)

        self._edit_out, self._edit_name, self._chk_load = _output_group(root, 'daninhas.gpkg')
        self._edit_name.setPlaceholderText('Daninhas')

        self._btn_run, btn_close = _add_run_close(
            self._outer, self._on_run, 'Detectar Daninhas / Detect Weeds', '#c62828')
        btn_close.clicked.connect(self.close)

    def _on_run(self):
        try:
            _check_deps()
            source, mode, bands = _get_veg_params(self._veg_w)
            out = self._edit_out.text().strip()
            if not out: QMessageBox.warning(self, 'RTH', 'Defina o arquivo de saida. / Define the output file.'); return
            if not out.lower().endswith('.gpkg'): out += '.gpkg'

            ds_val = self.spin_ds.value()
            prog = _progress(self, 'Calculando indice de vegetacao... / Computing vegetation index...')
            prog.show(); QApplication.processEvents()

            ds = _open_raster(source)
            vi = _compute_veg_index(ds, mode, bands, downsample=ds_val)
            gt = _adjusted_gt(ds, ds_val)
            proj = ds.GetProjection()
            ds = None

            prog.setLabelText('Criando mascara de entreerrei... / Creating inter-row mask...')
            QApplication.processEvents()

            h, w = vi.shape
            px_w, px_h = abs(gt[1]), abs(gt[5])
            cols_i, rows_i = np.meshgrid(np.arange(w), np.arange(h))
            x_map = gt[0] + cols_i * gt[1]
            y_map = gt[3] + rows_i * gt[5]

            az_rad  = math.radians(self.spin_dir.value())
            perp_x  = math.cos(az_rad); perp_y = -math.sin(az_rad)
            perp_dist = x_map * perp_x + y_map * perp_y

            row_sp = self.spin_spacing.value()
            row_w  = self.spin_width.value()
            cycle  = perp_dist % row_sp
            cycle  = np.where(cycle < 0, cycle + row_sp, cycle)
            in_row = (cycle < row_w / 2.0) | (cycle > row_sp - row_w / 2.0)
            inter_row = ~in_row

            veg_mask = (~np.isnan(vi)) & (vi > self.spin_thresh.value())
            weeds    = inter_row & veg_mask

            struct = generate_binary_structure(2, 2)
            weeds_clean = binary_closing(weeds, structure=struct, iterations=1)

            prog.setLabelText('Poligonizando daninhas... / Polygonizing weeds...')
            QApplication.processEvents()

            tmp = out.replace('.gpkg', '_tmp_weed.tif')
            _write_byte_raster(tmp, weeds_clean, gt, proj)
            _polygonize(tmp, out, 'daninhas', 'tipo')

            # Filter by min area and type=1
            drv = ogr.GetDriverByName('GPKG')
            edit_ds = drv.Open(out, 1)
            lyr = edit_ds.GetLayer('daninhas')
            min_area_m2 = self.spin_min_area.value()
            to_delete = []
            lyr.ResetReading()
            for feat in lyr:
                geom = feat.GetGeometryRef()
                dn   = feat.GetField('tipo')
                area = geom.GetArea() if geom else 0
                if dn != 1 or area < min_area_m2:
                    to_delete.append(feat.GetFID())
            for fid in to_delete:
                lyr.DeleteFeature(fid)
            edit_ds.Destroy()

            try: os.remove(tmp)
            except Exception: pass  # nosec B110

            weed_px  = int(np.sum(weeds_clean))
            weed_area = weed_px * px_w * px_h
            total_area = w * h * px_w * px_h
            weed_pct = weed_area / total_area * 100 if total_area > 0 else 0
            prog.close()

            if self._chk_load.isChecked():
                name = self._edit_name.text().strip() or 'Daninhas'
                _load_vector(out, name, self.iface)

            QMessageBox.information(self, 'RTH — Deteccao de Daninhas / Weed Detection',
                'Area de daninhas / Weed area: {:.2f} m²  ({:.4f} ha)\n'
                'Percentual de infestacao / Infestation rate: {:.1f}%\n'
                'Area analisada / Analysed area: {:.2f} ha\n\n'
                'Arquivo / File: {}'.format(
                    weed_area, weed_area / 10_000, weed_pct, total_area / 10_000, out))

        except RuntimeError as e:
            if 'prog' in dir(): prog.close()
            QMessageBox.critical(self, 'RTH', str(e))
        except Exception as e:
            if 'prog' in dir(): prog.close()
            QMessageBox.critical(self, 'RTH', 'Erro inesperado / Unexpected error:\n{}'.format(str(e)))


# ─── 4. Altura de Planta (DSM - DTM) ─────────────────────────────────────────

class PlantHeightDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle('RTH — Altura de Planta via DSM - DTM / Plant Height CHM')
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(560); self.setMaximumHeight(860)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0); self._outer.setSpacing(0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._outer.addWidget(scroll)
        cont = QWidget(); scroll.setWidget(cont)
        root = QVBoxLayout(cont)
        root.setContentsMargins(12, 12, 12, 12); root.setSpacing(8)

        _add_header(root,
            'Altura de Planta / Plant Height  (CHM = DSM - DTM)',
            'Modelo de Altura de Copas: subtrai o terreno (DTM) da superficie (DSM).\n'
            'Canopy Height Model: subtracts terrain (DTM) from surface (DSM).')

        # ── DSM ────────────────────────────────────────────────────────────────
        grp_dsm = QGroupBox('DSM — Modelo Digital de Superficie / Digital Surface Model')
        gd = QGridLayout(); gd.setContentsMargins(8,6,8,8); gd.setSpacing(5)
        gd.setColumnStretch(1, 1)

        gd.addWidget(QLabel('Camada DSM / DSM layer:'), 0, 0)
        self.combo_dsm = QComboBox()
        for name, _ in _raster_layers(): self.combo_dsm.addItem(name)
        gd.addWidget(self.combo_dsm, 0, 1)

        gd.addWidget(QLabel('Banda / Band:'), 1, 0)
        self.spin_dsm_band = QSpinBox()
        self.spin_dsm_band.setRange(1, 20); self.spin_dsm_band.setValue(1)
        gd.addWidget(self.spin_dsm_band, 1, 1)

        grp_dsm.setLayout(gd); root.addWidget(grp_dsm)

        # ── DTM ────────────────────────────────────────────────────────────────
        grp_dtm = QGroupBox('DTM — Modelo Digital de Terreno / Digital Terrain Model')
        gt_g = QGridLayout(); gt_g.setContentsMargins(8,6,8,8); gt_g.setSpacing(5)
        gt_g.setColumnStretch(1, 1)

        gt_g.addWidget(QLabel('Camada DTM / DTM layer:'), 0, 0)
        self.combo_dtm = QComboBox()
        for name, _ in _raster_layers(): self.combo_dtm.addItem(name)
        if self.combo_dtm.count() > 1: self.combo_dtm.setCurrentIndex(1)
        gt_g.addWidget(self.combo_dtm, 0, 1)

        gt_g.addWidget(QLabel('Banda / Band:'), 1, 0)
        self.spin_dtm_band = QSpinBox()
        self.spin_dtm_band.setRange(1, 20); self.spin_dtm_band.setValue(1)
        gt_g.addWidget(self.spin_dtm_band, 1, 1)

        grp_dtm.setLayout(gt_g); root.addWidget(grp_dtm)

        # ── Options ────────────────────────────────────────────────────────────
        grp_opt = QGroupBox('Opcoes / Options')
        go = QGridLayout(); go.setContentsMargins(8,6,8,8); go.setSpacing(5)
        go.setColumnStretch(1, 1)

        go.addWidget(QLabel('Altura minima valida / Min valid height (m):'), 0, 0)
        self.spin_min_h = QDoubleSpinBox()
        self.spin_min_h.setRange(-10.0, 100.0); self.spin_min_h.setValue(0.0)
        self.spin_min_h.setSuffix(' m'); self.spin_min_h.setDecimals(1)
        self.spin_min_h.setToolTip(
            'Valores de CHM abaixo disso serao zerados (ex: 0 = sem altura negativa).\n'
            'CHM values below this will be zeroed (e.g. 0 = no negative heights).')
        go.addWidget(self.spin_min_h, 0, 1)

        go.addWidget(QLabel('Altura maxima valida / Max valid height (m):'), 1, 0)
        self.spin_max_h = QDoubleSpinBox()
        self.spin_max_h.setRange(0.0, 500.0); self.spin_max_h.setValue(30.0)
        self.spin_max_h.setSuffix(' m'); self.spin_max_h.setDecimals(1)
        self.spin_max_h.setToolTip('Valores acima serao marcados como NoData (remove artefatos).\n'
                                   'Values above will be marked as NoData (removes artifacts).')
        go.addWidget(self.spin_max_h, 1, 1)

        go.addWidget(QLabel('Downsample (1 = resolucao original / original resolution):'), 2, 0)
        self.spin_ds = QSpinBox()
        self.spin_ds.setRange(1, 8); self.spin_ds.setValue(1)
        go.addWidget(self.spin_ds, 2, 1)

        self.chk_hillshade = QCheckBox(
            'Gerar Hillshade do CHM / Generate CHM Hillshade')
        self.chk_hillshade.setStyleSheet('font-size:10px;')
        go.addWidget(self.chk_hillshade, 3, 0, 1, 2)

        grp_opt.setLayout(go); root.addWidget(grp_opt)

        # ── Output ─────────────────────────────────────────────────────────────
        grp_out = QGroupBox('Saida / Output')
        gout = QGridLayout(); gout.setContentsMargins(8,6,8,8); gout.setSpacing(5)
        gout.setColumnStretch(1, 1)

        gout.addWidget(QLabel('Arquivo CHM / CHM file (.tif):'), 0, 0)
        row_o = QHBoxLayout(); row_o.setContentsMargins(0,0,0,0)
        self.edit_output = QLineEdit(); self.edit_output.setPlaceholderText('chm_drone.tif')
        row_o.addWidget(self.edit_output)
        btn_o = QPushButton('...'); btn_o.setFixedWidth(32)
        btn_o.clicked.connect(lambda: _browse_tif(self.edit_output))
        row_o.addWidget(btn_o)
        gout.addLayout(row_o, 0, 1)

        gout.addWidget(QLabel('Nome da camada / Layer name:'), 1, 0)
        self.edit_name = QLineEdit(); self.edit_name.setPlaceholderText('CHM_Drone')
        gout.addWidget(self.edit_name, 1, 1)

        self.chk_load = QCheckBox('Carregar no QGIS / Load in QGIS')
        self.chk_load.setChecked(True); self.chk_load.setStyleSheet('font-size:10px;')
        gout.addWidget(self.chk_load, 2, 0, 1, 2)

        grp_out.setLayout(gout); root.addWidget(grp_out)

        self._btn_run, btn_close = _add_run_close(
            self._outer, self._on_run, 'Calcular CHM / Calculate CHM', '#2e7d32')
        btn_close.clicked.connect(self.close)

    def _on_run(self):
        try:
            _check_deps()
            layers = _raster_layers()
            if not layers:
                raise RuntimeError(
                    'Nenhuma camada raster carregada / No raster layer loaded.')

            out = self.edit_output.text().strip()
            if not out: QMessageBox.warning(self, 'RTH', 'Defina o arquivo de saida. / Define the output file.'); return
            if not out.lower().endswith('.tif'): out += '.tif'

            idx_dsm = self.combo_dsm.currentIndex()
            idx_dtm = self.combo_dtm.currentIndex()
            if idx_dsm < 0 or idx_dsm >= len(layers):
                raise RuntimeError('Selecione uma camada DSM valida. / Select a valid DSM layer.')
            if idx_dtm < 0 or idx_dtm >= len(layers):
                raise RuntimeError('Selecione uma camada DTM valida. / Select a valid DTM layer.')

            dsm_src = layers[idx_dsm][1]
            dtm_src = layers[idx_dtm][1]
            ds_val  = self.spin_ds.value()

            prog = _progress(self, 'Lendo DSM... / Reading DSM...')
            prog.show(); QApplication.processEvents()

            ds_dsm = _open_raster(dsm_src)
            dsm, _, _ = _read_band(ds_dsm, self.spin_dsm_band.value(), ds_val)
            gt  = _adjusted_gt(ds_dsm, ds_val)
            proj = ds_dsm.GetProjection()
            ds_dsm = None

            prog.setLabelText('Lendo DTM... / Reading DTM...')
            QApplication.processEvents()

            ds_dtm = _open_raster(dtm_src)
            dtm, _, _ = _read_band(ds_dtm, self.spin_dtm_band.value(), ds_val)

            # Resample DTM to DSM shape if needed
            if dtm.shape != dsm.shape:
                from scipy.ndimage import zoom
                zoom_r = (dsm.shape[0] / dtm.shape[0], dsm.shape[1] / dtm.shape[1])
                dtm = zoom(dtm, zoom_r, order=1)
            ds_dtm = None

            prog.setLabelText('Calculando CHM = DSM - DTM... / Computing CHM = DSM - DTM...')
            QApplication.processEvents()

            chm = dsm - dtm

            min_h = self.spin_min_h.value()
            max_h = self.spin_max_h.value()
            chm = np.where(np.isnan(chm), np.nan, chm)
            chm = np.where(chm < min_h, min_h, chm)
            chm = np.where(chm > max_h, np.nan, chm)

            prog.setLabelText('Escrevendo CHM... / Writing CHM...')
            QApplication.processEvents()
            _write_raster(out, chm, gt, proj)

            # ── Hillshade ──────────────────────────────────────────────────────
            hs_path = None
            if self.chk_hillshade.isChecked():
                prog.setLabelText('Gerando hillshade... / Generating hillshade...')
                QApplication.processEvents()
                try:
                    import processing
                    hs_path = out.replace('.tif', '_hillshade.tif')
                    res = processing.run('gdal:hillshade', {
                        'INPUT': out, 'BAND': 1,
                        'Z_FACTOR': 2.0, 'SCALE': 1.0,
                        'AZIMUTH': 315.0, 'ALTITUDE': 45.0,
                        'COMBINED': False, 'MULTIDIRECTIONAL': False,
                        'OPTIONS': 'COMPRESS=LZW', 'EXTRA': '',
                        'OUTPUT': hs_path,
                    })
                    hs_path = res.get('OUTPUT', hs_path)
                except Exception:
                    hs_path = None

            prog.close()

            # ── Statistics ────────────────────────────────────────────────────
            valid = chm[~np.isnan(chm) & (chm >= min_h)]
            stats_txt = ''
            if len(valid) > 0:
                stats_txt = (
                    '\nEstatisticas / Statistics:\n'
                    '  Altura media / Mean height: {:.2f} m\n'
                    '  Altura maxima / Max height:  {:.2f} m\n'
                    '  Altura minima valida / Min:  {:.2f} m\n'
                    '  Desvio padrao / Std dev:     {:.2f} m\n'
                    '  Percentil 75 / P75:          {:.2f} m\n'
                    '  Percentil 90 / P90:          {:.2f} m'.format(
                        float(np.mean(valid)),
                        float(np.max(valid)),
                        float(np.min(valid)),
                        float(np.std(valid)),
                        float(np.percentile(valid, 75)),
                        float(np.percentile(valid, 90))))

            # ── Load ──────────────────────────────────────────────────────────
            if self.chk_load.isChecked():
                name = self.edit_name.text().strip() or 'CHM_Drone'
                _load_raster(out, name, self.iface)
                if hs_path and os.path.exists(hs_path):
                    _load_raster(hs_path, name + '_Hillshade', self.iface)

            QMessageBox.information(self, 'RTH — CHM / Canopy Height Model',
                'CHM gerado / CHM generated: {}{}'.format(out, stats_txt))

        except RuntimeError as e:
            if 'prog' in dir(): prog.close()
            QMessageBox.critical(self, 'RTH', str(e))
        except Exception as e:
            if 'prog' in dir(): prog.close()
            QMessageBox.critical(self, 'RTH', 'Erro inesperado / Unexpected error:\n{}'.format(str(e)))


# ─── Shared internal helpers (must come before class definitions above) ───────

def _add_header(root, title, subtitle=None):
    lbl = QLabel(title)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setStyleSheet('font-size:13px;font-weight:bold;')
    root.addWidget(lbl)
    if subtitle:
        ls = QLabel(subtitle)
        ls.setAlignment(Qt.AlignCenter)
        ls.setStyleSheet('color:#666;font-size:10px;')
        ls.setWordWrap(True)
        root.addWidget(ls)
    root.addWidget(_sep_widget())


def _progress(parent, msg):
    dlg = QProgressDialog(msg, None, 0, 0, parent)
    dlg.setWindowTitle('RTH Analytics')
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setValue(0)
    return dlg


# ─── Tool classes ─────────────────────────────────────────────────────────────

class PlantCountTool:
    def __init__(self, iface): self.iface = iface; self._dlg = None
    def run(self):
        if self._dlg is None or not self._dlg.isVisible():
            self._dlg = PlantCountDialog(self.iface, parent=self.iface.mainWindow())
        self._dlg.show(); self._dlg.raise_(); self._dlg.activateWindow()


class PlantingGapsTool:
    def __init__(self, iface): self.iface = iface; self._dlg = None
    def run(self):
        if self._dlg is None or not self._dlg.isVisible():
            self._dlg = PlantingGapsDialog(self.iface, parent=self.iface.mainWindow())
        self._dlg.show(); self._dlg.raise_(); self._dlg.activateWindow()


class WeedDetectionTool:
    def __init__(self, iface): self.iface = iface; self._dlg = None
    def run(self):
        if self._dlg is None or not self._dlg.isVisible():
            self._dlg = WeedDetectionDialog(self.iface, parent=self.iface.mainWindow())
        self._dlg.show(); self._dlg.raise_(); self._dlg.activateWindow()


class PlantHeightTool:
    def __init__(self, iface): self.iface = iface; self._dlg = None
    def run(self):
        if self._dlg is None or not self._dlg.isVisible():
            self._dlg = PlantHeightDialog(self.iface, parent=self.iface.mainWindow())
        self._dlg.show(); self._dlg.raise_(); self._dlg.activateWindow()
