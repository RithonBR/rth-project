# -*- coding: utf-8 -*-
"""
tool_flight_export.py

Exportador de Planos de Voo para Drones / Drone Flight Plan Exporter

Exporta camadas de planejamento de voo (linhas, waypoints, cobertura)
para formatos compatíveis com os principais drones e softwares GCS.

Exports flight planning layers (lines, waypoints, coverage) to formats
compatible with major drones and GCS software.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

import os
import csv
import zipfile

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QComboBox, QDoubleSpinBox, QPushButton, QLineEdit,
    QFrame, QFileDialog, QMessageBox, QScrollArea, QWidget,
    QApplication,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsVectorFileWriter,
)


# ─── Export presets ───────────────────────────────────────────────────────────
# (display_name, format_key, file_extension, description_pt, description_en)

EXPORT_PRESETS = [
    (
        'DJI Terra  —  KMZ',
        'kmz', '.kmz',
        'Importe no DJI Terra para missões automáticas de mapeamento.\n'
        'Compatível também com Google Earth Pro.',
        'Import into DJI Terra for automated mapping missions.\n'
        'Also compatible with Google Earth Pro.',
    ),
    (
        'DJI Litchi  —  CSV Waypoints',
        'litchi_csv', '.csv',
        'Aplicativo Litchi para drones DJI (Phantom, Mavic, Mini…).\n'
        'Waypoints com disparo automático de câmera (nadir).',
        'Litchi app for DJI drones (Phantom, Mavic, Mini…).\n'
        'Waypoints with automatic camera trigger (nadir).',
    ),
    (
        'Mission Planner / ArduPilot  —  Waypoints',
        'mission_planner', '.waypoints',
        'Mission Planner, APM Planner 2 e QGroundControl.\n'
        'Para drones com firmware ArduPilot ou PX4.',
        'Mission Planner, APM Planner 2 and QGroundControl.\n'
        'For drones running ArduPilot or PX4 firmware.',
    ),
    (
        'Parrot / Autel / Generico  —  KML',
        'kml', '.kml',
        'Parrot Pix4Dreact, Autel Explorer, Google Earth e qualquer\n'
        'app compatível com KML. Sem extensão proprietária.',
        'Parrot Pix4Dreact, Autel Explorer, Google Earth and any\n'
        'KML-compatible app. No proprietary extension.',
    ),
    (
        'Generico  —  Shapefile (.shp)',
        'shapefile', '.shp',
        'Formato GIS universal. Gera arquivos separados por camada\n'
        '(.shp + .dbf + .prj). Coordenadas em WGS-84.',
        'Universal GIS format. Generates separate files per layer\n'
        '(.shp + .dbf + .prj). Coordinates in WGS-84.',
    ),
    (
        'Generico  —  GeoPackage (.gpkg)',
        'gpkg', '.gpkg',
        'Formato GIS moderno em arquivo único (OGC standard).\n'
        'Todas as camadas em um só .gpkg. Coordenadas em WGS-84.',
        'Modern GIS format in a single file (OGC standard).\n'
        'All layers in one .gpkg. Coordinates in WGS-84.',
    ),
    (
        'Generico  —  CSV (lat, lon, alt)',
        'csv', '.csv',
        'Planilha genérica de waypoints para qualquer software.\n'
        'Colunas: id, latitude, longitude, altitude_m, tipo.',
        'Generic waypoint spreadsheet for any software.\n'
        'Columns: id, latitude, longitude, altitude_m, type.',
    ),
]


# ─── Dialog ───────────────────────────────────────────────────────────────────

class FlightExportDialog(QDialog):

    _STYLE_EXPORT = """
        QPushButton {
            background-color: #1565C0; color: white; border: none;
            padding: 10px 20px; border-radius: 5px; font-weight: bold; font-size: 12px;
        }
        QPushButton:hover   { background-color: #0D47A1; }
        QPushButton:pressed { background-color: #0A2F6B; }
        QPushButton:disabled{ background-color: #5a7fa8; color: #aaa; }
    """
    _STYLE_CANCEL = """
        QPushButton {
            background-color: #616161; color: white; border: none;
            padding: 10px 20px; border-radius: 5px; font-size: 11px;
        }
        QPushButton:hover   { background-color: #424242; }
        QPushButton:pressed { background-color: #212121; }
    """

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._build_ui()
        self._populate_layers()
        self._on_preset_changed(0)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle('RTH — Exportar Plano de Voo / Export Flight Plan')
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(500)
        self.setMinimumHeight(700)
        self.setMaximumHeight(780)

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
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # Title
        lbl_title = QLabel('✈  Exportar Plano de Voo / Export Flight Plan')
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold;')
        root.addWidget(lbl_title)

        lbl_sub = QLabel(
            'Exporta as camadas de voo para formatos compatíveis com drones e GCS.\n'
            'Exports flight layers to drone and GCS compatible formats.')
        lbl_sub.setAlignment(Qt.AlignCenter)
        lbl_sub.setStyleSheet('font-size:9px; color:#888;')
        root.addWidget(lbl_sub)
        root.addWidget(self._sep())

        # ── Input layers ──────────────────────────────────────────────────────
        grp_layers = QGroupBox('Camadas de Entrada / Input Layers')
        lay_l = QGridLayout()
        lay_l.setContentsMargins(8, 6, 8, 8)
        lay_l.setSpacing(5)
        lay_l.setColumnStretch(1, 1)

        lay_l.addWidget(QLabel('Linhas de Voo / Flight Lines:'), 0, 0)
        self.combo_lines = QComboBox()
        lay_l.addWidget(self.combo_lines, 0, 1)

        lay_l.addWidget(QLabel('Waypoints / Photo points:'), 1, 0)
        self.combo_waypoints = QComboBox()
        lay_l.addWidget(self.combo_waypoints, 1, 1)

        lay_l.addWidget(QLabel('Cobertura / Coverage (opt.):'), 2, 0)
        self.combo_coverage = QComboBox()
        lay_l.addWidget(self.combo_coverage, 2, 1)

        lbl_layer_hint = QLabel(
            '  Selecione ao menos Linhas de Voo ou Waypoints.\n'
            '  Select at least Flight Lines or Waypoints.')
        lbl_layer_hint.setStyleSheet('font-size:9px; color:#aaa;')
        lay_l.addWidget(lbl_layer_hint, 3, 0, 1, 2)

        grp_layers.setLayout(lay_l)
        root.addWidget(grp_layers)

        # ── Drone / software preset ───────────────────────────────────────────
        grp_fmt = QGroupBox('Drone / Software GCS')
        lay_fmt = QVBoxLayout()
        lay_fmt.setContentsMargins(8, 6, 8, 8)
        lay_fmt.setSpacing(6)

        self.combo_preset = QComboBox()
        for name, key, ext, desc_pt, desc_en in EXPORT_PRESETS:
            self.combo_preset.addItem(name, (key, ext))
        lay_fmt.addWidget(self.combo_preset)

        self.lbl_preset_desc = QLabel()
        self.lbl_preset_desc.setStyleSheet('font-size:9px; color:#888;')
        self.lbl_preset_desc.setWordWrap(True)
        lay_fmt.addWidget(self.lbl_preset_desc)

        grp_fmt.setLayout(lay_fmt)
        root.addWidget(grp_fmt)

        # ── Options ───────────────────────────────────────────────────────────
        grp_opt = QGroupBox('Opções / Options')
        lay_opt = QGridLayout()
        lay_opt.setContentsMargins(8, 6, 8, 8)
        lay_opt.setSpacing(5)
        lay_opt.setColumnStretch(1, 1)

        lay_opt.addWidget(QLabel('Altitude padrão / Default altitude:'), 0, 0)
        self.spin_alt = QDoubleSpinBox()
        self.spin_alt.setRange(1.0, 500.0)
        self.spin_alt.setValue(50.0)
        self.spin_alt.setSuffix(' m')
        self.spin_alt.setDecimals(1)
        self.spin_alt.setSingleStep(5.0)
        self.spin_alt.setMinimumHeight(28)
        lay_opt.addWidget(self.spin_alt, 0, 1)

        lbl_alt_hint = QLabel(
            '  Usada quando a camada não tem campo "altitude_m".\n'
            '  Used when the layer has no "altitude_m" field.')
        lbl_alt_hint.setStyleSheet('font-size:9px; color:#aaa;')
        lay_opt.addWidget(lbl_alt_hint, 1, 0, 1, 2)

        grp_opt.setLayout(lay_opt)
        root.addWidget(grp_opt)

        # ── Output path ───────────────────────────────────────────────────────
        grp_out = QGroupBox('Arquivo de Saída / Output File')
        lay_out = QVBoxLayout()
        lay_out.setContentsMargins(8, 6, 8, 8)
        lay_out.setSpacing(5)

        row_path = QHBoxLayout()
        self.edit_path = QLineEdit()
        self.edit_path.setPlaceholderText('Selecione o arquivo de saída / Select output file...')
        self.edit_path.setMinimumHeight(28)
        row_path.addWidget(self.edit_path)

        self.btn_browse = QPushButton('Salvar... / Save...')
        self.btn_browse.setMinimumHeight(28)
        self.btn_browse.clicked.connect(self._on_browse)
        row_path.addWidget(self.btn_browse)
        lay_out.addLayout(row_path)

        grp_out.setLayout(lay_out)
        root.addWidget(grp_out)

        root.addWidget(self._sep())

        # ── Action buttons ────────────────────────────────────────────────────
        row_btns = QHBoxLayout()

        self.btn_export = QPushButton('✈  Exportar / Export')
        self.btn_export.setStyleSheet(self._STYLE_EXPORT)
        self.btn_export.setMinimumHeight(38)
        self.btn_export.clicked.connect(self._on_export)

        btn_close = QPushButton('Fechar / Close')
        btn_close.setStyleSheet(self._STYLE_CANCEL)
        btn_close.setMinimumHeight(38)
        btn_close.clicked.connect(self.close)

        row_btns.addWidget(self.btn_export)
        row_btns.addWidget(btn_close)
        root.addLayout(row_btns)

        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)

    def _sep(self):
        ln = QFrame()
        ln.setFrameShape(QFrame.HLine)
        ln.setFrameShadow(QFrame.Sunken)
        return ln

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_preset_changed(self, idx=None):
        if idx is None:
            idx = self.combo_preset.currentIndex()
        if 0 <= idx < len(EXPORT_PRESETS):
            _, _, _, desc_pt, desc_en = EXPORT_PRESETS[idx]
            self.lbl_preset_desc.setText(desc_pt + '\n' + desc_en)
        # Update extension in the path field if already set
        path = self.edit_path.text().strip()
        if path and self.combo_preset.currentData():
            _, ext = self.combo_preset.currentData()
            base = os.path.splitext(path)[0]
            self.edit_path.setText(base + ext)

    def _on_browse(self):
        data = self.combo_preset.currentData()
        ext = data[1] if data else '.kml'
        filters = {
            '.kmz':       'KMZ Files (*.kmz)',
            '.kml':       'KML Files (*.kml)',
            '.csv':       'CSV Files (*.csv)',
            '.waypoints': 'Waypoint Files (*.waypoints)',
            '.shp':       'Shapefiles (*.shp)',
            '.gpkg':      'GeoPackage (*.gpkg)',
        }
        path, _ = QFileDialog.getSaveFileName(
            self, 'Salvar Plano de Voo / Save Flight Plan',
            '', filters.get(ext, 'All Files (*)'))
        if path:
            if not path.endswith(ext):
                path += ext
            self.edit_path.setText(path)

    def _populate_layers(self):
        for combo in (self.combo_lines, self.combo_waypoints, self.combo_coverage):
            combo.clear()
            combo.addItem('Nenhum / None', None)

        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            gt = QgsWkbTypes.geometryType(layer.wkbType())
            if gt == QgsWkbTypes.LineGeometry:
                self.combo_lines.addItem(layer.name(), layer.id())
            elif gt == QgsWkbTypes.PointGeometry:
                self.combo_waypoints.addItem(layer.name(), layer.id())
            elif gt == QgsWkbTypes.PolygonGeometry:
                self.combo_coverage.addItem(layer.name(), layer.id())

    def _get_layer(self, combo):
        lid = combo.currentData()
        return QgsProject.instance().mapLayer(lid) if lid else None

    def _on_export(self):
        lines_lyr    = self._get_layer(self.combo_lines)
        wp_lyr       = self._get_layer(self.combo_waypoints)
        coverage_lyr = self._get_layer(self.combo_coverage)

        if lines_lyr is None and wp_lyr is None:
            QMessageBox.warning(self, 'RTH',
                'Selecione ao menos uma camada (Linhas ou Waypoints).\n'
                'Select at least one layer (Lines or Waypoints).')
            return

        path = self.edit_path.text().strip()
        if not path:
            QMessageBox.warning(self, 'RTH',
                'Selecione o arquivo de saída.\nSelect the output file.')
            return

        fmt_key, ext = self.combo_preset.currentData()
        if not path.endswith(ext):
            path += ext

        default_alt = self.spin_alt.value()

        self.btn_export.setEnabled(False)
        self.btn_export.setText('Exportando... / Exporting...')
        QApplication.processEvents()

        try:
            if fmt_key == 'kmz':
                self._export_kml_kmz(path, lines_lyr, wp_lyr, coverage_lyr, default_alt, kmz=True)
            elif fmt_key == 'kml':
                self._export_kml_kmz(path, lines_lyr, wp_lyr, coverage_lyr, default_alt, kmz=False)
            elif fmt_key == 'litchi_csv':
                self._export_litchi_csv(path, lines_lyr, wp_lyr, default_alt)
            elif fmt_key == 'mission_planner':
                self._export_mission_planner(path, wp_lyr or lines_lyr, default_alt)
            elif fmt_key == 'shapefile':
                self._export_vector(path, lines_lyr, wp_lyr, coverage_lyr, 'ESRI Shapefile')
            elif fmt_key == 'gpkg':
                self._export_vector(path, lines_lyr, wp_lyr, coverage_lyr, 'GPKG')
            elif fmt_key == 'csv':
                self._export_generic_csv(path, wp_lyr or lines_lyr, default_alt)

            self.iface.messageBar().pushMessage(
                'RTH Exportar Voo',
                'Exportado: {}'.format(os.path.basename(path)),
                level=Qgis.MessageLevel.Success, duration=6)
            QMessageBox.information(
                self, 'RTH — Exportar Voo',
                '✔  Exportado com sucesso!\n'
                '✔  Exported successfully!\n\n'
                '{}'.format(path))

        except Exception as e:
            self.iface.messageBar().pushMessage(
                'RTH Exportar Voo', str(e),
                level=Qgis.MessageLevel.Critical, duration=8)
            QMessageBox.critical(self, 'RTH — Erro / Error', str(e))
        finally:
            self.btn_export.setEnabled(True)
            self.btn_export.setText('✈  Exportar / Export')

    # ── CRS helpers ───────────────────────────────────────────────────────────

    _WGS84 = QgsCoordinateReferenceSystem('EPSG:4326')

    def _xform(self, src_crs):
        if src_crs.authid() == 'EPSG:4326':
            return None
        return QgsCoordinateTransform(src_crs, self._WGS84, QgsProject.instance())

    def _to_lonlat(self, pt, xf):
        if xf is None:
            return pt.x(), pt.y()
        tp = xf.transform(pt)
        return tp.x(), tp.y()

    def _feat_alt(self, feat, default_alt):
        """Read altitude_m field from feature, fallback to default_alt."""
        idx = feat.fields().indexFromName('altitude_m')
        if idx >= 0:
            v = feat.attribute(idx)
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
        return default_alt

    def _polyline_pts(self, geom):
        """Return flat list of QgsPointXY from LineString or MultiLineString."""
        if geom.isMultipart():
            return [pt for part in geom.asMultiPolyline() for pt in part]
        return list(geom.asPolyline())

    # ── KML / KMZ ─────────────────────────────────────────────────────────────

    def _export_kml_kmz(self, path, lines_lyr, wp_lyr, coverage_lyr, default_alt, kmz):
        kml = self._build_kml(lines_lyr, wp_lyr, coverage_lyr, default_alt)
        if kmz:
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('doc.kml', kml.encode('utf-8'))
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(kml)

    def _build_kml(self, lines_lyr, wp_lyr, coverage_lyr, default_alt):
        out = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<kml xmlns="http://www.opengis.net/kml/2.2">',
            '<Document>',
            '<name>RTH Flight Plan</name>',
            '<description>Generated by RTH PROJECT — Precision Agriculture Tools</description>',
            '',
            # Styles
            '<Style id="sLine">',
            '  <LineStyle><color>ffff0000</color><width>2</width></LineStyle>',
            '</Style>',
            '<Style id="sWP">',
            '  <IconStyle><color>ff00ffff</color><scale>0.8</scale>',
            '    <Icon><href>http://maps.google.com/mapfiles/kml/paddle/ylw-circle.png</href></Icon>',
            '  </IconStyle>',
            '</Style>',
            '<Style id="sCoverage">',
            '  <LineStyle><color>ff00cc00</color><width>1</width></LineStyle>',
            '  <PolyStyle><color>3300cc00</color></PolyStyle>',
            '</Style>',
            '',
        ]

        # Flight lines
        if lines_lyr is not None:
            xf = self._xform(lines_lyr.crs())
            feats = [f for f in lines_lyr.getFeatures()
                     if f.geometry() and not f.geometry().isNull()]
            if feats:
                out.append('<Folder><name>Linhas de Voo / Flight Lines</name>')
                for i, feat in enumerate(feats, 1):
                    alt = self._feat_alt(feat, default_alt)
                    pts = self._polyline_pts(feat.geometry())
                    coords = ' '.join(
                        '{:.8f},{:.8f},{:.1f}'.format(*self._to_lonlat(p, xf), alt)
                        for p in pts)
                    if coords:
                        out += [
                            '<Placemark>',
                            '<name>Linha {} / Line {}</name>'.format(i, i),
                            '<styleUrl>#sLine</styleUrl>',
                            '<LineString>',
                            '<altitudeMode>relativeToGround</altitudeMode>',
                            '<coordinates>{}</coordinates>'.format(coords),
                            '</LineString>',
                            '</Placemark>',
                        ]
                out.append('</Folder>')

        # Waypoints
        if wp_lyr is not None:
            xf = self._xform(wp_lyr.crs())
            feats = [f for f in wp_lyr.getFeatures()
                     if f.geometry() and not f.geometry().isNull()]
            if feats:
                out.append('<Folder><name>Waypoints / Photo Points</name>')
                for i, feat in enumerate(feats, 1):
                    pt = feat.geometry().asPoint()
                    lon, lat = self._to_lonlat(pt, xf)
                    alt = self._feat_alt(feat, default_alt)
                    out += [
                        '<Placemark>',
                        '<name>WP{:04d}</name>'.format(i),
                        '<styleUrl>#sWP</styleUrl>',
                        '<description>Waypoint {} — {}m</description>'.format(i, alt),
                        '<Point>',
                        '<altitudeMode>relativeToGround</altitudeMode>',
                        '<coordinates>{:.8f},{:.8f},{:.1f}</coordinates>'.format(lon, lat, alt),
                        '</Point>',
                        '</Placemark>',
                    ]
                out.append('</Folder>')

        # Coverage polygon
        if coverage_lyr is not None:
            xf = self._xform(coverage_lyr.crs())
            feats = [f for f in coverage_lyr.getFeatures()
                     if f.geometry() and not f.geometry().isNull()]
            if feats:
                out.append('<Folder><name>Cobertura / Coverage</name>')
                for i, feat in enumerate(feats, 1):
                    geom = feat.geometry()
                    ring = self._outer_ring(geom)
                    coords = ' '.join(
                        '{:.8f},{:.8f},0'.format(*self._to_lonlat(p, xf))
                        for p in ring)
                    if coords:
                        out += [
                            '<Placemark>',
                            '<name>Cobertura {} / Coverage {}</name>'.format(i, i),
                            '<styleUrl>#sCoverage</styleUrl>',
                            '<Polygon>',
                            '<outerBoundaryIs><LinearRing>',
                            '<coordinates>{}</coordinates>'.format(coords),
                            '</LinearRing></outerBoundaryIs>',
                            '</Polygon>',
                            '</Placemark>',
                        ]
                out.append('</Folder>')

        out += ['</Document>', '</kml>']
        return '\n'.join(out)

    def _outer_ring(self, geom):
        if geom.isMultipart():
            polys = geom.asMultiPolygon()
            return polys[0][0] if polys and polys[0] else []
        poly = geom.asPolygon()
        return poly[0] if poly else []

    # ── Litchi CSV ────────────────────────────────────────────────────────────

    def _export_litchi_csv(self, path, lines_lyr, wp_lyr, default_alt):
        """
        Litchi waypoint CSV format.
        Uses waypoints layer if available; otherwise derives points from line endpoints.
        Camera trigger action (actiontype1=1) and nadir gimbal (-90°) are set automatically.
        """
        fieldnames = [
            'latitude', 'longitude', 'altitude(m)', 'heading(deg)',
            'curvesize(m)', 'rotationdir', 'gimbalmode', 'gimbalpitchangle',
            'actiontype1', 'actionparam1',
            'actiontype2', 'actionparam2',
        ]
        rows = []

        src_lyr = wp_lyr if wp_lyr is not None else lines_lyr
        if src_lyr is None:
            raise RuntimeError('Nenhuma camada válida para Litchi CSV / No valid layer for Litchi CSV')

        xf = self._xform(src_lyr.crs())
        gt = QgsWkbTypes.geometryType(src_lyr.wkbType())

        for feat in src_lyr.getFeatures():
            if not feat.geometry() or feat.geometry().isNull():
                continue
            alt = self._feat_alt(feat, default_alt)

            if gt == QgsWkbTypes.PointGeometry:
                pt = feat.geometry().asPoint()
                lon, lat = self._to_lonlat(pt, xf)
                rows.append(self._litchi_row(lat, lon, alt))
            else:
                for pt in self._polyline_pts(feat.geometry()):
                    lon, lat = self._to_lonlat(pt, xf)
                    rows.append(self._litchi_row(lat, lon, alt))

        if not rows:
            raise RuntimeError('Nenhuma feição exportável / No exportable features')

        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _litchi_row(self, lat, lon, alt):
        return {
            'latitude':          '{:.8f}'.format(lat),
            'longitude':         '{:.8f}'.format(lon),
            'altitude(m)':       '{:.1f}'.format(alt),
            'heading(deg)':      '-1',       # -1 = auto heading
            'curvesize(m)':      '0.0',
            'rotationdir':       '0',
            'gimbalmode':        '0',
            'gimbalpitchangle':  '-90',      # nadir (straight down)
            'actiontype1':       '1',        # 1 = take photo
            'actionparam1':      '-1',
            'actiontype2':       '-1',
            'actionparam2':      '-1',
        }

    # ── Mission Planner waypoints ─────────────────────────────────────────────

    def _export_mission_planner(self, path, layer, default_alt):
        """
        QGC WPL 110 format accepted by Mission Planner, APM Planner, QGroundControl.
        frame 3 = MAV_FRAME_GLOBAL_RELATIVE_ALT, cmd 16 = MAV_CMD_NAV_WAYPOINT.
        """
        if layer is None:
            raise RuntimeError('Nenhuma camada selecionada / No layer selected')

        xf = self._xform(layer.crs())
        gt = QgsWkbTypes.geometryType(layer.wkbType())
        wps = []

        for feat in layer.getFeatures():
            if not feat.geometry() or feat.geometry().isNull():
                continue
            alt = self._feat_alt(feat, default_alt)
            if gt == QgsWkbTypes.PointGeometry:
                pt = feat.geometry().asPoint()
                lon, lat = self._to_lonlat(pt, xf)
                wps.append((lat, lon, alt))
            else:
                for pt in self._polyline_pts(feat.geometry()):
                    lon, lat = self._to_lonlat(pt, xf)
                    wps.append((lat, lon, alt))

        if not wps:
            raise RuntimeError('Nenhuma feição exportável / No exportable features')

        with open(path, 'w', encoding='utf-8') as f:
            f.write('QGC WPL 110\n')
            # Index 0: home (current=1, altitude=0 = ground)
            f.write('0\t1\t0\t16\t0\t0\t0\t0\t{:.8f}\t{:.8f}\t0.00\t1\n'.format(
                wps[0][0], wps[0][1]))
            # Mission waypoints
            for i, (lat, lon, alt) in enumerate(wps, 1):
                # index, current, frame, cmd, p1-p4, lat, lon, alt, autocontinue
                f.write('{}\t0\t3\t16\t0\t0\t0\t0\t{:.8f}\t{:.8f}\t{:.2f}\t1\n'.format(
                    i, lat, lon, alt))

    # ── Generic CSV ───────────────────────────────────────────────────────────

    def _export_generic_csv(self, path, layer, default_alt):
        if layer is None:
            raise RuntimeError('Nenhuma camada selecionada / No layer selected')

        xf = self._xform(layer.crs())
        gt = QgsWkbTypes.geometryType(layer.wkbType())
        rows = []
        idx = 1

        for feat in layer.getFeatures():
            if not feat.geometry() or feat.geometry().isNull():
                continue
            alt = self._feat_alt(feat, default_alt)
            if gt == QgsWkbTypes.PointGeometry:
                pt = feat.geometry().asPoint()
                lon, lat = self._to_lonlat(pt, xf)
                rows.append({'id': idx, 'latitude': '{:.8f}'.format(lat),
                             'longitude': '{:.8f}'.format(lon),
                             'altitude_m': '{:.1f}'.format(alt), 'type': 'waypoint'})
                idx += 1
            else:
                for pt in self._polyline_pts(feat.geometry()):
                    lon, lat = self._to_lonlat(pt, xf)
                    rows.append({'id': idx, 'latitude': '{:.8f}'.format(lat),
                                 'longitude': '{:.8f}'.format(lon),
                                 'altitude_m': '{:.1f}'.format(alt), 'type': 'vertex'})
                    idx += 1

        if not rows:
            raise RuntimeError('Nenhuma feição exportável / No exportable features')

        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'latitude', 'longitude', 'altitude_m', 'type'])
            writer.writeheader()
            writer.writerows(rows)

    # ── Shapefile / GeoPackage ────────────────────────────────────────────────

    def _export_vector(self, path, lines_lyr, wp_lyr, coverage_lyr, driver):
        """
        Export to Shapefile (one file per layer) or GeoPackage (all layers in one file).
        All layers are reprojected to WGS-84.
        """
        layers = [(l, l.name()) for l in (lines_lyr, wp_lyr, coverage_lyr) if l is not None]
        if not layers:
            raise RuntimeError('Nenhuma camada selecionada / No layer selected')

        base = os.path.splitext(path)[0]
        errors = []

        for layer_idx, (layer, name) in enumerate(layers):
            if driver == 'ESRI Shapefile':
                safe = ''.join(c if c.isalnum() or c == '_' else '_' for c in name)[:20]
                out_path = '{}__{}.shp'.format(base, safe)
            else:
                out_path = path  # All layers go into the same GPKG

            opts = QgsVectorFileWriter.SaveVectorOptions()
            opts.driverName   = driver
            opts.fileEncoding = 'UTF-8'
            opts.ct           = QgsCoordinateTransform(layer.crs(), self._WGS84, QgsProject.instance())
            if driver == 'GPKG' and layer_idx > 0:
                opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
                opts.layerName = name
            try:
                result, *rest = QgsVectorFileWriter.writeAsVectorFormatV3(
                    layer, out_path, QgsProject.instance().transformContext(), opts)
                err = result
                msg = rest[0] if rest else ''
            except AttributeError:
                res = QgsVectorFileWriter.writeAsVectorFormatV2(
                    layer, out_path, QgsProject.instance().transformContext(), opts)
                err = res[0]
                msg = res[1] if len(res) > 1 else ''

            if err not in (QgsVectorFileWriter.NoError, 0):
                errors.append('{}: {}'.format(name, msg))

        if errors:
            raise RuntimeError('Erros na exportação:\n' + '\n'.join(errors))


# ─── Tool class ───────────────────────────────────────────────────────────────

class FlightExportTool:

    def __init__(self, iface):
        self.iface = iface
        self._dlg = None

    def run(self):
        if self._dlg is None or not self._dlg.isVisible():
            self._dlg = FlightExportDialog(self.iface, parent=self.iface.mainWindow())
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
