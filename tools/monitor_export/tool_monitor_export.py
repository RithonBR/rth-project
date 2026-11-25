# -*- coding: utf-8 -*-
import os
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET


def _pretty_xml(root):
    """Indent an ElementTree in-place and return it as a formatted XML string.
    Replaces minidom.parseString to avoid parsing externally-generated XML.
    """
    def _indent(elem, level=0):
        pad = '\n' + '  ' * level
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = pad + '  '
            if not elem.tail or not elem.tail.strip():
                elem.tail = pad
            for child in elem:
                _indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = pad
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = pad
    _indent(root)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding='unicode')

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QLineEdit, QFileDialog,
    QFrame, QRadioButton, QButtonGroup, QWidget
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QBrush
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsVectorFileWriter, QgsFeature, QgsFields
)

# Cada marca: has_iso_xml, abreviação no ícone, cor de fundo, cor do texto
# Each brand: has_iso_xml, icon abbreviation, background color, text color
MONITORS = {
    'John Deere':  {'has_iso_xml': True,  'abbrev': 'JD',  'bg': '#367C2B', 'fg': '#FFDE00'},
    'Case IH':     {'has_iso_xml': False, 'abbrev': 'CIH', 'bg': '#C41230', 'fg': '#FFFFFF'},
    'New Holland': {'has_iso_xml': False, 'abbrev': 'NH',  'bg': '#003F87', 'fg': '#FFFFFF'},
    'Trimble':     {'has_iso_xml': False, 'abbrev': 'TRM', 'bg': '#FFCC00', 'fg': '#1A1A1A'},
    'Topcon':      {'has_iso_xml': False, 'abbrev': 'TOP', 'bg': '#E31937', 'fg': '#FFFFFF'},
    'Raven':       {'has_iso_xml': False, 'abbrev': 'RAV', 'bg': '#003087', 'fg': '#FFFFFF'},
    'SOLINFTEC':   {'has_iso_xml': False, 'abbrev': 'SOL', 'bg': '#FF6B00', 'fg': '#FFFFFF'},
    'Ag-Leader':   {'has_iso_xml': False, 'abbrev': 'AGL', 'bg': '#00563F', 'fg': '#FFFFFF'},
}


def make_brand_icon(monitor_name, size=22):
    """Gera QIcon colorido com abreviação da marca / Generates colored QIcon with brand abbreviation."""
    cfg    = MONITORS.get(monitor_name, {})
    abbrev = cfg.get('abbrev', monitor_name[:3].upper())
    bg     = cfg.get('bg', '#555555')
    fg     = cfg.get('fg', '#FFFFFF')

    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(bg))

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    except AttributeError:
        painter.setRenderHint(QPainter.Antialiasing)

    font = QFont()
    font.setBold(True)
    font.setPointSize(size // 3 if len(abbrev) >= 3 else size // 2 - 1)
    painter.setFont(font)
    painter.setPen(QColor(fg))
    try:
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, abbrev)
    except AttributeError:
        painter.drawText(pixmap.rect(), Qt.AlignCenter, abbrev)
    painter.end()

    return QIcon(pixmap)


def make_tool_icon(size=22):
    """Gera QIcon genérico de monitor agrícola para o submenu / Generates generic agricultural monitor icon."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    except AttributeError:
        painter.setRenderHint(QPainter.Antialiasing)

    # Tela do monitor / Monitor screen
    screen_h = size * 14 // 20
    painter.setBrush(QBrush(QColor('#1a73e8')))
    painter.setPen(QColor('#0d47a1'))
    painter.drawRoundedRect(1, 1, size - 2, screen_h, 2, 2)

    # Interior branco / White interior
    painter.setBrush(QBrush(QColor('#ffffff')))
    painter.setPen(QColor(0, 0, 0, 0))
    painter.drawRect(3, 3, size - 6, screen_h - 4)

    # Sinal verde no centro / Green signal dot in center
    cx = size // 2
    cy = screen_h // 2 + 1
    r  = size // 8
    painter.setBrush(QBrush(QColor('#34a853')))
    painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

    # Haste / Stand
    painter.setBrush(QBrush(QColor('#5c85d6')))
    painter.drawRect(cx - 2, screen_h + 1, 4, 3)

    # Base
    base_w = size * 12 // 20
    painter.drawRect(cx - base_w // 2, screen_h + 4, base_w, 2)

    painter.end()
    return QIcon(pixmap)


class MonitorExportDialog(QDialog):

    def __init__(self, iface, monitor_name, has_iso_xml, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.monitor_name = monitor_name
        self.has_iso_xml = has_iso_xml
        self._build_ui()
        self._populate_layers()

    # ──────────────────────────────────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle('RTH Monitor Export — {}'.format(self.monitor_name))
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint |
            Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint
        )
        self.setMinimumWidth(450)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── Cabeçalho / Header ────────────────────────────────────────────────
        lbl_title = QLabel('Exportar para Monitor Agrícola / Export to Agricultural Monitor')
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold;')
        layout.addWidget(lbl_title)

        lbl_sub = QLabel(self.monitor_name)
        lbl_sub.setAlignment(Qt.AlignCenter)
        lbl_sub.setStyleSheet('color:#666; font-size:10px;')
        layout.addWidget(lbl_sub)

        self._sep(layout)

        # ── Seletor de camadas / Layer selectors ─────────────────────────────
        lbl_layer = QLabel('Camada de Linhas / Lines Layer')
        lbl_layer.setStyleSheet('font-weight:bold;')
        layout.addWidget(lbl_layer)

        self.combo_layer = QComboBox()
        layout.addWidget(self.combo_layer)

        lbl_curves = QLabel('Camada de Curvas / Curves Layer  (opcional / optional)')
        lbl_curves.setStyleSheet('font-weight:bold;')
        layout.addWidget(lbl_curves)

        self.combo_curves = QComboBox()
        layout.addWidget(self.combo_curves)

        self._sep(layout)

        # ── Formato de exportação / Export format ─────────────────────────────
        # Block with radio buttons — visible only when has_iso_xml=True (John Deere)
        self.widget_format = QWidget()
        fmt_layout = QVBoxLayout(self.widget_format)
        fmt_layout.setContentsMargins(0, 0, 0, 0)
        fmt_layout.setSpacing(4)

        lbl_fmt = QLabel('Formato de Exportação / Export Format')
        lbl_fmt.setStyleSheet('font-weight:bold;')
        fmt_layout.addWidget(lbl_fmt)

        fmt_row = QHBoxLayout()
        self.radio_shp = QRadioButton('Shapefile ZIP (.zip)')
        self.radio_shp.setChecked(True)
        self.radio_iso = QRadioButton('ISO-XML  (ISOBUS ISO 11783-10)')
        self._fmt_group = QButtonGroup()
        self._fmt_group.addButton(self.radio_shp)
        self._fmt_group.addButton(self.radio_iso)
        fmt_row.addWidget(self.radio_shp)
        fmt_row.addWidget(self.radio_iso)
        fmt_row.addStretch()
        fmt_layout.addLayout(fmt_row)

        sep_inner = QFrame()
        sep_inner.setFrameShape(QFrame.HLine)
        sep_inner.setFrameShadow(QFrame.Sunken)
        fmt_layout.addWidget(sep_inner)

        layout.addWidget(self.widget_format)
        self.widget_format.setVisible(self.has_iso_xml)

        # Fixed format label for monitors without ISO-XML
        if not self.has_iso_xml:
            lbl_fixed = QLabel('Formato / Format:   Shapefile ZIP (.zip)')
            lbl_fixed.setStyleSheet('font-weight:bold;')
            layout.addWidget(lbl_fixed)
            self._sep(layout)

        # ── Pasta de saída / Output folder ───────────────────────────────────
        lbl_out = QLabel('Pasta de Saída / Output Folder')
        lbl_out.setStyleSheet('font-weight:bold;')
        layout.addWidget(lbl_out)

        dir_row = QHBoxLayout()
        self.edit_dir = QLineEdit()
        self.edit_dir.setPlaceholderText('Pasta de saída / Output folder...')
        dir_row.addWidget(self.edit_dir)

        self.btn_browse = QPushButton('...')
        self.btn_browse.setFixedWidth(32)
        self.btn_browse.clicked.connect(self._on_browse)
        dir_row.addWidget(self.btn_browse)
        layout.addLayout(dir_row)

        self._sep(layout)

        # ── Status ────────────────────────────────────────────────────────────
        self.lbl_status = QLabel('')
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet('font-size:10px; color:#444;')
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        # ── Botão Run / Run button ────────────────────────────────────────────
        self.btn_run = QPushButton('▶  Exportar / Export')
        self.btn_run.setMinimumHeight(40)
        self.btn_run.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;font-size:13px;border-radius:5px;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        self.btn_run.clicked.connect(self._on_run)
        layout.addWidget(self.btn_run)

    def _sep(self, layout):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

    # ──────────────────────────────────────────────────────────────────────────
    # Lógica / Logic
    # ──────────────────────────────────────────────────────────────────────────

    def _populate_layers(self):
        self.combo_layer.clear()
        self.combo_curves.clear()
        self.combo_curves.addItem('— nenhuma / none —', None)
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                self.combo_layer.addItem(layer.name(), layer.id())
                self.combo_curves.addItem(layer.name(), layer.id())

    def _current_layer(self):
        if self.combo_layer.count() == 0:
            return None
        return QgsProject.instance().mapLayer(self.combo_layer.currentData())

    def _current_curves_layer(self):
        lid = self.combo_curves.currentData()
        if not lid:
            return None
        return QgsProject.instance().mapLayer(lid)

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            'Selecione a pasta de saída / Select output folder',
            self.edit_dir.text() or os.path.expanduser('~')
        )
        if folder:
            self.edit_dir.setText(folder)

    def _on_run(self):
        layer = self._current_layer()
        if layer is None:
            self.iface.messageBar().pushMessage(
                'RTH Monitor Export',
                'Selecione uma camada vetorial / Select a vector layer',
                level=Qgis.MessageLevel.Warning, duration=4)
            return

        out_dir = self.edit_dir.text().strip()
        if not out_dir:
            self.iface.messageBar().pushMessage(
                'RTH Monitor Export',
                'Selecione uma pasta de saída / Select an output folder',
                level=Qgis.MessageLevel.Warning, duration=4)
            return

        os.makedirs(out_dir, exist_ok=True)
        self.btn_run.setEnabled(False)
        self.lbl_status.setText('Exportando... / Exporting...')

        export_layer   = None
        _layer_is_temp = False
        try:
            curves_layer = self._current_curves_layer()
            if curves_layer is not None and curves_layer.id() != layer.id():
                self.lbl_status.setText('Mesclando camadas... / Merging layers...')
                export_layer   = _merge_layers(layer, curves_layer)
                _layer_is_temp = True
            else:
                export_layer = layer

            use_iso = self.has_iso_xml and self.radio_iso.isChecked()
            if use_iso:
                out_path = self._export_iso_xml(export_layer, out_dir)
            else:
                out_path = self._export_shp_zip(export_layer, out_dir)

            fname = os.path.basename(out_path)
            self.lbl_status.setText('Exportado / Exported: {}'.format(fname))
            self.iface.messageBar().pushMessage(
                'RTH Monitor Export',
                'Arquivo gerado / File created: {}'.format(out_path),
                level=Qgis.MessageLevel.Success, duration=6)
        except Exception as exc:
            self.lbl_status.setText('Erro / Error: {}'.format(str(exc)))
            self.iface.messageBar().pushMessage(
                'RTH Monitor Export', str(exc),
                level=Qgis.MessageLevel.Critical, duration=6)
        finally:
            # Libera o layer de memória temporário para não deixar referência C++
            # pendente no QGIS — apenas quando foi criado pelo merge, não quando
            # é o próprio layer original do projeto.
            # Release temp memory layer so the C++ object is freed promptly;
            # only when it was created by the merge, not the original project layer.
            if _layer_is_temp and export_layer is not None:
                del export_layer
                export_layer = None
            self.btn_run.setEnabled(True)

    # ──────────────────────────────────────────────────────────────────────────
    # Exportação Shapefile ZIP / Shapefile ZIP export
    # ──────────────────────────────────────────────────────────────────────────

    def _export_shp_zip(self, layer, out_dir):
        safe = _safe_name(layer.name())
        tmp_dir = tempfile.mkdtemp()
        try:
            shp_path = os.path.join(tmp_dir, safe + '.shp')

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = 'ESRI Shapefile'
            options.fileEncoding = 'UTF-8'

            transform_ctx = QgsProject.instance().transformContext()
            error, *rest = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, shp_path, transform_ctx, options)
            msg = rest[-1] if rest else ''

            if error != QgsVectorFileWriter.NoError:
                raise RuntimeError('Shapefile error: {}'.format(msg))

            zip_path = os.path.join(out_dir, safe + '.zip')
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for fname in os.listdir(tmp_dir):
                    fpath = os.path.join(tmp_dir, fname)
                    if os.path.isfile(fpath):
                        zf.write(fpath, fname)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return zip_path

    # ──────────────────────────────────────────────────────────────────────────
    # Exportação ISO-XML / ISO-XML export  (ISOBUS ISO 11783-10)
    # ──────────────────────────────────────────────────────────────────────────

    def _export_iso_xml(self, layer, out_dir):
        safe = _safe_name(layer.name())
        fields = layer.fields()

        src_crs = layer.crs()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        transform = None
        if src_crs.authid() != 'EPSG:4326':
            transform = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())

        root = ET.Element('ISO11783_TaskData')
        root.set('VersionMajor', '4')
        root.set('VersionMinor', '0')
        root.set('ManagementSoftwareManufacturer', 'RTH PROJECT')
        root.set('ManagementSoftwareVersion', '1.0')
        root.set('DataTransferOrigin', '1')

        tsk = ET.SubElement(root, 'TSK')
        tsk.set('A', 'TSK1')
        tsk.set('B', layer.name()[:64])
        tsk.set('G', '1')

        for feat_idx, feat in enumerate(layer.getFeatures()):
            geom = feat.geometry()
            if geom and not geom.isNull() and transform:
                geom.transform(transform)

            tzn = ET.SubElement(tsk, 'TZN')
            tzn.set('A', 'TSK1-TZN{}'.format(feat_idx + 1))
            tzn.set('B', str(feat_idx))

            for field in fields:
                val = feat.attribute(field.name())
                if val is not None:
                    pdt = ET.SubElement(tzn, 'PDV')
                    pdt.set('A', field.name()[:32])
                    pdt.set('B', str(val))

            if geom and not geom.isNull():
                pln = ET.SubElement(tzn, 'PLN')
                pln.set('A', '1')
                pln.set('B', '0')

                lsg = ET.SubElement(pln, 'LSG')
                lsg.set('A', '1')

                if geom.isMultipart():
                    polys = geom.asMultiPolygon()
                    rings = polys[0] if polys else []
                else:
                    poly = geom.asPolygon()
                    rings = poly if poly else []

                if rings:
                    for pt in rings[0]:
                        pnt = ET.SubElement(lsg, 'PNT')
                        pnt.set('A', '2')
                        pnt.set('C', '{:.8f}'.format(pt.y()))
                        pnt.set('D', '{:.8f}'.format(pt.x()))

        xml_str = _pretty_xml(root)

        zip_path = os.path.join(out_dir, safe + '_ISOXML.zip')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('TASKDATA/TASKDATA.XML', xml_str)

        return zip_path


# ──────────────────────────────────────────────────────────────────────────────
# Helpers / Tool class
# ──────────────────────────────────────────────────────────────────────────────

def _safe_name(name):
    return re.sub(r'[^\w]', '_', name)


def _merge_layers(layer_a, layer_b):
    """Combina features de dois layers vetoriais em um layer de memória temporário.
    Merge features from two vector layers into a temporary memory layer.
    Campos do layer_a têm prioridade; campos extras do layer_b são adicionados.
    Fields from layer_a take priority; extra fields from layer_b are appended.
    """
    fields_a = layer_a.fields()
    fields_b = layer_b.fields()

    # União dos campos / Union of fields
    merged_fields = QgsFields()
    field_names = set()
    for f in fields_a:
        merged_fields.append(f)
        field_names.add(f.name())
    for f in fields_b:
        if f.name() not in field_names:
            merged_fields.append(f)

    # Usa o tipo geométrico e CRS do primeiro layer / Use geometry type and CRS from first layer
    geom_type = QgsWkbTypes.displayString(layer_a.wkbType())
    crs_str   = layer_a.crs().authid()
    uri       = '{}?crs={}'.format(geom_type, crs_str)
    tmp       = QgsVectorLayer(uri, 'merged', 'memory')
    dp        = tmp.dataProvider()
    dp.addAttributes(merged_fields.toList())
    tmp.updateFields()

    def _copy_features(src_layer):
        src_crs = src_layer.crs()
        needs_transform = src_crs != layer_a.crs()
        transform = (QgsCoordinateTransform(src_crs, layer_a.crs(), QgsProject.instance())
                     if needs_transform else None)
        src_field_names = [f.name() for f in src_layer.fields()]
        chunk = []
        for src_feat in src_layer.getFeatures():
            new_feat = QgsFeature(merged_fields)
            geom = src_feat.geometry()
            if geom and not geom.isNull() and transform:
                geom.transform(transform)
            if geom and not geom.isNull():
                new_feat.setGeometry(geom)
            for fname in src_field_names:
                idx = merged_fields.indexOf(fname)
                if idx >= 0:
                    new_feat.setAttribute(idx, src_feat[fname])
            chunk.append(new_feat)
            if len(chunk) >= 200:   # flush em lotes — evita lista gigante na memória
                dp.addFeatures(chunk)
                chunk.clear()
        if chunk:
            dp.addFeatures(chunk)

    _copy_features(layer_a)
    _copy_features(layer_b)
    tmp.updateExtents()
    return tmp


class MonitorExportTool:

    def __init__(self, iface):
        self.iface = iface
        self._dialogs = {}

    def open(self, monitor_name):
        cfg = MONITORS[monitor_name]
        dlg = self._dialogs.get(monitor_name)
        if dlg is None or not dlg.isVisible():
            dlg = MonitorExportDialog(
                self.iface, monitor_name, cfg['has_iso_xml'],
                parent=self.iface.mainWindow()
            )
            self._dialogs[monitor_name] = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
