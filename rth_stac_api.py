# -*- coding: utf-8 -*-
"""
rth_stac_api — Funções de consulta à API STAC do INPE e Planetary Computer
rth_stac_api — INPE and Planetary Computer STAC API query functions

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Biblioteca padrão para serialização JSON / Standard library for JSON
import json
# Biblioteca padrão para requisições e erros HTTP / Standard library for HTTP requests and errors
import urllib.request
import urllib.error

# Módulos QGIS para CRS e transformação / QGIS modules for CRS and transform
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
)

# ── Endpoints STAC disponíveis ───────────────────────────────────────────────
# Brazil Data Cube — INPE (padrão / default)
STAC_BDC      = 'https://data.inpe.br/bdc/stac/v1'
# Microsoft Planetary Computer — cobertura global / global coverage
STAC_PC       = 'https://planetarycomputer.microsoft.com/api/stac/v1'
# AWS Element84 Earth Search — cobertura global / global coverage
STAC_ELEMENT84 = 'https://earth-search.aws.element84.com/v1'

# Compatibilidade com código legado / Backward compatibility with legacy code
STAC_BASE   = STAC_BDC
STAC_SEARCH = STAC_BDC + '/search'

# ── Roteamento de coleção → (endpoint, collection_id_real) ───────────────────
# IDs com sufixo '-aws' são aliases internos para o Element84
# IDs with '-aws' suffix are internal aliases for Element84
# Coleções não listadas usam BDC por padrão / Unlisted collections default to BDC
_COLLECTION_ROUTING = {
    # Microsoft Planetary Computer / Microsoft Planetary Computer
    'sentinel-2-l2a':      (STAC_PC,        'sentinel-2-l2a'),
    'landsat-c2-l2':       (STAC_PC,        'landsat-c2-l2'),
    # AWS Element84 Earth Search / AWS Element84 Earth Search
    'sentinel-2-l2a-aws':  (STAC_ELEMENT84, 'sentinel-2-l2a'),
}


def _route_for(collection_id):
    """Retorna (endpoint, real_collection_id) para a coleção / Return (endpoint, real_collection_id) for the collection.

    :param collection_id: ID interno da coleção (pode ter sufixo -aws) / Internal collection ID (may have -aws suffix)
    :returns: tupla (endpoint_url, real_id) / tuple (endpoint_url, real_id)
    :rtype: tuple[str, str]
    """
    if collection_id in _COLLECTION_ROUTING:
        return _COLLECTION_ROUTING[collection_id]
    # Padrão: BDC com o mesmo ID / Default: BDC with same ID
    return (STAC_BDC, collection_id)


# ── Prefixos para agrupamento de coleções por satélite ───────────────────────
# Ordem importa: CBERS-4A deve vir antes de CBERS-4 / Order matters: CBERS-4A must come before CBERS-4
_SAT_PREFIXES = [
    # 's2-' e 's2_' evitam capturar Sentinel-1 e Sentinel-3 / 's2-' and 's2_' avoid Sentinel-1 and Sentinel-3
    ('Sentinel-2',  ('s2-', 's2_', 'sentinel-2')),
    ('Landsat',     ('landsat', 'lc8', 'lc9', 'lc7')),
    ('Amazonia-1',  ('amz1',)),
    ('CBERS-4A',    ('cb4a', 'cbers4a')),
    ('CBERS-4',     ('cb4-', 'cb4_', 'cbers4-', 'cbers4_')),
    ('CBERS-2B',    ('cbers2b', 'cb2b')),
]


def get_bbox_from_canvas(iface):
    """Retorna [min_lon, min_lat, max_lon, max_lat] em WGS84 do canvas atual / Return [min_lon, min_lat, max_lon, max_lat] in WGS84 from current canvas.

    :param iface: interface QGIS / QGIS interface
    :returns: lista com as coordenadas bbox / list with bbox coordinates
    :rtype: list[float]
    """
    # CRS alvo: WGS84 / Target CRS: WGS84
    wgs84  = QgsCoordinateReferenceSystem('EPSG:4326')
    canvas = iface.mapCanvas()
    extent = canvas.extent()
    canvas_crs = canvas.mapSettings().destinationCrs()
    # Transforma para WGS84 se necessário / Transform to WGS84 if needed
    if canvas_crs != wgs84:
        transform = QgsCoordinateTransform(canvas_crs, wgs84, QgsProject.instance())
        extent = transform.transformBoundingBox(extent)
    # Retorna como lista arredondada / Return as rounded list
    return [
        round(extent.xMinimum(), 6),
        round(extent.yMinimum(), 6),
        round(extent.xMaximum(), 6),
        round(extent.yMaximum(), 6),
    ]


def search_stac(collection_id, bbox, date_ini, date_fim, cloud_max):
    """Faz requisição POST na API STAC e retorna features filtradas e ordenadas / Make POST to STAC API and return filtered, sorted features.

    :param collection_id: ID da coleção STAC / STAC collection ID
    :param bbox: [min_lon, min_lat, max_lon, max_lat] em WGS84
    :param date_ini: data inicial ISO 8601 / start date ISO 8601
    :param date_fim: data final ISO 8601 / end date ISO 8601
    :param cloud_max: limiar máximo de nuvens 0-100 / max cloud threshold 0-100
    :returns: lista de features GeoJSON / list of GeoJSON features
    :rtype: list[dict]
    """
    # Roteia para o endpoint correto ANTES de montar o payload / Route to correct endpoint BEFORE building the payload
    # Necessário para usar o ID real da coleção (ex: 'sentinel-2-l2a' em vez do alias 'sentinel-2-l2a-aws')
    # Necessary to use the real collection ID (e.g. 'sentinel-2-l2a' instead of alias 'sentinel-2-l2a-aws')
    endpoint, real_id = _route_for(collection_id)
    search_url        = endpoint + '/search'

    # Monta o corpo da requisição com o ID real / Build request body with the real collection ID
    payload = {
        'collections': [real_id],
        'bbox':        bbox,
        'datetime':    '{}/{}'.format(date_ini, date_fim),
        'limit':       100,
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        search_url,
        data=data,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
        method='POST',
    )

    # Valida o esquema da URL antes de abrir / Validate URL scheme before opening
    if not req.full_url.startswith(('https://', 'http://')):
        raise ValueError('URL scheme not permitted: {}'.format(req.full_url))
    # Executa com timeout de 30 s / Execute with 30 s timeout
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
        result = json.loads(resp.read().decode('utf-8'))

    features = result.get('features', [])

    # Filtra pelo limiar de nuvens — `or 0` evita NoneType quando o valor é null
    # Filter by cloud threshold — `or 0` avoids NoneType when value is null
    if cloud_max < 100:
        features = [
            f for f in features
            if (f.get('properties', {}).get('eo:cloud_cover') or 0) <= cloud_max
        ]

    # Ordena por data decrescente (mais recente primeiro) / Sort descending by date (newest first)
    features.sort(
        key=lambda f: f.get('properties', {}).get('datetime', ''),
        reverse=True,
    )

    return features


def fetch_stac_catalog():
    """Busca todas as coleções da API BDC STAC e as agrupa por satélite / Fetch all collections from BDC STAC API grouped by satellite.

    :returns: dicionário {satélite: [(id, título)]} / dict {satellite: [(id, title)]}
    :rtype: dict[str, list[tuple[str, str]]]
    :raises urllib.error.URLError: em falha de rede / on network failure
    """
    url = STAC_BASE + '/collections'
    if not url.startswith(('https://', 'http://')):
        raise ValueError('URL scheme not permitted: {}'.format(url))
    with urllib.request.urlopen(url, timeout=15) as resp:  # nosec B310
        data = json.loads(resp.read().decode('utf-8'))

    # Resposta pode ser {"collections": [...]} ou diretamente [...] / Response can be {"collections":[...]} or [...]
    raw = data.get('collections', data) if isinstance(data, dict) else data

    # Agrupa por satélite usando os prefixos definidos / Group by satellite using defined prefixes
    grouped = {}
    for coll in raw:
        coll_id = coll.get('id', '')
        title   = coll.get('title', coll_id)
        cl      = coll_id.lower()

        sat = 'Outros / Others'
        for satellite, prefixes in _SAT_PREFIXES:
            if any(cl.startswith(p) for p in prefixes):
                sat = satellite
                break

        grouped.setdefault(sat, []).append((coll_id, title))

    # Ordena coleções dentro de cada satélite / Sort collections within each satellite
    for sat in grouped:
        grouped[sat].sort(key=lambda x: x[0])

    return grouped


def fetch_collection_detail(collection_id):
    """Busca os metadados detalhados de uma coleção, incluindo eo:bands / Fetch detailed metadata for a collection, including eo:bands.

    :param collection_id: ID da coleção / Collection ID
    :returns: dicionário com metadados da coleção / collection metadata dict
    :rtype: dict
    :raises urllib.error.URLError: em falha de rede / on network failure
    """
    # Roteia para o endpoint correto e resolve o ID real / Route to correct endpoint and resolve real ID
    endpoint, real_id = _route_for(collection_id)
    url = '{}/collections/{}'.format(endpoint, real_id)
    if not url.startswith(('https://', 'http://')):
        raise ValueError('URL scheme not permitted: {}'.format(url))
    with urllib.request.urlopen(url, timeout=10) as resp:  # nosec B310
        return json.loads(resp.read().decode('utf-8'))
