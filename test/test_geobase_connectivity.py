# -*- coding: utf-8 -*-
"""
test_geobase_connectivity.py
────────────────────────────────────────────────────────────────────────────
Testa a conectividade de todos os órgãos do catálogo brazil_geobase.

Roda do console Python do QGIS (só urllib — sem criar camadas, sem crash):
    exec(open(r'C:/Users/nohti/Desktop/rth_project/test/test_geobase_connectivity.py').read())

Ou linha de comando Python normal:
    python test/test_geobase_connectivity.py
────────────────────────────────────────────────────────────────────────────
"""
import json
import os
import ssl
import time
import urllib.error
import urllib.request

_SSL_NO_VERIFY = frozenset({'idem.dhn.mar.mil.br'})

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # noqa: S405

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE    = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else r'C:\Users\nohti\Desktop\rth_project\test'
_CATALOG = os.path.join(_HERE, '..', 'tools', 'brazil_geobase', 'brazil_geobase_catalog.json')

TIMEOUT  = 20   # seconds per request
SEP      = '─' * 76
SEP2     = '═' * 76

# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch(url):
    """GET url → (http_code, text, elapsed_s, error_str).
    SSL verification is skipped for hosts in _SSL_NO_VERIFY."""
    t0 = time.monotonic()
    try:
        hostname = url.split('/')[2].split(':')[0]
        req = urllib.request.Request(url, headers={'User-Agent': 'QGIS-RTH-Test/1.0'})
        if hostname in _SSL_NO_VERIFY:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            cm = urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx)  # nosec B310
        else:
            cm = urllib.request.urlopen(req, timeout=TIMEOUT)  # nosec B310
        with cm as r:
            text = r.read().decode('utf-8', errors='replace')
            return r.getcode(), text, time.monotonic() - t0, None
    except urllib.error.HTTPError as e:
        return e.code, None, time.monotonic() - t0, f'HTTP {e.code}: {e.reason}'
    except urllib.error.URLError as e:
        return None, None, time.monotonic() - t0, f'URLError: {e.reason}'
    except Exception as e:
        return None, None, time.monotonic() - t0, f'{type(e).__name__}: {e}'


def _count_wms_layers(text):
    """Count unique named WMS layers in GetCapabilities XML."""
    try:
        root = ET.fromstring(text)  # nosec B314
        ns = ''
        if root.tag.startswith('{'):
            ns = root.tag.split('}')[0] + '}'
        names = set()
        for elem in root.iter(f'{ns}Layer'):
            n = elem.find(f'{ns}Name')
            if n is not None and n.text and n.text.strip():
                names.add(n.text.strip())
        return len(names)
    except Exception:
        return -1


def _count_wfs_types(text):
    """Count FeatureType elements in WFS GetCapabilities XML."""
    try:
        root = ET.fromstring(text)  # nosec B314
        count = 0
        for elem in root.iter():
            local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if local == 'FeatureType':
                count += 1
        return count
    except Exception:
        return -1


def _count_wcs_coverages(text):
    """Count coverage identifiers in WCS GetCapabilities XML."""
    try:
        root = ET.fromstring(text)  # nosec B314
        count = 0
        for elem in root.iter():
            local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if local in ('CoverageSummary', 'CoverageId', 'Identifier',
                         'CoverageOfferingBrief'):
                count += 1
        return count
    except Exception:
        return -1


# ── Main test ─────────────────────────────────────────────────────────────────

def run_connectivity():
    print(SEP2)
    print('  RTH PROJECT — GeoBase Bulk Connectivity Test')
    print(f'  Catálogo: {os.path.abspath(_CATALOG)}')
    print(f'  Timeout por request: {TIMEOUT}s')
    print(SEP2)

    with open(_CATALOG, encoding='utf-8') as f:
        catalog = json.load(f)

    total   = len(catalog)
    results = []   # (descricao, svc, ok, code, elapsed, count, error)

    for idx, entry in enumerate(catalog, 1):
        desc = entry.get('descricao', '?')
        print(f'\n[{idx:02d}/{total}] {desc}')

        for svc, avail_key, cap_key, count_fn in (
            ('WMS', 'wmsAvailable', 'wmsGetCapabilities', _count_wms_layers),
            ('WFS', 'wfsAvailable', 'wfsGetCapabilities', _count_wfs_types),
            ('WCS', 'wcsAvailable', 'wcsGetCapabilities', _count_wcs_coverages),
        ):
            if not entry.get(avail_key):
                continue
            url = entry.get(cap_key) or ''
            if not url:
                print(f'  {svc}: ⚠  sem URL de GetCapabilities no catálogo')
                results.append((desc, svc, None, None, 0, 0, 'sem URL'))
                continue

            code, text, elapsed, err = _fetch(url)

            if err or code != 200:
                icon = '❌'
                count = 0
                detail = err or f'HTTP {code}'
                print(f'  {svc}: {icon} {detail}  ({elapsed:.1f}s)')
                results.append((desc, svc, False, code, elapsed, 0, detail))
            else:
                count = count_fn(text) if text else 0
                icon = '✅'
                print(f'  {svc}: {icon} HTTP {code}  {elapsed:.1f}s  '
                      f'{"camadas" if svc == "WMS" else "tipos" if svc == "WFS" else "coverages"}: {count}')
                results.append((desc, svc, True, code, elapsed, count, None))

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print(SEP2)
    print('  RESUMO')
    print(SEP2)

    for svc in ('WMS', 'WFS', 'WCS'):
        svc_results = [(ok, code, elapsed, count, err)
                       for (desc, s, ok, code, elapsed, count, err) in results
                       if s == svc]
        n_ok    = sum(1 for (ok, *_) in svc_results if ok)
        n_fail  = sum(1 for (ok, *_) in svc_results if ok is False)
        n_nourl = sum(1 for (ok, *_) in svc_results if ok is None)
        if not svc_results:
            continue
        print(f'\n{svc}: {n_ok} ok  /  {n_fail} falha  /  {n_nourl} sem URL')

    print()
    print('── Falhas ──')
    failures = [(desc, svc, code, elapsed, err)
                for (desc, svc, ok, code, elapsed, count, err) in results
                if ok is False]
    if not failures:
        print('  Nenhuma falha! ✅')
    else:
        for desc, svc, code, elapsed, err in failures:
            print(f'  ❌ [{svc}] {desc[:55]}  →  {err}  ({elapsed:.1f}s)')

    print()
    print('── Servidores lentos (> 8s) ──')
    slow = [(desc, svc, elapsed)
            for (desc, svc, ok, code, elapsed, count, err) in results
            if ok and elapsed > 8]
    if not slow:
        print('  Nenhum acima de 8s ✅')
    else:
        for desc, svc, elapsed in sorted(slow, key=lambda x: -x[2]):
            print(f'  ⏳ [{svc}] {desc[:55]}  {elapsed:.1f}s')

    print()
    print('── WCS com coverages reais (> 0) ──')
    wcs_with = [(desc, count)
                for (desc, svc, ok, code, elapsed, count, err) in results
                if svc == 'WCS' and ok and count > 0]
    if not wcs_with:
        print('  Nenhum WCS com coverages publicadas')
    else:
        for desc, count in sorted(wcs_with, key=lambda x: -x[1]):
            print(f'  📦 {desc[:55]}  {count} coverages')

    print()
    print(SEP2)
    print('  TESTE CONCLUÍDO')
    print(SEP2)


if __name__ == '__main__':
    run_connectivity()
