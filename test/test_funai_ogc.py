# -*- coding: utf-8 -*-
"""
test_funai_ogc.py
─────────────────────────────────────────────────────────────────────────────
Diagnostic test — FUNAI WFS + WCS virtualize & download.

Run from QGIS Python console:
    exec(open(r'C:/Users/nohti/Desktop/rth_project/test/test_funai_ogc.py').read())

Or run standalone (needs QGIS_PREFIX_PATH set):
    python test/test_funai_ogc.py
─────────────────────────────────────────────────────────────────────────────
"""
import os
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # noqa: S405  # nosec B405

# ── Endpoints ─────────────────────────────────────────────────────────────────

FUNAI_BASE    = 'https://geoserver.funai.gov.br/geoserver/ows'
FUNAI_WFS_CAP = (
    'https://geoserver.funai.gov.br/geoserver/ows'
    '?service=wfs&request=GetCapabilities&version=2.0.0'
)
FUNAI_WCS_CAP = (
    'https://geoserver.funai.gov.br/geoserver/ows'
    '?service=wcs&request=GetCapabilities&version=1.1.1'
)
# Second FUNAI server (CMR)
CMR_BASE    = 'https://cmr.funai.gov.br/geoserver/ows'
CMR_WFS_CAP = (
    'https://cmr.funai.gov.br/geoserver/ows'
    '?service=wfs&request=GetCapabilities&version=2.0.0'
)

SEP  = '─' * 72
SEP2 = '═' * 72

RESULTS = []   # (section, status, detail)

def p(msg=''):
    print(msg)
    RESULTS.append(msg)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch(url, label=''):
    """Fetch URL, return (status_code, text, error_str)."""
    try:
        req = urllib.request.Request(
            url, headers={'User-Agent': 'QGIS-RTH-Test/1.0'})
        with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310
            return r.getcode(), r.read().decode('utf-8', errors='replace'), None
    except urllib.error.HTTPError as e:
        return e.code, None, f'HTTP {e.code}: {e.reason}'
    except urllib.error.URLError as e:
        return None, None, f'URLError: {e.reason}'
    except Exception as e:
        return None, None, f'{type(e).__name__}: {e}'


def _layer_info(lyr):
    """Return detailed QGIS layer info dict."""
    info = {'valid': lyr.isValid()}
    try:
        info['provider_type'] = lyr.providerType()
    except Exception:
        info['provider_type'] = '?'
    try:
        dp = lyr.dataProvider()
        info['has_dp'] = dp is not None
        if dp:
            info['dp_name'] = dp.name()
            try:
                info['dp_is_valid'] = dp.isValid()
            except Exception:
                info['dp_is_valid'] = '?'
            # error()
            try:
                err = dp.error()
                if err is not None:
                    info['dp_error_msg']     = getattr(err, 'message', lambda: '')()
                    info['dp_error_summary'] = getattr(err, 'summary', lambda: '')()
                    info['dp_error_empty']   = getattr(err, 'isEmpty', lambda: True)()
            except Exception as exc:
                info['dp_error_exception'] = str(exc)
            # lastError*
            for attr in ('lastErrorTitle', 'lastErrorMessage', 'lastError'):
                try:
                    val = getattr(dp, attr, None)
                    if callable(val):
                        info[attr] = val()
                except Exception:  # nosec B110
                    pass
            # capabilities
            try:
                caps = dp.capabilities()
                info['dp_caps'] = int(caps)
            except Exception:  # nosec B110
                pass
            # feature count
            try:
                info['feature_count'] = dp.featureCount()
            except Exception:  # nosec B110
                pass
            # crs
            try:
                info['crs'] = dp.crs().authid()
            except Exception:  # nosec B110
                pass
            # fields for vector
            try:
                flds = dp.fields()
                info['field_count'] = flds.count()
                info['fields'] = [flds.at(i).name() for i in range(min(flds.count(), 8))]
            except Exception:  # nosec B110
                pass
    except Exception as exc:
        info['dp_exception'] = str(exc)
    return info


def _print_info(info: dict, indent='  '):
    for k, v in info.items():
        if isinstance(v, str) and len(v) > 120:
            v = v[:120] + '…'
        p(f'{indent}{k}: {v}')


# ── Section 0: QGIS Provider Registry ─────────────────────────────────────────

def section_0_registry():
    p(SEP2)
    p('SECTION 0 — QGIS Provider Registry')
    p(SEP2)
    try:
        from qgis.core import QgsProviderRegistry
        reg = QgsProviderRegistry.instance()
        providers = sorted(reg.providerList())
        p(f'Available providers ({len(providers)}):')
        p('  ' + '  '.join(providers))
        p()
        for key in ('wfs', 'WFS', 'wcs', 'WCS', 'wms', 'WMS', 'ogr', 'gdal'):
            try:
                md = reg.providerMetadata(key)
                p(f"  providerMetadata('{key}'): {md}")
            except Exception as exc:
                p(f"  providerMetadata('{key}'): EXCEPTION — {exc}")
    except Exception as exc:
        p(f'EXCEPTION in section_0: {exc}')
        traceback.print_exc()


# ── Section 1: Raw network — WFS GetCapabilities ──────────────────────────────

def section_1_wfs_network():
    p()
    p(SEP2)
    p('SECTION 1 — Raw network: FUNAI WFS GetCapabilities')
    p(SEP2)

    p(f'URL: {FUNAI_WFS_CAP}')
    code, text, err = _fetch(FUNAI_WFS_CAP, 'WFS')
    p(f'HTTP status: {code}')
    if err:
        p(f'ERROR: {err}')
        return None
    p(f'Response size: {len(text)} chars')

    # Parse
    try:
        root = ET.fromstring(text)  # nosec B314
        p(f'XML root tag: {root.tag}')
    except Exception as exc:
        p(f'XML parse error: {exc}')
        p(f'First 500 chars: {text[:500]}')
        return None

    # Count FeatureTypes
    feature_types = []
    for ft in root.iter():
        local = ft.tag.split('}')[-1] if '}' in ft.tag else ft.tag
        if local == 'FeatureType':
            name_el  = None
            title_el = None
            crs_el   = None
            for child in ft:
                cl = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if cl == 'Name':
                    name_el = child
                elif cl == 'Title':
                    title_el = child
                elif cl in ('DefaultCRS', 'DefaultSRS'):
                    crs_el = child
            name = (name_el.text or '').strip() if name_el is not None else ''
            title = (title_el.text or '').strip() if title_el is not None else ''
            crs   = (crs_el.text or '').strip()   if crs_el  is not None else ''
            if name:
                feature_types.append({'name': name, 'title': title, 'crs': crs})

    p(f'Feature types found: {len(feature_types)}')
    for i, ft in enumerate(feature_types[:15]):
        p(f"  [{i+1:02d}] {ft['name']}  |  {ft['title'][:50]}  |  CRS: {ft['crs']}")
    if len(feature_types) > 15:
        p(f'  … and {len(feature_types) - 15} more')
    return feature_types


# ── Section 2: Raw network — WCS GetCapabilities ──────────────────────────────

def section_2_wcs_network():
    p()
    p(SEP2)
    p('SECTION 2 — Raw network: FUNAI WCS GetCapabilities')
    p(SEP2)

    p(f'URL: {FUNAI_WCS_CAP}')
    code, text, err = _fetch(FUNAI_WCS_CAP, 'WCS')
    p(f'HTTP status: {code}')
    if err:
        p(f'ERROR: {err}')
        return
    p(f'Response size: {len(text)} chars')
    p(f'First 600 chars of response:')
    p(text[:600])

    # Count coverages
    cov_count = 0
    for tag in ('CoverageSummary', 'CoverageId', 'Identifier', 'CoverageOfferingBrief'):
        for _ in ET.fromstring(text).iter():  # nosec B314
            local = _.tag.split('}')[-1] if '}' in _.tag else _.tag
            if local == tag:
                cov_count += 1
    p(f'Coverage elements found (any tag): {cov_count}')
    if cov_count == 0:
        p('→ WCS server has NO published coverages (expected per browser check)')


# ── Section 3: QGIS WFS layer creation ───────────────────────────────────────

def section_3_wfs_layer(feature_types):
    p()
    p(SEP2)
    p('SECTION 3 — QGIS WFS layer creation')
    p(SEP2)

    if not feature_types:
        p('No feature types from section 1 — skipping')
        return

    try:
        from qgis.core import QgsVectorLayer
    except ImportError:
        p('QGIS not available — skipping')
        return

    # Pick test layers: first, last, and one with namespaced name if any
    picks = [feature_types[0]]
    if len(feature_types) > 1:
        picks.append(feature_types[-1])
    namespaced = [ft for ft in feature_types if ':' in ft['name']]
    if namespaced and namespaced[0] not in picks:
        picks.append(namespaced[0])

    # URI variants to try
    def make_uris(ft):
        name = ft['name']
        # Normalize CRS
        crs_raw = ft.get('crs', 'EPSG:4674')
        if 'EPSG' in crs_raw.upper():
            crs = 'EPSG:' + crs_raw.split(':')[-1].split('::')[-1]
        else:
            crs = 'EPSG:4674'
        return [
            # (label, uri)
            ('version=auto',
             f'typename={urllib.parse.quote(name, safe=":")}'
             f'&url={FUNAI_BASE}&version=auto&srsname={crs}'),
            ('version=2.0.0',
             f'typename={urllib.parse.quote(name, safe=":")}'
             f'&url={FUNAI_BASE}&version=2.0.0&srsname={crs}'),
            ('version=1.1.0',
             f'typename={urllib.parse.quote(name, safe=":")}'
             f'&url={FUNAI_BASE}&version=1.1.0&srsname={crs}'),
            ('version=1.0.0',
             f'typename={urllib.parse.quote(name, safe=":")}'
             f'&url={FUNAI_BASE}&version=1.0.0&srsname={crs}'),
            ('url-first order',
             f'url={FUNAI_BASE}'
             f'&typename={urllib.parse.quote(name, safe=":")}'
             f'&version=auto&srsname={crs}'),
            ('maxNumFeatures=5',
             f'typename={urllib.parse.quote(name, safe=":")}'
             f'&url={FUNAI_BASE}&version=auto&srsname={crs}&maxNumFeatures=5'),
        ]

    # Provider keys to try
    prov_keys = ['WFS', 'wfs']

    for ft in picks:
        p()
        p(SEP)
        p(f"Layer: {ft['name']}  |  {ft['title'][:60]}")
        p(SEP)
        for uri_label, uri in make_uris(ft):
            for pkey in prov_keys:
                label = f"[uri={uri_label}  prov='{pkey}']"
                p()
                p(f'  {label}')
                p(f'  URI: {uri[:120]}')
                try:
                    lyr = QgsVectorLayer(uri, ft['name'], pkey)
                    info = _layer_info(lyr)
                    _print_info(info, '    ')
                    if info.get('valid'):
                        p(f'  ✅ VALID — {info.get("feature_count","?")} features, '
                          f'{info.get("field_count","?")} fields, CRS={info.get("crs","?")}')
                        # Stop trying more variants for this layer if we got a valid one
                        break
                    else:
                        p('  ❌ INVALID')
                except Exception as exc:
                    p(f'  EXCEPTION: {exc}')
                    traceback.print_exc()
            else:
                # inner loop completed without break — try next uri variant
                continue
            break  # valid layer found for this feature type — move to next layer


# ── Section 4a: Raw network — WFS DescribeFeatureType ────────────────────────

def section_4a_describe_feature_type():
    p()
    p(SEP2)
    p('SECTION 4a — Raw network: WFS DescribeFeatureType (urllib)')
    p(SEP2)

    for version in ['2.0.0', '1.1.0', '1.0.0']:
        params = urllib.parse.urlencode({
            'SERVICE':  'WFS',
            'VERSION':  version,
            'REQUEST':  'DescribeFeatureType',
            'TYPENAME': 'Funai:aldeias_pontos',
        })
        url = f'{FUNAI_BASE}?{params}'
        p(f'DescribeFeatureType v{version}:')
        p(f'  {url}')
        code, text, err = _fetch(url)
        p(f'  HTTP {code}  |  err={err}')
        if text:
            p(f'  Response ({len(text)} chars): {text[:300]}')
        p()


# ── Section 8: QGIS QgsNetworkAccessManager — SSL test ───────────────────────

def section_8_qgis_network():
    p()
    p(SEP2)
    p('SECTION 8 — QGIS QgsNetworkAccessManager direct request (SSL check)')
    p(SEP2)

    try:
        from qgis.core import QgsNetworkAccessManager
        from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer
        from qgis.PyQt.QtNetwork import QNetworkRequest, QNetworkReply
    except ImportError:
        p('QGIS not available — skipping')
        return

    manager = QgsNetworkAccessManager.instance()
    if manager is None:
        p('QgsNetworkAccessManager.instance() returned None — skipping')
        return

    # Map QNetworkReply.NetworkError codes to names
    error_names = {
        0:  'NoError',
        1:  'ConnectionRefusedError',
        2:  'RemoteHostClosedError',
        3:  'HostNotFoundError',
        4:  'TimeoutError',
        5:  'OperationCanceledError',
        6:  'SslHandshakeFailedError',
        7:  'TemporaryNetworkFailureError',
        99: 'UnknownNetworkError',
        301: 'ContentAccessDenied',
    }

    # PyQt6 enum compat helpers
    def _enum_int(val):
        """Return integer value of a Qt enum in both PyQt5 and PyQt6."""
        try:
            return int(val)
        except TypeError:
            try:
                return val.value
            except AttributeError:
                return -1

    def _http_attr(reply):
        """Get HTTP status code attribute (handles PyQt5/6 enum differences)."""
        for attr_name in (
            'HttpStatusCodeAttribute',
        ):
            for ns in (
                lambda: getattr(QNetworkRequest.Attribute, attr_name),
                lambda: getattr(QNetworkRequest, attr_name),
            ):
                try:
                    return reply.attribute(ns())
                except Exception:  # nosec B110
                    pass
        return None

    def qgis_get(url_str, label):
        p(f'  [{label}]')
        p(f'  URL: {url_str}')
        try:
            req   = QNetworkRequest(QUrl(url_str))
            reply = manager.get(req)

            loop  = QEventLoop()
            timer = QTimer()
            timer.setSingleShot(True)
            reply.finished.connect(loop.quit)
            timer.timeout.connect(loop.quit)
            timer.start(15000)
            loop.exec()
            timer.stop()

            if reply.isRunning():
                reply.abort()
                p('  ⏳ Timed out after 15 s — QGIS could not reach the server')
                return

            code       = _http_attr(reply)
            error_enum = reply.error()
            error      = _enum_int(error_enum)
            ename      = error_names.get(error, f'code={error}  raw={error_enum}')
            data       = bytes(reply.readAll())

            p(f'  HTTP status: {code}')
            p(f'  QNetworkReply.error: {error} ({ename})')

            try:
                ssl_errs = reply.sslErrors()
                if ssl_errs:
                    p(f'  SSL errors ({len(ssl_errs)}):')
                    for e in ssl_errs:
                        p(f'    {e.errorString()}')
                else:
                    p('  SSL errors: none')
            except Exception as exc:
                p(f'  SSL check exception: {exc}')

            p(f'  Response size: {len(data)} bytes')
            if data:
                p(f'  First 300 bytes: {data[:300]}')
            else:
                p('  Response body: empty')

            if error == 6:
                p('  ❌ SSL HANDSHAKE FAILED — root cause confirmed')
            elif error == 0 and code and int(code) < 400:
                p('  ✅ QGIS network succeeded')
            elif error == 0 and not code:
                p('  ⚠ error=0 but no HTTP code — possible redirect or protocol issue')
            else:
                p(f'  ❌ QGIS network failed (error={ename}  http={code})')

        except Exception as exc:
            p(f'  EXCEPTION: {exc}')
            import traceback; traceback.print_exc()
        p()

    qgis_get(
        f'{FUNAI_BASE}?SERVICE=WFS&REQUEST=GetCapabilities',
        'FUNAI HTTPS GetCapabilities (uppercase SERVICE)'
    )
    qgis_get(
        f'{FUNAI_BASE}?service=wfs&request=GetCapabilities',
        'FUNAI HTTPS GetCapabilities (lowercase service)'
    )
    qgis_get(
        f'{FUNAI_BASE}?SERVICE=WFS&VERSION=1.1.0&REQUEST=DescribeFeatureType&TYPENAME=Funai:aldeias_pontos',
        'FUNAI HTTPS DescribeFeatureType v1.1.0'
    )
    # Try HTTP (not HTTPS) if server supports it
    http_base = FUNAI_BASE.replace('https://', 'http://', 1)
    qgis_get(
        f'{http_base}?SERVICE=WFS&REQUEST=GetCapabilities',
        'FUNAI HTTP (not HTTPS) GetCapabilities'
    )


# ── Section 4: Raw network — WFS GetFeature ───────────────────────────────────

def section_4_wfs_getfeature(feature_types):
    p()
    p(SEP2)
    p('SECTION 4 — Raw network: WFS GetFeature (first layer, 2 features)')
    p(SEP2)

    if not feature_types:
        p('No feature types — skipping')
        return

    ft = feature_types[0]
    name = ft['name']

    # Try both WFS 2.0 and 1.1 GetFeature
    for version, count_param, count_val in [
        ('2.0.0', 'count',       '2'),
        ('1.1.0', 'maxFeatures', '2'),
        ('1.0.0', 'maxFeatures', '2'),
    ]:
        params = urllib.parse.urlencode({
            'service':     'WFS',
            'request':     'GetFeature',
            'version':     version,
            'typename':    name,
            count_param:   count_val,
            'outputFormat': 'application/json',
        })
        url = f'{FUNAI_BASE}?{params}'
        p(f'GetFeature v{version}: {url}')
        code, text, err = _fetch(url)
        p(f'  HTTP {code}  |  err={err}')
        if text:
            p(f'  Response ({len(text)} chars): {text[:300]}')
        p()


# ── Section 5: QGIS WCS layer creation ───────────────────────────────────────

def section_5_wcs_layer():
    p()
    p(SEP2)
    p('SECTION 5 — QGIS WCS layer creation (FUNAI has empty WCS, testing URI builder)')
    p(SEP2)

    try:
        from qgis.core import QgsRasterLayer
    except ImportError:
        p('QGIS not available — skipping')
        return

    # FUNAI has no WCS coverages — test a known empty and also log what happens
    # when we try to create a WCS layer with a made-up identifier
    test_cases = [
        ('wcs',  f'identifier=test_coverage&url={FUNAI_BASE}&crs=EPSG:4674'),
        ('WCS',  f'identifier=test_coverage&url={FUNAI_BASE}&crs=EPSG:4674'),
        ('wcs',  f'identifier=test_coverage&url={FUNAI_BASE}&crs=EPSG:4674&version=1.1.1'),
    ]
    for pkey, uri in test_cases:
        p(f"  provider='{pkey}'  URI: {uri[:100]}")
        try:
            lyr = QgsRasterLayer(uri, 'test_wcs', pkey)
            info = _layer_info(lyr)
            _print_info(info, '    ')
        except Exception as exc:
            p(f'    EXCEPTION: {exc}')
        p()


# ── Section 3b: WFS async — does the layer become valid after processEvents? ──

def section_3b_wfs_async(feature_types):
    p()
    p(SEP2)
    p('SECTION 3b — WFS async: wait up to 30 s for layer to become valid')
    p(SEP2)

    if not feature_types:
        p('No feature types — skipping')
        return None

    try:
        from qgis.PyQt.QtWidgets import QApplication
        from qgis.core import QgsVectorLayer
    except ImportError:
        p('QGIS not available — skipping')
        return None

    ft = feature_types[0]
    name = ft['name']
    crs_raw = ft.get('crs', 'EPSG:4674')
    crs = 'EPSG:' + crs_raw.split(':')[-1].split('::')[-1] if 'EPSG' in crs_raw.upper() else 'EPSG:4674'

    uri = (
        f'typename={urllib.parse.quote(name, safe=":")}'
        f'&url={FUNAI_BASE}&version=auto&srsname={crs}'
    )
    p(f'Layer: {name}')
    p(f'URI: {uri}')
    p('Creating layer with WFS provider…')
    lyr = QgsVectorLayer(uri, name, 'WFS')

    dp = lyr.dataProvider()
    dp_caps = int(dp.capabilities()) if dp else 0
    p(f'Immediately after construction: isValid={lyr.isValid()}  dp_caps={dp_caps}  crs={lyr.crs().authid() if lyr.crs() else "?"}')

    if lyr.isValid():
        p('Already valid — no async wait needed.')
        return lyr

    if dp_caps == 0:
        p('dp_caps=0: provider failed to parse URI — cannot proceed.')
        return None

    p(f'Not yet valid. Waiting up to 30 s for async init (processEvents loop)…')
    import time
    deadline = time.monotonic() + 30
    checks = 0
    while not lyr.isValid() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.1)
        checks += 1
        if checks % 20 == 0:
            elapsed = 30 - (deadline - time.monotonic())
            p(f'  {elapsed:.1f}s elapsed — isValid={lyr.isValid()}  '
              f'crs={lyr.crs().authid() if lyr.crs() else "?"}  '
              f'fields={lyr.fields().count() if lyr.isValid() else 0}')

    elapsed_total = 30 - max(0, deadline - time.monotonic())
    p(f'After {elapsed_total:.1f}s: isValid={lyr.isValid()}  '
      f'crs={lyr.crs().authid() if lyr.crs() else "?"}  '
      f'fields={lyr.fields().count() if lyr.isValid() else "?"}  '
      f'features={lyr.dataProvider().featureCount() if lyr.isValid() else "?"}')

    if lyr.isValid():
        p('✅ Layer became valid after async wait — QGIS 4 WFS is async confirmed.')
    else:
        p('❌ Layer still invalid after 30 s — may be a network/server issue.')
        info = _layer_info(lyr)
        _print_info(info, '  ')

    return lyr if lyr.isValid() else None


# ── Section 6: WFS download — save first valid layer as GeoPackage ────────────

def section_6_wfs_download(feature_types):
    p()
    p(SEP2)
    p('SECTION 6 — WFS download: save first valid layer as GeoPackage')
    p(SEP2)

    if not feature_types:
        p('No feature types — skipping')
        return

    try:
        from qgis.core import (
            QgsVectorLayer, QgsVectorFileWriter,
            QgsCoordinateTransformContext,
        )
    except ImportError:
        p('QGIS not available — skipping')
        return

    ft = feature_types[0]
    name = ft['name']
    crs_raw = ft.get('crs', 'EPSG:4674')
    crs = 'EPSG:' + crs_raw.split(':')[-1].split('::')[-1] if 'EPSG' in crs_raw.upper() else 'EPSG:4674'

    # Build URI with maxNumFeatures to keep download fast
    uri = (
        f'typename={urllib.parse.quote(name, safe=":")}'
        f'&url={FUNAI_BASE}&version=auto&srsname={crs}&maxNumFeatures=5'
    )
    p(f'Layer: {name}')
    p(f'URI (maxNumFeatures=5): {uri}')

    lyr = None
    for pkey in ('WFS', 'wfs'):
        lyr = QgsVectorLayer(uri, name, pkey)
        if lyr.isValid():
            p(f"✅ Layer valid with provider='{pkey}'")
            break
        p(f"  ❌ provider='{pkey}': invalid")
        info = _layer_info(lyr)
        _print_info(info, '  ')

    if lyr is None or not lyr.isValid():
        p('Cannot proceed with download — no valid layer')
        return

    # Write to temp GeoPackage
    out_path = os.path.join(tempfile.gettempdir(), 'test_funai_wfs_download.gpkg')
    p(f'Output: {out_path}')

    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName   = 'GPKG'
    opts.fileEncoding = 'UTF-8'

    p('Saving…')
    try:
        result, err_msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
            lyr, out_path, QgsCoordinateTransformContext(), opts)
    except (AttributeError, TypeError):
        result, err_msg = QgsVectorFileWriter.writeAsVectorFormatV2(
            lyr, out_path, QgsCoordinateTransformContext(), opts)

    p(f'writeAsVectorFormat result code: {result}')
    p(f'writeAsVectorFormat error msg:   {err_msg!r}')
    if result == QgsVectorFileWriter.NoError:
        size = os.path.getsize(out_path) if os.path.exists(out_path) else -1
        p(f'✅ GeoPackage written — {size} bytes at {out_path}')
    else:
        p(f'❌ Write failed (code={result}): {err_msg}')


# ── Section 7: CMR (second FUNAI server) WFS ─────────────────────────────────

def section_7_cmr_wfs():
    p()
    p(SEP2)
    p('SECTION 7 — CMR (cmr.funai.gov.br) WFS network check')
    p(SEP2)

    p(f'URL: {CMR_WFS_CAP}')
    code, text, err = _fetch(CMR_WFS_CAP, 'CMR-WFS')
    p(f'HTTP status: {code}  |  error: {err}')
    if text is None:
        return
    p(f'Response size: {len(text)} chars')

    # Count feature types
    ft_count = sum(
        1 for elem in ET.fromstring(text).iter()  # nosec B314
        if (elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag) == 'FeatureType'
    )
    p(f'FeatureType elements: {ft_count}')

    # Try QGIS layer with first feature type
    if ft_count > 0:
        try:
            from qgis.core import QgsVectorLayer
            first_name_el = next(
                (child for elem in ET.fromstring(text).iter()  # nosec B314
                 if (elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag) == 'FeatureType'
                 for child in elem
                 if (child.tag.split('}')[-1] if '}' in child.tag else child.tag) == 'Name'),
                None
            )
            if first_name_el is not None and first_name_el.text:
                fn = first_name_el.text.strip()
                uri = (f'typename={urllib.parse.quote(fn, safe=":")}'
                       f'&url={CMR_BASE}&version=auto&srsname=EPSG:4674')
                p(f"Testing QgsVectorLayer('{fn}', 'WFS'):")
                lyr = QgsVectorLayer(uri, fn, 'WFS')
                info = _layer_info(lyr)
                _print_info(info, '  ')
                if not lyr.isValid():
                    p("  Retrying with 'wfs'…")
                    lyr2 = QgsVectorLayer(uri, fn, 'wfs')
                    info2 = _layer_info(lyr2)
                    _print_info(info2, '  ')
        except Exception as exc:
            p(f'EXCEPTION in CMR layer test: {exc}')
            traceback.print_exc()


# ── Section 9: Capture QgsMessageLog during WFS layer creation ───────────────

def section_9_message_log():
    p()
    p(SEP2)
    p('SECTION 9 — Capture QgsMessageLog during WFS layer creation')
    p(SEP2)

    try:
        from qgis.core import QgsApplication, QgsVectorLayer
        from qgis.PyQt.QtWidgets import QApplication
    except ImportError:
        p('QGIS not available — skipping')
        return

    uri = (
        f'typename=Funai:aldeias_pontos'
        f'&url={FUNAI_BASE}'
        f'&version=auto'
        f'&srsname=EPSG:4674'
    )

    captured = []

    def on_message(message, tag, level):
        captured.append((tag, level, message))

    log_instance = QgsApplication.instance().messageLog()
    if log_instance is None:
        p('messageLog() returned None')
        return

    p('Connecting to QgsMessageLog.messageReceived…')
    try:
        log_instance.messageReceived.connect(on_message)
    except Exception as exc:
        p(f'Could not connect to messageReceived: {exc}')
        return

    p(f'Creating QgsVectorLayer(uri, "test", "WFS")…')
    lyr = QgsVectorLayer(uri, 'test_wfs_log', 'WFS')
    p(f'  → isValid immediately: {lyr.isValid()}')

    p('Processing events for 8 s to let provider do its work…')
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.05)

    try:
        log_instance.messageReceived.disconnect(on_message)
    except Exception:  # nosec B110
        pass

    p(f'isValid after 8 s: {lyr.isValid()}')
    p(f'Total log messages captured: {len(captured)}')
    p()

    if not captured:
        p('  ⚠ No messages captured — WFS provider is completely silent')
        p('  (this rules out QgsMessageLog as the error channel)')
    else:
        for tag, level, msg in captured:
            p(f'  [{tag}] level={level}:')
            p(f'    {msg[:300]}')
    p()

    # Also check: does QgsApplication.instance().messageLog() have a
    # method to retrieve stored messages?
    for method_name in ('messages', 'logMessages', 'recentMessages'):
        try:
            m = getattr(log_instance, method_name, None)
            if m is not None:
                p(f'  log.{method_name}(): {m}')
        except Exception:  # nosec B110
            pass


# ── Section 10: Test WFS with a known-good public server ─────────────────────

def section_10_known_good_wfs():
    p()
    p(SEP2)
    p('SECTION 10 — WFS provider sanity check with known-good server')
    p(SEP2)

    try:
        from qgis.core import QgsVectorLayer
    except ImportError:
        p('QGIS not available — skipping')
        return

    # GeoServer public demo — well-known stable WFS endpoint
    DEMO_BASE = 'https://ahocevar.com/geoserver/wfs'
    DEMO_LAYER = 'ne:ne_10m_admin_0_countries'

    uri = (
        f'typename={urllib.parse.quote(DEMO_LAYER, safe=":")}'
        f'&url={DEMO_BASE}'
        f'&version=2.0.0'
        f'&srsname=EPSG:4326'
    )
    p(f'Server: {DEMO_BASE}')
    p(f'Layer:  {DEMO_LAYER}')
    p(f'URI:    {uri[:120]}')

    # First verify it's reachable via urllib
    test_url = f'{DEMO_BASE}?SERVICE=WFS&REQUEST=GetCapabilities'
    code, text, err = _fetch(test_url)
    p(f'urllib GetCapabilities: HTTP {code}  err={err}')
    if code != 200:
        p('  Server unreachable via urllib — skipping QGIS test')
        return

    p('Creating QgsVectorLayer…')
    lyr = QgsVectorLayer(uri, DEMO_LAYER, 'WFS')
    info = _layer_info(lyr)
    _print_info(info, '  ')

    if lyr.isValid():
        p('✅ Known-good server WFS works in QGIS — WFS provider is functional')
        p('   → FUNAI WFS failure is specific to that server/config')
    else:
        p('❌ Known-good server WFS also fails — WFS provider is broken in this QGIS build')
        p('   → This is a QGIS 4 WFS provider bug, not FUNAI-specific')


# ── Section 11: OGR WFS driver (bypasses broken QGIS WFS provider) ───────────

def section_11_ogr_wfs():
    p()
    p(SEP2)
    p('SECTION 11 — OGR WFS driver (GDAL, bypasses QGIS WFS provider)')
    p(SEP2)

    try:
        from qgis.core import QgsVectorLayer
    except ImportError:
        p('QGIS not available — skipping')
        return

    base = FUNAI_BASE
    layer_name = 'Funai:aldeias_pontos'

    # GDAL WFS driver URI — uses "WFS:" prefix with provider='ogr'
    for version in ('1.1.0', '2.0.0', '1.0.0'):
        cap_url = (
            f'WFS:{base}'
            f'?SERVICE=WFS&VERSION={version}&REQUEST=GetCapabilities'
        )
        # With layername sub-dataset
        uri_layername = f'{cap_url}|layername={layer_name}'
        p(f'  version={version}  uri: {uri_layername[:120]}')
        try:
            lyr = QgsVectorLayer(uri_layername, layer_name, 'ogr')
            info = _layer_info(lyr)
            _print_info(info, '    ')
            if lyr.isValid():
                p(f'  ✅ OGR WFS v{version} VALID — '
                  f'{info.get("feature_count","?")} features, '
                  f'{info.get("field_count","?")} fields, CRS={info.get("crs","?")}')
                return   # found a working version
            else:
                p(f'  ❌ OGR WFS v{version} invalid')
        except Exception as exc:
            p(f'  EXCEPTION v{version}: {exc}')
        p()

    # Try without layername (list sublayers)
    p('  Trying WFS root URL (no layername) to list sublayers:')
    root_uri = f'WFS:{base}?SERVICE=WFS&VERSION=1.1.0&REQUEST=GetCapabilities'
    try:
        lyr = QgsVectorLayer(root_uri, 'wfs_root', 'ogr')
        p(f'    isValid: {lyr.isValid()}')
        try:
            subs = lyr.dataProvider().subLayers() if lyr.dataProvider() else []
            p(f'    sublayers ({len(subs)}):')
            for s in subs[:5]:
                p(f'      {s}')
        except Exception as exc:
            p(f'    sublayers exception: {exc}')
    except Exception as exc:
        p(f'  root EXCEPTION: {exc}')


# ── Section 12: urllib GeoJSON → temp file → OGR (guaranteed workaround) ─────

def section_12_geojson_temp():
    p()
    p(SEP2)
    p('SECTION 12 — urllib GetFeature GeoJSON → temp file → OGR load')
    p(SEP2)

    try:
        from qgis.core import (
            QgsVectorLayer, QgsVectorFileWriter,
            QgsCoordinateTransformContext, QgsProject,
        )
    except ImportError:
        p('QGIS not available — skipping')
        return

    import tempfile, os

    layer_name = 'Funai:aldeias_pontos'
    safe_name  = 'Funai_aldeias_pontos'

    # Download all features as GeoJSON via urllib (v1.1.0 confirmed working)
    getfeature_url = (
        f'{FUNAI_BASE}'
        f'?SERVICE=WFS&VERSION=1.1.0&REQUEST=GetFeature'
        f'&TYPENAME={urllib.parse.quote(layer_name, safe=":")}'
        f'&outputFormat=application%2Fjson'
        f'&maxFeatures=20'     # limit for test
    )
    p(f'GetFeature URL (maxFeatures=20): {getfeature_url}')

    code, text, err = _fetch(getfeature_url)
    p(f'HTTP {code}  |  err={err}  |  size={len(text) if text else 0}')
    if not text or code != 200:
        p('Download failed — cannot proceed')
        return

    # Save to temp file
    tmp = tempfile.NamedTemporaryFile(
        suffix='.geojson', delete=False,
        mode='w', encoding='utf-8',
    )
    tmp.write(text)
    tmp.close()
    p(f'Saved to: {tmp.name}  ({os.path.getsize(tmp.name)} bytes)')

    # Load with OGR provider
    lyr = QgsVectorLayer(tmp.name, layer_name, 'ogr')
    info = _layer_info(lyr)
    p(f'OGR load — isValid: {lyr.isValid()}')
    _print_info(info, '  ')

    if not lyr.isValid():
        p('❌ GeoJSON temp file failed to load with OGR')
        return

    p(f'✅ GeoJSON temp file loaded — {info["feature_count"]} features, '
      f'{info["field_count"]} fields, CRS={info["crs"]}')

    # Write to GeoPackage
    gpkg_path = os.path.join(tempfile.gettempdir(), f'{safe_name}_test.gpkg')
    p(f'Writing to GeoPackage: {gpkg_path}')
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName   = 'GPKG'
    opts.fileEncoding = 'UTF-8'
    try:
        result, err_msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
            lyr, gpkg_path, QgsCoordinateTransformContext(), opts)
    except (AttributeError, TypeError):
        result, err_msg = QgsVectorFileWriter.writeAsVectorFormatV2(
            lyr, gpkg_path, QgsCoordinateTransformContext(), opts)
    p(f'Write result: {result}  err: {err_msg!r}')
    if result == QgsVectorFileWriter.NoError:
        size = os.path.getsize(gpkg_path) if os.path.exists(gpkg_path) else -1
        p(f'✅ GeoPackage saved — {size} bytes at {gpkg_path}')
    else:
        p(f'❌ GeoPackage write failed: {err_msg}')

    # Clean up temp GeoJSON
    try:
        os.unlink(tmp.name)
    except Exception:  # nosec B110
        pass


# ── Section ANA-1: Raw network — ANA WMS GetCapabilities ─────────────────────

ANA_WMS_BASE = 'https://www.snirh.gov.br/arcgis/services/INDE/Camadas/MapServer/WMSServer'
ANA_WMS_CAP  = (
    'https://www.snirh.gov.br/arcgis/services/INDE/Camadas/MapServer/WMSServer'
    '?service=wms&request=GetCapabilities&version=1.3.0'
)

def section_ana1_network():
    p()
    p(SEP2)
    p('SECTION ANA-1 — Raw network: ANA WMS GetCapabilities (urllib)')
    p(SEP2)
    p(f'URL: {ANA_WMS_CAP}')
    code, text, err = _fetch(ANA_WMS_CAP)
    p(f'HTTP status: {code}  |  err: {err}')
    if not text:
        return []
    p(f'Response size: {len(text)} chars')

    try:
        root = ET.fromstring(text)  # nosec B314
        p(f'XML root tag: {root.tag}')
    except Exception as exc:
        p(f'XML parse error: {exc}')
        p(f'First 500 chars: {text[:500]}')
        return []

    # Parse WMS layers
    layers = []
    ns = 'http://www.opengis.net/wms' if root.tag.startswith('{') else ''
    def tag(t):
        return f'{{{ns}}}{t}' if ns else t
    for elem in root.iter(tag('Layer')):
        name_el  = elem.find(tag('Name'))
        title_el = elem.find(tag('Title'))
        if name_el is not None and name_el.text:
            layers.append({
                'name':  name_el.text.strip(),
                'title': (title_el.text or name_el.text).strip() if title_el is not None else name_el.text.strip(),
            })

    # Deduplicate
    seen, unique = set(), []
    for lyr in layers:
        if lyr['name'] not in seen:
            seen.add(lyr['name'])
            unique.append(lyr)

    p(f'WMS layers found: {len(unique)}')
    for i, l in enumerate(unique[:10]):
        p(f"  [{i+1:02d}] {l['name']}  |  {l['title'][:60]}")
    if len(unique) > 10:
        p(f'  … and {len(unique)-10} more')
    return unique


def section_ana2_qgis_network():
    p()
    p(SEP2)
    p('SECTION ANA-2 — QGIS QgsNetworkAccessManager (SSL check)')
    p(SEP2)
    try:
        from qgis.core import QgsNetworkAccessManager
        from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer
        from qgis.PyQt.QtNetwork import QNetworkRequest
    except ImportError:
        p('QGIS not available — skipping'); return

    manager = QgsNetworkAccessManager.instance()

    def _qget(url_str, label):
        p(f'  [{label}]  {url_str[:100]}')
        try:
            req   = QNetworkRequest(QUrl(url_str))
            reply = manager.get(req)
            loop, timer = QEventLoop(), QTimer()
            timer.setSingleShot(True)
            reply.finished.connect(loop.quit)
            timer.timeout.connect(loop.quit)
            timer.start(15000)
            loop.exec(); timer.stop()
            if reply.isRunning():
                reply.abort(); p('  ⏳ Timed out'); return
            err_obj = reply.error()
            try:    err_int = err_obj.value
            except Exception: err_int = int(err_obj)  # nosec B110
            code = None
            for attr in ('Attribute.HttpStatusCodeAttribute', 'HttpStatusCodeAttribute'):
                try:
                    parts = attr.split('.')
                    obj = QNetworkRequest
                    for p_ in parts: obj = getattr(obj, p_)
                    code = reply.attribute(obj); break
                except Exception: pass  # nosec B110
            data = bytes(reply.readAll())
            p(f'    HTTP {code}  error={err_int}  size={len(data)} bytes')
            if data: p(f'    First 200: {data[:200]}')
            if err_int == 0 and code and int(code) < 400:
                p('    ✅ QGIS network succeeded')
            else:
                p(f'    ❌ QGIS network failed')
        except Exception as exc:
            p(f'    EXCEPTION: {exc}')
        p()

    _qget(ANA_WMS_CAP,  'ANA WMS GetCapabilities')
    _qget(f'{ANA_WMS_BASE}?service=wms&request=GetCapabilities', 'ANA WMS GetCapabilities (no version)')


def section_ana3_wms_layer(wms_layers):
    p()
    p(SEP2)
    p('SECTION ANA-3 — QGIS WMS layer creation')
    p(SEP2)
    if not wms_layers:
        p('No layers from ANA-1 — skipping'); return []

    try:
        from qgis.core import QgsRasterLayer
    except ImportError:
        p('QGIS not available — skipping'); return []

    valid_layers = []
    picks = [wms_layers[0]]
    if len(wms_layers) > 1: picks.append(wms_layers[len(wms_layers)//2])
    if len(wms_layers) > 2: picks.append(wms_layers[-1])

    for lyr_def in picks:
        name  = lyr_def['name']
        title = lyr_def['title']
        # WMS URI format (same as plugin)
        uri = (
            f'IgnoreGetMapUrl=1'
            f'&crs=EPSG:4674'
            f'&dpiMode=7'
            f'&featureCount=10'
            f'&format=image/png'
            f'&layers={urllib.parse.quote(name, safe=":")}'
            f'&styles'
            f'&url={ANA_WMS_BASE}'
        )
        p(f'  Layer: {name}  |  {title[:50]}')
        p(f'  URI: {uri[:120]}')
        qlyr = QgsRasterLayer(uri, title, 'wms')
        info = _layer_info(qlyr)
        _print_info(info, '    ')
        if qlyr.isValid():
            p(f'  ✅ VALID — CRS={info.get("crs","?")}')
            valid_layers.append((qlyr, lyr_def))
        else:
            p(f'  ❌ INVALID — {info.get("dp_error_summary","no error")}')
        p()

    return valid_layers


def section_ana4_download(valid_layers):
    p()
    p(SEP2)
    p('SECTION ANA-4 — Download WMS layer as GeoTIFF')
    p(SEP2)
    if not valid_layers:
        p('No valid layers from ANA-3 — skipping'); return

    try:
        from qgis.core import (
            QgsRasterFileWriter, QgsRasterPipe,
            QgsCoordinateTransform, QgsProject,
        )
        from qgis.PyQt.QtWidgets import QApplication
    except ImportError:
        p('QGIS not available — skipping'); return

    import tempfile, os

    qlyr, lyr_def = valid_layers[0]
    name  = lyr_def['name']
    safe  = ''.join(c if c.isalnum() or c in '-_' else '_' for c in name)
    out   = os.path.join(tempfile.gettempdir(), f'ana_test_{safe}.tif')

    p(f'Layer: {name}')
    p(f'Output: {out}')

    # Use layer extent (full layer, no canvas needed)
    extent = qlyr.extent()
    p(f'Layer extent: {extent.toString()}')
    p(f'Layer CRS: {qlyr.crs().authid()}')

    if not extent.isFinite() or extent.isEmpty():
        p('❌ Layer extent is empty/invalid — cannot export GeoTIFF')
        return

    # Cap at 512x512 for test
    aspect = extent.width() / max(extent.height(), 1e-10)
    if aspect >= 1:
        cols, rows = 512, max(1, int(512 / aspect))
    else:
        rows, cols = 512, max(1, int(512 * aspect))

    p(f'Export size: {cols} x {rows} px')

    pipe = QgsRasterPipe()
    if not pipe.set(qlyr.dataProvider().clone()):
        p('❌ Could not create raster pipe'); return

    writer = QgsRasterFileWriter(out)
    writer.setOutputFormat('GTiff')
    p('Writing GeoTIFF…')
    QApplication.processEvents()

    error = writer.writeRaster(pipe, cols, rows, extent, qlyr.crs())
    # Handle PyQt6 enum for NoError
    try:
        no_err = QgsRasterFileWriter.WriterError.NoError
    except AttributeError:
        no_err = QgsRasterFileWriter.NoError

    if error == no_err:
        size = os.path.getsize(out) if os.path.exists(out) else -1
        p(f'✅ GeoTIFF saved — {size} bytes at {out}')
    else:
        p(f'❌ Write failed (error code: {error})')


# ── ANATEL endpoints ──────────────────────────────────────────────────────────

ANATEL_BASE    = 'https://sistemas.anatel.gov.br/geoserver/ows'
ANATEL_WMS_CAP = f'{ANATEL_BASE}?service=wms&request=GetCapabilities&version=1.3.0'
ANATEL_WFS_CAP = f'{ANATEL_BASE}?service=wfs&request=GetCapabilities&version=2.0.0'
ANATEL_WCS_CAP = f'{ANATEL_BASE}?service=wcs&request=GetCapabilities&version=1.1.1'


# ── Section ANATEL-1: Raw network — all three services ────────────────────────

def section_anatel1_network():
    p()
    p(SEP2)
    p('SECTION ANATEL-1 — Raw network: WMS + WFS + WCS GetCapabilities')
    p(SEP2)

    results = {}
    for svc, url, count_fn in (
        ('WMS', ANATEL_WMS_CAP, _count_wms_layers),
        ('WFS', ANATEL_WFS_CAP, _count_wfs_types),
        ('WCS', ANATEL_WCS_CAP, _count_wcs_coverages),
    ):
        p(f'  [{svc}] {url}')
        code, text, err = _fetch(url)
        if err or code != 200:
            p(f'  ❌ HTTP {code}  err: {err}')
            results[svc] = None
            continue
        p(f'  ✅ HTTP {code}  {len(text)} chars')
        count = count_fn(text)
        p(f'  Itens encontrados: {count}')
        results[svc] = (text, count)
        p()

    return results


def _count_wms_layers(text):
    try:
        root = ET.fromstring(text)  # nosec B314
        ns = (root.tag.split('}')[0] + '}') if root.tag.startswith('{') else ''
        names = set()
        for elem in root.iter(f'{ns}Layer'):
            n = elem.find(f'{ns}Name')
            if n is not None and n.text and n.text.strip():
                names.add(n.text.strip())
        return len(names)
    except Exception:
        return -1


def _count_wfs_types(text):
    try:
        root = ET.fromstring(text)  # nosec B314
        return sum(
            1 for e in root.iter()
            if (e.tag.split('}')[-1] if '}' in e.tag else e.tag) == 'FeatureType'
        )
    except Exception:
        return -1


def _count_wcs_coverages(text):
    try:
        root = ET.fromstring(text)  # nosec B314
        return sum(
            1 for e in root.iter()
            if (e.tag.split('}')[-1] if '}' in e.tag else e.tag)
            in ('CoverageSummary', 'CoverageId', 'Identifier', 'CoverageOfferingBrief')
        )
    except Exception:
        return -1


# ── Section ANATEL-2: Parse and pick sample layers ────────────────────────────

def section_anatel2_parse(net_results):
    p()
    p(SEP2)
    p('SECTION ANATEL-2 — Parse layers from each service')
    p(SEP2)

    picks = {}

    # WMS
    if net_results.get('WMS'):
        text, _ = net_results['WMS']
        try:
            root = ET.fromstring(text)  # nosec B314
            ns = (root.tag.split('}')[0] + '}') if root.tag.startswith('{') else ''
            layers = []
            for elem in root.iter(f'{ns}Layer'):
                n = elem.find(f'{ns}Name')
                t = elem.find(f'{ns}Title')
                if n is not None and n.text and n.text.strip():
                    layers.append({'name': n.text.strip(),
                                   'title': (t.text or n.text).strip() if t is not None else n.text.strip()})
            seen, unique = set(), []
            for lyr in layers:
                if lyr['name'] not in seen:
                    seen.add(lyr['name']); unique.append(lyr)
            p(f'WMS: {len(unique)} camadas únicas')
            for i, l in enumerate(unique[:5]):
                p(f"  [{i+1}] {l['name']}  |  {l['title'][:60]}")
            if len(unique) > 5:
                p(f'  … e mais {len(unique)-5}')
            picks['WMS'] = unique[:3]
        except Exception as exc:
            p(f'WMS parse error: {exc}')

    # WFS
    if net_results.get('WFS'):
        text, _ = net_results['WFS']
        try:
            root = ET.fromstring(text)  # nosec B314
            types = []
            for elem in root.iter():
                local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                if local == 'FeatureType':
                    name_el = next(
                        (c for c in elem
                         if (c.tag.split('}')[-1] if '}' in c.tag else c.tag) == 'Name'),
                        None)
                    crs_el = next(
                        (c for c in elem
                         if (c.tag.split('}')[-1] if '}' in c.tag else c.tag) in ('DefaultCRS','DefaultSRS')),
                        None)
                    if name_el is not None and name_el.text:
                        types.append({'name': name_el.text.strip(),
                                      'crs': (crs_el.text or 'EPSG:4674').strip() if crs_el is not None else 'EPSG:4674'})
            p(f'\nWFS: {len(types)} feature types')
            for i, t in enumerate(types[:5]):
                p(f"  [{i+1}] {t['name']}  CRS: {t['crs']}")
            if len(types) > 5:
                p(f'  … e mais {len(types)-5}')
            picks['WFS'] = types[:2]
        except Exception as exc:
            p(f'WFS parse error: {exc}')

    # WCS
    if net_results.get('WCS'):
        text, count = net_results['WCS']
        p(f'\nWCS: {count} coverages')
        if count == 0:
            p('  → Sem coverages publicadas')

    return picks


# ── Section ANATEL-3: QGIS layer virtualization ───────────────────────────────

def section_anatel3_virtualize(picks):
    p()
    p(SEP2)
    p('SECTION ANATEL-3 — QGIS layer virtualization (WMS + WFS)')
    p(SEP2)

    try:
        from qgis.core import QgsRasterLayer, QgsVectorLayer
    except ImportError:
        p('QGIS não disponível — pulando'); return {}

    valid = {}

    # WMS
    for lyr_def in picks.get('WMS', []):
        name  = lyr_def['name']
        title = lyr_def['title']
        uri = (
            f'IgnoreGetMapUrl=1&crs=EPSG:4674&dpiMode=7&featureCount=10'
            f'&format=image/png&layers={urllib.parse.quote(name, safe=":")}'
            f'&styles&url={ANATEL_BASE}'
        )
        p(f'  WMS [{name}]:')
        qlyr = QgsRasterLayer(uri, title, 'wms')
        if not qlyr.isValid():
            # GDAL WMS XML fallback
            import tempfile, os as _os
            xml = (
                '<GDAL_WMS><Service name="WMS"><Version>1.3.0</Version>'
                f'<ServerUrl>{ANATEL_BASE}?</ServerUrl>'
                f'<Layers>{name}</Layers>'
                '<CRS>EPSG:4326</CRS><ImageFormat>image/png</ImageFormat>'
                '<Transparent>TRUE</Transparent></Service>'
                '<DataWindow><UpperLeftX>-180</UpperLeftX><UpperLeftY>90</UpperLeftY>'
                '<LowerRightX>180</LowerRightX><LowerRightY>-90</LowerRightY>'
                '<SizeX>512</SizeX><SizeY>512</SizeY></DataWindow>'
                '<BandsCount>4</BandsCount></GDAL_WMS>'
            )
            tmp = tempfile.NamedTemporaryFile(suffix='.xml', delete=False, mode='w')
            tmp.write(xml); tmp.close()
            qlyr = QgsRasterLayer(tmp.name, title, 'gdal')
            try: _os.unlink(tmp.name)
            except Exception: pass  # nosec B110
            p(f'    → provider nativo falhou, tentou GDAL WMS')
        info = _layer_info(qlyr)
        _print_info(info, '    ')
        if qlyr.isValid():
            p(f'    ✅ válida')
            valid.setdefault('WMS', []).append((qlyr, lyr_def))
        else:
            p(f'    ❌ inválida')
        p()

    # WFS — nativo + OGR fallback
    for ft in picks.get('WFS', []):
        name = ft['name']
        crs_raw = ft.get('crs', 'EPSG:4674')
        crs = 'EPSG:' + crs_raw.split(':')[-1].split('::')[-1] if 'EPSG' in crs_raw.upper() else 'EPSG:4674'
        uri = (
            f'typename={urllib.parse.quote(name, safe=":")}'
            f'&url={ANATEL_BASE}&version=auto&srsname={crs}'
        )
        p(f'  WFS [{name}]:')
        vlyr = QgsVectorLayer(uri, name, 'WFS')
        if not vlyr.isValid():
            vlyr = QgsVectorLayer(uri, name, 'wfs')
        used_ogr = False
        if not vlyr.isValid():
            dp = vlyr.dataProvider()
            if dp is not None and int(dp.capabilities()) > 0:
                ogr_uri = (
                    f'WFS:{ANATEL_BASE}'
                    f'?SERVICE=WFS&VERSION=1.1.0&REQUEST=GetCapabilities'
                    f'|layername={name}'
                )
                vlyr = QgsVectorLayer(ogr_uri, name, 'ogr')
                used_ogr = True
                p(f'    → provider nativo falhou (dp_caps>0), tentou OGR')
        info = _layer_info(vlyr)
        _print_info(info, '    ')
        if vlyr.isValid():
            p(f'    ✅ válida  {"(OGR)" if used_ogr else "(nativo)"}  '
              f'{info.get("feature_count","?")} feições')
            valid.setdefault('WFS', []).append((vlyr, ft))
        else:
            p(f'    ❌ inválida')
        p()

    return valid


# ── Section ANATEL-4: Download WFS → GeoPackage ───────────────────────────────

def section_anatel4_download(valid):
    p()
    p(SEP2)
    p('SECTION ANATEL-4 — Download WFS → GeoPackage')
    p(SEP2)

    wfs_layers = valid.get('WFS', [])
    if not wfs_layers:
        p('Nenhuma camada WFS válida — pulando'); return

    try:
        from qgis.core import (
            QgsVectorFileWriter, QgsCoordinateTransformContext,
        )
    except ImportError:
        p('QGIS não disponível — pulando'); return

    vlyr, ft = wfs_layers[0]
    name = ft['name']
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in name)
    out  = os.path.join(tempfile.gettempdir(), f'anatel_{safe}.gpkg')

    p(f'Camada: {name}')
    p(f'Saída:  {out}')

    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName   = 'GPKG'
    opts.fileEncoding = 'UTF-8'

    p('Salvando…')
    try:
        result, err_msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
            vlyr, out, QgsCoordinateTransformContext(), opts)
    except (AttributeError, TypeError):
        result, err_msg = QgsVectorFileWriter.writeAsVectorFormatV2(
            vlyr, out, QgsCoordinateTransformContext(), opts)

    p(f'Resultado: {result}  erro: {err_msg!r}')
    if result == QgsVectorFileWriter.NoError:
        size = os.path.getsize(out) if os.path.exists(out) else -1
        p(f'✅ GeoPackage salvo — {size} bytes em {out}')
    else:
        p(f'❌ Falha ao salvar (código {result}): {err_msg}')


# ── Main ──────────────────────────────────────────────────────────────────────

def run_all():
    p(SEP2)
    p('  RTH PROJECT — ANATEL OGC Diagnostic Test')
    p('  Running from: ' + os.path.abspath(__file__) if '__file__' in dir() else '  (console)')
    p(SEP2)

    net     = section_anatel1_network()
    picks   = section_anatel2_parse(net)
    valid   = section_anatel3_virtualize(picks)
    section_anatel4_download(valid)

    p()
    p(SEP2)
    p('  DIAGNOSTIC COMPLETE')
    p(SEP2)


if __name__ == '__main__':
    run_all()
