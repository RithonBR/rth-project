# -*- coding: utf-8 -*-
"""
tool_brazil_geobase.py

Brazil Public GeoBase — catálogo dinâmico de serviços geoespaciais públicos
brasileiros (INDE e outros). Conecta diretamente ao provedor via GetCapabilities,
lista todas as camadas disponíveis e permite virtualizar (streaming) ou baixar.

Brazil Public GeoBase — dynamic catalog of Brazilian public geospatial services
(INDE and others). Connects live to each provider via GetCapabilities, lists all
available layers, and allows virtualization (streaming) or download as GeoPackage.
"""

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

# Hosts with broken/self-signed SSL certificates that we explicitly bypass.
# Cert verification is skipped only for these specific domains.
_SSL_NO_VERIFY = frozenset({'idem.dhn.mar.mil.br'})
try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # noqa: S405  # nosec B405  (fallback — defusedxml not installed)

from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QSortFilterProxyModel
from qgis.PyQt.QtGui import QColor, QBrush, QFont, QStandardItemModel, QStandardItem
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton,
    QLabel, QFrame, QApplication, QMessageBox, QTreeWidget,
    QTreeWidgetItem, QLineEdit, QGroupBox, QAbstractItemView,
    QTableView, QHeaderView, QProgressBar, QWidget, QFileDialog,
    QButtonGroup, QRadioButton, QSizePolicy,
)
from qgis.core import (
    Qgis, QgsProject, QgsRasterLayer, QgsVectorLayer,
    QgsVectorFileWriter, QgsCoordinateTransformContext,
    QgsRasterFileWriter, QgsRasterPipe, QgsCoordinateTransform,
)
from core.rth_layer_utils import collapse_layer

# ── PyQt5 / PyQt6 enum compatibility ─────────────────────────────────────────
# QGIS 3.x uses PyQt5 (flat Qt.Foo access).
# QGIS 4.x uses PyQt6 (enums moved to Qt.SomeEnum.Foo).
try:
    _Qt_ItemIsEnabled       = Qt.ItemFlag.ItemIsEnabled
    _Qt_ItemIsUserCheckable = Qt.ItemFlag.ItemIsUserCheckable
except AttributeError:
    _Qt_ItemIsEnabled       = Qt.ItemIsEnabled        # type: ignore[attr-defined]
    _Qt_ItemIsUserCheckable = Qt.ItemIsUserCheckable  # type: ignore[attr-defined]

try:
    _Qt_Checked   = Qt.CheckState.Checked
    _Qt_Unchecked = Qt.CheckState.Unchecked
except AttributeError:
    _Qt_Checked   = Qt.Checked    # type: ignore[attr-defined]
    _Qt_Unchecked = Qt.Unchecked  # type: ignore[attr-defined]

try:
    _Qt_UserRole = Qt.ItemDataRole.UserRole
except AttributeError:
    _Qt_UserRole = Qt.UserRole  # type: ignore[attr-defined]

try:
    _NoSelection     = QAbstractItemView.SelectionMode.NoSelection
    _NoEditTriggers  = QAbstractItemView.EditTrigger.NoEditTriggers
except AttributeError:
    _NoSelection     = QAbstractItemView.NoSelection      # type: ignore[attr-defined]
    _NoEditTriggers  = QAbstractItemView.NoEditTriggers   # type: ignore[attr-defined]

# ── Constants ─────────────────────────────────────────────────────────────────

_CATALOG_FILE = os.path.join(os.path.dirname(__file__), 'brazil_geobase_catalog.json')

_NIVEL_ORDER = ['Nacional', 'Subnacional', 'Governo Local', 'Universidade/Academia']
_NIVEL_COLOR = {
    'Nacional':             '#1565C0',
    'Subnacional':          '#2E7D32',
    'Governo Local':        '#E65100',
    'Universidade/Academia':'#6A1B9A',
}

_WMS_NS  = 'http://www.opengis.net/wms'
_WFS2_NS = 'http://www.opengis.net/wfs/2.0'
_WFS1_NS = 'http://www.opengis.net/wfs'

_DEFAULT_CRS = 'EPSG:4674'   # SIRGAS 2000


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_catalog():
    with open(_CATALOG_FILE, encoding='utf-8') as f:
        return json.load(f)


def _normalize_nivel(nivel: str) -> str:
    """Normalises case variants in nivel_no field."""
    n = nivel.strip()
    mapping = {
        'governo local':          'Governo Local',
        'governo local ':         'Governo Local',
        'universidade/academia':  'Universidade/Academia',
        'universidade / academia':'Universidade/Academia',
        'subnacional':            'Subnacional',
        'nacional':               'Nacional',
    }
    return mapping.get(n.lower(), n)


def _parse_wms(xml_text: str) -> list:
    """Returns list of {name, title, abstract, type='WMS'} from WMS GetCapabilities."""
    layers = []
    try:
        root = ET.fromstring(xml_text)  # nosec B314
        # Handle both namespaced and non-namespaced responses
        ns = _WMS_NS if root.tag.startswith('{') else ''
        tag = lambda t: f'{{{ns}}}{t}' if ns else t

        for elem in root.iter(tag('Layer')):
            name_el = elem.find(tag('Name'))
            title_el = elem.find(tag('Title'))
            abs_el   = elem.find(tag('Abstract'))
            if name_el is not None and name_el.text:
                layers.append({
                    'name':     name_el.text.strip(),
                    'title':    (title_el.text or name_el.text).strip() if title_el is not None else name_el.text.strip(),
                    'abstract': (abs_el.text or '').strip() if abs_el is not None else '',
                    'crs':      _DEFAULT_CRS,
                    'type':     'WMS',
                })
    except ET.ParseError:  # nosec B110
        pass
    # deduplicate by name
    seen = set()
    out = []
    for lyr in layers:
        if lyr['name'] not in seen:
            seen.add(lyr['name'])
            out.append(lyr)
    return out


def _parse_wfs(xml_text: str) -> list:
    """Returns list of {name, title, abstract, crs, type='WFS'} from WFS GetCapabilities."""
    layers = []
    try:
        root = ET.fromstring(xml_text)  # nosec B314
        # Detect namespace
        if _WFS2_NS in root.tag:
            ns = _WFS2_NS
        elif _WFS1_NS in root.tag:
            ns = _WFS1_NS
        else:
            ns = ''
        tag = lambda t: f'{{{ns}}}{t}' if ns else t

        for ft in root.iter(tag('FeatureType')):
            name_el  = ft.find(tag('Name'))
            title_el = ft.find(tag('Title'))
            abs_el   = ft.find(tag('Abstract'))
            crs_el   = ft.find(tag('DefaultCRS')) or ft.find(tag('DefaultSRS'))
            if name_el is not None and name_el.text:
                crs_raw = (crs_el.text or _DEFAULT_CRS).strip() if crs_el is not None else _DEFAULT_CRS
                # Normalise OGC URN → EPSG:XXXX
                if 'EPSG' in crs_raw.upper():
                    crs_code = 'EPSG:' + crs_raw.split(':')[-1].split('::')[-1]
                else:
                    crs_code = _DEFAULT_CRS
                layers.append({
                    'name':     name_el.text.strip(),
                    'title':    (title_el.text or name_el.text).strip() if title_el is not None else name_el.text.strip(),
                    'abstract': (abs_el.text or '').strip() if abs_el is not None else '',
                    'crs':      crs_code,
                    'type':     'WFS',
                })
    except ET.ParseError:  # nosec B110
        pass
    return layers


def _parse_wcs(xml_text: str) -> list:
    """Returns list of {name, title, type='WCS'} from WCS GetCapabilities."""
    layers = []
    try:
        root = ET.fromstring(xml_text)  # nosec B314
        # WCS 1.1.x namespace
        ns_map = {
            'wcs': 'http://www.opengis.net/wcs/1.1.1',
            'ows': 'http://www.opengis.net/ows/1.1',
        }
        # try WCS 1.1 structure
        for summary in root.iter('{http://www.opengis.net/wcs/1.1.1}CoverageSummary'):
            id_el    = summary.find('{http://www.opengis.net/ows/1.1}Identifier')
            title_el = summary.find('{http://www.opengis.net/ows/1.1}Title')
            abs_el   = summary.find('{http://www.opengis.net/ows/1.1}Abstract')
            if id_el is not None and id_el.text:
                layers.append({
                    'name':     id_el.text.strip(),
                    'title':    (title_el.text or id_el.text).strip() if title_el is not None else id_el.text.strip(),
                    'abstract': (abs_el.text or '').strip() if abs_el is not None else '',
                    'crs':      _DEFAULT_CRS,
                    'type':     'WCS',
                })
        # try WCS 2.0 / 1.0 fallback
        if not layers:
            for offer in root.iter():
                if offer.tag.endswith('CoverageId') or offer.tag.endswith('Identifier'):
                    name = (offer.text or '').strip()
                    if name:
                        layers.append({'name': name, 'title': name, 'abstract': '', 'crs': _DEFAULT_CRS, 'type': 'WCS'})
    except ET.ParseError:  # nosec B110
        pass
    return layers


def _wms_uri(base_url: str, layer_name: str,
             crs: str = _DEFAULT_CRS, fmt: str = 'image/png') -> str:
    from urllib.parse import quote
    return (
        f'IgnoreGetMapUrl=1'
        f'&crs={crs}'
        f'&dpiMode=7'
        f'&featureCount=10'
        f'&format={fmt}'
        f'&layers={quote(layer_name, safe=":")}'
        f'&styles'
        f'&url={base_url}'
    )


def _gdal_wcs_layer(base_url: str, identifier: str, title: str) -> 'QgsRasterLayer':
    """GDAL WCS XML fallback when the QGIS built-in WCS provider fails silently.

    WCS 1.0.0 is used explicitly — 1.1.1 fails on GeoServer INDE instances even
    though DescribeCoverage returns HTTP 200 with valid XML (QGIS 4 provider bug).
    GDAL reads the XML once on Open() so the temp file can be deleted immediately.
    """
    import tempfile
    xml = (
        '<WCS_GDAL>'
        f'<ServiceURL>{base_url}?</ServiceURL>'
        '<Version>1.0.0</Version>'
        f'<CoverageName>{identifier}</CoverageName>'
        '</WCS_GDAL>'
    )
    tmp = tempfile.NamedTemporaryFile(
        suffix='.xml', delete=False, mode='w', encoding='utf-8')
    tmp.write(xml)
    tmp.close()
    lyr = QgsRasterLayer(tmp.name, title, 'gdal')
    try:
        os.unlink(tmp.name)
    except Exception:  # nosec B110
        pass
    return lyr


def _gdal_wms_layer(base_url: str, layer_name: str, title: str,
                    fmt: str = 'image/png') -> 'QgsRasterLayer':
    """GDAL WMS XML fallback when the QGIS built-in WMS provider fails silently.

    Writes a temporary GDAL_WMS XML descriptor, creates the layer, then deletes
    the file (GDAL reads configuration once on Open() and needs no further access).
    Uses EPSG:4326 with global extent so any WMS server is covered.
    """
    import tempfile
    xml = (
        '<GDAL_WMS><Service name="WMS">'
        '<Version>1.3.0</Version>'
        f'<ServerUrl>{base_url}?</ServerUrl>'
        f'<Layers>{layer_name}</Layers>'
        '<CRS>EPSG:4326</CRS>'
        f'<ImageFormat>{fmt}</ImageFormat>'
        '<Transparent>TRUE</Transparent>'
        '</Service>'
        '<DataWindow>'
        '<UpperLeftX>-180</UpperLeftX><UpperLeftY>90</UpperLeftY>'
        '<LowerRightX>180</LowerRightX><LowerRightY>-90</LowerRightY>'
        '<SizeX>512</SizeX><SizeY>512</SizeY>'
        '</DataWindow>'
        '<BandsCount>4</BandsCount>'
        '</GDAL_WMS>'
    )
    tmp = tempfile.NamedTemporaryFile(
        suffix='.xml', delete=False, mode='w', encoding='utf-8')
    tmp.write(xml)
    tmp.close()
    lyr = QgsRasterLayer(tmp.name, title, 'gdal')
    try:
        os.unlink(tmp.name)
    except Exception:  # nosec B110
        pass
    return lyr


def _wfs_uri(base_url: str, typename: str, crs: str = _DEFAULT_CRS) -> str:
    from urllib.parse import quote
    return (
        f'typename={quote(typename, safe=":")}'
        f'&url={base_url}'
        f'&version=auto'
        f'&srsname={crs}'
    )


def _ogr_wfs_uri(base_url: str, typename: str) -> str:
    """GDAL OGR WFS URI — fallback when the QGIS built-in WFS provider fails.

    The QGIS 4 WFS provider silently fails on some builds (isValid()=False,
    dp_caps=67108992, no error message). The GDAL OGR WFS driver works correctly
    and is used as a fallback via provider='ogr'.

    WFS 1.1.0 is used explicitly because the FUNAI server rejects 2.0.0 GetFeature.
    """
    return (
        f'WFS:{base_url}'
        f'?SERVICE=WFS&VERSION=1.1.0&REQUEST=GetCapabilities'
        f'|layername={typename}'
    )


def _wcs_uri(base_url: str, identifier: str, crs: str = _DEFAULT_CRS) -> str:
    from urllib.parse import quote
    return (
        f'identifier={quote(identifier, safe=":")}'
        f'&url={base_url}'
        f'&crs={crs}'
    )


def _layer_error_msg(qlyr) -> str:
    """Return the QGIS data-provider error string for an invalid layer, or ''."""
    try:
        dp = qlyr.dataProvider()
        if dp is not None:
            err = dp.error()
            if err is not None:
                msg = getattr(err, 'message', lambda: '')()
                if msg:
                    return msg.strip()[:300]
    except Exception:  # nosec B110
        pass
    return ''


def _toggle_service_case(url: str) -> str:
    """Return the URL with `service` and `request` query params toggled in case.

    Some OGC servers accept only uppercase (SERVICE=WCS), others only lowercase
    (service=wcs). This returns the alternate-case variant so the caller can
    retry when the first attempt returns 0 layers.
    """
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    toggled = []
    changed = False
    for k, v in params:
        if k.lower() == 'service':
            new_v = v.lower() if v == v.upper() else v.upper()
            toggled.append((k, new_v))
            changed = True
        elif k.lower() == 'request':
            new_v = v.lower() if v == v.upper() else v.upper()
            toggled.append((k, new_v))
            changed = True
        else:
            toggled.append((k, v))
    if not changed:
        return url
    new_query = urllib.parse.urlencode(toggled)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


# ── Background fetcher ────────────────────────────────────────────────────────

class _CapFetcher(QThread):
    """Fetches GetCapabilities in a background thread."""

    done   = pyqtSignal(list, str)   # (layers, svc_type)
    failed = pyqtSignal(str)         # error message

    def __init__(self, cap_url: str, svc_type: str, parent=None):
        super().__init__(parent)
        self._cap_url  = cap_url
        self._svc_type = svc_type.upper()

    def run(self):
        try:
            parsed = urllib.parse.urlparse(self._cap_url)
            if parsed.scheme not in ('http', 'https'):
                self.failed.emit('INVALID_SCHEME: only http/https URLs are permitted')
                return
            hostname = parsed.netloc.split(':')[0]
            req = urllib.request.Request(
                self._cap_url,
                headers={'User-Agent': 'QGIS-RTH-GeoBase/1.0'},
            )
            # Build SSL context — skip verification for known broken-cert hosts
            if hostname in _SSL_NO_VERIFY:
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode    = ssl.CERT_NONE
            else:
                ssl_ctx = None
            try:
                with urllib.request.urlopen(  # nosec B310
                    req, timeout=120,
                    **(({'context': ssl_ctx}) if ssl_ctx else {}),
                ) as resp:
                    xml_bytes = resp.read()
            except urllib.error.HTTPError as e:
                self.failed.emit(f'HTTP_{e.code}: {e.reason}')
                return
            except urllib.error.URLError as e:
                reason = str(e.reason)
                if 'certificate' in reason.lower() or 'ssl' in reason.lower():
                    self.failed.emit(f'SSL: {reason}')
                elif 'timed out' in reason.lower() or 'timeout' in reason.lower():
                    self.failed.emit(f'TIMEOUT: {reason}')
                else:
                    self.failed.emit(f'CONNECTION: {reason}')
                return

            xml_text = xml_bytes.decode('utf-8', errors='replace')

            if self._svc_type == 'WMS':
                layers = _parse_wms(xml_text)
            elif self._svc_type == 'WFS':
                layers = _parse_wfs(xml_text)
            elif self._svc_type == 'WCS':
                layers = _parse_wcs(xml_text)
            else:
                layers = []

            # Retry with toggled SERVICE= case when server returned 0 layers
            # (some servers require uppercase, others lowercase)
            if not layers:
                alt_url = _toggle_service_case(self._cap_url)
                if alt_url != self._cap_url:
                    try:
                        req2 = urllib.request.Request(
                            alt_url,
                            headers={'User-Agent': 'QGIS-RTH-GeoBase/1.0'},
                        )
                        with urllib.request.urlopen(  # nosec B310
                            req2, timeout=120,
                            **(({'context': ssl_ctx}) if ssl_ctx else {}),
                        ) as resp2:
                            xml_text2 = resp2.read().decode('utf-8', errors='replace')
                        if self._svc_type == 'WMS':
                            layers2 = _parse_wms(xml_text2)
                        elif self._svc_type == 'WFS':
                            layers2 = _parse_wfs(xml_text2)
                        elif self._svc_type == 'WCS':
                            layers2 = _parse_wcs(xml_text2)
                        else:
                            layers2 = []
                        if layers2:
                            layers = layers2
                    except Exception:  # nosec B110
                        pass  # keep layers = [] from first attempt

            self.done.emit(layers, self._svc_type)
        except Exception as exc:
            self.failed.emit(str(exc))


# ── Dialog ────────────────────────────────────────────────────────────────────

class BrazilGeoBaseDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self._iface = iface
        self._catalog = _load_catalog()
        self._cap_cache: dict = {}       # {(cap_url, svc): [layers]}
        self._fetcher: _CapFetcher | None = None
        self._cur_entry: dict | None = None
        self._cur_svc: str = 'WMS'

        self.setWindowTitle('Brazil Public GeoBase / Base de Dados Pública do Brasil')
        self.setMinimumSize(1050, 650)
        self._build_ui()
        self._populate_providers()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Header ──
        hdr = QLabel(
            '<b style="font-size:14px">🌐 Brazil Public GeoBase</b>'
            ' &nbsp;|&nbsp; Base de Dados Pública do Brasil (INDE)'
        )
        root.addWidget(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # ── Main splitter ──
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # Left panel — provider tree
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 4, 0)
        left_lay.setSpacing(4)

        left_lay.addWidget(QLabel('<b>Provedores / Providers</b>'))

        self._search_prov = QLineEdit()
        self._search_prov.setPlaceholderText('Filtrar provedores… / Filter providers…')
        self._search_prov.textChanged.connect(self._filter_providers)
        left_lay.addWidget(self._search_prov)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(12)
        self._tree.setAlternatingRowColors(True)
        self._tree.currentItemChanged.connect(self._on_provider_select)
        left_lay.addWidget(self._tree, 1)

        splitter.addWidget(left)

        # Right panel — layers
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(4, 0, 0, 0)
        right_lay.setSpacing(4)

        # Provider name label
        self._lbl_prov = QLabel('<i>Selecione um provedor à esquerda… / Select a provider on the left…</i>')
        self._lbl_prov.setWordWrap(True)
        right_lay.addWidget(self._lbl_prov)

        # Service type buttons
        svc_box = QGroupBox('Tipo de serviço / Service type')
        svc_lay = QHBoxLayout(svc_box)
        svc_lay.setSpacing(6)
        self._btn_wms = QPushButton('WMS')
        self._btn_wfs = QPushButton('WFS')
        self._btn_wcs = QPushButton('WCS')
        for btn in (self._btn_wms, self._btn_wfs, self._btn_wcs):
            btn.setCheckable(True)
            btn.setEnabled(False)
            btn.setFixedWidth(72)
            svc_lay.addWidget(btn)
        svc_lay.addStretch()
        self._btn_wms.clicked.connect(lambda: self._switch_service('WMS'))
        self._btn_wfs.clicked.connect(lambda: self._switch_service('WFS'))
        self._btn_wcs.clicked.connect(lambda: self._switch_service('WCS'))

        self._btn_refresh = QPushButton('🔄  Recarregar / Refresh')
        self._btn_refresh.setToolTip(
            'Busca a lista de camadas novamente no servidor / Re-fetch the layer list from the server')
        self._btn_refresh.setEnabled(False)
        self._btn_refresh.clicked.connect(self._refresh_list)
        svc_lay.addWidget(self._btn_refresh)

        right_lay.addWidget(svc_box)

        # Layer filter + select all / deselect all
        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)
        self._search_lyr = QLineEdit()
        self._search_lyr.setPlaceholderText('Filtrar camadas… / Filter layers…')
        self._search_lyr.textChanged.connect(self._filter_layers)
        filter_row.addWidget(self._search_lyr, 1)

        self._btn_sel_all   = QPushButton('☑ Todos / All')
        self._btn_desel_all = QPushButton('☐ Nenhum / None')
        for _b in (self._btn_sel_all, self._btn_desel_all):
            _b.setEnabled(False)
            _b.setFixedWidth(100)
        self._btn_sel_all.clicked.connect(self._select_all)
        self._btn_desel_all.clicked.connect(self._deselect_all)
        filter_row.addWidget(self._btn_sel_all)
        filter_row.addWidget(self._btn_desel_all)
        right_lay.addLayout(filter_row)

        # Layer table
        self._lyr_model = QStandardItemModel(0, 2)
        self._lyr_model.setHorizontalHeaderLabels(['Identificador / Name', 'Título / Title'])

        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._lyr_model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)  # all columns

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSelectionMode(_NoSelection)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(_NoEditTriggers)
        right_lay.addWidget(self._table, 1)

        # Progress bar (hidden when idle)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminate
        self._progress.setVisible(False)
        self._progress.setFixedHeight(6)
        right_lay.addWidget(self._progress)

        # Status label — fetch errors, layer counts
        self._lbl_cap_status = QLabel('')
        self._lbl_cap_status.setWordWrap(True)
        self._lbl_cap_status.setStyleSheet('font-size:10px;color:#555;padding:2px;')
        self._lbl_cap_status.setVisible(False)
        right_lay.addWidget(self._lbl_cap_status)

        splitter.addWidget(right)
        splitter.setSizes([320, 730])

        # ── Bottom buttons ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_virt = QPushButton('▶  Virtualizar Selecionadas / Virtualize Selected')
        self._btn_virt.setEnabled(False)
        self._btn_virt.setToolTip('Adiciona as camadas selecionadas ao mapa (streaming, sem download) / Adds selected layers to the map (streaming, no download)')
        self._btn_virt.clicked.connect(self._virtualize_selected)

        self._btn_dl = QPushButton('💾  Baixar WFS como GeoPackage / Download WFS as GPKG')
        self._btn_dl.setEnabled(False)
        self._btn_dl.setToolTip('Baixa as camadas WFS selecionadas como arquivo GeoPackage local / Downloads selected WFS layers as a local GeoPackage file')
        self._btn_dl.clicked.connect(self._download_selected)

        self._btn_close = QPushButton('Fechar / Close')
        self._btn_close.clicked.connect(self.accept)

        btn_row.addWidget(self._btn_virt)
        btn_row.addWidget(self._btn_dl)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

        # checkbox change → enable action buttons
        self._lyr_model.itemChanged.connect(self._on_layer_select)

    # ── Provider tree ─────────────────────────────────────────────────────────

    def _populate_providers(self):
        self._tree.clear()

        # Group entries by nivel in pure Python first, then add to tree in order
        # (never clear() after items have already been added — that destroys C++ objects)
        groups: dict[str, list] = {}
        for entry in self._catalog:
            nivel = _normalize_nivel(entry.get('nivel_no', 'Nacional'))
            groups.setdefault(nivel, []).append(entry)

        all_niveaux = list(_NIVEL_ORDER) + [n for n in groups if n not in _NIVEL_ORDER]

        for nivel in all_niveaux:
            if nivel not in groups:
                continue
            grp = QTreeWidgetItem(self._tree, [nivel])
            color = _NIVEL_COLOR.get(nivel, '#333333')
            grp.setForeground(0, QBrush(QColor(color)))
            font = grp.font(0)
            font.setBold(True)
            grp.setFont(0, font)
            grp.setExpanded(True)

            for entry in groups[nivel]:
                desc = entry.get('descricao', '?')
                badges = []
                if entry.get('wmsAvailable'): badges.append('WMS')
                if entry.get('wfsAvailable'): badges.append('WFS')
                if entry.get('wcsAvailable'): badges.append('WCS')
                label = f"{desc}  [{' · '.join(badges)}]"
                child = QTreeWidgetItem(grp, [label])
                child.setData(0, _Qt_UserRole, entry)
                child.setToolTip(0, entry.get('url', ''))


    def _filter_providers(self, text: str):
        text = text.strip().lower()
        root = self._tree.invisibleRootItem()
        for gi in range(root.childCount()):
            grp = root.child(gi)
            any_vis = False
            for ci in range(grp.childCount()):
                child = grp.child(ci)
                vis = not text or text in child.text(0).lower()
                child.setHidden(not vis)
                if vis:
                    any_vis = True
            grp.setHidden(not any_vis)

    # ── Provider selection ────────────────────────────────────────────────────

    def _on_provider_select(self, current, _previous):
        if current is None:
            return
        entry = current.data(0, _Qt_UserRole)
        if entry is None:
            return   # group item clicked

        self._cur_entry = entry
        desc = entry.get('descricao', '')
        url  = entry.get('url', '')
        self._lbl_prov.setText(f'<b>{desc}</b><br><small style="color:#555">{url}</small>')

        # enable service buttons
        self._btn_wms.setEnabled(bool(entry.get('wmsAvailable')))
        self._btn_wfs.setEnabled(bool(entry.get('wfsAvailable')))
        self._btn_wcs.setEnabled(bool(entry.get('wcsAvailable')))
        self._btn_refresh.setEnabled(True)

        # switch to first available service
        if entry.get('wmsAvailable'):
            self._switch_service('WMS')
        elif entry.get('wfsAvailable'):
            self._switch_service('WFS')
        elif entry.get('wcsAvailable'):
            self._switch_service('WCS')
        else:
            self._clear_layers()

    def _refresh_list(self):
        if self._cur_entry is None:
            return
        cap_url = self._cur_entry.get(f'{self._cur_svc.lower()}GetCapabilities')
        if cap_url:
            self._cap_cache.pop((cap_url, self._cur_svc), None)
        self._switch_service(self._cur_svc)

    def _switch_service(self, svc: str):
        if self._cur_entry is None:
            return
        self._cur_svc = svc
        # update button states
        self._btn_wms.setChecked(svc == 'WMS')
        self._btn_wfs.setChecked(svc == 'WFS')
        self._btn_wcs.setChecked(svc == 'WCS')
        # update download button label
        if svc == 'WFS':
            self._btn_dl.setText('💾  Baixar WFS como GeoPackage / Download as GPKG')
            self._btn_dl.setToolTip('Baixa as camadas WFS selecionadas como arquivo GeoPackage local / Downloads selected WFS layers as a local GeoPackage file')
        else:
            self._btn_dl.setText('💾  Baixar como GeoTIFF / Download as GeoTIFF')
            self._btn_dl.setToolTip(
                'Baixa as camadas selecionadas como GeoTIFF local '
                '(usa a extensão visível no mapa atual).\n'
                'Downloads the selected layers as a local GeoTIFF '
                '(uses the current map canvas extent).'
            )

        cap_url = self._cur_entry.get(f'{svc.lower()}GetCapabilities')
        if not cap_url:
            self._clear_layers()
            return

        cache_key = (cap_url, svc)
        if cache_key in self._cap_cache:
            self._populate_layers(self._cap_cache[cache_key])
            return

        # fetch in background
        self._clear_layers()
        self._start_fetch(cap_url, svc)

    # ── Background fetch ──────────────────────────────────────────────────────

    def _start_fetch(self, cap_url: str, svc: str):
        if self._fetcher and self._fetcher.isRunning():
            self._fetcher.done.disconnect()
            self._fetcher.failed.disconnect()
            self._fetcher.quit()
            self._fetcher.wait(2000)

        self._lbl_cap_status.setText(f'Conectando ao provedor {svc}… / Connecting to {svc} provider…')
        self._lbl_cap_status.setStyleSheet('font-size:10px;color:#555;padding:2px;')
        self._lbl_cap_status.setVisible(True)
        self._progress.setVisible(True)

        self._fetcher = _CapFetcher(cap_url, svc, self)
        self._fetcher.done.connect(self._on_fetch_done)
        self._fetcher.failed.connect(self._on_fetch_failed)
        self._fetcher.start()

    def _on_fetch_done(self, layers: list, svc: str):
        self._progress.setVisible(False)
        cap_url = self._cur_entry.get(f'{svc.lower()}GetCapabilities', '') if self._cur_entry else ''
        self._cap_cache[(cap_url, svc)] = layers
        if svc == self._cur_svc:
            self._populate_layers(layers)
            if layers:
                self._lbl_cap_status.setText(f'{len(layers)} camada(s) disponível(is) / layer(s) available via {svc}.')
                self._lbl_cap_status.setStyleSheet('font-size:10px;color:#2e7d32;padding:2px;')
            else:
                self._lbl_cap_status.setText(
                    f'Nenhuma camada encontrada via {svc}. '
                    f'Tente outro tipo de serviço (WMS / WFS / WCS) ou tente mais tarde.\n'
                    f'No layers found via {svc}. Try another service type or try again later.'
                )
                self._lbl_cap_status.setStyleSheet('font-size:10px;color:#e65100;padding:2px;')

    def _on_fetch_failed(self, msg: str):
        self._progress.setVisible(False)
        self._lyr_model.setRowCount(0)

        if msg.startswith('HTTP_403') or '403' in msg or 'forbidden' in msg.lower():
            note = (self._cur_entry or {}).get('accessNote', '')
            display = (
                '⛔  Acesso público bloqueado / Public access blocked (HTTP 403).\n'
                'Este servidor removeu o acesso público aos seus serviços geoespaciais.\n'
                'This server has removed public access to its geospatial services.\n'
                + (f'{note}\n' if note else
                   'Se o acesso for restaurado, o plugin voltará a funcionar automaticamente.\n'
                   'If access is restored, the plugin will work again automatically.\n'
                   'Reporte em / Report at: https://github.com/RithonBR/rth-project/issues')
            )
        elif msg.startswith('HTTP_404') or msg.startswith('HTTP_503') or msg.startswith('HTTP_502'):
            display = (
                '🔴  Servidor indisponível temporariamente / Server temporarily unavailable.\n'
                'Este serviço está fora do ar no momento. Tente novamente mais tarde.\n'
                'This service is currently down. Please try again later.'
            )
        elif msg.startswith('HTTP_'):
            code = msg.split(':')[0].replace('HTTP_', '')
            display = (
                f'⚠  Erro HTTP {code} / HTTP {code} error.\n'
                f'{msg[len(f"HTTP_{code}: "):][:100]}'
            )
        elif msg.startswith('TIMEOUT') or 'timed out' in msg.lower() or 'timeout' in msg.lower():
            display = (
                '⏳  Servidor não respondeu. Tente trocar o tipo de serviço (WMS / WFS / WCS).\n'
                'Se não funcionar, o servidor está fora do ar.\n'
                'Server did not respond. Try switching the service type (WMS / WFS / WCS).\n'
                'If it still fails, the server is down.'
            )
        elif msg.startswith('SSL') or 'certificate' in msg.lower():
            display = (
                '🔒  Certificado SSL inválido / Invalid SSL certificate.\n'
                'O servidor possui um certificado SSL com problema de cadeia de certificação.\n'
                'The server has an SSL certificate with a broken certificate chain.\n'
                'As camadas podem não carregar corretamente neste servidor.\n'
                'Layers may not load correctly from this server.'
            )
        elif msg.startswith('CONNECTION'):
            display = (
                '🔌  Não foi possível conectar ao servidor. Verifique sua conexão com a internet.\n'
                'Could not connect to server. Check your internet connection.\n'
                + msg[12:][:100]
            )
        else:
            display = f'⚠  Erro / Error:\n{msg[:150]}'

        self._lbl_cap_status.setText(display)
        self._lbl_cap_status.setStyleSheet(
            'font-size:10px;color:#b71c1c;background:#ffebee;'
            'border:1px solid #e57373;border-radius:3px;padding:4px;'
        )
        self._lbl_cap_status.setVisible(True)

    # ── Layer table ───────────────────────────────────────────────────────────

    def _clear_layers(self):
        self._lyr_model.setRowCount(0)
        self._btn_virt.setEnabled(False)
        self._btn_dl.setEnabled(False)
        self._btn_sel_all.setEnabled(False)
        self._btn_desel_all.setEnabled(False)
        self._lbl_cap_status.setVisible(False)
        self._lbl_cap_status.setText('')

    def _populate_layers(self, layers: list):
        # Disconnect itemChanged only — the view still needs rowsInserted to repaint
        try:
            self._lyr_model.itemChanged.disconnect(self._on_layer_select)
        except (TypeError, RuntimeError):  # nosec B110
            pass

        self._lyr_model.setRowCount(0)
        for lyr in layers:
            name_item  = QStandardItem(lyr.get('name', ''))
            title_item = QStandardItem(lyr.get('title', ''))
            name_item.setFlags(_Qt_ItemIsUserCheckable | _Qt_ItemIsEnabled)
            name_item.setCheckState(_Qt_Unchecked)
            title_item.setFlags(_Qt_ItemIsEnabled)
            name_item.setData(lyr, _Qt_UserRole)
            name_item.setToolTip(lyr.get('abstract', ''))
            title_item.setToolTip(lyr.get('abstract', ''))
            self._lyr_model.appendRow([name_item, title_item])

        self._lyr_model.itemChanged.connect(self._on_layer_select)
        self._on_layer_select()

    def _filter_layers(self, text: str):
        self._proxy.setFilterFixedString(text)

    def _on_layer_select(self, *_):
        has_checked = any(
            self._lyr_model.item(r, 0).checkState() == _Qt_Checked
            for r in range(self._lyr_model.rowCount())
            if self._lyr_model.item(r, 0)
        )
        has_layers = self._lyr_model.rowCount() > 0
        self._btn_virt.setEnabled(has_checked)
        self._btn_dl.setEnabled(has_checked)
        self._btn_sel_all.setEnabled(has_layers)
        self._btn_desel_all.setEnabled(has_checked)

    def _selected_layers(self) -> list:
        layers = []
        for r in range(self._lyr_model.rowCount()):
            item = self._lyr_model.item(r, 0)
            if item and item.checkState() == _Qt_Checked:
                layers.append(item.data(_Qt_UserRole))
        return layers

    def _select_all(self):
        try:
            self._lyr_model.itemChanged.disconnect(self._on_layer_select)
        except (TypeError, RuntimeError):  # nosec B110
            pass
        # Deselect everything first so hidden rows never stay checked silently
        for r in range(self._lyr_model.rowCount()):
            item = self._lyr_model.item(r, 0)
            if item:
                item.setCheckState(_Qt_Unchecked)
        # Then select only the rows currently visible in the filter
        for proxy_r in range(self._proxy.rowCount()):
            src_idx = self._proxy.mapToSource(self._proxy.index(proxy_r, 0))
            item = self._lyr_model.item(src_idx.row(), 0)
            if item:
                item.setCheckState(_Qt_Checked)
        self._lyr_model.itemChanged.connect(self._on_layer_select)
        self._on_layer_select()

    def _deselect_all(self):
        try:
            self._lyr_model.itemChanged.disconnect(self._on_layer_select)
        except (TypeError, RuntimeError):  # nosec B110
            pass
        for r in range(self._lyr_model.rowCount()):
            item = self._lyr_model.item(r, 0)
            if item:
                item.setCheckState(_Qt_Unchecked)
        self._lyr_model.itemChanged.connect(self._on_layer_select)
        self._on_layer_select()

    # ── Virtualize ────────────────────────────────────────────────────────────

    def _virtualize_selected(self):
        if self._cur_entry is None:
            return
        base_url = self._cur_entry.get('url', '')
        svc = self._cur_svc
        sel = self._selected_layers()
        if not sel:
            return

        added = 0
        errors = []
        is_raster_svc = svc in ('WMS', 'WCS')
        total = len(sel)

        self._btn_virt.setEnabled(False)
        self._btn_dl.setEnabled(False)
        self._progress.setVisible(True)
        self._lbl_cap_status.setStyleSheet('font-size:10px;color:#555;padding:2px;')
        self._lbl_cap_status.setVisible(True)

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for i, lyr in enumerate(sel):
                name  = lyr.get('name', '')
                title = lyr.get('title', name)
                crs   = lyr.get('crs', _DEFAULT_CRS)

                self._lbl_cap_status.setText(
                    f'⏳ [{i + 1}/{total}] Conectando: {title or name}…'
                )
                QApplication.processEvents()

                try:
                    if svc == 'WMS':
                        uri = _wms_uri(base_url, name, crs)
                        qlyr = QgsRasterLayer(uri, title, 'wms')
                        # GDAL WMS XML fallback — handles servers (e.g. ArcGIS) where
                        # the QGIS WMS provider silently fails due to slow GetCapabilities.
                        if not qlyr.isValid():
                            qlyr = _gdal_wms_layer(base_url, name, title)
                    elif svc == 'WFS':
                        uri = _wfs_uri(base_url, name, crs)
                        # Try native QGIS WFS provider (works on QGIS 3 and healthy QGIS 4)
                        qlyr = QgsVectorLayer(uri, title, 'WFS')
                        if not qlyr.isValid():
                            qlyr = QgsVectorLayer(uri, title, 'wfs')
                        # QGIS 4 bug: built-in WFS provider silently fails
                        # (dp_caps=67108992, isValid=False, zero error messages).
                        # Fall back to the GDAL OGR WFS driver which works on all builds.
                        if not qlyr.isValid():
                            dp = qlyr.dataProvider()
                            if dp is not None and int(dp.capabilities()) > 0:
                                qlyr = QgsVectorLayer(_ogr_wfs_uri(base_url, name), title, 'ogr')
                    elif svc == 'WCS':
                        uri = _wcs_uri(base_url, name, crs)
                        qlyr = QgsRasterLayer(uri, title, 'wcs')
                        if not qlyr.isValid():
                            qlyr = QgsRasterLayer(uri, title, 'WCS')
                        # GDAL WCS XML fallback — WCS 1.0.0 works where the QGIS
                        # WCS provider silently fails (same pattern as WFS/WMS).
                        if not qlyr.isValid():
                            qlyr = _gdal_wcs_layer(base_url, name, title)
                    else:
                        continue
                except Exception as exc:
                    errors.append(f'{name} ({exc})')
                    continue

                if qlyr.isValid():
                    QgsProject.instance().addMapLayer(qlyr)
                    collapse_layer(qlyr)
                    added += 1
                else:
                    err_detail = _layer_error_msg(qlyr)
                    errors.append(f'{name}: {err_detail}' if err_detail else name)
        finally:
            QApplication.restoreOverrideCursor()
            self._progress.setVisible(False)
            self._on_layer_select()

        if added:
            self._lbl_cap_status.setText(
                f'✅ {added} camada(s) adicionada(s) ao mapa. / {added} layer(s) added to map.'
            )
            self._lbl_cap_status.setStyleSheet('font-size:10px;color:#2e7d32;padding:2px;')
            self._iface.messageBar().pushMessage(
                'GeoBase', f'{added} camada(s) adicionada(s) ao mapa. / {added} layer(s) added to map.',
                level=Qgis.Success, duration=5
            )
        if errors:
            err_text = '\n'.join(errors)
            self._lbl_cap_status.setText(f'⚠ Falha ao carregar / Failed to load:\n{err_text}')
            self._lbl_cap_status.setStyleSheet(
                'font-size:10px;color:#b71c1c;background:#ffebee;'
                'border:1px solid #e57373;border-radius:3px;padding:4px;'
            )
            self._lbl_cap_status.setVisible(True)
            if is_raster_svc:
                self._iface.messageBar().pushMessage(
                    'GeoBase — Servidor indisponível / Server unavailable',
                    (
                        f'Não foi possível carregar: {", ".join(errors[:3])}{"…" if len(errors) > 3 else ""}. '
                        f'O servidor WMS/WCS não respondeu a tempo — instabilidade do servidor público, não um erro do plugin. '
                        f'/ Could not load: server did not respond in time. Try again later.'
                    ),
                    level=Qgis.Warning,
                    duration=20,
                )
            else:
                self._iface.messageBar().pushMessage(
                    'GeoBase', f'Falha ao carregar / Failed to load: {"; ".join(e.split(chr(10))[0] for e in errors)[:120]}',
                    level=Qgis.Warning, duration=10
                )

    # ── Raster download helper (WMS / WCS → GeoTIFF) ─────────────────────────

    def _download_raster(self, qlyr: QgsRasterLayer, out_path: str) -> tuple:
        """Export a streaming raster layer to a local GeoTIFF.

        Uses the current map canvas extent clipped to the layer's own extent.
        Resolution is capped at 4096 px on the longest side to avoid very large files.
        Returns (ok: bool, error_message: str).
        """
        canvas = self._iface.mapCanvas()
        layer_extent = qlyr.extent()

        # Reproject canvas extent to layer CRS if necessary
        canvas_crs = canvas.mapSettings().destinationCrs()
        if canvas_crs != qlyr.crs():
            try:
                xform = QgsCoordinateTransform(canvas_crs, qlyr.crs(), QgsProject.instance())
                canvas_extent = xform.transformBoundingBox(canvas.extent())
            except Exception:
                canvas_extent = layer_extent
        else:
            canvas_extent = canvas.extent()

        extent = canvas_extent.intersect(layer_extent)
        if not extent.isFinite() or extent.isEmpty():
            extent = layer_extent

        # Calculate output size preserving aspect ratio, max 4096 px
        max_px = 4096
        aspect = extent.width() / max(extent.height(), 1e-10)
        if aspect >= 1:
            cols = max_px
            rows = max(1, int(max_px / aspect))
        else:
            rows = max_px
            cols = max(1, int(max_px * aspect))

        pipe = QgsRasterPipe()
        if not pipe.set(qlyr.dataProvider().clone()):
            return False, 'Não foi possível criar o pipeline de exportação. / Could not create export pipeline.'

        writer = QgsRasterFileWriter(out_path)
        writer.setOutputFormat('GTiff')
        error = writer.writeRaster(pipe, cols, rows, extent, qlyr.crs())
        if error != QgsRasterFileWriter.NoError:
            return False, f'Erro ao salvar GeoTIFF (código {error}) / Error saving GeoTIFF (code {error})'
        return True, ''

    # ── Download (WFS → GeoPackage | WMS/WCS → GeoTIFF) ─────────────────────

    def _download_selected(self):
        if self._cur_entry is None:
            return
        svc = self._cur_svc
        sel = self._selected_layers()
        if not sel:
            return

        out_dir = QFileDialog.getExistingDirectory(
            self, 'Selecionar pasta de saída / Select output folder'
        )
        if not out_dir:
            return

        base_url = self._cur_entry.get('url', '')
        provider_slug = self._cur_entry.get('descricao', 'geobase').split()[0].replace('/', '_')
        errors = []
        total = len(sel)

        self._btn_virt.setEnabled(False)
        self._btn_dl.setEnabled(False)
        self._progress.setVisible(True)
        self._lbl_cap_status.setStyleSheet('font-size:10px;color:#555;padding:2px;')
        self._lbl_cap_status.setVisible(True)

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for i, lyr_def in enumerate(sel):
                name  = lyr_def.get('name', '')
                title = lyr_def.get('title', name)
                crs   = lyr_def.get('crs', _DEFAULT_CRS)
                safe_name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in name)

                self._lbl_cap_status.setText(
                    f'⏳ [{i + 1}/{total}] Conectando: {title or name}…'
                )
                QApplication.processEvents()

                if svc == 'WFS':
                    # ── WFS → GeoPackage ──────────────────────────────────
                    uri    = _wfs_uri(base_url, name, crs)
                    vlayer = QgsVectorLayer(uri, title, 'WFS')
                    if not vlayer.isValid():
                        vlayer = QgsVectorLayer(uri, title, 'wfs')
                    # QGIS 4 bug: fall back to GDAL OGR WFS driver
                    if not vlayer.isValid():
                        dp = vlayer.dataProvider()
                        if dp is not None and int(dp.capabilities()) > 0:
                            vlayer = QgsVectorLayer(_ogr_wfs_uri(base_url, name), title, 'ogr')
                    if not vlayer.isValid():
                        err_detail = _layer_error_msg(vlayer)
                        errors.append(f'{name}: {err_detail}' if err_detail else f'{name} (inválida)')
                        continue

                    out_path = os.path.join(out_dir, f'{provider_slug}_{safe_name}.gpkg')
                    self._lbl_cap_status.setText(
                        f'⏳ [{i + 1}/{total}] Salvando GeoPackage: {title or name}…'
                    )
                    QApplication.processEvents()

                    opts = QgsVectorFileWriter.SaveVectorOptions()
                    opts.driverName = 'GPKG'
                    opts.fileEncoding = 'UTF-8'
                    try:
                        result, err_msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
                            vlayer, out_path, QgsCoordinateTransformContext(), opts)
                    except (AttributeError, TypeError):
                        result, err_msg = QgsVectorFileWriter.writeAsVectorFormatV2(
                            vlayer, out_path, QgsCoordinateTransformContext(), opts)
                    if result != QgsVectorFileWriter.NoError:
                        errors.append(f'{name} ({err_msg})')
                        continue

                    self._lbl_cap_status.setText(
                        f'⏳ [{i + 1}/{total}] Abrindo no QGIS: {title or name}…'
                    )
                    QApplication.processEvents()

                    local_lyr = QgsVectorLayer(out_path, title, 'ogr')
                    if local_lyr.isValid():
                        QgsProject.instance().addMapLayer(local_lyr)
                        collapse_layer(local_lyr)

                else:
                    # ── WMS / WCS → GeoTIFF ───────────────────────────────
                    if svc == 'WMS':
                        uri  = _wms_uri(base_url, name, crs)
                        rlyr = QgsRasterLayer(uri, title, 'wms')
                        # GDAL WMS XML fallback — same as in _virtualize_selected
                        if not rlyr.isValid():
                            rlyr = _gdal_wms_layer(base_url, name, title)
                    else:
                        uri  = _wcs_uri(base_url, name, crs)
                        rlyr = QgsRasterLayer(uri, title, 'wcs')
                        if not rlyr.isValid():
                            rlyr = QgsRasterLayer(uri, title, 'WCS')
                        # GDAL WCS XML fallback — same as in _virtualize_selected
                        if not rlyr.isValid():
                            rlyr = _gdal_wcs_layer(base_url, name, title)

                    if not rlyr.isValid():
                        err_detail = _layer_error_msg(rlyr)
                        errors.append(f'{name}: {err_detail}' if err_detail else f'{name} (inválida)')
                        continue

                    out_path = os.path.join(out_dir, f'{provider_slug}_{safe_name}.tif')
                    self._lbl_cap_status.setText(
                        f'⏳ [{i + 1}/{total}] Exportando GeoTIFF: {title or name}…'
                    )
                    QApplication.processEvents()

                    ok, err_msg = self._download_raster(rlyr, out_path)
                    if not ok:
                        errors.append(f'{name} ({err_msg})')
                        continue

                    self._lbl_cap_status.setText(
                        f'⏳ [{i + 1}/{total}] Abrindo no QGIS: {title or name}…'
                    )
                    QApplication.processEvents()

                    local_lyr = QgsRasterLayer(out_path, title, 'gdal')
                    if local_lyr.isValid():
                        QgsProject.instance().addMapLayer(local_lyr)
                        collapse_layer(local_lyr)

        finally:
            QApplication.restoreOverrideCursor()
            self._progress.setVisible(False)
            self._on_layer_select()

        if errors:
            self._lbl_cap_status.setText(
                f'⚠ Erros ao baixar / Download errors: {"; ".join(errors)}'
            )
            self._lbl_cap_status.setStyleSheet(
                'font-size:10px;color:#b71c1c;background:#ffebee;'
                'border:1px solid #e57373;border-radius:3px;padding:4px;'
            )
            self._iface.messageBar().pushMessage(
                'GeoBase — Erro no download / Download error',
                (
                    f'Não foi possível baixar: {", ".join(errors[:3])}{"…" if len(errors) > 3 else ""}. '
                    f'Verifique se o servidor WMS/WCS está acessível e tente novamente. / '
                    f'Could not download. Check if the WMS/WCS server is accessible and try again.'
                ),
                level=Qgis.Warning, duration=12,
            )
        else:
            saved = total - len(errors)
            self._lbl_cap_status.setText(
                f'✅ {saved} camada(s) salvas em {out_dir} e abertas no QGIS. / '
                f'{saved} layer(s) saved to {out_dir} and opened in QGIS.'
            )
            self._lbl_cap_status.setStyleSheet('font-size:10px;color:#2e7d32;padding:2px;')
            self._iface.messageBar().pushMessage(
                'GeoBase', f'Download concluído em / completed in {out_dir}',
                level=Qgis.Success, duration=6
            )

    def closeEvent(self, event):
        if self._fetcher and self._fetcher.isRunning():
            self._fetcher.quit()
            self._fetcher.wait(3000)
        super().closeEvent(event)


# ── Tool entry point ──────────────────────────────────────────────────────────

class BrazilGeoBaseTool:

    def __init__(self, iface):
        self._iface = iface
        self._dlg: BrazilGeoBaseDialog | None = None

    def run(self):
        if self._dlg is None or not self._dlg.isVisible():
            self._dlg = BrazilGeoBaseDialog(self._iface, self._iface.mainWindow())
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
