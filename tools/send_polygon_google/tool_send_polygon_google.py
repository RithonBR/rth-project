# -*- coding: utf-8 -*-
import os
import tempfile
import subprocess

from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry
)


# KML color format: aabbggrr (alpha, blue, green, red)
_OUTLINE_COLOR = 'ff0000ff'   # vermelho sólido / solid red
_OUTLINE_WIDTH = 2

_GE_PATHS = [
    r'C:\Program Files\Google\Google Earth Pro\client\googleearth.exe',
    r'C:\Program Files (x86)\Google\Google Earth Pro\client\googleearth.exe',
]

_KML_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
    '<Document>\n'
    '  <name>{doc_name}</name>\n'
    '  <Style id="outline_only">\n'
    '    <LineStyle>\n'
    '      <color>{color}</color>\n'
    '      <width>{width}</width>\n'
    '    </LineStyle>\n'
    '    <PolyStyle>\n'
    '      <fill>0</fill>\n'
    '      <outline>1</outline>\n'
    '    </PolyStyle>\n'
    '  </Style>\n'
)

_KML_FOOTER = '</Document>\n</kml>'


# ──────────────────────────────────────────────────────────────────────────────
# KML builders
# ──────────────────────────────────────────────────────────────────────────────

def _ring_coords(pts):
    return ' '.join('{:.8f},{:.8f},0'.format(p.x(), p.y()) for p in pts)


def _kml_polygon_elem(rings):
    """Converts a list of rings (list of QgsPointXY) to a KML <Polygon> string."""
    parts = ['<Polygon>']
    outer_coords = _ring_coords(rings[0])
    parts.append(
        '<outerBoundaryIs><LinearRing>'
        '<coordinates>{}</coordinates>'
        '</LinearRing></outerBoundaryIs>'.format(outer_coords))
    for hole in rings[1:]:
        hole_coords = _ring_coords(hole)
        parts.append(
            '<innerBoundaryIs><LinearRing>'
            '<coordinates>{}</coordinates>'
            '</LinearRing></innerBoundaryIs>'.format(hole_coords))
    parts.append('</Polygon>')
    return ''.join(parts)


def _geom_to_kml(geom):
    """
    Converts a QgsGeometry (Polygon or MultiPolygon, already in WGS84)
    to the KML geometry string inside a <Placemark>.
    Returns a single <Polygon> or <MultiGeometry> element.
    """
    if geom.isMultipart():
        polys = geom.asMultiPolygon()
        if not polys:
            return ''
        if len(polys) == 1:
            return _kml_polygon_elem(polys[0])
        parts = ['<MultiGeometry>']
        for poly_rings in polys:
            if poly_rings:
                parts.append(_kml_polygon_elem(poly_rings))
        parts.append('</MultiGeometry>')
        return ''.join(parts)
    else:
        rings = geom.asPolygon()
        if not rings:
            return ''
        return _kml_polygon_elem(rings)


def _build_kml(layer_name, features, layer_crs):
    """Build full KML string for the given features (already selected/filtered)."""
    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    needs_transform = layer_crs.authid() != 'EPSG:4326'
    if needs_transform:
        transform = QgsCoordinateTransform(
            layer_crs, wgs84, QgsProject.instance())

    # Try to find a "name" field in the layer
    field_names = [f.name().lower() for f in features[0].fields()] if features else []
    name_field = next(
        (f for f in ('nome', 'name', 'id', 'fid') if f in field_names), None)

    lines = [_KML_HEADER.format(
        doc_name=layer_name,
        color=_OUTLINE_COLOR,
        width=_OUTLINE_WIDTH)]

    for idx, feat in enumerate(features):
        geom = QgsGeometry(feat.geometry())
        if geom is None or geom.isNull():
            continue
        if needs_transform:
            geom.transform(transform)

        geom_kml = _geom_to_kml(geom)
        if not geom_kml:
            continue

        if name_field:
            feat_name = str(feat.attribute(name_field) or 'Poligono {}'.format(idx + 1))
        else:
            feat_name = 'Poligono {}'.format(idx + 1)

        lines.append(
            '  <Placemark>\n'
            '    <name>{}</name>\n'
            '    <styleUrl>#outline_only</styleUrl>\n'
            '    {}\n'
            '  </Placemark>'.format(feat_name, geom_kml))

    lines.append(_KML_FOOTER)
    return '\n'.join(lines)


def _open_in_google_earth(kml_path):
    """Try to open kml_path in Google Earth Pro. Returns True if launched."""
    for exe in _GE_PATHS:
        if os.path.exists(exe):
            try:
                subprocess.Popen([exe, kml_path], close_fds=True)  # nosec B603
                return True
            except Exception:  # nosec B110
                pass
    # Fallback: sistema abre o arquivo KML com o app padrão / system default app
    try:
        os.startfile(kml_path)  # nosec B606
        return True
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Tool class
# ──────────────────────────────────────────────────────────────────────────────

class SendPolygonToGoogleTool:

    def __init__(self, iface):
        self.iface = iface

    def run(self):
        try:
            self._send()
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                'Google Earth Pro',
                str(exc),
                level=Qgis.MessageLevel.Critical, duration=6)

    def _send(self):
        # ── 1. Camada ativa deve ser vetorial de polígono ─────────────────────
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            self.iface.messageBar().pushMessage(
                'Google Earth Pro',
                'Ative uma camada vetorial de poligono / '
                'Activate a polygon vector layer',
                level=Qgis.MessageLevel.Warning, duration=5)
            return

        if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
            self.iface.messageBar().pushMessage(
                'Google Earth Pro',
                'A camada ativa nao e de poligono / '
                'The active layer is not a polygon layer',
                level=Qgis.MessageLevel.Warning, duration=5)
            return

        # ── 2. Usa feições selecionadas (obrigatório) ─────────────────────────
        selected = layer.selectedFeatures()
        if not selected:
            self.iface.messageBar().pushMessage(
                'Google Earth Pro',
                'Selecione ao menos uma feicao na camada / '
                'Select at least one feature in the layer',
                level=Qgis.MessageLevel.Warning, duration=5)
            return

        # ── 3. Gera KML ───────────────────────────────────────────────────────
        kml = _build_kml(layer.name(), selected, layer.crs())

        tf = tempfile.NamedTemporaryFile(
            delete=False, suffix='.kml',
            prefix='rth_polygon_')
        tf.write(kml.encode('utf-8'))
        tf.close()
        kml_path = tf.name

        # ── 4. Abre no Google Earth Pro ───────────────────────────────────────
        launched = _open_in_google_earth(kml_path)

        n = len(selected)
        if launched:
            self.iface.messageBar().pushMessage(
                'Google Earth Pro',
                '{} poligono(s) enviado(s) (sem preenchimento) / '
                '{} polygon(s) sent (outline only)'.format(n, n),
                level=Qgis.MessageLevel.Success, duration=5)
        else:
            self.iface.messageBar().pushMessage(
                'Google Earth Pro',
                'Google Earth Pro nao encontrado. KML salvo em: {} / '
                'Google Earth Pro not found. KML saved at: {}'.format(
                    kml_path, kml_path),
                level=Qgis.MessageLevel.Warning, duration=8)
